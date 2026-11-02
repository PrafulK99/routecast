# Weather-Aware Truck Routing: System Design

Nov 1, 2026 · @Praful Kharpuriye

## Scope and success criteria

The system takes an origin, destination, departure time and load weight, returns three truck routes scored for weather risk at timed checkpoints, and names one recommended route with a reason. Correct risk scoring and ranking is the priority; everything else exists to display it.

**In scope**

- Address search, three route options, checkpoints every 10, 25 or 50 miles, forecast lookup at each truck ETA, risk classification with load rules, and a recommendation.
- A map with all routes, risk-colored checkpoints, popups and a route comparison panel.
- A weather heatmap over the trip corridor with a 0 to 48 hour slider.
- A hosted app, a GitHub repo, and a README that states every assumption.

**Out of scope, on purpose**

- Accounts, saved trips, alerts, live traffic, driver rest rules, bridge and weight restrictions, re-routing around weather, a native mobile app.
- A routing engine. A third-party API supplies routes.

**How the grading weights shape the design**

| Weight | What must be true | Design response |
| --- | --- | --- |
| 40% logic | Thresholds, load rules, ETA-aligned forecast and ranking are exact | Risk and ranking are pure functions with no I/O, covered by boundary tests |
| 40% UI and map | Map and slider stay smooth with 3 routes and 100+ points | Simplified geometry, GeoJSON sources, all 49 heatmap frames sent once, slider only switches a map property |
| 15% code | Easy to read | Thin API views, a service layer, one module per concern |
| 5% docs | A reviewer can follow the decisions | README lists assumptions; Loom walks one analysis end to end |

## Ambiguities and decisions

The spec leaves 17 points open. Each is resolved here so the code has one right answer; the README repeats these as its assumptions list.

1. **Checkpoint interval (10 / 25 / 50 miles).** The user picks 10, 25 or 50; the default is 25. Checkpoints sit at mile 0, every N miles, and the destination. If a route would exceed 150 checkpoints, the server moves to the next larger interval and reports it. Reason: the spec gives three values and no rule for choosing.
2. **Combining wind, rain and snow.** Each is classified separately. The checkpoint level is the highest of the three, and the response names which factor set it. Reason: no weighting is given, and the worst condition is what limits a truck.
3. **Level order.** Low 0, Moderate 1, High 2, Severe 3, No Travel 4. Used for comparing, averaging and heatmap weight.
4. **Boundary values.** Forecasts are decimals, so 25 to 34 mph leaves 34.5 undefined. Rule: each level starts at its lower bound (inclusive) and runs up to, not including, the next bound. A value shared by two ranges, such as 0.25 in/hr rain, takes the higher level, the safer side. Rain and snow keep the spec's strict "over" for No Travel, so exactly 1.00 in/hr rain is Severe. Values are never rounded before comparing. The full table is in the Risk engine section.
5. **Which wind value.** Sustained 10 m wind speed at the checkpoint hour, in mph. Gusts are not used because the spec says wind. It is one config constant if gusts are preferred.
6. **Rain and snow measures.** Rain is liquid rain plus showers, in inches per hour. Snow is snowfall depth in inches per hour. Snow water equivalent is never added to rain.
7. **Load rules.** All three concern wind only. They can raise the wind level, never lower it. They apply when load is strictly greater than the stated weight, so exactly 30,000 lb does not trigger the 30,000 lb rule. Load is in pounds. Rain and snow ignore load.
8. **Forecast hour for an ETA.** Round the ETA to the nearest whole hour (half rounds up) and use that hour's value. Interpolating would add complexity to fix under 30 minutes of error, which is smaller than the ETA error itself.
9. **ETA.** Departure time plus cumulative route duration to the checkpoint, multiplied by a truck factor (default 1.10, configurable) because routing APIs model cars. Rest stops are not modeled.
10. **Miles per risk level.** Each checkpoint owns the stretch halfway to its neighbours on each side. The first starts at mile 0 and the last ends at the destination. Severe miles is the sum of those stretches for Severe checkpoints.
11. **Average risk.** The mile-weighted mean of level numbers, 0 to 4.
12. **No Travel in the ranking.** The spec's ranking list does not mention it. Ignoring it would let a route with 100 No Travel miles beat a route with one Severe mile. Decision: the first sort key is No Travel miles, then the spec's four keys. A route with any No Travel mile is labelled Blocked but still shown. If every route is blocked, the least blocked is recommended with a prominent warning.
13. **Balance versus strict order.** The spec says balance, then lists an ordered preference. Decision: strict lexicographic order, with miles compared to 0.1 mile. The comparison panel shows time differences so the driver can overrule. A tolerance band is a possible later option and is not built.
14. **Heatmap time axis.** Slider position 0 to 48 means hours after departure, with departure rounded down to the hour. Colors show the risk level for the entered load, so the heatmap and the route scores always agree.
15. **Forecast limits.** Departure must fall between the current hour and 7 days ahead. A checkpoint beyond the available forecast is marked no forecast, left out of mile totals, and the route shows its forecast coverage percentage.
16. **Fewer than three routes.** If the provider returns fewer, a via-point fallback tries to add distinct routes. If there are still fewer, return what exists with a notice.
17. **Routing provider.** Mapbox Directions behind a small interface so another provider can replace it. OpenRouteService is unsuitable because its public API caps alternative routes at 100 km. **Open question: confirm Mapbox.**

