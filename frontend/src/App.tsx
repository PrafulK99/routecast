import { useQuery } from '@tanstack/react-query'
import { Suspense, lazy, useEffect, useState } from 'react'
import { analyze, fetchHeatmap, wakeServer } from './api/client'
import type { AnalyzeRequest } from './api/types'
import './App.css'
import { ErrorPanel } from './components/ErrorPanel'
import { Footer } from './components/Footer'
import { HeatmapControl } from './components/HeatmapControl'
import { HeatmapLayer } from './components/HeatmapLayer'
import { RecommendationBanner } from './components/RecommendationBanner'
import { RouteCards, RouteCardsSkeleton } from './components/RouteCards'
import { TripForm } from './components/TripForm'
import { HeatmapController } from './heatmap/controller'
import { heatmapToGeoJson } from './heatmap/data'
import { useAfterDelay } from './hooks'

// The map library is large; load it after the form is already usable.
const MapView = lazy(() => import('./components/MapView'))

export const WAKING_AFTER_MS = 5_000

interface Submission {
  id: number // a new id per submit or retry, so each gets its own query
  request: AnalyzeRequest
}

export default function App() {
  const [submission, setSubmission] = useState<Submission | null>(null)
  const [selection, setSelection] = useState<{ analysisId: string; routeId: string } | null>(null)

  // Wake a sleeping free-tier server while the user fills in the form.
  useEffect(() => wakeServer(), [])

  // A new submission changes the key: the previous request is aborted and its late
  // reply can never replace newer data.
  const query = useQuery({
    queryKey: ['analyze', submission?.id],
    queryFn: ({ signal }) => analyze(submission!.request, signal),
    enabled: submission !== null,
    retry: false,
    staleTime: Infinity,
  })
  const analysis = query.data
  const waking = useAfterDelay(query.isFetching, WAKING_AFTER_MS)

  // The heatmap loads after, and independently of, the routes: it is keyed to the
  // analysis, so a new analysis drops this query and aborts its request, and the
  // route results never wait on it. Parsed once into a map-ready collection.
  const [heatmapController] = useState(() => new HeatmapController())
  const [heatmapVisible, setHeatmapVisible] = useState(true)
  const noPoints = analysis !== undefined && analysis.corridor_points.length === 0
  const heatmap = useQuery({
    queryKey: ['heatmap', analysis?.meta.request_id],
    queryFn: ({ signal }) =>
      fetchHeatmap(
        {
          points: analysis!.corridor_points,
          departure_time: submission!.request.departure_time,
          load_weight_lb: submission!.request.load_weight_lb,
        },
        signal,
      ),
    enabled: analysis !== undefined && submission !== null && !noPoints,
    select: heatmapToGeoJson,
    retry: false,
    staleTime: Infinity,
  })

  // Every analysis starts on its recommended route.
  const selectedRouteId =
    analysis &&
    (selection?.analysisId === analysis.meta.request_id ? selection.routeId : analysis.recommendation.route_id)

  const submit = (request: AnalyzeRequest) => {
    heatmapController.setHour(0) // a new trip starts the heatmap at +0 h
    setSubmission((previous) => ({ id: (previous?.id ?? 0) + 1, request }))
  }
  const retry = () => setSubmission((previous) => previous && { ...previous, id: previous.id + 1 })

  return (
    <div className="app">
      <aside className="panel">
        <header>
          <h1>Routecast</h1>
          <p className="tagline">Weather-aware truck routing</p>
        </header>

        <TripForm onSubmit={submit} />

        <div className="results" aria-live="polite">
          {waking && (
            <p className="waking" role="status">
              Waking the server, this can take up to a minute
            </p>
          )}
          {!submission && <p className="idle">Enter a trip to compare three routes for weather risk.</p>}
          {query.isFetching && <RouteCardsSkeleton />}
          {query.isError && !query.isFetching && <ErrorPanel error={query.error} onRetry={retry} />}
          {analysis && !query.isFetching && (
            <>
              <RecommendationBanner analysis={analysis} />
              <RouteCards
                routes={analysis.routes}
                recommendedId={analysis.recommendation.route_id}
                selectedId={selectedRouteId!}
                onSelect={(routeId) => setSelection({ analysisId: analysis.meta.request_id, routeId })}
              />
            </>
          )}
        </div>
        <Footer />
      </aside>

      <main className="map-area">
        <Suspense fallback={<div className="map-notice">Loading map…</div>}>
          <MapView
            analysis={query.isFetching ? undefined : analysis}
            selectedRouteId={selectedRouteId}
            onSelectRoute={(routeId) =>
              analysis && setSelection({ analysisId: analysis.meta.request_id, routeId })
            }
          >
            {heatmap.data && !heatmap.data.isEmpty && (
              <HeatmapLayer data={heatmap.data} visible={heatmapVisible} controller={heatmapController} />
            )}
          </MapView>
        </Suspense>
        <div className="map-bottom-slot">
          {analysis && !query.isFetching && (
            <HeatmapControl
              key={analysis.meta.request_id}
              data={heatmap.data}
              loading={heatmap.isFetching}
              error={heatmap.isError ? heatmap.error : null}
              noPoints={noPoints}
              onRetry={() => void heatmap.refetch()}
              controller={heatmapController}
              visible={heatmapVisible}
              onToggleVisible={() => setHeatmapVisible((visible) => !visible)}
              loadWeight={submission!.request.load_weight_lb}
            />
          )}
        </div>
      </main>
    </div>
  )
}
