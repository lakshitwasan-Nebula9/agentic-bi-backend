"""add unique constraint on kpi_snapshots (kpi_id, period_start, period_end)

Revision ID: b2c3d4e5f6a7
Revises: a6d35c135af6
Create Date: 2026-06-23 00:00:00.000000

PostgreSQL treats NULL values as distinct for UNIQUE constraint purposes, so rows
with (kpi_id, NULL, NULL) do not conflict — the full-dataset fallback path continues
to accumulate freely while monthly buckets are deduplicated per period.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a6d35c135af6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_kpi_snapshots_kpi_period",
        "kpi_snapshots",
        ["kpi_id", "period_start", "period_end"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_kpi_snapshots_kpi_period", "kpi_snapshots", type_="unique")
