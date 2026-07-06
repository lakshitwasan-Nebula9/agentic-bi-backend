"""merge auth_method and audit_logs heads

Revision ID: 95a113ff6e6c
Revises: c4d5e6f7a8b9, e7f8a9b0c1d2
Create Date: 2026-07-06 16:54:07.658164

"""

from collections.abc import Sequence

revision: str = "95a113ff6e6c"
down_revision: str | None = ("c4d5e6f7a8b9", "e7f8a9b0c1d2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
