Run the full local CI checklist and ship the current changes. Stop at the first failure and report it — do not proceed to later steps.

Steps (in order):

1. **Lint** — run `ruff check . --fix && black .` to auto-fix, then `ruff check . && black --check .` to confirm clean.

2. **Services up** — run `docker compose up -d db redis` to ensure the sample-data Postgres and the Redis event bus the tests need are running.

3. **Tests** — run `python -m pytest tests/ -v --tb=short` (uses `DATABASE_URL` from `.env` → Supabase; there is no separate test DB and no `alembic upgrade head` step). Skips are acceptable; any failure is a blocker.

4. **Docker build** — run `docker build -t agentic-bi-backend:ci .` and confirm it succeeds.

5. **Commit & push** — only if all above pass: stage the relevant files, commit with a descriptive message, and push to the current branch.
