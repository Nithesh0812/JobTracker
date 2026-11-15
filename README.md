# Job Tracker API

![CI](https://github.com/Nithesh0812/JobTracker/actions/workflows/ci.yml/badge.svg)

A REST API for tracking job applications, with JWT authentication and per-user data isolation. Built with FastAPI, SQLAlchemy, and Alembic, and runs on PostgreSQL in Docker.

## Live demo

Interactive API docs: **https://54-209-43-23.sslip.io/docs**

To try it:

1. Open `POST /auth/register`, click **Try it out**, enter an email and a password (8 to 128 characters), and click **Execute**.
2. Open `POST /auth/login` and log in. Copy the `access_token` from the response.
3. Click **Authorize** at the top of the page and paste the token.
4. Create, list, filter, update, and delete job applications. You only see your own jobs.

Health checks: https://54-209-43-23.sslip.io/health/live and https://54-209-43-23.sslip.io/health/ready

The demo is hosted on a small AWS instance and may be offline at times. Please use a throwaway email and password.

## Features

- Register and log in with JWT bearer tokens; passwords are hashed with Argon2 (via `pwdlib`)
- Create, read, update, and delete job applications
- Filter by status, company, and role; sort and paginate results
- Every query is scoped to the authenticated user, so users can never see or change each other's data
- Input validation: email format, password length (8 to 128 characters), and a fixed set of job statuses
- Database migrations managed with Alembic
- Structured JSON logs with a request ID on every line, returned to the client in an `X-Request-ID` header
- Prometheus metrics for request rates, latency, errors and the database connection pool
- Separate liveness and readiness checks, and a 503 (not a 500) when the database is unavailable
- Dockerized API and PostgreSQL with a healthcheck, so the API only starts once the database is ready
- Served over HTTPS in production through a Caddy reverse proxy with automatic Let's Encrypt certificates
- Automated test suite with pytest, including cross-user authorization tests, run on every push by GitHub Actions against PostgreSQL and SQLite

## Tech stack

Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Pydantic, Docker, Docker Compose, Caddy, Prometheus, pytest, GitHub Actions, AWS EC2

## Run with Docker (recommended)

Requires Git and Docker Desktop.

```bash
git clone https://github.com/Nithesh0812/JobTracker.git
cd JobTracker
cp .env.example .env        # Windows: copy .env.example .env
```

Edit `.env` and replace the placeholder values. Generate a secret key with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Use letters and digits for `POSTGRES_PASSWORD`. Special characters such as `@` break the database URL.

`DOMAIN` and Caddy are only used for the HTTPS deployment. Locally you can leave `DOMAIN` as it is, and the API is served on http://localhost:8000.

Start the API and PostgreSQL, then create the tables:

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
```

Open http://localhost:8000/docs for the interactive API documentation. To call protected routes there, log in with `POST /auth/login`, copy the `access_token`, click **Authorize**, and paste it.

Useful commands:

```bash
docker compose ps            # service status
docker compose logs api      # API logs (JSON, one event per line)
docker compose stop          # stop, keep data
docker compose down -v       # stop and delete the database
```

After changing code, run `docker compose up -d --build` again, since the container holds a copy of your files.

## Run without Docker (SQLite)

Requires Python 3.11 or newer.

```bash
git clone https://github.com/Nithesh0812/JobTracker.git
cd JobTracker

python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
```

Create a `.env` file in the project root with a secret key for signing tokens:

```
SECRET_KEY=<paste a long random string>
```

Apply the database migrations and start the server:

```bash
alembic upgrade head
uvicorn main:app --reload
```

By default the app uses a local SQLite file (`jobtracker.db`). To use a different database, set the `DATABASE_URL` environment variable.

## Observability

The API is built to be investigated when something goes wrong, by a person or by a tool.

**Logs.** Every log line is a single JSON object with a timestamp, level, event name and the request ID:

```json
{"timestamp": "2026-11-12T18:40:59.585Z", "service": "jobtracker-api", "level": "WARNING", "logger": "jobtracker.access", "request_id": "req-f6be1057130d4f36", "event": "http_request", "method": "GET", "path": "/jobs/{job_id}", "status_code": 404, "duration_ms": 5.45}
```

- Every request gets an ID, returned in the `X-Request-ID` response header. Send your own `X-Request-ID` and the API uses it, so you can follow one request through every log line it produced.
- Paths are logged as route templates (`/jobs/{job_id}`), never with real IDs or query strings.
- Logs never contain passwords, tokens, email addresses, SQL, or text users typed (company names, notes, search terms). Errors are logged by exception class only. Tests check this.
- In Docker, logs go to `docker compose logs api` and to `./logs/app.log` on the host, rotated at 10 MB with 5 old files kept.

Main events: `http_request`, `auth_login_successful`, `auth_login_failed`, `auth_token_rejected`, `user_registered`, `job_application_created`, `job_application_updated`, `job_application_deleted`, `db_error`, `db_unavailable`, `db_pool_exhausted` and `db_transaction_failed`.

**Health checks.**

| Endpoint | Checks | Use it to ask |
| --- | --- | --- |
| `GET /health/live` | Only that the API process answers | Is the API running? Docker's healthcheck uses this |
| `GET /health/ready` | The database too, with its response time | Can the API do real work? |
| `GET /health` | Same as `/health/ready` | Kept for backward compatibility |

If the database goes down, `/health/live` stays 200 while `/health/ready` and the job endpoints return 503 within a few seconds, so an unresponsive API and a database failure look different.

**Metrics.** `GET /metrics` serves Prometheus metrics: `http_requests_total`, `http_request_duration_seconds`, `http_requests_in_progress`, `http_server_errors_total`, `jobtracker_db_up`, `jobtracker_db_errors_total`, `jobtracker_db_pool_exhausted_total` and, on PostgreSQL, the connection pool gauges (`jobtracker_db_pool_size`, `_checked_out`, `_checked_in` and `_overflow`). It's for internal use: Caddy answers 404 to it from the internet, and it isn't listed in `/docs`.

To keep metrics history, start Prometheus with the `telemetry` profile:

```bash
docker compose --profile telemetry up -d
```

It scrapes the API every 15 seconds, keeps 7 days of data, and is reachable only from the machine itself at http://localhost:9090.

**Reading logs and metrics from a deployed server.** Nothing besides the API is exposed to the internet. Use an SSH tunnel:

```bash
ssh -i key.pem -L 9090:localhost:9090 -L 8000:localhost:8000 ubuntu@<server>
```

While it's open, Prometheus is at http://localhost:9090 and the API's `/metrics` at http://localhost:8000/metrics on your own machine. The log file is `~/JobTracker/logs/app.log` on the server.

## Demo incident scenarios (temporary)

JobTracker doubles as a test service for TraceLens, an incident investigation tool. For that it can simulate incidents on demand. This is **off by default** and is temporary: it lives in `demo_scenarios.py` and `scripts/demo.py`, and every other line it needs is marked `DEMO`.

| Scenario | What happens while it's on |
| --- | --- |
| `db_outage` | Every database query fails, as if PostgreSQL were down: 503s, `/health/ready` fails, `jobtracker_db_up` drops to 0. `/health/live` stays up |
| `latency` | `GET /jobs` and `GET /jobs/{job_id}` wait an extra `delay_ms` (50 to 10,000) |
| `exception` | A share (`error_rate`, 0 to 1) of `/jobs` requests fail with an unhandled error and return 500 |
| Traffic spike | Not a switch: `scripts/demo.py traffic` with a high `--rps` |

Safeguards:

- Nothing happens unless `DEMO_SCENARIOS_ENABLED=true` **and** `DEMO_TOKEN` is at least 16 characters. Otherwise every `/demo` URL returns 404.
- Every `/demo` request needs the token in an `X-Demo-Token` header. `/demo` isn't listed in `/docs`, and Caddy answers 404 to it from the internet, so it can only be used from the server itself.
- Every scenario switches itself off after `--duration` seconds (10 minutes by default, 1 hour at most). A restart clears them all.
- Scenarios never change stored data. `scripts/demo.py` only ever uses accounts ending in `@demo.example.com`.
- Every change is logged as a `demo_scenario_enabled`, `demo_scenario_disabled`, `demo_scenario_expired` or `demo_scenarios_reset` event, and shown in the `jobtracker_demo_scenario_active` metric.

To run a demo on the server, set `DEMO_SCENARIOS_ENABLED=true` and a `DEMO_TOKEN` in `.env`, then:

```bash
docker compose up -d                                            # apply the .env change
docker compose exec api python scripts/demo.py seed             # demo users and jobs
docker compose exec api python scripts/demo.py traffic --rps 2 --duration 300   # healthy baseline
docker compose exec api python scripts/demo.py scenario on latency --delay-ms 1500
docker compose exec api python scripts/demo.py scenario status
docker compose exec api python scripts/demo.py reset            # all scenarios off, demo data restored
```

For `db_outage`, start the traffic first (in a second terminal) and switch the outage on while it runs, since the demo users can't log in during an outage. Set `DEMO_SCENARIOS_ENABLED=false` again afterwards.

## Running the tests

```bash
pytest -q
```

By default the tests use an in-memory SQLite database and never touch your real data. To run them against PostgreSQL, set `TEST_DATABASE_URL` to a throwaway database. Its tables are dropped and recreated for every test, so never point it at real data:

```bash
TEST_DATABASE_URL=postgresql://user:password@localhost:5432/jobtracker_test pytest -q
```

The tests cover registration and login, input validation, job CRUD, filtering, sorting, pagination defaults, and authorization (including a test that one user cannot read, edit, or delete another user's job, and that a token for a deleted user is rejected). `tests/test_observability.py` covers the logging, request IDs, metrics and health checks, including a simulated database outage, an exhausted connection pool, recovery afterwards, and checks that no secrets or user data reach the logs or metrics. `tests/test_demo_scenarios.py` covers the demo scenarios and their safeguards.

On every push, GitHub Actions runs the tests against PostgreSQL and then SQLite, applies all migrations to a fresh PostgreSQL database, checks that the models and migrations agree (`alembic check`), and validates `docker-compose.yml` with every profile.

## Deployment

The live demo runs on an AWS EC2 instance using the same Docker Compose setup described above, plus a Caddy reverse proxy:

- Caddy, the API and PostgreSQL run as three containers, plus Prometheus when the `telemetry` profile is on. The database data and Caddy's certificates live in named Docker volumes, so they survive container recreation.
- Caddy serves HTTPS on ports 80 and 443 with automatic Let's Encrypt certificates. The API port is bound to localhost and only reachable through Caddy. PostgreSQL is reachable only from inside the Docker network.
- All services use `restart: unless-stopped`, so they come back after a crash or a server reboot. The API has a Docker healthcheck on `/health/live`, and Caddy waits for it before starting.
- Each container has memory and CPU limits, so one runaway service can't take down the server. The API and database limits can be raised in `.env` (see `.env.example`).
- Docker's own logs are rotated (3 files of 10 MB per container), so logs can't fill the disk.
- Secrets (`SECRET_KEY` and the database credentials) are read from a `.env` file on the server and are not committed to the repository.
- An Elastic IP keeps the address stable across instance restarts.

To deploy or update, set `DOMAIN` and `COMPOSE_PROFILES=https` in the server's `.env` (or `COMPOSE_PROFILES=https,telemetry` to keep metrics history), then run:

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
```

The EC2 security group allows inbound ports 80 and 443; port 8000 is not exposed.