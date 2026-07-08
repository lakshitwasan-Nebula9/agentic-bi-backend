"""merge hot-read indexes and insight feedback heads

Revision ID: 882440c29286
Revises: b5c6d7e8f9a0, 043a0d3dfe15
Create Date: 2026-07-08 17:08:47.161230

"""

from collections.abc import Sequence

revision: str = "882440c29286"
down_revision: str | None = ("b5c6d7e8f9a0", "043a0d3dfe15")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
