"""merge multiple heads

Revision ID: 6da92d3e30c7
Revises: a3f2c1d4e5b6, f70328567ec7
Create Date: 2026-06-11 16:30:57.878413

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6da92d3e30c7'
down_revision: Union[str, None] = ('a3f2c1d4e5b6', 'f70328567ec7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
