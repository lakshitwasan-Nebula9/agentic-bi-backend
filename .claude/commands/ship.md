Run the full local CI checklist and ship the current changes. Stop at the first failure and report it — do not proceed to later steps.

Steps (in order):

1. **Lint** — run `ruff check . --fix && black .` to auto-fix, then `ruff check . && black --check .` to confirm clean.

2. **DB up** — run `docker compose up -d db` to ensure Postgres is running.

3. **Migrations** — run `DATABASE_URL=postgresql://user:password@localhost:5432/agentic_bi alembic upgrade head` and confirm it exits cleanly (already-applied migrations are fine).

4. **Tests** — run `DATABASE_URL=postgresql://user:password@localhost:5432/agentic_bi python -m pytest tests/ -v --tb=short`. Skips are acceptable; any failure is a blocker.

5. **Docker build** — run `docker build -t agentic-bi-backend:ci .` and confirm it succeeds.

6. **Commit & push** — only if all above pass: stage the relevant files, commit with a descriptive message, and push to the current branch.
