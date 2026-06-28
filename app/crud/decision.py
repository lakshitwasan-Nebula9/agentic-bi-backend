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


def get_decision(db: Session, decision_id: uuid.UUID) -> DecisionRecord | None:
    return db.get(DecisionRecord, decision_id)


def get_decision_by_insight(db: Session, insight_event_id: uuid.UUID) -> DecisionRecord | None:
    stmt = select(DecisionRecord).where(DecisionRecord.insight_event_id == insight_event_id)
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
) -> list[DecisionRecord]:
    stmt = select(DecisionRecord)
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
        .where(DecisionRecord.created_at > since)
        .order_by(DecisionRecord.created_at.asc())
    )
    return list(db.scalars(stmt).all())
