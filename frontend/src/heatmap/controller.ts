import { HEATMAP_LAYER, weightExpression } from './style'

/** Play advances the slider one hour per tick, from a single timer. */
export const PLAY_INTERVAL_MS = 400

/** The two map calls the controller needs, so tests can pass a fake. */
export interface PaintTarget {
  getLayer(id: string): unknown
  setPaintProperty(layerId: string, name: string, value: unknown): void
}

/**
 * Moves the heatmap to an hour through the map's own API, outside React: the slider
 * calls setHour on every tick and neither App nor MapView re-renders. It remembers
 * the hour, so a map attached later (or a layer added later) starts in the right place.
 */
export class HeatmapController {
  hour = 0
  private map: PaintTarget | null = null

  attach(map: PaintTarget | null): void {
    this.map = map
    this.apply()
  }

  setHour(hour: number): void {
    this.hour = hour
    this.apply()
  }

  private apply(): void {
    if (this.map?.getLayer(HEATMAP_LAYER)) {
      this.map.setPaintProperty(HEATMAP_LAYER, 'heatmap-weight', weightExpression(this.hour))
    }
  }
}
