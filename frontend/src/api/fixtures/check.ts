// Build-time contract check. These assignments only type-check while the real
// sample responses written by the backend tests match the types in ../types.ts.
// The samples also serve as mock data for the UI.
import type { AnalyzeResponse, HeatmapResponse, PlanResponse } from '../types'
import analyzeJson from './analyze.sample.json'
import heatmapJson from './heatmap.sample.json'
import planJson from './plan.sample.json'

export const analyzeSample: AnalyzeResponse = analyzeJson
export const heatmapSample: HeatmapResponse = heatmapJson
export const planSample: PlanResponse = planJson
