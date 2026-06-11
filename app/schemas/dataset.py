import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DatasetCreate(BaseModel):
    name: str
    connector_id: uuid.UUID
    source_query: str


class DatasetResponse(BaseModel):
    id: uuid.UUID
    connector_id: uuid.UUID
    name: str
    source_query: str
    schema_fingerprint: dict | None
    row_count: int
    status: str
    last_synced_at: datetime | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DatasetPreviewResult(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]


class DatasetSyncResult(BaseModel):
    row_count: int
    schema_fingerprint: dict
    synced_at: datetime


class DatasetRecordResponse(BaseModel):
    id: uuid.UUID
    row_data: dict[str, Any]
    ingested_at: datetime

    class Config:
        from_attributes = True
