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

Health check: https://54-209-43-23.sslip.io/health

The demo is hosted on a small AWS instance and may be offline at times. Please use a throwaway email and password.

## Features

- Register and log in with JWT bearer tokens; passwords are hashed with Argon2 (via `pwdlib`)
- Create, read, update, and delete job applications
- Filter by status, company, and role; sort and paginate results
- Every query is scoped to the authenticated user, so users can never see or change each other's data
- Input validation: email format, password length (8 to 128 characters), and a fixed set of job statuses
- Database migrations managed with Alembic
- `/health` endpoint that checks the database connection
- Dockerized API and PostgreSQL with a healthcheck, so the API only starts once the database is ready
- Served over HTTPS in production through a Caddy reverse proxy with automatic Let's Encrypt certificates
- Automated test suite with pytest, including cross-user authorization tests, run on every push by GitHub Actions against PostgreSQL and SQLite

## Tech stack

Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Pydantic, Docker, Docker Compose, Caddy, pytest, GitHub Actions, AWS EC2

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
docker compose logs api      # API logs
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

## Running the tests

```bash
pytest -q
```

By default the tests use an in-memory SQLite database and never touch your real data. To run them against PostgreSQL, set `TEST_DATABASE_URL` to a throwaway database. Its tables are dropped and recreated for every test, so never point it at real data:

```bash
TEST_DATABASE_URL=postgresql://user:password@localhost:5432/jobtracker_test pytest -q
```

The tests cover registration and login, input validation, job CRUD, filtering, sorting, pagination defaults, the health check, and authorization (including a test that one user cannot read, edit, or delete another user's job, and that a token for a deleted user is rejected).

On every push, GitHub Actions runs the tests against PostgreSQL and then SQLite, applies all migrations to a fresh PostgreSQL database, and checks that the models and migrations agree (`alembic check`).

## Deployment

The live demo runs on an AWS EC2 instance using the same Docker Compose setup described above, plus a Caddy reverse proxy:

- Caddy, the API and PostgreSQL run as three containers. The database data and Caddy's certificates live in named Docker volumes, so they survive container recreation.
- Caddy serves HTTPS on ports 80 and 443 with automatic Let's Encrypt certificates. The API port is bound to localhost and only reachable through Caddy. PostgreSQL is reachable only from inside the Docker network.
- All three services use `restart: unless-stopped`, so they come back after a crash or a server reboot.
- Secrets (`SECRET_KEY` and the database credentials) are read from a `.env` file on the server and are not committed to the repository.
- An Elastic IP keeps the address stable across instance restarts.

To deploy or update, set `DOMAIN` and `COMPOSE_PROFILES=https` in the server's `.env`, then run:

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
```

The EC2 security group allows inbound ports 80 and 443; port 8000 is not exposed.