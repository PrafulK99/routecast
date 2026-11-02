import type { Checkpoint } from '../api/types'
import { type TimeOptions, formatLocalTime, formatRate, formatWind } from '../format'
import { levelInfo } from '../risk/levels'

interface Props {
  checkpoint: Checkpoint
  time?: TimeOptions // the viewer's zone by default; tests pass one
}

export function CheckpointPopup({ checkpoint, time }: Props) {
  const { risk } = checkpoint
  const info = levelInfo(risk.level)
  const unavailable = risk.level === null

  return (
    <div className="popup">
      <p className="popup-title">
        <strong>Checkpoint {checkpoint.index + 1}</strong>
        <span className="popup-mile"> · mile {checkpoint.mile.toFixed(1)}</span>
      </p>
      <p className="popup-level">
        <span className="level-pill">
          <span
            className={`swatch${unavailable ? ' hollow' : ''}`}
            style={unavailable ? { borderColor: info.color } : { background: info.color }}
            aria-hidden="true"
          />
          <strong>{info.name}</strong>
        </span>
        {risk.factor && <span className="popup-factor"> (set by {risk.factor})</span>}
      </p>
      <dl>
        <div>
          <dt>Arrival (ETA)</dt>
          <dd>{formatLocalTime(checkpoint.eta, time)}</dd>
        </div>
        <div>
          <dt>Forecast hour</dt>
          <dd>{formatLocalTime(checkpoint.forecast_hour, time)}</dd>
        </div>
        {!unavailable && (
          <>
            <div>
              <dt>Wind</dt>
              <dd>{formatWind(checkpoint.wind_mph)}</dd>
            </div>
            <div>
              <dt>Rain</dt>
              <dd>{formatRate(checkpoint.rain_in_hr)}</dd>
            </div>
            <div>
              <dt>Snow</dt>
              <dd>{formatRate(checkpoint.snow_in_hr)}</dd>
            </div>
          </>
        )}
      </dl>
      {unavailable && <p className="popup-note">No forecast covers this time, so the risk is unknown.</p>}
      {checkpoint.status === 'partial' && (
        <p className="popup-note">Partial forecast: some values are missing, so the level uses what is known.</p>
      )}
      {risk.load_rule_applied && (
        <p className="popup-note">Your load weight raised the wind level at this checkpoint.</p>
      )}
    </div>
  )
}
