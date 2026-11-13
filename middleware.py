"""Request middleware: request IDs, latency, status and errors.

For every request it:
- reuses a safe incoming X-Request-ID, or generates one, and returns it in the
  X-Request-ID response header
- makes that ID available to every log line written during the request
- writes one "http_request" log line with the route template (never the raw
  URL, which can contain IDs and query strings), status and duration
- turns an unhandled exception into a logged 500 with the exception class only

It never reads or logs headers other than X-Request-ID, so tokens never reach
the logs.
"""

import logging
import re
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from logging_config import log_event, request_id_var

logger = logging.getLogger("jobtracker.access")

REQUEST_ID_HEADER = "X-Request-ID"
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:16]}"


def route_template(request: Request) -> str:
    # "/jobs/{job_id}" rather than "/jobs/12345"
    route = request.scope.get("route")
    return getattr(route, "path", "<unmatched>")


async def request_middleware(request: Request, call_next):
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    request_id = incoming if SAFE_REQUEST_ID.match(incoming) else new_request_id()
    request.state.request_id = request_id
    token = request_id_var.set(request_id)

    start = time.perf_counter()
    try:
        try:
            response = await call_next(request)
        except Exception as exc:
            request.state.error_type = type(exc).__name__
            response = JSONResponse(status_code=500, content={"detail": "Internal server error"})

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        status = response.status_code
        level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO

        fields = {
            "method": request.method,
            "path": route_template(request),
            "status_code": status,
            "duration_ms": duration_ms,
        }
        error_type = getattr(request.state, "error_type", None)
        if error_type:
            fields["error_type"] = error_type
        log_event(logger, "http_request", level, **fields)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        request_id_var.reset(token)