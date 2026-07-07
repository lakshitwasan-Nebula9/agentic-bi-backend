"""Insight feedback: thumbs up/down + comments, and the short-term suppression heuristic.

Two consumers read this data:
  - This module's ``compute_suppression`` — a cheap, same-KPI similarity check run
    at detection time (see insight_service.detect_for_kpi) that flags a new insight
    as ``is_suppressed`` when it closely resembles ones users recently down-voted.
    It never hides anything; the frontend badges/grays flagged insights.
  - app.services.insight_guidance_service — periodically summarizes *all* feedback
    (including comments) into prompt guidance for the Insight Agent. That is the
    primary, long-term quality lever; suppression is just a short-term UX patch.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.crud import insight_feedback as feedback_crud
from app.crud import notification as notification_crud
from app.models.embeddings import EmbeddingRecord
from app.models.insight import InsightEvent
from app.models.insight_feedback import InsightFeedback
from app.models.user import User
from app.schemas.insight_feedback import InsightFeedbackSummary
from app.services import embedding_service
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

SUPPRESSION_LOOKBACK_DAYS = 90
SUPPRESSION_DISTANCE_THRESHOLD = 0.15  # cosine distance; lower = more similar
SUPPRESSION_MIN_DISTINCT_DOWN_USERS = 2

# Extends the app's informal notification_type vocabulary (see the
# _EVENT_TYPE-style constants in notification_fanout.py for the Redis-driven
# ones — there is no formal enum type to hook into). Written synchronously
# from submit_feedback, not via the Redis fanout, since it reacts to a direct
# user action rather than an agent pipeline event.
INSIGHT_FEEDBACK_RECORDED = "insight_feedback_recorded"


def _signature(insight: InsightEvent) -> str:
    return (
        f"{insight.kpi_id}|{insight.insight_type}|"
        f"{insight.llm_category or ''}|{insight.llm_title or ''}"
    )


def submit_feedback(
    db: Session,
    *,
    insight: InsightEvent,
    user: User,
    rating: str,
    comment: str | None,
) -> InsightFeedback:
    previous = feedback_crud.get_active(db, insight.id, user.id)
    previous_rating = previous.rating if previous else None

    feedback = feedback_crud.upsert(
        db,
        insight_id=insight.id,
        user_id=user.id,
        rating=rating,
        comment=comment,
    )

    record_audit(
        db,
        action="insight.feedback_submitted",
        entity_type="insight",
        entity_id=insight.id,
        actor_id=user.id,
        actor_role=user.role.value if hasattr(user.role, "value") else str(user.role),
        summary=f"{rating} feedback on insight {insight.id}",
        details={"rating": rating, "comment": comment},
    )

    if rating == "down":
        _store_suppression_vector(db, insight, comment)

    _notify_feedback_recorded(
        db,
        insight=insight,
        user=user,
        rating=rating,
        comment=comment,
        rating_changed=rating != previous_rating,
    )

    return feedback


def retract_feedback(db: Session, *, insight_id: uuid.UUID, user: User) -> bool:
    existing = feedback_crud.get_active(db, insight_id, user.id)
    if existing is None:
        return False
    feedback_crud.soft_delete(db, existing)
    record_audit(
        db,
        action="insight.feedback_retracted",
        entity_type="insight",
        entity_id=insight_id,
        actor_id=user.id,
        summary=f"Feedback retracted on insight {insight_id}",
    )
    _suppress_unread_feedback_notification(db, user_id=user.id, insight_id=insight_id)
    return True


def get_summary(
    db: Session, *, insight_id: uuid.UUID, user_id: uuid.UUID
) -> InsightFeedbackSummary:
    thumbs_up, thumbs_down = feedback_crud.count_ratings(db, insight_id)
    mine = feedback_crud.get_active(db, insight_id, user_id)
    return InsightFeedbackSummary(
        insight_id=insight_id,
        thumbs_up=thumbs_up,
        thumbs_down=thumbs_down,
        my_feedback=mine,
    )


def _feedback_notification_body(insight: InsightEvent, rating: str, comment: str | None) -> str:
    title = insight.llm_title or f"this {insight.insight_type} insight"
    if rating == "up":
        return f'You marked "{title}" as helpful'
    if comment:
        return f'You marked "{title}" as unhelpful, with a comment'
    return f'You marked "{title}" as unhelpful'


def _notify_feedback_recorded(
    db: Session,
    *,
    insight: InsightEvent,
    user: User,
    rating: str,
    comment: str | None,
    rating_changed: bool,
) -> None:
    """Best-effort bell notification for the acting user.

    Idempotent per *vote*, not per POST: re-submitting the same rating (e.g.
    the down-vote flow firing once on click and again when the optional
    comment is attached) updates the existing notification in place instead of
    creating a second one. A new row is only created when the rating itself
    changes (up<->down) or after a retract+revote, since that's a genuinely
    new action worth surfacing again.
    """
    try:
        body = _feedback_notification_body(insight, rating, comment)
        source_id = str(insight.id)

        if not rating_changed:
            existing = notification_crud.get_latest_for_source(
                db, user.id, INSIGHT_FEEDBACK_RECORDED, "insight", source_id
            )
            if existing is not None:
                notification_crud.update_notification(
                    db, existing, title="Feedback recorded", body=body
                )
                return

        notification_crud.create_notification(
            db,
            user_id=user.id,
            notification_type=INSIGHT_FEEDBACK_RECORDED,
            title="Feedback recorded",
            body=body,
            severity="info",
            source_id=source_id,
            source_type="insight",
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to write feedback-recorded notification for insight %s",
            insight.id,
            exc_info=True,
        )


def _suppress_unread_feedback_notification(
    db: Session, *, user_id: uuid.UUID, insight_id: uuid.UUID
) -> None:
    """On retract, don't notify — just clear the prior unread notification, if any.

    "You removed your feedback" isn't actionable, so no new notification is
    written; an already-read notification is left alone as history.
    """
    try:
        existing = notification_crud.get_latest_for_source(
            db, user_id, INSIGHT_FEEDBACK_RECORDED, "insight", str(insight_id)
        )
        if existing is not None and not existing.is_read:
            notification_crud.delete_notification(db, existing)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to suppress feedback notification for insight %s", insight_id, exc_info=True
        )


def _store_suppression_vector(db: Session, insight: InsightEvent, comment: str | None) -> None:
    """Best-effort: embed this insight's signature so future similar insights can
    be scored against it. Never allowed to break feedback submission."""
    try:
        content = _signature(insight) + (f" | {comment}" if comment else "")
        embedding_service.upsert_embedding(
            db,
            entity_type="insight_suppression",
            entity_id=str(insight.id),
            content=content,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to store suppression vector for insight %s", insight.id, exc_info=True
        )


def compute_suppression(db: Session, insight: InsightEvent) -> tuple[bool, float]:
    """Score a newly-detected insight against recent same-KPI feedback.

    Returns (is_suppressed, net_score). Best-effort: any failure here must not
    block insight detection, so callers should treat exceptions as "not suppressed".
    """
    try:
        since = datetime.now(UTC) - timedelta(days=SUPPRESSION_LOOKBACK_DAYS)
        query_vector = embedding_service.generate_embedding(_signature(insight))

        down_votes = feedback_crud.list_ratings_since(
            db, insight.kpi_id, "down", since, exclude_insight_id=insight.id
        )
        up_votes = feedback_crud.list_ratings_since(
            db, insight.kpi_id, "up", since, exclude_insight_id=insight.id
        )

        neg_weight, neg_users = _weighted_matches(db, query_vector, down_votes)
        pos_weight, _ = _weighted_matches(db, query_vector, up_votes)

        net_score = neg_weight - pos_weight
        is_suppressed = net_score > 0 and len(neg_users) >= SUPPRESSION_MIN_DISTINCT_DOWN_USERS
        return is_suppressed, net_score
    except Exception:  # noqa: BLE001
        logger.warning(
            "Suppression scoring failed for insight %s — treating as not suppressed",
            insight.id,
            exc_info=True,
        )
        return False, 0.0


def _weighted_matches(
    db: Session, query_vector: list[float], votes: list[InsightFeedback]
) -> tuple[float, set[uuid.UUID]]:
    """Sum (1 - cosine_distance) over votes whose insight's stored vector is within
    the similarity threshold of ``query_vector``, plus the set of distinct voters."""
    if not votes:
        return 0.0, set()

    insight_ids = {str(v.insight_id) for v in votes}
    rows = (
        db.query(EmbeddingRecord.entity_id, EmbeddingRecord.embedding.cosine_distance(query_vector))
        .filter(
            EmbeddingRecord.entity_type == "insight_suppression",
            EmbeddingRecord.entity_id.in_(insight_ids),
            EmbeddingRecord.is_deleted.is_(False),
        )
        .all()
    )
    distance_by_insight_id = dict(rows)

    weight = 0.0
    matched_users: set[uuid.UUID] = set()
    for vote in votes:
        distance = distance_by_insight_id.get(str(vote.insight_id))
        if distance is not None and distance < SUPPRESSION_DISTANCE_THRESHOLD:
            weight += 1 - distance
            matched_users.add(vote.user_id)
    return weight, matched_users
