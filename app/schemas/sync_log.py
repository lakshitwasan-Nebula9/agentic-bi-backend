import uuid
from datetime import datetime

from pydantic import BaseModel


class SyncLogResponse(BaseModel):
    id: uuid.UUID
    connector_id: uuid.UUID
    dataset_id: uuid.UUID | None
    dataset_name: str | None
    sync_type: str
    status: str
    message: str
    tables_updated: int
    rows_synced: int
    duration_ms: int | None
    triggered_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
