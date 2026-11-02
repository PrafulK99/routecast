import type { WeatherCell } from '../api/types'

// Weather data by Open-Meteo.com (CC BY 4.0). The browser fetches it, so each visitor has their own quota.
export const OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'
export const BATCH_SIZE = 50
export const MAX_PARALLEL = 4
export const REQUEST_TIMEOUT_MS = 10_000
export const RETRY_BACKOFF_MS = 500
export const CACHE_TTL_MS = 30 * 60_000 // as the server's own weather cache
const MAX_FORECAST_DAYS = 16
const DAY_MS = 86_400_000
const HOURLY = 'wind_speed_10m,rain,showers,snowfall'

export interface HourWindow {
  first_hour: string // UTC ISO
  last_hour: string
}

/** minutely, hourly or daily from the 429 reason text, else unknown. */
export type RateLimit = 'minutely' | 'hourly' | 'daily' | 'unknown'

/**
 * rate_limited: Open-Meteo answered 429 (`limit` says which quota)
 * unreachable:  no usable answer from any batch (offline, blocked, errors), or a 429 the
 *               browser could not read (its error body is hidden when CORS headers are missing)
 */
export class WeatherError extends Error {
  readonly kind: 'rate_limited' | 'unreachable'
  readonly limit: RateLimit

  constructor(kind: 'rate_limited' | 'unreachable', limit: RateLimit = 'unknown') {
    super(`weather ${kind} ${limit}`)
    this.kind = kind
    this.limit = limit
  }
}

export function classifyRateLimit(reason: unknown): RateLimit {
  const text = typeof reason === 'string' ? reason.toLowerCase() : ''
  for (const kind of ['minutely', 'hourly', 'daily'] as const) {
    if (text.includes(kind)) return kind
  }
  return 'unknown'
}

export interface WeatherClientDeps {
  fetchFn?: typeof fetch
  now?: () => number
  sleep?: (ms: number) => Promise<void>
}

type Cell = number[]

const cellKey = ([lat, lon]: Cell) => `${lat},${lon}` // exact coordinates as the server named them
const abortError = () => new DOMException('The weather request was cancelled.', 'AbortError')

function inWindow(series: WeatherCell, first: number, last: number): WeatherCell {
  const keep = series.time.map((text) => {
    const at = Date.parse(`${text}Z`)
    return at >= first && at <= last
  })
  const pick = <T>(values: T[]) => values.filter((_, i) => keep[i])
  return {
    lat: series.lat,
    lon: series.lon,
    time: pick(series.time),
    wind_speed_10m: pick(series.wind_speed_10m),
    rain: pick(series.rain),
    showers: pick(series.showers),
    snowfall: pick(series.snowfall),
  }
}

function covers(series: WeatherCell, first: number, last: number): boolean {
  const times = series.time
  return times.length > 0 && Date.parse(`${times[0]}Z`) <= first && Date.parse(`${times[times.length - 1]}Z`) >= last
}

/** The parsed series for each requested cell, or null if the body is not what we asked for. */
function parseBody(body: unknown, cells: Cell[]): WeatherCell[] | null {
  const locations = Array.isArray(body) ? body : [body]
  if (locations.length !== cells.length) return null
  const out: WeatherCell[] = []
  for (const [index, location] of locations.entries()) {
    const hourly = (location as { hourly?: Record<string, unknown> } | null)?.hourly
    if (!hourly || !Array.isArray(hourly.time)) return null
    const arrays = {} as Record<string, (number | null)[]>
    for (const name of ['wind_speed_10m', 'rain', 'showers', 'snowfall']) {
      const values = hourly[name]
      if (!Array.isArray(values) || values.length !== hourly.time.length) return null
      arrays[name] = values as (number | null)[]
    }
    out.push({
      lat: cells[index][0], // our requested cell, not the coordinates Open-Meteo snapped to
      lon: cells[index][1],
      time: hourly.time as string[],
      wind_speed_10m: arrays.wind_speed_10m,
      rain: arrays.rain,
      showers: arrays.showers,
      snowfall: arrays.snowfall,
    })
  }
  return out
}

