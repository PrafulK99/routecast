import 'mapbox-gl/dist/mapbox-gl.css'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import Map, { Layer, type MapMouseEvent, type MapRef, Popup, Source } from 'react-map-gl/mapbox'
import type { AnalyzeResponse } from '../api/types'
import { MAPBOX_TOKEN } from '../config'
import { boundsOf, checkpointsGeoJson, routesGeoJson } from '../map/geojson'
import { CheckpointPopup } from './CheckpointPopup'
import { RiskLegend } from './RiskLegend'

export interface MapViewProps {
  analysis: AnalyzeResponse | undefined
  selectedRouteId: string | undefined
  onSelectRoute: (routeId: string) => void
  /** Extra map layers, e.g. the Phase 5 heatmap. Rendered inside the map. */
  children?: ReactNode
}

const ROUTE_LAYER = 'route-line'
const CHECKPOINT_LAYER = 'checkpoint-circle'
const isSelected = ['==', ['get', 'selected'], 1]
const isUnavailable = ['==', ['get', 'unavailable'], 1]

export default function MapView({ analysis, selectedRouteId, onSelectRoute, children }: MapViewProps) {
  const mapRef = useRef<MapRef>(null)
  const [loaded, setLoaded] = useState(false)
  const [cursor, setCursor] = useState('')
  const [popup, setPopup] = useState<{ requestId: string; routeId: string; index: number } | null>(null)
  const fittedFor = useRef<string | null>(null)

  const routes = analysis?.routes
  const selectedRoute = routes?.find((route) => route.id === selectedRouteId)
  const requestId = analysis?.meta.request_id

  // Rebuilt only when the routes or the selection change, never on map movement.
  const routeData = useMemo(
    () => routesGeoJson(routes ?? [], selectedRouteId ?? ''),
    [routes, selectedRouteId],
  )
  const checkpointData = useMemo(() => checkpointsGeoJson(selectedRoute), [selectedRoute])

  // Fit the view once per analysis, not on every selection or state change.
  useEffect(() => {
    if (!loaded || !routes || !requestId || fittedFor.current === requestId) return
    const bounds = boundsOf(routes)
    if (!bounds) return
    fittedFor.current = requestId
    mapRef.current?.fitBounds(bounds, { padding: 56, duration: 800 })
  }, [loaded, routes, requestId])

  const openCheckpoint =
    popup && popup.requestId === requestId && popup.routeId === selectedRouteId
      ? selectedRoute?.checkpoints.find((checkpoint) => checkpoint.index === popup.index)
      : undefined

  function onClick(event: MapMouseEvent) {
    const features = event.features ?? []
    const checkpoint = features.find((feature) => feature.layer?.id === CHECKPOINT_LAYER)
    if (checkpoint && selectedRouteId && requestId) {
      setPopup({ requestId, routeId: selectedRouteId, index: Number(checkpoint.properties?.index) })
      return
    }
    const route = features.find((feature) => feature.layer?.id === ROUTE_LAYER)
    if (route) onSelectRoute(String(route.properties?.id))
  }

  if (!MAPBOX_TOKEN) {
    return (
      <div className="map-notice" role="alert">
        The map needs a Mapbox public token. Set VITE_MAPBOX_PUBLIC_TOKEN in .env and restart.
      </div>
    )
  }

  return (
    <div className="map-wrap">
      <Map
        ref={mapRef}
        mapboxAccessToken={MAPBOX_TOKEN}
        mapStyle="mapbox://styles/mapbox/light-v11"
        initialViewState={{ longitude: -96, latitude: 38, zoom: 3.2 }}
        interactiveLayerIds={[ROUTE_LAYER, CHECKPOINT_LAYER]}
        cursor={cursor}
        onLoad={() => setLoaded(true)}
        onClick={onClick}
        onMouseEnter={() => setCursor('pointer')}
        onMouseLeave={() => setCursor('')}
      >
        <Source id="routes" type="geojson" data={routeData}>
          <Layer
            id="route-casing"
            type="line"
            layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            paint={{
              'line-color': '#ffffff',
              'line-width': ['case', isSelected, 10, 6],
              'line-opacity': ['case', isSelected, 0.9, 0.4],
            }}
          />
          <Layer
            id={ROUTE_LAYER}
            type="line"
            layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            paint={{
              'line-color': ['get', 'color'],
              'line-width': ['case', isSelected, 6, 3],
              'line-opacity': ['case', isSelected, 1, 0.45],
            }}
          />
        </Source>

        <Source id="checkpoints" type="geojson" data={checkpointData}>
          <Layer
            id={CHECKPOINT_LAYER}
            type="circle"
            paint={{
              'circle-radius': 7,
              'circle-color': ['get', 'color'],
              // Unavailable checkpoints are hollow: no fill, a gray ring.
              'circle-opacity': ['case', isUnavailable, 0, 1],
              'circle-stroke-color': ['case', isUnavailable, '#4b5563', '#ffffff'],
              'circle-stroke-width': ['case', isUnavailable, 2.5, 1.5],
            }}
          />
        </Source>

        {openCheckpoint && (
          <Popup
            longitude={openCheckpoint.lon}
            latitude={openCheckpoint.lat}
            anchor="bottom"
            offset={12}
            maxWidth="280px"
            closeOnClick={false}
            onClose={() => setPopup(null)}
          >
            <CheckpointPopup checkpoint={openCheckpoint} />
          </Popup>
        )}
        {children}
      </Map>
      <RiskLegend />
    </div>
  )
}
