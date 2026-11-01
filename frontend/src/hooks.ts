import { useEffect, useState } from 'react'

/** The value, but only after it has stopped changing for `delayMs`. */
export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

/** True once `active` has stayed true for `delayMs`; false again as soon as it turns false. */
export function useAfterDelay(active: boolean, delayMs: number): boolean {
  const [elapsed, setElapsed] = useState(false)
  useEffect(() => {
    if (!active) return
    const timer = setTimeout(() => setElapsed(true), delayMs)
    return () => {
      clearTimeout(timer)
      setElapsed(false) // reset when the activity ends, ready for the next one
    }
  }, [active, delayMs])
  return active && elapsed
}
