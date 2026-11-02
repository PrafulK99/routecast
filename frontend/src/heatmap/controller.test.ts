import { describe, expect, test, vi } from 'vitest'
import { HeatmapController } from './controller'
import { HEATMAP_LAYER, weightExpression } from './style'

function fakeMap(layerExists = true) {
  return { getLayer: vi.fn(() => (layerExists ? {} : undefined)), setPaintProperty: vi.fn() }
}

describe('HeatmapController', () => {
  test('sets the weight expression of the hour on the heatmap layer', () => {
    const map = fakeMap()
    const controller = new HeatmapController()
    controller.attach(map)
    map.setPaintProperty.mockClear()

    controller.setHour(13)

    expect(map.setPaintProperty).toHaveBeenCalledTimes(1)
    expect(map.setPaintProperty).toHaveBeenCalledWith(HEATMAP_LAYER, 'heatmap-weight', weightExpression(13))
    expect(controller.hour).toBe(13)
  })

  test('does nothing without a map, or while the layer does not exist yet', () => {
    const controller = new HeatmapController()
    expect(() => controller.setHour(5)).not.toThrow()

    const map = fakeMap(false)
    controller.attach(map)
    controller.setHour(6)

    expect(map.setPaintProperty).not.toHaveBeenCalled()
  })

  test('remembers the hour, so a map attached later starts in the right place', () => {
    const controller = new HeatmapController()
    controller.setHour(30)
    const map = fakeMap()

    controller.attach(map)

    expect(map.setPaintProperty).toHaveBeenCalledWith(HEATMAP_LAYER, 'heatmap-weight', weightExpression(30))
  })

  test('detaching stops updates', () => {
    const map = fakeMap()
    const controller = new HeatmapController()
    controller.attach(map)
    controller.attach(null)
    map.setPaintProperty.mockClear()

    controller.setHour(2)

    expect(map.setPaintProperty).not.toHaveBeenCalled()
  })
})
