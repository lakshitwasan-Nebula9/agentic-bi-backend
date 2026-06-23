import uuid

from sqlalchemy.orm import Session

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


def detect_for_kpi(db: Session, kpi_id: uuid.UUID) -> InsightEvent | None:
    """Run math on the latest monthly snapshot for one KPI.

    Returns None when there are fewer than 3 monthly snapshots or the latest
    period has already been analysed.
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
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def detect_all(db: Session) -> list[InsightEvent]:
    """Run detection across all certified KPIs that have monthly snapshots."""
    kpi_ids = [
        row[0]
        for row in db.query(KPIDefinition.id).filter(KPIDefinition.status == "certified").all()
    ]
    events: list[InsightEvent] = []
    for kpi_id in kpi_ids:
        event = detect_for_kpi(db, kpi_id)
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
