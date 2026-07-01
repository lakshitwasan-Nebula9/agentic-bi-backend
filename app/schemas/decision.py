import uuid
from datetime import datetime

from pydantic import BaseModel


class DecisionRecordResponse(BaseModel):
    id: uuid.UUID
    insight_event_id: uuid.UUID
    kpi_id: uuid.UUID

    # Deterministic fields
    priority: str
    recommended_owner_role: str
    sla_hours: int
    suggested_due_date: datetime
    requires_approval: bool

    # LLM output (nullable — best-effort)
    action_type: str | None = None
    decision_type: str | None = None
    llm_rationale: str | None = None
    llm_action_summary: str | None = None
    llm_business_impact: str | None = None
    llm_confidence: float | None = None
    decided_at: datetime | None = None

    # Lifecycle
    status: str
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    actioned_at: datetime | None = None

    created_at: datetime

    model_config = {"from_attributes": True}


class DecisionRejectRequest(BaseModel):
    reason: str
