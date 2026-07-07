import uuid
from datetime import datetime

from pydantic import BaseModel


class InsightEventResponse(BaseModel):
    id: uuid.UUID
    kpi_id: uuid.UUID
    period_start: datetime
    value: float
    z_score: float | None
    baseline_mean: float | None
    baseline_std: float | None
    rolling_avg_3m: float | None
    rolling_avg_6m: float | None
    trend_slope: float | None
    insight_type: str
    is_anomaly: bool

    # GenAI narrative layer (best-effort; null when the LLM is disabled or failed)
    llm_title: str | None = None
    llm_category: str | None = None
    llm_severity: str | None = None
    llm_summary: str | None = None
    narrated_at: datetime | None = None

    is_suppressed: bool = False
    suppression_score: float | None = None

    created_at: datetime

    model_config = {"from_attributes": True}
