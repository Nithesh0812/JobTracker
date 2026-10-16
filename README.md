# Job Tracker API

![CI](https://github.com/Nithesh0812/JobTracker/actions/workflows/ci.yml/badge.svg)

A REST API for tracking job applications, with JWT authentication and per-user data isolation. Built with FastAPI, SQLAlchemy, and Alembic, and runs on PostgreSQL in Docker.

## Live demo

Interactive API docs: **http://34.195.14.161:8000/docs**

To try it:

1. Open `POST /auth/register`, click **Try it out**, enter an email and a password (8 to 128 characters), and click **Execute**.
2. Open `POST /auth/login` and log in. Copy the `access_token` from the response.
3. Click **Authorize** at the top of the page and paste the token.
4. Create, list, filter, update, and delete job applications. You only see your own jobs.

The demo runs over plain HTTP, so use a throwaway email and password, not one you use elsewhere. It is hosted on a small AWS instance and may be offline at times.

Health check: http://34.195.14.161:8000/health

## Features

- Register and log in with JWT bearer tokens; passwords are hashed with Argon2 (via `pwdlib`)
- Create, read, update, and delete job applications
- Filter by status, company, and role; sort and paginate results
- Every query is scoped to the authenticated user, so users can never see or change each other's data
- Input validation: email format, password length (8 to 128 characters), and a fixed set of job statuses
- Database migrations managed with Alembic
- `/health` endpoint that checks the database connection
- Dockerized API and PostgreSQL with a healthcheck, so the API only starts once the database is ready
- Automated test suite with pytest, including cross-user authorization tests, run on every push by GitHub Actions against a real PostgreSQL service

## Tech stack

Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Docker, Docker Compose, Pydantic, pytest, GitHub Actions, AWS EC2

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

The tests run against a separate in-memory database and never touch your real data. They cover registration and login, input validation, job CRUD, filtering, sorting, pagination defaults, the health check, and authorization (including a test that one user cannot read, edit, or delete another user's job, and that a token for a deleted user is rejected).

GitHub Actions runs the tests on every push, then applies all migrations to a fresh PostgreSQL database and checks that the models and migrations agree (`alembic check`).

## Deployment

The live demo runs on an AWS EC2 instance using the same Docker Compose setup described above:

- The API and PostgreSQL run as two containers; the database data lives in a named Docker volume, so it survives container recreation.
- Only the API port (8000) is published. PostgreSQL is reachable only from inside the Docker network.
- Both services use `restart: unless-stopped`, so they come back after a crash or a server reboot.
- Secrets (`SECRET_KEY` and the database credentials) are read from a `.env` file on the server and are not committed to the repository.
- An Elastic IP keeps the address stable across instance restarts.

