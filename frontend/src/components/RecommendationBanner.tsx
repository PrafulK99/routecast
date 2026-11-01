import type { AnalyzeResponse } from '../api/types'

interface Props {
  analysis: AnalyzeResponse
}

export function RecommendationBanner({ analysis }: Props) {
  const { recommendation, meta, routes } = analysis
  const recommended = routes.find((route) => route.id === recommendation.route_id)
  const warnings = meta.warnings
  // Partial results: some stretch of a route has no forecast.
  const partial = routes.some((route) => route.summary.coverage_pct < 100)

  return (
    <section className="banner" aria-labelledby="recommendation-title">
      {recommendation.all_blocked && (
        <div className="banner-alert" role="alert">
          <strong>
            <span aria-hidden="true">⚠</span> No safe route: every route has No Travel conditions
          </strong>
          <p>Do not treat the recommended route as safe. Delay the trip or change the plan.</p>
        </div>
      )}
      <h2 id="recommendation-title">
        {recommendation.all_blocked ? 'Least blocked route' : 'Recommended'}: {recommended?.label}
      </h2>
      <ul className="reasons">
        {recommendation.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
      {warnings.length > 0 && (
        <details className="warnings" open={partial}>
          <summary>
            {partial ? 'Partial results: ' : ''}
            {warnings.length === 1 ? '1 warning' : `${warnings.length} warnings`}
          </summary>
          <ul>
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
