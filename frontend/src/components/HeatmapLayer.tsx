import { useEffect } from 'react'
import { Layer, Source, useMap } from 'react-map-gl/mapbox'
import type { HeatmapController } from '../heatmap/controller'
import type { HeatmapData } from '../heatmap/data'
import {
  HEATMAP_COLOR,
  HEATMAP_INTENSITY,
  HEATMAP_LAYER,
  HEATMAP_OPACITY,
  HEATMAP_RADIUS,
  weightExpression,
} from '../heatmap/style'
import { ROUTE_CASING_LAYER } from '../map/layers'

interface Props {
  data: HeatmapData
  visible: boolean
  controller: HeatmapController
}

/**
 * The heatmap, drawn in MapView's children slot. The slider never reaches this
 * component: it moves the layer through the controller, straight on the map.
 */
export function HeatmapLayer({ data, visible, controller }: Props) {
  const { current: map } = useMap()

  // Hand the map to the controller so slider ticks can set the paint property directly.
  useEffect(() => {
    controller.attach(map?.getMap() ?? null)
    return () => controller.attach(null)
  }, [map, controller])

  return (
    <Source id="heatmap" type="geojson" data={data.collection}>
      <Layer
        id={HEATMAP_LAYER}
        type="heatmap"
        beforeId={ROUTE_CASING_LAYER} // under the routes and checkpoints
        layout={{ visibility: visible ? 'visible' : 'none' }}
        paint={{
          'heatmap-weight': weightExpression(controller.hour),
          'heatmap-color': HEATMAP_COLOR,
          'heatmap-radius': HEATMAP_RADIUS,
          'heatmap-opacity': HEATMAP_OPACITY,
          'heatmap-intensity': HEATMAP_INTENSITY,
        }}
      />
    </Source>
  )
}
