import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class InsightFeedbackCreate(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=2000)


class InsightFeedbackResponse(BaseModel):
    id: uuid.UUID
    insight_id: uuid.UUID
    user_id: uuid.UUID
    rating: str
    comment: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InsightFeedbackSummary(BaseModel):
    insight_id: uuid.UUID
    thumbs_up: int
    thumbs_down: int
    my_feedback: InsightFeedbackResponse | None = None
