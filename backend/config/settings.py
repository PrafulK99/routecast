import os
from pathlib import Path

from dotenv import load_dotenv

from domain.constants import DEFAULT_TRUCK_FACTOR, MAX_CHECKPOINTS_PER_ROUTE as DEFAULT_MAX_CHECKPOINTS
from providers.constants import DEFAULT_WEATHER_CACHE_TTL_S

BASE_DIR = Path(__file__).resolve().parent.parent

# Repo-root .env; real environment variables take precedence.
load_dotenv(BASE_DIR.parent / ".env")


def env_list(name):
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def env_number(name, default, cast):
    """A numeric setting from the environment; a blank value means the default."""
    return cast(os.environ.get(name) or default)


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")

CORS_ALLOWED_ORIGINS = env_list("ALLOWED_ORIGINS")

# Tunables (docs/DESIGN.md, Configuration)
TRUCK_DURATION_FACTOR = env_number("TRUCK_DURATION_FACTOR", DEFAULT_TRUCK_FACTOR, float)
MAX_CHECKPOINTS_PER_ROUTE = env_number("MAX_CHECKPOINTS_PER_ROUTE", DEFAULT_MAX_CHECKPOINTS, int)
WEATHER_CACHE_TTL_S = env_number("WEATHER_CACHE_TTL_S", DEFAULT_WEATHER_CACHE_TTL_S, int)

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "api",
]

MIDDLEWARE = [
    "api.middleware.RequestIdMiddleware",
    "django.middleware.gzip.GZipMiddleware",  # inside the request-id layer, so compressed replies still carry it
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# Stateless API: no database (see docs/DESIGN.md, Data model).
DATABASES = {}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "api.errors.exception_handler",
    "DEFAULT_THROTTLE_RATES": {"api": "30/min"},
    # Proxies in front of the app (1 on the host); the client is then the last
    # X-Forwarded-For entry, which the host's proxy adds and a visitor cannot forge.
    "NUM_PROXIES": env_number("NUM_PROXIES", 1, int),
}

# Local memory is enough for one small server (docs/DESIGN.md, Data model). Throttle
# counters live here too, so they are per process.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "OPTIONS": {"MAX_ENTRIES": 2000},
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    # httpx logs every request URL at INFO, and Mapbox takes its token in the query string.
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
}

USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
