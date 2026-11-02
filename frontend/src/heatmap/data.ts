import type { FeatureCollection, Point } from 'geojson'
import type { HeatmapResponse } from '../api/types'
import { type TimeOptions, formatLocalTime } from '../format'

/** Properties h0 to h48: the risk level at each hour after departure; -1 means no forecast. */
export type HeatmapProperties = Record<string, number>

export interface HeatmapData {
  collection: FeatureCollection<Point, HeatmapProperties>
  startHour: string // UTC, departure rounded down to the hour
  hours: number // 49: the slider runs 0 to hours - 1
  isEmpty: boolean
}

export function levelProperty(hour: number): string {
  return `h${hour}`
}

/** "Nov 2, 8:00 PM CST (+5 h)": the selected hour in the viewer's local time, and its offset. */
export function hourLabel(startHour: string, hour: number, time?: TimeOptions): string {
  const instant = new Date(Date.parse(startHour) + hour * 3_600_000).toISOString()
  return `${formatLocalTime(instant, time)} (+${hour} h)`
}

/**
 * The response as one map-ready point collection with all 49 levels on every point,
 * so the slider only changes which property the layer reads and nothing is rebuilt.
 * Used as a query `select`, so it runs once per response.
 */
export function heatmapToGeoJson(response: HeatmapResponse): HeatmapData {
  const features = response.points.map((point) => {
    const properties: HeatmapProperties = {}
    point.levels.forEach((level, hour) => {
      properties[levelProperty(hour)] = level
    })
    return {
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [point.lon, point.lat] },
      properties,
    }
  })
  return {
    collection: { type: 'FeatureCollection', features },
    startHour: response.start_hour,
    hours: response.hours,
    isEmpty: features.length === 0,
  }
}
