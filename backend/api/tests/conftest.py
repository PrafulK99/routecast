import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from services import container

from .helpers import NOW, REQUEST_ID, ScenarioWeather, calm, three_routes


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """A frozen clock and request id, and an empty cache so the throttle starts fresh."""
    cache.clear()
    monkeypatch.setattr("api.serializers._now", lambda: NOW)
    monkeypatch.setattr("api.middleware.new_request_id", lambda: REQUEST_ID)
    yield
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def providers(monkeypatch):
    """Install fake providers. Defaults: three routes and calm weather everywhere."""

    def install(routing=None, weather=None):
        routing = routing or three_routes()
        weather = weather or ScenarioWeather(calm)
        monkeypatch.setattr(container, "routing_provider", lambda: routing)
        monkeypatch.setattr(container, "weather_provider", lambda: weather)
        return routing, weather

    return install
