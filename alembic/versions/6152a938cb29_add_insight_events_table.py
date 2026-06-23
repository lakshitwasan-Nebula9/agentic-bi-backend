"""add insight_events table

Revision ID: 6152a938cb29
Revises: 049afe1ef937
Create Date: 2026-06-23 17:44:29.152803

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6152a938cb29"
down_revision: str | None = "049afe1ef937"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "insight_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kpi_id", sa.UUID(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("z_score", sa.Float(), nullable=True),
        sa.Column("baseline_mean", sa.Float(), nullable=True),
        sa.Column("baseline_std", sa.Float(), nullable=True),
        sa.Column("rolling_avg_3m", sa.Float(), nullable=True),
        sa.Column("rolling_avg_6m", sa.Float(), nullable=True),
        sa.Column("trend_slope", sa.Float(), nullable=True),
        sa.Column("insight_type", sa.String(), nullable=False),
        sa.Column("is_anomaly", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["kpi_id"], ["kpi_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_insight_events_kpi_id"), "insight_events", ["kpi_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_insight_events_kpi_id"), table_name="insight_events")
    op.drop_table("insight_events")
