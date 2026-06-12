from pydantic import BaseModel


class QualityScorecardResponse(BaseModel):
    completeness: float
    consistency: float
    recency: float
    overall_score: float
    status_label: str
    should_quarantine: bool
    null_rate: dict[str, float]
    type_issues: list[str]
    row_count: int
    column_count: int
    checked_at: str

    model_config = {"from_attributes": True}
