import { ApiError } from './client'

export interface ErrorView {
  message: string
  fields: Record<string, string[]>
  requestId: string | null
}

// One user-facing message per API error code. The two rate-limit codes use the
// server's own text, which is safe by design and says "a minute" or "later".
const MESSAGES: Record<string, string> = {
  validation_error: 'The server rejected some of the trip details. Check them and try again.',
  no_route: 'No drivable route was found between these two places. Try different locations.',
  route_too_long:
    'This trip is too long to analyze, even with the largest checkpoint interval. Try a shorter trip.',
  routing_unavailable: 'The routing service is not responding. Please try again in a moment.',
  weather_unavailable:
    'The weather service could not provide a forecast, so no safety score can be shown. Please try again in a moment.',
  internal_error: 'Something went wrong on our side. Please try again.',
}

const FALLBACK_RATE_LIMITED = 'You are sending requests too quickly. Wait a moment, then try again.'
const FALLBACK_WEATHER_RATE_LIMITED = 'The weather service is rate limited; try again later.'

export function describeError(error: unknown): ErrorView {
  if (!(error instanceof ApiError)) {
    return { message: MESSAGES.internal_error, fields: {}, requestId: null }
  }
  const { code, fields, requestId } = error
  let message: string
  if (error.kind === 'network') {
    message = "Can't reach the server. Check your internet connection and try again."
  } else if (error.kind === 'timeout') {
    message = 'The server did not answer within 90 seconds. Please try again.'
  } else if (code === 'rate_limited') {
    message = error.message || FALLBACK_RATE_LIMITED
  } else if (code === 'weather_rate_limited') {
    message = error.message || FALLBACK_WEATHER_RATE_LIMITED
  } else if (code && code in MESSAGES) {
    message = MESSAGES[code]
  } else {
    message = `Something unexpected happened${code ? ` (${code})` : ''}. Please try again.`
  }
  return { message, fields, requestId }
}
