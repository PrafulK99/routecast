"""Provider tunables (docs/DESIGN.md, Routing, ETA and weather pipeline)."""

METERS_PER_MILE = 1609.344
RETRY_BACKOFF_S = 0.5

# Mapbox Directions
MAPBOX_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving"
MAPBOX_TIMEOUT_S = 10.0
ROUTE_CACHE_TTL_S = 600
NO_ROUTE_CODES = ("NoRoute", "NoSegment")
# Mapbox answers HTTP 422 "Route exceeds maximum distance limitation" for trips too far to route
# (for example across an ocean): the same answer to the user as "no road between the points".
DISTANCE_LIMIT_MESSAGE = "maximum distance"

# Via-point fallback. Mapbox returns at most 2 routes (alternatives=true; a number is refused), so the
# third comes from a via point. Values chosen from a sweep over six real trips.
MAX_ROUTES = 3
# Candidate via points: (position along the primary route, offset as a share of the straight-line trip
# distance). Each setting goes to both sides, so 2 settings = 4 candidate calls, 5 Mapbox calls in all.
VIA_CANDIDATES = ((0.35, 0.20), (0.65, 0.40))
VIA_OFFSET_MIN_MILES = 10
VIA_OFFSET_MAX_MILES = 600
VIA_MAX_LENGTH_RATIO = 1.5  # candidate length vs the primary route
VIA_MAX_OVERLAP = 0.80  # a candidate may share at most this much with a route already kept
# Among valid candidates, the best is the lowest (worst overlap + penalty x extra length ratio).
VIA_LENGTH_PENALTY = 1.0
# A route Mapbox itself returns that lies this much on an earlier route is a duplicate and is dropped.
PROVIDER_DUPLICATE_OVERLAP = 0.95
OVERLAP_SPACING_MILES = 5
OVERLAP_TOLERANCE_MILES = 1
VIA_MAX_WORKERS = 4

# Open-Meteo (weather data by Open-Meteo.com, CC BY 4.0)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_HOURLY = "wind_speed_10m,rain,showers,snowfall"
WEATHER_TIMEOUT_S = 5.0
WEATHER_BATCH_SIZE = 50
WEATHER_MAX_WORKERS = 4
MAX_FORECAST_DAYS = 16
# A 429 whose reason says "minutely" is retried after these waits (plus jitter), so
# the extra wait stays under 10 seconds. Hourly and daily limits are not retried.
WEATHER_RATE_LIMIT_DELAYS_S = (2.0, 5.0)
WEATHER_RATE_LIMIT_JITTER_S = 0.5
WEATHER_REASON_MAX_CHARS = 200
DEFAULT_WEATHER_CACHE_TTL_S = 1800
