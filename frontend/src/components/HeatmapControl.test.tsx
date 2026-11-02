import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { Profiler } from 'react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import { heatmapSample } from '../api/fixtures/check'
import { HeatmapController } from '../heatmap/controller'
import { heatmapToGeoJson } from '../heatmap/data'
import { RISK_LEVELS } from '../risk/levels'
import { HeatmapControl } from './HeatmapControl'

// The sample starts 2026-11-02 14:00 UTC. Phoenix is UTC-7 all year (no daylight saving),
// so every +1 h step is exactly one hour on the local clock: 7:00 AM MST at +0 h.
const PHOENIX = { timeZone: 'America/Phoenix', locale: 'en-US' }
const data = heatmapToGeoJson(heatmapSample)
const FRAME = 20 // longer than one animation frame (16 ms)
const plain = (text: string | null) => (text ?? '').replace(/\s/g, ' ')

beforeEach(() =>
  vi.useFakeTimers({
    toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'requestAnimationFrame', 'cancelAnimationFrame'],
  }),
)
afterEach(() => vi.useRealTimers())

function setup(overrides: Partial<React.ComponentProps<typeof HeatmapControl>> = {}) {
  const controller = new HeatmapController()
  const setHour = vi.spyOn(controller, 'setHour')
  let renders = 0
  const props = {
    data,
    loading: false,
    error: null,
    noPoints: false,
    onRetry: vi.fn(),
    controller,
    visible: true,
    onToggleVisible: vi.fn(),
    loadWeight: 45_000,
    time: PHOENIX,
    ...overrides,
  }
  const view = render(
    <Profiler id="control" onRender={() => renders++}>
      <HeatmapControl {...props} />
    </Profiler>,
  )
  return { ...view, props, setHour, renders: () => renders }
}

const slider = () => screen.getByRole('slider', { name: 'Hours after departure' }) as HTMLInputElement
const playButton = () => screen.getByRole('button', { name: /Play|Pause/ })
const label = () => plain(document.querySelector('.heatmap-label')!.textContent)
const frame = () => act(() => { vi.advanceTimersByTime(FRAME) })
const tick = (ms: number) => act(() => { vi.advanceTimersByTime(ms) })
const dragTo = (hour: number) => fireEvent.change(slider(), { target: { value: String(hour) } })

describe('slider and label', () => {
  test('runs from 0 to 48 in whole hours', () => {
    setup()

    expect(slider().min).toBe('0')
    expect(slider().max).toBe('48')
    expect(slider().step).toBe('1')
    expect(slider().value).toBe('0')
  })

  test('labels the selected hour in local time with the zone and +N h', () => {
    setup()
    expect(label()).toBe('Nov 2, 7:00 AM MST (+0 h)')

    for (const [hour, expected] of [
      [1, 'Nov 2, 8:00 AM MST (+1 h)'],
      [17, 'Nov 3, 12:00 AM MST (+17 h)'], // across local midnight
      [24, 'Nov 3, 7:00 AM MST (+24 h)'], // same clock time, a day later
      [48, 'Nov 4, 7:00 AM MST (+48 h)'],
    ] as const) {
      dragTo(hour)
      frame()
      expect(label()).toBe(expected)
    }
  })

  test('gives the slider the same text for screen readers', () => {
    setup()
    dragTo(5)
    frame()

    expect(slider().getAttribute('aria-valuetext')).toBe(screen.getByText(/\(\+5 h\)/).textContent)
  })

  test('every slider event reaches the map at once; the label renders at most once per frame', () => {
    const { setHour, renders } = setup()
    const rendersAfterMount = renders()
    setHour.mockClear()

    for (const hour of [1, 2, 3, 4, 5]) dragTo(hour)

    expect(setHour.mock.calls.map(([hour]) => hour)).toEqual([1, 2, 3, 4, 5]) // each one went to the map
    expect(renders()).toBe(rendersAfterMount) // but React has not rendered yet
    expect(label()).toContain('(+0 h)')

    frame()

    expect(renders()).toBe(rendersAfterMount + 1) // one render for all five
    expect(label()).toContain('(+5 h)')
  })

  test('a new analysis starts at +0 h on the map', () => {
    const { setHour } = setup()

    expect(setHour).toHaveBeenCalledWith(0)
  })
})

