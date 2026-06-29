import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InsightExplanationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    insight_event_id: uuid.UUID
    kpi_id: uuid.UUID
    confidence_score: int
    confidence_breakdown: dict | None = None
    source_dataset: str | None = None
    data_freshness_at: datetime | None = None
    kpi_formula: str | None = None
    llm_explanation: str | None = None
    business_drivers: list | None = None
    recommended_actions: list | None = None
    # Passthrough of the insight narrative so the modal can render everything in one call.
    rationale: str | None = None
    created_at: datetime
