"""add approval_requests table

Revision ID: c1d2e3f4a5b6
Revises: 667a9cb78666
Create Date: 2026-06-16 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "667a9cb78666"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String, nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("current_stage", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="2"),
        sa.Column("assigned_role", sa.String, nullable=False),
        sa.Column("assigned_to", UUID(as_uuid=True), nullable=True),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", UUID(as_uuid=True), nullable=True),
        sa.Column("resolution_note", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_approval_requests_entity_id", "approval_requests", ["entity_id"])
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"])
    op.create_index("ix_approval_requests_assigned_role", "approval_requests", ["assigned_role"])


def downgrade() -> None:
    op.drop_index("ix_approval_requests_assigned_role", table_name="approval_requests")
    op.drop_index("ix_approval_requests_status", table_name="approval_requests")
    op.drop_index("ix_approval_requests_entity_id", table_name="approval_requests")
    op.drop_table("approval_requests")
