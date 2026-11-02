const HOUR_MS = 3_600_000

export interface HeatmapDeparture {
  departure: string // ISO, UTC
  adjusted: boolean // true when the original had to be replaced
}

/**
 * The departure to send with a heatmap request. The server refuses a departure from before
 * the start of the current hour, so a Retry made long after the analysis would fail for good.
 * If the original departure's hour has passed, use the next full hour instead; otherwise the
 * original is sent unchanged (a departure earlier in the current hour is still accepted).
 */
export function heatmapDeparture(original: string, now: Date): HeatmapDeparture {
  const currentHour = Math.floor(now.getTime() / HOUR_MS) * HOUR_MS
  if (Date.parse(original) >= currentHour) return { departure: original, adjusted: false }
  return { departure: new Date(currentHour + HOUR_MS).toISOString(), adjusted: true }
}