## Architecture

A stateless Django API does all scoring and ranking; the React app only collects input and renders results. No database is needed, because every answer can be recomputed from the request and two external APIs.

&#91;embedded content: system architecture · browser, API layers, two external services\]

The browser talks to the API for planning and scoring, to Mapbox directly for address search and map tiles, and to Open-Meteo directly for the weather. The hosted server shares one outgoing IP with other apps, so Open-Meteo's free daily limit (counted per location per IP) is spent every day; fetching in the browser gives each visitor their own quota. The server never fetches weather for a request that carries it. It fetches weather itself only when a request carries none (local development, scratch scripts, tests). Only the Providers layer touches Mapbox routing and the server-side Open-Meteo path, and only the Domain layer holds the graded logic, whichever way the weather arrived.

**Backend layers.** Dependencies point inward, so the risk logic never imports Django or an HTTP client.

1. **Views** (DRF): parse and validate the request, call one service, shape the response and errors.
2. **Services**: orchestrate a request (fetch routes, sample, fetch weather, score, rank).
3. **Domain**: pure functions with no I/O. Risk classification, load rules, checkpoint sampling, ETA, mile attribution, ranking.
4. **Providers**: adapters for Mapbox (routes) and Open-Meteo (weather), each behind an interface with a fake used in tests.

**Technology choices**

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | React, TypeScript, Vite, TanStack Query | Typed API contract; request cancellation and caching built in |
| Map | react-map-gl with Mapbox GL JS | One vendor and one token for tiles, geocoding and routing; native heatmap layer; avoids any question about Directions API display terms |
| Backend | Django 5, Django REST Framework, Python 3.12 | Required stack; serializers give validation and clear errors |
| Outbound HTTP | httpx with a thread pool for parallel weather batches (server path); browser fetch, 4 batches in parallel (browser path) | Simple synchronous code, no async server needed; the browser path spends the visitor's own Open-Meteo quota |
| Routing and geocoding | Mapbox Directions and Geocoding | Alternatives on long routes; per-segment duration annotations for accurate ETAs |
| Weather | Open-Meteo, fetched by the browser | No key, hourly wind, rain and snowfall, many locations per request; one quota per visitor |
| Cache | Django cache (local memory, Redis if configured) | Weather and route responses are reusable; cache misses only cost latency |
| Hosting | Render or Railway (API), Vercel (web) | Free tiers, simple deploys |

**Request flow for one analysis**

1. The browser resolves the typed addresses to coordinates with Mapbox Geocoding and sends POST /api/plan.
2. The view validates the payload. The routing provider returns up to 3 routes with full geometry and per-segment distance and duration; the via-point fallback fills gaps. The raw Mapbox answers are cached for 10 minutes.
3. For each route the domain builds cumulative distance and time, places checkpoints, and computes each ETA. The plan response lists the unique weather grid cells of all checkpoints of all routes and the UTC hour window needed (from the first checkpoint hour to the later of the last ETA hour and 48 hours after departure). It makes no Open-Meteo call.
4. The browser fetches those cells from Open-Meteo in batches of 50 locations, up to 4 requests in parallel, and trims each series to the window. Cells fetched in the last 30 minutes are reused.
5. The browser sends POST /api/analyze with the same body plus `weather`. Routing repeats from the cache, so no routing call is made again.
6. For each checkpoint, the domain picks the forecast hour for the ETA and classifies the risk using the load weight, from the supplied weather. A checkpoint whose cell or hour was not supplied is unavailable.
7. Per route, it totals miles by level, average risk, duration and forecast coverage, then ranks the routes and writes the recommendation reason.
8. The response carries the routes, checkpoints, recommendation, a short list of corridor points and the grid cells of those points.
9. After rendering, the browser fetches the corridor cells it does not already hold (the exact coordinates the response names, never rounded in the browser) for departure hour to +48 hours, and posts the corridor points with that weather to POST /api/heatmap. The route results never wait on it.

