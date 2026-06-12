"""drop tenant_id from embeddings

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF EXISTS guards against fresh DBs where a3f2c1d4e5b6 already ran
    # without tenant_id (after we removed it from that migration)
    op.execute("DROP INDEX IF EXISTS ix_embeddings_tenant_id")
    op.execute("ALTER TABLE embeddings DROP COLUMN IF EXISTS tenant_id")


def downgrade() -> None:
    op.add_column(
        "embeddings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_embeddings_tenant_id", "embeddings", ["tenant_id"])
