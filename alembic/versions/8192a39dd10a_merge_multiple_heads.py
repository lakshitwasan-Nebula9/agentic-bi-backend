"""merge multiple heads

Revision ID: 8192a39dd10a
Revises: 6da92d3e30c7, b7e4d2f1a8c9
Create Date: 2026-06-11 16:58:37.452376

"""

from collections.abc import Sequence

revision: str = "8192a39dd10a"
down_revision: str | None = ("6da92d3e30c7", "b7e4d2f1a8c9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
