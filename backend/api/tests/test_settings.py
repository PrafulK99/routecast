import logging

import pytest
from django.conf import settings

from config.settings import env_number


def test_env_number_reads_the_environment(monkeypatch):
    monkeypatch.setenv("SOME_NUMBER", "1.25")

    assert env_number("SOME_NUMBER", 1.10, float) == 1.25


def test_env_number_uses_the_default_when_unset_or_blank(monkeypatch):
    monkeypatch.delenv("SOME_NUMBER", raising=False)
    assert env_number("SOME_NUMBER", 150, int) == 150

    monkeypatch.setenv("SOME_NUMBER", "")
    assert env_number("SOME_NUMBER", 150, int) == 150


def test_env_number_rejects_garbage(monkeypatch):
    monkeypatch.setenv("SOME_NUMBER", "lots")

    with pytest.raises(ValueError):
        env_number("SOME_NUMBER", 150, int)


def test_design_defaults(monkeypatch):
    # Only meaningful with a clean environment, so evaluate the same expressions
    # settings.py uses against an empty one.
    from domain.constants import DEFAULT_TRUCK_FACTOR, MAX_CHECKPOINTS_PER_ROUTE
    from providers.constants import DEFAULT_WEATHER_CACHE_TTL_S

    for name in ("TRUCK_DURATION_FACTOR", "MAX_CHECKPOINTS_PER_ROUTE", "WEATHER_CACHE_TTL_S", "NUM_PROXIES"):
        monkeypatch.delenv(name, raising=False)

    assert env_number("TRUCK_DURATION_FACTOR", DEFAULT_TRUCK_FACTOR, float) == 1.10
    assert env_number("MAX_CHECKPOINTS_PER_ROUTE", MAX_CHECKPOINTS_PER_ROUTE, int) == 150
    assert env_number("WEATHER_CACHE_TTL_S", DEFAULT_WEATHER_CACHE_TTL_S, int) == 1800
    assert env_number("NUM_PROXIES", 1, int) == 1


def test_the_cache_is_local_memory_and_no_database_is_configured():
    assert settings.CACHES["default"]["BACKEND"] == "django.core.cache.backends.locmem.LocMemCache"
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.dummy"
    assert settings.REST_FRAMEWORK["NUM_PROXIES"] >= 0
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] == {"api": "30/min"}


@pytest.mark.parametrize("name", ["httpx", "httpcore"])
def test_http_client_logs_cannot_carry_the_mapbox_token(name):
    # httpx logs full request URLs at INFO, and the token is in the query string.
    assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
