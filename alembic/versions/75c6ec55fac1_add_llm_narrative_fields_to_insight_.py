"""add llm narrative fields to insight_events

Revision ID: 75c6ec55fac1
Revises: 6152a938cb29
Create Date: 2026-06-23 18:06:06.030286

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "75c6ec55fac1"
down_revision: str | None = "6152a938cb29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("insight_events", sa.Column("llm_title", sa.String(), nullable=True))
    op.add_column("insight_events", sa.Column("llm_category", sa.String(), nullable=True))
    op.add_column("insight_events", sa.Column("llm_severity", sa.String(), nullable=True))
    op.add_column("insight_events", sa.Column("llm_summary", sa.Text(), nullable=True))
    op.add_column(
        "insight_events", sa.Column("narrated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("insight_events", "narrated_at")
    op.drop_column("insight_events", "llm_summary")
    op.drop_column("insight_events", "llm_severity")
    op.drop_column("insight_events", "llm_category")
    op.drop_column("insight_events", "llm_title")
