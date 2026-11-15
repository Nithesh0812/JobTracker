"""Demo tooling for TraceLens: seed data, generate traffic, trigger incidents, reset.

TEMPORARY / DEMO ONLY, like demo_scenarios.py.

Run it on the server, inside the API container, where it can reach the API and
already has DEMO_TOKEN:

    docker compose exec api python scripts/demo.py seed
    docker compose exec api python scripts/demo.py traffic --rps 2 --duration 120
    docker compose exec api python scripts/demo.py scenario on latency --delay-ms 1500
    docker compose exec api python scripts/demo.py scenario status
    docker compose exec api python scripts/demo.py reset

Commands:
    seed      Create the demo users and their jobs (safe to run again)
    traffic   Send a realistic mix of requests as the demo users. Low --rps
              gives a healthy baseline; high --rps is a traffic spike
    scenario  on/off/status for db_outage, latency and exception
    reset     Switch every scenario off, then delete and recreate the demo
              users' jobs. Never touches any other user's data

Only accounts with emails ending in @demo.example.com are ever used.
"""

import argparse
import os
import random
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx

DEMO_EMAIL_DOMAIN = "demo.example.com"
DEFAULT_BASE_URL = os.getenv("DEMO_BASE_URL", "http://127.0.0.1:8000")
DEMO_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "demo-password-2026")

COMPANIES = ["Northwind", "Contoso", "Fabrikam", "Initech", "Globex", "Umbrella",
             "Hooli", "Stark Industries", "Wayne Enterprises", "Acme"]
ROLES = ["Backend Engineer", "Software Engineer", "Platform Engineer",
         "Site Reliability Engineer", "Data Engineer", "ML Engineer"]
STATUSES = ["Applied", "Interview", "Offer Extended", "Rejected"]


def demo_email(n: int) -> str:
    return f"demo{n}@{DEMO_EMAIL_DOMAIN}"


def is_demo_email(email: str) -> bool:
    return email.endswith("@" + DEMO_EMAIL_DOMAIN)


# ---------- Users and data ----------

