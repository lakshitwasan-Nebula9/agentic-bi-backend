import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConnectorCreate(BaseModel):
    name: str
    connector_type: str = "postgres"
    host: str
    port: int = 5432
    database_name: str
    username: str
    password: str
    extra_config: dict | None = None


class ConnectorUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    password: str | None = None
    extra_config: dict | None = None
    is_active: bool | None = None


class ConnectorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    connector_type: str
    host: str
    port: int
    database_name: str
    username: str
    extra_config: dict | None
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    is_deleted: bool = False
    deleted_at: datetime | None = None

    table_count: int | None = None
    kpi_count: int | None = None
    quality_score: float | None = None


class ArchivedConnectorResponse(BaseModel):
    """A soft-deleted connector still within the 7-day restore window."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    connector_type: str
    deleted_at: datetime
    expires_at: datetime
    kpi_count: int
    table_count: int


class ConnectorDashboardResponse(BaseModel):
    """A dashboard that references this connector's KPIs (via its widgets)."""

    id: uuid.UUID
    name: str
    description: str | None = None
    widget_count: int
    kpi_count: int
    updated_at: datetime


class ConnectorDatasetSyncResult(BaseModel):
    """Outcome of syncing one dataset during a connector-wide sync."""

    dataset_id: uuid.UUID
    dataset_name: str
    status: str = Field(description='"success", "warning" (quality low), or "error"')
    row_count: int = 0
    quality_score: float | None = None
    message: str | None = None


class ConnectorSyncResult(BaseModel):
    """Aggregate result of syncing every dataset under a connector."""

    datasets_total: int
    datasets_synced: int
    datasets_failed: int
    total_rows: int
    kpi_generation_triggered: int = Field(
        description="Number of datasets that queued first-time KPI generation"
    )
    results: list[ConnectorDatasetSyncResult] = []


class ConnectionTestResult(BaseModel):
    success: bool
    message: str = Field(description="Human-readable result of the connection attempt")


class ConnectionTestRequest(BaseModel):
    host: str
    port: int = 5432
    database_name: str
    username: str
    password: str
    connector_type: str = "postgres"


class TableInfo(BaseModel):
    table_name: str
    table_type: str
    row_estimate: int | None = None


class ColumnInfo(BaseModel):
    column_name: str
    data_type: str
    is_nullable: bool
    column_default: str | None = None
