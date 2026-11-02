// Mirrors the response serializers in backend/api/serializers.py field for field.
// fixtures/check.ts type-checks real sample responses against these, so the
// build fails if a field is missing, renamed or retyped. Types are kept as plain
// number/string (allowed values in comments) because a JSON import is typed loosely.

/** Risk level number: 0 Low, 1 Moderate, 2 High, 3 Severe, 4 No Travel. */
export type Level = number

export interface ApiPoint {
  lat: number // -90 to 90
  lon: number // -180 to 180
  label?: string
}

export interface AnalyzeRequest {
  origin: ApiPoint
  destination: ApiPoint // at least 0.5 mile from the origin
  departure_time: string // ISO 8601 with a UTC offset, from the current hour to 7 days ahead
  load_weight_lb: number // integer, 0 to 200000
  checkpoint_interval_miles?: number // 10, 25 or 50; default 25
  weather?: WeatherCell[] // fetched by the browser; without it the server fetches the weather itself
}

/** One grid cell of Open-Meteo hourly output (mph, inches), exactly as /api/plan named the cell. */
export interface WeatherCell {
  lat: number
  lon: number
  time: string[] // UTC hours with no zone suffix, e.g. 2026-11-02T14:00
  wind_speed_10m: (number | null)[]
  rain: (number | null)[]
  showers: (number | null)[]
  snowfall: (number | null)[]
}

export interface PlanResponse {
  cells: number[][] // [lat, lon] grid cells of every checkpoint of every route
  window: { first_hour: string; last_hour: string } // UTC hours the weather must cover
}

export interface Risk {
  level: Level | null // null when the checkpoint is unavailable
  level_name: string | null // Low, Moderate, High, Severe, No Travel
  factor: string | null // wind, rain or snow
  wind_level: Level | null
  rain_level: Level | null
  snow_level: Level | null
  load_rule_applied: boolean
}

export interface Checkpoint {
  index: number
  mile: number
  lat: number
  lon: number
  eta: string // UTC, e.g. 2026-11-02T14:27:30Z
  forecast_hour: string // UTC hour the forecast was read for
  wind_mph: number | null
  rain_in_hr: number | null
  snow_in_hr: number | null
  segment_mi: number
  status: string // ok, partial or unavailable
  risk: Risk
}

export interface MilesByLevel {
  low: number
  moderate: number
  high: number
  severe: number
  no_travel: number
}

export interface RouteSummary {
  miles_by_level: MilesByLevel
  avg_risk: number | null // null when no checkpoint could be scored
  worst_level: Level | null
  worst_level_name: string | null
  coverage_pct: number
  blocked: boolean
}

export interface LineString {
  type: string // "LineString"
  coordinates: number[][] // [lon, lat] pairs
}

export interface Route {
  id: string
  label: string
  distance_mi: number
  duration_s: number // truck-adjusted
  departure_time: string
  arrival_time: string
  geometry: LineString // simplified for display
  summary: RouteSummary
  checkpoints: Checkpoint[]
}

export interface SortKey {
  no_travel_mi: number
  severe_mi: number
  high_mi: number
  avg_risk: number | null
  duration_s: number
}

export interface RankingEntry {
  rank: number
  route_id: string
  sort_key: SortKey
}

export interface Recommendation {
  route_id: string
  reasons: string[]
  all_blocked: boolean
  ranking: RankingEntry[]
}

export interface Meta {
  request_id: string
  interval_miles: number // the interval actually used
  truck_duration_factor: number
  forecast_source: string
  warnings: string[]
}

export interface AnalyzeResponse {
  meta: Meta
  routes: Route[]
  recommendation: Recommendation
  corridor_points: number[][] // [lat, lon] pairs, at most 120
  corridor_cells: number[][] // [lat, lon] grid cells of the corridor points: the heatmap's weather
}

export interface HeatmapRequest {
  points: number[][] // [lat, lon] pairs, 1 to 120
  departure_time: string
  load_weight_lb: number
  weather?: WeatherCell[] // fetched by the browser, for the corridor_cells
}

export interface HeatmapPoint {
  lat: number
  lon: number
  levels: number[] // 49 values, hours 0 to 48 after departure; -1 where there is no forecast
}

export interface HeatmapResponse {
  start_hour: string // departure rounded down to the hour, UTC
  hours: number // 49
  points: HeatmapPoint[]
}

/** Every error response has this shape. */
export interface ApiErrorBody {
  error: {
    code: string // validation_error, no_route, route_too_long, routing_unavailable,
    // weather_unavailable, weather_rate_limited, rate_limited, payload_too_large, internal_error, ...
    message: string
    fields: Record<string, string[]> // per-field messages, empty when not about a field
    request_id: string | null
  }
}
