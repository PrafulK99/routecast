import { analyze, fetchHeatmap, plan } from './api/client'
import type { AnalyzeRequest, AnalyzeResponse, HeatmapResponse } from './api/types'
import { weatherClient } from './weather/openMeteo'

/** Where an analysis is: asking the server which weather it needs, fetching it, then scoring. */
export type Stage = 'planning' | 'fetching' | 'scoring'

export const STAGE_LABELS: Record<Stage, string> = {
  planning: 'Planning routes',
  fetching: 'Fetching weather',
  scoring: 'Scoring routes',
}

const HOUR_MS = 3_600_000
const HEATMAP_HOURS = 49 // slider positions 0 to 48

/**
 * The three steps of one analysis. The server names the grid cells and hours it needs, the browser
 * fetches them from Open-Meteo (its own quota), and the server scores and ranks with that weather.
 */
export async function runAnalysis(
  request: AnalyzeRequest,
  signal: AbortSignal,
  onStage: (stage: Stage) => void = () => {},
  weather = weatherClient,
): Promise<AnalyzeResponse> {
  onStage('planning')
  const { cells, window } = await plan(request, signal)
  onStage('fetching')
  const entries = await weather.fetchWeather(cells, window, signal)
  onStage('scoring')
  return analyze({ ...request, weather: entries }, signal)
}

/**
 * The heatmap for an analysis: the weather for its corridor cells (exact coordinates from the
 * analysis, so nothing is rounded here) from departure's hour to 48 hours later, then /api/heatmap.
 * Cells already fetched for the routes are not fetched again.
 */
export async function runHeatmap(
  analysis: AnalyzeResponse,
  departure: string,
  loadWeightLb: number,
  signal: AbortSignal,
  weather = weatherClient,
): Promise<HeatmapResponse> {
  const start = Math.floor(Date.parse(departure) / HOUR_MS) * HOUR_MS
  const window = {
    first_hour: new Date(start).toISOString(),
    last_hour: new Date(start + (HEATMAP_HOURS - 1) * HOUR_MS).toISOString(),
  }
  const entries = await weather.fetchWeather(analysis.corridor_cells, window, signal)
  return fetchHeatmap(
    { points: analysis.corridor_points, departure_time: departure, load_weight_lb: loadWeightLb, weather: entries },
    signal,
  )
}
