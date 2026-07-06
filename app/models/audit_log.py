import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """Append-only audit trail of AI decisions and KPI changes.

    Rows are only ever inserted — never updated or deleted. There is no
    mutation API surface; the log is written internally at service/router
    choke points via `app.services.audit_service.record_audit`.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Null actor = system/automated principal (agents, AI decisions).
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # executive | manager | analyst | system
    actor_role: Mapped[str | None] = mapped_column(String, nullable=True)

    # Dotted taxonomy, e.g. kpi.certified | kpi.created | decision.approved
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # kpi | decision
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    # Human-readable one-liner shown in the audit viewer
    summary: Mapped[str | None] = mapped_column(String, nullable=True)

    # Structured before/after payload (e.g. {"kpi_id": ..., "reason": ...})
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
