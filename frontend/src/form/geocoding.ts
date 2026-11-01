import { MAPBOX_TOKEN } from '../config'

export interface GeocodeSuggestion {
  id: string
  label: string
  lat: number
  lon: number
}

export const MIN_QUERY_LENGTH = 3
const ENDPOINT = 'https://api.mapbox.com/search/geocode/v6/forward'

interface GeocodeFeature {
  id?: string
  geometry?: { coordinates?: number[] }
  properties?: {
    mapbox_id?: string
    name?: string
    full_address?: string
    place_formatted?: string
    coordinates?: { latitude?: number; longitude?: number }
  }
}

/** Suggestions from a Mapbox Geocoding v6 response. Features without coordinates are dropped. */
export function parseGeocode(body: { features?: GeocodeFeature[] }): GeocodeSuggestion[] {
  const suggestions: GeocodeSuggestion[] = []
  for (const feature of body.features ?? []) {
    const properties = feature.properties ?? {}
    const lat = properties.coordinates?.latitude ?? feature.geometry?.coordinates?.[1]
    const lon = properties.coordinates?.longitude ?? feature.geometry?.coordinates?.[0]
    if (typeof lat !== 'number' || typeof lon !== 'number') continue
    const label =
      properties.full_address ?? [properties.name, properties.place_formatted].filter(Boolean).join(', ')
    if (!label) continue
    suggestions.push({ id: properties.mapbox_id ?? feature.id ?? `${lat},${lon}`, label, lat, lon })
  }
  return suggestions
}

export async function geocode(
  query: string,
  signal: AbortSignal,
  token: string = MAPBOX_TOKEN,
): Promise<GeocodeSuggestion[]> {
  if (!token) throw new Error('missing token')
  const params = new URLSearchParams({
    q: query,
    autocomplete: 'true',
    limit: '5',
    access_token: token,
  })
  const response = await fetch(`${ENDPOINT}?${params}`, { signal })
  if (!response.ok) throw new Error(`geocoding failed (${response.status})`)
  return parseGeocode(await response.json())
}
