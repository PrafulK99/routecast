import { describe, expect, test } from 'vitest'
import {
  type PlaceChoice,
  type TripFormValues,
  defaultDeparture,
  departureBounds,
  parseLoad,
  toLocalInputValue,
  toRequest,
  validateTrip,
} from './validation'

const NOW = new Date('2026-11-02T12:30:00Z')
const MILE = 1 / 69.09 // degrees of latitude per mile
const dallas: PlaceChoice = { label: 'Dallas, Texas, United States', lat: 32.7767, lon: -96.797 }
const chicago: PlaceChoice = { label: 'Chicago, Illinois, United States', lat: 41.8781, lon: -87.6298 }

/** A datetime-local value for an exact UTC instant, whatever the machine's time zone. */
const local = (iso: string) => toLocalInputValue(new Date(iso))

const valid: TripFormValues = {
  origin: dallas,
  destination: chicago,
  departure: local('2026-11-02T14:00:00Z'),
  loadWeight: '40000',
  interval: '25',
}

const errorsFor = (changes: Partial<TripFormValues>) => validateTrip({ ...valid, ...changes }, NOW)

describe('validateTrip', () => {
  test('accepts a valid trip', () => {
    expect(errorsFor({})).toEqual({})
  })

  test('both places must be chosen from the suggestions', () => {
    expect(errorsFor({ origin: null }).origin).toMatch(/starting point/)
    expect(errorsFor({ destination: null }).destination).toMatch(/destination/)
  })

  test.each([
    [0, false],
    [0.4, false],
    [0.49, false],
    [0.6, true],
    [5, true],
  ])('places %s miles apart: valid=%s', (miles, ok) => {
    const near = { ...dallas, lat: dallas.lat + miles * MILE }

    const errors = errorsFor({ destination: near })

    expect(errors.destination === undefined).toBe(ok)
    if (!ok) expect(errors.destination).toMatch(/at least 0\.5 mile/)
  })

  describe('departure window: the current UTC hour to 7 days ahead', () => {
    test.each([
      ['2026-11-02T12:00:00Z', true], // start of the current hour
      ['2026-11-02T14:00:00Z', true],
      ['2026-11-09T12:30:00Z', true], // exactly 7 days from now
      ['2026-11-02T11:59:00Z', false],
      ['2026-11-01T14:00:00Z', false],
      ['2026-11-09T12:31:00Z', false],
      ['2026-12-01T00:00:00Z', false],
    ])('%s -> valid=%s', (iso, ok) => {
      const errors = errorsFor({ departure: local(iso) })

      expect(errors.departure === undefined).toBe(ok)
      if (!ok) expect(errors.departure).toMatch(/^Departure must be between/)
    })

    test.each(['', 'tomorrow'])('"%s" asks for a date and time', (departure) => {
      expect(errorsFor({ departure }).departure).toBe('Choose a departure date and time.')
    })

    test('bounds are the start of the UTC hour and 7 days ahead', () => {
      const { min, max } = departureBounds(NOW)

      expect(min.toISOString()).toBe('2026-11-02T12:00:00.000Z')
      expect(max.toISOString()).toBe('2026-11-09T12:30:00.000Z')
    })

    test.each(['2026-11-02T12:00:00Z', '2026-11-02T12:59:59Z', '2026-11-02T23:30:00Z'])(
      'the default departure for %s is after now and is valid',
      (iso) => {
        const now = new Date(iso)
        const departure = defaultDeparture(now)

        expect(new Date(departure) > now).toBe(true)
        expect(validateTrip({ ...valid, departure }, now).departure).toBeUndefined()
      },
    )
  })

  describe('load weight: a whole number of pounds from 0 to 200,000', () => {
    test.each(['0', '1', '80000', '200000', '40,000', ' 5000 '])('%j is accepted', (loadWeight) => {
      expect(errorsFor({ loadWeight }).loadWeight).toBeUndefined()
    })

    test.each([
      ['', 'Enter the load weight in pounds.'],
      ['   ', 'Enter the load weight in pounds.'],
      ['abc', 'Load weight must be a whole number of pounds.'],
      ['1.5', 'Load weight must be a whole number of pounds.'],
      ['12e3', 'Load weight must be a whole number of pounds.'],
      ['-1', "Load weight can't be negative."],
      ['200001', 'Load weight can be at most 200,000 lb.'],
    ])('%j -> %s', (loadWeight, message) => {
      expect(errorsFor({ loadWeight }).loadWeight).toBe(message)
    })

    test('parseLoad', () => {
      expect(parseLoad('40,000')).toBe(40000)
      expect(parseLoad('x')).toBeNull()
      expect(parseLoad('')).toBeNull()
    })
  })

  test.each(['10', '25', '50'])('interval %s is accepted', (interval) => {
    expect(errorsFor({ interval }).interval).toBeUndefined()
  })

  test.each(['', '15', '100', 'far'])('interval %j is rejected', (interval) => {
    expect(errorsFor({ interval }).interval).toBe('Choose 10, 25 or 50 miles.')
  })

  test('reports every problem at once', () => {
    const errors = errorsFor({ origin: null, loadWeight: '-5', interval: '7', departure: '' })

    expect(Object.keys(errors).sort()).toEqual(['departure', 'interval', 'loadWeight', 'origin'])
  })
})

describe('toRequest', () => {
  test('builds the analyze body with a UTC ISO departure', () => {
    const request = toRequest(valid)

    expect(request).toEqual({
      origin: { lat: 32.7767, lon: -96.797, label: 'Dallas, Texas, United States' },
      destination: { lat: 41.8781, lon: -87.6298, label: 'Chicago, Illinois, United States' },
      departure_time: '2026-11-02T14:00:00.000Z',
      load_weight_lb: 40000,
      checkpoint_interval_miles: 25,
    })
    expect(request.departure_time).toMatch(/(Z|[+-]\d\d:\d\d)$/) // carries a UTC offset
  })

  test('reads a load typed with a comma and an interval from the select', () => {
    const request = toRequest({ ...valid, loadWeight: '45,000', interval: '50' })

    expect(request.load_weight_lb).toBe(45000)
    expect(request.checkpoint_interval_miles).toBe(50)
  })
})
