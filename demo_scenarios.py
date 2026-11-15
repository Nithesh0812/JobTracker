"""Controlled incident scenarios for demos and for testing TraceLens.

TEMPORARY / DEMO ONLY. Remove this file, scripts/demo.py and the lines marked
"DEMO" in main.py, docker-compose.yml, Caddyfile and .env.example when
JobTracker is no longer used as TraceLens's test service.

Safety:
- Off unless DEMO_SCENARIOS_ENABLED=true AND DEMO_TOKEN is at least 16
  characters. When off, every /demo URL answers 404, as if it didn't exist.
- Every /demo request needs the token in an X-Demo-Token header.
- /demo is hidden from /docs, and Caddy answers 404 to it from the internet,
  so it can only be called from the server itself.
- Every scenario switches itself off after a time limit (10 minutes by
  default, 1 hour at most), so a forgotten fault can't stay on.
- Scenarios never touch stored data. They change how requests behave while
  they're on, and nothing else.

Scenarios:
- db_outage:  every database query fails, as if Postgres were down
- latency:    GET /jobs and GET /jobs/{id} wait delay_ms before answering
- exception:  a share (error_rate) of /jobs requests raise an unhandled error
A traffic spike is generated from outside instead: scripts/demo.py traffic.
"""

import asyncio
import hmac
import logging
import os
import random
import threading
import time
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY
from pydantic import BaseModel, Field
from sqlalchemy import event
from sqlalchemy.engine import Engine

from logging_config import log_event

logger = logging.getLogger("jobtracker.demo")

SCENARIOS = ("db_outage", "latency", "exception")
DEFAULT_DURATION_S = 600
MAX_DURATION_S = 3600
MIN_TOKEN_LENGTH = 16

# Paths the latency and exception scenarios apply to
JOB_PATH_PREFIX = "/jobs"


# ---------- Switches ----------

def demo_enabled() -> bool:
    # Read on every request, so the setting can't be cached in a bad state
    token = os.getenv("DEMO_TOKEN", "")
    return os.getenv("DEMO_SCENARIOS_ENABLED", "false").lower() == "true" and len(token) >= MIN_TOKEN_LENGTH


