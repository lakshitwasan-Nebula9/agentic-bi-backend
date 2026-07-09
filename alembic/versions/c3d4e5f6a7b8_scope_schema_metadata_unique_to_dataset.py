"""scope schema_metadata uniqueness to (dataset_id, table_name)

Two connectors pointed at the same source DB could create datasets against the same
table name; schema_metadata's global unique index on table_name meant the second
dataset's schema detection silently overwrote the first dataset's row (repointing
dataset_id and clobbering columns/measures/dimensions). Scope uniqueness per-dataset
so each dataset keeps its own schema annotation.

Revision ID: c3d4e5f6a7b8
Revises: 882440c29286
Create Date: 2026-07-09 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "882440c29286"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_schema_metadata_table_name", table_name="schema_metadata")
    op.create_index("ix_schema_metadata_table_name", "schema_metadata", ["table_name"])
    op.create_unique_constraint(
        "uq_schema_metadata_dataset_table", "schema_metadata", ["dataset_id", "table_name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_schema_metadata_dataset_table", "schema_metadata", type_="unique")
    op.drop_index("ix_schema_metadata_table_name", table_name="schema_metadata")
    op.create_index("ix_schema_metadata_table_name", "schema_metadata", ["table_name"], unique=True)
