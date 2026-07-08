import uuid
from datetime import datetime

from pydantic import BaseModel


class InsightGuidanceResponse(BaseModel):
    id: uuid.UUID
    guidance_text: str
    feedback_count_considered: int
    period_start: datetime | None
    period_end: datetime | None
    model_used: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
