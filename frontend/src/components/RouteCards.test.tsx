import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, test, vi } from 'vitest'
import { formatDuration, formatMiles } from '../format'
import { threeRouteAnalysis } from '../test/helpers'
import { barSegments } from '../riskBar'
import { RouteCards, RouteCardsSkeleton } from './RouteCards'

const analysis = threeRouteAnalysis()
const [routeA, routeB] = analysis.routes

function renderCards(routes = analysis.routes, selectedId = 'route-2') {
  const onSelect = vi.fn()
  render(<RouteCards routes={routes} recommendedId="route-2" selectedId={selectedId} onSelect={onSelect} />)
  const card = (label: string) => screen.getByRole('button', { name: new RegExp(label) })
  return { onSelect, card }
}

describe('route cards', () => {
  test('shows one card per route with duration and distance', () => {
    const { card } = renderCards()

    expect(screen.getAllByRole('button')).toHaveLength(3)
    for (const route of analysis.routes) {
      const text = card(route.label).textContent
      expect(text).toContain(formatDuration(route.duration_s))
      expect(text).toContain(formatMiles(route.distance_mi))
    }
  })

  test('puts the Recommended badge on the recommended route only', () => {
    const { card } = renderCards()

    expect(screen.getAllByText('Recommended')).toHaveLength(1)
    expect(within(card('Route B')).getByText('Recommended')).toBeTruthy()
    expect(within(card('Route A')).queryByText('Recommended')).toBeNull()
  })

  test('shows the Blocked badge for a blocked route', () => {
    const blocked = structuredClone(analysis.routes)
    blocked[2].summary.blocked = true
    const { card } = renderCards(blocked)

    expect(screen.getAllByText('Blocked')).toHaveLength(1)
    expect(within(card('Route C')).getByText('Blocked')).toBeTruthy()
  })

  test('marks the selected card and reports clicks', () => {
    const { card, onSelect } = renderCards(analysis.routes, 'route-1')

    expect(card('Route A').getAttribute('aria-pressed')).toBe('true')
    expect(card('Route B').getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(card('Route C'))

    expect(onSelect).toHaveBeenCalledWith('route-3')
  })

  test('shows average risk and forecast coverage', () => {
    const routes = structuredClone(analysis.routes)
    routes[0].summary.avg_risk = 1.234
    routes[0].summary.coverage_pct = 68.75
    routes[1].summary.avg_risk = null
    const { card } = renderCards(routes)

    expect(card('Route A').textContent).toContain('Average risk 1.23 of 4')
    expect(card('Route A').textContent).toContain('Forecast coverage 68.7%')
    expect(card('Route B').textContent).toContain('Average risk n/a')
  })
})

describe('stacked bar of miles by risk level', () => {
  test('has a segment per level that has miles', () => {
    const segments = barSegments(routeA)

    expect(segments.length).toBeGreaterThan(1)
    for (const segment of segments) expect(segment.miles).toBeGreaterThan(0)
    expect(segments.find((segment) => segment.name === 'Severe')?.miles).toBe(routeA.summary.miles_by_level.severe)
    expect(segments.find((segment) => segment.name === 'No Travel')).toBeUndefined() // zero miles are left out
  })

  test('renders every segment sized by its miles, each with its level name beside it', () => {
    const { card } = renderCards()
    const bar = within(card('Route A')).getByRole('img')

    const grows = Array.from(bar.children).map((segment) => Number((segment as HTMLElement).style.flexGrow))

    expect(grows).toEqual(barSegments(routeA).map((segment) => segment.miles))
    for (const segment of barSegments(routeA)) {
      expect(bar.getAttribute('aria-label')).toContain(`${segment.name} ${formatMiles(segment.miles)}`)
      expect(card('Route A').textContent).toContain(`${segment.name} ${formatMiles(segment.miles)}`) // legend text
    }
  })

  test('shows the stretch with no forecast as its own hatched part, not as Low', () => {
    const route = structuredClone(routeB)
    route.summary.miles_by_level = { low: route.distance_mi - 40, moderate: 0, high: 0, severe: 0, no_travel: 0 }

    const segments = barSegments(route)

    expect(segments.map((segment) => segment.name)).toEqual(['Low', 'No forecast'])
    expect(segments[1].hatched).toBe(true)
    expect(segments[1].miles).toBeCloseTo(40, 5)
  })

  test('has no remainder segment when every mile is scored', () => {
    const route = structuredClone(routeB)
    route.distance_mi = Object.values(route.summary.miles_by_level).reduce((sum, miles) => sum + miles, 0)

    expect(barSegments(route).some((segment) => segment.hatched)).toBe(false)
  })
})

test('the skeleton announces loading and is hidden from the reading order', () => {
  render(<RouteCardsSkeleton />)

  expect(screen.getByRole('status').textContent).toBe('Analyzing routes…')
  expect(document.querySelector('[aria-busy="true"]')).toBeTruthy()
  expect(document.querySelectorAll('.skeleton')).toHaveLength(3)
})