Without a `weather` field, /api/analyze and /api/heatmap fetch the weather themselves from Open-Meteo (cache first, parallel batches), exactly as before. The progress states shown in the browser are Planning routes (steps 1 to 3), Fetching weather (step 4) and Scoring routes (steps 5 to 8).

## Risk engine

A checkpoint's risk is the highest of its wind, rain and snow levels, after the load rules have raised the wind level where they apply. The engine is one pure function: weather values and load weight in, a level and its reasons out.

**Thresholds** (lower bound inclusive; see decision 4)

| Level | Number | Wind (mph) | Rain (in/hr) | Snow (in/hr) |
| --- | --- | --- | --- | --- |
| Low | 0 | under 25 | under 0.10 | under 0.5 |
| Moderate | 1 | 25 to under 35 | 0.10 to under 0.25 | 0.5 to under 1.0 |
| High | 2 | 35 to under 45 | 0.25 to under 0.50 | 1.0 to under 2.0 |
| Severe | 3 | 45 to under 55 | 0.50 to 1.00 inclusive | 2.0 to 3.0 inclusive |
| No Travel | 4 | 55 or more | over 1.00 | over 3.0 |

**Load rules** (wind only; the load must be strictly greater than the weight stated)

| Wind (mph) | Load over | Result |
| --- | --- | --- |
| 55 or more | any load | No Travel |
| 45 to under 55 | 30,000 lb | No Travel |
| 35 to under 45 | 40,000 lb | Severe |

**Algorithm**

1. Convert each input to the units above. A missing value stays missing; it is never treated as zero.
2. Classify wind, rain and snow separately with the threshold table.
3. Apply the load rules to the wind level: final wind level is the larger of the table level and the load-rule level.
4. Checkpoint level is the largest of the three final levels. The factor is the one that set it; on a tie, wind, then rain, then snow.
5. Return the level, the three individual levels, the deciding factor, and whether a load rule raised the result.

**Worked examples**

| Wind | Rain | Snow | Load | Result | Why |
| --- | --- | --- | --- | --- | --- |
| 38 | 0.05 | 0 | 45,000 | Severe | Wind is High, load over 40,000 raises it to Severe |
| 38 | 0.05 | 0 | 40,000 | High | 40,000 is not over 40,000 |
| 47 | 0 | 0 | 30,001 | No Travel | Severe wind, load over 30,000 |
| 47 | 0 | 0 | 30,000 | Severe | 30,000 is not over 30,000 |
| 55 | 0 | 0 | 0 | No Travel | 55 mph stops any load |
| 20 | 0.30 | 0 | 50,000 | High | Rain sets the level; load rules only touch wind |
| 10 | 1.00 | 0 | 10,000 | Severe | 1.00 is not over 1.00 |
| 10 | 1.01 | 0 | 10,000 | No Travel | Over 1.00 |
| 34.9 | 0 | 0 | 10,000 | Moderate | Below the 35 bound |

**Partial and missing data**

- Some values missing: classify with the ones present and mark the checkpoint partial.
- All three missing, or no forecast covers the ETA: mark the checkpoint unavailable. It has no level, is excluded from mile totals, and lowers the route's coverage percentage.

**Validation and invariants**

- Inputs must be finite and not negative; anything else is a programming error and raises, not a silent Low.
- Raising any weather value never lowers the level. Raising the load never lowers the level. Both are checked with property tests.
- Thresholds and load rules live in one constants module, so the tests and the README read from the same source.

## Route scoring and recommendation

The recommended route is the one that sorts first on five keys compared in strict order: No Travel miles, Severe miles, High miles, average risk, then travel time. Lower is better on every key.

**Per-route metrics**

| Metric | Definition |
| --- | --- |
| Miles at each level | Sum of segment miles of checkpoints at that level (decision 10) |
| Average risk | Sum of (level number times segment miles) divided by scored miles |
| Duration | Routing duration times the truck factor |
| Coverage | Scored miles divided by total route miles, as a percentage |
| Blocked | True if No Travel miles is above 0 |

**Ranking procedure**

1. Compute the metrics for every route.
2. Round miles to 0.1 and average risk to 3 decimals, so floating-point noise cannot decide a ranking.
3. Sort by the tuple (No Travel miles, Severe miles, High miles, average risk, duration).
4. If tuples are still equal, the shorter distance wins, then the lower route index, so the result is deterministic.
5. Return every route with its rank, and the recommendation with its reasons.

**Reason text.** Built from the first key where the winner differs from the runner-up, for example: Route B has 0 Severe miles against 14 on Route A, and is 38 minutes slower. If the routes differ on no weather key, the reason says weather is equal and time decided it.

