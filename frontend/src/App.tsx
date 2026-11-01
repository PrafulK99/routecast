import { useQuery } from '@tanstack/react-query'
import { Suspense, lazy, useEffect, useState } from 'react'
import { analyze, wakeServer } from './api/client'
import type { AnalyzeRequest } from './api/types'
import './App.css'
import { ErrorPanel } from './components/ErrorPanel'
import { Footer } from './components/Footer'
import { RecommendationBanner } from './components/RecommendationBanner'
import { RouteCards, RouteCardsSkeleton } from './components/RouteCards'
import { TripForm } from './components/TripForm'
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

  // Every analysis starts on its recommended route.
  const selectedRouteId =
    analysis &&
    (selection?.analysisId === analysis.meta.request_id ? selection.routeId : analysis.recommendation.route_id)

  const submit = (request: AnalyzeRequest) => setSubmission((previous) => ({ id: (previous?.id ?? 0) + 1, request }))
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
            {/* Phase 5: the heatmap layer goes here, inside the map. */}
          </MapView>
        </Suspense>
        {/* Phase 5: the heatmap slider goes in this strip along the bottom of the map. */}
        <div className="map-bottom-slot" />
      </main>
    </div>
  )
}
