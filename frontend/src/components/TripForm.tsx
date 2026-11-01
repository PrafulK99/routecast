import { useId, useState } from 'react'
import type { AnalyzeRequest } from '../api/types'
import {
  DEFAULT_INTERVAL,
  DEFAULT_LOAD_LB,
  INTERVALS,
  defaultDeparture,
  departureBounds,
  toLocalInputValue,
  toRequest,
  validateTrip,
} from '../form/validation'
import { PlaceInput, type PlaceFieldValue } from './PlaceInput'

const EMPTY_PLACE: PlaceFieldValue = { text: '', selected: null }

interface Props {
  onSubmit: (request: AnalyzeRequest) => void
}

export function TripForm({ onSubmit }: Props) {
  const ids = useId()
  const [origin, setOrigin] = useState(EMPTY_PLACE)
  const [destination, setDestination] = useState(EMPTY_PLACE)
  const [departure, setDeparture] = useState(() => defaultDeparture(new Date()))
  const [loadWeight, setLoadWeight] = useState(String(DEFAULT_LOAD_LB))
  const [interval, setInterval] = useState(String(DEFAULT_INTERVAL))
  const [showErrors, setShowErrors] = useState(false)
  const [now, setNow] = useState(() => new Date()) // refreshed on submit; the picker's limits use it

  const values = {
    origin: origin.selected,
    destination: destination.selected,
    departure,
    loadWeight,
    interval,
  }
  const errors = showErrors ? validateTrip(values, now) : {}
  const errorCount = Object.keys(errors).length
  const { min, max } = departureBounds(now)

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const current = new Date()
    setNow(current)
    setShowErrors(true)
    if (Object.keys(validateTrip(values, current)).length === 0) onSubmit(toRequest(values))
  }

  return (
    <form className="trip-form" onSubmit={submit} noValidate aria-label="Trip details">
      <PlaceInput label="From" value={origin} onChange={setOrigin} error={errors.origin} />
      <PlaceInput label="To" value={destination} onChange={setDestination} error={errors.destination} />

      <div className="field">
        <label htmlFor={`${ids}-departure`}>Departure</label>
        <input
          id={`${ids}-departure`}
          type="datetime-local"
          value={departure}
          min={toLocalInputValue(min)}
          max={toLocalInputValue(max)}
          aria-invalid={errors.departure ? true : undefined}
          aria-describedby={errors.departure ? `${ids}-departure-error` : `${ids}-departure-hint`}
          onChange={(event) => setDeparture(event.target.value)}
        />
        <p id={`${ids}-departure-hint`} className="field-hint">
          From the current hour up to 7 days ahead, in your local time.
        </p>
        {errors.departure && (
          <p id={`${ids}-departure-error`} className="field-error">
            {errors.departure}
          </p>
        )}
      </div>

      <div className="field-row">
        <div className="field">
          <label htmlFor={`${ids}-load`}>Load weight (lb)</label>
          <input
            id={`${ids}-load`}
            type="text"
            inputMode="numeric"
            value={loadWeight}
            aria-invalid={errors.loadWeight ? true : undefined}
            aria-describedby={errors.loadWeight ? `${ids}-load-error` : `${ids}-load-hint`}
            onChange={(event) => setLoadWeight(event.target.value)}
          />
          <p id={`${ids}-load-hint`} className="field-hint">
            0 to 200,000. Typical maximum is 80,000 lb.
          </p>
          {errors.loadWeight && (
            <p id={`${ids}-load-error`} className="field-error">
              {errors.loadWeight}
            </p>
          )}
        </div>

        <div className="field">
          <label htmlFor={`${ids}-interval`}>Checkpoint every</label>
          <select
            id={`${ids}-interval`}
            value={interval}
            aria-invalid={errors.interval ? true : undefined}
            onChange={(event) => setInterval(event.target.value)}
          >
            {INTERVALS.map((miles) => (
              <option key={miles} value={miles}>
                {miles} miles
              </option>
            ))}
          </select>
          {errors.interval && <p className="field-error">{errors.interval}</p>}
        </div>
      </div>

      {errorCount > 0 && (
        <p role="alert" className="form-summary">
          Please fix {errorCount === 1 ? '1 problem' : `${errorCount} problems`} above.
        </p>
      )}
      <button type="submit" className="primary">
        Analyze routes
      </button>
    </form>
  )
}
