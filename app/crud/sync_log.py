import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sync_log import SyncLog


def create_sync_log(db: Session, log: SyncLog) -> SyncLog:
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def list_sync_logs(
    db: Session,
    connector_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[SyncLog]:
    stmt = (
        select(SyncLog)
        .where(SyncLog.connector_id == connector_id)
        .order_by(SyncLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def list_sync_logs_since(
    db: Session,
    connector_id: uuid.UUID,
    since: datetime,
) -> list[SyncLog]:
    """Return logs newer than `since`, oldest-first, for SSE streaming."""
    stmt = (
        select(SyncLog)
        .where(SyncLog.connector_id == connector_id, SyncLog.created_at > since)
        .order_by(SyncLog.created_at.asc())
    )
    return list(db.scalars(stmt).all())
