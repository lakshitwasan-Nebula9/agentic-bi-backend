import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Screen context — sent by the frontend on every message
# ---------------------------------------------------------------------------


class ScreenContext(BaseModel):
    current_page: str | None = None
    dashboard_id: uuid.UUID | None = None
    widget_id: uuid.UUID | None = None  # the specific widget the user clicked / is focused on
    kpi_id: uuid.UUID | None = None
    insight_id: uuid.UUID | None = None
    report_id: uuid.UUID | None = None
    decision_id: uuid.UUID | None = None
    # All KPI widget IDs currently rendered on the user's dashboard layout
    visible_kpi_ids: list[uuid.UUID] | None = None
    # Insight IDs visible in the left panel
    visible_insight_ids: list[uuid.UUID] | None = None


# ---------------------------------------------------------------------------
# Source reference — links in assistant responses back to platform objects
# ---------------------------------------------------------------------------


class SourceReference(BaseModel):
    type: str  # "kpi" | "insight" | "decision" | "report" | "dashboard" | "connector"
    id: str
    name: str | None = None
    route: str | None = None  # frontend navigation route e.g. "/kpis/uuid"


class SuggestedAction(BaseModel):
    label: str
    route: str


# ---------------------------------------------------------------------------
# Request / Response
# ---------------------------------------------------------------------------


class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    screen_context: ScreenContext | None = None


class SendMessageResponse(BaseModel):
    session_id: uuid.UUID
    message_id: uuid.UUID
    response: str
    intent: str
    source_references: list[SourceReference] = []
    suggested_actions: list[SuggestedAction] = []
    sql_generated: str | None = None
    generation_time_ms: int | None = None


# ---------------------------------------------------------------------------
# Session schemas
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    screen_context: ScreenContext | None = None


class UpdateSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    intent: str | None
    screen_context: dict[str, Any] | None
    metadata_json: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None
    is_active: bool
    primary_dashboard_id: uuid.UUID | None = None
    primary_dashboard_name: str | None = None
    created_at: datetime
    updated_at: datetime
    last_message_preview: str | None = None

    model_config = {"from_attributes": True}


class ChatSessionDetailResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageResponse] = []

    model_config = {"from_attributes": True}
