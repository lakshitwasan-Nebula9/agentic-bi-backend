"""add_sync_logs_table

Revision ID: e511f0583839
Revises: 5ae4f8d65903
Create Date: 2026-06-24 17:13:08.971536

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e511f0583839"
down_revision: str | None = "5ae4f8d65903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("connector_id", sa.UUID(), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=True),
        sa.Column("dataset_name", sa.String(), nullable=True),
        sa.Column("sync_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("tables_updated", sa.Integer(), nullable=False),
        sa.Column("rows_synced", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("triggered_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["connector_id"], ["data_connectors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sync_logs_connector_id"), "sync_logs", ["connector_id"], unique=False)
    op.create_index(op.f("ix_sync_logs_created_at"), "sync_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sync_logs_created_at"), table_name="sync_logs")
    op.drop_index(op.f("ix_sync_logs_connector_id"), table_name="sync_logs")
    op.drop_table("sync_logs")
