"""add insight_explanations table

Revision ID: e9648299390e
Revises: 75c6ec55fac1
Create Date: 2026-06-25 13:03:39.005093

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e9648299390e"
down_revision: str | None = "75c6ec55fac1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "insight_explanations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("insight_event_id", sa.UUID(), nullable=False),
        sa.Column("kpi_id", sa.UUID(), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("confidence_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_dataset", sa.String(), nullable=True),
        sa.Column("data_freshness_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kpi_formula", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["insight_event_id"], ["insight_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_insight_explanations_insight_event_id"),
        "insight_explanations",
        ["insight_event_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_insight_explanations_kpi_id"), "insight_explanations", ["kpi_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_insight_explanations_kpi_id"), table_name="insight_explanations")
    op.drop_index(
        op.f("ix_insight_explanations_insight_event_id"), table_name="insight_explanations"
    )
    op.drop_table("insight_explanations")
