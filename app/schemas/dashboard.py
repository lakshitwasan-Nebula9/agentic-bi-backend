import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.user import UserRole


class DashboardAccessLevel(str, enum.Enum):
    READ = "read"
    WRITE = "write"


def _normalize_category(value: str | None) -> str | None:
    """Normalize a dashboard category (trim + lower-case); '' → None.

    Categories are dynamic — they mirror the GenAI-assigned KPI categories of the
    dashboard's data source (see GET /kpis/categories), so there is no fixed
    allow-list to validate against here.
    """
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


class WidgetCreate(BaseModel):
    widget_type: str
    title: str | None = None
    config: dict | None = None
    x: int = 0
    y: int = 0
    w: int = 4
    h: int = 4


class WidgetUpdate(BaseModel):
    title: str | None = None
    config: dict | None = None
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None


class WidgetLayoutUpdate(BaseModel):
    id: uuid.UUID
    x: int
    y: int
    w: int
    h: int


class WidgetResponse(BaseModel):
    id: uuid.UUID
    dashboard_id: uuid.UUID
    widget_type: str
    title: str | None
    config: dict | None
    x: int
    y: int
    w: int
    h: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DashboardCreate(BaseModel):
    name: str
    description: str | None = None
    category: str | None = None
    is_default: bool = False
    # When set, the new dashboard is preconfigured with widgets built from this
    # connector's most recently certified KPIs. Empty → blank dashboard.
    connector_id: uuid.UUID | None = None

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str | None) -> str | None:
        return _normalize_category(v)


class DashboardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    is_default: bool | None = None

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str | None) -> str | None:
        return _normalize_category(v)


class DashboardResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    category: str | None
    is_default: bool
    created_at: datetime
    updated_at: datetime
    # Caller's effective access ("read" | "write"), attached by the service so
    # the frontend knows whether to show edit controls / the permissions panel.
    my_access: DashboardAccessLevel | None = None
    # Listing metadata attached by the service (not stored columns): how many
    # widgets / distinct KPIs the dashboard has, and its owner's display name.
    widget_count: int = 0
    kpi_count: int = 0
    owner_name: str | None = None
    # Whether the *current viewer* has pinned this dashboard (per-user, from
    # dashboard_pins) — distinct from the deprecated global is_default column.
    is_pinned: bool = False

    class Config:
        from_attributes = True


class DashboardDetailResponse(DashboardResponse):
    widgets: list[WidgetResponse] = []


class DashboardPinRequest(BaseModel):
    pinned: bool


class DashboardPermissionUpsert(BaseModel):
    access_level: DashboardAccessLevel


class DashboardPermissionResponse(BaseModel):
    id: uuid.UUID
    dashboard_id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    user_name: str | None
    user_role: UserRole
    access_level: DashboardAccessLevel
    granted_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
