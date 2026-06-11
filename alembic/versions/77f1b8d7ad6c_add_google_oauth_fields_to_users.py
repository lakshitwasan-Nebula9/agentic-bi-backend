"""add google oauth fields to users

Revision ID: 77f1b8d7ad6c
Revises: 2cc1517af63c
Create Date: 2026-06-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "77f1b8d7ad6c"
down_revision: str | None = "2cc1517af63c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "hashed_password", existing_type=sa.String(), nullable=True)
    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(), server_default="local", nullable=False),
    )
    op.add_column("users", sa.Column("external_subject", sa.String(), nullable=True))
    op.create_index(op.f("ix_users_external_subject"), "users", ["external_subject"], unique=True)
    op.alter_column("users", "auth_provider", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_external_subject"), table_name="users")
    op.drop_column("users", "external_subject")
    op.drop_column("users", "auth_provider")
    op.alter_column("users", "hashed_password", existing_type=sa.String(), nullable=False)