**Special cases**

- One route returned: it is recommended, with a note that no alternatives were available.
- Every route blocked: recommend the one with the fewest No Travel miles and set all\_blocked so the UI shows a warning instead of a normal recommendation.
- Coverage below 100%: ranking still uses the scored miles, and the UI shows the coverage next to the route so a reader can see the comparison is partly blind.

**Example.** Interval 25 miles, route length 80 miles. Checkpoints sit at miles 0, 25, 50, 75 and 80. Their segments are 0 to 12.5, 12.5 to 37.5, 37.5 to 62.5, 62.5 to 77.5 and 77.5 to 80, so the segment miles are 12.5, 25, 25, 15 and 2.5, which add up to 80.

## Routing, ETA and weather pipeline

Every checkpoint gets its own arrival time and the forecast for that hour at that place. The pipeline below is built so each of those steps can be tested without a network.

**1. Routes (Mapbox Directions)**

- Request: driving profile, alternatives on, full-resolution GeoJSON geometry, per-segment distance and duration annotations, no turn-by-turn steps.
- Convert meters to miles with 1 mile = 1609.344 m.
- Annotations give a duration for every geometry segment, so ETAs reflect fast highway stretches and slow urban ones. If annotations are missing, fall back to proportional time along the route and add a warning.
- Mapbox returns up to 3 routes and often fewer on corridors with one dominant highway.

**2. Via-point fallback when fewer than 3 routes come back**

1. Take the midpoint of the primary route and offset it sideways, to the left and to the right, by 20% of the straight-line trip distance, limited to 10 to 60 miles.
2. Route origin to offset point to destination, up to 4 candidate calls in parallel (two sides, two positions along the route at 35% and 65%).
3. Keep a candidate only if it is no longer than 1.5 times the primary route and shares no more than 80% of its length (sampled every 5 miles, within 1 mile) with a route already kept.
4. Stop at 3 routes. If fewer remain, continue with what exists.

**3. Checkpoints and ETA**

1. Build arrays of cumulative miles and cumulative seconds at each geometry vertex.
2. Place checkpoints at mile 0, every N miles, and the destination. Position is found by linear interpolation between the two surrounding vertices.
3. ETA = departure time + cumulative seconds at that mile times the truck factor.
4. The forecast hour is the ETA rounded to the nearest whole hour, in UTC.

**4. Weather (Open-Meteo)**

Two paths feed the same domain code. The **browser path** (the app) fetches Open-Meteo itself and sends the hourly series with the request. The **server path** (no `weather` field) fetches it as described below. Both read the same variables in the same units, and supplied series are converted by the same parser, so identical data gives identical results.

- Variables: hourly wind speed at 10 m, rain, showers and snowfall. Units requested: mph and inches. Time zone: GMT, so all timestamps are UTC.
- Rain used for the rules = rain plus showers.
- Locations are rounded to a 0.1 degree grid (about 7 miles) so nearby checkpoints share one lookup and the cache hits often.
- Fetch the unique cells in batches of up to 50 locations, up to 4 requests in parallel. Server: 5 second timeout, one retry with a short backoff, and a per-minute 429 is waited out. Browser: 10 second timeout, one retry on a network error or 5xx, and any 429 stops the fetch with a message that names the quota (minutely, hourly or daily) read from the reason text. A 429 the browser cannot read (its error body is hidden when the response has no CORS headers) is reported as the weather service being unreachable, with a retry button.
- The full forecast series for each cell is cached for 30 minutes: on the server for the server path, and in the page for the browser path (matched by the exact cell coordinates the server named). Both the risk scoring and the heatmap read from it. Weather a client supplies is never written to the server cache.
- Verify in the first hour (see roadmap): exact variable names, that snowfall follows the inch unit, and the batch size limit.

**5. Corridor points for the heatmap**

1. Sample every route at 15 mile spacing.
2. Drop points that fall in the same 0.1 degree cell as an earlier point.
3. Cap at 200 points; if over, increase the spacing.
4. Return them in the analyze response as `corridor_points`, together with `corridor_cells`: their unique grid cells, rounded by the server from the points as sent (5 decimals), in first-seen order. The browser fetches exactly those cells and sends them back unchanged, so it holds no rounding logic. The heatmap endpoint scores each point for 49 hours using the same risk function and load weight.

**6. Geometry sent to the browser.** The full geometry is used for sampling on the server. The browser gets a simplified copy (Douglas-Peucker, about 50 m tolerance, capped near 2,000 points per route) so the map stays fast.

## API contracts

Four JSON endpoints, all stateless. The browser resolves addresses to coordinates itself, so the API never geocodes and has one fewer failure mode.

