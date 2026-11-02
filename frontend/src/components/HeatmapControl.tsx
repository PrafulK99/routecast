import { useCallback, useEffect, useRef, useState } from 'react'
import { describeError } from '../api/errorMessages'
import { type TimeOptions, formatLocalTime } from '../format'
import { PLAY_INTERVAL_MS, type HeatmapController } from '../heatmap/controller'
import { type HeatmapData, hourLabel } from '../heatmap/data'
import { RISK_LEVELS } from '../risk/levels'

interface Props {
  data: HeatmapData | undefined
  loading: boolean
  error: unknown // set when the request failed
  noPoints: boolean // the analysis had no corridor points, so nothing was requested
  onRetry: () => void
  controller: HeatmapController
  visible: boolean
  onToggleVisible: () => void
  loadWeight: number
  time?: TimeOptions // the viewer's zone by default; tests pass one
}

/** The strip under the map: show/hide, the hour slider with play/pause, and the key. */
export function HeatmapControl({ data, loading, error, noPoints, onRetry, visible, onToggleVisible, ...player }: Props) {
  let body
  if (loading) {
    body = (
      <p className="heatmap-message" role="status">
        <span className="spinner" aria-hidden="true" /> Loading weather heatmap…
      </p>
    )
  } else if (error) {
    body = (
      <div className="heatmap-message heatmap-error" role="alert">
        <span>
          <span aria-hidden="true">⚠</span> Weather heatmap unavailable: {describeError(error).message} The routes above
          are not affected.
        </span>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      </div>
    )
  } else if (noPoints || data?.isEmpty) {
    body = <p className="heatmap-message">No corridor points, so there is no heatmap for this trip.</p>
  } else if (data) {
    body = <HeatmapPlayer data={data} {...player} />
  }

  return (
    <section className="heatmap-control" aria-label="Weather heatmap">
      <div className="heatmap-head">
        <strong>Weather heatmap</strong>
        <label className="heatmap-toggle">
          <input type="checkbox" checked={visible} onChange={onToggleVisible} /> Show heatmap
        </label>
      </div>
      {body}
    </section>
  )
}

interface PlayerProps {
  data: HeatmapData
  controller: HeatmapController
  loadWeight: number
  time?: TimeOptions
}

function HeatmapPlayer({ data, controller, loadWeight, time }: PlayerProps) {
  const maxHour = data.hours - 1
  const inputRef = useRef<HTMLInputElement>(null)
  const hourRef = useRef(0) // the real position; React state only feeds the label
  const frameRef = useRef<number | null>(null)
  const [labelHour, setLabelHour] = useState(0)
  const [playing, setPlaying] = useState(false)

  // Move the map at once; update the label (React state) at most once per animation frame.
  const moveTo = useCallback(
    (hour: number) => {
      hourRef.current = hour
      if (inputRef.current) inputRef.current.value = String(hour)
      controller.setHour(hour)
      if (frameRef.current === null) {
        frameRef.current = requestAnimationFrame(() => {
          frameRef.current = null
          setLabelHour(hourRef.current)
        })
      }
    },
    [controller],
  )

  // A new analysis mounts a fresh player: start at +0 h, and clean up on unmount.
  useEffect(() => {
    controller.setHour(0)
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    }
  }, [controller])

  // One timer while playing; it stops itself at the last hour and is cleared on pause or unmount.
  useEffect(() => {
    if (!playing) return
    const timer = setInterval(() => {
      const next = hourRef.current + 1
      moveTo(next)
      if (next >= maxHour) setPlaying(false)
    }, PLAY_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [playing, moveTo, maxHour])

  function togglePlay() {
    if (!playing && hourRef.current >= maxHour) moveTo(0) // pressing Play at the end starts over
    setPlaying(!playing)
  }

  const label = hourLabel(data.startHour, labelHour, time)

  return (
    <div className="heatmap-player">
      <div className="heatmap-row">
        <button type="button" className="play-button" onClick={togglePlay}>
          <span aria-hidden="true">{playing ? '⏸' : '▶'}</span> {playing ? 'Pause' : 'Play'}
        </button>
        <input
          ref={inputRef}
          type="range"
          min={0}
          max={maxHour}
          step={1}
          defaultValue={0}
          aria-label="Hours after departure"
          aria-valuetext={label}
          onChange={(event) => {
            if (playing) setPlaying(false) // dragging takes over from the animation
            moveTo(Number(event.target.value))
          }}
        />
      </div>
      {data.departureAdjusted && (
        <p className="heatmap-note" role="status">
          The original departure time has passed, so the heatmap starts at {formatLocalTime(data.startHour, time)} instead.
        </p>
      )}
      <p className="heatmap-label">{label}</p>
      <ul className="heatmap-legend" aria-label="Heatmap colors">
        {RISK_LEVELS.map((level) => (
          <li key={level.level}>
            <span className="swatch" style={{ background: level.color }} aria-hidden="true" />
            {level.name}
          </li>
        ))}
        <li>Faint green: low risk. Transparent: no forecast.</li>
      </ul>
      <p className="heatmap-note">
        Risk shown is for your load weight of {loadWeight.toLocaleString('en-US')} lb. Colors blend where points overlap;
        checkpoint circles show exact levels.
      </p>
    </div>
  )
}
