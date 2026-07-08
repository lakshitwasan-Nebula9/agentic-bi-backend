import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InsightEvent(Base):
    """One row per (KPI, period_start) — written by the Insight Agent math layer."""

    __tablename__ = "insight_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kpi_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpi_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # The KPI value for this period
    value: Mapped[float] = mapped_column(Float, nullable=False)

    # Z-score of value vs. baseline window (previous months)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_std: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Rolling averages (None when fewer snapshots exist than window size)
    rolling_avg_3m: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_avg_6m: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Normalized slope: % change per month from linear regression over all snapshots
    trend_slope: Mapped[float | None] = mapped_column(Float, nullable=True)

    # spike | dip | trend_up | trend_down | stable
    insight_type: Mapped[str] = mapped_column(String, nullable=False, default="stable")
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # GenAI narrative layer — populated best-effort by the Insight Agent (Gemini).
    # All nullable: the math event persists even when the LLM is disabled or fails.
    llm_title: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_category: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_severity: Mapped[str | None] = mapped_column(String, nullable=True)  # info|warning|critical
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Short-term feedback-suppression heuristic (app.services.insight_feedback_service).
    # Never hides the event — it is still created, narrated, and pushed; the
    # frontend uses these to badge/gray it out per repeated similar down-votes.
    is_suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suppression_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        # Hot read path: insight feed filters live rows (+ optional kpi_id) newest-first
        # (insight_service.list_insights) and batch reads by kpi_id in connector/dataset
        # services. Replaces the plain kpi_id FK index — this partial composite is a superset.
        Index(
            "ix_insight_events_kpi_created_active",
            "kpi_id",
            text("created_at DESC"),
            postgresql_where=text("is_deleted = false"),
        ),
    )