| Endpoint | Purpose |
| --- | --- |
| GET /api/health | Liveness check for the host and for warming a sleeping free-tier server |
| POST /api/plan | The weather an analysis needs: grid cells and hour window. Routing only, no weather call |
| POST /api/analyze | Routes, checkpoints, risk, recommendation, corridor points and cells |
| POST /api/heatmap | 49 hourly risk levels for each corridor point |

**POST /api/plan**

- Request: the same body as /api/analyze, without `weather`.
- Response: `cells` (list of [lat, lon] grid cells of every checkpoint of every route, unique) and `window` (`first_hour`, `last_hour`, UTC). It reuses the cached routing answer, so the later analyze repeats no routing call.

**POST /api/analyze request**

| Field | Type and rule |
| --- | --- |
| origin, destination | Object with lat (-90 to 90), lon (-180 to 180), optional label. The two must be at least 0.5 mile apart |
| departure\_time | ISO 8601 with a UTC offset. From the current hour to 7 days ahead |
| load\_weight\_lb | Integer, 0 to 200,000 |
| checkpoint\_interval\_miles | 10, 25 or 50. Default 25 |
| weather | Optional list of weather cells fetched by the browser. Absent or null means the server fetches the weather itself |

**The weather field** (also accepted by /api/heatmap). Each entry has exactly `lat`, `lon`, `time`, `wind_speed_10m`, `rain`, `showers`, `snowfall`, in the units requested from Open-Meteo (mph, inches). Checked strictly:

- At most 450 cells (3 routes times the 150-checkpoint cap, so any plan the server issues fits) and 1 to 400 hours per cell; no two entries in the same 0.1 degree cell.
- `time`: UTC hours written like `2026-11-02T14:00`, no zone suffix, real dates, strictly increasing.
- The four arrays have the same length as `time`; each value is a finite number of 0 or more, or null. Booleans, strings, NaN, infinity and negatives are rejected.
- Cells are matched to checkpoints by the server's own grid cell of `lat` and `lon`. The field is trusted for weather values only; cells nobody needs are ignored.
- A cell or hour that is missing makes its checkpoints unavailable and adds a warning; a null value stays unknown, never 0. If no needed cell was supplied the answer is 502 weather\_unavailable.
- The request body is limited to MAX\_REQUEST\_BYTES (5 MiB). A weather entry costs about 43 bytes per hour, so a typical Dallas to Chicago trip is about 0.2 MB and the largest trip the server accepts (450 cells, about 200 hours) about 4 MB.

**POST /api/analyze response**

- **meta**: request id, interval actually used, truck duration factor, forecast source, and a warnings list (interval raised, route fallback used, partial coverage, missing annotations).
- **routes** (up to 3), each with:
  - id, label, distance in miles, duration in seconds (truck-adjusted), departure and arrival times
  - display geometry (GeoJSON LineString, simplified)
  - summary: miles at each level, average risk, worst level, coverage percent, blocked flag
  - checkpoints: index, mile marker, lat, lon, ETA, forecast hour, wind in mph, rain and snow in inches per hour, segment miles, status (ok, partial, unavailable), and risk (level number, level name, deciding factor, the three individual levels, load rule applied)
- **recommendation**: recommended route id, reason lines, all\_blocked flag, and the ranking list with each route's sort key values.
- **corridor\_points**: list of \[lat, lon\] pairs, at most 200.
- **corridor\_cells**: the unique grid cells of those points, in first-seen order. They are the weather the heatmap needs.

**POST /api/heatmap**

- Request: points (list of \[lat, lon\], at most 200), departure\_time, load\_weight\_lb, and the optional weather field above.
- Response: start\_hour (UTC, departure rounded down to the hour), hours (49), and for each point its lat, lon and a list of 49 risk levels, with -1 where no forecast exists.

**Errors.** One shape for all: an error object with code, message and optional per-field details.

| Status | Code | When |
| --- | --- | --- |
| 400 | validation\_error | Any field rule above is broken |
| 422 | no\_route | The routing provider finds no drivable route |
| 413 | payload\_too\_large | The request body is over MAX\_REQUEST\_BYTES |
| 429 | rate\_limited | More than 30 requests a minute from one client. Plan, analyze and heatmap share the limit; one analysis uses three |
| 502 | routing\_unavailable | Mapbox fails after one retry |
| 502 | weather\_unavailable | Open-Meteo fails for every location. If only some locations fail, the response succeeds with those checkpoints unavailable and a warning |
| 500 | internal\_error | Anything unexpected. Logged with the request id, never with a stack trace in the response |

The response schema is written once as serializers and mirrored as TypeScript types, so a mismatch fails at build time.

