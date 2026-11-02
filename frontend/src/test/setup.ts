import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
import { weatherClient } from '../weather/openMeteo'

// Testing Library only unmounts between tests by itself when Vitest globals are on.
afterEach(cleanup)
// The weather client remembers cells for 30 minutes; tests must not share them.
afterEach(() => weatherClient.clearCache())
