import { describe, expect, test } from 'vitest'
import { analyzeSample } from '../api/fixtures/check'
import type { Route } from '../api/types'
import { ROUTE_COLORS, boundsOf, checkpointsGeoJson, routeColor, routesGeoJson } from './geojson'

const routes = analyzeSample.routes
const stormRoute = routes[0] // route-1: Severe checkpoints in the middle
const calmRoute = routes[1]

describe('routesGeoJson', () => {
  test('has one line feature per route with its id, label and color', () => {
    const collection = routesGeoJson(routes, calmRoute.id)

    expect(collection.features).toHaveLength(routes.length)
    const byId = Object.fromEntries(collection.features.map((f) => [f.properties.id, f]))
    expect(byId['route-1'].properties).toMatchObject({ label: 'Route A', color: ROUTE_COLORS[0] })
    expect(byId['route-2'].properties).toMatchObject({ label: 'Route B', color: ROUTE_COLORS[1] })
    expect(byId['route-1'].geometry).toBe(stormRoute.geometry)
  })

  test('marks only the selected route and draws it last, on top', () => {
    const collection = routesGeoJson(routes, 'route-1')

    expect(collection.features.map((f) => f.properties.selected)).toEqual([0, 1])
    expect(collection.features.at(-1)?.properties.id).toBe('route-1')
  })

  test('colors cycle and stay outside the risk palette', () => {
    expect(routeColor(0)).toBe(ROUTE_COLORS[0])
    expect(routeColor(3)).toBe(ROUTE_COLORS[0])
    expect(new Set(ROUTE_COLORS).size).toBe(ROUTE_COLORS.length)
  })
})

describe('checkpointsGeoJson', () => {
  test('has one point per checkpoint, [lon, lat], colored by level', () => {
    const collection = checkpointsGeoJson(stormRoute)

    expect(collection.features).toHaveLength(stormRoute.checkpoints.length)
    const first = collection.features[0]
    expect(first.geometry.coordinates).toEqual([stormRoute.checkpoints[0].lon, stormRoute.checkpoints[0].lat])
    const severe = collection.features.find((f) => f.properties.levelName === 'Severe')
    expect(severe?.properties).toMatchObject({ color: '#D55E00', unavailable: 0 })
  })

  test('shows an unavailable checkpoint as unavailable, never as Low', () => {
    const route: Route = structuredClone(calmRoute)
    route.checkpoints[2].risk = { ...route.checkpoints[2].risk, level: null, level_name: null, factor: null }
    route.checkpoints[2].status = 'unavailable'

    const feature = checkpointsGeoJson(route).features[2]

    expect(feature.properties).toMatchObject({ unavailable: 1, levelName: 'Unavailable' })
    expect(feature.properties.levelName).not.toBe('Low')
  })

  test('is empty without a route', () => {
    expect(checkpointsGeoJson(undefined).features).toEqual([])
  })
})

describe('boundsOf', () => {
  test('is the box around every route', () => {
    const [[west, south], [east, north]] = boundsOf(routes)!
    const all = routes.flatMap((r) => r.geometry.coordinates)

    expect(west).toBe(Math.min(...all.map(([lon]) => lon)))
    expect(east).toBe(Math.max(...all.map(([lon]) => lon)))
    expect(south).toBe(Math.min(...all.map(([, lat]) => lat)))
    expect(north).toBe(Math.max(...all.map(([, lat]) => lat)))
    expect(west).toBeLessThan(east)
    expect(south).toBeLessThan(north)
  })

  test('is null without routes', () => {
    expect(boundsOf([])).toBeNull()
  })
})
