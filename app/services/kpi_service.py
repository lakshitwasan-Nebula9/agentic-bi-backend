import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.crud import kpi as kpi_crud
from app.models.kpi import KPIDefinition, KPISnapshot
from app.schemas.kpi import KPICertifyRequest, KPIRejectRequest, KPIUpdate


def _get_or_404(db: Session, kpi_id: uuid.UUID) -> KPIDefinition:
    kpi = kpi_crud.get_kpi(db, kpi_id)
    if kpi is None:
        raise HTTPException(status_code=404, detail=f"KPI {kpi_id} not found")
    return kpi


def get_kpi(db: Session, kpi_id: uuid.UUID) -> KPIDefinition:
    return _get_or_404(db, kpi_id)


def list_kpis(
    db: Session,
    dataset_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[KPIDefinition]:
    return kpi_crud.list_kpis(db, dataset_id=dataset_id, status=status)


def update_kpi(db: Session, kpi_id: uuid.UUID, updates: KPIUpdate) -> KPIDefinition:
    kpi = _get_or_404(db, kpi_id)
    return kpi_crud.update_kpi(db, kpi, updates)


def certify_kpi(db: Session, kpi_id: uuid.UUID, req: KPICertifyRequest) -> KPIDefinition:
    kpi = _get_or_404(db, kpi_id)
    try:
        return kpi_crud.certify_kpi(db, kpi, req.certified_by)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def reject_kpi(db: Session, kpi_id: uuid.UUID, req: KPIRejectRequest) -> KPIDefinition:
    kpi = _get_or_404(db, kpi_id)
    try:
        return kpi_crud.reject_kpi(db, kpi, req.rejected_by, req.rejection_reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def list_snapshots(db: Session, kpi_id: uuid.UUID, limit: int = 100) -> list[KPISnapshot]:
    _get_or_404(db, kpi_id)
    return kpi_crud.list_snapshots(db, kpi_id, limit=limit)
