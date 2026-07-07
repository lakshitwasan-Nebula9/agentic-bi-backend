"""add insight feedback, insight guidance tables, and suppression fields

Revision ID: a79bd48aefe4
Revises: 95a113ff6e6c
Create Date: 2026-07-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a79bd48aefe4"
down_revision: str | None = "95a113ff6e6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "insight_events",
        sa.Column("is_suppressed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("insight_events", sa.Column("suppression_score", sa.Float(), nullable=True))

    op.create_table(
        "insight_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "insight_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("insight_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.String(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_insight_feedback_insight_id", "insight_feedback", ["insight_id"])
    op.create_index("ix_insight_feedback_user_id", "insight_feedback", ["user_id"])
    op.create_index(
        "uq_insight_feedback_insight_user_active",
        "insight_feedback",
        ["insight_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )

    op.create_table(
        "insight_guidance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("guidance_text", sa.Text(), nullable=False),
        sa.Column("feedback_count_considered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_used", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("insight_guidance")
    op.drop_index("uq_insight_feedback_insight_user_active", table_name="insight_feedback")
    op.drop_index("ix_insight_feedback_user_id", table_name="insight_feedback")
    op.drop_index("ix_insight_feedback_insight_id", table_name="insight_feedback")
    op.drop_table("insight_feedback")
    op.drop_column("insight_events", "suppression_score")
    op.drop_column("insight_events", "is_suppressed")
