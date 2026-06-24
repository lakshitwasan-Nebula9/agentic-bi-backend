import logging
import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.agents.messaging import AgentPublisher
from app.crud import dataset as dataset_crud
from app.crud import sync_log as sync_log_crud
from app.models.dataset import Dataset, DatasetRecord
from app.models.sync_log import SyncLog
from app.schemas.dataset import DatasetCreate
from app.services import connector_service
from app.services.connector_service import get_connector_or_404

logger = logging.getLogger(__name__)

PREVIEW_ROW_LIMIT = 50


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _jsonable_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _to_jsonable(value) for key, value in row.items()}


def _schema_fingerprint(rows: list[dict[str, Any]]) -> dict[str, str]:
    if not rows:
        return {}
    return {column: type(value).__name__ for column, value in rows[0].items()}


def get_dataset_or_404(db: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = dataset_crud.get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


def list_datasets(db: Session) -> list[Dataset]:
    return dataset_crud.list_datasets(db)


def create_dataset(db: Session, payload: DatasetCreate, created_by: uuid.UUID) -> Dataset:
    if dataset_crud.get_dataset_by_name(db, payload.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A dataset with this name already exists",
        )

    get_connector_or_404(db, payload.connector_id)

    dataset = Dataset(
        connector_id=payload.connector_id,
        name=payload.name,
        source_query=payload.source_query,
        created_by=created_by,
    )
    return dataset_crud.create_dataset(db, dataset)


def delete_dataset(db: Session, dataset_id: uuid.UUID) -> None:
    dataset = get_dataset_or_404(db, dataset_id)
    dataset_crud.delete_dataset(db, dataset)


def list_records(
    db: Session, dataset_id: uuid.UUID, limit: int = 100, offset: int = 0
) -> list[DatasetRecord]:
    get_dataset_or_404(db, dataset_id)
    return dataset_crud.list_dataset_records(db, dataset_id, limit=limit, offset=offset)


def preview_dataset(db: Session, dataset_id: uuid.UUID) -> tuple[list[str], list[dict[str, Any]]]:
    dataset = get_dataset_or_404(db, dataset_id)
    connector = get_connector_or_404(db, dataset.connector_id)

    preview_query = (
        f"SELECT * FROM ({dataset.source_query}) AS dataset_preview LIMIT {PREVIEW_ROW_LIMIT}"
    )

    try:
        rows = connector_service.extract_rows(connector, preview_query)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to run dataset query: {exc}",
        ) from exc

    jsonable_rows = [_jsonable_row(row) for row in rows]
    columns = list(jsonable_rows[0].keys()) if jsonable_rows else []
    return columns, jsonable_rows


def sync_dataset(
    db: Session,
    dataset_id: uuid.UUID,
    triggered_by: uuid.UUID | None = None,
) -> Dataset:
    dataset = get_dataset_or_404(db, dataset_id)
    connector = get_connector_or_404(db, dataset.connector_id)
    sync_type = "incremental" if dataset.last_synced_at is not None else "full"
    start_ms = time.monotonic()

    try:
        rows = connector_service.extract_rows(connector, dataset.source_query)
    except Exception as exc:
        _write_sync_log(
            db,
            connector_id=dataset.connector_id,
            dataset_id=dataset_id,
            dataset_name=dataset.name,
            sync_type=sync_type,
            status="error",
            message=f"Sync failed — {exc}",
            rows_synced=0,
            duration_ms=int((time.monotonic() - start_ms) * 1000),
            triggered_by=triggered_by,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to run dataset query: {exc}",
        ) from exc

    jsonable_rows = [_jsonable_row(row) for row in rows]
    dataset_crud.replace_dataset_records(db, dataset_id, jsonable_rows)

    updated = dataset_crud.mark_synced(
        db,
        dataset,
        row_count=len(jsonable_rows),
        schema_fingerprint=_schema_fingerprint(jsonable_rows),
        synced_at=datetime.now(UTC),
    )

    # Run quality pipeline to score data and set dataset.status / quality_score
    quality_passed = True
    try:
        from app.services.data_quality_service import run_quality_pipeline

        scorecard = run_quality_pipeline(db, dataset_id)
        db.refresh(updated)
        quality_passed = not scorecard.should_quarantine
    except Exception:
        logger.warning(
            "Quality pipeline failed for dataset %s — treating as passed", dataset_id, exc_info=True
        )

    duration_ms = int((time.monotonic() - start_ms) * 1000)
    sync_status = "warning" if not quality_passed else "success"
    score = updated.quality_score
    if not quality_passed and score is not None:
        msg = f"{sync_type.capitalize()} sync completed — quality score low ({score:.0f}%)"
    else:
        msg = f"{sync_type.capitalize()} sync completed — {len(jsonable_rows):,} rows loaded"

    _write_sync_log(
        db,
        connector_id=dataset.connector_id,
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        sync_type=sync_type,
        status=sync_status,
        message=msg,
        rows_synced=len(jsonable_rows),
        duration_ms=duration_ms,
        triggered_by=triggered_by,
    )

    event_type = "dataset_quality_passed" if quality_passed else "dataset_synced"
    try:
        AgentPublisher().publish(event_type, {"dataset_id": str(dataset_id)})
    except Exception:
        pass

    return updated


def _write_sync_log(
    db: Session,
    *,
    connector_id: uuid.UUID,
    dataset_id: uuid.UUID | None,
    dataset_name: str | None,
    sync_type: str,
    status: str,
    message: str,
    rows_synced: int,
    duration_ms: int | None,
    triggered_by: uuid.UUID | None,
) -> None:
    try:
        log = SyncLog(
            connector_id=connector_id,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            sync_type=sync_type,
            status=status,
            message=message,
            tables_updated=1,
            rows_synced=rows_synced,
            duration_ms=duration_ms,
            triggered_by=triggered_by,
        )
        sync_log_crud.create_sync_log(db, log)
    except Exception:
        logger.warning("Failed to write sync log for dataset %s", dataset_id, exc_info=True)
