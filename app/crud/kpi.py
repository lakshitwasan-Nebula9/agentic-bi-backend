import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.kpi import KPIDefinition, KPISnapshot, KPIVersion
from app.schemas.kpi import KPICreate, KPIUpdate

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_review"},
    "pending_review": {"certified", "rejected"},
    "certified": {"rejected", "pending_review"},
    "rejected": {"pending_review"},
}


def create_kpi(db: Session, kpi: KPICreate) -> KPIDefinition:
    record = KPIDefinition(
        dataset_id=kpi.dataset_id,
        table_name=kpi.table_name,
        name=kpi.name,
        display_name=kpi.display_name,
        description=kpi.description,
        category=kpi.category,
        formula=kpi.formula,
        sql_expression=kpi.sql_expression,
        unit=kpi.unit,
        direction=kpi.direction,
        suggested_chart=kpi.suggested_chart_type,
        owner_id=kpi.owner_id,
        owner_name=kpi.owner_name,
        owner_role=kpi.owner_role,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_kpi(db: Session, kpi_id: uuid.UUID) -> KPIDefinition | None:
    return db.get(KPIDefinition, kpi_id)


def list_kpis(
    db: Session,
    dataset_id: uuid.UUID | None = None,
    status: str | None = None,
    category: str | None = None,
) -> list[KPIDefinition]:
    q = db.query(KPIDefinition)
    if dataset_id is not None:
        q = q.filter(KPIDefinition.dataset_id == dataset_id)
    if status is not None:
        q = q.filter(KPIDefinition.status == status)
    if category is not None:
        q = q.filter(KPIDefinition.category == category)
    return q.order_by(KPIDefinition.created_at.desc()).all()


def list_categories(db: Session) -> list[str]:
    rows = db.query(KPIDefinition.category).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


def update_kpi(db: Session, kpi: KPIDefinition, updates: KPIUpdate) -> KPIDefinition:
    _snapshot_version(db, kpi, changed_by=None, reason="analyst_edit")
    for field, value in updates.model_dump(exclude_none=True).items():
        setattr(kpi, field, value)
    kpi.version += 1
    db.commit()
    db.refresh(kpi)
    return kpi


def certify_kpi(db: Session, kpi: KPIDefinition, certified_by: uuid.UUID) -> KPIDefinition:
    _assert_transition(kpi, "certified")
    _snapshot_version(db, kpi, changed_by=certified_by, reason="certified")
    kpi.status = "certified"
    kpi.certified_by = certified_by
    kpi.certified_at = datetime.utcnow()
    kpi.version += 1
    db.commit()
    db.refresh(kpi)
    return kpi


def delete_kpi(db: Session, kpi: KPIDefinition) -> None:
    if kpi.status not in {"draft", "rejected"}:
        raise ValueError(
            f"Cannot delete a KPI with status '{kpi.status}'. Only draft or rejected KPIs can be deleted."
        )
    db.delete(kpi)
    db.commit()


def reset_to_pending_review(db: Session, kpi: KPIDefinition) -> KPIDefinition:
    _assert_transition(kpi, "pending_review")
    _snapshot_version(db, kpi, changed_by=None, reason="regen_requested")
    kpi.status = "pending_review"
    kpi.version += 1
    db.commit()
    db.refresh(kpi)
    return kpi


def reject_kpi(
    db: Session, kpi: KPIDefinition, rejected_by: uuid.UUID, reason: str
) -> KPIDefinition:
    _assert_transition(kpi, "rejected")
    _snapshot_version(db, kpi, changed_by=rejected_by, reason=f"rejected: {reason}")
    kpi.status = "rejected"
    kpi.rejection_reason = reason
    kpi.version += 1
    db.commit()
    db.refresh(kpi)
    return kpi


def create_snapshot(
    db: Session,
    kpi_id: uuid.UUID,
    dataset_id: uuid.UUID,
    value: float,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> KPISnapshot:
    snapshot = KPISnapshot(
        kpi_id=kpi_id,
        dataset_id=dataset_id,
        value=value,
        period_start=period_start,
        period_end=period_end,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def list_snapshots(db: Session, kpi_id: uuid.UUID, limit: int = 100) -> list[KPISnapshot]:
    return (
        db.query(KPISnapshot)
        .filter(KPISnapshot.kpi_id == kpi_id)
        .order_by(KPISnapshot.period_start.asc().nulls_last(), KPISnapshot.computed_at.asc())
        .limit(limit)
        .all()
    )


def _snapshot_version(
    db: Session, kpi: KPIDefinition, changed_by: uuid.UUID | None, reason: str | None
) -> KPIVersion:
    version_record = KPIVersion(
        kpi_id=kpi.id,
        version=kpi.version,
        name=kpi.name,
        formula=kpi.formula,
        sql_expression=kpi.sql_expression,
        status=kpi.status,
        changed_by=changed_by,
        change_reason=reason,
    )
    db.add(version_record)
    return version_record


def _assert_transition(kpi: KPIDefinition, target_status: str) -> None:
    allowed = _VALID_TRANSITIONS.get(kpi.status, set())
    if target_status not in allowed:
        raise ValueError(
            f"Cannot transition KPI from '{kpi.status}' to '{target_status}'. "
            f"Allowed: {sorted(allowed) or 'none'}"
        )
