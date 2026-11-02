import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactElement } from 'react'
import { vi } from 'vitest'
import { analyzeSample, heatmapSample } from '../api/fixtures/check'
import type { AnalyzeRequest, AnalyzeResponse, HeatmapRequest, HeatmapResponse, PlanResponse } from '../api/types'
import { SEARCH_DELAY_MS } from '../components/PlaceInput'

export function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

export function apiError(status: number, code: string, message: string, fields: Record<string, string[]> = {}) {
  return jsonResponse({ error: { code, message, fields, request_id: 'req-test' } }, status)
}

/** The recorded two-route sample, extended to the three routes the API normally returns. */
export function threeRouteAnalysis(requestId = 'req-1'): AnalyzeResponse {
  const analysis = structuredClone(analyzeSample)
  const third = structuredClone(analysis.routes[0])
  third.id = 'route-3'
  third.label = 'Route C'
  analysis.routes.push(third)
  analysis.recommendation.ranking.push({ rank: 3, route_id: 'route-3', sort_key: { ...analysis.recommendation.ranking[1].sort_key } })
  analysis.meta.request_id = requestId
  return analysis
}

// --- Mapbox geocoding stand-in ---------------------------------------------------

const PLACES: Record<string, { label: string; lat: number; lon: number }[]> = {
  dall: [
    { label: 'Dallas, Texas, United States', lat: 32.7767, lon: -96.797 },
    { label: 'Dallas, Georgia, United States', lat: 33.9237, lon: -84.8408 },
  ],
  chic: [{ label: 'Chicago, Illinois, United States', lat: 41.8781, lon: -87.6298 }],
}

export function geocodeBody(query: string) {
  const places = Object.entries(PLACES).find(([prefix]) => query.toLowerCase().startsWith(prefix))?.[1] ?? []
  return {
    type: 'FeatureCollection',
    features: places.map((place) => ({
      type: 'Feature',
      properties: {
        mapbox_id: place.label,
        full_address: place.label,
        coordinates: { latitude: place.lat, longitude: place.lon },
      },
    })),
  }
}

// --- fetch stand-in --------------------------------------------------------------

export interface AnalyzeCall {
  request: AnalyzeRequest
  signal: AbortSignal
}

export interface HeatmapCall {
  request: HeatmapRequest
  signal: AbortSignal
}

/** The recorded heatmap sample, as a fresh copy. */
export function heatmapResponse(): HeatmapResponse {
  return structuredClone(heatmapSample)
}

/** What /api/plan answers by default: two cells and a 48-hour window. */
export function planResponse(): PlanResponse {
  return {
    cells: [[32.8, -96.8], [41.9, -87.6]],
    window: { first_hour: '2026-11-02T14:00:00Z', last_hour: '2026-11-04T14:00:00Z' },
  }
}

/** An Open-Meteo answer for the requested locations: calm, 72 hours from 2026-11-02T00:00. */
export function openMeteoBody(url: URL) {
  const lats = (url.searchParams.get('latitude') ?? '').split(',')
  const lons = (url.searchParams.get('longitude') ?? '').split(',')
  const time = Array.from({ length: 72 }, (_, h) => new Date(Date.UTC(2026, 10, 2, h)).toISOString().slice(0, 16))
  const zeros = time.map(() => 0)
  const locations = lats.map((lat, i) => ({
    latitude: Number(lat),
    longitude: Number(lons[i]),
    hourly: { time, wind_speed_10m: time.map(() => 5), rain: zeros, showers: zeros, snowfall: zeros },
  }))
  return locations.length === 1 ? locations[0] : locations
}

interface Handlers {
  plan?: (call: { request: AnalyzeRequest; signal: AbortSignal }) => Response | Promise<Response>
  weather?: (url: URL, signal: AbortSignal) => Response | Promise<Response>
}

/** Routes fetch by URL: health, geocoding, Open-Meteo, and the given /api/plan, /api/analyze and /api/heatmap handlers. */
export function installFetch(
  analyze: (call: AnalyzeCall) => Response | Promise<Response> = () => jsonResponse(threeRouteAnalysis()),
  heatmap: (call: HeatmapCall) => Response | Promise<Response> = () => jsonResponse(heatmapResponse()),
  { plan = () => jsonResponse(planResponse()), weather = (url) => jsonResponse(openMeteoBody(url)) }: Handlers = {},
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/health')) return jsonResponse({ status: 'ok' })
    if (url.includes('api.open-meteo.com')) return weather(new URL(url), init?.signal as AbortSignal)
    if (url.includes('/api/plan')) {
      return plan({ request: JSON.parse(String(init?.body)), signal: init?.signal as AbortSignal })
    }
    if (url.includes('/geocode/v6/forward')) return jsonResponse(geocodeBody(new URL(url).searchParams.get('q') ?? ''))
    if (url.includes('/api/analyze')) {
      return analyze({ request: JSON.parse(String(init?.body)), signal: init?.signal as AbortSignal })
    }
    if (url.includes('/api/heatmap')) {
      return heatmap({ request: JSON.parse(String(init?.body)), signal: init?.signal as AbortSignal })
    }
    throw new Error(`unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

export function callsTo(fetchMock: ReturnType<typeof installFetch>, fragment: string) {
  return fetchMock.mock.calls.filter(([input]) => String(input).includes(fragment))
}

/** A promise settled from the outside, for requests the test wants to keep pending. */
export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

// --- form filling (fake timers: the search is debounced) --------------------------

export async function pickPlace(field: 'From' | 'To', typed: string, option: RegExp) {
  fireEvent.change(screen.getByRole('combobox', { name: field }), { target: { value: typed } })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(SEARCH_DELAY_MS)
  })
  fireEvent.click(await within(await screen.findByRole('listbox')).findByRole('option', { name: option }))
}

/** Fills both places (the other fields have valid defaults) and presses Analyze. */
export async function submitTrip() {
  await pickPlace('From', 'Dallas', /Dallas, Texas/)
  await pickPlace('To', 'Chicago', /Chicago/)
  fireEvent.click(screen.getByRole('button', { name: 'Analyze routes' }))
}