def login(client: httpx.Client, email: str) -> dict:
    """Log in a demo user, registering it first if needed. Returns auth headers."""
    if not is_demo_email(email):
        raise ValueError(f"refusing to use a non-demo account: {email}")
    response = client.post("/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    if response.status_code == 401:
        registered = client.post("/auth/register", json={
            "full_name": f"Demo User {email.split('@')[0]}",
            "email": email,
            "password": DEMO_PASSWORD,
        })
        registered.raise_for_status()
        response = client.post("/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def list_all_jobs(client: httpx.Client, headers: dict) -> list[dict]:
    jobs, skip = [], 0
    while True:
        page = client.get("/jobs", headers=headers, params={"skip": skip, "limit": 20})
        page.raise_for_status()
        batch = page.json()
        jobs.extend(batch)
        if len(batch) < 20:
            return jobs
        skip += 20


def seed(client: httpx.Client, users: int = 3, jobs_per_user: int = 8, seed_value: int = 42) -> dict:
    """Give each demo user jobs_per_user jobs. Users that already have jobs are left as they are."""
    rng = random.Random(seed_value)  # same data every time
    created = 0
    for n in range(1, users + 1):
        headers = login(client, demo_email(n))
        if list_all_jobs(client, headers):
            continue
        for _ in range(jobs_per_user):
            response = client.post("/jobs", headers=headers, json={
                "company": rng.choice(COMPANIES),
                "role": rng.choice(ROLES),
                "status": rng.choice(STATUSES),
                "job_link": "https://example.com/careers",
                "notes": "Demo data",
            })
            response.raise_for_status()
            created += 1
    return {"users": users, "jobs_created": created}


def delete_demo_jobs(client: httpx.Client, users: int = 3) -> int:
    deleted = 0
    for n in range(1, users + 1):
        headers = login(client, demo_email(n))
        for job in list_all_jobs(client, headers):
            response = client.delete(f"/jobs/{job['id']}", headers=headers)
            if response.status_code == 204:
                deleted += 1
    return deleted


# ---------- Scenarios ----------

def demo_headers() -> dict:
    token = os.getenv("DEMO_TOKEN", "")
    if not token:
        sys.exit("DEMO_TOKEN is not set. Set it in .env (and DEMO_SCENARIOS_ENABLED=true).")
    return {"X-Demo-Token": token}


def scenario_request(client: httpx.Client, method: str, path: str, **kwargs) -> dict:
    response = client.request(method, f"/demo{path}", headers=demo_headers(), **kwargs)
    if response.status_code == 404:
        sys.exit("Demo mode is off. Set DEMO_SCENARIOS_ENABLED=true and a DEMO_TOKEN of 16+ "
                 "characters in .env, then: docker compose up -d")
    if response.status_code == 401:
        sys.exit("DEMO_TOKEN doesn't match the API's.")
    response.raise_for_status()
    return response.json()


def scenario_on(client: httpx.Client, name: str, duration_s: int,
                delay_ms: int | None = None, error_rate: float | None = None) -> dict:
    body = {"duration_s": duration_s}
    if name == "latency":
        body["delay_ms"] = delay_ms or 1500
    if name == "exception":
        body["error_rate"] = error_rate or 0.3
    return scenario_request(client, "PUT", f"/scenarios/{name}", json=body)


def reset(client: httpx.Client, users: int = 3) -> dict:
    stopped = scenario_request(client, "DELETE", "/scenarios")["stopped"]
    deleted = delete_demo_jobs(client, users)
    seeded = seed(client, users)
    return {"scenarios_stopped": stopped, "jobs_deleted": deleted, **seeded}


# ---------- Traffic ----------

def one_request(client: httpx.Client, headers: dict, rng: random.Random) -> tuple[str, int, float]:
    """A realistic mix: mostly reads, some updates, a few health checks."""
    roll = rng.random()
    if roll < 0.55:
        name = "GET /jobs"
    elif roll < 0.80:
        name = "GET /jobs/{job_id}"
    elif roll < 0.95:
        name = "PATCH /jobs/{job_id}"
    else:
        name = "GET /health/ready"

    start = time.perf_counter()
    try:
        if name == "GET /jobs":
            response = client.get("/jobs", headers=headers, params={"limit": rng.choice([5, 10, 20])})
        elif name == "GET /health/ready":
            response = client.get("/health/ready")
        else:
            jobs = client.get("/jobs", headers=headers, params={"limit": 20}).json()
            job_id = rng.choice(jobs)["id"] if isinstance(jobs, list) and jobs else 1
            if name == "GET /jobs/{job_id}":
                response = client.get(f"/jobs/{job_id}", headers=headers)
            else:
                response = client.patch(f"/jobs/{job_id}", headers=headers,
                                        json={"status": rng.choice(STATUSES)})
        status = response.status_code
    except httpx.HTTPError:
        status = 0  # no response at all (connection refused, timeout)
    return name, status, time.perf_counter() - start


def traffic(client: httpx.Client, rps: float, duration_s: float, users: int = 3,
            workers: int = 8, seed_value: int | None = None) -> dict:
    rng = random.Random(seed_value)
    try:
        sessions = [login(client, demo_email(n)) for n in range(1, users + 1)]
    except httpx.HTTPError as exc:
        sys.exit(f"Couldn't log in the demo users ({exc}). Is the API up? If a db_outage "
                 "scenario is on, start the traffic first and switch the outage on while it runs.")
    results = []
    interval = 1 / rps
    deadline = time.monotonic() + duration_s
    next_at = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        while time.monotonic() < deadline:
            futures.append(pool.submit(one_request, client, rng.choice(sessions),
                                       random.Random(rng.random())))
            next_at += interval
            time.sleep(max(0, next_at - time.monotonic()))
        results = [f.result() for f in futures]

    latencies = sorted(r[2] for r in results)
    statuses = Counter(r[1] for r in results)
    return {
        "requests": len(results),
        "by_status": dict(sorted(statuses.items())),
        "errors_5xx": sum(c for s, c in statuses.items() if s >= 500 or s == 0),
        "p50_ms": round(statistics.median(latencies) * 1000, 1) if latencies else None,
        "p95_ms": round(latencies[int(len(latencies) * 0.95) - 1] * 1000, 1) if latencies else None,
    }


# ---------- Command line ----------

def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--users", type=int, default=3, help="number of demo users (default 3)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="create demo users and jobs")
    sub.add_parser("reset", help="switch scenarios off and restore the demo data")

    t = sub.add_parser("traffic", help="send requests as the demo users")
    t.add_argument("--rps", type=float, default=2, help="requests per second (default 2)")
    t.add_argument("--duration", type=float, default=60, help="seconds (default 60)")
    t.add_argument("--workers", type=int, default=8, help="requests in flight at once (default 8)")

    s = sub.add_parser("scenario", help="switch an incident scenario on or off")
    s.add_argument("action", choices=["on", "off", "status"])
    s.add_argument("name", nargs="?", choices=["db_outage", "latency", "exception"])
    s.add_argument("--duration", type=int, default=600, help="seconds before it switches off (default 600)")
    s.add_argument("--delay-ms", type=int, help="latency: delay per request (default 1500)")
    s.add_argument("--error-rate", type=float, help="exception: share of requests that fail, 0-1 (default 0.3)")

    args = parser.parse_args(argv)
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        if args.command == "seed":
            result = seed(client, args.users)
        elif args.command == "reset":
            result = reset(client, args.users)
        elif args.command == "traffic":
            result = traffic(client, args.rps, args.duration, args.users, args.workers)
        elif args.action == "status":
            result = scenario_request(client, "GET", "/scenarios")
        elif not args.name:
            parser.error("say which scenario: db_outage, latency or exception")
        elif args.action == "on":
            result = scenario_on(client, args.name, args.duration, args.delay_ms, args.error_rate)
        else:
            result = scenario_request(client, "DELETE", f"/scenarios/{args.name}")
    print(result)


if __name__ == "__main__":
    main()