def require_demo_token(x_demo_token: str = Header(default="")) -> None:
    if not demo_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    expected = os.getenv("DEMO_TOKEN", "")
    # compare_digest takes the same time whatever the input, so the token
    # can't be guessed one character at a time
    if not hmac.compare_digest(x_demo_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid demo token")


# ---------- State ----------

class _State:
    """Which scenarios are on. Kept in memory: a restart clears everything."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active: dict[str, dict] = {}

    def set(self, name: str, settings: dict, duration_s: int) -> dict:
        with self._lock:
            self._active[name] = {**settings, "expires_at": time.time() + duration_s}
            return dict(self._active[name])

    def clear(self, name: str) -> bool:
        with self._lock:
            return self._active.pop(name, None) is not None

    def clear_all(self) -> list[str]:
        with self._lock:
            names = sorted(self._active)
            self._active.clear()
            return names

    def get(self, name: str) -> dict | None:
        with self._lock:
            entry = self._active.get(name)
            if entry and entry["expires_at"] <= time.time():
                del self._active[name]
                expired = True
            else:
                expired = False
        if expired:
            log_event(logger, "demo_scenario_expired", logging.WARNING, scenario=name)
            return None
        return dict(entry) if entry else None

    def snapshot(self) -> dict:
        result = {}
        for name in SCENARIOS:
            entry = self.get(name)
            if entry:
                entry["expires_in_s"] = max(0, round(entry.pop("expires_at") - time.time()))
                result[name] = {"enabled": True, **entry}
            else:
                result[name] = {"enabled": False}
        return result


state = _State()


def is_active(name: str) -> dict | None:
    # Scenarios only ever take effect while demo mode is switched on
    if not demo_enabled():
        return None
    return state.get(name)


# ---------- Effects ----------

class _SimulatedOutage(Exception):
    pass


def _fail_queries_during_outage(cursor, statement, parameters, context, *args):
    """db_outage: make every query fail with the driver's own error class.

    Raised at the moment the query would be sent, so nothing is read or
    written. It happens inside SQLAlchemy's own error handling, so the real
    error handling, db_error logs, metrics and 503 responses all run exactly
    as they would for a real outage.
    """
    if is_active("db_outage"):
        raise context.dialect.loaded_dbapi.OperationalError("database unavailable")


for _hook in ("do_execute", "do_execute_no_params", "do_executemany"):
    event.listen(Engine, _hook, _fail_queries_during_outage)


async def inject_job_faults(request: Request) -> None:
    """latency and exception scenarios, for /jobs routes only.

    Added to the app as a dependency, so it runs after routing: the request
    log then shows the real route ("/jobs/{job_id}"), as a real fault would.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", "")
    if not (path == JOB_PATH_PREFIX or path.startswith(JOB_PATH_PREFIX + "/")):
        return

    latency = is_active("latency")
    if latency and request.method == "GET":
        await asyncio.sleep(latency["delay_ms"] / 1000)

    failure = is_active("exception")
    if failure and random.random() < failure["error_rate"]:
        # Caught and logged by the request middleware like any real bug
        raise RuntimeError("simulated application error")


# ---------- Metrics ----------

class _ScenarioCollector:
    def collect(self):
        gauge = GaugeMetricFamily(
            "jobtracker_demo_scenario_active",
            "1 while a demo incident scenario is switched on",
            labels=["scenario"],
        )
        for name in SCENARIOS:
            gauge.add_metric([name], 1 if is_active(name) else 0)
        yield gauge


_collector_registered = False


def register_metrics() -> None:
    global _collector_registered
    if not _collector_registered:
        REGISTRY.register(_ScenarioCollector())
        _collector_registered = True


# ---------- API ----------

class Duration(BaseModel):
    duration_s: int = Field(default=DEFAULT_DURATION_S, ge=10, le=MAX_DURATION_S)


class LatencySettings(Duration):
    delay_ms: int = Field(ge=50, le=10_000)


class ExceptionSettings(Duration):
    error_rate: float = Field(gt=0, le=1)


router = APIRouter(
    prefix="/demo",
    include_in_schema=False,
    dependencies=[Depends(require_demo_token)],
)


def _switched_on(name: str, settings: dict, duration_s: int) -> dict:
    entry = state.set(name, settings, duration_s)
    log_event(logger, "demo_scenario_enabled", logging.WARNING,
              scenario=name, duration_s=duration_s, **settings)
    return {"scenario": name, "enabled": True, **settings,
            "expires_in_s": round(entry["expires_at"] - time.time())}


@router.get("/scenarios")
def list_scenarios():
    return state.snapshot()


@router.put("/scenarios/db_outage")
def start_db_outage(body: Duration = Duration()):
    return _switched_on("db_outage", {}, body.duration_s)


@router.put("/scenarios/latency")
def start_latency(body: LatencySettings):
    return _switched_on("latency", {"delay_ms": body.delay_ms}, body.duration_s)


@router.put("/scenarios/exception")
def start_exception(body: ExceptionSettings):
    return _switched_on("exception", {"error_rate": body.error_rate}, body.duration_s)


@router.delete("/scenarios/{name}")
def stop_scenario(name: Literal["db_outage", "latency", "exception"]):
    was_on = state.clear(name)
    log_event(logger, "demo_scenario_disabled", logging.WARNING, scenario=name, was_on=was_on)
    return {"scenario": name, "enabled": False}


@router.delete("/scenarios")
def stop_all():
    stopped = state.clear_all()
    log_event(logger, "demo_scenarios_reset", logging.WARNING, stopped=stopped)
    return {"stopped": stopped}