export function createWeatherClient({
  fetchFn = (...args) => fetch(...args),
  now = Date.now,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
}: WeatherClientDeps = {}) {
  // Whole series per cell as Open-Meteo returned them, so a later request for other hours can reuse them.
  const cache = new Map<string, { series: WeatherCell; expires: number }>()

  async function requestBatch(cells: Cell[], days: number, signal: AbortSignal): Promise<WeatherCell[] | null> {
    const params = new URLSearchParams({
      latitude: cells.map(([lat]) => lat).join(','),
      longitude: cells.map(([, lon]) => lon).join(','),
      hourly: HOURLY,
      wind_speed_unit: 'mph',
      precipitation_unit: 'inch',
      timezone: 'GMT',
      forecast_days: String(days),
    })
    for (let attempt = 0; attempt < 2; attempt++) {
      if (attempt) await sleep(RETRY_BACKOFF_MS)
      const timeout = new AbortController()
      const timer = setTimeout(() => timeout.abort(), REQUEST_TIMEOUT_MS)
      const onCancel = () => timeout.abort()
      signal.addEventListener('abort', onCancel, { once: true })
      try {
        let response: Response
        try {
          response = await fetchFn(`${OPEN_METEO_URL}?${params}`, { signal: timeout.signal })
        } catch {
          if (signal.aborted) throw abortError()
          continue // network error or timeout: retry once
        }
        if (response.status === 429) {
          const reason = await response.json().then((body: { reason?: unknown }) => body.reason, () => null)
          throw new WeatherError('rate_limited', classifyRateLimit(reason))
        }
        if (response.status >= 500) continue
        if (!response.ok) return null // another client error will not improve on retry
        const parsed = parseBody(await response.json().catch(() => null), cells)
        if (parsed) return parsed
      } finally {
        clearTimeout(timer)
        signal.removeEventListener('abort', onCancel)
      }
    }
    return null
  }

  /** Runs the tasks with at most `limit` in flight; a failure cancels the rest. */
  async function runLimited<T>(tasks: ((signal: AbortSignal) => Promise<T>)[], limit: number, signal: AbortSignal) {
    const inner = new AbortController()
    const onCancel = () => inner.abort()
    if (signal.aborted) inner.abort()
    signal.addEventListener('abort', onCancel, { once: true })
    const results: T[] = new Array(tasks.length)
    let next = 0
    const worker = async () => {
      while (next < tasks.length) {
        if (inner.signal.aborted) throw abortError()
        const index = next++
        results[index] = await tasks[index](inner.signal)
      }
    }
    try {
      await Promise.all(Array.from({ length: Math.min(limit, tasks.length) }, worker))
    } catch (error) {
      inner.abort()
      throw signal.aborted ? abortError() : error
    } finally {
      signal.removeEventListener('abort', onCancel)
    }
    return results
  }

  /**
   * Weather for `cells` (exact coordinates from the server) over `window`, as the `weather` field of
   * /api/analyze or /api/heatmap. Cells fetched within 30 minutes are reused. A batch that fails
   * leaves its cells out (the server marks them unavailable and says so); if nothing at all could
   * be obtained this throws instead of sending an empty list.
   */
  async function fetchWeather(cells: Cell[], window: HourWindow, signal: AbortSignal): Promise<WeatherCell[]> {
    const first = Date.parse(window.first_hour)
    const last = Date.parse(window.last_hour)
    const current = now()
    const ready = new Map<string, WeatherCell>()
    const missing: Cell[] = []
    for (const cell of cells) {
      const cached = cache.get(cellKey(cell))
      if (cached && cached.expires > current && covers(cached.series, first, last)) {
        ready.set(cellKey(cell), cached.series)
      } else {
        missing.push(cell)
      }
    }

    if (missing.length) {
      const today = Math.floor(current / DAY_MS) * DAY_MS
      const days = Math.max(1, Math.min(Math.floor((last - today) / DAY_MS) + 1, MAX_FORECAST_DAYS))
      const batches: Cell[][] = []
      for (let i = 0; i < missing.length; i += BATCH_SIZE) batches.push(missing.slice(i, i + BATCH_SIZE))
      const fetched = await runLimited(
        batches.map((batch) => (inner: AbortSignal) => requestBatch(batch, days, inner)),
        MAX_PARALLEL,
        signal,
      )
      fetched.forEach((series, index) => {
        series?.forEach((entry, i) => {
          const key = cellKey(batches[index][i])
          ready.set(key, entry)
          cache.set(key, { series: entry, expires: current + CACHE_TTL_MS })
        })
      })
      if (ready.size === 0) throw new WeatherError('unreachable')
    }

    return cells.flatMap((cell) => {
      const series = ready.get(cellKey(cell))
      return series ? [inWindow(series, first, last)] : []
    })
  }

  return { fetchWeather, clearCache: () => cache.clear() }
}

/** The one client the app uses. */
export const weatherClient = createWeatherClient()
