import uuid

from sqlalchemy.orm import Session

from app.models.explanation import InsightExplanation


def get_by_insight(db: Session, insight_event_id: uuid.UUID) -> InsightExplanation | None:
    return (
        db.query(InsightExplanation)
        .filter(
            InsightExplanation.insight_event_id == insight_event_id,
            InsightExplanation.is_deleted.is_(False),
        )
        .first()
    )


def upsert_explanation(
    db: Session,
    *,
    insight_event_id: uuid.UUID,
    kpi_id: uuid.UUID,
    confidence_score: int,
    confidence_breakdown: dict | None,
    source_dataset: str | None,
    data_freshness_at,
    kpi_formula: str | None,
    llm_explanation: str | None = None,
    business_drivers: list | None = None,
    recommended_actions: list | None = None,
) -> InsightExplanation:
    """Create or update the receipt for an insight (idempotent on insight_event_id)."""
    record = get_by_insight(db, insight_event_id)
    if record is None:
        record = InsightExplanation(insight_event_id=insight_event_id, kpi_id=kpi_id)
        db.add(record)

    record.kpi_id = kpi_id
    record.confidence_score = confidence_score
    record.confidence_breakdown = confidence_breakdown
    record.source_dataset = source_dataset
    record.data_freshness_at = data_freshness_at
    record.kpi_formula = kpi_formula
    record.llm_explanation = llm_explanation
    record.business_drivers = business_drivers
    record.recommended_actions = recommended_actions

    db.commit()
    db.refresh(record)
    return record
