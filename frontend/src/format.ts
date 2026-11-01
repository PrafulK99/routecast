/** 15797 seconds -> "4 h 23 min"; under an hour -> "23 min". */
export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours === 0) return `${minutes} min`
  return `${hours} h ${minutes} min`
}

export function formatMiles(miles: number): string {
  const digits = miles < 10 ? 1 : 0
  return `${miles.toLocaleString('en-US', { maximumFractionDigits: digits })} mi`
}

/** Coverage under 100% keeps one decimal so 99.6% never reads as 100%. */
export function formatPercent(percent: number): string {
  return percent >= 100 ? '100%' : `${(Math.floor(percent * 10) / 10).toString()}%`
}

/** Rain and snow rates keep up to three decimals: 0.098 must not read as 0.10. */
export function formatRate(value: number | null): string {
  return value === null ? 'n/a' : `${Number(value.toFixed(3))} in/hr`
}

export function formatWind(value: number | null): string {
  return value === null ? 'n/a' : `${Number(value.toFixed(1))} mph`
}

export interface TimeOptions {
  timeZone?: string // defaults to the viewer's zone
  locale?: string
}

/** A UTC instant in the viewer's local time with the zone label, e.g. "Nov 2, 8:27 AM CST". */
export function formatLocalTime(iso: string, { timeZone, locale }: TimeOptions = {}): string {
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
    timeZone,
  }).format(new Date(iso))
}
