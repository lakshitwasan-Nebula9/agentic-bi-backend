import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.approval_request import ApprovalRequest
from app.models.connector import DataConnector
from app.models.dataset import Dataset, DatasetRecord
from app.models.decision import DecisionRecord
from app.models.embeddings import EmbeddingRecord
from app.models.explanation import InsightExplanation
from app.models.insight import InsightEvent
from app.models.kpi import KPIDefinition, KPISnapshot, KPIVersion
from app.models.schema_metadata import SchemaMetadata

SOFT_DELETE_WINDOW_DAYS = 7


def purge_expired_soft_deletes(db: Session) -> dict[str, int]:
    """Hard-delete all soft-deleted records older than 7 days.

    Children are deleted before parents to respect FK constraints.
    Returns a summary of rows removed per table.
    """
    cutoff = datetime.now(UTC) - timedelta(days=SOFT_DELETE_WINDOW_DAYS)
    counts: dict[str, int] = {}

    def _purge(model, label: str) -> None:
        result = (
            db.query(model)
            .filter(model.is_deleted.is_(True), model.deleted_at < cutoff)
            .delete(synchronize_session=False)
        )
        counts[label] = result

    # Leaf tables first
    _purge(EmbeddingRecord, "embeddings")
    _purge(ApprovalRequest, "approval_requests")
    _purge(KPISnapshot, "kpi_snapshots")
    _purge(KPIVersion, "kpi_versions")
    _purge(InsightExplanation, "insight_explanations")
    _purge(DecisionRecord, "decision_records")
    _purge(InsightEvent, "insight_events")
    _purge(KPIDefinition, "kpi_definitions")
    _purge(SchemaMetadata, "schema_metadata")
    _purge(DatasetRecord, "dataset_records")
    _purge(Dataset, "datasets")
    _purge(DataConnector, "data_connectors")

    db.commit()
    return counts


def purge_connector(db: Session, connector_id: uuid.UUID) -> None:
    """Permanently hard-delete an already-archived connector and its full cascade now.

    Bypasses the 7-day window — backs the Archive & Recovery "permanent delete" action.
    Children are deleted before parents to respect FK constraints.
    """
    connector = db.query(DataConnector).filter(DataConnector.id == connector_id).one_or_none()
    if connector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    if not connector.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only archived connectors can be permanently deleted",
        )

    dataset_ids = [
        row[0] for row in db.query(Dataset.id).filter(Dataset.connector_id == connector_id).all()
    ]
    kpi_ids: list = []
    table_names: list = []
    insight_ids: list = []
    if dataset_ids:
        kpi_ids = [
            row[0]
            for row in db.query(KPIDefinition.id)
            .filter(KPIDefinition.dataset_id.in_(dataset_ids))
            .all()
        ]
        table_names = [
            row[0]
            for row in db.query(SchemaMetadata.table_name)
            .filter(SchemaMetadata.dataset_id.in_(dataset_ids))
            .all()
        ]
    if kpi_ids:
        insight_ids = [
            row[0]
            for row in db.query(InsightEvent.id).filter(InsightEvent.kpi_id.in_(kpi_ids)).all()
        ]

    def _del(query) -> None:
        query.delete(synchronize_session=False)

    # Leaf tables first, mirroring purge_expired_soft_deletes ordering.
    if kpi_ids:
        _del(
            db.query(EmbeddingRecord).filter(
                EmbeddingRecord.entity_type == "kpi_definition",
                EmbeddingRecord.entity_id.in_([str(k) for k in kpi_ids]),
            )
        )
        _del(
            db.query(ApprovalRequest).filter(
                ApprovalRequest.entity_type == "kpi",
                ApprovalRequest.entity_id.in_(kpi_ids),
            )
        )
        _del(db.query(KPISnapshot).filter(KPISnapshot.kpi_id.in_(kpi_ids)))
        _del(db.query(KPIVersion).filter(KPIVersion.kpi_id.in_(kpi_ids)))
    if insight_ids:
        _del(
            db.query(InsightExplanation).filter(
                InsightExplanation.insight_event_id.in_(insight_ids)
            )
        )
        _del(db.query(DecisionRecord).filter(DecisionRecord.insight_event_id.in_(insight_ids)))
    if kpi_ids:
        _del(db.query(InsightEvent).filter(InsightEvent.kpi_id.in_(kpi_ids)))
        _del(db.query(KPIDefinition).filter(KPIDefinition.id.in_(kpi_ids)))
    if table_names:
        _del(
            db.query(EmbeddingRecord).filter(
                EmbeddingRecord.entity_type == "schema_description",
                EmbeddingRecord.entity_id.in_(table_names),
            )
        )
    if dataset_ids:
        _del(db.query(SchemaMetadata).filter(SchemaMetadata.dataset_id.in_(dataset_ids)))
        _del(db.query(DatasetRecord).filter(DatasetRecord.dataset_id.in_(dataset_ids)))
        _del(db.query(Dataset).filter(Dataset.id.in_(dataset_ids)))

    db.delete(connector)
    db.commit()
