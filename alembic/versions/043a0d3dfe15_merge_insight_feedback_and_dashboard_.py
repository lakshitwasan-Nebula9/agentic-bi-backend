"""merge insight feedback and dashboard permissions heads

Revision ID: 043a0d3dfe15
Revises: a4b5c6d7e8f9, a79bd48aefe4
Create Date: 2026-07-07 16:41:45.595010

"""

from collections.abc import Sequence

revision: str = "043a0d3dfe15"
down_revision: str | None = ("a4b5c6d7e8f9", "a79bd48aefe4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
