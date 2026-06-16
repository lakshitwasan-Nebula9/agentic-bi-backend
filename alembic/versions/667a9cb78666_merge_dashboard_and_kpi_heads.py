"""merge dashboard and kpi heads

Revision ID: 667a9cb78666
Revises: 9e09d76e83df, a1b2c3d4e5f6
Create Date: 2026-06-16 12:27:01.682085

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '667a9cb78666'
down_revision: Union[str, None] = ('9e09d76e83df', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
