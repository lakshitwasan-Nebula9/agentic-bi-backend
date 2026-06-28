"""merge_decision_and_explainability_heads

Revision ID: 70a7c1c9e45c
Revises: 157d7fe6e961, a1b2c3d4e5f7
Create Date: 2026-06-28 20:14:02.487408

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '70a7c1c9e45c'
down_revision: Union[str, None] = ('157d7fe6e961', 'a1b2c3d4e5f7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
