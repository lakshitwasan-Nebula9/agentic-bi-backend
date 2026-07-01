import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, computed_field


class ApprovalRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    current_stage: str
    status: str
    priority: int
    assigned_role: str
    assigned_to: uuid.UUID | None
    sla_deadline: datetime
    resolved_at: datetime | None
    resolved_by: uuid.UUID | None
    resolution_note: str | None
    created_at: datetime

    @computed_field
    @property
    def is_overdue(self) -> bool:
        now = datetime.now(UTC)
        deadline = self.sla_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return self.status == "pending" and deadline < now


class ApprovalActionRequest(BaseModel):
    note: str | None = None


class ApprovalRejectRequest(BaseModel):
    rejection_reason: str
