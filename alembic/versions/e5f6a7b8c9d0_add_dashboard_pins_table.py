"""add dashboard_pins table (per-user dashboard pinning)

Pinning used to flip the global ``dashboards.is_default`` column, so a pin showed
in every user's Pinned section. Introduce a per-user pin association so pinning is
a private preference. The ``is_default`` column is left in place but no longer
drives pin state.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboard_pins",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dashboard_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dashboards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "dashboard_id", name="uq_dashboard_pin"),
    )
    op.create_index("ix_dashboard_pins_user_id", "dashboard_pins", ["user_id"])
    op.create_index("ix_dashboard_pins_dashboard_id", "dashboard_pins", ["dashboard_id"])


def downgrade() -> None:
    op.drop_index("ix_dashboard_pins_dashboard_id", table_name="dashboard_pins")
    op.drop_index("ix_dashboard_pins_user_id", table_name="dashboard_pins")
    op.drop_table("dashboard_pins")
