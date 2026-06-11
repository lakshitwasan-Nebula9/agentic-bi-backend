"""Add datasets and dataset_records tables

Revision ID: f70328567ec7
Revises: 9f36c1b62c43
Create Date: 2026-06-11 13:04:40.385758

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f70328567ec7"
down_revision: str | None = "9f36c1b62c43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("connector_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_query", sa.Text(), nullable=False),
        sa.Column("schema_fingerprint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["connector_id"], ["data_connectors.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_datasets_name"), "datasets", ["name"], unique=True)
    op.create_table(
        "dataset_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("row_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dataset_records_dataset_id"), "dataset_records", ["dataset_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dataset_records_dataset_id"), table_name="dataset_records")
    op.drop_table("dataset_records")
    op.drop_index(op.f("ix_datasets_name"), table_name="datasets")
    op.drop_table("datasets")
