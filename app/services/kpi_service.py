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


def _is_sum_metric(sql_expression: str) -> bool:
    return sql_expression.strip().upper().startswith("SUM(")


def _enrich(db: Session, kpis: list[KPIDefinition]) -> list[KPIResponse]:
    """Attach current_value, MoM, YoY, QoQ, YTD, and data_source_name to a batch of KPIs."""
    if not kpis:
        return []

    kpi_ids = [k.id for k in kpis]
    dataset_ids = list({k.dataset_id for k in kpis})

    # All snapshots for the batch, newest first.
    all_snapshots: list[KPISnapshot] = (
        db.query(KPISnapshot)
        .filter(KPISnapshot.kpi_id.in_(kpi_ids))
        .order_by(KPISnapshot.period_start.desc().nulls_last(), KPISnapshot.computed_at.desc())
        .all()
    )

    # Group full snapshot objects by kpi_id (newest first, preserving query order).
    snaps_by_kpi: dict[uuid.UUID, list[KPISnapshot]] = {}
    for snap in all_snapshots:
        snaps_by_kpi.setdefault(snap.kpi_id, []).append(snap)

    # Period map for time intelligence: kpi_id → {(year, month): value}.
    # Only monthly snapshots (period_start is not None) are included.
    period_map_by_kpi: dict[uuid.UUID, dict[tuple[int, int], float]] = {}
    for snap in all_snapshots:
        if snap.period_start is not None:
            ym = (snap.period_start.year, snap.period_start.month)
            period_map_by_kpi.setdefault(snap.kpi_id, {})[ym] = snap.value

    # Connector names via dataset join
    datasets = db.query(Dataset).filter(Dataset.id.in_(dataset_ids)).all()
    connector_ids = list({d.connector_id for d in datasets})
    connectors = db.query(DataConnector).filter(DataConnector.id.in_(connector_ids)).all()
    connector_by_id = {c.id: c.name for c in connectors}
    source_by_dataset = {d.id: connector_by_id.get(d.connector_id) for d in datasets}

    results: list[KPIResponse] = []
    for kpi in kpis:
        r = KPIResponse.model_validate(kpi)
        snaps = snaps_by_kpi.get(kpi.id, [])
        period_map = period_map_by_kpi.get(kpi.id, {})

        # current_value + MoM from latest 2 snapshots (full-dataset fallback included).
        vals = [s.value for s in snaps[:2]]
        if vals:
            r.current_value = vals[0]
            if len(vals) == 2 and vals[1] != 0:
                r.mom_change_pct = round((vals[0] - vals[1]) / vals[1] * 100, 2)

        r.data_source_name = source_by_dataset.get(kpi.dataset_id)

        # Time intelligence requires at least one monthly snapshot.
        current_snap = next((s for s in snaps if s.period_start is not None), None)
        if current_snap is None:
            results.append(r)
            continue

        cy, cm = current_snap.period_start.year, current_snap.period_start.month

        # YoY: same calendar month last year (needs ≥13 months of data).
        yoy_ym = (cy - 1, cm)
        if yoy_ym in period_map and period_map[yoy_ym] != 0:
            r.yoy_change_pct = round(
                (current_snap.value - period_map[yoy_ym]) / period_map[yoy_ym] * 100, 2
            )

        # QoQ: same calendar month 3 months ago (needs ≥4 months of data).
        total = cy * 12 + (cm - 1) - 3
        qoq_ym = (total // 12, total % 12 + 1)
        if qoq_ym in period_map and period_map[qoq_ym] != 0:
            r.qoq_change_pct = round(
                (current_snap.value - period_map[qoq_ym]) / period_map[qoq_ym] * 100, 2
            )

        # YTD: aggregate all monthly snapshots in the current year.
        # SUM metrics are summed; AVG/rate metrics are averaged.
        ytd_vals = [v for (yr, _), v in period_map.items() if yr == cy]
        if ytd_vals:
            r.ytd_value = round(
                (
                    sum(ytd_vals)
                    if _is_sum_metric(kpi.sql_expression)
                    else sum(ytd_vals) / len(ytd_vals)
                ),
                4,
            )

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
