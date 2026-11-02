import { act, fireEvent, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import App, { WAKING_AFTER_MS } from './App'
import { analyzeSample } from './api/fixtures/check'
import {
  type AnalyzeCall,
  callsTo,
  deferred,
  heatmapResponse,
  installFetch,
  jsonResponse,
  openMeteoBody,
  planResponse,
  renderWithClient,
  submitTrip,
  threeRouteAnalysis,
} from './test/helpers'

// The real map needs WebGL, which jsdom does not have.
vi.mock('./components/MapView', () => ({ default: () => null }))

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0) })
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

type Handlers = NonNullable<Parameters<typeof installFetch>[2]>

async function start(handlers: Handlers = {}, analyze?: (call: AnalyzeCall) => Response | Promise<Response>) {
  const fetchMock = installFetch(analyze, undefined, handlers)
  renderWithClient(<App />)
  return fetchMock
}

const openMeteoUrls = (fetchMock: ReturnType<typeof installFetch>) =>
  callsTo(fetchMock, 'api.open-meteo.com').map(([input]) => new URL(String(input)))

describe('the three-step flow', () => {
  test('shows Planning routes, Fetching weather, then Scoring routes, and then the results', async () => {
    const plan = deferred<Response>()
    const weather = deferred<Response>()
    const analysis = deferred<Response>()
    await start({ plan: () => plan.promise, weather: () => weather.promise }, () => analysis.promise)

    await submitTrip()
    expect(await screen.findByText('Planning routes…')).toBeTruthy()

    plan.resolve(jsonResponse(planResponse()))
    await flush()
    expect(screen.getByText('Fetching weather…')).toBeTruthy()

    weather.resolve(jsonResponse(openMeteoBody(new URL('https://x/?latitude=32.8,41.9&longitude=-96.8,-87.6'))))
    await flush()
    expect(screen.getByText('Scoring routes…')).toBeTruthy()

    analysis.resolve(jsonResponse(threeRouteAnalysis()))
    expect(await screen.findByRole('list', { name: 'Routes' })).toBeTruthy()
    expect(screen.queryByText('Scoring routes…')).toBeNull()
  })

  test('analyze carries the fetched weather for exactly the cells /api/plan named, and the server fetches none', async () => {
    const calls: AnalyzeCall[] = []
    const fetchMock = await start({}, (call) => {
      calls.push(call)
      return jsonResponse(threeRouteAnalysis())
    })

    await submitTrip()
    await screen.findByRole('list', { name: 'Routes' })

    const { weather } = calls[0].request
    expect(weather?.map((cell) => [cell.lat, cell.lon])).toEqual(planResponse().cells)
    expect(callsTo(fetchMock, '/api/plan')).toHaveLength(1)
    expect(JSON.parse(String(callsTo(fetchMock, '/api/plan')[0][1]?.body)).weather).toBeUndefined()
  })

  test('the waking message still appears when the server is slow to plan', async () => {
    const plan = deferred<Response>()
    await start({ plan: () => plan.promise })

    await submitTrip()
    await advance(WAKING_AFTER_MS)

    expect(screen.getByText(/Waking the server/)).toBeTruthy()
  })
})

describe('weather failures', () => {
  test.each([
    ['Minutely API request limit exceeded. Please try again in one minute.', /per-minute limit/],
    ['Hourly API request limit exceeded. Please try again in the next hour.', /hourly weather limit/],
    ['Daily API request limit exceeded. Please try again tomorrow.', /daily weather limit.*midnight UTC/],
  ])('a 429 "%s" shows its own message and a retry button', async (reason, message) => {
    let limited = true
    const fetchMock = await start({
      weather: (url) =>
        limited ? jsonResponse({ error: true, reason }, 429) : jsonResponse(openMeteoBody(url)),
    })

    await submitTrip()
    expect((await screen.findByRole('alert')).textContent).toMatch(message)
    expect(callsTo(fetchMock, '/api/analyze')).toHaveLength(0) // never scored without weather

    limited = false
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('list', { name: 'Routes' })).toBeTruthy()
  })

  test('a weather service that cannot be reached says so, with a retry button', async () => {
    await start({ weather: () => jsonResponse({}, 500) })

    await submitTrip()

    expect((await screen.findByRole('alert')).textContent).toMatch(/weather service could not be reached/)
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })
})

describe('cancelling stale work', () => {
  test('a new submission aborts the Open-Meteo request still in flight, and its late reply is ignored', async () => {
    const signals: AbortSignal[] = []
    const late = deferred<Response>()
    let first = true
    await start({
      weather: (url, signal) => {
        signals.push(signal)
        if (first) {
          first = false
          return late.promise
        }
        return jsonResponse(openMeteoBody(url))
      },
    })

    await submitTrip()
    await flush()
    expect(signals).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'Analyze routes' }))
    await screen.findByRole('list', { name: 'Routes' })

    expect(signals[0].aborted).toBe(true)
    late.resolve(jsonResponse(openMeteoBody(new URL('https://x/?latitude=32.8&longitude=-96.8'))))
    await flush()
    expect(screen.getAllByRole('list', { name: 'Routes' })).toHaveLength(1)
  })
})

describe('the heatmap weather', () => {
  test('fetches only the corridor cells not already held from the route weather, by exact coordinates', async () => {
    const corridor = analyzeSample.corridor_cells
    const routeCells = corridor.slice(0, 2) // pretend the routes already used these two cells
    const fetchMock = await start({
      plan: () => jsonResponse({ ...planResponse(), cells: routeCells }),
    })

    await submitTrip()
    await screen.findByRole('list', { name: 'Routes' })
    await vi.waitFor(() => expect(openMeteoUrls(fetchMock)).toHaveLength(2)) // routes, then heatmap

    const [routes, heatmap] = openMeteoUrls(fetchMock)
    expect(routes.searchParams.get('latitude')).toBe(routeCells.map(([lat]) => lat).join(','))
    const rest = corridor.slice(2)
    expect(heatmap.searchParams.get('latitude')).toBe(rest.map(([lat]) => lat).join(','))
    expect(heatmap.searchParams.get('longitude')).toBe(rest.map(([, lon]) => lon).join(','))
  })

  test('sends the weather it fetched with /api/heatmap', async () => {
    const bodies: unknown[] = []
    const fetchMock = installFetch(undefined, (call) => {
      bodies.push(call.request)
      return jsonResponse(heatmapResponse())
    })
    renderWithClient(<App />)

    await submitTrip()
    await screen.findByRole('list', { name: 'Routes' })
    await vi.waitFor(() => expect(bodies).toHaveLength(1))

    expect((bodies[0] as { weather: unknown[] }).weather).toHaveLength(analyzeSample.corridor_cells.length)
    expect(callsTo(fetchMock, '/api/heatmap')).toHaveLength(1)
  })
})
