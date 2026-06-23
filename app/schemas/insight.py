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
    created_at: datetime

    model_config = {"from_attributes": True}
