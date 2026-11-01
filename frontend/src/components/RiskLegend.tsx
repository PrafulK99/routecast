import { RISK_LEVELS, UNAVAILABLE } from '../risk/levels'

/** The map's key: every checkpoint color with its level name; unavailable is hollow. */
export function RiskLegend() {
  return (
    <div className="map-legend" aria-label="Checkpoint risk levels">
      <strong>Checkpoint risk</strong>
      <ul>
        {RISK_LEVELS.map((level) => (
          <li key={level.level}>
            <span className="swatch" style={{ background: level.color }} aria-hidden="true" />
            {level.name}
          </li>
        ))}
        <li>
          <span className="swatch hollow" style={{ borderColor: UNAVAILABLE.color }} aria-hidden="true" />
          {UNAVAILABLE.name}
        </li>
      </ul>
    </div>
  )
}
