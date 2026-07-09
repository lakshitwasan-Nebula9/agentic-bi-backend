"""add report scope columns

Reports were global-only: every report pulled every certified KPI/dataset/insight.
Add a scope discriminator plus optional foreign keys so a report can be pinned to a
single dashboard (its widget KPIs) or a single database/connector (all of its
certified KPIs). Both FKs stay null for a global report.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("scope", sa.String(), nullable=False, server_default="global"),
    )
    op.add_column(
        "reports",
        sa.Column("dashboard_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "reports",
        sa.Column("connector_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_reports_dashboard_id",
        "reports",
        "dashboards",
        ["dashboard_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_reports_connector_id",
        "reports",
        "data_connectors",
        ["connector_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_reports_connector_id", "reports", type_="foreignkey")
    op.drop_constraint("fk_reports_dashboard_id", "reports", type_="foreignkey")
    op.drop_column("reports", "connector_id")
    op.drop_column("reports", "dashboard_id")
    op.drop_column("reports", "scope")
