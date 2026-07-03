"""add_dashboard_category

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-07-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dashboards", sa.Column("category", sa.String(), nullable=True))
    op.create_index("ix_dashboards_category", "dashboards", ["category"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_dashboards_category", table_name="dashboards")
    op.drop_column("dashboards", "category")
