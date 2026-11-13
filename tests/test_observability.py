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