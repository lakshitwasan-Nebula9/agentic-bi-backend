"""add description to dashboards

Revision ID: a6d35c135af6
Revises: c1d2e3f4a5b6
Create Date: 2026-06-19 14:51:05.521559

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a6d35c135af6"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dashboards", sa.Column("description", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("dashboards", "description")
