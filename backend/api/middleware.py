import logging
import uuid
from time import perf_counter

from providers.request_context import request_id_var

logger = logging.getLogger("routecast.request")


def new_request_id() -> str:
    return uuid.uuid4().hex


class RequestIdMiddleware:
    """Gives every request an id, returns it in X-Request-ID and logs one line.

    The line holds no coordinates or other user input (docs/DESIGN.md, Security).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = new_request_id()
        started = perf_counter()
        token = request_id_var.set(request.request_id)  # for log lines written inside providers
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response["X-Request-ID"] = request.request_id
        logger.info(
            "request request_id=%s method=%s path=%s status=%s total_ms=%.0f",
            request.request_id,
            request.method,
            request.path,
            response.status_code,
            (perf_counter() - started) * 1000,
        )
        return response
