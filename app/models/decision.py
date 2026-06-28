import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DecisionRecord(Base):
    """One row per InsightEvent — written by the Decision Agent.

    Deterministic fields (priority, owner role, SLA) are computed by pure Python
    rule engine before the LLM is called. LLM fields are best-effort and nullable.
    """

    __tablename__ = "decision_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    insight_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("insight_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    kpi_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kpi_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Deterministic fields — set before LLM call ---
    priority: Mapped[str] = mapped_column(String, nullable=False)  # P1 | P2 | P3
    recommended_owner_role: Mapped[str] = mapped_column(String, nullable=False)
    sla_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    suggested_due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- LLM output fields — best-effort, all nullable ---
    action_type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # monitor | investigate | optimize | escalate
    decision_type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # corrective | preventive | informational | approval_required
    llm_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_action_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_business_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Lifecycle ---
    # pending → decided (P2/P3) | awaiting_approval (P1)
    # awaiting_approval → approved | rejected
    # approved / decided → actioned
    # any → expired
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")

    # --- Approval tracking (P1 only) ---
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Downstream consumption ---
    actioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
