"""add embeddings table with pgvector

Revision ID: a3f2c1d4e5b6
Revises: 77f1b8d7ad6c
Create Date: 2026-06-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a3f2c1d4e5b6"
down_revision: str | None = "77f1b8d7ad6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Vector column added via raw SQL — Alembic autogenerate doesn't know Vector type
    op.execute("ALTER TABLE embeddings ADD COLUMN embedding vector(768)")

    # HNSW index for fast approximate nearest-neighbour cosine search
    op.execute("CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops)")

    op.create_index("ix_embeddings_entity_type", "embeddings", ["entity_type"])


def downgrade() -> None:
    op.drop_table("embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")
