import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SchemaMetadata(Base):
    __tablename__ = "schema_metadata"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Nullable for legacy/unscoped rows (e.g. ad-hoc detection without a dataset). Uniqueness
    # is scoped per-dataset below so two datasets sharing a table name (e.g. two connectors
    # pointed at the same source DB) don't clobber each other's schema annotations.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    table_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    columns: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    identifiers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dimensions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    measures: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    date_columns: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    suggested_kpis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    business_questions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("dataset_id", "table_name", name="uq_schema_metadata_dataset_table"),
    )
