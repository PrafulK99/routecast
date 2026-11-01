"""The id of the request being served, for log lines written deep inside providers.

The API middleware sets it; providers that run work in threads copy the context
into each thread (contextvars.copy_context) so the id follows the work.
"""

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
