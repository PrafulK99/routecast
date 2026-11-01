"""Provider tunables (docs/DESIGN.md, Routing, ETA and weather pipeline)."""

METERS_PER_MILE = 1609.344
RETRY_BACKOFF_S = 0.5

# Mapbox Directions
MAPBOX_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving"
MAPBOX_TIMEOUT_S = 10.0
ROUTE_CACHE_TTL_S = 600
NO_ROUTE_CODES = ("NoRoute", "NoSegment")

# Via-point fallback
MAX_ROUTES = 3
VIA_OFFSET_FRACTION = 0.20  # of the straight-line trip distance
VIA_OFFSET_MIN_MILES = 10
VIA_OFFSET_MAX_MILES = 60
VIA_POSITIONS = (0.35, 0.65)  # fractions along the primary route
VIA_MAX_LENGTH_RATIO = 1.5  # candidate length vs the primary route
VIA_MAX_OVERLAP = 0.80
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
DEFAULT_WEATHER_CACHE_TTL_S = 1800
