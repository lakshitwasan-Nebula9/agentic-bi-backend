import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents.insight_agent import narrate
from app.agents.messaging import INSIGHT_DETECTED, AgentPublisher
from app.core.database import SessionLocal
from app.crud.kpi import get_kpi
from app.models.dataset import Dataset
from app.models.insight import InsightEvent
from app.models.kpi import KPIDefinition, KPISnapshot
from app.schemas.insight import InsightEventResponse
from app.services import insight_feedback_service, insight_guidance_service
from app.services.insight_math_service import analyze

logger = logging.getLogger(__name__)

_publisher = AgentPublisher()


def _publish_insight(event: InsightEvent) -> None:
    """Best-effort: emit the new insight onto Redis for the WebSocket listener.

    Detection must never fail because the broker is down, so any error here is
    logged and swallowed — the InsightEvent is already persisted.
    """
    try:
        payload = InsightEventResponse.model_validate(event).model_dump(mode="json")
        _publisher.publish(INSIGHT_DETECTED, payload)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to publish insight event %s to Redis", event.id, exc_info=True)


def _get_monthly_snapshots_asc(db: Session, kpi_id: uuid.UUID) -> list[KPISnapshot]:
    """Return monthly snapshots for a KPI in chronological order (oldest first)."""
    return (
        db.query(KPISnapshot)
        .filter(
            KPISnapshot.kpi_id == kpi_id,
            KPISnapshot.period_start.isnot(None),
            KPISnapshot.is_deleted.is_(False),
        )
        .order_by(KPISnapshot.period_start.asc())
        .all()
    )


def _already_detected(db: Session, kpi_id: uuid.UUID, period_start) -> bool:
    return (
        db.query(InsightEvent)
        .filter(
            InsightEvent.kpi_id == kpi_id,
            InsightEvent.period_start == period_start,
            InsightEvent.is_deleted.is_(False),
        )
        .first()
        is not None
    )


async def detect_for_kpi(db: Session, kpi_id: uuid.UUID) -> InsightEvent | None:
    """Run math on the latest monthly snapshot for one KPI, then narrate it.

    Returns None when there are fewer than 3 monthly snapshots or the latest
    period has already been analysed. Narration is best-effort — the event is
    persisted with null narrative fields when the LLM is disabled or fails.
    """
    snapshots = _get_monthly_snapshots_asc(db, kpi_id)
    if len(snapshots) < 3:
        return None

    latest = snapshots[-1]
    if _already_detected(db, kpi_id, latest.period_start):
        return None

    values = [s.value for s in snapshots]
    result = analyze(values)

    event = InsightEvent(
        kpi_id=kpi_id,
        period_start=latest.period_start,
        value=latest.value,
        z_score=result.z_score,
        baseline_mean=result.baseline_mean,
        baseline_std=result.baseline_std,
        rolling_avg_3m=result.rolling_avg_3m,
        rolling_avg_6m=result.rolling_avg_6m,
        trend_slope=result.trend_slope,
        insight_type=result.insight_type,
        is_anomaly=result.is_anomaly,
    )

    # GenAI narration (best-effort). Includes the latest feedback-derived
    # guidance, if any, so the agent's writing improves over time.
    kpi: KPIDefinition | None = get_kpi(db, kpi_id)
    guidance_text = insight_guidance_service.get_active_guidance_text(db)
    narrative = await narrate(
        {
            "kpi_id": kpi_id,
            "kpi_name": kpi.display_name if kpi else None,
            "kpi_category": kpi.category if kpi else None,
            "unit": kpi.unit if kpi else None,
            "direction": kpi.direction if kpi else None,
            "value": latest.value,
            "expected": result.baseline_mean,
            "z_score": result.z_score,
            "rolling_avg_3m": result.rolling_avg_3m,
            "rolling_avg_6m": result.rolling_avg_6m,
            "trend_slope": result.trend_slope,
            "insight_type": result.insight_type,
            "recent_values": values[-7:],
            "guidance": guidance_text,
        }
    )
    if narrative is not None:
        event.llm_title = narrative.title
        event.llm_category = narrative.category
        event.llm_severity = narrative.severity
        event.llm_summary = narrative.summary
        event.narrated_at = datetime.now(UTC)

    # Short-term suppression heuristic — never blocks persistence; the event is
    # still created and published, just flagged for the frontend to badge.
    is_suppressed, suppression_score = insight_feedback_service.compute_suppression(db, event)
    event.is_suppressed = is_suppressed
    event.suppression_score = suppression_score

    db.add(event)
    db.commit()
    db.refresh(event)
    _publish_insight(event)
    return event


async def detect_all(db: Session) -> list[InsightEvent]:
    """Run detection across all certified KPIs that have monthly snapshots."""
    kpi_ids = [
        row[0]
        for row in db.query(KPIDefinition.id)
        .filter(KPIDefinition.status == "certified", KPIDefinition.is_deleted.is_(False))
        .all()
    ]
    return await _detect_for_kpi_ids(db, kpi_ids)


async def detect_for_connector(db: Session, connector_id: uuid.UUID) -> list[InsightEvent]:
    """Run detection across the certified KPIs reachable from a connector's datasets."""
    kpi_ids = [
        row[0]
        for row in db.query(KPIDefinition.id)
        .join(Dataset, Dataset.id == KPIDefinition.dataset_id)
        .filter(
            Dataset.connector_id == connector_id,
            Dataset.is_deleted.is_(False),
            KPIDefinition.status == "certified",
            KPIDefinition.is_deleted.is_(False),
        )
        .all()
    ]
    return await _detect_for_kpi_ids(db, kpi_ids)


async def _detect_for_kpi_ids(db: Session, kpi_ids: list[uuid.UUID]) -> list[InsightEvent]:
    events: list[InsightEvent] = []
    for kpi_id in kpi_ids:
        event = await detect_for_kpi(db, kpi_id)
        if event is not None:
            events.append(event)
    return events


async def run_detection_bg(connector_id: uuid.UUID | None = None) -> None:
    """Background entrypoint: open a fresh session and run detection.

    Scoped to a connector's certified KPIs when given, otherwise all certified
    KPIs. Used as a FastAPI background task (e.g. on dashboard creation), so it
    owns its session and never propagates errors to the request.
    """
    db = SessionLocal()
    try:
        if connector_id is not None:
            await detect_for_connector(db, connector_id)
        else:
            await detect_all(db)
    except Exception:  # noqa: BLE001
        logger.warning("Background insight detection failed", exc_info=True)
    finally:
        db.close()


def list_insights(
    db: Session,
    kpi_id: uuid.UUID | None = None,
    insight_type: str | None = None,
    is_anomaly: bool | None = None,
    limit: int = 100,
    include_deleted: bool = False,
) -> list[InsightEvent]:
    q = db.query(InsightEvent)
    if not include_deleted:
        q = q.filter(InsightEvent.is_deleted.is_(False))
    if kpi_id is not None:
        q = q.filter(InsightEvent.kpi_id == kpi_id)
    if insight_type is not None:
        q = q.filter(InsightEvent.insight_type == insight_type)
    if is_anomaly is not None:
        q = q.filter(InsightEvent.is_anomaly == is_anomaly)
    return q.order_by(InsightEvent.created_at.desc()).limit(limit).all()
