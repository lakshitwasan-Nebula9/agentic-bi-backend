"""One-off: apply the insight_feedback / insight_guidance DDL directly to Supabase.

Per CLAUDE.md's multi-dev Alembic caveat, `alembic upgrade head` can't be run
against Supabase (its alembic_version sits on a different lineage), so new
tables/columns are applied via their migration's raw DDL instead. This mirrors
alembic/versions/a79bd48aefe4_add_insight_feedback_and_guidance.py::upgrade()
exactly, but is idempotent (IF NOT EXISTS) so it's safe to re-run.
"""

from sqlalchemy import text

from app.core.database import engine

DDL_STATEMENTS = [
    "ALTER TABLE insight_events ADD COLUMN IF NOT EXISTS is_suppressed boolean NOT NULL DEFAULT false",
    "ALTER TABLE insight_events ADD COLUMN IF NOT EXISTS suppression_score float",
    # Orphan table from an earlier/other-branch experiment: 0 rows, different
    # schema (insight_event_id/feedback_type), not referenced by any model or
    # migration in this codebase. Confirmed empty and safe to drop before
    # recreating with this migration's schema.
    "DROP TABLE IF EXISTS insight_feedback",
    """
    CREATE TABLE IF NOT EXISTS insight_feedback (
        id UUID PRIMARY KEY,
        insight_id UUID NOT NULL REFERENCES insight_events(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        rating VARCHAR NOT NULL,
        comment TEXT,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now(),
        is_deleted boolean NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_insight_feedback_insight_id ON insight_feedback (insight_id)",
    "CREATE INDEX IF NOT EXISTS ix_insight_feedback_user_id ON insight_feedback (user_id)",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_insight_feedback_insight_user_active
    ON insight_feedback (insight_id, user_id)
    WHERE is_deleted = false
    """,
    """
    CREATE TABLE IF NOT EXISTS insight_guidance (
        id UUID PRIMARY KEY,
        guidance_text TEXT NOT NULL,
        feedback_count_considered INTEGER NOT NULL DEFAULT 0,
        period_start TIMESTAMPTZ,
        period_end TIMESTAMPTZ,
        model_used TEXT,
        is_active boolean NOT NULL DEFAULT true,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
]


def main() -> None:
    with engine.begin() as conn:
        for stmt in DDL_STATEMENTS:
            conn.execute(text(stmt))
    print("insight_feedback / insight_guidance DDL applied.")


if __name__ == "__main__":
    main()
