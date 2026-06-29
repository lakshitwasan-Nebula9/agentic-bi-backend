"""Explainability Agent core — builds the receipt shown in the insight drill-down modal.

For a given InsightEvent it gathers deterministic context (KPI → Dataset → Connector),
derives the four modal values (confidence score, source dataset, data freshness, KPI
formula) and persists an idempotent InsightExplanation receipt. No LLM is involved.
"""

import logging

from sqlalchemy.orm import Session

from app.crud.dataset import get_dataset
from app.crud.explanation import upsert_explanation
from app.crud.kpi import get_kpi
from app.models.connector import DataConnector
from app.models.dataset import Dataset
from app.models.explanation import InsightExplanation
from app.models.insight import InsightEvent
from app.models.kpi import KPISnapshot
from app.services.confidence_service import compute_confidence

logger = logging.getLogger(__name__)


def _source_dataset(db: Session, kpi, dataset: Dataset | None) -> str | None:
    """Build "<database_name>.<table_name>" (e.g. "sales_db.orders")."""
    if kpi is None:
        return None
    connector = (
        db.query(DataConnector)
        .filter(DataConnector.id == dataset.connector_id, DataConnector.is_deleted.is_(False))
        .first()
        if dataset is not None
        else None
    )
    if connector is None:
        return kpi.table_name
    return f"{connector.database_name}.{kpi.table_name}"


def build_explanation(db: Session, insight: InsightEvent) -> InsightExplanation:
    """Compute and persist the explainability receipt for an insight."""
    kpi = get_kpi(db, insight.kpi_id)
    dataset = get_dataset(db, kpi.dataset_id) if kpi is not None else None

    num_snapshots = (
        db.query(KPISnapshot)
        .filter(KPISnapshot.kpi_id == insight.kpi_id, KPISnapshot.is_deleted.is_(False))
        .count()
    )

    # Data freshness: when the source data was last synced; fall back to the latest
    # snapshot's computed_at when the dataset has never recorded a sync.
    data_freshness_at = dataset.last_synced_at if dataset is not None else None
    if data_freshness_at is None:
        latest = (
            db.query(KPISnapshot)
            .filter(KPISnapshot.kpi_id == insight.kpi_id, KPISnapshot.is_deleted.is_(False))
            .order_by(KPISnapshot.computed_at.desc())
            .first()
        )
        data_freshness_at = latest.computed_at if latest is not None else None

    score, breakdown = compute_confidence(insight, dataset, num_snapshots)

    return upsert_explanation(
        db,
        insight_event_id=insight.id,
        kpi_id=insight.kpi_id,
        confidence_score=score,
        confidence_breakdown=breakdown,
        source_dataset=_source_dataset(db, kpi, dataset),
        data_freshness_at=data_freshness_at,
        kpi_formula=kpi.formula if kpi is not None else None,
    )
