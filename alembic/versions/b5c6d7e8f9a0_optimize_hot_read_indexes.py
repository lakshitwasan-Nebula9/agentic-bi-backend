"""optimize_hot_read_indexes

Replaces the single-column FK indexes on the two hottest append-only tables
(kpi_snapshots, insight_events) with partial composite indexes that match the
real read shapes: filter kpi_id + is_deleted=false, ordered newest-first. The
old single-column indexes become redundant prefixes of the new composites.

Note: this migration file uses plain CREATE INDEX (runs inside Alembic's
transaction, used only by CI's fresh DB). The live Supabase DB is indexed by
hand with CREATE INDEX CONCURRENTLY to avoid locking the tables — see the
Sprint 5 query-optimization plan.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-07-08 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: str | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # kpi_snapshots: per-KPI time-series, live rows, newest-first.
    op.create_index(
        "ix_kpi_snapshots_kpi_period_computed_active",
        "kpi_snapshots",
        ["kpi_id", sa.text("period_start DESC NULLS LAST"), sa.text("computed_at DESC")],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_index("ix_kpi_snapshots_kpi_id", table_name="kpi_snapshots")

    # insight_events: insight feed, live rows, newest-first.
    op.create_index(
        "ix_insight_events_kpi_created_active",
        "insight_events",
        ["kpi_id", sa.text("created_at DESC")],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_index("ix_insight_events_kpi_id", table_name="insight_events")


def downgrade() -> None:
    op.create_index(
        "ix_insight_events_kpi_id",
        "insight_events",
        ["kpi_id"],
        unique=False,
    )
    op.drop_index("ix_insight_events_kpi_created_active", table_name="insight_events")

    op.create_index(
        "ix_kpi_snapshots_kpi_id",
        "kpi_snapshots",
        ["kpi_id"],
        unique=False,
    )
    op.drop_index("ix_kpi_snapshots_kpi_period_computed_active", table_name="kpi_snapshots")
