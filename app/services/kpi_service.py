import logging
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.crud import kpi as kpi_crud
from app.models.connector import DataConnector
from app.models.dataset import Dataset
from app.models.kpi import KPIDefinition, KPISnapshot
from app.schemas.kpi import (
    KPICategoryResponse,
    KPICertifyRequest,
    KPIManualCreate,
    KPIRejectRequest,
    KPIResponse,
    KPIUpdate,
)

logger = logging.getLogger(__name__)


def _get_or_404(db: Session, kpi_id: uuid.UUID) -> KPIDefinition:
    kpi = kpi_crud.get_kpi(db, kpi_id)
    if kpi is None:
        raise HTTPException(status_code=404, detail=f"KPI {kpi_id} not found")
    return kpi


def _enrich(db: Session, kpis: list[KPIDefinition]) -> list[KPIResponse]:
    """Attach current_value, mom_change_pct, and data_source_name to a batch of KPIs."""
    if not kpis:
        return []

    kpi_ids = [k.id for k in kpis]
    dataset_ids = list({k.dataset_id for k in kpis})

    # Latest 2 snapshots per KPI ordered by period_start (monthly snapshots),
    # falling back to computed_at for full-dataset snapshots where period_start is NULL.
    all_snapshots: list[KPISnapshot] = (
        db.query(KPISnapshot)
        .filter(KPISnapshot.kpi_id.in_(kpi_ids))
        .order_by(KPISnapshot.period_start.desc().nulls_last(), KPISnapshot.computed_at.desc())
        .all()
    )
    # Group by kpi_id, keep first two
    snaps_by_kpi: dict[uuid.UUID, list[float]] = {}
    for snap in all_snapshots:
        lst = snaps_by_kpi.setdefault(snap.kpi_id, [])
        if len(lst) < 2:
            lst.append(snap.value)

    # Connector names via dataset join
    datasets = db.query(Dataset).filter(Dataset.id.in_(dataset_ids)).all()
    connector_ids = list({d.connector_id for d in datasets})
    connectors = db.query(DataConnector).filter(DataConnector.id.in_(connector_ids)).all()
    connector_by_id = {c.id: c.name for c in connectors}
    source_by_dataset = {d.id: connector_by_id.get(d.connector_id) for d in datasets}

    results: list[KPIResponse] = []
    for kpi in kpis:
        r = KPIResponse.model_validate(kpi)
        vals = snaps_by_kpi.get(kpi.id, [])
        if vals:
            r.current_value = vals[0]
            if len(vals) == 2 and vals[1] != 0:
                r.mom_change_pct = round((vals[0] - vals[1]) / vals[1] * 100, 2)
        r.data_source_name = source_by_dataset.get(kpi.dataset_id)
        results.append(r)
    return results


def get_kpi(db: Session, kpi_id: uuid.UUID) -> KPIResponse:
    kpi = _get_or_404(db, kpi_id)
    return _enrich(db, [kpi])[0]


def list_kpis(
    db: Session,
    dataset_id: uuid.UUID | None = None,
    status: str | None = None,
    category: str | None = None,
) -> list[KPIResponse]:
    kpis = kpi_crud.list_kpis(db, dataset_id=dataset_id, status=status, category=category)
    return _enrich(db, kpis)


def list_categories(db: Session) -> list[KPICategoryResponse]:
    names = kpi_crud.list_categories(db)
    return [KPICategoryResponse(id=name, name=name) for name in names]


def update_kpi(db: Session, kpi_id: uuid.UUID, updates: KPIUpdate) -> KPIResponse:
    kpi = _get_or_404(db, kpi_id)
    updated = kpi_crud.update_kpi(db, kpi, updates)
    return _enrich(db, [updated])[0]


def certify_kpi(db: Session, kpi_id: uuid.UUID, req: KPICertifyRequest) -> KPIResponse:
    kpi = _get_or_404(db, kpi_id)
    try:
        updated = kpi_crud.certify_kpi(db, kpi, req.certified_by)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _enrich(db, [updated])[0]


def reject_kpi(db: Session, kpi_id: uuid.UUID, req: KPIRejectRequest) -> KPIResponse:
    kpi = _get_or_404(db, kpi_id)
    try:
        updated = kpi_crud.reject_kpi(db, kpi, req.rejected_by, req.rejection_reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _enrich(db, [updated])[0]


def list_snapshots(db: Session, kpi_id: uuid.UUID, limit: int = 100) -> list[KPISnapshot]:
    _get_or_404(db, kpi_id)
    return kpi_crud.list_snapshots(db, kpi_id, limit=limit)


def delete_kpi(db: Session, kpi_id: uuid.UUID) -> None:
    kpi = _get_or_404(db, kpi_id)
    try:
        kpi_crud.delete_kpi(db, kpi)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_manual_kpi(db: Session, req: KPIManualCreate) -> KPIDefinition:
    """Create a KPI from the 'Add New KPI' form. Returns the ORM object so the router can create an AR."""
    from app.schemas.kpi import KPICreate
    from app.services.kpi_calculation_service import snapshot_kpi

    dataset = db.get(Dataset, req.dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset {req.dataset_id} not found")
    kpi_create = KPICreate(
        dataset_id=req.dataset_id,
        table_name=dataset.name,
        name=req.name,
        display_name=req.name,
        description=req.description or "",
        category=req.category,
        formula=req.sql_expression,
        sql_expression=req.sql_expression,
        direction="up_is_good",
        owner_name=req.owner_name,
    )
    kpi = kpi_crud.create_kpi(db, kpi_create)
    try:
        snapshot_kpi(db, kpi)
    except Exception:
        logger.warning("Snapshot failed for manual KPI %s (%s)", kpi.id, kpi.name, exc_info=True)
    return kpi


def regen_kpi(db: Session, kpi_id: uuid.UUID) -> KPIDefinition:
    """Reset a KPI to pending_review so a new approval cycle can begin."""
    kpi = _get_or_404(db, kpi_id)
    if kpi.status == "pending_review":
        return kpi
    try:
        return kpi_crud.reset_to_pending_review(db, kpi)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
