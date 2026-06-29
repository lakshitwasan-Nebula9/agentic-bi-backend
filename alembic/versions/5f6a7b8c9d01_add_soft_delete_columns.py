"""add soft delete columns (is_deleted + deleted_at) to all entity tables

Revision ID: 5f6a7b8c9d01
Revises: 70a7c1c9e45c
Create Date: 2026-06-29

NOTE: The DDL in this migration was applied directly to Supabase via psql.
Do NOT run alembic upgrade head against Supabase — the schema is already live.
This file exists so CI (ephemeral Postgres) and local dev resets pick up the change.
"""

import sqlalchemy as sa

from alembic import op

revision = "5f6a7b8c9d01"
down_revision = "70a7c1c9e45c"
branch_labels = None
depends_on = None

_TABLES = [
    "data_connectors",
    "datasets",
    "dataset_records",
    "kpi_definitions",
    "kpi_versions",
    "kpi_snapshots",
    "insight_events",
    "insight_explanations",
    "decision_records",
    "schema_metadata",
    "embeddings",
    "approval_requests",
]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table, sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false")
        )
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index(
        "idx_kpi_definitions_not_deleted",
        "kpi_definitions",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_kpi_snapshots_not_deleted",
        "kpi_snapshots",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_insight_events_not_deleted",
        "insight_events",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_embeddings_not_deleted",
        "embeddings",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_embeddings_not_deleted", table_name="embeddings")
    op.drop_index("idx_insight_events_not_deleted", table_name="insight_events")
    op.drop_index("idx_kpi_snapshots_not_deleted", table_name="kpi_snapshots")
    op.drop_index("idx_kpi_definitions_not_deleted", table_name="kpi_definitions")

    for table in reversed(_TABLES):
        op.drop_column(table, "deleted_at")
        op.drop_column(table, "is_deleted")
