import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KPICreate(BaseModel):
    dataset_id: uuid.UUID
    table_name: str
    name: str
    display_name: str
    description: str
    category: str
    formula: str
    sql_expression: str
    unit: str | None = None
    direction: str
    suggested_chart_type: str | None = None
    owner_id: uuid.UUID | None = None
    owner_name: str | None = None
    owner_role: str | None = None


class KPIUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    formula: str | None = None
    sql_expression: str | None = None
    unit: str | None = None
    direction: str | None = None
    owner_id: uuid.UUID | None = None
    owner_name: str | None = None
    owner_role: str | None = None


class KPICertifyRequest(BaseModel):
    certified_by: uuid.UUID


class KPIRejectRequest(BaseModel):
    rejection_reason: str
    rejected_by: uuid.UUID


class KPISnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kpi_id: uuid.UUID
    dataset_id: uuid.UUID
    value: float
    period_start: datetime | None
    period_end: datetime | None
    computed_at: datetime


class KPIResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    table_name: str
    name: str
    display_name: str
    description: str
    category: str
    formula: str
    sql_expression: str
    unit: str | None
    direction: str
    suggested_chart: str | None
    status: str
    version: int
    owner_id: uuid.UUID | None
    owner_name: str | None
    owner_role: str | None
    created_at: datetime
    certified_at: datetime | None
    rejection_reason: str | None
