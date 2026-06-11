"""resize embedding vector from 768 to 384 for all-MiniLM-L6-v2

Revision ID: b7e4d2f1a8c9
Revises: a3f2c1d4e5b6
Create Date: 2026-06-11 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7e4d2f1a8c9"
down_revision: str | None = "a3f2c1d4e5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS embeddings_embedding_idx")
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(384)")
    op.execute("CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS embeddings_embedding_idx")
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(768)")
    op.execute("CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops)")