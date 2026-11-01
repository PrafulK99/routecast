import type { MilesByLevel, Route } from './api/types'
import { RISK_LEVELS, UNAVAILABLE } from './risk/levels'

// Which MilesByLevel entry belongs to which level number.
const MILES_KEYS: readonly (keyof MilesByLevel)[] = ['low', 'moderate', 'high', 'severe', 'no_travel']

export interface Segment {
  name: string
  color: string
  miles: number
  hatched?: boolean
}

/** Miles by risk level, plus whatever has no forecast, as the parts of one bar. */
export function barSegments(route: Route): Segment[] {
  const segments: Segment[] = RISK_LEVELS.map((level) => ({
    name: level.name,
    color: level.color,
    miles: route.summary.miles_by_level[MILES_KEYS[level.level]],
  }))
  const scored = segments.reduce((sum, segment) => sum + segment.miles, 0)
  const unscored = route.distance_mi - scored
  if (unscored > 0.05) {
    segments.push({ name: 'No forecast', color: UNAVAILABLE.color, miles: unscored, hatched: true })
  }
  return segments.filter((segment) => segment.miles > 0)
}
