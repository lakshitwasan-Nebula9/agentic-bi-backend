import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String, nullable=False)
    period_label: Mapped[str | None] = mapped_column(String, nullable=True)

    # generating | ready | failed
    status: Mapped[str] = mapped_column(String, nullable=False, default="generating")

    # Report scope: global | dashboard | database. A global report leaves the
    # scoped foreign keys null; a dashboard/database report pins one of them.
    scope: Mapped[str] = mapped_column(String, nullable=False, server_default="global")
    dashboard_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dashboards.id", ondelete="SET NULL"), nullable=True
    )
    connector_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_connectors.id", ondelete="SET NULL"), nullable=True
    )

    # Quick-access denormalized narrative (also stored inside report_json)
    executive_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full structured report as JSON — matches the ReportData Pydantic schema
    report_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
