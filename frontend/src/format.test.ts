import { describe, expect, test } from 'vitest'
import {
  formatDuration,
  formatLocalTime,
  formatMiles,
  formatPercent,
  formatRate,
  formatWind,
} from './format'

const plain = (text: string) => text.replace(/\s/g, ' ') // newer ICU uses a narrow no-break space

describe('formatDuration', () => {
  test.each([
    [15797, '4 h 23 min'],
    [3600, '1 h 0 min'],
    [3599, '1 h 0 min'], // rounds to the nearest minute
    [1380, '23 min'],
    [0, '0 min'],
    [86400 + 120, '24 h 2 min'],
  ])('%s s is %s', (seconds, expected) => expect(formatDuration(seconds)).toBe(expected))
})

describe('number formatting', () => {
  test('miles', () => {
    expect(formatMiles(967.5)).toBe('968 mi')
    expect(formatMiles(5.25)).toBe('5.3 mi')
    expect(formatMiles(1234.4)).toBe('1,234 mi')
  })

  test('percent never rounds up to 100', () => {
    expect(formatPercent(100)).toBe('100%')
    expect(formatPercent(99.96)).toBe('99.9%')
    expect(formatPercent(68.75)).toBe('68.7%')
  })

  test('weather values keep their precision and show n/a when missing', () => {
    expect(formatRate(0.098)).toBe('0.098 in/hr')
    expect(formatRate(0)).toBe('0 in/hr')
    expect(formatRate(null)).toBe('n/a')
    expect(formatWind(12.34)).toBe('12.3 mph')
    expect(formatWind(null)).toBe('n/a')
  })
})

describe('formatLocalTime', () => {
  test('converts a UTC instant to the given zone and labels it', () => {
    const iso = '2026-11-02T14:27:30Z'

    expect(plain(formatLocalTime(iso, { timeZone: 'America/Chicago', locale: 'en-US' }))).toBe('Nov 2, 8:27 AM CST')
    expect(plain(formatLocalTime(iso, { timeZone: 'UTC', locale: 'en-US' }))).toBe('Nov 2, 2:27 PM UTC')
  })

  test('follows daylight saving time', () => {
    const summer = formatLocalTime('2026-07-02T14:00:00Z', { timeZone: 'America/Chicago', locale: 'en-US' })

    expect(plain(summer)).toBe('Jul 2, 9:00 AM CDT')
  })
})
