"""add_auth_method_to_data_connectors

Revision ID: c4d5e6f7a8b9
Revises: d1e2f3a4b5c6
Create Date: 2026-07-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "data_connectors",
        sa.Column(
            "auth_method",
            sa.String(),
            nullable=False,
            server_default="password",
        ),
    )


def downgrade() -> None:
    op.drop_column("data_connectors", "auth_method")
