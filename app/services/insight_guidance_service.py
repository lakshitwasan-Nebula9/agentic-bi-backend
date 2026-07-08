"""Periodic learning loop: turns accumulated insight feedback into prompt guidance.

This is the primary quality lever for the insight feedback loop (as opposed to
the short-term suppression heuristic in insight_feedback_service): rather than
just hiding repeatedly-disliked insights, it periodically asks Gemini to merge
recent feedback into a running set of writing rules, which the Insight Agent
then appends to its narration prompt (see app.agents.insight_agent._build_prompt
and insight_service.detect_for_kpi).
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents.insight_guidance_agent import summarize_guidance
from app.crud import insight_guidance as guidance_crud
from app.crud.insight_feedback import list_since
from app.models.insight import InsightEvent
from app.models.insight_guidance import InsightGuidance
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

MIN_NEW_FEEDBACK_TO_REGENERATE = 10


def get_active_guidance_text(db: Session) -> str | None:
    active = guidance_crud.get_active(db)
    return active.guidance_text if active else None


async def generate_guidance(
    db: Session, *, min_feedback: int = MIN_NEW_FEEDBACK_TO_REGENERATE
) -> InsightGuidance | None:
    """Merge feedback since the last run into updated guidance.

    Returns the new InsightGuidance row, or None if generation was skipped
    (too little new feedback, or the LLM call failed/is disabled) — the
    previously active guidance stays in effect either way.
    """
    previous = guidance_crud.get_active(db)
    since = previous.created_at if previous else None

    feedback_rows = list_since(db, since)
    if len(feedback_rows) < min_feedback:
        logger.info(
            "Skipping guidance generation: only %d new feedback rows (need %d)",
            len(feedback_rows),
            min_feedback,
        )
        return None

    insight_ids = {row.insight_id for row in feedback_rows}
    insights_by_id = {
        insight.id: insight
        for insight in db.query(InsightEvent).filter(InsightEvent.id.in_(insight_ids)).all()
    }

    feedback_items = []
    for row in feedback_rows:
        insight = insights_by_id.get(row.insight_id)
        feedback_items.append(
            {
                "title": insight.llm_title if insight else None,
                "category": insight.llm_category if insight else None,
                "insight_type": insight.insight_type if insight else None,
                "rating": row.rating,
                "comment": row.comment,
            }
        )

    summary = await summarize_guidance(previous.guidance_text if previous else "", feedback_items)
    if summary is None or not summary.bullets:
        logger.info("Guidance generation produced no update; keeping previous guidance")
        return None

    guidance_text = "\n".join(f"- {bullet}" for bullet in summary.bullets)
    period_start = since or feedback_rows[0].created_at
    period_end = datetime.now(UTC)

    row = guidance_crud.create(
        db,
        guidance_text=guidance_text,
        feedback_count_considered=len(feedback_items),
        period_start=period_start,
        period_end=period_end,
        model_used=None,
    )

    record_audit(
        db,
        action="insight.guidance_generated",
        entity_type="insight_guidance",
        entity_id=row.id,
        summary=f"Updated insight narration guidance from {len(feedback_items)} feedback entries",
        details={"bullets": summary.bullets, "feedback_count": len(feedback_items)},
    )

    return row
