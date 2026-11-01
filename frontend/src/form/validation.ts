import type { AnalyzeRequest } from '../api/types'

export interface PlaceChoice {
  label: string
  lat: number
  lon: number
}

export interface TripFormValues {
  origin: PlaceChoice | null
  destination: PlaceChoice | null
  departure: string // from <input type="datetime-local">: local time, "YYYY-MM-DDTHH:mm"
  loadWeight: string
  interval: string
}

export type TripErrors = Partial<Record<'origin' | 'destination' | 'departure' | 'loadWeight' | 'interval', string>>

export const MAX_LOAD_LB = 200_000
export const MIN_TRIP_MILES = 0.5
export const INTERVALS = [10, 25, 50] as const
export const DEFAULT_INTERVAL = 25
export const DEFAULT_LOAD_LB = 40_000
const HOUR_MS = 3_600_000
const WEEK_MS = 7 * 24 * HOUR_MS
const MINUTE_MS = 60_000

const pad = (n: number) => String(n).padStart(2, '0')

/** A Date as the local "YYYY-MM-DDTHH:mm" an <input type="datetime-local"> uses. */
export function toLocalInputValue(date: Date): string {
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** Departure window: the start of the current UTC hour (as the server counts it) to 7 days ahead. */
export function departureBounds(now: Date): { min: Date; max: Date } {
  return {
    min: new Date(Math.floor(now.getTime() / HOUR_MS) * HOUR_MS),
    max: new Date(Math.floor((now.getTime() + WEEK_MS) / MINUTE_MS) * MINUTE_MS),
  }
}

/** The next full hour, a sensible default that is always inside the window. */
export function defaultDeparture(now: Date): string {
  return toLocalInputValue(new Date((Math.floor(now.getTime() / HOUR_MS) + 1) * HOUR_MS))
}

function distanceMiles(a: PlaceChoice, b: PlaceChoice): number {
  const radius = 3958.7613
  const rad = (degrees: number) => (degrees * Math.PI) / 180
  const h =
    Math.sin((rad(b.lat) - rad(a.lat)) / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin((rad(b.lon) - rad(a.lon)) / 2) ** 2
  return 2 * radius * Math.asin(Math.min(1, Math.sqrt(h)))
}

/** The load weight as a whole number, or null if the text is not one. Allows "40,000". */
export function parseLoad(text: string): number | null {
  const cleaned = text.replace(/[\s,]/g, '')
  return /^-?\d+$/.test(cleaned) ? Number(cleaned) : null
}

export function validateTrip(values: TripFormValues, now: Date): TripErrors {
  const errors: TripErrors = {}
  const label = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

  if (!values.origin) errors.origin = 'Choose a starting point from the suggestions.'
  if (!values.destination) errors.destination = 'Choose a destination from the suggestions.'
  if (values.origin && values.destination && distanceMiles(values.origin, values.destination) < MIN_TRIP_MILES) {
    errors.destination = `The destination must be at least ${MIN_TRIP_MILES} mile from the starting point.`
  }

  const departure = new Date(values.departure)
  const { min, max } = departureBounds(now)
  if (!values.departure || Number.isNaN(departure.getTime())) {
    errors.departure = 'Choose a departure date and time.'
  } else if (departure < min || departure > max) {
    errors.departure = `Departure must be between ${label.format(min)} and ${label.format(max)}.`
  }

  const load = parseLoad(values.loadWeight)
  if (values.loadWeight.trim() === '') errors.loadWeight = 'Enter the load weight in pounds.'
  else if (load === null) errors.loadWeight = 'Load weight must be a whole number of pounds.'
  else if (load < 0) errors.loadWeight = "Load weight can't be negative."
  else if (load > MAX_LOAD_LB) errors.loadWeight = `Load weight can be at most ${MAX_LOAD_LB.toLocaleString('en-US')} lb.`

  if (!(INTERVALS as readonly number[]).includes(Number(values.interval))) {
    errors.interval = 'Choose 10, 25 or 50 miles.'
  }
  return errors
}

/** The request body for valid values. The departure goes out as a UTC ISO string. */
export function toRequest(values: TripFormValues): AnalyzeRequest {
  const { origin, destination } = values
  if (!origin || !destination) throw new Error('toRequest needs validated values')
  return {
    origin: { lat: origin.lat, lon: origin.lon, label: origin.label },
    destination: { lat: destination.lat, lon: destination.lon, label: destination.label },
    departure_time: new Date(values.departure).toISOString(),
    load_weight_lb: parseLoad(values.loadWeight) as number,
    checkpoint_interval_miles: Number(values.interval),
  }
}
