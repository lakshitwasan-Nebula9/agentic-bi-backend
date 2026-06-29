"""replace global unique constraints with soft-delete-aware partial unique indexes

Revision ID: 7b8c9d0e1f23
Revises: 6a7b8c9d0e12
Create Date: 2026-06-29

Both data_connectors.name and kpi_snapshots(kpi_id, period_start, period_end) were
globally unique, which blocked legitimate reuse after a soft delete: you could not
reconnect a connector with a previously used name, nor re-snapshot a period whose
prior snapshot had been soft-deleted. These become partial unique indexes scoped to
live (is_deleted = false) rows.

NOTE: The DDL was applied directly to Supabase. This file exists for CI / local dev.
Do NOT run alembic upgrade head against Supabase — the schema is already live.
"""

import sqlalchemy as sa

from alembic import op

revision = "7b8c9d0e1f23"
down_revision = "6a7b8c9d0e12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # data_connectors: global unique name -> non-unique index + partial unique among live rows
    op.drop_index("ix_data_connectors_name", table_name="data_connectors")
    op.create_index("ix_data_connectors_name", "data_connectors", ["name"])
    op.create_index(
        "ix_data_connectors_name_active",
        "data_connectors",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )

    # kpi_snapshots: plain unique constraint -> partial unique index among live rows
    op.drop_constraint("uq_kpi_snapshots_kpi_period", "kpi_snapshots", type_="unique")
    op.create_index(
        "uq_kpi_snapshots_kpi_period_active",
        "kpi_snapshots",
        ["kpi_id", "period_start", "period_end"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index("uq_kpi_snapshots_kpi_period_active", table_name="kpi_snapshots")
    op.create_unique_constraint(
        "uq_kpi_snapshots_kpi_period",
        "kpi_snapshots",
        ["kpi_id", "period_start", "period_end"],
    )

    op.drop_index("ix_data_connectors_name_active", table_name="data_connectors")
    op.drop_index("ix_data_connectors_name", table_name="data_connectors")
    op.create_index("ix_data_connectors_name", "data_connectors", ["name"], unique=True)
