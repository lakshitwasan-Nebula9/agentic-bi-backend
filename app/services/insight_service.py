import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents.insight_agent import narrate
from app.crud.kpi import get_kpi
from app.models.insight import InsightEvent
from app.models.kpi import KPIDefinition, KPISnapshot
from app.services.insight_math_service import analyze


def _get_monthly_snapshots_asc(db: Session, kpi_id: uuid.UUID) -> list[KPISnapshot]:
    """Return monthly snapshots for a KPI in chronological order (oldest first)."""
    return (
        db.query(KPISnapshot)
        .filter(KPISnapshot.kpi_id == kpi_id, KPISnapshot.period_start.isnot(None))
        .order_by(KPISnapshot.period_start.asc())
        .all()
    )


def _already_detected(db: Session, kpi_id: uuid.UUID, period_start) -> bool:
    return (
        db.query(InsightEvent)
        .filter(InsightEvent.kpi_id == kpi_id, InsightEvent.period_start == period_start)
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

    # GenAI narration (best-effort).
    kpi: KPIDefinition | None = get_kpi(db, kpi_id)
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
        }
    )
    if narrative is not None:
        event.llm_title = narrative.title
        event.llm_category = narrative.category
        event.llm_severity = narrative.severity
        event.llm_summary = narrative.summary
        event.narrated_at = datetime.now(UTC)

    db.add(event)
    db.commit()
    db.refresh(event)
    return event


async def detect_all(db: Session) -> list[InsightEvent]:
    """Run detection across all certified KPIs that have monthly snapshots."""
    kpi_ids = [
        row[0]
        for row in db.query(KPIDefinition.id).filter(KPIDefinition.status == "certified").all()
    ]
    events: list[InsightEvent] = []
    for kpi_id in kpi_ids:
        event = await detect_for_kpi(db, kpi_id)
        if event is not None:
            events.append(event)
    return events


def list_insights(
    db: Session,
    kpi_id: uuid.UUID | None = None,
    insight_type: str | None = None,
    is_anomaly: bool | None = None,
    limit: int = 100,
) -> list[InsightEvent]:
    q = db.query(InsightEvent)
    if kpi_id is not None:
        q = q.filter(InsightEvent.kpi_id == kpi_id)
    if insight_type is not None:
        q = q.filter(InsightEvent.insight_type == insight_type)
    if is_anomaly is not None:
        q = q.filter(InsightEvent.is_anomaly == is_anomaly)
    return q.order_by(InsightEvent.created_at.desc()).limit(limit).all()
