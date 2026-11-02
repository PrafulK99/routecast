import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import App from './App'
import { hourLabel } from './heatmap/data'
import {
  type AnalyzeCall,
  type HeatmapCall,
  apiError,
  callsTo,
  deferred,
  heatmapResponse,
  installFetch,
  jsonResponse,
  renderWithClient,
  submitTrip,
  threeRouteAnalysis,
} from './test/helpers'

// The real map needs WebGL, which jsdom does not have; a stand-in shows what App passes it.
vi.mock('./components/MapView', async () => {
  const { createElement } = await import('react')
  return {
    default: (props: {
      analysis?: { meta: { request_id: string } }
      selectedRouteId?: string
      onSelectRoute: (id: string) => void
    }) =>
      createElement(
        'div',
        {
          'data-testid': 'map',
          'data-analysis': props.analysis?.meta.request_id ?? '',
          'data-selected': props.selectedRouteId ?? '',
        },
        createElement('button', { onClick: () => props.onSelectRoute('route-1') }, 'Map: pick Route A'),
      ),
  }
})

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
const map = () => screen.findByTestId('map')
const cardList = () => screen.findByRole('list', { name: 'Routes' })
const cards = async () => within(await cardList()).getAllByRole('button')
const card = async (label: string) => (await cards()).find((c) => c.textContent?.includes(label))!

async function startApp(
  analyze?: (call: AnalyzeCall) => Response | Promise<Response>,
  heatmap?: (call: HeatmapCall) => Response | Promise<Response>,
) {
  const fetchMock = installFetch(analyze, heatmap)
  renderWithClient(<App />)
  await map()
  return fetchMock
}

