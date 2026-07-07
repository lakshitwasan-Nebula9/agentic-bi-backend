"""add_dashboard_permissions_table

Revision ID: a4b5c6d7e8f9
Revises: 95a113ff6e6c
Create Date: 2026-07-07 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | None = "95a113ff6e6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboard_permissions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dashboard_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("access_level", sa.String(), nullable=False),
        sa.Column("granted_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["dashboard_id"], ["dashboards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dashboard_id", "user_id", name="uq_dashboard_permission"),
    )
    op.create_index(
        op.f("ix_dashboard_permissions_dashboard_id"),
        "dashboard_permissions",
        ["dashboard_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dashboard_permissions_user_id"),
        "dashboard_permissions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dashboard_permissions_user_id"), table_name="dashboard_permissions")
    op.drop_index(op.f("ix_dashboard_permissions_dashboard_id"), table_name="dashboard_permissions")
    op.drop_table("dashboard_permissions")
