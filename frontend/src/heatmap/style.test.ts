import { describe, expect, test } from 'vitest'
import { RISK_LEVELS } from '../risk/levels'
import {
  HEATMAP_COLOR,
  HEATMAP_COLOR_STOPS,
  HEATMAP_INTENSITY,
  HEATMAP_OPACITY,
  HEATMAP_RADIUS,
  LOW_BAND_END,
  LOW_BAND_START,
  LOW_WEIGHT,
  intensityForZoom,
  radiusForZoom,
  spacingPx,
  weightExpression,
} from './style'

/** Evaluates the few expression operators the weight uses (get, coalesce, case, >=, max, divide). */
function evaluate(expression: unknown, properties: Record<string, number>): number | undefined {
  if (typeof expression === 'number') return expression
  const [operator, ...args] = expression as [string, ...unknown[]]
  const value = (arg: unknown) => evaluate(arg, properties) as number
  switch (operator) {
    case 'get':
      return properties[args[0] as string]
    case 'coalesce':
      return args.map((arg) => evaluate(arg, properties)).find((result) => result !== undefined)
    case 'case':
      return value(args[0]) ? evaluate(args[1], properties) : evaluate(args[2], properties)
    case '>=':
      return (value(args[0]) >= value(args[1]) ? 1 : 0) as number
    case 'max':
      return Math.max(...args.map(value))
    case '/':
      return value(args[0]) / value(args[1])
    default:
      throw new Error(`the test evaluator does not know "${operator}"`)
  }
}

describe('weight expression', () => {
  test('Low weighs a small positive amount, so calm weather still draws', () => {
    const weight = evaluate(weightExpression(7), { h7: 0 }) as number

    expect(weight).toBe(LOW_WEIGHT)
    expect(weight).toBeGreaterThan(0)
    expect(weight).toBeLessThan(0.25) // well below Moderate
  })

  test.each([
    [1, 0.25],
    [2, 0.5],
    [3, 0.75],
    [4, 1],
  ])('level %s weighs level / 4 = %s', (level, weight) => {
    expect(evaluate(weightExpression(7), { h7: level })).toBe(weight)
  })

  test('each level weighs more than the one below it', () => {
    const weights = [0, 1, 2, 3, 4].map((level) => evaluate(weightExpression(7), { h7: level }) as number)

    expect(weights).toEqual([...weights].sort((a, b) => a - b))
    expect(new Set(weights).size).toBe(5)
  })

  test('no forecast (-1) weighs exactly 0, not negative and not Low', () => {
    expect(evaluate(weightExpression(7), { h7: -1 })).toBe(0)
    expect(evaluate(weightExpression(7), { h7: -1 })).toBeLessThan(LOW_WEIGHT)
  })

  test('a missing property weighs 0', () => {
    expect(evaluate(weightExpression(7), {})).toBe(0)
  })

  test('reads the property of the selected hour only', () => {
    const properties = { h5: 1, h6: 3, h7: 0, h8: -1 }

    expect(evaluate(weightExpression(5), properties)).toBe(0.25)
    expect(evaluate(weightExpression(6), properties)).toBe(0.75)
    expect(evaluate(weightExpression(7), properties)).toBe(LOW_WEIGHT)
    expect(evaluate(weightExpression(8), properties)).toBe(0)
  })
})

