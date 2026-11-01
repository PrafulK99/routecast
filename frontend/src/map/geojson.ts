import type { FeatureCollection, LineString, Point } from 'geojson'
import type { Route } from '../api/types'
import { levelInfo } from '../risk/levels'

// Route identity colors. Deliberately outside the risk palette, so a line is never
// mistaken for a risk level; the cards carry the same swatch.
export const ROUTE_COLORS = ['#0072B2', '#7A3E9D', '#4D4D4D'] as const

export function routeColor(index: number): string {
  return ROUTE_COLORS[index % ROUTE_COLORS.length]
}

export interface RouteProperties {
  id: string
  label: string
  color: string
  selected: 0 | 1 // numbers, because map expressions compare them directly
}

/** One line per route, the selected one last so it draws on top. */
export function routesGeoJson(routes: Route[], selectedId: string): FeatureCollection<LineString, RouteProperties> {
  const features = routes.map((route, index) => ({
    type: 'Feature' as const,
    geometry: route.geometry as LineString,
    properties: {
      id: route.id,
      label: route.label,
      color: routeColor(index),
      selected: (route.id === selectedId ? 1 : 0) as 0 | 1,
    },
  }))
  features.sort((a, b) => a.properties.selected - b.properties.selected)
  return { type: 'FeatureCollection', features }
}

export interface CheckpointProperties {
  index: number
  color: string
  levelName: string
  unavailable: 0 | 1
}

/** One point per checkpoint of a route, colored by risk level. */
export function checkpointsGeoJson(route: Route | undefined): FeatureCollection<Point, CheckpointProperties> {
  const features = (route?.checkpoints ?? []).map((checkpoint) => {
    const info = levelInfo(checkpoint.risk.level)
    return {
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [checkpoint.lon, checkpoint.lat] },
      properties: {
        index: checkpoint.index,
        color: info.color,
        levelName: info.name,
        unavailable: (checkpoint.risk.level === null ? 1 : 0) as 0 | 1,
      },
    }
  })
  return { type: 'FeatureCollection', features }
}

/** [[west, south], [east, north]] around every route, or null if there are none. */
export function boundsOf(routes: Route[]): [[number, number], [number, number]] | null {
  let west = Infinity
  let south = Infinity
  let east = -Infinity
  let north = -Infinity
  for (const route of routes) {
    for (const [lon, lat] of route.geometry.coordinates) {
      west = Math.min(west, lon)
      east = Math.max(east, lon)
      south = Math.min(south, lat)
      north = Math.max(north, lat)
    }
  }
  return Number.isFinite(west) ? [[west, south], [east, north]] : null
}
