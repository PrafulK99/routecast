import { afterEach, describe, expect, test, vi } from 'vitest'
import { geocode, parseGeocode } from './geocoding'

// Trimmed from a real Mapbox Geocoding v6 response.
const REAL = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      id: 'abc',
      geometry: { type: 'Point', coordinates: [-96.798183, 32.780617] },
      properties: {
        mapbox_id: 'abc',
        name: '1600 Main Street',
        full_address: '1600 Main Street, Dallas, Texas 75201, United States',
        place_formatted: 'Dallas, Texas 75201, United States',
        coordinates: { longitude: -96.798183, latitude: 32.780617 },
      },
    },
  ],
}

afterEach(() => vi.unstubAllGlobals())

describe('parseGeocode', () => {
  test('reads the label and coordinates of a v6 feature', () => {
    expect(parseGeocode(REAL)).toEqual([
      {
        id: 'abc',
        label: '1600 Main Street, Dallas, Texas 75201, United States',
        lat: 32.780617,
        lon: -96.798183,
      },
    ])
  })

  test('falls back to the geometry and to name + place', () => {
    const body = {
      features: [
        {
          geometry: { coordinates: [-87.6, 41.9] },
          properties: { name: 'Chicago', place_formatted: 'Illinois, United States' },
        },
      ],
    }

    expect(parseGeocode(body)).toMatchObject([{ label: 'Chicago, Illinois, United States', lat: 41.9, lon: -87.6 }])
  })

  test('drops features without coordinates or a label, and copes with no features', () => {
    const body = {
      features: [
        { properties: { full_address: 'Nowhere' } },
        { properties: { coordinates: { latitude: 1, longitude: 2 } } },
      ],
    }

    expect(parseGeocode(body)).toEqual([])
    expect(parseGeocode({})).toEqual([])
  })
})

describe('geocode', () => {
  test('asks Mapbox for five autocomplete matches with the public token', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => REAL })
    vi.stubGlobal('fetch', fetchMock)
    const signal = new AbortController().signal

    const result = await geocode('1600 main', signal, 'pk.test')

    const [url, init] = fetchMock.mock.calls[0]
    const parsed = new URL(url)
    expect(parsed.origin + parsed.pathname).toBe('https://api.mapbox.com/search/geocode/v6/forward')
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      q: '1600 main',
      autocomplete: 'true',
      limit: '5',
      access_token: 'pk.test',
    })
    expect(init.signal).toBe(signal)
    expect(result).toHaveLength(1)
  })

  test('fails on an error status and when there is no token', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))
    const signal = new AbortController().signal

    await expect(geocode('dallas', signal, 'pk.test')).rejects.toThrow('401')
    await expect(geocode('dallas', signal, '')).rejects.toThrow('missing token')
  })
})