describe('color ramp', () => {
  test('starts fully transparent', () => {
    const [density, color] = HEATMAP_COLOR_STOPS[0]

    expect(density).toBe(0)
    expect(color).toMatch(/,0\)$/)
  })

  test('uses the shared risk color for each level at density level / 4', () => {
    for (const level of RISK_LEVELS.slice(1)) {
      expect(HEATMAP_COLOR_STOPS).toContainEqual([level.level / 4, level.color])
    }
  })

  test('draws Low as a faint green, held flat around the density a Low point reaches', () => {
    const [, [startDensity, start], [endDensity, end]] = HEATMAP_COLOR_STOPS

    expect(startDensity).toBe(LOW_BAND_START)
    expect(endDensity).toBe(LOW_BAND_END)
    expect(LOW_BAND_START).toBeLessThan(LOW_WEIGHT)
    expect(LOW_WEIGHT).toBeLessThan(LOW_BAND_END)
    expect(end).toBe(start) // flat: the dips between neighbouring points keep the same green
    const alpha = Number(start.match(/^rgba\(0,158,115,([\d.]+)\)$/)?.[1]) // the shared Low color, #009E73
    expect(alpha).toBeGreaterThan(0.3) // visible
    expect(alpha).toBeLessThan(1) // but faint, not solid
  })

  test('keeps Low well apart from Moderate: its own flat stop, and a clear density gap', () => {
    const moderate = HEATMAP_COLOR_STOPS.find(([, color]) => color === RISK_LEVELS[1].color)!

    expect(moderate[0] - LOW_BAND_END).toBeGreaterThanOrEqual(0.12)
    expect(moderate[0] - LOW_WEIGHT).toBeGreaterThanOrEqual(0.15)
    expect(moderate[1]).not.toBe(HEATMAP_COLOR_STOPS[1][1])
  })

  test('ends on the shared No Travel color', () => {
    expect(HEATMAP_COLOR_STOPS.at(-1)).toEqual([1, RISK_LEVELS[4].color])
  })

  test('densities rise strictly from 0 to 1', () => {
    const densities = HEATMAP_COLOR_STOPS.map(([density]) => density)

    expect(densities).toEqual([...densities].sort((a, b) => a - b))
    expect(new Set(densities).size).toBe(densities.length)
    expect(densities[0]).toBe(0)
    expect(densities.at(-1)).toBe(1)
  })

  test('is a linear interpolation of the heatmap density with those stops', () => {
    expect(HEATMAP_COLOR).toEqual(['interpolate', ['linear'], ['heatmap-density'], ...HEATMAP_COLOR_STOPS.flat()])
  })

  test('opacity is moderate', () => {
    expect(HEATMAP_OPACITY).toBeGreaterThan(0.3)
    expect(HEATMAP_OPACITY).toBeLessThan(0.7)
  })
})

describe('radius', () => {
  test('15 miles on screen doubles with every zoom level', () => {
    expect(spacingPx(8) / spacingPx(7)).toBeCloseTo(2, 5)
    expect(spacingPx(5)).toBeGreaterThan(5) // a few tens of pixels at a regional view
  })

  test.each([3, 4, 5, 6, 7, 8, 9, 10])('at zoom %s neighbouring points, 15 miles apart, overlap', (zoom) => {
    expect(radiusForZoom(zoom)).toBeGreaterThanOrEqual(spacingPx(zoom))
  })

  test('never shrinks as the map zooms in, and stays within sane bounds', () => {
    let previous = 0
    for (let zoom = 0; zoom <= 16; zoom += 0.5) {
      const radius = radiusForZoom(zoom)
      expect(radius).toBeGreaterThanOrEqual(previous)
      expect(radius).toBeGreaterThanOrEqual(10)
      expect(radius).toBeLessThanOrEqual(440)
      previous = radius
    }
  })

  test('is written as an exponential zoom interpolation through those values', () => {
    const [kind, base, input, ...stops] = HEATMAP_RADIUS as unknown as [string, unknown[], unknown[], ...number[]]

    expect([kind, base, input]).toEqual(['interpolate', ['exponential', 2], ['zoom']])
    for (let i = 0; i < stops.length; i += 2) expect(stops[i + 1]).toBe(radiusForZoom(stops[i]))
    expect(stops.length / 2).toBeGreaterThanOrEqual(8)
  })
})

describe('intensity', () => {
  test.each([5, 6, 7, 8, 9, 10])('is the calibrated 2.5 where radius follows the spacing (zoom %s)', (zoom) => {
    expect(intensityForZoom(zoom)).toBeCloseTo(2.5, 5)
  })

  test('is lowered when zoomed far out, where the minimum radius stacks the points', () => {
    expect(intensityForZoom(4)).toBeLessThan(2.5)
    expect(intensityForZoom(3)).toBeLessThan(intensityForZoom(4))
    expect(intensityForZoom(2)).toBeGreaterThan(0)
  })

  test('is written as a linear zoom interpolation through those values', () => {
    const [kind, base, input, ...stops] = HEATMAP_INTENSITY as unknown as [string, unknown[], unknown[], ...number[]]

    expect([kind, base, input]).toEqual(['interpolate', ['linear'], ['zoom']])
    for (let i = 0; i < stops.length; i += 2) expect(stops[i + 1]).toBe(intensityForZoom(stops[i]))
  })
})
