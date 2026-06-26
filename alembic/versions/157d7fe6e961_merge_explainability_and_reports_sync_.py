"""merge explainability and reports/sync_logs heads

Revision ID: 157d7fe6e961
Revises: e511f0583839, e9648299390e
Create Date: 2026-06-26 16:13:32.329146

"""

from collections.abc import Sequence

revision: str = "157d7fe6e961"
down_revision: str | None = ("e511f0583839", "e9648299390e")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
