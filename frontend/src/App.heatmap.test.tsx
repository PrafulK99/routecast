// The real MapView, HeatmapLayer and HeatmapControl, with only react-map-gl replaced by a
// fake. Its Map counts every render and exposes a fake map, so these tests can show what
// the slider does to the map: it sets paint properties and never re-renders the component.
import { act, fireEvent, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import App from './App'
import { HeatmapController } from './heatmap/controller'
import {
  HEATMAP_COLOR,
  HEATMAP_INTENSITY,
  HEATMAP_LAYER,
  HEATMAP_OPACITY,
  HEATMAP_RADIUS,
  weightExpression,
} from './heatmap/style'
import { installFetch, renderWithClient, submitTrip } from './test/helpers'

const fake = vi.hoisted(() => {
  const layerIds = new Set<string>()
  return {
    mapRenders: 0, // every render of the fake <Map>, i.e. of MapView
    countMapRender() {
      this.mapRenders++
    },
    layerIds, // layers currently on the fake map
    layerOrder: [] as string[], // the order layers were added in
    layerProps: new globalThis.Map<string, Record<string, unknown>>(), // latest props by layer id
    sourceData: new globalThis.Map<string, Set<unknown>>(), // every data object each source ever received
    map: {
      getLayer: (id: string) => (layerIds.has(id) ? {} : undefined),
      setPaintProperty: vi.fn(),
    },
    fitBounds: vi.fn(),
  }
})

vi.mock('./config', () => ({ API_BASE_URL: 'http://localhost:8000', MAPBOX_TOKEN: 'pk.test' }))

vi.mock('react-map-gl/mapbox', async () => {
  const React = await import('react')
  const mapHandle = { getMap: () => fake.map, fitBounds: fake.fitBounds }
  const MapContext = React.createContext<{ current: typeof mapHandle } | null>(null)
  const contextValue = { current: mapHandle } // one object, so effects that depend on it do not re-run

  const Map = React.forwardRef<unknown, { children?: React.ReactNode; onLoad?: () => void }>((props, ref) => {
    fake.countMapRender()
    React.useImperativeHandle(ref, () => mapHandle)
    React.useEffect(() => props.onLoad?.(), []) // eslint-disable-line react-hooks/exhaustive-deps
    return React.createElement(MapContext.Provider, { value: contextValue }, props.children)
  })

  const Source = (props: { id: string; data: unknown; children?: React.ReactNode }) => {
    if (!fake.sourceData.has(props.id)) fake.sourceData.set(props.id, new globalThis.Set())
    fake.sourceData.get(props.id)!.add(props.data)
    return React.createElement(React.Fragment, null, props.children)
  }

  const Layer = (props: { id: string } & Record<string, unknown>) => {
    fake.layerProps.set(props.id, props)
    React.useEffect(() => {
      fake.layerIds.add(props.id)
      fake.layerOrder.push(props.id)
      return () => void fake.layerIds.delete(props.id)
    }, [props.id])
    return null
  }

  const Popup = (props: { children?: React.ReactNode }) => React.createElement('div', null, props.children)
  const useMap = () => React.useContext(MapContext) ?? {}
  return { default: Map, Source, Layer, Popup, useMap }
})

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  fake.mapRenders = 0
  fake.layerIds.clear()
  fake.layerOrder.length = 0
  fake.layerProps.clear()
  fake.sourceData.clear()
  fake.map.setPaintProperty.mockClear()
  fake.fitBounds.mockClear()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
const slider = () => screen.findByRole('slider', { name: 'Hours after departure' }) as Promise<HTMLInputElement>
const paintCalls = () => fake.map.setPaintProperty.mock.calls

async function startWithHeatmap() {
  installFetch()
  renderWithClient(<App />)
  await submitTrip()
  const range = await slider()
  await advance(50)
  return range
}

describe('heatmap layer on the map', () => {
  test('is added once, below the routes, with the ramp, radius and a moderate opacity', async () => {
    await startWithHeatmap()

    const paint = fake.layerProps.get(HEATMAP_LAYER)!.paint as Record<string, unknown>
    expect(fake.layerProps.get(HEATMAP_LAYER)).toMatchObject({ type: 'heatmap', beforeId: 'route-casing' })
    expect(paint['heatmap-color']).toBe(HEATMAP_COLOR)
    expect(paint['heatmap-radius']).toBe(HEATMAP_RADIUS)
    expect(paint['heatmap-opacity']).toBe(HEATMAP_OPACITY)
    expect(paint['heatmap-intensity']).toBe(HEATMAP_INTENSITY)
    expect(paint['heatmap-weight']).toEqual(weightExpression(0))
    expect(fake.layerOrder.filter((id) => id === HEATMAP_LAYER)).toHaveLength(1)
    // The route casing layer was added first, so the heatmap really sits beneath it.
    expect(fake.layerOrder.indexOf('route-casing')).toBeLessThan(fake.layerOrder.indexOf(HEATMAP_LAYER))
  })

  test('the source gets one GeoJSON point per corridor point, with all 49 levels on each', async () => {
    await startWithHeatmap()

    const [data] = [...fake.sourceData.get('heatmap')!] as { type: string; features: { properties: object }[] }[]
    expect(data.type).toBe('FeatureCollection')
    expect(data.features.length).toBeGreaterThan(0)
    expect(Object.keys(data.features[0].properties)).toHaveLength(49)
  })

  test('is not drawn at all until the heatmap has loaded', async () => {
    installFetch(undefined, () => new Promise(() => {})) // the heatmap never arrives
    renderWithClient(<App />)
    await submitTrip()
    await screen.findByText(/Loading weather heatmap/)

    expect(fake.layerIds.has(HEATMAP_LAYER)).toBe(false)
    expect(fake.layerIds.has('route-line')).toBe(true) // the routes are already on the map
  })

  test('the checkbox shows and hides the layer', async () => {
    await startWithHeatmap()
    const toggle = screen.getByRole('checkbox', { name: 'Show heatmap' }) as HTMLInputElement
    const visibility = () => (fake.layerProps.get(HEATMAP_LAYER)!.layout as { visibility: string }).visibility
    expect(visibility()).toBe('visible')

    fireEvent.click(toggle)
    expect(visibility()).toBe('none')
    expect(toggle.checked).toBe(false)

    fireEvent.click(toggle)
    expect(visibility()).toBe('visible')
    // App re-rendered twice, yet the parsed collection is still the one and only object.
    expect(fake.sourceData.get('heatmap')!.size).toBe(1)
  })
})

describe('the slider and the map', () => {
  test('every hour sets the weight expression of that hour on the heatmap layer', async () => {
    const range = await startWithHeatmap()
    fake.map.setPaintProperty.mockClear()

    for (let hour = 1; hour <= 48; hour++) {
      fireEvent.change(range, { target: { value: String(hour) } })
      await advance(20)
    }

    expect(paintCalls()).toHaveLength(48)
    paintCalls().forEach(([layer, property, value], index) => {
      expect([layer, property]).toEqual([HEATMAP_LAYER, 'heatmap-weight'])
      expect(value).toEqual(weightExpression(index + 1))
    })
    expect(JSON.stringify(paintCalls().at(-1)![2])).toContain('"h48"')
  })

  test('49 slider ticks never re-render the map component or rebuild its data', async () => {
    const range = await startWithHeatmap()
    const rendersBefore = fake.mapRenders
    const dataObjects = fake.sourceData.get('heatmap')!.size

    for (let hour = 1; hour <= 48; hour++) {
      fireEvent.change(range, { target: { value: String(hour) } })
      await advance(20)
    }
    fireEvent.change(range, { target: { value: '0' } })
    await advance(20)

    expect(paintCalls().length).toBeGreaterThanOrEqual(49) // the map really was updated each time
    expect(fake.mapRenders).toBe(rendersBefore)
    expect(fake.sourceData.get('heatmap')!.size).toBe(dataObjects)
    expect(dataObjects).toBe(1) // one parsed collection, the same object on every render
  })

  test('a full play-through to +48 h does not re-render the map either', async () => {
    await startWithHeatmap()
    const rendersBefore = fake.mapRenders
    fake.map.setPaintProperty.mockClear()

    fireEvent.click(screen.getByRole('button', { name: /Play/ }))
    await advance(400 * 48 + 50)

    expect(paintCalls()).toHaveLength(48)
    expect(fake.mapRenders).toBe(rendersBefore)
    expect(screen.getByRole('button', { name: /Play/ })).toBeTruthy() // it stopped at 48
    expect((await slider()).value).toBe('48')
  })

  test('the counter is live: a React state change in App does re-render the map', async () => {
    await startWithHeatmap()
    const rendersBefore = fake.mapRenders

    fireEvent.click(screen.getByRole('checkbox', { name: 'Show heatmap' })) // App state

    expect(fake.mapRenders).toBeGreaterThan(rendersBefore)
  })

  test('a layer added after the slider moved starts at the current hour', () => {
    // The controller remembers the hour, so a map or layer that appears later is not left at +0 h.
    const controller = new HeatmapController()
    controller.setHour(17)
    fake.layerIds.add(HEATMAP_LAYER)

    controller.attach(fake.map)

    expect(fake.map.setPaintProperty).toHaveBeenCalledWith(HEATMAP_LAYER, 'heatmap-weight', weightExpression(17))
  })
})
