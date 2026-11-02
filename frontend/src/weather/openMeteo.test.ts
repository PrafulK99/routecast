import { describe, expect, test, vi } from 'vitest'
import {
  BATCH_SIZE,
  CACHE_TTL_MS,
  MAX_PARALLEL,
  type HourWindow,
  WeatherError,
  classifyRateLimit,
  createWeatherClient,
} from './openMeteo'

const NOW = Date.UTC(2026, 10, 2, 12, 0) // 2026-11-02T12:00Z
const WINDOW: HourWindow = { first_hour: '2026-11-02T14:00:00Z', last_hour: '2026-11-04T14:00:00Z' }

function hours(count: number, from = Date.UTC(2026, 10, 2, 0)) {
  return Array.from({ length: count }, (_, h) => new Date(from + h * 3_600_000).toISOString().slice(0, 16))
}

/** An Open-Meteo reply for a request URL: 72 hours from 2026-11-02T00:00, wind = the hour index. */
function reply(url: string, init?: RequestInit, count = 72) {
  void init
  const params = new URL(url).searchParams
  const lats = params.get('latitude')!.split(',')
  const lons = params.get('longitude')!.split(',')
  const time = hours(count)
  const locations = lats.map((lat, i) => ({
    latitude: Number(lat) + 0.01, // Open-Meteo reports the grid point it snapped to
    longitude: Number(lons[i]) + 0.01,
    hourly: {
      time,
      wind_speed_10m: time.map((_, h) => h),
      rain: time.map(() => 0),
      showers: time.map(() => 0),
      snowfall: time.map(() => null),
    },
  }))
  return new Response(JSON.stringify(locations.length === 1 ? locations[0] : locations), { status: 200 })
}

const cellsOf = (count: number, lat0 = 30) => Array.from({ length: count }, (_, i) => [lat0 + i * 0.1, -99.5])
const noSleep = () => Promise.resolve()
const never = new AbortController().signal

function clientWith(fetchFn: (url: string, init?: RequestInit) => Promise<Response> | Response, now = NOW) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => fetchFn(String(input), init))
  return {
    mock,
    client: createWeatherClient({ fetchFn: mock as unknown as typeof fetch, now: () => now, sleep: noSleep }),
  }
}

const urlsOf = (mock: ReturnType<typeof clientWith>['mock']) => mock.mock.calls.map(([input]) => new URL(String(input)))

describe('requests', () => {
  test('asks Open-Meteo for the same variables, units and time zone as the server does', async () => {
    const { client, mock } = clientWith(reply)

    await client.fetchWeather(cellsOf(2), WINDOW, never)

    const url = urlsOf(mock)[0]
    expect(url.origin + url.pathname).toBe('https://api.open-meteo.com/v1/forecast')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      latitude: '30,30.1',
      longitude: '-99.5,-99.5',
      hourly: 'wind_speed_10m,rain,showers,snowfall',
      wind_speed_unit: 'mph',
      precipitation_unit: 'inch',
      timezone: 'GMT',
      forecast_days: '3', // reaches 2026-11-04, from today 2026-11-02
    })
  })

  test('forecast days are capped at 16 and never below 1', async () => {
    const far = { first_hour: WINDOW.first_hour, last_hour: '2026-12-31T00:00:00Z' }
    const { client, mock } = clientWith(reply)

    await client.fetchWeather(cellsOf(1), far, never)
    await client.fetchWeather(cellsOf(1, 40), { first_hour: WINDOW.first_hour, last_hour: '2026-11-02T14:00:00Z' }, never)

    expect(urlsOf(mock).map((u) => u.searchParams.get('forecast_days'))).toEqual(['16', '1'])
  })

  test('125 cells go out in batches of 50, 50 and 25 in order', async () => {
    const { client, mock } = clientWith(reply)

    const result = await client.fetchWeather(cellsOf(125), WINDOW, never)

    expect(BATCH_SIZE).toBe(50)
    expect(urlsOf(mock).map((u) => u.searchParams.get('latitude')!.split(',').length)).toEqual([50, 50, 25])
    expect(result).toHaveLength(125)
  })

  test('a single cell is read from the object Open-Meteo answers with', async () => {
    const { client } = clientWith(reply)

    const [entry] = await client.fetchWeather(cellsOf(1), WINDOW, never)

    expect(entry.wind_speed_10m.length).toBeGreaterThan(0)
  })

  test('never more than 4 requests are in flight, and 4 are used when there are enough batches', async () => {
    let inFlight = 0
    let peak = 0
    const { client } = clientWith(async (url) => {
      inFlight++
      peak = Math.max(peak, inFlight)
      await new Promise((resolve) => setTimeout(resolve, 5))
      inFlight--
      return reply(url)
    })

    await client.fetchWeather(cellsOf(50 * 10), WINDOW, never)

    expect(MAX_PARALLEL).toBe(4)
    expect(peak).toBe(4)
  })
})

