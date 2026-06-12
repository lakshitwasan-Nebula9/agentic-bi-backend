"""add quality_metrics and quality_score to datasets

Revision ID: d2e3f4a5b6c7
Revises: 8192a39dd10a
Create Date: 2026-06-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "8192a39dd10a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("quality_metrics", JSONB, nullable=True))
    op.add_column("datasets", sa.Column("quality_score", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("datasets", "quality_score")
    op.drop_column("datasets", "quality_metrics")
