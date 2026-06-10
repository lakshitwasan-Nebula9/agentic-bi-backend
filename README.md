# Agentic BI Backend

Backend API for the Nebula9.ai Agentic & Autonomous Business Intelligence Platform — a
multi-tenant SaaS that closes the loop from data ingestion to certified KPIs, AI-driven
insights, and autonomous task assignment.

## Tech Stack

- **API**: FastAPI (Python 3.11)
- **Database**: PostgreSQL + pgvector
- **Migrations**: Alembic
- **Message Broker**: Redis Streams
- **Lint/Format**: Ruff, Black
- **Tests**: Pytest
- **CI**: GitHub Actions

## Prerequisites

- Python 3.11+
- Docker & Docker Compose

## Setup

### 1. Environment variables

```bash
cp .env.example .env
```

Update `.env` with your configuration. `DATABASE_URL` should point at the Postgres
instance (see below).

### 2. Start Postgres + Redis

```bash
docker compose up -d db redis
```

This starts Postgres (with the `pgvector` extension) on `localhost:5432` and Redis on
`localhost:6379`.

### 3. Install dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Run database migrations

```bash
alembic upgrade head
```

### 5. Run the API

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`. Interactive docs at
`http://localhost:8000/docs`.

## Running with Docker

To run the full stack (API + Postgres + Redis) in Docker:

```bash
docker compose up --build
```

## Development

### Linting & Formatting

```bash
ruff check .
black .
```

### Tests

```bash
pytest
```

### Migrations

```bash
alembic revision --autogenerate -m "description"   # generate migration from model changes
alembic upgrade head                               # apply all pending migrations
alembic downgrade -1                               # roll back one migration
```

## Project Structure

```
app/
├── core/        # config, database session, settings
├── models/      # SQLAlchemy models
├── schemas/     # Pydantic schemas
├── routers/     # API route handlers
├── services/    # business logic
└── main.py      # FastAPI app entrypoint

alembic/         # database migrations
docs/            # product & architecture docs
tests/           # test suite
```

## API Conventions

- All routes are prefixed with `/api/v1`
- Multi-tenant: every record and request carries a `tenant_id`, enforced via
  Postgres Row-Level Security
- RBAC roles: Executive, Business Manager, Data/BI Analyst, Operations User

See `CLAUDE.md` and `docs/` for full architecture and product documentation.
