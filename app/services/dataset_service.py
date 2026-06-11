import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.crud import dataset as dataset_crud
from app.models.dataset import Dataset, DatasetRecord
from app.schemas.dataset import DatasetCreate
from app.services import connector_service
from app.services.connector_service import get_connector_or_404

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


def sync_dataset(db: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = get_dataset_or_404(db, dataset_id)
    connector = get_connector_or_404(db, dataset.connector_id)

    try:
        rows = connector_service.extract_rows(connector, dataset.source_query)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to run dataset query: {exc}",
        ) from exc

    jsonable_rows = [_jsonable_row(row) for row in rows]
    dataset_crud.replace_dataset_records(db, dataset_id, jsonable_rows)

    return dataset_crud.mark_synced(
        db,
        dataset,
        row_count=len(jsonable_rows),
        schema_fingerprint=_schema_fingerprint(jsonable_rows),
        synced_at=datetime.now(UTC),
    )
