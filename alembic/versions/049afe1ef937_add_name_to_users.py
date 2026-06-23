"""add_name_to_users

Revision ID: 049afe1ef937
Revises: b2c3d4e5f6a7
Create Date: 2026-06-23 13:01:00.861935

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "049afe1ef937"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "name")
