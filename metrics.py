"""Prometheus metrics for the API, served at GET /metrics.

Labels only ever hold fixed values (HTTP method, route template, status code,
exception class, SQL verb), never user input or IDs. That keeps the number of
time series small and keeps private data out of the metrics.
"""

from prometheus_client import Counter, Gauge, Histogram, disable_created_metrics
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY
from sqlalchemy.pool import QueuePool

# Skip the extra "*_created" timestamp series the library adds to every counter
disable_created_metrics()

# ---------- HTTP ----------

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests handled, by method, route template and status code",
    ["method", "path", "status_code"],
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Time spent handling a request, by method and route template",
    ["method", "path"],
    # 5 ms to 10 s: covers normal requests and the slow ones worth alerting on
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Requests currently being handled",
)

HTTP_SERVER_ERRORS = Counter(
    "http_server_errors_total",
    "Responses with a 5xx status, by route template and exception class",
    ["method", "path", "status_code", "error_type"],
)

# ---------- Database ----------

DB_UP = Gauge(
    "jobtracker_db_up",
    "1 if the last database check (SELECT 1) succeeded, 0 if it failed",
)

DB_CHECK_SECONDS = Gauge(
    "jobtracker_db_check_duration_seconds",
    "How long the last database check took",
)

DB_ERRORS = Counter(
    "jobtracker_db_errors_total",
    "Errors raised by the database driver, by SQLAlchemy class and SQL verb",
    ["error_type", "operation"],
)

DB_POOL_EXHAUSTED = Counter(
    "jobtracker_db_pool_exhausted_total",
    "Requests that gave up waiting for a free database connection",
)


class PoolCollector:
    """Reads the connection pool's numbers at scrape time.

    Only Postgres's QueuePool reports them; with SQLite nothing is exported.
    """

    def __init__(self, engine):
        self.engine = engine

    def collect(self):
        pool = self.engine.pool
        if not isinstance(pool, QueuePool):
            return
        values = {
            "jobtracker_db_pool_size": ("Connections the pool keeps open", pool.size()),
            "jobtracker_db_pool_checked_out": ("Connections currently in use by requests", pool.checkedout()),
            "jobtracker_db_pool_checked_in": ("Open connections waiting in the pool", pool.checkedin()),
            # Negative while the pool hasn't opened all its connections yet
            "jobtracker_db_pool_overflow": ("Connections open beyond pool_size", pool.overflow()),
        }
        for name, (help_text, value) in values.items():
            yield GaugeMetricFamily(name, help_text, value=value)


_pool_collector_registered = False


def register_pool_metrics(engine) -> None:
    global _pool_collector_registered
    if not _pool_collector_registered:
        REGISTRY.register(PoolCollector(engine))
        _pool_collector_registered = True