import { render } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import { analyzeSample } from '../api/fixtures/check'
import type { Checkpoint } from '../api/types'
import { formatLocalTime } from '../format'
import { CheckpointPopup } from './CheckpointPopup'

const chicago = { timeZone: 'America/Chicago', locale: 'en-US' }
const plain = (text: string | null) => (text ?? '').replace(/\s/g, ' ')

// A real Severe checkpoint from the storm sample (50 mph wind).
const severe: Checkpoint = analyzeSample.routes[0].checkpoints.find((cp) => cp.risk.level_name === 'Severe')!

function popupText(checkpoint: Checkpoint) {
  const { container } = render(<CheckpointPopup checkpoint={checkpoint} time={chicago} />)
  return plain(container.textContent)
}

describe('checkpoint popup', () => {
  test('shows ETA and forecast hour in the viewer zone with its label', () => {
    const text = popupText(severe)

    expect(text).toContain(plain(formatLocalTime(severe.eta, chicago)))
    expect(text).toContain(plain(formatLocalTime(severe.forecast_hour, chicago)))
    expect(text).toMatch(/(CST|CDT)/) // textContent runs labels together, so no word boundary
  })

  test('shows wind, rain, snow, level name and the deciding factor', () => {
    const text = popupText(severe)

    expect(text).toContain('Severe')
    expect(text).toContain('set by wind')
    expect(text).toContain('Wind50 mph')
    expect(text).toContain('Rain0 in/hr')
    expect(text).toContain('Snow0 in/hr')
  })

  test('mentions the load only when a load rule raised the level', () => {
    expect(popupText(severe)).not.toContain('load weight')

    const raised = structuredClone(severe)
    raised.risk.load_rule_applied = true
    document.body.innerHTML = ''

    expect(popupText(raised)).toContain('Your load weight raised the wind level')
  })

  test('says there is no forecast for an unavailable checkpoint, and rates nothing as Low', () => {
    const unavailable = structuredClone(severe)
    unavailable.status = 'unavailable'
    unavailable.risk = { ...unavailable.risk, level: null, level_name: null, factor: null }
    unavailable.wind_mph = unavailable.rain_in_hr = unavailable.snow_in_hr = null

    const text = popupText(unavailable)

    expect(text).toContain('Unavailable')
    expect(text).toContain('No forecast covers this time')
    expect(text).not.toContain('Low')
    expect(text).not.toContain('Wind')
  })

  test('notes a partial forecast', () => {
    const partial = structuredClone(severe)
    partial.status = 'partial'
    partial.rain_in_hr = null

    const text = popupText(partial)

    expect(text).toContain('Partial forecast')
    expect(text).toContain('Rainn/a')
  })
})
