import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { defaultDeparture } from '../form/validation'
import { callsTo, installFetch, pickPlace, renderWithClient } from '../test/helpers'
import { SEARCH_DELAY_MS } from './PlaceInput'
import { TripForm } from './TripForm'

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const type = (name: string, value: string) =>
  fireEvent.change(screen.getByRole('combobox', { name }), { target: { value } })
const settle = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
const press = (name: string, key: string) => fireEvent.keyDown(screen.getByRole('combobox', { name }), { key })
const submit = () => fireEvent.click(screen.getByRole('button', { name: 'Analyze routes' }))
// The suggestions only: the interval <select> has options of its own.
const suggestionOptions = async () => within(await screen.findByRole('listbox')).getAllByRole('option')

function setup() {
  const fetchMock = installFetch()
  const onSubmit = vi.fn()
  renderWithClient(<TripForm onSubmit={onSubmit} />)
  return { fetchMock, onSubmit }
}

describe('fields', () => {
  test('starts with sensible defaults and the hints', () => {
    setup()

    expect((screen.getByLabelText('Load weight (lb)') as HTMLInputElement).value).toBe('40000')
    expect((screen.getByLabelText('Checkpoint every') as HTMLSelectElement).value).toBe('25')
    expect(within(screen.getByLabelText('Checkpoint every')).getAllByRole('option').map((o) => o.textContent)).toEqual([
      '10 miles',
      '25 miles',
      '50 miles',
    ])
    expect(screen.getByText(/Typical maximum is 80,000 lb/)).toBeTruthy()
    expect((screen.getByLabelText('Departure') as HTMLInputElement).value).toBe(defaultDeparture(new Date()))
  })

  test('limits the departure picker to the current hour through 7 days ahead', () => {
    setup()
    const input = screen.getByLabelText('Departure') as HTMLInputElement

    const span = new Date(input.max).getTime() - new Date(input.min).getTime()

    expect(span).toBeGreaterThan(6.9 * 24 * 3_600_000)
    expect(span).toBeLessThanOrEqual(7 * 24 * 3_600_000 + 3_600_000)
  })
})

describe('place search', () => {
  test('waits for 3 characters and 300 ms of quiet before searching Mapbox', async () => {
    const { fetchMock } = setup()

    type('From', 'Da')
    await settle(SEARCH_DELAY_MS + 50)
    expect(callsTo(fetchMock, '/geocode/')).toHaveLength(0)

    type('From', 'Dall')
    await settle(SEARCH_DELAY_MS - 50)
    expect(callsTo(fetchMock, '/geocode/')).toHaveLength(0)
    await settle(100)
    await suggestionOptions()
    expect(callsTo(fetchMock, '/geocode/')).toHaveLength(1)
  })

  test('only the last of several quick keystrokes is searched', async () => {
    const { fetchMock } = setup()

    for (const text of ['Dal', 'Dall', 'Dalla']) {
      type('From', text)
      await settle(100)
    }
    await settle(SEARCH_DELAY_MS)
    await suggestionOptions()

    const queries = callsTo(fetchMock, '/geocode/').map(([url]) => new URL(String(url)).searchParams.get('q'))
    expect(queries).toEqual(['Dalla'])
  })

  test('lists the suggestions as an accessible listbox', async () => {
    setup()

    type('From', 'Dallas')
    await settle(SEARCH_DELAY_MS)
    const options = await suggestionOptions()

    const input = screen.getByRole('combobox', { name: 'From' })
    expect(options.map((o) => o.textContent)).toEqual(['Dallas, Texas, United States', 'Dallas, Georgia, United States'])
    expect(screen.getByRole('listbox', { name: 'From suggestions' })).toBeTruthy()
    expect(input.getAttribute('aria-expanded')).toBe('true')
    expect(input.getAttribute('aria-controls')).toBe(screen.getByRole('listbox').id)
  })

  test('arrow keys move through the suggestions and Enter chooses one', async () => {
    const { onSubmit } = setup()
    type('From', 'Dallas')
    await settle(SEARCH_DELAY_MS)
    const options = await suggestionOptions()
    const input = screen.getByRole('combobox', { name: 'From' })

    press('From', 'ArrowDown')
    expect(input.getAttribute('aria-activedescendant')).toBe(options[0].id)
    expect(options[0].getAttribute('aria-selected')).toBe('true')
    press('From', 'ArrowDown')
    expect(input.getAttribute('aria-activedescendant')).toBe(options[1].id)
    press('From', 'ArrowDown') // wraps around
    expect(input.getAttribute('aria-activedescendant')).toBe(options[0].id)
    press('From', 'ArrowUp') // and back
    expect(input.getAttribute('aria-activedescendant')).toBe(options[1].id)

    press('From', 'Enter')

    expect((input as HTMLInputElement).value).toBe('Dallas, Georgia, United States')
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(screen.getByText('✓ Location chosen')).toBeTruthy()
    expect(onSubmit).not.toHaveBeenCalled() // Enter chose the place, it did not submit the form
  })

  test('Escape closes the list without choosing', async () => {
    setup()
    type('From', 'Dallas')
    await settle(SEARCH_DELAY_MS)
    await suggestionOptions()

    press('From', 'ArrowDown')
    press('From', 'Escape')

    expect(screen.queryByRole('listbox')).toBeNull()
    expect(screen.queryByText('✓ Location chosen')).toBeNull()
  })

  test('says so when nothing matches or the search fails', async () => {
    setup()
    type('From', 'zzzzz')
    await settle(SEARCH_DELAY_MS)
    expect(await screen.findByText('No places found.')).toBeTruthy()

    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    type('To', 'Boston')
    await settle(SEARCH_DELAY_MS)
    expect(await screen.findByText(/Place search is unavailable/)).toBeTruthy()
  })
})

