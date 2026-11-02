import type { ExpressionSpecification } from 'mapbox-gl'
import { RISK_LEVELS } from '../risk/levels'
import { levelProperty } from './data'

export const HEATMAP_LAYER = 'risk-heatmap'
export const HEATMAP_OPACITY = 0.55 // moderate, so routes and checkpoints stay readable on top

const MAX_LEVEL = 4
const SPACING_MILES = 15 // corridor points are about this far apart
const REFERENCE_LATITUDE = 38 // the middle of the contiguous US
const METERS_PER_MILE = 1609.344
const METERS_PER_PIXEL_AT_ZOOM_0 = 78271.517 // equator, 512 px world (Mapbox GL)
const MIN_RADIUS_PX = 10
const MAX_RADIUS_PX = 440
const RADIUS_OVERLAP = 1.1 // a little more than the spacing, so neighbouring points merge
const RADIUS_ZOOMS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
/**
 * Low (level 0) weighs a little, so calm weather still shows as a faint green band along the
 * corridor; no forecast weighs nothing and draws nothing. Levels 1 to 4 weigh level / 4.
 */
export const LOW_WEIGHT = 0.1
/** How strongly the Low green is drawn: faint, not solid. */
const LOW_ALPHA = 0.7
/**
 * The Low green is held flat over this density range around LOW_WEIGHT, so the dips between
 * neighbouring points do not show as beads: only the outer edge of the band fades out.
 */
export const LOW_BAND_START = LOW_WEIGHT * 0.5
export const LOW_BAND_END = LOW_WEIGHT * 1.2

const asExpression = (value: unknown) => value as ExpressionSpecification

/** How many screen pixels apart two corridor points are at a zoom level. */
export function spacingPx(zoom: number): number {
  const metersPerPixel = (METERS_PER_PIXEL_AT_ZOOM_0 * Math.cos((REFERENCE_LATITUDE * Math.PI) / 180)) / 2 ** zoom
  return (SPACING_MILES * METERS_PER_MILE) / metersPerPixel
}

/** Heatmap point radius for a zoom: grows with the map so neighbouring points keep merging. */
export function radiusForZoom(zoom: number): number {
  return Math.min(MAX_RADIUS_PX, Math.max(MIN_RADIUS_PX, spacingPx(zoom) * RADIUS_OVERLAP))
}

export const HEATMAP_RADIUS = asExpression([
  'interpolate',
  ['exponential', 2],
  ['zoom'],
  ...RADIUS_ZOOMS.flatMap((zoom) => [zoom, radiusForZoom(zoom)]),
])

/**
 * Calibrated in a real browser: with this intensity a lone point of level L renders as level L's
 * color, and so does a continuous band of points 15 miles apart. Level 4 shows as No Travel.
 */
const BASE_INTENSITY = 2.5

/**
 * Where the radius is held up by its minimum (zoomed far out), points sit closer than a radius
 * and stack, which would run hot. Intensity is lowered by the square root of that overlap (the
 * kernel is narrow, so stacking is less than proportional) and a band keeps its color.
 */
export function intensityForZoom(zoom: number): number {
  const overlap = radiusForZoom(zoom) / (RADIUS_OVERLAP * spacingPx(zoom))
  return BASE_INTENSITY / Math.sqrt(Math.max(1, overlap))
}

export const HEATMAP_INTENSITY = asExpression([
  'interpolate',
  ['linear'],
  ['zoom'],
  ...RADIUS_ZOOMS.flatMap((zoom) => [zoom, intensityForZoom(zoom)]),
])

function rgba(hex: string, alpha: number): string {
  const [r, g, b] = [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16))
  return `rgba(${r},${g},${b},${alpha})`
}

/**
 * Transparent, then the shared risk colors, each at the density a lone point of that level
 * reaches: a flat faint Low green around LOW_WEIGHT, and each higher level at level / 4.
 */
export const HEATMAP_COLOR_STOPS: ReadonlyArray<readonly [number, string]> = [
  [0, rgba(RISK_LEVELS[0].color, 0)],
  [LOW_BAND_START, rgba(RISK_LEVELS[0].color, LOW_ALPHA)],
  [LOW_BAND_END, rgba(RISK_LEVELS[0].color, LOW_ALPHA)],
  ...RISK_LEVELS.slice(1).map((level) => [level.level / MAX_LEVEL, level.color] as const),
]

export const HEATMAP_COLOR = asExpression([
  'interpolate',
  ['linear'],
  ['heatmap-density'],
  ...HEATMAP_COLOR_STOPS.flat(),
])

/**
 * The selected hour's level divided by 4, but never less than LOW_WEIGHT for a real level, so
 * Low still draws. No forecast (-1) and a missing value weigh 0 and draw nothing.
 */
export function weightExpression(hour: number): ExpressionSpecification {
  const level = ['coalesce', ['get', levelProperty(hour)], -1]
  return asExpression(['case', ['>=', level, 0], ['max', ['/', level, MAX_LEVEL], LOW_WEIGHT], 0])
}