## Data model

Nothing is stored permanently, so there is no relational schema to design. The model is a set of typed objects built per request, plus two cache entries.

**Domain objects (per request, never saved)**

| Object | Fields | Notes |
| --- | --- | --- |
| TripRequest | origin, destination, departure\_utc, load\_weight\_lb, interval\_miles | Validated once at the edge |
| Route | id, label, distance\_mi, duration\_s, geometry, cumulative\_mi, cumulative\_s | Full geometry stays server side |
| Checkpoint | index, mile, lat, lon, eta\_utc, forecast\_hour\_utc, segment\_mi | Created by sampling |
| WeatherSample | wind\_mph, rain\_in\_hr, snow\_in\_hr, each possibly missing | One per checkpoint |
| RiskResult | level, wind\_level, rain\_level, snow\_level, factor, load\_rule\_applied, status | Output of the risk function |
| RouteSummary | miles\_by\_level, avg\_risk, duration\_s, coverage\_pct, blocked | Input to ranking |
| Recommendation | route\_id, reasons, all\_blocked, ranking | Output of ranking |

**Cache entries**

| Key | Value | Time to live |
| --- | --- | --- |
| weather:{lat 1 decimal}:{lon 1 decimal} | Hourly series of wind, rain and snow for the cell | 30 minutes |
| route:{hash of origin, destination, provider} | Raw provider routes | 10 minutes |

A cache miss only costs latency, so a restart or a second server process cannot produce a wrong answer. Local memory is enough for a single small server; a Redis URL, if set, replaces it.

**Why no database.** The app has no users, no history and no shared state. A database would add a migration, a hosting cost and a failure point without improving any graded behavior.

**Optional later: shareable results.** Only if requested, one table: analysis\_run with id (UUID, primary key), created\_at, request (JSON), response (JSON), expires\_at. It is not part of the plan.

## Frontend, map and heatmap

The map stays smooth because the slider never triggers a network call or a React re-render of the map: all 49 hours arrive once and the slider only switches which value the heatmap reads.

**Screen layout.** A left panel holds the form, then the route comparison cards, then the recommendation. The map fills the rest. The heatmap slider sits along the bottom of the map.

**Components**

| Component | Job |
| --- | --- |
| TripForm | Origin and destination search with autocomplete, departure picker, load weight, interval select; validates before sending |
| RouteCards | One card per route: time, miles by level as a stacked bar, average risk, coverage, Recommended and Blocked badges; click selects the route |
| RecommendationBanner | The reason text, or the all-blocked warning |
| MapView | Owns the map instance and all layers |
| CheckpointPopup | ETA, forecast hour, wind, rain, snow, level, deciding factor, load-rule note |
| HeatmapControl | Slider 0 to 48, hour label in local time, play and pause |

**Map layers**

| Layer | Source | Style and behaviour |
| --- | --- | --- |
| Routes | One GeoJSON feature per route | Three distinct line colors; selected route thicker with the others dimmed; click selects |
| Checkpoints | One GeoJSON point collection per selected route | Circle color from the level (data-driven); unavailable shown hollow; click opens the popup |
| Heatmap | One GeoJSON point collection, 49 level properties per point | Heatmap layer, weight = level divided by 4; the slider switches the property the weight reads |

**Heatmap behaviour**

- Color ramp runs transparent, green, yellow, orange, red, dark red as density rises. Radius grows with zoom so points 15 miles apart merge into one continuous band at every zoom.
- Because heatmap color shows density, an isolated point looks milder than the same level in a cluster. The checkpoint circles carry the exact levels, and the popup text always states the level in words.
- Playing the slider advances one hour every 400 ms using a single timer.

**Performance rules**

1. Draw routes from the simplified geometry only.
2. Update the slider through the map's own property API from a ref, and update React state only for the hour label, at most once per animation frame.
3. Parse the heatmap response once into a map-ready collection; never rebuild it per tick.
4. Cancel in-flight requests when a new analysis starts.
5. Fit the map to the routes once per analysis, not on every state change.

**States.** Idle, loading with a skeleton in the cards, results, partial results (with the warnings list), heatmap loading (route results already usable), and error with a retry button. Colors are always paired with text or an icon, so the level is readable without color vision.

## Edge cases and failure scenarios

Every row below has a defined behaviour and a test or manual check. The rule behind all of them: never show a Low rating where the real answer is unknown.

