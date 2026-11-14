"""Tests for logging, request IDs and request tracking (checklist items 1-3)."""

import json
import logging

import pytest

import crud
from logging_config import JSONFormatter
from tests.test_jobs import auth_headers, client, create_job, test_user  # noqa: F401


class CaptureHandler(logging.Handler):
    """Collects log lines as parsed JSON, exactly as they would be printed."""

    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(json.loads(JSONFormatter().format(record)))

    def events(self, name):
        return [line for line in self.lines if line["event"] == name]


@pytest.fixture
def logs():
    handler = CaptureHandler()
    app_logger = logging.getLogger("jobtracker")
    app_logger.addHandler(handler)
    old_level = app_logger.level
    app_logger.setLevel(logging.INFO)
    yield handler
    app_logger.removeHandler(handler)
    app_logger.setLevel(old_level)


# ---------- 1. Structured JSON logging ----------

def test_log_lines_are_json_with_required_fields(client, logs):
    client.get("/")
    line = logs.events("http_request")[0]
    assert {"timestamp", "service", "level", "logger", "event", "request_id"} <= line.keys()
    assert line["service"] == "jobtracker-api"
    assert line["timestamp"].endswith("Z")


def test_job_lifecycle_events(client, logs):
    headers = auth_headers(client, "events@example.com")
    job = create_job(client, headers).json()
    client.patch(f"/jobs/{job['id']}", headers=headers, json={"status": "Interview", "notes": "private"})
    client.delete(f"/jobs/{job['id']}", headers=headers)

    assert [e["event"] for e in logs.lines if e["event"].startswith("job_")] == [
        "job_application_created", "job_application_updated", "job_application_deleted"]
    assert logs.events("job_application_created")[0]["status"] == "Applied"
    assert logs.events("job_application_updated")[0]["fields"] == ["notes", "status"]


def test_failed_login_is_logged_without_email(client, test_user, logs):
    client.post("/auth/login", json={"email": test_user["email"], "password": "wrong-password"})
    failed = logs.events("auth_login_failed")
    assert len(failed) == 1 and failed[0]["level"] == "WARNING"
    assert test_user["email"] not in json.dumps(logs.lines)


def test_logs_contain_no_secrets_or_user_text(client, test_user, logs):
    login = client.post("/auth/login", json={"email": test_user["email"], "password": test_user["password"]})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    create_job(client, headers, company="SecretCompany", notes="private note")
    client.get("/jobs", headers=headers, params={"company": "SecretCompany"})

    everything = json.dumps(logs.lines)
    for secret in (test_user["password"], test_user["email"], token, "SecretCompany", "private note"):
        assert secret not in everything


# ---------- 2. Request IDs ----------

def test_request_id_generated_and_returned(client):
    response = client.get("/")
    assert response.headers["X-Request-ID"].startswith("req-")


def test_incoming_request_id_is_reused(client, logs):
    response = client.get("/", headers={"X-Request-ID": "tracelens-42"})
    assert response.headers["X-Request-ID"] == "tracelens-42"
    assert logs.events("http_request")[0]["request_id"] == "tracelens-42"


def test_unsafe_request_id_is_replaced(client):
    response = client.get("/", headers={"X-Request-ID": "bad id <script>"})
    assert response.headers["X-Request-ID"].startswith("req-")


def test_request_id_reaches_app_logs(client, logs):
    headers = auth_headers(client, "trace@example.com")
    headers["X-Request-ID"] = "trace-create-1"
    create_job(client, headers)
    created = logs.events("job_application_created")[0]
    request = [e for e in logs.events("http_request") if e["path"] == "/jobs"][0]
    assert created["request_id"] == request["request_id"] == "trace-create-1"


def test_no_request_id_outside_requests():
    handler = CaptureHandler()
    logging.getLogger("jobtracker.test").addHandler(handler)
    logging.getLogger("jobtracker.test").warning("outside a request")
    assert "request_id" not in handler.lines[0]


# ---------- 3. Latency and status tracking ----------

def test_request_line_has_status_and_duration(client, logs):
    client.get("/")
    line = logs.events("http_request")[0]
    assert line["method"] == "GET" and line["path"] == "/" and line["status_code"] == 200
    assert isinstance(line["duration_ms"], float) and line["duration_ms"] >= 0
    assert line["level"] == "INFO"


def test_route_template_used_instead_of_ids(client, logs):
    headers = auth_headers(client, "ids@example.com")
    client.get("/jobs/98765", headers=headers)
    line = [e for e in logs.events("http_request") if e["status_code"] == 404][0]
    assert line["path"] == "/jobs/{job_id}"
    assert line["level"] == "WARNING"
    assert "98765" not in json.dumps(logs.lines)


