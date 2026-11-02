import type { Route } from '../api/types'
import { formatDuration, formatMiles, formatPercent } from '../format'
import { routeColor } from '../map/geojson'
import { barSegments } from '../riskBar'
import { Icon } from './Icon'

interface Props {
  routes: Route[]
  recommendedId: string
  selectedId: string
  onSelect: (routeId: string) => void
}

export function RouteCards({ routes, recommendedId, selectedId, onSelect }: Props) {
  return (
    <ul className="route-cards" aria-label="Routes">
      {routes.map((route, index) => {
        const segments = barSegments(route)
        const summary = route.summary
        return (
          <li key={route.id}>
            <button
              type="button"
              className={`route-card${route.id === selectedId ? ' selected' : ''}`}
              aria-pressed={route.id === selectedId}
              onClick={() => onSelect(route.id)}
            >
              <span className="route-swatch" style={{ background: routeColor(index) }} aria-hidden="true" />
              <span className="card-head">
                <strong>{route.label}</strong>
                {route.id === recommendedId && (
                  <span className="badge badge-recommended">
                    <Icon name="star" /> Recommended
                  </span>
                )}
                {summary.blocked && (
                  <span className="badge badge-blocked">
                    <Icon name="ban" /> Blocked
                  </span>
                )}
              </span>
              <span className="card-stats">
                <span>{formatDuration(route.duration_s)}</span>
                <span>{formatMiles(route.distance_mi)}</span>
              </span>
              <span
                className="risk-bar"
                role="img"
                aria-label={`Miles by risk level: ${segments
                  .map((segment) => `${segment.name} ${formatMiles(segment.miles)}`)
                  .join(', ')}`}
              >
                {segments.map((segment) => (
                  <span
                    key={segment.name}
                    className={segment.hatched ? 'hatched' : undefined}
                    style={{ flexGrow: segment.miles, background: segment.color }}
                  />
                ))}
              </span>
              <span className="risk-legend">
                {segments.map((segment) => (
                  <span key={segment.name} className="legend-item">
                    <span
                      className={`swatch${segment.hatched ? ' hatched' : ''}`}
                      style={{ background: segment.color }}
                      aria-hidden="true"
                    />
                    {segment.name} {formatMiles(segment.miles)}
                  </span>
                ))}
              </span>
              <span className="card-meta">
                <span>
                  Average risk {summary.avg_risk === null ? 'n/a' : `${summary.avg_risk.toFixed(2)} of 4`}
                </span>
                <span>Forecast coverage {formatPercent(summary.coverage_pct)}</span>
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

/** Placeholder cards while an analysis is running. */
export function RouteCardsSkeleton() {
  return (
    <div className="route-cards" aria-busy="true">
      <p className="sr-only" role="status">
        Analyzing routes…
      </p>
      {[0, 1, 2].map((index) => (
        <div key={index} className="route-card skeleton" aria-hidden="true">
          <span className="skeleton-line wide" />
          <span className="skeleton-line" />
          <span className="skeleton-line bar" />
        </div>
      ))}
    </div>
  )
}
