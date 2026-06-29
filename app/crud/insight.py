from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.insight import InsightEvent


def list_insight_events_since(db: Session, since: datetime) -> list[InsightEvent]:
    """Return InsightEvents created after `since`, oldest-first, for SSE streaming."""
    stmt = (
        select(InsightEvent)
        .where(InsightEvent.created_at > since, InsightEvent.is_deleted.is_(False))
        .order_by(InsightEvent.created_at.asc())
    )
    return list(db.scalars(stmt).all())
