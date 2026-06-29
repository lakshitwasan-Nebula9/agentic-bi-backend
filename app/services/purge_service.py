from datetime import UTC, datetime, timedelta

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
