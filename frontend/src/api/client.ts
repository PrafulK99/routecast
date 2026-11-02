import { API_BASE_URL } from '../config'
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ApiErrorBody,
  HeatmapRequest,
  HeatmapResponse,
} from './types'

export const ANALYZE_TIMEOUT_MS = 90_000

/**
 * api:     the server answered with an error (code from the error body, null if it was not ours)
 * network: no usable answer (offline, server down, garbled reply)
 * timeout: no answer within 90 seconds
 */
export type ApiFailureKind = 'api' | 'network' | 'timeout'

export class ApiError extends Error {
  readonly kind: ApiFailureKind
  readonly status: number | null
  readonly code: string | null
  readonly fields: Record<string, string[]>
  readonly requestId: string | null

  constructor(
    kind: ApiFailureKind,
    message: string,
    details: { status?: number; code?: string; fields?: Record<string, string[]>; requestId?: string | null } = {},
  ) {
    super(message)
    this.kind = kind
    this.status = details.status ?? null
    this.code = details.code ?? null
    this.fields = details.fields ?? {}
    this.requestId = details.requestId ?? null
  }
}

async function readApiError(response: Response): Promise<ApiError> {
  try {
    const { error } = (await response.json()) as ApiErrorBody
    return new ApiError('api', error.message, {
      status: response.status,
      code: error.code,
      fields: error.fields,
      requestId: error.request_id,
    })
  } catch {
    // Not our error shape, e.g. an HTML page from a proxy.
    return new ApiError('api', `HTTP ${response.status}`, { status: response.status })
  }
}

/**
 * POST JSON and read the reply. `signal` is TanStack Query's: it aborts when a newer
 * analysis starts, and that cancellation is rethrown untouched. A 90 second timeout
 * is linked to the same request and reported as its own kind of failure.
 */
async function postJson<T>(path: string, body: unknown, signal: AbortSignal): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, ANALYZE_TIMEOUT_MS)
  const onCancel = () => controller.abort()
  if (signal.aborted) controller.abort()
  else signal.addEventListener('abort', onCancel, { once: true })

  try {
    let response: Response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
    } catch (error) {
      if (timedOut) throw new ApiError('timeout', 'The server did not answer in time.')
      if (signal.aborted) throw error
      throw new ApiError('network', 'The server could not be reached.')
    }
    if (!response.ok) throw await readApiError(response)
    try {
      return (await response.json()) as T
    } catch {
      throw new ApiError('network', 'The server sent a reply that could not be read.')
    }
  } finally {
    clearTimeout(timer)
    signal.removeEventListener('abort', onCancel)
  }
}

export function analyze(request: AnalyzeRequest, signal: AbortSignal): Promise<AnalyzeResponse> {
  return postJson('/api/analyze', request, signal)
}

export function fetchHeatmap(request: HeatmapRequest, signal: AbortSignal): Promise<HeatmapResponse> {
  return postJson('/api/heatmap', request, signal)
}

/** Silent GET /api/health on page load, to wake a sleeping free-tier server. */
export function wakeServer(): void {
  fetch(`${API_BASE_URL}/api/health`).catch(() => {})
}
