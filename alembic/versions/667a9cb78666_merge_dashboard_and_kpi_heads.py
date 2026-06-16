"""merge dashboard and kpi heads

Revision ID: 667a9cb78666
Revises: 9e09d76e83df, a1b2c3d4e5f6
Create Date: 2026-06-16 12:27:01.682085

"""
from collections.abc import Sequence

revision: str = '667a9cb78666'
down_revision: str | None = ('9e09d76e83df', 'a1b2c3d4e5f6')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
