import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.decision import DecisionRecord


def create_decision(db: Session, record: DecisionRecord) -> DecisionRecord:
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_decision(
    db: Session, decision_id: uuid.UUID, include_deleted: bool = False
) -> DecisionRecord | None:
    q = select(DecisionRecord).where(DecisionRecord.id == decision_id)
    if not include_deleted:
        q = q.where(DecisionRecord.is_deleted.is_(False))
    return db.scalars(q).first()


def get_decision_by_insight(db: Session, insight_event_id: uuid.UUID) -> DecisionRecord | None:
    stmt = select(DecisionRecord).where(
        DecisionRecord.insight_event_id == insight_event_id,
        DecisionRecord.is_deleted.is_(False),
    )
    return db.scalars(stmt).first()


def already_decided(db: Session, insight_event_id: uuid.UUID) -> bool:
    return get_decision_by_insight(db, insight_event_id) is not None


def list_decisions(
    db: Session,
    priority: str | None = None,
    status: str | None = None,
    action_type: str | None = None,
    decision_type: str | None = None,
    kpi_id: uuid.UUID | None = None,
    limit: int = 100,
    include_deleted: bool = False,
) -> list[DecisionRecord]:
    stmt = select(DecisionRecord)
    if not include_deleted:
        stmt = stmt.where(DecisionRecord.is_deleted.is_(False))
    if priority is not None:
        stmt = stmt.where(DecisionRecord.priority == priority)
    if status is not None:
        stmt = stmt.where(DecisionRecord.status == status)
    if action_type is not None:
        stmt = stmt.where(DecisionRecord.action_type == action_type)
    if decision_type is not None:
        stmt = stmt.where(DecisionRecord.decision_type == decision_type)
    if kpi_id is not None:
        stmt = stmt.where(DecisionRecord.kpi_id == kpi_id)
    stmt = stmt.order_by(DecisionRecord.created_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def update_decision(db: Session, record: DecisionRecord, **kwargs) -> DecisionRecord:
    for key, value in kwargs.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


def list_decisions_since(db: Session, since: datetime) -> list[DecisionRecord]:
    """Return DecisionRecords created after `since`, oldest-first, for SSE streaming."""
    stmt = (
        select(DecisionRecord)
        .where(DecisionRecord.created_at > since, DecisionRecord.is_deleted.is_(False))
        .order_by(DecisionRecord.created_at.asc())
    )
    return list(db.scalars(stmt).all())
