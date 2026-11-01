import { describe, expect, test } from 'vitest'
import { RISK_LEVELS, UNAVAILABLE, contrastRatio, levelInfo, textColorOn } from './levels'

describe('risk level mapping', () => {
  test('has the five levels in order with the backend names', () => {
    expect(RISK_LEVELS.map((entry) => [entry.level, entry.name])).toEqual([
      [0, 'Low'],
      [1, 'Moderate'],
      [2, 'High'],
      [3, 'Severe'],
      [4, 'No Travel'],
    ])
  })

  test('every level has its own valid hex color', () => {
    const colors = RISK_LEVELS.map((entry) => entry.color)
    expect(new Set(colors).size).toBe(colors.length)
    expect(colors).not.toContain(UNAVAILABLE.color)
    for (const color of colors) expect(color).toMatch(/^#[0-9A-F]{6}$/)
  })

  test('levelInfo returns the entry for a level number', () => {
    expect(levelInfo(3)).toEqual({ level: 3, name: 'Severe', color: '#D55E00' })
    expect(levelInfo(0).name).toBe('Low')
  })

  test.each([null, undefined, -1, 5, 2.5])('levelInfo(%s) is unavailable, never Low', (level) => {
    expect(levelInfo(level)).toBe(UNAVAILABLE)
    expect(UNAVAILABLE.name).toBe('Unavailable')
  })

  test('the text color chosen for each level color is readable (contrast of at least 4.5)', () => {
    for (const { color } of [...RISK_LEVELS, UNAVAILABLE]) {
      expect(contrastRatio(color, textColorOn(color))).toBeGreaterThanOrEqual(4.5)
    }
  })

  test('contrast ratio of black on white is 21', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 5)
  })
})
