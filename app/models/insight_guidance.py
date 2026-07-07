import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InsightGuidance(Base):
    """A generated batch of prompt guidance derived from user feedback.

    Written by app.services.insight_guidance_service on a weekly cron (and
    on-demand via the analyst-facing endpoint). Each run inserts a new row
    rather than overwriting the previous one, so the guidance history is
    auditable; only the latest ``is_active`` row is read by the Insight Agent.
    """

    __tablename__ = "insight_guidance"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    guidance_text: Mapped[str] = mapped_column(Text, nullable=False)
    feedback_count_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
