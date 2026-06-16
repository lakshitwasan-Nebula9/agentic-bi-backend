"""add schema_metadata table

Revision ID: f1a2b3c4d5e6
Revises: e3f4a5b6c7d8
Create Date: 2026-06-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schema_metadata",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("table_name", sa.String, nullable=False),
        sa.Column("entity_type", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("columns", JSONB, nullable=True),
        sa.Column("identifiers", JSONB, nullable=True),
        sa.Column("dimensions", JSONB, nullable=True),
        sa.Column("measures", JSONB, nullable=True),
        sa.Column("date_columns", JSONB, nullable=True),
        sa.Column("suggested_kpis", JSONB, nullable=True),
        sa.Column("business_questions", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_schema_metadata_table_name", "schema_metadata", ["table_name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_schema_metadata_table_name", table_name="schema_metadata")
    op.drop_table("schema_metadata")
