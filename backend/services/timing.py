"""Time spent in each upstream call, logged once per request with the request id."""

import logging
from contextlib import contextmanager
from time import perf_counter


@contextmanager
def timed(timings: dict[str, float], name: str):
    started = perf_counter()
    try:
        yield
    finally:
        timings[name] = timings.get(name, 0.0) + (perf_counter() - started) * 1000


def log_timings(
    logger: logging.Logger, label: str, request_id: str, timings: dict[str, float], started: float
):
    """One line: no coordinates or other user input, only the id and durations."""
    parts = " ".join(f"{name}_ms={ms:.0f}" for name, ms in timings.items())
    total_ms = (perf_counter() - started) * 1000
    logger.info("%s request_id=%s %s total_ms=%.0f", label, request_id, parts, total_ms)
