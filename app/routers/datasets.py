import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.user import User, UserRole
from app.schemas.dataset import (
    DatasetCreate,
    DatasetPreviewResult,
    DatasetRecordResponse,
    DatasetResponse,
    DatasetSyncResult,
)
from app.services import dataset_service

router = APIRouter(prefix="/datasets", tags=["datasets"])

MANAGE_ROLES = (UserRole.ANALYST, UserRole.MANAGER, UserRole.EXECUTIVE)


@router.post("", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
def create_dataset(
    payload: DatasetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    return dataset_service.create_dataset(db, payload, created_by=current_user.id)


@router.get("", response_model=list[DatasetResponse])
def list_datasets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dataset_service.list_datasets(db)


@router.get("/{dataset_id}", response_model=DatasetResponse)
def get_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dataset_service.get_dataset_or_404(db, dataset_id)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    dataset_service.delete_dataset(db, dataset_id)


@router.get("/{dataset_id}/preview", response_model=DatasetPreviewResult)
def preview_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    columns, rows = dataset_service.preview_dataset(db, dataset_id)
    return DatasetPreviewResult(columns=columns, rows=rows)


@router.post("/{dataset_id}/sync", response_model=DatasetSyncResult)
def sync_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    dataset = dataset_service.sync_dataset(db, dataset_id)
    return DatasetSyncResult(
        row_count=dataset.row_count,
        schema_fingerprint=dataset.schema_fingerprint or {},
        synced_at=dataset.last_synced_at,
    )


@router.get("/{dataset_id}/records", response_model=list[DatasetRecordResponse])
def list_dataset_records(
    dataset_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dataset_service.list_records(db, dataset_id, limit=limit, offset=offset)
