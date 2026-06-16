import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.kpi import (
    KPICertifyRequest,
    KPIRejectRequest,
    KPIResponse,
    KPISnapshotResponse,
    KPIUpdate,
)
from app.services import kpi_service
from app.services.kpi_calculation_service import recompute_snapshot

router = APIRouter(tags=["kpis"])


@router.get("/kpis", response_model=list[KPIResponse])
def list_kpis(
    dataset_id: uuid.UUID | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    return kpi_service.list_kpis(db, dataset_id=dataset_id, status=status)


@router.get("/kpis/{kpi_id}", response_model=KPIResponse)
def get_kpi(kpi_id: uuid.UUID, db: Session = Depends(get_db)):
    return kpi_service.get_kpi(db, kpi_id)


@router.put("/kpis/{kpi_id}", response_model=KPIResponse)
def update_kpi(kpi_id: uuid.UUID, updates: KPIUpdate, db: Session = Depends(get_db)):
    return kpi_service.update_kpi(db, kpi_id, updates)


@router.post("/kpis/{kpi_id}/certify", response_model=KPIResponse)
def certify_kpi(kpi_id: uuid.UUID, req: KPICertifyRequest, db: Session = Depends(get_db)):
    return kpi_service.certify_kpi(db, kpi_id, req)


@router.post("/kpis/{kpi_id}/reject", response_model=KPIResponse)
def reject_kpi(kpi_id: uuid.UUID, req: KPIRejectRequest, db: Session = Depends(get_db)):
    return kpi_service.reject_kpi(db, kpi_id, req)


@router.get("/kpis/{kpi_id}/snapshots", response_model=list[KPISnapshotResponse])
def list_snapshots(kpi_id: uuid.UUID, limit: int = 100, db: Session = Depends(get_db)):
    return kpi_service.list_snapshots(db, kpi_id, limit=limit)


@router.post("/kpis/{kpi_id}/recompute", response_model=KPISnapshotResponse)
def recompute_kpi_snapshot(kpi_id: uuid.UUID, db: Session = Depends(get_db)):
    """Recompute and snapshot the KPI value. Called when the underlying dataset is refreshed."""
    return recompute_snapshot(db, kpi_id)


@router.post("/datasets/{dataset_id}/kpis/generate", response_model=list[uuid.UUID])
async def generate_kpis(dataset_id: uuid.UUID, db: Session = Depends(get_db)):
    """HTTP trigger for KPI generation — same logic as Redis path, no broker required."""
    from app.agents.kpi_agent import generate_kpis_for_dataset

    return await generate_kpis_for_dataset(db, dataset_id)
