"""merge_decision_and_explainability_heads

Revision ID: 70a7c1c9e45c
Revises: 157d7fe6e961, a1b2c3d4e5f7
Create Date: 2026-06-28 20:14:02.487408

"""

from collections.abc import Sequence

revision: str = "70a7c1c9e45c"
down_revision: str | None = ("157d7fe6e961", "a1b2c3d4e5f7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
