from datetime import datetime

from sqlalchemy.orm import Session

from app.models.insight_guidance import InsightGuidance


def get_active(db: Session) -> InsightGuidance | None:
    return (
        db.query(InsightGuidance)
        .filter(InsightGuidance.is_active.is_(True))
        .order_by(InsightGuidance.created_at.desc())
        .first()
    )


def create(
    db: Session,
    *,
    guidance_text: str,
    feedback_count_considered: int,
    period_start: datetime | None,
    period_end: datetime | None,
    model_used: str | None,
) -> InsightGuidance:
    """Insert the new guidance row and deactivate the previous active one."""
    previous = get_active(db)
    if previous is not None:
        previous.is_active = False

    row = InsightGuidance(
        guidance_text=guidance_text,
        feedback_count_considered=feedback_count_considered,
        period_start=period_start,
        period_end=period_end,
        model_used=model_used,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
