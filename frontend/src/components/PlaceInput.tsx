import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { MAPBOX_TOKEN } from '../config'
import { type GeocodeSuggestion, MIN_QUERY_LENGTH, geocode } from '../form/geocoding'
import type { PlaceChoice } from '../form/validation'
import { useDebounced } from '../hooks'

export const SEARCH_DELAY_MS = 300

export interface PlaceFieldValue {
  text: string
  selected: PlaceChoice | null // set only by picking a suggestion
}

interface Props {
  label: string
  value: PlaceFieldValue
  onChange: (value: PlaceFieldValue) => void
  error?: string
}

/** A text box with Mapbox autocomplete, following the ARIA combobox pattern. */
export function PlaceInput({ label, value, onChange, error }: Props) {
  const id = useId()
  const listId = `${id}-list`
  const errorId = `${id}-error`
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)

  const term = useDebounced(value.text.trim(), SEARCH_DELAY_MS)
  const searching = !value.selected && term.length >= MIN_QUERY_LENGTH
  const query = useQuery({
    queryKey: ['geocode', term],
    queryFn: ({ signal }) => geocode(term, signal),
    enabled: searching && MAPBOX_TOKEN !== '',
    staleTime: 5 * 60_000,
    retry: false,
  })
  const suggestions: GeocodeSuggestion[] = searching ? (query.data ?? []) : []
  const listVisible = open && suggestions.length > 0

  let status = ''
  if (open && searching) {
    if (!MAPBOX_TOKEN) status = 'Place search needs a Mapbox token (VITE_MAPBOX_PUBLIC_TOKEN).'
    else if (query.isError) status = 'Place search is unavailable right now. Check your connection.'
    else if (query.isFetching) status = 'Searching…'
    else if (query.isSuccess && suggestions.length === 0) status = 'No places found.'
    else if (suggestions.length > 0) status = `${suggestions.length} suggestions. Use the arrow keys to choose.`
  }

  function choose(suggestion: GeocodeSuggestion) {
    onChange({
      text: suggestion.label,
      selected: { label: suggestion.label, lat: suggestion.lat, lon: suggestion.lon },
    })
    setOpen(false)
    setActive(-1)
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (suggestions.length === 0) return
      event.preventDefault()
      setOpen(true)
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((current) => (current + step + suggestions.length) % suggestions.length)
    } else if (event.key === 'Enter' && listVisible && active >= 0) {
      event.preventDefault() // choose the suggestion instead of submitting the form
      choose(suggestions[active])
    } else if (event.key === 'Escape') {
      setOpen(false)
      setActive(-1) // reopening starts from the first suggestion, not from where it was
    }
  }

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="combobox">
        <input
          id={id}
          type="text"
          role="combobox"
          autoComplete="off"
          aria-autocomplete="list"
          aria-expanded={listVisible}
          aria-controls={listId}
          aria-activedescendant={listVisible && active >= 0 ? `${id}-option-${active}` : undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          value={value.text}
          placeholder="Search for a city or address"
          onChange={(event) => {
            onChange({ text: event.target.value, selected: null }) // typing discards a picked place
            setOpen(true)
            setActive(-1)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
        />
        {listVisible && (
          <ul id={listId} role="listbox" aria-label={`${label} suggestions`} className="suggestions">
            {suggestions.map((suggestion, index) => (
              <li
                key={suggestion.id}
                id={`${id}-option-${index}`}
                role="option"
                aria-selected={index === active}
                className={index === active ? 'active' : undefined}
                onMouseDown={(event) => event.preventDefault()} // keep focus so the click lands
                onClick={() => choose(suggestion)}
              >
                {suggestion.label}
              </li>
            ))}
          </ul>
        )}
      </div>
      <p className="field-hint" role="status">
        {status}
        {!status && value.selected ? '✓ Location chosen' : ''}
      </p>
      {error && (
        <p id={errorId} className="field-error">
          {error}
        </p>
      )}
    </div>
  )
}