describe('page load', () => {
  test('quietly pings /api/health to wake a sleeping server', async () => {
    const fetchMock = await startApp()

    const pings = callsTo(fetchMock, '/api/health')
    expect(pings).toHaveLength(1)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  test('starts idle: a hint, no cards, a map with no analysis', async () => {
    await startApp()

    expect(screen.getByText(/Enter a trip to compare three routes/)).toBeTruthy()
    expect(screen.queryByRole('list', { name: 'Routes' })).toBeNull()
    expect((await map()).dataset.analysis).toBe('')
  })

  test('has the Open-Meteo credit linking to open-meteo.com', async () => {
    await startApp()

    const link = screen.getByRole('link', { name: 'Weather data by Open-Meteo.com' })
    expect(link.getAttribute('href')).toBe('https://open-meteo.com/')
  })

  test('does not call the API while the form is invalid', async () => {
    const fetchMock = await startApp()

    fireEvent.click(screen.getByRole('button', { name: 'Analyze routes' }))

    expect(callsTo(fetchMock, '/api/analyze')).toHaveLength(0)
    expect(screen.getByText('Choose a starting point from the suggestions.')).toBeTruthy()
  })
})

describe('a successful analysis', () => {
  test('posts the trip and shows three route cards with one Recommended badge', async () => {
    const fetchMock = await startApp()

    await submitTrip()
    await cardList()

    const [url, init] = callsTo(fetchMock, '/api/analyze')[0]
    expect(String(url)).toMatch(/\/api\/analyze$/)
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toMatchObject({
      origin: { label: 'Dallas, Texas, United States' },
      destination: { label: 'Chicago, Illinois, United States' },
      load_weight_lb: 40000,
      checkpoint_interval_miles: 25,
    })
    expect(await cards()).toHaveLength(3)
    expect(screen.getAllByText('Recommended')).toHaveLength(1)
    expect(within(await card('Route B')).getByText('Recommended')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Recommended: Route B' })).toBeTruthy()
    for (const reason of threeRouteAnalysis().recommendation.reasons) {
      expect(screen.getByText(reason)).toBeTruthy()
    }
  })

  test('hands the analysis to the map with the recommended route selected', async () => {
    await startApp()

    await submitTrip()
    await cardList()

    expect((await map()).dataset).toMatchObject({ analysis: 'req-1', selected: 'route-2' })
    expect((await card('Route B')).getAttribute('aria-pressed')).toBe('true')
  })

  test('clicking a card, or a route on the map, selects it', async () => {
    await startApp()
    await submitTrip()
    await cardList()

    fireEvent.click(await card('Route C'))
    expect((await map()).dataset.selected).toBe('route-3')
    expect((await card('Route C')).getAttribute('aria-pressed')).toBe('true')
    expect((await card('Route B')).getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(screen.getByRole('button', { name: 'Map: pick Route A' }))
    expect((await map()).dataset.selected).toBe('route-1')
    expect((await card('Route A')).getAttribute('aria-pressed')).toBe('true')
  })

  test('a new analysis starts again on its recommended route', async () => {
    let count = 0
    await startApp(() => jsonResponse(threeRouteAnalysis(`req-${++count}`)))
    await submitTrip()
    await cardList()
    fireEvent.click(await card('Route C'))
    expect((await map()).dataset.selected).toBe('route-3')

    fireEvent.click(screen.getByRole('button', { name: 'Analyze routes' }))
    await act(async () => {})

    await vi.waitFor(() => expect(screen.getByTestId('map').dataset).toMatchObject({ analysis: 'req-2', selected: 'route-2' }))
  })
})

describe('loading', () => {
  test('shows a skeleton while the analysis runs, then the cards', async () => {
    const reply = deferred<Response>()
    await startApp(() => reply.promise)

    await submitTrip()

    expect(await screen.findByText('Analyzing routes…')).toBeTruthy()
    expect(document.querySelectorAll('.skeleton')).toHaveLength(3)
    expect(screen.queryByRole('list', { name: 'Routes' })).toBeNull()

    await act(async () => reply.resolve(jsonResponse(threeRouteAnalysis())))

    expect(await cards()).toHaveLength(3)
    expect(document.querySelectorAll('.skeleton')).toHaveLength(0)
  })

  test('after 5 seconds says the server is waking up, and stops saying it when done', async () => {
    const reply = deferred<Response>()
    await startApp(() => reply.promise)
    await submitTrip()
    await screen.findByText('Analyzing routes…')

    await advance(4_900)
    expect(screen.queryByText(/Waking the server/)).toBeNull()

    await advance(200)
    expect(screen.getByText('Waking the server, this can take up to a minute')).toBeTruthy()

    await act(async () => reply.resolve(jsonResponse(threeRouteAnalysis())))
    await cardList()
    expect(screen.queryByText(/Waking the server/)).toBeNull()
  })

  test('a fast reply never shows the waking message', async () => {
    await startApp()

    await submitTrip()
    await cardList()
    await advance(10_000)

    expect(screen.queryByText(/Waking the server/)).toBeNull()
  })
})

describe('recommendation banner', () => {
  test('shows a prominent warning when every route is blocked', async () => {
    const blocked = threeRouteAnalysis()
    blocked.recommendation.all_blocked = true
    blocked.recommendation.reasons = [
      'Every route has No Travel conditions. Route C has the fewest (40 miles); do not treat it as a safe route.',
      'Route C has 40 No Travel miles against 55 on Route A.',
    ]
    for (const route of blocked.routes) route.summary.blocked = true
    await startApp(() => jsonResponse(blocked))

    await submitTrip()
    await cardList()

    const alert = screen.getByText(/No safe route: every route has No Travel conditions/).closest('[role="alert"]')!
    expect(alert.textContent).toContain('Do not treat the recommended route as safe')
    expect(screen.getByRole('heading', { name: /Least blocked route/ })).toBeTruthy()
    expect(screen.getByText(blocked.recommendation.reasons[0])).toBeTruthy()
    expect(screen.getAllByText('Blocked')).toHaveLength(3)
  })

  test('has no such warning for a normal recommendation', async () => {
    await startApp()

    await submitTrip()
    await cardList()

    expect(screen.queryByText(/No safe route/)).toBeNull()
    expect(screen.queryByText('Blocked')).toBeNull()
  })

  test('lists meta warnings, open when the results are partial', async () => {
    const partial = threeRouteAnalysis()
    partial.meta.warnings = ['Route B has forecast data for 68% of its length; the rest could not be scored.']
    partial.routes[1].summary.coverage_pct = 68.75
    await startApp(() => jsonResponse(partial))

    await submitTrip()
    await cardList()

    const details = document.querySelector('details.warnings') as HTMLDetailsElement
    expect(details.open).toBe(true)
    expect(within(details).getByText('Partial results: 1 warning')).toBeTruthy()
    expect(within(details).getByText(partial.meta.warnings[0])).toBeTruthy()
  })

  test('keeps warnings collapsed when coverage is complete, and omits the list when there are none', async () => {
    const calm = threeRouteAnalysis()
    calm.meta.warnings = ['Checkpoint interval raised from 10 to 25 miles so each route stays within 150 checkpoints.', 'Another note.']
    for (const route of calm.routes) route.summary.coverage_pct = 100
    await startApp(() => jsonResponse(calm))
    await submitTrip()
    await cardList()

    const details = document.querySelector('details.warnings') as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(within(details).getByText('2 warnings')).toBeTruthy()

    fireEvent.click(within(details).getByText('2 warnings')) // jsdom toggles <details> on summary click
    expect(details.open).toBe(true)
  })

  test('shows no warnings list when the analysis has none', async () => {
    const none = threeRouteAnalysis()
    none.meta.warnings = []
    for (const route of none.routes) route.summary.coverage_pct = 100
    await startApp(() => jsonResponse(none))

    await submitTrip()
    await cardList()

    expect(document.querySelector('details.warnings')).toBeNull()
  })
})

describe('errors', () => {
  const REQUEST_ID = /Request id: req-test/

  test.each([
    [400, 'validation_error', 'Some fields are invalid.', /The server rejected some of the trip details/],
    [422, 'no_route', 'No drivable route was found between these points.', /No drivable route was found between these two places/],
    [422, 'route_too_long', 'The longest route is 3200 miles...', /too long to analyze/],
    [502, 'routing_unavailable', 'Mapbox did not respond after one retry.', /routing service is not responding/],
    [502, 'weather_unavailable', 'The weather service failed for every location.', /could not provide a forecast/],
    [503, 'weather_rate_limited', 'The weather service is rate limited; try again in a minute.', /rate limited; try again in a minute\./],
    [503, 'weather_rate_limited', 'The weather service is rate limited; try again later.', /rate limited; try again later\./],
    [429, 'rate_limited', 'Too many requests. Try again in 12 seconds.', /Too many requests\. Try again in 12 seconds\./],
    [500, 'internal_error', 'Something went wrong on our side.', /Something went wrong on our side\. Please try again\./],
    [500, 'something_new', 'x', /Something unexpected happened \(something_new\)/],
  ])('%s %s shows its message and a Try again button', async (status, code, serverMessage, expected) => {
    await startApp(() => apiError(status as number, code as string, serverMessage as string))

    await submitTrip()

    const alert = await screen.findByText(expected as RegExp)
    expect(alert.closest('[role="alert"]')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
    expect(screen.getByText(REQUEST_ID)).toBeTruthy()
    expect(screen.queryByRole('list', { name: 'Routes' })).toBeNull()
  })

  test('validation errors list the fields the server complained about', async () => {
    await startApp(() => apiError(400, 'validation_error', 'Some fields are invalid.', { 'origin.lat': ['Ensure this value is less than or equal to 90.'] }))

    await submitTrip()

    expect(await screen.findByText('origin lat: Ensure this value is less than or equal to 90.')).toBeTruthy()
  })

  test('a reply that is not our error format still gets a message and a retry', async () => {
    await startApp(() => new Response('<html>Bad gateway</html>', { status: 502 }))

    await submitTrip()

    expect(await screen.findByText(/Something unexpected happened/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  test('a network failure says the server cannot be reached', async () => {
    await startApp(() => Promise.reject(new TypeError('Failed to fetch')))

    await submitTrip()

    expect(await screen.findByText(/Can't reach the server/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  test('gives up after 90 seconds', async () => {
    await startApp(({ signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))))
    await submitTrip()
    await screen.findByText('Analyzing routes…')

    await advance(89_000)
    expect(screen.queryByText(/did not answer within 90 seconds/)).toBeNull()

    await advance(2_000)
    expect(await screen.findByText(/did not answer within 90 seconds/)).toBeTruthy()
  })

  test('Try again sends the same trip again', async () => {
    const replies = [apiError(502, 'routing_unavailable', 'down'), jsonResponse(threeRouteAnalysis())]
    const bodies: unknown[] = []
    await startApp(({ request }) => {
      bodies.push(request)
      return replies.shift()!
    })
    await submitTrip()
    fireEvent.click(await screen.findByRole('button', { name: 'Try again' }))

    expect(await cards()).toHaveLength(3)
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]).toEqual(bodies[0])
  })
})

describe('overlapping requests', () => {
  test('a new analysis cancels the one in flight, and a late reply cannot replace newer results', async () => {
    const first = deferred<Response>()
    const second = deferred<Response>()
    const calls: AnalyzeCall[] = []
    await startApp((call) => {
      calls.push(call)
      return (calls.length === 1 ? first : second).promise
    })
    await submitTrip()
    await vi.waitFor(() => expect(calls).toHaveLength(1))

    fireEvent.click(screen.getByRole('button', { name: 'Analyze routes' }))
    await vi.waitFor(() => expect(calls).toHaveLength(2))

    expect(calls[0].signal.aborted).toBe(true)
    expect(calls[1].signal.aborted).toBe(false)

    await act(async () => second.resolve(jsonResponse(threeRouteAnalysis('req-new'))))
    await cardList()
    expect((await map()).dataset.analysis).toBe('req-new')

    // The cancelled request's reply arrives afterwards (as if the browser ignored the abort).
    await act(async () => first.resolve(jsonResponse(threeRouteAnalysis('req-old'))))
    await advance(100)

    expect((await map()).dataset.analysis).toBe('req-new')
    expect(await cards()).toHaveLength(3)
  })
})

describe('weather heatmap', () => {
  const heatmapRegion = () => screen.findByRole('region', { name: 'Weather heatmap' })
  const heatmapSlider = () => screen.findByRole('slider', { name: 'Hours after departure' })
  const labelText = () => (document.querySelector('.heatmap-label')?.textContent ?? '').replace(/\s/g, ' ')

  test('is requested once after the analysis, with its corridor points, departure time and load', async () => {
    const analyzeCalls: AnalyzeCall[] = []
    const heatmapCalls: HeatmapCall[] = []
    const fetchMock = await startApp(
      (call) => {
        analyzeCalls.push(call)
        return jsonResponse(threeRouteAnalysis())
      },
      (call) => {
        heatmapCalls.push(call)
        return jsonResponse(heatmapResponse())
      },
    )

    await submitTrip()
    await heatmapSlider()

    expect(callsTo(fetchMock, '/api/heatmap')).toHaveLength(1)
    const [url, init] = callsTo(fetchMock, '/api/heatmap')[0]
    expect(String(url)).toMatch(/\/api\/heatmap$/)
    expect(init?.method).toBe('POST')
    expect(heatmapCalls[0].request).toEqual({
      points: threeRouteAnalysis().corridor_points,
      departure_time: analyzeCalls[0].request.departure_time,
      load_weight_lb: 40000,
    })
  })

  test('the route results never wait for it: cards show while the heatmap is still loading', async () => {
    const reply = deferred<Response>()
    await startApp(undefined, () => reply.promise)

    await submitTrip()

    expect(await cards()).toHaveLength(3)
    expect((await map()).dataset.analysis).toBe('req-1')
    expect(within(await heatmapRegion()).getByText(/Loading weather heatmap/)).toBeTruthy()
    expect(screen.queryByRole('slider')).toBeNull()

    await act(async () => reply.resolve(jsonResponse(heatmapResponse())))

    expect(await heatmapSlider()).toBeTruthy()
    expect(screen.queryByText(/Loading weather heatmap/)).toBeNull()
  })

  test('shows the slider with the first hour of the response and the load note', async () => {
    await startApp()

    await submitTrip()
    await heatmapSlider()

    expect(labelText()).toBe(hourLabel(heatmapResponse().start_hour, 0).replace(/\s/g, ' '))
    expect(screen.getByText(/Risk shown is for your load weight of 40,000 lb/)).toBeTruthy()
  })

  test('a failure shows a message and Retry while the routes stay usable; Retry loads it', async () => {
    const replies = [apiError(502, 'weather_unavailable', 'down'), jsonResponse(heatmapResponse())]
    const calls: HeatmapCall[] = []
    await startApp(undefined, (call) => {
      calls.push(call)
      return replies.shift()!
    })

    await submitTrip()

    const alert = await within(await heatmapRegion()).findByRole('alert')
    expect(alert.textContent).toContain('Weather heatmap unavailable')
    expect(await cards()).toHaveLength(3) // the routes are unaffected
    fireEvent.click(await card('Route A')) // and still selectable
    expect((await map()).dataset.selected).toBe('route-1')

    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))

    expect(await heatmapSlider()).toBeTruthy()
    expect(calls).toHaveLength(2)
    expect(screen.queryByText(/Weather heatmap unavailable/)).toBeNull()
  })

  test('a network failure of the heatmap is reported the same way', async () => {
    await startApp(undefined, () => Promise.reject(new TypeError('Failed to fetch')))

    await submitTrip()

    expect((await within(await heatmapRegion()).findByRole('alert')).textContent).toContain("Can't reach the server")
    expect(await cards()).toHaveLength(3)
  })

  test('a new analysis cancels the heatmap request in flight, and its late reply is ignored', async () => {
    const first = deferred<Response>()
    const second = deferred<Response>()
    const calls: HeatmapCall[] = []
    let analyses = 0
    await startApp(
      () => jsonResponse(threeRouteAnalysis(`req-${++analyses}`)),
      (call) => {
        calls.push(call)
        return (calls.length === 1 ? first : second).promise
      },
    )
    await submitTrip()
    await vi.waitFor(() => expect(calls).toHaveLength(1))

    fireEvent.click(screen.getByRole('button', { name: 'Analyze routes' }))
    await vi.waitFor(() => expect(calls).toHaveLength(2))

    expect(calls[0].signal.aborted).toBe(true)
    expect(calls[1].signal.aborted).toBe(false)

    await act(async () => second.resolve(jsonResponse({ ...heatmapResponse(), start_hour: '2026-11-02T20:00:00Z' })))
    await heatmapSlider()
    // The cancelled request's reply arrives afterwards, as if the browser had ignored the abort.
    await act(async () => first.resolve(jsonResponse({ ...heatmapResponse(), start_hour: '2026-11-03T08:00:00Z' })))
    await advance(100)

    expect(labelText()).toBe(hourLabel('2026-11-02T20:00:00Z', 0).replace(/\s/g, ' '))
    expect((await map()).dataset.analysis).toBe('req-2')
  })

  test('a new analysis starts the slider at +0 h again', async () => {
    let analyses = 0
    await startApp(() => jsonResponse(threeRouteAnalysis(`req-${++analyses}`)))
    await submitTrip()
    fireEvent.change(await heatmapSlider(), { target: { value: '12' } })
    await advance(50)
    expect(labelText()).toContain('(+12 h)')

    fireEvent.click(screen.getByRole('button', { name: 'Analyze routes' }))
    await vi.waitFor(() => expect(labelText()).toContain('(+0 h)'))
    expect((await heatmapSlider() as HTMLInputElement).value).toBe('0')
  })

  test('no corridor points means no request and a plain message', async () => {
    const empty = threeRouteAnalysis()
    empty.corridor_points = []
    const fetchMock = await startApp(() => jsonResponse(empty))

    await submitTrip()
    await cards()

    expect(callsTo(fetchMock, '/api/heatmap')).toHaveLength(0)
    expect(within(await heatmapRegion()).getByText(/No corridor points/)).toBeTruthy()
    expect(screen.queryByRole('slider')).toBeNull()
  })

  test('an empty heatmap response shows the same message', async () => {
    await startApp(undefined, () => jsonResponse({ ...heatmapResponse(), points: [] }))

    await submitTrip()

    expect(await within(await heatmapRegion()).findByText(/No corridor points/)).toBeTruthy()
    expect(await cards()).toHaveLength(3)
  })

  test('is not requested when the analysis fails', async () => {
    const fetchMock = await startApp(() => apiError(422, 'no_route', 'none'))

    await submitTrip()
    await screen.findByText(/No drivable route was found/)

    expect(callsTo(fetchMock, '/api/heatmap')).toHaveLength(0)
    expect(screen.queryByRole('region', { name: 'Weather heatmap' })).toBeNull()
  })
})

describe('hardening', () => {
  const HOUR = 3_600_000
  const heatmapRegion = () => screen.findByRole('region', { name: 'Weather heatmap' })
  const startWithFailingHeatmap = async () => {
    const analyzeCalls: AnalyzeCall[] = []
    const heatmapCalls: HeatmapCall[] = []
    const replies = [apiError(502, 'weather_unavailable', 'down'), jsonResponse(heatmapResponse())]
    await startApp(
      (call) => {
        analyzeCalls.push(call)
        return jsonResponse(threeRouteAnalysis())
      },
      (call) => {
        heatmapCalls.push(call)
        return replies.shift()!
      },
    )
    await submitTrip()
    const alert = await within(await heatmapRegion()).findByRole('alert')
    return { analyzeCalls, heatmapCalls, alert }
  }

  test('a heatmap Retry after the departure hour has passed uses the next full hour and says so', async () => {
    const { analyzeCalls, heatmapCalls, alert } = await startWithFailingHeatmap()
    const departure = analyzeCalls[0].request.departure_time // the next full hour when the form was filled
    expect(heatmapCalls[0].request.departure_time).toBe(departure) // the first request was on time

    // Two hours and ten minutes later the original departure hour is long gone.
    vi.setSystemTime(Date.parse(departure) + 2 * HOUR + 10 * 60_000)
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))

    await screen.findByRole('slider', { name: 'Hours after departure' })
    expect(heatmapCalls).toHaveLength(2)
    expect(heatmapCalls[1].request.departure_time).toBe(new Date(Date.parse(departure) + 3 * HOUR).toISOString())
    expect(heatmapCalls[1].request.points).toEqual(heatmapCalls[0].request.points)
    expect(heatmapCalls[1].request.load_weight_lb).toBe(heatmapCalls[0].request.load_weight_lb)
    expect(screen.getByText(/The original departure time has passed, so the heatmap starts at/)).toBeTruthy()
  })

  test('a heatmap Retry made in time sends the original departure and shows no note', async () => {
    const { analyzeCalls, heatmapCalls, alert } = await startWithFailingHeatmap()

    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))

    await screen.findByRole('slider', { name: 'Hours after departure' })
    expect(heatmapCalls[1].request.departure_time).toBe(analyzeCalls[0].request.departure_time)
    expect(screen.queryByText(/original departure time has passed/)).toBeNull()
  })

  test('a cancelled request shows nothing: no error, no message, only the newer result', async () => {
    const second = deferred<Response>()
    let calls = 0
    await startApp(({ signal }) => {
      calls++
      if (calls === 1) {
        return new Promise((_, reject) =>
          signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))),
        )
      }
      return second.promise
    })
    await submitTrip()
    await vi.waitFor(() => expect(calls).toBe(1))

    fireEvent.click(screen.getByRole('button', { name: 'Analyze routes' })) // cancels the first
    await vi.waitFor(() => expect(calls).toBe(2))
    await advance(200)

    expect(screen.queryByRole('alert')).toBeNull()
    expect(document.querySelector('.error-panel')).toBeNull()
    expect(screen.queryByText(/Can't reach the server|Something unexpected|Try again/)).toBeNull()

    await act(async () => second.resolve(jsonResponse(threeRouteAnalysis('req-2'))))
    expect(await cards()).toHaveLength(3)
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
