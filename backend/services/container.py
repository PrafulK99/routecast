"""The real providers, built once. Tests replace these two functions with fakes."""

from functools import lru_cache

import httpx
from django.conf import settings
from django.core.cache import cache

from providers.interfaces import RoutingProvider, WeatherProvider
from providers.mapbox import MapboxRoutingProvider
from providers.openmeteo import OpenMeteoWeatherProvider


@lru_cache(maxsize=1)
def _http_client() -> httpx.Client:
    return httpx.Client()


@lru_cache(maxsize=1)
def routing_provider() -> RoutingProvider:
    return MapboxRoutingProvider.from_env(_http_client(), cache)


@lru_cache(maxsize=1)
def weather_provider() -> WeatherProvider:
    return OpenMeteoWeatherProvider(_http_client(), cache, ttl_s=settings.WEATHER_CACHE_TTL_S)
