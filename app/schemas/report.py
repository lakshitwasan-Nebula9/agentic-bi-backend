import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

# ---------------------------------------------------------------------------
# Nested report structure — matches the JSON stored in reports.report_json
# ---------------------------------------------------------------------------


class HeadlineMetric(BaseModel):
    label: str
    value: str  # pre-formatted, e.g. "38.7%" or "4,820"
    delta: str | None = None  # e.g. "+12.4% MoM"
    direction: str | None = None  # up | down | neutral


class ReportExecutiveSummary(BaseModel):
    narrative: str
    key_wins: list[str]
    key_risks: list[str]
    critical_actions: list[str]
    headline_metrics: list[HeadlineMetric]


class KPIScorecardItem(BaseModel):
    kpi_id: uuid.UUID
    name: str
    display_name: str
    category: str
    unit: str | None
    direction: str
    status: str  # certified | pending_review | draft
    current_value: float | None
    previous_value: float | None
    mom_change_pct: float | None = None
    qoq_change_pct: float | None = None
    yoy_change_pct: float | None = None


class InsightItem(BaseModel):
    insight_id: uuid.UUID
    kpi_id: uuid.UUID
    kpi_name: str
    kpi_display_name: str
    title: str
    description: str
    severity: str  # info | warning | critical
    confidence_score: float | None = None  # 0–100 derived from abs(z_score)
    insight_type: str  # spike | dip | trend_up | trend_down | stable
    is_anomaly: bool
    category: str  # revenue | operational | customer | financial | other
    period_start: datetime
    value: float
    baseline_mean: float | None = None
    z_score: float | None = None


class InsightSection(BaseModel):
    category: str
    display_name: str  # e.g. "Revenue Insights"
    insights: list[InsightItem]


class TimeIntelligenceItem(BaseModel):
    kpi_id: uuid.UUID
    kpi_name: str
    kpi_display_name: str
    unit: str | None
    direction: str
    latest_value: float | None = None
    trend_slope: float | None = None
    mom_change_pct: float | None = None
    rolling_avg_3m: float | None = None
    rolling_avg_6m: float | None = None


class DecisionAction(BaseModel):
    insight_id: uuid.UUID
    kpi_name: str
    action_title: str
    priority: str  # P1 | P2 | P3
    assigned_owner: str | None = None
    status: str  # pending | routed | in_progress | resolved
    severity: str  # critical | warning | info


class AppendixDataSource(BaseModel):
    dataset_id: uuid.UUID
    name: str
    connector_type: str
    quality_score: float | None
    last_synced_at: datetime | None
    row_count: int
    status: str


class ReportAppendix(BaseModel):
    data_sources: list[AppendixDataSource]
    certified_kpi_count: int
    total_insight_count: int
    anomaly_count: int
    generated_at: datetime
    methodology: str


class ReportData(BaseModel):
    report_id: uuid.UUID
    title: str
    period_label: str
    generated_at: datetime
    executive_summary: ReportExecutiveSummary
    kpi_scorecard: list[KPIScorecardItem]
    insight_sections: list[InsightSection]
    time_intelligence: list[TimeIntelligenceItem]
    decision_actions: list[DecisionAction]
    appendix: ReportAppendix


# ---------------------------------------------------------------------------
# API request / response schemas
# ---------------------------------------------------------------------------


class ReportGenerateRequest(BaseModel):
    title: str | None = None
    period_label: str | None = None
    # Optional scope. At most one may be set:
    #   dashboard_id -> report covers only that dashboard's KPIs
    #   connector_id -> report consolidates all certified KPIs of that database
    # Neither set -> global report (all certified KPIs), the historical behavior.
    dashboard_id: uuid.UUID | None = None
    connector_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_scope_at_most(self) -> "ReportGenerateRequest":
        if self.dashboard_id is not None and self.connector_id is not None:
            raise ValueError("Provide at most one of dashboard_id or connector_id, not both.")
        return self


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    period_label: str | None
    status: str
    scope: str
    dashboard_id: uuid.UUID | None
    connector_id: uuid.UUID | None
    executive_narrative: str | None
    generated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ReportDetailResponse(ReportResponse):
    report_json: dict[str, Any] | None = None