| Scenario | Behaviour |
| --- | --- |
| Origin and destination within 0.5 mile | 400 validation error |
| Departure before the current hour or more than 7 days out | 400 validation error that names the allowed window |
| Load weight 0 | Allowed; only the wind rules for any load apply |
| Load exactly 30,000 or 40,000 lb | Rules need strictly more, so not triggered |
| Weather exactly on a boundary (25, 35, 45, 55 mph; 0.25, 0.50 in/hr) | Higher level, per decision 4 |
| Rain exactly 1.00 or snow exactly 3.0 | Severe, not No Travel |
| No road between the points (island, closed region) | 422 no\_route with a plain message |
| Provider returns 1 or 2 routes | Via-point fallback; if still short, show what exists with a notice |
| Two routes nearly identical | Fallback candidates over 80% overlap are dropped; routes the provider itself returns are kept |
| Trip longer than the forecast covers | Later checkpoints unavailable; coverage shown; no Low assumed |
| Open-Meteo fails for some locations | Those checkpoints unavailable with a warning; the rest are scored |
| A browser batch fails twice, or the supplied weather lacks cells or hours | The server marks those checkpoints unavailable with a warning; never Low |
| Open-Meteo answers 429 to the browser | No scoring. The message names the quota: minutely (wait a minute), hourly (about an hour), daily (resets at 00:00 UTC), or unknown. A 429 the browser cannot read shows as the weather service being unreachable, with a retry button |
| Weather supplied that is malformed, too large or for the wrong cells | 400 validation\_error with the field path, 413 payload\_too\_large, or 502 weather\_unavailable when no needed cell was supplied |
| Plan and analyze see different routes (routing cache expired, or another server process answered) | Checkpoints whose cell was not fetched are unavailable with a warning; never Low |
| Open-Meteo fails entirely | Server path: 502 weather\_unavailable. Browser path: the weather step fails with a retry button. Either way no safety score is shown without weather |
| Mapbox fails or times out | One retry, then 502 routing\_unavailable |
| Annotation arrays missing or the wrong length | Proportional time along the route and a warning |
| Very long route (over 150 checkpoints) | Interval raised to the next allowed value; reported in meta |
| Route crosses the antimeridian or poles | Not supported; documented |
| Trip crosses time zones | All times are computed in UTC; the UI shows them in the viewer's local zone with the zone label |
| Trip longer than a driving day | ETAs assume continuous driving; documented as a limitation because rest rules are out of scope |
| Departure at 00:20 | Checkpoint ETAs round to the nearest hour independently |
| All routes blocked | Least-blocked route recommended with a warning; no silent normal recommendation |
| Free-tier server asleep | First request is slow; the UI shows a still-working message after 5 seconds and the health endpoint is used to warm the server before a demo |
| Browser offline or request cancelled | Error state with retry; a cancelled request shows nothing |
| Heatmap request fails | Routes stay usable; the heatmap control shows an inline retry |
| Double submit | The earlier request is cancelled and its late reply is ignored |

## Testing and validation

The 40% logic grade is won by tests that pin every threshold, rule and ranking step, so most testing effort goes to the pure domain code.

| Level | What it covers | Tool |
| --- | --- | --- |
| Domain unit tests | Every threshold value and the value just below it for wind, rain and snow; each load rule at, below and above its weight; precedence of overrides; mile attribution; ETA hour rounding; each ranking key and tie-break | pytest, table-driven |
| Property tests | Raising a weather value or the load never lowers the level; segment miles always sum to the route length; ranking is the same for any input order | Hypothesis |
| Provider tests | Parsing of real recorded Mapbox and Open-Meteo responses, including a missing-annotation case and a short forecast | Saved fixtures, no network in CI |
| API tests | Validation errors, each error code, one full analyze run with fake providers | DRF test client |
| Frontend tests | Form validation, rendering of each state, a risk-to-color mapping check | Vitest and Testing Library |
| Smoke test | Submit one real trip against the hosted app and check three routes, checkpoints and the heatmap appear | Manual checklist, optionally Playwright |

**Scenario fixtures** (fake weather and fake routes, used by the API tests and in the Loom)

1. Calm day: all routes Low; the shortest wins on time.
2. Heavy load in 40 mph wind: the same weather scores Severe at 45,000 lb and High at 35,000 lb.
3. Storm on the fastest route: a slower route with fewer Severe miles is recommended.
4. No Travel segment on every route: all\_blocked warning appears.
5. Forecast gap: coverage drops below 100% and the UI says so.

**Done means:** domain code fully covered; every row of the edge case table has a test or a named manual check; the same trip analyzed twice returns identical results when the weather is unchanged.

## Deployment, configuration and security

Two deployables: the Django API on Render or Railway, and the static React build on Vercel. All tunable numbers are environment variables with the defaults in this document.

**Configuration**

