"""merge multiple heads

Revision ID: 6da92d3e30c7
Revises: a3f2c1d4e5b6, f70328567ec7
Create Date: 2026-06-11 16:30:57.878413

"""

from collections.abc import Sequence

revision: str = "6da92d3e30c7"
down_revision: str | None = ("a3f2c1d4e5b6", "f70328567ec7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
