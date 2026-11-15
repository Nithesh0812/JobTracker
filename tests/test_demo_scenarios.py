"""Tests for the demo incident scenarios and scripts/demo.py (checklist items 5 and 8).

TEMPORARY / DEMO ONLY: delete this file together with demo_scenarios.py.
"""

import importlib.util
import json
import pathlib
import time

import pytest

import demo_scenarios
from tests.test_jobs import auth_headers, client, create_job, test_user  # noqa: F401
from tests.test_observability import logs, sample  # noqa: F401

TOKEN = "test-demo-token-0123456789"
DEMO = {"X-Demo-Token": TOKEN}

# Load scripts/demo.py as a module (scripts/ isn't a package)
_spec = importlib.util.spec_from_file_location(
    "demo_script", pathlib.Path(__file__).parent.parent / "scripts" / "demo.py")
demo_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_script)


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("DEMO_SCENARIOS_ENABLED", "true")
    monkeypatch.setenv("DEMO_TOKEN", TOKEN)
    demo_scenarios.state.clear_all()
    yield
    demo_scenarios.state.clear_all()


# ---------- Gating ----------

def test_demo_is_off_by_default(client, monkeypatch):
    monkeypatch.delenv("DEMO_SCENARIOS_ENABLED", raising=False)
    monkeypatch.setenv("DEMO_TOKEN", TOKEN)
    assert client.get("/demo/scenarios", headers=DEMO).status_code == 404
    assert client.put("/demo/scenarios/db_outage", headers=DEMO, json={}).status_code == 404


def test_demo_needs_a_long_enough_token(client, monkeypatch):
    monkeypatch.setenv("DEMO_SCENARIOS_ENABLED", "true")
    monkeypatch.setenv("DEMO_TOKEN", "short")
    # A weak token counts as demo mode being off
    assert client.get("/demo/scenarios", headers={"X-Demo-Token": "short"}).status_code == 404


def test_demo_rejects_missing_or_wrong_token(client, demo_on):
    assert client.get("/demo/scenarios").status_code == 401
    assert client.get("/demo/scenarios", headers={"X-Demo-Token": "wrong-token-0123456789"}).status_code == 401
    assert client.get("/demo/scenarios", headers=DEMO).status_code == 200


def test_demo_routes_hidden_from_docs(client, demo_on):
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(path.startswith("/demo") for path in paths)


def test_scenarios_have_no_effect_once_demo_mode_is_off(client, demo_on, monkeypatch):
    headers = auth_headers(client, "gate@example.com")
    client.put("/demo/scenarios/db_outage", headers=DEMO, json={})
    monkeypatch.setenv("DEMO_SCENARIOS_ENABLED", "false")
    assert client.get("/jobs", headers=headers).status_code == 200


# ---------- Scenario: database outage ----------

def test_db_outage_looks_like_a_real_outage(client, demo_on, logs):
    headers = auth_headers(client, "outage-demo@example.com")
    create_job(client, headers)

    response = client.put("/demo/scenarios/db_outage", headers=DEMO, json={"duration_s": 60})
    assert response.status_code == 200 and response.json()["enabled"] is True

    assert client.get("/jobs", headers=headers).status_code == 503
    assert client.get("/health/ready").status_code == 503
    assert client.get("/health/live").status_code == 200  # the API itself is fine
    metrics_text = client.get("/metrics").text
    assert "jobtracker_db_up 0.0" in metrics_text
    assert 'jobtracker_demo_scenario_active{scenario="db_outage"} 1.0' in metrics_text

    db_error = logs.events("db_error")[0]
    assert db_error["error_type"] == "OperationalError"
    assert db_error["operation"] == "SELECT"

    # Switching it off restores everything, and no data was lost
    assert client.delete("/demo/scenarios/db_outage", headers=DEMO).status_code == 200
    jobs = client.get("/jobs", headers=headers)
    assert jobs.status_code == 200 and len(jobs.json()) == 1


# ---------- Scenario: latency ----------

def test_latency_slows_job_reads_only(client, demo_on, logs):
    headers = auth_headers(client, "slow-demo@example.com")
    client.put("/demo/scenarios/latency", headers=DEMO, json={"delay_ms": 300})

    start = time.perf_counter()
    assert client.get("/jobs", headers=headers).status_code == 200
    assert time.perf_counter() - start >= 0.3

    start = time.perf_counter()
    client.get("/health/ready")
    create_job(client, headers)  # a POST, not a read
    assert time.perf_counter() - start < 0.3

    slow = [e for e in logs.events("http_request") if e["path"] == "/jobs" and e["method"] == "GET"][0]
    assert slow["duration_ms"] >= 300


def test_latency_settings_are_validated(client, demo_on):
    assert client.put("/demo/scenarios/latency", headers=DEMO, json={"delay_ms": 60000}).status_code == 422
    assert client.put("/demo/scenarios/latency", headers=DEMO, json={"delay_ms": 10}).status_code == 422
    assert client.put("/demo/scenarios/latency", headers=DEMO, json={"delay_ms": 500, "duration_s": 99999}).status_code == 422


