import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
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

logger = logging.getLogger(__name__)


async def _auto_generate_kpis(dataset_id: uuid.UUID) -> None:
    """Background task: run KPI generation for a newly-synced dataset."""
    from app.agents.kpi_agent import generate_kpis_for_dataset
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        await generate_kpis_for_dataset(db, dataset_id)
        logger.info("Auto KPI generation complete for dataset %s", dataset_id)
    except Exception:
        logger.warning("Auto KPI generation failed for dataset %s", dataset_id, exc_info=True)
    finally:
        db.close()


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
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dataset_service.list_datasets(db, include_deleted=include_deleted)


@router.get("/{dataset_id}", response_model=DatasetResponse)
def get_dataset(
    dataset_id: uuid.UUID,
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dataset_service.get_dataset_or_404(db, dataset_id, include_deleted=include_deleted)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    dataset_service.delete_dataset(db, dataset_id)


@router.post("/{dataset_id}/restore", response_model=DatasetResponse)
def restore_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    return dataset_service.restore_dataset(db, dataset_id)


@router.get("/{dataset_id}/preview", response_model=DatasetPreviewResult)
def preview_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    columns, rows = dataset_service.preview_dataset(db, dataset_id)
    return DatasetPreviewResult(columns=columns, rows=rows)


@router.post("/{dataset_id}/sync", response_model=DatasetSyncResult)
async def sync_dataset(
    dataset_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    # Capture whether this is the first sync before data is written
    existing = dataset_service.get_dataset_or_404(db, dataset_id)
    is_first_sync = existing.last_synced_at is None

    dataset = dataset_service.sync_dataset(db, dataset_id, triggered_by=current_user.id)

    # Auto-trigger KPI generation: first sync only, quality must have passed
    kpi_triggered = False
    if is_first_sync and dataset.status != "quarantined":
        from app.crud import kpi as kpi_crud

        if not kpi_crud.list_kpis(db, dataset_id=dataset_id):
            background_tasks.add_task(_auto_generate_kpis, dataset_id)
            kpi_triggered = True
            logger.info("Queued auto KPI generation for dataset %s", dataset_id)

    return DatasetSyncResult(
        row_count=dataset.row_count,
        schema_fingerprint=dataset.schema_fingerprint or {},
        synced_at=dataset.last_synced_at,
        quality_score=dataset.quality_score,
        kpi_generation_triggered=kpi_triggered,
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
