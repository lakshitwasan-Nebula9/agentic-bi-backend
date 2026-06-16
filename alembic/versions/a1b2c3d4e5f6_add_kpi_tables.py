"""add kpi_definitions, kpi_versions, kpi_snapshots tables

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-06-15 00:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kpi_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("table_name", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("display_name", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("formula", sa.Text, nullable=False),
        sa.Column("sql_expression", sa.Text, nullable=False),
        sa.Column("unit", sa.String, nullable=True),
        sa.Column("direction", sa.String, nullable=False),
        sa.Column("suggested_chart", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="pending_review"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=True),
        sa.Column("owner_name", sa.String, nullable=True),
        sa.Column("owner_role", sa.String, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("certified_by", UUID(as_uuid=True), nullable=True),
        sa.Column("certified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_kpi_definitions_dataset_id", "kpi_definitions", ["dataset_id"])
    op.create_index("ix_kpi_definitions_status", "kpi_definitions", ["status"])

    op.create_table(
        "kpi_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "kpi_id",
            UUID(as_uuid=True),
            sa.ForeignKey("kpi_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("formula", sa.Text, nullable=False),
        sa.Column("sql_expression", sa.Text, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("changed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("change_reason", sa.Text, nullable=True),
        sa.Column(
            "snapshot_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_kpi_versions_kpi_id", "kpi_versions", ["kpi_id"])

    op.create_table(
        "kpi_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "kpi_id",
            UUID(as_uuid=True),
            sa.ForeignKey("kpi_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_id", UUID(as_uuid=True), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_kpi_snapshots_kpi_id", "kpi_snapshots", ["kpi_id"])


def downgrade() -> None:
    op.drop_index("ix_kpi_snapshots_kpi_id", table_name="kpi_snapshots")
    op.drop_table("kpi_snapshots")
    op.drop_index("ix_kpi_versions_kpi_id", table_name="kpi_versions")
    op.drop_table("kpi_versions")
    op.drop_index("ix_kpi_definitions_status", table_name="kpi_definitions")
    op.drop_index("ix_kpi_definitions_dataset_id", table_name="kpi_definitions")
    op.drop_table("kpi_definitions")
