"""add decision_records table

Revision ID: a1b2c3d4e5f7
Revises: 75c6ec55fac1
Create Date: 2026-06-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | None = "75c6ec55fac1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "decision_records" not in inspector.get_table_names():
        op.create_table(
            "decision_records",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("insight_event_id", sa.UUID(), nullable=False),
            sa.Column("kpi_id", sa.UUID(), nullable=False),
            # Deterministic fields
            sa.Column("priority", sa.String(), nullable=False),
            sa.Column("recommended_owner_role", sa.String(), nullable=False),
            sa.Column("sla_hours", sa.Integer(), nullable=False),
            sa.Column("suggested_due_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("requires_approval", sa.Boolean(), nullable=False),
            # LLM output (best-effort, nullable)
            sa.Column("action_type", sa.String(), nullable=True),
            sa.Column("decision_type", sa.String(), nullable=True),
            sa.Column("llm_rationale", sa.Text(), nullable=True),
            sa.Column("llm_action_summary", sa.Text(), nullable=True),
            sa.Column("llm_business_impact", sa.Text(), nullable=True),
            sa.Column("llm_confidence", sa.Float(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            # Lifecycle
            sa.Column("status", sa.String(), nullable=False),
            # Approval tracking
            sa.Column("approved_by", sa.UUID(), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            # Downstream
            sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["insight_event_id"], ["insight_events.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["kpi_id"], ["kpi_definitions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("insight_event_id", name="uq_decision_records_insight_event_id"),
        )
    existing_indexes = {i["name"] for i in inspector.get_indexes("decision_records")} if "decision_records" in inspector.get_table_names() else set()
    if "ix_decision_records_insight_event_id" not in existing_indexes:
        op.create_index(
            op.f("ix_decision_records_insight_event_id"),
            "decision_records",
            ["insight_event_id"],
            unique=True,
        )
    if "ix_decision_records_kpi_id" not in existing_indexes:
        op.create_index(
            op.f("ix_decision_records_kpi_id"),
            "decision_records",
            ["kpi_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_decision_records_kpi_id"), table_name="decision_records")
    op.drop_index(op.f("ix_decision_records_insight_event_id"), table_name="decision_records")
    op.drop_table("decision_records")