describe('the result', () => {
  test('is trimmed to the requested hours, values kept aligned with their times', async () => {
    const { client } = clientWith(reply)
    const window = { first_hour: '2026-11-02T10:00:00Z', last_hour: '2026-11-02T12:00:00Z' }

    const [entry] = await client.fetchWeather(cellsOf(1), window, never)

    expect(entry.time).toEqual(['2026-11-02T10:00', '2026-11-02T11:00', '2026-11-02T12:00'])
    expect(entry.wind_speed_10m).toEqual([10, 11, 12]) // wind = hour index in the fake reply
    expect(entry.rain).toHaveLength(3)
    expect(entry.showers).toHaveLength(3)
    expect(entry.snowfall).toEqual([null, null, null]) // a null stays null
  })

  test('uses the requested cell coordinates, not the ones Open-Meteo snapped to', async () => {
    const { client } = clientWith(reply)

    const result = await client.fetchWeather([[30.0, -99.6], [30.1, -99.5]], WINDOW, never)

    expect(result.map((e) => [e.lat, e.lon])).toEqual([[30.0, -99.6], [30.1, -99.5]])
  })
})

describe('failures', () => {
  test('a network error is retried once, then the batch succeeds', async () => {
    let attempts = 0
    const { client, mock } = clientWith((url) => {
      if (attempts++ === 0) throw new TypeError('network down')
      return reply(url)
    })

    const result = await client.fetchWeather(cellsOf(2), WINDOW, never)

    expect(mock).toHaveBeenCalledTimes(2)
    expect(result).toHaveLength(2)
  })

  test('a 5xx is retried once', async () => {
    let attempts = 0
    const { client, mock } = clientWith((url) => (attempts++ === 0 ? new Response('', { status: 503 }) : reply(url)))

    expect(await client.fetchWeather(cellsOf(1), WINDOW, never)).toHaveLength(1)
    expect(mock).toHaveBeenCalledTimes(2)
  })

  test('a malformed reply is retried once', async () => {
    let attempts = 0
    const { client, mock } = clientWith((url) => (attempts++ === 0 ? new Response('not json', { status: 200 }) : reply(url)))

    expect(await client.fetchWeather(cellsOf(1), WINDOW, never)).toHaveLength(1)
    expect(mock).toHaveBeenCalledTimes(2)
  })

  test('a 4xx other than 429 is not retried; the batch is left out', async () => {
    const { client, mock } = clientWith((url) =>
      url.includes('latitude=30%2C') ? new Response('{}', { status: 400 }) : reply(url),
    )

    const result = await client.fetchWeather([...cellsOf(50), ...cellsOf(2, 40)], WINDOW, never)

    expect(mock).toHaveBeenCalledTimes(2) // one try for the bad batch, one for the good
    expect(result.map((e) => e.lat)).toEqual([40, 40.1])
  })

  test('a batch that fails twice is left out and the others are still returned', async () => {
    const { client, mock } = clientWith((url) => {
      if (url.includes('latitude=30%2C')) throw new TypeError('network down')
      return reply(url)
    })

    const result = await client.fetchWeather([...cellsOf(50), ...cellsOf(2, 40)], WINDOW, never)

    expect(mock).toHaveBeenCalledTimes(3) // the bad batch twice, the good one once
    expect(result).toHaveLength(2)
  })

  test('when nothing at all can be fetched it throws, rather than returning an empty list', async () => {
    const { client } = clientWith(() => new Response('', { status: 500 }))

    await expect(client.fetchWeather(cellsOf(3), WINDOW, never)).rejects.toMatchObject({
      name: 'Error',
      kind: 'unreachable',
    })
  })

  test('a request that times out counts as a failed attempt', async () => {
    vi.useFakeTimers()
    try {
      let attempts = 0
      const { client } = clientWith((url, init) => {
        if (attempts++ < 2) {
          return new Promise<Response>((_, reject) =>
            init!.signal!.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError'))),
          )
        }
        return reply(url)
      })

      const pending = client.fetchWeather(cellsOf(1), WINDOW, never)
      const outcome = expect(pending).rejects.toMatchObject({ kind: 'unreachable' })
      await vi.advanceTimersByTimeAsync(10_000)
      await vi.advanceTimersByTimeAsync(10_000)
      await outcome
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('rate limits (429)', () => {
  test.each([
    ['Minutely API request limit exceeded. Please try again in one minute.', 'minutely'],
    ['Hourly API request limit exceeded. Please try again in the next hour.', 'hourly'],
    ['Daily API request limit exceeded. Please try again tomorrow.', 'daily'],
    ['Something else is wrong', 'unknown'],
  ])('"%s" is %s', async (reason, limit) => {
    const { client, mock } = clientWith(
      () => new Response(JSON.stringify({ error: true, reason }), { status: 429 }),
    )

    const error = await client.fetchWeather(cellsOf(2), WINDOW, never).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(WeatherError)
    expect(error).toMatchObject({ kind: 'rate_limited', limit })
    expect(mock).toHaveBeenCalledTimes(1) // never retried
  })

  test('a 429 without a readable reason is a rate limit of unknown kind', async () => {
    const { client } = clientWith(() => new Response('<html>', { status: 429 }))

    await expect(client.fetchWeather(cellsOf(1), WINDOW, never)).rejects.toMatchObject({
      kind: 'rate_limited',
      limit: 'unknown',
    })
  })

  test('a 429 whose body the browser cannot read (blocked by CORS) is "unreachable"', async () => {
    // Without CORS headers a browser reports the whole response as a network error.
    const { client, mock } = clientWith(() => {
      throw new TypeError('Failed to fetch')
    })

    await expect(client.fetchWeather(cellsOf(1), WINDOW, never)).rejects.toMatchObject({ kind: 'unreachable' })
    expect(mock).toHaveBeenCalledTimes(2) // the one retry
  })

  test('a 429 stops the batches that have not started', async () => {
    const { client, mock } = clientWith(
      () => new Response(JSON.stringify({ reason: 'Daily API request limit exceeded' }), { status: 429 }),
    )

    await expect(client.fetchWeather(cellsOf(50 * 12), WINDOW, never)).rejects.toMatchObject({ limit: 'daily' })

    expect(mock.mock.calls.length).toBeLessThanOrEqual(MAX_PARALLEL)
  })

  test('classifyRateLimit reads the words in any case', () => {
    expect(classifyRateLimit('MINUTELY limit')).toBe('minutely')
    expect(classifyRateLimit('hourly')).toBe('hourly')
    expect(classifyRateLimit('daily')).toBe('daily')
    expect(classifyRateLimit(undefined)).toBe('unknown')
    expect(classifyRateLimit(42)).toBe('unknown')
  })
})

describe('the cell cache', () => {
  test('fetches only the cells not already held, matching by exact coordinates', async () => {
    const { client, mock } = clientWith(reply)
    const routeCells = [[30, -99.6], [30, -99.2], [30.2, -99.6]]
    const corridorCells = [[30, -99.6], [30, -99.7], [30.2, -99.6], [30.4, -99.3]]

    await client.fetchWeather(routeCells, WINDOW, never)
    const result = await client.fetchWeather(corridorCells, WINDOW, never)

    const second = urlsOf(mock)[1].searchParams
    expect(mock).toHaveBeenCalledTimes(2)
    expect(second.get('latitude')).toBe('30,30.4') // only (30, -99.7) and (30.4, -99.3) were new
    expect(second.get('longitude')).toBe('-99.7,-99.3')
    expect(result.map((e) => [e.lat, e.lon])).toEqual(corridorCells) // all four, in the order asked
  })

  test('makes no request at all when every cell is held', async () => {
    const { client, mock } = clientWith(reply)

    await client.fetchWeather(cellsOf(3), WINDOW, never)
    await client.fetchWeather(cellsOf(3), WINDOW, never)

    expect(mock).toHaveBeenCalledTimes(1)
  })

  test('a held series is trimmed to the new window', async () => {
    const { client } = clientWith(reply)
    await client.fetchWeather(cellsOf(1), WINDOW, never)

    const [entry] = await client.fetchWeather(
      cellsOf(1),
      { first_hour: '2026-11-03T00:00:00Z', last_hour: '2026-11-03T02:00:00Z' },
      never,
    )

    expect(entry.time).toEqual(['2026-11-03T00:00', '2026-11-03T01:00', '2026-11-03T02:00'])
  })

  test('is refetched once 30 minutes have passed', async () => {
    let now = NOW
    const mock = vi.fn(async (input: RequestInfo | URL) => reply(String(input)))
    const client = createWeatherClient({ fetchFn: mock as unknown as typeof fetch, now: () => now, sleep: noSleep })

    await client.fetchWeather(cellsOf(1), WINDOW, never)
    now += CACHE_TTL_MS - 1
    await client.fetchWeather(cellsOf(1), WINDOW, never)
    expect(mock).toHaveBeenCalledTimes(1)
    now += 2
    await client.fetchWeather(cellsOf(1), WINDOW, never)

    expect(mock).toHaveBeenCalledTimes(2)
  })

  test('is refetched when the held hours do not reach the window', async () => {
    const { client, mock } = clientWith((url, init) => reply(url, init, 30)) // only until 2026-11-03T05:00

    await client.fetchWeather(cellsOf(1), { first_hour: WINDOW.first_hour, last_hour: '2026-11-03T05:00:00Z' }, never)
    await client.fetchWeather(cellsOf(1), WINDOW, never)

    expect(mock).toHaveBeenCalledTimes(2)
  })

  test('failed batches are not cached', async () => {
    let fail = true
    const { client, mock } = clientWith((url) => (fail ? new Response('', { status: 500 }) : reply(url)))

    await expect(client.fetchWeather(cellsOf(1), WINDOW, never)).rejects.toBeInstanceOf(WeatherError)
    fail = false
    await client.fetchWeather(cellsOf(1), WINDOW, never)

    expect(mock).toHaveBeenCalledTimes(3)
  })
})

describe('cancellation', () => {
  test('aborting rejects with an AbortError, aborts the in-flight requests and starts no more batches', async () => {
    const controller = new AbortController()
    const seen: AbortSignal[] = []
    const { client, mock } = clientWith(
      (_, init) =>
        new Promise<Response>((_resolve, reject) => {
          seen.push(init!.signal!)
          init!.signal!.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    )

    const pending = client.fetchWeather(cellsOf(50 * 12), WINDOW, controller.signal)
    const outcome = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    await new Promise((resolve) => setTimeout(resolve, 0))
    controller.abort()
    await outcome

    expect(mock).toHaveBeenCalledTimes(MAX_PARALLEL)
    expect(seen.every((signal) => signal.aborted)).toBe(true)
  })

  test('an already aborted signal makes no request', async () => {
    const controller = new AbortController()
    controller.abort()
    const { client, mock } = clientWith(reply)

    await expect(client.fetchWeather(cellsOf(3), WINDOW, controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    })
    expect(mock).not.toHaveBeenCalled()
  })
})
