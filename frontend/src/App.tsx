import { useEffect, useState } from 'react'

type Health = { status: string }

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export default function App() {
  const [result, setResult] = useState('checking...')

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_BASE_URL}/api/health`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() as Promise<Health>
      })
      .then((body) => setResult(body.status))
      .catch((error: Error) => {
        if (error.name !== 'AbortError') setResult(`error (${error.message})`)
      })
    return () => controller.abort()
  }, [])

  return (
    <main>
      <h1>Routecast</h1>
      <p>API: {result}</p>
    </main>
  )
}
