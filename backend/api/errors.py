"""One error shape for every failure: {"error": {"code", "message", "fields", "request_id"}}."""

import logging

from rest_framework import status
from rest_framework.exceptions import APIException, ParseError, Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from providers.errors import (
    NoRouteError,
    RoutingUnavailableError,
    WeatherRateLimitedError,
    WeatherUnavailableError,
)
from services.errors import RouteTooLongError

logger = logging.getLogger("routecast.api")

# exception type -> (HTTP status, code); the message comes from the exception.
PROVIDER_ERRORS = (
    (NoRouteError, status.HTTP_422_UNPROCESSABLE_ENTITY, "no_route"),
    (RouteTooLongError, status.HTTP_422_UNPROCESSABLE_ENTITY, "route_too_long"),
    (RoutingUnavailableError, status.HTTP_502_BAD_GATEWAY, "routing_unavailable"),
    (WeatherUnavailableError, status.HTTP_502_BAD_GATEWAY, "weather_unavailable"),
    (WeatherRateLimitedError, status.HTTP_503_SERVICE_UNAVAILABLE, "weather_rate_limited"),
)


def _flatten(detail, prefix=""):
    """Nested serializer errors as {"origin.lat": ["message"], ...}."""
    fields = {}
    if isinstance(detail, dict):
        for key, value in detail.items():
            fields.update(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(detail, list):
        if all(isinstance(item, str) for item in detail):
            if detail:
                fields[prefix or "non_field_errors"] = [str(item) for item in detail]
        else:
            for index, item in enumerate(detail):
                fields.update(_flatten(item, f"{prefix}.{index}" if prefix else str(index)))
    else:
        fields[prefix or "non_field_errors"] = [str(detail)]
    return fields


def error_response(request, http_status, code, message, fields=None, headers=None):
    body = {
        "error": {
            "code": code,
            "message": message,
            "fields": fields or {},
            "request_id": getattr(request, "request_id", None),
        }
    }
    return Response(body, status=http_status, headers=headers)


def exception_handler(exc, context):
    request = context.get("request")

    if isinstance(exc, ValidationError):
        return error_response(
            request, status.HTTP_400_BAD_REQUEST, "validation_error",
            "Some fields are invalid. See fields for details.", _flatten(exc.detail),
        )
    if isinstance(exc, ParseError):
        return error_response(
            request, status.HTTP_400_BAD_REQUEST, "validation_error", "The request body is not valid JSON."
        )
    if isinstance(exc, Throttled):
        wait = int(exc.wait) if exc.wait else None
        return error_response(
            request, status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited",
            f"Too many requests. Try again in {wait} seconds." if wait else "Too many requests.",
            headers={"Retry-After": str(wait)} if wait else None,
        )

    for exc_type, http_status, code in PROVIDER_ERRORS:
        if isinstance(exc, exc_type):
            logger.warning("%s request_id=%s", code, getattr(request, "request_id", None))
            return error_response(request, http_status, code, str(exc))

    # Other DRF errors (405, 415, ...) keep their own status.
    if isinstance(exc, APIException):
        response = drf_exception_handler(exc, context)
        headers = {
            name: value
            for name, value in response.items()
            if name in ("Allow", "WWW-Authenticate", "Retry-After")
        }
        return error_response(
            request, response.status_code, exc.default_code, str(exc.detail), headers=headers
        )

    # Anything else: details go to the log with the request id, never to the client.
    logger.exception("internal_error request_id=%s", getattr(request, "request_id", None))
    return error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "Something went wrong on our side. Quote the request id if you report it.",
    )
