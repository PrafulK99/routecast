import { beforeEach, describe, expect, test, vi } from 'vitest'
import * as client from './api/client'
import { analyzeSample, heatmapSample, planSample } from './api/fixtures/check'
import type { AnalyzeRequest, WeatherCell } from './api/types'
import { type Stage, runAnalysis, runHeatmap } from './flow'
import type { HourWindow } from './weather/openMeteo'

vi.mock('./api/client', () => ({ plan: vi.fn(), analyze: vi.fn(), fetchHeatmap: vi.fn() }))

const REQUEST: AnalyzeRequest = {
  origin: { lat: 32.78, lon: -96.8 },
  destination: { lat: 41.88, lon: -87.63 },
  departure_time: '2026-11-02T14:20:00Z',
  load_weight_lb: 40000,
}
const ENTRY: WeatherCell = {
  lat: 30,
  lon: -100,
  time: ['2026-11-02T14:00'],
  wind_speed_10m: [5],
  rain: [0],
  showers: [0],
  snowfall: [0],
}
const signal = new AbortController().signal

function fakeWeather() {
  return {
    fetchWeather: vi.fn(async (_cells: number[][], _window: HourWindow, _signal: AbortSignal) => [ENTRY]),
    clearCache: vi.fn(),
  }
}

beforeEach(() => {
  vi.mocked(client.plan).mockReset().mockResolvedValue(planSample)
  vi.mocked(client.analyze).mockReset().mockResolvedValue(analyzeSample)
  vi.mocked(client.fetchHeatmap).mockReset().mockResolvedValue(heatmapSample)
})

describe('runAnalysis', () => {
  test('plans, fetches the planned weather, then analyzes with it, reporting each step', async () => {
    const weather = fakeWeather()
    const order: string[] = []
    vi.mocked(client.plan).mockImplementation(async () => (order.push('plan'), planSample))
    weather.fetchWeather.mockImplementation(async () => (order.push('weather'), [ENTRY]))
    vi.mocked(client.analyze).mockImplementation(async () => (order.push('analyze'), analyzeSample))
    const stages: Stage[] = []

    const result = await runAnalysis(REQUEST, signal, (stage) => stages.push(stage), weather)

    expect(order).toEqual(['plan', 'weather', 'analyze'])
    expect(stages).toEqual(['planning', 'fetching', 'scoring'])
    expect(result).toBe(analyzeSample)
    expect(client.plan).toHaveBeenCalledWith(REQUEST, signal) // no weather in the plan request
    expect(weather.fetchWeather).toHaveBeenCalledWith(planSample.cells, planSample.window, signal)
    expect(client.analyze).toHaveBeenCalledWith({ ...REQUEST, weather: [ENTRY] }, signal)
  })

  test('a weather failure stops the flow before analyze is called', async () => {
    const weather = fakeWeather()
    weather.fetchWeather.mockRejectedValue(new Error('daily limit'))

    await expect(runAnalysis(REQUEST, signal, () => {}, weather)).rejects.toThrow('daily limit')

    expect(client.analyze).not.toHaveBeenCalled()
  })

  test('a plan failure stops the flow before any weather is fetched', async () => {
    const weather = fakeWeather()
    vi.mocked(client.plan).mockRejectedValue(new Error('no route'))

    await expect(runAnalysis(REQUEST, signal, () => {}, weather)).rejects.toThrow('no route')

    expect(weather.fetchWeather).not.toHaveBeenCalled()
  })
})

describe('runHeatmap', () => {
  test('fetches the corridor cells exactly as the analysis named them, for departure hour to +48 hours', async () => {
    const weather = fakeWeather()

    const result = await runHeatmap(analyzeSample, '2026-11-02T14:20:00Z', 40000, signal, weather)

    expect(result).toBe(heatmapSample)
    expect(weather.fetchWeather).toHaveBeenCalledWith(
      analyzeSample.corridor_cells,
      { first_hour: '2026-11-02T14:00:00.000Z', last_hour: '2026-11-04T14:00:00.000Z' },
      signal,
    )
    expect(client.fetchHeatmap).toHaveBeenCalledWith(
      {
        points: analyzeSample.corridor_points,
        departure_time: '2026-11-02T14:20:00Z',
        load_weight_lb: 40000,
        weather: [ENTRY],
      },
      signal,
    )
  })

  test('sends the cell coordinates back unchanged: no rounding happens in the browser', async () => {
    const weather = fakeWeather()
    const cells = [[30.25, -99.75], [30.0, -99.7]]

    await runHeatmap({ ...analyzeSample, corridor_cells: cells }, REQUEST.departure_time, 1, signal, weather)

    expect(weather.fetchWeather.mock.calls[0][0]).toBe(cells)
  })
})
