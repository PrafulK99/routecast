import { describe, expect, test } from 'vitest'
import { heatmapSample } from '../api/fixtures/check'
import type { HeatmapResponse } from '../api/types'
import { heatmapToGeoJson, levelProperty, selectHeatmap } from './data'

describe('heatmapToGeoJson', () => {
  const data = heatmapToGeoJson(heatmapSample)

  test('makes one point per response point, as [lon, lat]', () => {
    expect(data.collection.type).toBe('FeatureCollection')
    expect(data.collection.features).toHaveLength(heatmapSample.points.length)
    heatmapSample.points.forEach((point, index) => {
      const feature = data.collection.features[index]
      expect(feature.geometry).toEqual({ type: 'Point', coordinates: [point.lon, point.lat] })
    })
    expect(data.isEmpty).toBe(false)
  })

  test('carries all 49 levels on every point as h0 to h48', () => {
    heatmapSample.points.forEach((point, index) => {
      const properties = data.collection.features[index].properties
      expect(Object.keys(properties)).toHaveLength(49)
      expect(properties[levelProperty(0)]).toBe(point.levels[0])
      expect(properties.h48).toBe(point.levels[48])
      point.levels.forEach((level, hour) => expect(properties[`h${hour}`]).toBe(level))
    })
  })

  test('keeps the start hour and the number of hours', () => {
    expect(data.startHour).toBe(heatmapSample.start_hour)
    expect(data.hours).toBe(49)
  })

  test('keeps -1 (no forecast) as it is; the layer gives it weight 0, below Low', () => {
    const response: HeatmapResponse = {
      start_hour: '2026-11-02T14:00:00Z',
      hours: 49,
      points: [{ lat: 30, lon: -97, levels: [0, 3, -1, ...Array(46).fill(-1)] }],
    }

    const properties = heatmapToGeoJson(response).collection.features[0].properties

    expect(properties.h1).toBe(3)
    expect(properties.h2).toBe(-1)
    expect(properties.h48).toBe(-1)
  })

  test('an empty response is flagged empty', () => {
    const result = heatmapToGeoJson({ start_hour: '2026-11-02T14:00:00Z', hours: 49, points: [] })

    expect(result.isEmpty).toBe(true)
    expect(result.collection.features).toEqual([])
  })

  test('levelProperty names hours h0 to h48', () => {
    expect(levelProperty(0)).toBe('h0')
    expect(levelProperty(48)).toBe('h48')
  })
})

describe('selectHeatmap', () => {
  test('parses the response and carries the adjusted flag', () => {
    const onTime = selectHeatmap({ response: heatmapSample, adjusted: false })
    const moved = selectHeatmap({ response: heatmapSample, adjusted: true })

    expect(onTime.departureAdjusted).toBe(false)
    expect(moved.departureAdjusted).toBe(true)
    expect(moved.collection).toEqual(heatmapToGeoJson(heatmapSample).collection)
    expect(heatmapToGeoJson(heatmapSample).departureAdjusted).toBe(false)
  })
})
