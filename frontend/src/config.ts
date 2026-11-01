// Read once from the repo-root .env (Vite envDir). Both are public values.
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
export const MAPBOX_TOKEN: string = import.meta.env.VITE_MAPBOX_PUBLIC_TOKEN ?? ''
