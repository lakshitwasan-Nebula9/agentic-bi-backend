import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InsightExplanation(Base):
    """Explainability receipt for one InsightEvent — written by the Explainability Agent.

    One row per insight (unique on insight_event_id). Holds the deterministic values
    surfaced in the insight drill-down modal: a computed confidence score, the source
    dataset, data freshness, and the KPI formula. No LLM is involved — the narrative
    rationale already lives on the InsightEvent (llm_summary).
    """

    __tablename__ = "insight_explanations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    insight_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("insight_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    kpi_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Computed confidence (0–100) plus a breakdown of the component scores for auditability.
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # e.g. "sales_db.orders" (connector database_name + KPI table_name)
    source_dataset: Mapped[str | None] = mapped_column(String, nullable=True)
    # When the source data was last synced; the frontend renders this relatively ("4 min ago").
    data_freshness_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    kpi_formula: Mapped[str | None] = mapped_column(Text, nullable=True)

    llm_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_drivers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    recommended_actions: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
