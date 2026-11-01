// The one place that maps a risk level number to its name and color.
// Names match the backend (domain/constants.py LEVEL_NAMES). The ramp is based on the
// Okabe-Ito colorblind-safe palette. Color is never the only signal: every swatch
// in the UI sits next to the level name, and "unavailable" is a hollow circle.

export interface RiskLevel {
  level: number
  name: string
  color: string
}

export const RISK_LEVELS: readonly RiskLevel[] = [
  { level: 0, name: 'Low', color: '#009E73' },
  { level: 1, name: 'Moderate', color: '#F0E442' },
  { level: 2, name: 'High', color: '#E69F00' },
  { level: 3, name: 'Severe', color: '#D55E00' },
  { level: 4, name: 'No Travel', color: '#4A1486' },
]

/** A checkpoint or stretch with no forecast: drawn hollow, never as Low. */
export const UNAVAILABLE: RiskLevel = { level: -1, name: 'Unavailable', color: '#6B7280' }

/** The info for a level number; null (or an unknown number) means unavailable. */
export function levelInfo(level: number | null | undefined): RiskLevel {
  return RISK_LEVELS.find((entry) => entry.level === level) ?? UNAVAILABLE
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((start) => {
    const value = parseInt(hex.slice(start, start + 2), 16) / 255
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

export function contrastRatio(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (light + 0.05) / (dark + 0.05)
}

/** Black or white, whichever reads better on the given background. */
export function textColorOn(background: string): string {
  return contrastRatio(background, '#000000') >= contrastRatio(background, '#FFFFFF')
    ? '#000000'
    : '#FFFFFF'
}
