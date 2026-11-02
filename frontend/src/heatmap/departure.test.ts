import { describe, expect, test } from 'vitest'
import { heatmapDeparture } from './departure'

const NOW = new Date('2026-11-02T16:20:00Z')

describe('heatmapDeparture', () => {
  test.each([
    ['2026-11-02T18:00:00Z', 'a future departure'],
    ['2026-11-02T17:00:00Z', 'the next full hour'],
    ['2026-11-02T16:20:00Z', 'exactly now'],
    ['2026-11-02T16:05:00Z', 'earlier in the current hour (the server still accepts it)'],
    ['2026-11-02T16:00:00Z', 'the very start of the current hour'],
  ])('keeps %s unchanged (%s)', (original) => {
    expect(heatmapDeparture(original, NOW)).toEqual({ departure: original, adjusted: false })
  })

  test.each([
    ['2026-11-02T15:59:59Z', 'one second before the current hour'],
    ['2026-11-02T14:00:00Z', 'two hours ago'],
    ['2026-10-30T09:30:00Z', 'days ago'],
  ])('replaces %s (%s) with the next full hour', (original) => {
    expect(heatmapDeparture(original, NOW)).toEqual({ departure: '2026-11-02T17:00:00.000Z', adjusted: true })
  })

  test('works from an exact hour', () => {
    const onTheHour = new Date('2026-11-02T16:00:00Z')

    expect(heatmapDeparture('2026-11-02T15:30:00Z', onTheHour)).toEqual({
      departure: '2026-11-02T17:00:00.000Z',
      adjusted: true,
    })
    expect(heatmapDeparture('2026-11-02T16:00:00Z', onTheHour).adjusted).toBe(false)
  })

  test('compares instants, so a UTC offset does not matter', () => {
    // 09:30 at UTC-5 is 14:30 UTC, which is before the current hour (16:00 UTC).
    expect(heatmapDeparture('2026-11-02T09:30:00-05:00', NOW).adjusted).toBe(true)
    // 11:30 at UTC-5 is 16:30 UTC, still to come.
    expect(heatmapDeparture('2026-11-02T11:30:00-05:00', NOW).adjusted).toBe(false)
  })

  test('the replacement is always inside the window the server accepts', () => {
    const { departure } = heatmapDeparture('2020-01-01T00:00:00Z', NOW)

    expect(Date.parse(departure)).toBeGreaterThanOrEqual(Math.floor(NOW.getTime() / 3_600_000) * 3_600_000)
    expect(Date.parse(departure)).toBeLessThanOrEqual(NOW.getTime() + 7 * 24 * 3_600_000)
  })
})
