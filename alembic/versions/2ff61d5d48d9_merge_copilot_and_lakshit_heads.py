"""merge_copilot_and_lakshit_heads

Revision ID: 2ff61d5d48d9
Revises: 7b8c9d0e1f23, b3c4d5e6f7a8
Create Date: 2026-06-30 16:12:35.387842

"""

from collections.abc import Sequence

revision: str = "2ff61d5d48d9"
down_revision: str | None = ("7b8c9d0e1f23", "b3c4d5e6f7a8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