def test_unknown_url_is_not_logged_verbatim(client, logs):
    client.get("/secret-path-123")
    assert logs.events("http_request")[0]["path"] == "<unmatched>"
    assert "secret-path-123" not in json.dumps(logs.lines)


def test_unhandled_exception_returns_500_and_logs_class(client, logs, monkeypatch):
    headers = auth_headers(client, "boom@example.com")

    def explode(*args, **kwargs):
        raise RuntimeError("contains private details")

    monkeypatch.setattr(crud, "get_job_by_id_for_user", explode)
    response = client.get("/jobs/1", headers=headers)

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["X-Request-ID"].startswith("req-")
    line = [e for e in logs.events("http_request") if e["status_code"] == 500][0]
    assert line["error_type"] == "RuntimeError" and line["level"] == "ERROR"
    assert "private details" not in json.dumps(logs.lines)

# ---------- 4 and 6. Database errors and health checks ----------

import sqlalchemy.exc
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main import app, get_db
from tests.test_jobs import override_get_db

BROKEN_DB_URL = "postgresql://telemetry_user:hunter2secret@127.0.0.1:1/nodb"


def broken_db():
    # A database that refuses connections, like a stopped Postgres container
    bad_engine = create_engine(BROKEN_DB_URL, connect_args={"connect_timeout": 1})
    db = Session(bind=bad_engine)
    try:
        yield db
    finally:
        db.close()
        bad_engine.dispose()


@pytest.fixture
def database_down():
    app.dependency_overrides[get_db] = broken_db
    yield
    app.dependency_overrides[get_db] = override_get_db


