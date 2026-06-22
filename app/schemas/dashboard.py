import uuid
from datetime import datetime

from pydantic import BaseModel


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
    is_default: bool = False


class DashboardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_default: bool | None = None


class DashboardResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DashboardDetailResponse(DashboardResponse):
    widgets: list[WidgetResponse] = []
