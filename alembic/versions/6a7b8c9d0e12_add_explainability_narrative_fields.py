"""add llm_explanation, business_drivers, recommended_actions to insight_explanations

Revision ID: 6a7b8c9d0e12
Revises: 5f6a7b8c9d01
Create Date: 2026-06-29

NOTE: DDL already applied to Supabase directly. This file is for CI/local dev only.
Do not run alembic upgrade head against Supabase (see CLAUDE.md multi-dev caveat).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "6a7b8c9d0e12"
down_revision = "5f6a7b8c9d01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("insight_explanations", sa.Column("llm_explanation", sa.Text(), nullable=True))
    op.add_column("insight_explanations", sa.Column("business_drivers", JSONB(), nullable=True))
    op.add_column("insight_explanations", sa.Column("recommended_actions", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("insight_explanations", "recommended_actions")
    op.drop_column("insight_explanations", "business_drivers")
    op.drop_column("insight_explanations", "llm_explanation")