def test_health_live(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_ready(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"]["status"] == "available"
    assert body["checks"]["database"]["latency_ms"] >= 0


def test_database_down_live_vs_ready(client, database_down, logs):
    # The API process is fine...
    assert client.get("/health/live").status_code == 200
    # ...but it can't do real work
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"
    assert ready.json()["checks"]["database"]["status"] == "unavailable"
    # The old endpoint keeps its old behaviour
    assert client.get("/health").status_code == 503

    line = [e for e in logs.events("http_request") if e["path"] == "/health/ready"][0]
    assert line["status_code"] == 503 and line["error_type"] == "OperationalError"


def test_database_down_returns_503_and_logs_it(client, logs):
    headers = auth_headers(client, "outage@example.com")
    app.dependency_overrides[get_db] = broken_db
    try:
        response = client.get("/jobs", headers=headers)
    finally:
        app.dependency_overrides[get_db] = override_get_db

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}

    db_error = logs.events("db_error")[0]
    assert db_error["level"] == "ERROR"
    assert db_error["error_type"] == "OperationalError"
    assert db_error["operation"] == "CONNECT"
    assert db_error["request_id"] == response.headers["X-Request-ID"]
    assert logs.events("db_unavailable")[0]["error_type"] == "OperationalError"

    request = [e for e in logs.events("http_request") if e["path"] == "/jobs"][0]
    assert request["status_code"] == 503 and request["level"] == "ERROR"

    # No hostnames, usernames or passwords from the connection string
    everything = json.dumps(logs.lines)
    for secret in ("telemetry_user", "hunter2secret", "127.0.0.1", "nodb"):
        assert secret not in everything


def test_recovers_when_database_returns(client, database_down):
    assert client.get("/health/ready").status_code == 503
    app.dependency_overrides[get_db] = override_get_db
    assert client.get("/health/ready").status_code == 200


def test_pool_exhaustion_returns_503(client, tmp_path, logs):
    headers = auth_headers(client, "pool@example.com")
    # A pool with room for one connection, already taken
    tiny = create_engine(f"sqlite:///{tmp_path}/pool.db", pool_size=1, max_overflow=0, pool_timeout=0.1)
    held = tiny.connect()

    def exhausted_db():
        db = Session(bind=tiny)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = exhausted_db
    try:
        response = client.get("/jobs", headers=headers)
    finally:
        app.dependency_overrides[get_db] = override_get_db
        held.close()
        tiny.dispose()

    assert response.status_code == 503
    assert len(logs.events("db_pool_exhausted")) == 1
    request = [e for e in logs.events("http_request") if e["path"] == "/jobs"][0]
    assert request["error_type"] == "TimeoutError"


def test_failed_transaction_returns_500_and_logs_class(client, logs, monkeypatch):
    headers = auth_headers(client, "txn@example.com")

    def reject(*args, **kwargs):
        raise sqlalchemy.exc.DataError("INSERT ... private-value", {}, Exception("private detail"))

    monkeypatch.setattr(crud, "create_job_applications", reject)
    response = client.post("/jobs", headers=headers, json={"company": "A", "role": "B", "status": "Applied"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    failed = logs.events("db_transaction_failed")
    assert len(failed) == 1 and failed[0]["error_type"] == "DataError"
    everything = json.dumps(logs.lines)
    assert "private-value" not in everything and "private detail" not in everything


def test_real_constraint_error_is_logged_without_sql(client, logs):
    # A real failed INSERT against the test database: a job for a user who
    # doesn't exist breaks the NOT NULL rule on user_id
    import models
    from tests.test_jobs import TestingSessionLocal

    db = TestingSessionLocal()
    try:
        db.add(models.JobApplication(company="LeakyCo", role="r", status="Applied", user_id=None))
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()

    error = logs.events("db_error")[0]
    assert error["error_type"] == "IntegrityError"
    # Postgres also reports the exact rule that was broken
    assert error["driver_error"] in ("IntegrityError", "NotNullViolation")
    assert error["sqlstate"] in (None, "23502")
    assert error["operation"] == "INSERT"
    assert "LeakyCo" not in json.dumps(logs.lines)

# ---------- 9. Metrics ----------

from prometheus_client import REGISTRY

from database import engine


def sample(name, **labels):
    # Counters keep counting across tests, so tests compare before and after
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_metrics_endpoint_serves_prometheus_text(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    for name in ("http_requests_total", "http_request_duration_seconds_bucket",
                 "http_requests_in_progress", "jobtracker_db_up"):
        assert name in response.text


def test_metrics_not_in_api_docs(client):
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


def test_request_counter_and_latency(client):
    labels = {"method": "GET", "path": "/", "status_code": "200"}
    count_before = sample("http_requests_total", **labels)
    latency_before = sample("http_request_duration_seconds_count", method="GET", path="/")

    client.get("/")
    client.get("/")

    assert sample("http_requests_total", **labels) == count_before + 2
    assert sample("http_request_duration_seconds_count", method="GET", path="/") == latency_before + 2
    assert sample("http_requests_in_progress") == 0


def test_metrics_use_route_templates_not_ids(client):
    headers = auth_headers(client, "metrics-ids@example.com")
    client.get("/jobs/424242", headers=headers)
    client.get("/no-such-page-777")

    text = client.get("/metrics").text
    assert 'path="/jobs/{job_id}",status_code="404"' in text
    assert 'path="<unmatched>"' in text
    assert "424242" not in text and "no-such-page-777" not in text


def test_server_errors_counted_with_exception_class(client, monkeypatch):
    headers = auth_headers(client, "metrics-500@example.com")
    labels = {"method": "GET", "path": "/jobs/{job_id}", "status_code": "500", "error_type": "RuntimeError"}
    before = sample("http_server_errors_total", **labels)

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(crud, "get_job_by_id_for_user", explode)
    client.get("/jobs/1", headers=headers)

    assert sample("http_server_errors_total", **labels) == before + 1


def test_database_outage_shows_in_metrics(client):
    labels = {"method": "GET", "path": "/health/ready", "status_code": "503", "error_type": "OperationalError"}
    errors_before = sample("http_server_errors_total", **labels)
    db_errors_before = sample("jobtracker_db_errors_total", error_type="OperationalError", operation="CONNECT")

    app.dependency_overrides[get_db] = broken_db
    try:
        client.get("/health/ready")
        down = client.get("/metrics").text
    finally:
        app.dependency_overrides[get_db] = override_get_db

    assert "jobtracker_db_up 0.0" in down
    assert sample("http_server_errors_total", **labels) == errors_before + 1
    assert sample("jobtracker_db_errors_total", error_type="OperationalError", operation="CONNECT") >= db_errors_before + 2
    # The connection string never reaches the metrics
    assert "hunter2secret" not in down and "telemetry_user" not in down

    # Recovery
    assert "jobtracker_db_up 1.0" in client.get("/metrics").text


def test_pool_exhaustion_counted(client, tmp_path):
    headers = auth_headers(client, "metrics-pool@example.com")
    before = sample("jobtracker_db_pool_exhausted_total")
    tiny = create_engine(f"sqlite:///{tmp_path}/pool.db", pool_size=1, max_overflow=0, pool_timeout=0.1)
    held = tiny.connect()

    def exhausted_db():
        db = Session(bind=tiny)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = exhausted_db
    try:
        assert client.get("/jobs", headers=headers).status_code == 503
    finally:
        app.dependency_overrides[get_db] = override_get_db
        held.close()
        tiny.dispose()

    assert sample("jobtracker_db_pool_exhausted_total") == before + 1


def test_pool_gauges_on_postgres(client):
    from sqlalchemy.pool import QueuePool

    text = client.get("/metrics").text
    if isinstance(engine.pool, QueuePool):
        for name in ("jobtracker_db_pool_size", "jobtracker_db_pool_checked_out",
                     "jobtracker_db_pool_checked_in", "jobtracker_db_pool_overflow"):
            assert name in text
    else:
        # SQLite's pool has no such numbers, so nothing is exported
        assert "jobtracker_db_pool_size" not in text