describe('submitting', () => {
  test('blocks an empty form and explains every problem', async () => {
    const { onSubmit } = setup()
    fireEvent.change(screen.getByLabelText('Load weight (lb)'), { target: { value: 'heavy' } })

    submit()

    expect(onSubmit).not.toHaveBeenCalled()
    expect((await screen.findByRole('alert')).textContent).toBe('Please fix 3 problems above.')
    expect(screen.getByText('Choose a starting point from the suggestions.')).toBeTruthy()
    expect(screen.getByText('Choose a destination from the suggestions.')).toBeTruthy()
    expect(screen.getByText('Load weight must be a whole number of pounds.')).toBeTruthy()
    const from = screen.getByRole('combobox', { name: 'From' })
    expect(from.getAttribute('aria-invalid')).toBe('true')
    expect(from.getAttribute('aria-describedby')).toBeTruthy()
  })

  test('a typed place that was not picked from the list is not accepted', async () => {
    const { onSubmit } = setup()

    type('From', 'Dallas, anywhere')
    type('To', 'Chicago')
    submit()

    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText('Choose a starting point from the suggestions.')).toBeTruthy()
  })

  test('editing a picked place discards the choice', async () => {
    const { onSubmit } = setup()
    await pickPlace('From', 'Dallas', /Dallas, Texas/)
    await pickPlace('To', 'Chicago', /Chicago/)

    type('From', 'Dallas, Texas, United States!')
    submit()

    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText('Choose a starting point from the suggestions.')).toBeTruthy()
  })

  test('messages clear once the problem is fixed', async () => {
    setup()
    fireEvent.change(screen.getByLabelText('Load weight (lb)'), { target: { value: '-5' } })
    submit()
    expect(screen.getByText("Load weight can't be negative.")).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Load weight (lb)'), { target: { value: '45000' } })

    expect(screen.queryByText("Load weight can't be negative.")).toBeNull()
  })

  test('sends the chosen places, the load and the interval, with a UTC departure', async () => {
    const { onSubmit } = setup()
    await pickPlace('From', 'Dallas', /Dallas, Texas/)
    await pickPlace('To', 'Chicago', /Chicago/)
    fireEvent.change(screen.getByLabelText('Load weight (lb)'), { target: { value: '45,000' } })
    fireEvent.change(screen.getByLabelText('Checkpoint every'), { target: { value: '50' } })

    submit()

    expect(onSubmit).toHaveBeenCalledTimes(1)
    const request = onSubmit.mock.calls[0][0]
    expect(request).toMatchObject({
      origin: { lat: 32.7767, lon: -96.797, label: 'Dallas, Texas, United States' },
      destination: { lat: 41.8781, lon: -87.6298, label: 'Chicago, Illinois, United States' },
      load_weight_lb: 45000,
      checkpoint_interval_miles: 50,
    })
    expect(request.departure_time).toBe(new Date(defaultDeparture(new Date())).toISOString())
    expect(request.departure_time).toMatch(/Z$/)
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
