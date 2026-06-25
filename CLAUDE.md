# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Product Overview

Agentic & Autonomous Business Intelligence Platform (Nebula9.ai / EvoPort). Closes the loop from data ingestion → certified KPIs → AI insight detection → autonomous task assignment. Multi-tenant SaaS, no third-party BI tool dependency. Two developers: **Lakshit** (backend/infra) and **Aanchal** (frontend + GenAI/LLM tasks).

## Development Commands

### Local (venv)
```bash
source venv/bin/activate
uvicorn app.main:app --reload          # dev server on :8000
```

### Docker
```bash
docker compose up --build              # start API + sample-data Postgres + Redis
docker compose up -d db                # start only the local sample-data Postgres
```

## Databases

**Supabase is the only database.** All project data and metadata — connectors, datasets, KPIs,
snapshots, insights, explanations, dashboards, users, etc. — live in Supabase. `.env` `DATABASE_URL`
points at Supabase; the running API, the migrations, **and the test suite** all target it.

The only other database is the **local docker Postgres (`db` service, `agentic_bi`)** — a throwaway
*sample data source* used only to exercise connector functionality (e.g. the `orders` /
`support_tickets` demo tables). It is **not** the app DB and is slated for removal. Never point the
app or store project data here.

**Tests run against Supabase** (`DATABASE_URL` from `.env`). There is no separate test database, so the
suite operates on real project data — every test must create its own rows with unique identifiers and
clean them up in teardown (see `tests/test_explanation_endpoint.py` for the pattern). Avoid assertions
on global row counts or unscoped deletes.

**CI is the exception:** `.github/workflows/ci.yml` runs against a fresh, ephemeral Postgres service
(not Supabase), so it can `alembic upgrade head` on a clean DB and run the suite in isolation — that's
the one place migrations get validated. (CI works only while a single branch's lineage is checked out;
see the merge caveat below.)

### Alembic Migrations
```bash
alembic revision --autogenerate -m "description"   # generate migration from model changes
alembic upgrade head                               # apply to Supabase (DATABASE_URL from .env)
alembic downgrade -1                               # roll back one migration
```
The `alembic.ini` hardcodes a fallback DB URL, but `alembic/env.py` overrides it with
`settings.DATABASE_URL` from `.env` — so migrations target Supabase by default.

**Multi-dev caveat:** Lakshit's and Aanchal's branches keep separate Alembic lineages that both get
applied to the shared Supabase DB, so Supabase's `alembic_version` currently sits on the other branch's
head and `alembic upgrade head` reports an unknown revision (`Can't locate revision …`). Because of
this, **don't run `alembic upgrade head` against Supabase as a routine step** — the schema is already
applied. Do **not** `alembic stamp` Supabase to your own head either (it erases the other lineage's
record). Reconcile with `alembic merge heads` when branches integrate into `master`; until then, a new
table can be applied to Supabase with the migration's DDL directly.

## Pre-Commit Checklist

Run all of these before every commit. Use `/ship` to automate the full sequence.

Tests run against Supabase (`DATABASE_URL` from `.env`) — there is no separate test DB and no
`alembic upgrade head` step (see the multi-dev caveat above; the Supabase schema is already applied).

```bash
ruff check . --fix && black .          # lint + format (auto-fix)
ruff check . && black --check .        # verify clean
docker compose up -d db redis          # sample-data source + Redis event bus the tests need
python -m pytest tests/ -v --tb=short  # DATABASE_URL from .env → Supabase
docker build -t agentic-bi-backend:ci .
```

Auto-generated files (alembic migrations, etc.) are **not** exempt from ruff/black.

**Git commits:** always run `git add` and `git commit` as **separate Bash calls** — never chain them with `&&`. The pre-commit hook (`if: "Bash(git commit*)"`) only fires on standalone `git commit` commands and will be skipped if add and commit are chained.

## Architecture

### Request flow
```
HTTP → app/main.py → app/routers/<feature>.py → app/services/<feature>.py → app/core/database.py
```

### Agent pipeline (event-driven via Redis Streams)
```
Data Agent → KPI Agent → HITL Workflow Agent → Insight Agent
          → Explainability Agent → Decision Agent → Task Assignment Agent → Reporting Agent
```
Each agent is a containerized Python worker that subscribes to specific Redis event types only.

### Key files
- `app/core/config.py` — Pydantic `Settings`; all env vars go here first
- `app/core/database.py` — SQLAlchemy `engine`, `SessionLocal`, `Base`; import `Base` in every model file so Alembic detects it
- `app/main.py` — mounts all routers; add new routers with `app.include_router(..., prefix=settings.API_V1_PREFIX)`

### Conventions
- All API routes prefixed `/api/v1`
- **Multi-tenant**: every DB record and API request must carry `tenant_id`; Row-Level Security enforced at the DB layer
- **RBAC**: 4 roles — Executive, Business Manager, Data/BI Analyst, Operations User — enforced via JWT claims
- KPIs have two states: **Draft** (Analyst-only) and **Certified** (published); insights only run against certified KPIs
- Models → `app/models/`, Pydantic schemas → `app/schemas/`, business logic → `app/services/`
- DB session injected via `Depends(get_db)` from `app/core/database.py`
- New models must be imported in `app/models/__init__.py` for Alembic autogenerate to pick them up

## Tech Stack
| Layer | Technology |
|---|---|
| API | FastAPI (Python) |
| Agent workers | Python + LangChain or custom orchestration |
| LLM | Google Gemini |
| Vector store | pgvector (Postgres extension) |
| Data transform | dbt Core |
| Message broker | Redis Streams |
| Auth | Auth0 or AWS Cognito (JWT + RBAC) |
| Deployment | Docker → AWS ECS Fargate or GCP Cloud Run |
| CI/CD | GitHub Actions |

## Sprint Ownership (Lakshit = backend/infra)

**Sprint 1:** JWT middleware + `tenant_id` enforcement, Redis `AgentPublisher`/`AgentSubscriber` base classes, Postgres connector service (extract + load), connector registry tables + CRUD APIs, credential encryption.

**Sprint 2:** Dashboard shell APIs (save/load state, widget coordinates), react-grid-layout backend support, RBAC context wiring.

**Sprint 3:** Insight Agent math (z-scores, rolling averages, trend slopes), GenAI layer (anomaly → LLM → category + summary), WebSocket manager (Redis → frontend push), MoM/YoY time intelligence.

**Sprint 4:** Explainability Agent (receipt generator, pgvector KPI lookup, reasoning chain), confidence scoring algorithm, explainability UI components (drill-down modal, evidence trail).

**Sprint 5:** Reporting Agent (weekly cron, LLM executive summary), append-only audit logs, production hardening (rate limiting, ECS deployment, query optimization).
