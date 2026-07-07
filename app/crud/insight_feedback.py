import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.insight_feedback import InsightFeedback


def get_active(db: Session, insight_id: uuid.UUID, user_id: uuid.UUID) -> InsightFeedback | None:
    return (
        db.query(InsightFeedback)
        .filter(
            InsightFeedback.insight_id == insight_id,
            InsightFeedback.user_id == user_id,
            InsightFeedback.is_deleted.is_(False),
        )
        .first()
    )


def upsert(
    db: Session,
    *,
    insight_id: uuid.UUID,
    user_id: uuid.UUID,
    rating: str,
    comment: str | None,
) -> InsightFeedback:
    existing = get_active(db, insight_id, user_id)
    if existing is not None:
        existing.rating = rating
        existing.comment = comment
        db.commit()
        db.refresh(existing)
        return existing

    row = InsightFeedback(insight_id=insight_id, user_id=user_id, rating=rating, comment=comment)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def soft_delete(db: Session, feedback: InsightFeedback) -> None:
    feedback.is_deleted = True
    feedback.deleted_at = func.now()
    db.commit()


def list_for_insight(db: Session, insight_id: uuid.UUID) -> list[InsightFeedback]:
    return (
        db.query(InsightFeedback)
        .filter(InsightFeedback.insight_id == insight_id, InsightFeedback.is_deleted.is_(False))
        .order_by(InsightFeedback.created_at.desc())
        .all()
    )


def count_ratings(db: Session, insight_id: uuid.UUID) -> tuple[int, int]:
    """Return (thumbs_up, thumbs_down) counts for one insight."""
    rows = (
        db.query(InsightFeedback.rating, func.count(InsightFeedback.id))
        .filter(InsightFeedback.insight_id == insight_id, InsightFeedback.is_deleted.is_(False))
        .group_by(InsightFeedback.rating)
        .all()
    )
    counts = dict(rows)
    return counts.get("up", 0), counts.get("down", 0)


def list_since(db: Session, since: datetime | None) -> list[InsightFeedback]:
    """All active feedback rows created after ``since`` (or all, if None), oldest first."""
    q = db.query(InsightFeedback).filter(InsightFeedback.is_deleted.is_(False))
    if since is not None:
        q = q.filter(InsightFeedback.created_at > since)
    return q.order_by(InsightFeedback.created_at.asc()).all()


def list_ratings_since(
    db: Session,
    kpi_id: uuid.UUID,
    rating: str,
    since: datetime,
    exclude_insight_id: uuid.UUID | None = None,
) -> list[InsightFeedback]:
    """Votes of one rating for insights on one KPI, since a cutoff.

    Feeds the suppression heuristic in insight_feedback_service: "down" rows
    are the suppression signal, "up" rows are the counter-signal.
    """
    from app.models.insight import InsightEvent

    q = (
        db.query(InsightFeedback)
        .join(InsightEvent, InsightEvent.id == InsightFeedback.insight_id)
        .filter(
            InsightEvent.kpi_id == kpi_id,
            InsightFeedback.rating == rating,
            InsightFeedback.is_deleted.is_(False),
            InsightFeedback.created_at >= since,
        )
    )
    if exclude_insight_id is not None:
        q = q.filter(InsightFeedback.insight_id != exclude_insight_id)
    return q.all()