describe('play and pause', () => {
  test('advances one hour per 400 ms', () => {
    const { setHour } = setup()
    setHour.mockClear()

    fireEvent.click(playButton())
    expect(playButton().textContent).toContain('Pause')
    tick(399)
    expect(setHour).not.toHaveBeenCalled()
    tick(1)
    expect(setHour).toHaveBeenLastCalledWith(1)
    tick(800)

    expect(setHour.mock.calls.map(([hour]) => hour)).toEqual([1, 2, 3])
    expect(slider().value).toBe('3')
    frame() // the label follows on the next animation frame
    expect(label()).toContain('(+3 h)')
  })

  test('uses a single timer for the whole run', () => {
    const setIntervalSpy = vi.spyOn(globalThis, 'setInterval')
    setup()

    fireEvent.click(playButton())
    tick(400 * 10)

    expect(setIntervalSpy).toHaveBeenCalledTimes(1)
    setIntervalSpy.mockRestore()
  })

  test('stops by itself at 48 and goes back to Play', () => {
    const { setHour } = setup()
    setHour.mockClear()

    fireEvent.click(playButton())
    tick(400 * 48)

    expect(setHour).toHaveBeenCalledTimes(48)
    expect(setHour).toHaveBeenLastCalledWith(48)
    expect(slider().value).toBe('48')
    expect(playButton().textContent).toContain('Play')

    setHour.mockClear()
    tick(400 * 5)
    expect(setHour).not.toHaveBeenCalled() // nothing keeps running
    expect(vi.getTimerCount()).toBe(0)
  })

  test('Play at the end starts over from 0', () => {
    const { setHour } = setup()
    dragTo(48)
    frame()
    setHour.mockClear()

    fireEvent.click(playButton())
    tick(400)

    expect(setHour.mock.calls.map(([hour]) => hour)).toEqual([0, 1])
  })

  test('Pause stops the animation where it is', () => {
    const { setHour } = setup()
    fireEvent.click(playButton())
    tick(400 * 4)
    fireEvent.click(playButton())
    setHour.mockClear()

    tick(400 * 5)

    expect(setHour).not.toHaveBeenCalled()
    expect(slider().value).toBe('4')
    expect(playButton().textContent).toContain('Play')
  })

  test('dragging the slider while playing takes over and pauses', () => {
    const { setHour } = setup()
    fireEvent.click(playButton())
    tick(400)

    dragTo(30)
    setHour.mockClear()
    tick(400 * 3)

    expect(setHour).not.toHaveBeenCalled()
    expect(playButton().textContent).toContain('Play')
  })

  test('unmounting while playing leaves no timer behind', () => {
    const { unmount } = setup()
    fireEvent.click(playButton())
    tick(400)
    dragTo(9) // leaves a label update waiting for the next frame too
    fireEvent.click(playButton())
    tick(1) // still playing: the interval is armed

    unmount()

    expect(vi.getTimerCount()).toBe(0)
  })

  test('unmounting mid-run clears the interval and any pending frame', () => {
    const { unmount } = setup()
    fireEvent.click(playButton())
    tick(400 * 2 + 5) // the last tick queued a frame that has not run yet

    unmount()

    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('toggle', () => {
  test('is on when the heatmap is visible and reports clicks', () => {
    const { props } = setup()
    const toggle = screen.getByRole('checkbox', { name: 'Show heatmap' }) as HTMLInputElement

    expect(toggle.checked).toBe(true)
    fireEvent.click(toggle)

    expect(props.onToggleVisible).toHaveBeenCalledTimes(1)
  })

  test('is off when the heatmap is hidden', () => {
    setup({ visible: false })

    expect((screen.getByRole('checkbox', { name: 'Show heatmap' }) as HTMLInputElement).checked).toBe(false)
  })
})

describe('states', () => {
  test('loading shows a small spinner and no slider', () => {
    setup({ data: undefined, loading: true })

    expect(screen.getByRole('status').textContent).toContain('Loading weather heatmap')
    expect(document.querySelector('.spinner')).toBeTruthy()
    expect(screen.queryByRole('slider')).toBeNull()
  })

  test('failure shows a message and a Retry button that calls back', () => {
    const { props } = setup({ data: undefined, error: new ApiError('api', 'down', { code: 'weather_unavailable', status: 502 }) })

    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('Weather heatmap unavailable')
    expect(alert.textContent).toContain('could not provide a forecast')
    expect(alert.textContent).toContain('routes above are not affected')
    expect(screen.queryByRole('slider')).toBeNull()

    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(props.onRetry).toHaveBeenCalledTimes(1)
  })

  test('shows loading, not the old error, while a retry is running', () => {
    setup({ data: undefined, loading: true, error: new ApiError('network', 'x') })

    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('status').textContent).toContain('Loading weather heatmap')
  })

  test.each([
    ['the analysis had no corridor points', { data: undefined, noPoints: true }],
    ['the response has no points', { data: heatmapToGeoJson({ start_hour: heatmapSample.start_hour, hours: 49, points: [] }) }],
  ])('says there are no points when %s', (_, overrides) => {
    setup(overrides)

    expect(screen.getByText(/No corridor points/)).toBeTruthy()
    expect(screen.queryByRole('slider')).toBeNull()
  })

  test('the toggle is available in every state', () => {
    setup({ data: undefined, loading: true })

    expect(screen.getByRole('checkbox', { name: 'Show heatmap' })).toBeTruthy()
  })
})

describe('legend and note', () => {
  test('explains the colors with level names beside them', () => {
    setup()
    const legend = screen.getByRole('list', { name: 'Heatmap colors' })

    for (const level of RISK_LEVELS) expect(within(legend).getByText(level.name)).toBeTruthy()
    expect(legend.textContent).toContain('Faint green: low risk. Transparent: no forecast.')
  })

  test('says the heatmap is for the entered load weight', () => {
    setup({ loadWeight: 45_000 })

    expect(screen.getByText(/Risk shown is for your load weight of 45,000 lb/)).toBeTruthy()
    expect(screen.getByText(/checkpoint circles show exact levels/)).toBeTruthy()
  })
})
