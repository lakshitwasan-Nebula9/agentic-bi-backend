"""
Notification Fanout Service

Tails all agent pipeline Redis streams and writes Notification rows for
the relevant users based on event type and severity. Runs as a background
asyncio task started in app lifespan.
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.agents.messaging import stream_name
from app.core.config import settings
from app.core.database import SessionLocal
from app.crud import notification as notification_crud
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

# All agent pipeline event types this fanout cares about
_INSIGHT_DETECTED = "insight_detected"
_KPI_GENERATED = "kpi_generated"
_KPI_PENDING_REVIEW = "kpi_pending_review"
_KPI_CERTIFIED = "kpi_certified"
_KPI_REJECTED = "kpi_rejected"
_DATASET_QUARANTINED = "dataset_quarantined"
_DECISION_MADE = "decision_made"
_DECISION_APPROVAL_REQUIRED = "decision_approval_required"
_APPROVAL_OVERDUE = "approval_overdue"

WATCHED_STREAMS = [
    _INSIGHT_DETECTED,
    _KPI_GENERATED,
    _KPI_PENDING_REVIEW,
    _KPI_CERTIFIED,
    _KPI_REJECTED,
    _DATASET_QUARANTINED,
    _DECISION_MADE,
    _DECISION_APPROVAL_REQUIRED,
    _APPROVAL_OVERDUE,
]


def _build_notification(event_type: str, payload: dict) -> dict | None:
    """
    Maps a Redis event to notification kwargs + target roles.
    Returns None when the event should not produce a notification.
    """
    if event_type == _INSIGHT_DETECTED:
        severity = payload.get("llm_severity") or "info"
        prefix = "Critical anomaly" if severity == "critical" else "New insight"
        title = f"{prefix}: {payload.get('llm_title') or 'KPI signal detected'}"
        return {
            "title": title,
            "body": payload.get("llm_summary"),
            "severity": severity,
            "source_id": str(payload.get("id", "")),
            "source_type": "insight",
            "roles": [UserRole.EXECUTIVE, UserRole.MANAGER, UserRole.ANALYST],
        }

    if event_type == _KPI_GENERATED:
        count = payload.get("count", 0)
        noun = "KPIs" if count != 1 else "KPI"
        return {
            "title": f"{count} new {noun} generated from data sync",
            "body": None,
            "severity": "info",
            "source_id": payload.get("dataset_id"),
            "source_type": "dataset",
            "roles": [UserRole.ANALYST, UserRole.MANAGER],
        }

    if event_type == _KPI_PENDING_REVIEW:
        count = len(payload.get("kpi_ids", []))
        noun = "KPIs" if count != 1 else "KPI"
        return {
            "title": f"{count} {noun} pending your approval",
            "body": "Review and certify in the KPI workflow.",
            "severity": "warning",
            "source_id": payload.get("dataset_id"),
            "source_type": "kpi",
            "roles": [UserRole.ANALYST],
        }

    if event_type == _KPI_CERTIFIED:
        return {
            "title": "KPI certified and published",
            "body": None,
            "severity": "info",
            "source_id": payload.get("kpi_id"),
            "source_type": "kpi",
            "roles": [UserRole.ANALYST],
        }

    if event_type == _KPI_REJECTED:
        return {
            "title": "KPI rejected",
            "body": payload.get("reason") or None,
            "severity": "warning",
            "source_id": payload.get("kpi_id"),
            "source_type": "kpi",
            "roles": [UserRole.ANALYST],
        }

    if event_type == _DATASET_QUARANTINED:
        return {
            "title": "Data quality check failed — dataset quarantined",
            "body": "Review data quality issues before KPI generation resumes.",
            "severity": "critical",
            "source_id": payload.get("dataset_id"),
            "source_type": "dataset",
            "roles": [UserRole.ANALYST, UserRole.MANAGER],
        }

    if event_type == _DECISION_MADE:
        priority = payload.get("priority", "P3")
        severity = "critical" if priority == "P1" else "warning" if priority == "P2" else "info"
        action = payload.get("action_type", "Review required")
        return {
            "title": f"Action recommended ({priority}): {action}",
            "body": payload.get("llm_action_summary"),
            "severity": severity,
            "source_id": payload.get("decision_id"),
            "source_type": "decision",
            "roles": [UserRole.EXECUTIVE, UserRole.MANAGER],
        }

    if event_type == _DECISION_APPROVAL_REQUIRED:
        return {
            "title": "P1 decision requires your approval",
            "body": payload.get("llm_action_summary"),
            "severity": "critical",
            "source_id": payload.get("decision_id"),
            "source_type": "decision",
            "roles": [UserRole.EXECUTIVE, UserRole.MANAGER],
        }

    if event_type == _APPROVAL_OVERDUE:
        entity = payload.get("entity_type", "item")
        assigned = payload.get("assigned_role", "")
        deadline = payload.get("sla_deadline", "")
        return {
            "title": f"Approval overdue — SLA missed for {entity}",
            "body": f"Assigned to: {assigned}. Deadline was: {deadline}",
            "severity": "critical",
            "source_id": payload.get("ar_id"),
            "source_type": "approval",
            "roles": [UserRole.MANAGER, UserRole.EXECUTIVE],
        }

    return None


def _write_notifications(event_type: str, payload: dict) -> None:
    """Synchronous DB write — called via run_in_executor to avoid blocking the event loop."""
    notif = _build_notification(event_type, payload)
    if notif is None:
        return

    roles = notif.pop("roles")
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.role.in_(roles), User.is_active.is_(True)).all()
        for user in users:
            notification_crud.create_notification(
                db,
                user_id=user.id,
                notification_type=event_type,
                **notif,
            )
    except Exception:
        logger.exception("Notification fanout DB write failed for event_type=%s", event_type)
    finally:
        db.close()


async def run() -> None:
    """
    Long-running background task. Tails all watched Redis streams from the
    moment the app starts and fans out a Notification row to every user whose
    role should receive that event type.
    """
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    # Start from "$" so we only deliver events that arrive after startup
    stream_positions: dict[str, str] = {stream_name(et): "$" for et in WATCHED_STREAMS}
    loop = asyncio.get_event_loop()

    logger.info("Notification fanout started, watching %d streams", len(WATCHED_STREAMS))
    try:
        while True:
            try:
                response = await client.xread(stream_positions, block=15_000, count=50)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Notification fanout: Redis read error — retrying in 2s")
                await asyncio.sleep(2.0)
                continue

            for stream, messages in response or []:
                for message_id, fields in messages:
                    stream_positions[stream] = message_id
                    event_type = fields.get("event_type", "")
                    try:
                        payload = json.loads(fields.get("payload", "{}"))
                    except Exception:
                        payload = {}
                    await loop.run_in_executor(None, _write_notifications, event_type, payload)
    finally:
        await client.aclose()
        logger.info("Notification fanout stopped")