| Variable | Used by | Default or note |
| --- | --- | --- |
| MAPBOX\_API\_TOKEN | API | Server-side token with Directions access |
| VITE\_MAPBOX\_PUBLIC\_TOKEN | Web | Public token restricted to the web app's URL |
| VITE\_API\_BASE\_URL | Web | URL of the deployed API |
| ALLOWED\_ORIGINS | API | The web app's URL, for CORS |
| DJANGO\_SECRET\_KEY, DEBUG, ALLOWED\_HOSTS | API | Standard Django; DEBUG off in production |
| TRUCK\_DURATION\_FACTOR | API | 1.10 |
| MAX\_CHECKPOINTS\_PER\_ROUTE | API | 150 |
| WEATHER\_CACHE\_TTL\_S | API | 1800 (server-fetch path only; the browser holds fetched cells for the same 30 minutes) |
| MAX\_REQUEST\_BYTES | API | 5242880 (5 MiB) |
| REDIS\_URL | API | Optional; local memory cache if absent |

**Security and abuse limits**

- Secrets only in host environment settings, never in the repo; an .env.example lists the names.
- CORS allows only the web app's origin.
- 30 requests a minute per client on the two POST endpoints, to protect the free-tier quotas of both APIs.
- A request size limit (MAX\_REQUEST\_BYTES) and the field rules above; weather supplied by a client is validated strictly, used for weather values only, and never cached; no user text is stored or logged beyond the request id.
- The browser never sees the server token. It calls Open-Meteo directly (no key) and keeps its attribution visible.

**Operations**

- Each request gets an id returned in the response and written to the logs along with the time spent in each upstream call.
- A health endpoint for the host's check.
- Free-tier servers sleep. Call the health endpoint before the Loom recording and before submitting, so a reviewer's first click is fast.

**Repository layout.** One repo with backend and frontend folders, a README with setup in under 10 commands, the assumptions list, the architecture picture, and a link to the live app and the Loom.

## Implementation roadmap

The plan uses 15 of the 16 allowed hours and keeps one hour as buffer. It builds the graded logic first, on fakes, so the 40% logic score is secured before any API or map work starts.

| Phase | Deliverable | Depends on | Hours | Done when |
| --- | --- | --- | --- | --- |
| 0. Foundations | Repo, Django and Vite skeletons, API keys, hello-world deployed to both hosts, spike on the three unknowns below | None | 1.0 | Both hosts serve a page and the health endpoint |
| 1. Domain engine | Constants, risk function, load rules, sampling, ETA, mile attribution, ranking, with tests | 0 | 2.5 | All domain tests and property tests pass |
| 2. Providers | Mapbox adapter with via-point fallback, Open-Meteo adapter with grid cache, saved fixtures | 0 | 2.5 | Real trip returns 3 routes and weather; fixtures recorded |
| 3. Analyze API | Serializers, service, error mapping, throttling, API tests | 1, 2 | 1.5 | Scenario fixtures 1 to 5 pass through the endpoint |
| 4. Frontend core | Form with geocoding, routes and checkpoints on map, popups, route cards, recommendation banner | 3 | 3.0 | One real trip works end to end locally |
| 5. Heatmap | Heatmap endpoint, layer, slider, play button | 3, 4 | 1.5 | Slider moves smoothly across 49 hours |
| 6. Hardening | Edge-case table checked, loading and error states, performance check on a 1,500 mile trip, deploy | 4, 5 | 1.5 | Hosted app passes the smoke test |
| 7. Docs and Loom | README with assumptions, architecture picture, Loom recorded | 6 | 1.5 | Repo, live link and Loom link ready to submit |

**First-hour spikes** (each is a quick call, not a build)

1. Call Mapbox for a 1,000 mile trip with alternatives on. Check how many routes return and that the annotation arrays line up with the geometry.
2. Call Open-Meteo for 50 locations. Confirm the variable names for rain, showers and snowfall, that snowfall follows the inch unit, and the batch size limit.
3. Confirm the cold-start time of the chosen API host.

If a spike contradicts this document, change the document first, then the code.

**If time runs short, cut in this order:** play button, via-point fallback tuning (keep the basic version), route cards polish. Never cut domain tests, the all-blocked warning, or the README assumptions.

**Loom outline (about 7 minutes):** 1 min what the app does; 2 min live demo of one trip and the heatmap slider; 2 min the risk rules and the tests that pin them; 1 min architecture and why there is no database; 1 min assumptions and limits.

**Open questions for you**

- Confirm Mapbox as the routing provider (decision 17).
- Confirm the checkpoint interval is a user setting (decision 1).
- Confirm that No Travel miles rank first (decision 12). If the assessment owner has a different rule, this is the one most likely to differ.