# ---------- Scenario: application exception ----------

def test_exception_scenario_raises_on_job_routes(client, demo_on, logs):
    headers = auth_headers(client, "boom-demo@example.com")
    job = create_job(client, headers).json()
    client.put("/demo/scenarios/exception", headers=DEMO, json={"error_rate": 1.0})

    response = client.get(f"/jobs/{job['id']}", headers=headers)
    assert response.status_code == 500
    assert client.get("/health/ready").status_code == 200  # other routes unaffected

    line = [e for e in logs.events("http_request") if e["status_code"] == 500][0]
    # The real route, not "<unmatched>", so the failing endpoint can be found
    assert line["path"] == "/jobs/{job_id}"
    assert line["error_type"] == "RuntimeError"


def test_exception_rate_is_validated(client, demo_on):
    assert client.put("/demo/scenarios/exception", headers=DEMO, json={"error_rate": 0}).status_code == 422
    assert client.put("/demo/scenarios/exception", headers=DEMO, json={"error_rate": 1.5}).status_code == 422


# ---------- Safety: expiry, reset, audit ----------

def test_scenarios_switch_themselves_off(client, demo_on, monkeypatch, logs):
    headers = auth_headers(client, "expiry@example.com")
    client.put("/demo/scenarios/db_outage", headers=DEMO, json={"duration_s": 10})
    assert client.get("/jobs", headers=headers).status_code == 503

    later = time.time() + 11
    monkeypatch.setattr(demo_scenarios.time, "time", lambda: later)
    assert client.get("/jobs", headers=headers).status_code == 200
    assert logs.events("demo_scenario_expired")[0]["scenario"] == "db_outage"


def test_reset_switches_everything_off(client, demo_on):
    client.put("/demo/scenarios/db_outage", headers=DEMO, json={})
    client.put("/demo/scenarios/latency", headers=DEMO, json={"delay_ms": 100})
    response = client.delete("/demo/scenarios", headers=DEMO)
    assert response.json()["stopped"] == ["db_outage", "latency"]
    status = client.get("/demo/scenarios", headers=DEMO).json()
    assert all(not s["enabled"] for s in status.values())


def test_every_change_is_logged_without_the_token(client, demo_on, logs):
    client.put("/demo/scenarios/latency", headers=DEMO, json={"delay_ms": 200, "duration_s": 30})
    client.delete("/demo/scenarios/latency", headers=DEMO)

    enabled = logs.events("demo_scenario_enabled")[0]
    assert enabled["scenario"] == "latency" and enabled["delay_ms"] == 200
    assert enabled["level"] == "WARNING"
    assert logs.events("demo_scenario_disabled")[0]["was_on"] is True
    assert TOKEN not in json.dumps(logs.lines)


# ---------- scripts/demo.py ----------

def test_seed_is_repeatable(client):
    first = demo_script.seed(client, users=2, jobs_per_user=3)
    second = demo_script.seed(client, users=2, jobs_per_user=3)
    assert first == {"users": 2, "jobs_created": 6}
    assert second == {"users": 2, "jobs_created": 0}  # already seeded


def test_reset_only_touches_demo_accounts(client, demo_on):
    real_user = auth_headers(client, "real-person@example.com")
    create_job(client, real_user, company="Real Job")
    demo_script.seed(client, users=2, jobs_per_user=3)
    client.put("/demo/scenarios/latency", headers=DEMO, json={"delay_ms": 100})

    result = demo_script.reset(client, users=2)

    assert result["scenarios_stopped"] == ["latency"]
    # Deletes the 6 seeded jobs, then reseeds the default 8 per user
    assert result["jobs_deleted"] == 6 and result["jobs_created"] == 16
    real_jobs = client.get("/jobs", headers=real_user).json()
    assert [j["company"] for j in real_jobs] == ["Real Job"]


def test_script_refuses_non_demo_accounts(client):
    with pytest.raises(ValueError):
        demo_script.login(client, "real-person@example.com")


def test_traffic_generates_a_request_mix(client):
    demo_script.seed(client, users=2, jobs_per_user=3)
    result = demo_script.traffic(client, rps=20, duration_s=1, users=2, workers=1, seed_value=1)
    assert result["requests"] >= 10
    assert result["errors_5xx"] == 0
    assert set(result["by_status"]) <= {200}


def test_traffic_counts_failures(client, demo_on):
    demo_script.seed(client, users=1, jobs_per_user=2)
    client.put("/demo/scenarios/exception", headers=DEMO, json={"error_rate": 1.0})
    result = demo_script.traffic(client, rps=20, duration_s=1, users=1, workers=1, seed_value=1)
    # Every /jobs request fails; only the occasional /health/ready succeeds
    assert result["errors_5xx"] == result["requests"] - result["by_status"].get(200, 0)
    assert result["errors_5xx"] > 0
