# Routecast

Weather-aware truck routing (React + Django). Given origin, destination, departure time and load weight, it returns 3 routes scored for weather risk at timed checkpoints, plus a recommended route and a 0-48h weather heatmap.
Grading: 40% routes/weather/risk logic, 40% UI/map/heatmap performance, 15% code quality, 5% docs.

## Rules
- docs/DESIGN.md is the source of truth. Read it before changing behaviour. If code and design disagree, stop and ask.
- backend/domain imports no Django and no HTTP library. All thresholds and load rules live in one constants module.
- Providers (Mapbox, Open-Meteo) sit behind interfaces; tests use fakes and saved fixtures, never the network.
- Views stay thin: validate, call one service, shape the response.
- Units: miles, mph, inches per hour, pounds. Time is UTC internally.
- Run pytest (backend) and vitest (frontend) before finishing any task.
- Do not add dependencies, features or files that were not asked for.
- Commit messages name the phase, e.g. "phase 1: domain engine".