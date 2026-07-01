import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_manager
from app.models.user import User
from app.schemas.kpi import (
    KPICategoryResponse,
    KPICertifyRequest,
    KPIManualCreate,
    KPIRejectRequest,
    KPIResponse,
    KPISnapshotResponse,
    KPIUpdate,
)
from app.services import hitl_workflow_service as hitl_svc
from app.services import kpi_service
from app.services.kpi_calculation_service import recompute_snapshot

router = APIRouter(tags=["kpis"])


@router.get("/kpis/categories", response_model=list[KPICategoryResponse])
def list_kpi_categories(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return distinct KPI category values so the frontend can build the tab bar dynamically."""
    return kpi_service.list_categories(db)


@router.get("/kpis", response_model=list[KPIResponse])
def list_kpis(
    dataset_id: uuid.UUID | None = None,
    status: str | None = None,
    category: str | None = None,
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return kpi_service.list_kpis(
        db,
        dataset_id=dataset_id,
        status=status,
        category=category,
        include_deleted=include_deleted,
    )


@router.post("/kpis", response_model=KPIResponse, status_code=201)
def create_kpi_manual(
    req: KPIManualCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Create a KPI from the 'Add New KPI' form and immediately queue it for executive approval."""
    kpi = kpi_service.create_manual_kpi(db, req)
    hitl_svc.create_kpi_approval(db, kpi.id)
    return kpi_service.get_kpi(db, kpi.id)


@router.get("/kpis/{kpi_id}", response_model=KPIResponse)
def get_kpi(
    kpi_id: uuid.UUID,
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return kpi_service.get_kpi(db, kpi_id, include_deleted=include_deleted)


@router.put("/kpis/{kpi_id}", response_model=KPIResponse)
def update_kpi(
    kpi_id: uuid.UUID,
    updates: KPIUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return kpi_service.update_kpi(db, kpi_id, updates)


@router.delete("/kpis/{kpi_id}", status_code=204)
def delete_kpi(
    kpi_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager),
):
    kpi_service.delete_kpi(db, kpi_id)


@router.post("/kpis/{kpi_id}/regen", response_model=KPIResponse)
def regen_kpi(
    kpi_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Reset a KPI to pending_review and open a new executive approval request."""
    kpi = kpi_service.regen_kpi(db, kpi_id)
    hitl_svc.create_kpi_approval(db, kpi.id)
    return kpi_service.get_kpi(db, kpi_id)


@router.post("/kpis/{kpi_id}/certify", response_model=KPIResponse)
def certify_kpi(
    kpi_id: uuid.UUID,
    req: KPICertifyRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager),
):
    return kpi_service.certify_kpi(db, kpi_id, req)


@router.post("/kpis/{kpi_id}/reject", response_model=KPIResponse)
def reject_kpi(
    kpi_id: uuid.UUID,
    req: KPIRejectRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager),
):
    return kpi_service.reject_kpi(db, kpi_id, req)


@router.get("/kpis/{kpi_id}/snapshots", response_model=list[KPISnapshotResponse])
def list_snapshots(
    kpi_id: uuid.UUID,
    limit: int = 100,
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return kpi_service.list_snapshots(db, kpi_id, limit=limit, include_deleted=include_deleted)


@router.post("/kpis/{kpi_id}/recompute", response_model=KPISnapshotResponse)
def recompute_kpi_snapshot(
    kpi_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Recompute and snapshot the KPI value. Called when the underlying dataset is refreshed."""
    return recompute_snapshot(db, kpi_id)


@router.post("/datasets/{dataset_id}/kpis/generate", response_model=list[uuid.UUID])
async def generate_kpis(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """HTTP trigger for KPI generation — same logic as Redis path, no broker required."""
    from app.agents.kpi_agent import generate_kpis_for_dataset

    return await generate_kpis_for_dataset(db, dataset_id)


@router.post("/datasets/{dataset_id}/kpis/recompute", response_model=list[uuid.UUID])
def recompute_kpis(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Recompute snapshots for all certified KPIs of a dataset.

    Called when the dataset is re-synced. Does not regenerate KPI definitions.
    """
    from app.agents.kpi_agent import recompute_kpis_for_dataset

    return recompute_kpis_for_dataset(db, dataset_id)
