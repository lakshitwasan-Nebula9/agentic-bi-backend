import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    summary: str | None
    details: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
