# Job Tracker API

A REST API for tracking job applications, with JWT authentication and per-user data isolation. Built with FastAPI, SQLAlchemy, and Alembic.

## Features

- Register and log in with JWT bearer tokens; passwords are hashed with Argon2 (via `pwdlib`)
- Create, read, update, and delete job applications
- Filter by status, company, and role; sort and paginate results
- Every query is scoped to the authenticated user, so users can never see or change each other's data
- Input validation: email format, password length (8 to 128 characters), and a fixed set of job statuses
- Database migrations managed with Alembic
- Automated test suite with pytest, including cross-user authorization tests

## Tech stack

Python, FastAPI, SQLAlchemy, Alembic, SQLite, Pydantic, pytest

## Setup

Requires Python 3.11 or newer.

```bash
git clone https://github.com/Nithesh0812/JobTracker.git
cd JobTracker

python -m venv venv
# Windows (PowerShell):  venv\Scripts\activate
# macOS / Linux / Git Bash:  source venv/bin/activate

pip install -r requirements.txt
```

Create a `.env` file in the project root with a secret key for signing tokens:

```
SECRET_KEY=<paste a long random string>
```

Generate one with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Apply the database migrations and start the server:

```bash
alembic upgrade head
uvicorn main:app --reload
```

Open http://127.0.0.1:8000/docs for the interactive API documentation. To call protected routes there, log in with `POST /auth/login`, copy the `access_token`, click **Authorize**, and paste it.

By default the app uses a local SQLite file (`jobtracker.db`). To use a different database, set the `DATABASE_URL` environment variable.

## Running the tests

```bash
pytest -q
```

The tests run against a separate in-memory database and never touch your real data. They cover registration and login, input validation, job CRUD, filtering, sorting, pagination defaults, and authorization (including a test that one user cannot read, edit, or delete another user's job, and that a token for a deleted user is rejected).

## API overview

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/` | Health message | No |
| POST | `/auth/register` | Create an account | No |
| POST | `/auth/login` | Log in and receive a token | No |
| GET | `/auth/me` | Current user's profile | Yes |
| POST | `/jobs` | Create a job application | Yes |
| GET | `/jobs` | List your applications | Yes |
| GET | `/jobs/{job_id}` | Get one application | Yes |
| PATCH | `/jobs/{job_id}` | Update an application | Yes |
| DELETE | `/jobs/{job_id}` | Delete an application | Yes |

`GET /jobs` query parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `status` | `Applied`, `Interview`, `Offer Extended`, or `Rejected` | none |
| `company`, `role` | Case-insensitive partial match | none |
| `sort_by` | `id`, `company`, `role`, or `status` | `id` |
| `order` | `asc` or `desc` | `asc` |
| `skip` | Number of results to skip | `0` |
| `limit` | Page size, 1 to 20 | `10` |

## Design decisions

- **404 instead of 403 for other users' jobs.** Requesting a job that belongs to someone else returns the same 404 as a job that does not exist, so job ids cannot be probed.
- **Allow-listed sorting.** `sort_by` is checked against a fixed list of columns, so clients cannot sort by arbitrary fields.
- **Deleted users lose access immediately.** A still-valid token for a deleted account returns 401.
- **Separate test database.** Tests override the database dependency with an in-memory SQLite database, so each test starts from a clean state.

## Roadmap

Planned, not yet built:

- Status history for each application
- PostgreSQL, Docker, and CI
- Deployment to AWS
- LLM-based extraction of job details from pasted postings
- Background processing and caching
- Stats endpoint (stage conversion and time in stage)
