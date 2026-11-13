"""JSON logging for the whole app.

Every log line is one JSON object on stdout, so `docker compose logs api` can be
read by people and parsed by tools such as TraceLens.

Log an event with:
    log_event(logger, "job_created", job_id=job.id, user_id=user_id)

Never pass passwords, tokens, emails or free text the user typed (company,
notes, search terms) as fields.
"""

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

SERVICE_NAME = os.getenv("SERVICE_NAME", "jobtracker-api")

# Set by the request middleware, so every log line written while a request is
# being handled carries that request's ID, including lines from crud.py.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "service": SERVICE_NAME,
            "level": record.levelname,
            "logger": record.name,
        }
        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id

        fields = getattr(record, "fields", None)
        if fields:
            entry.update(fields)
        else:
            # Plain messages, e.g. uvicorn's startup lines
            entry["event"] = "log_message"
            entry["message"] = record.getMessage()

        if record.exc_info and record.exc_info[0]:
            # The class only: exception messages can contain SQL or user data
            entry["error_type"] = record.exc_info[0].__name__
        return json.dumps(entry, default=str)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": {"event": event, **fields}})


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    # Send uvicorn's own messages (startup, shutdown, errors) through the JSON
    # handler. Its access log is replaced by our middleware's http_request line.
    for name in ("uvicorn", "uvicorn.error"):
        uv = logging.getLogger(name)
        uv.handlers = []
        uv.propagate = True
    logging.getLogger("uvicorn.access").disabled = True