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
docker compose up --build              # start API + Postgres
docker compose up -d db                # start only Postgres (for local dev against real DB)
```

### Alembic Migrations
```bash
alembic revision --autogenerate -m "description"   # generate migration from model changes
alembic upgrade head                               # apply all pending migrations
alembic downgrade -1                               # roll back one migration
```
The `alembic.ini` hardcodes a fallback DB URL, but `alembic/env.py` overrides it with `settings.DATABASE_URL` from `.env` — always set the real URL there.

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
