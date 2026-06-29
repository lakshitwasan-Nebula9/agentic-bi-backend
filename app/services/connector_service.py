import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg2
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.crud import connector as connector_crud
from app.models.approval_request import ApprovalRequest
from app.models.connector import DataConnector
from app.models.dataset import Dataset, DatasetRecord
from app.models.decision import DecisionRecord
from app.models.embeddings import EmbeddingRecord
from app.models.explanation import InsightExplanation
from app.models.insight import InsightEvent
from app.models.kpi import KPIDefinition, KPISnapshot, KPIVersion
from app.models.schema_metadata import SchemaMetadata
from app.schemas.connector import ConnectorCreate, ConnectorResponse, ConnectorUpdate
from app.services.encryption_service import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

SOFT_DELETE_WINDOW_DAYS = 7

CONNECT_TIMEOUT_SECONDS = 5


def get_decrypted_password(connector: DataConnector) -> str:
    return decrypt_value(connector.encrypted_password)


def encrypt_password(password: str) -> str:
    return encrypt_value(password)


def get_connector_or_404(
    db: Session, connector_id: uuid.UUID, include_deleted: bool = False
) -> DataConnector:
    connector = connector_crud.get_connector(db, connector_id, include_deleted=include_deleted)
    if connector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    return connector


def list_connectors(db: Session, include_deleted: bool = False) -> list[DataConnector]:
    return connector_crud.list_connectors(db, include_deleted=include_deleted)


def create_connector(db: Session, payload: ConnectorCreate, created_by: uuid.UUID) -> DataConnector:
    if connector_crud.get_connector_by_name(db, payload.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A connector with this name already exists",
        )

    connector = DataConnector(
        name=payload.name,
        connector_type=payload.connector_type,
        host=payload.host,
        port=payload.port,
        database_name=payload.database_name,
        username=payload.username,
        encrypted_password=encrypt_password(payload.password),
        extra_config=payload.extra_config,
        created_by=created_by,
    )
    return connector_crud.create_connector(db, connector)


def update_connector(
    db: Session, connector_id: uuid.UUID, payload: ConnectorUpdate
) -> DataConnector:
    connector = get_connector_or_404(db, connector_id)

    updates = payload.model_dump(exclude_unset=True, exclude={"password"})
    if payload.password is not None:
        updates["encrypted_password"] = encrypt_password(payload.password)

    return connector_crud.update_connector(db, connector, updates)


def delete_connector(db: Session, connector_id: uuid.UUID) -> None:
    connector = get_connector_or_404(db, connector_id)
    now = datetime.now(UTC)
    stamp = {"is_deleted": True, "deleted_at": now}

    dataset_ids = [
        row[0]
        for row in db.query(Dataset.id)
        .filter(Dataset.connector_id == connector_id, Dataset.is_deleted.is_(False))
        .all()
    ]
    if dataset_ids:
        kpi_ids = [
            row[0]
            for row in db.query(KPIDefinition.id)
            .filter(KPIDefinition.dataset_id.in_(dataset_ids), KPIDefinition.is_deleted.is_(False))
            .all()
        ]
        if kpi_ids:
            db.query(KPISnapshot).filter(
                KPISnapshot.kpi_id.in_(kpi_ids), KPISnapshot.is_deleted.is_(False)
            ).update(stamp, synchronize_session=False)
            db.query(KPIVersion).filter(KPIVersion.kpi_id.in_(kpi_ids)).update(
                stamp, synchronize_session=False
            )

            insight_ids = [
                row[0]
                for row in db.query(InsightEvent.id)
                .filter(InsightEvent.kpi_id.in_(kpi_ids), InsightEvent.is_deleted.is_(False))
                .all()
            ]
            if insight_ids:
                db.query(InsightExplanation).filter(
                    InsightExplanation.insight_event_id.in_(insight_ids),
                    InsightExplanation.is_deleted.is_(False),
                ).update(stamp, synchronize_session=False)
                db.query(DecisionRecord).filter(
                    DecisionRecord.insight_event_id.in_(insight_ids),
                    DecisionRecord.is_deleted.is_(False),
                ).update(stamp, synchronize_session=False)
            db.query(InsightEvent).filter(
                InsightEvent.kpi_id.in_(kpi_ids), InsightEvent.is_deleted.is_(False)
            ).update(stamp, synchronize_session=False)

            # Polymorphic tables (no FK) — must be stamped explicitly.
            db.query(EmbeddingRecord).filter(
                EmbeddingRecord.entity_type == "kpi_definition",
                EmbeddingRecord.entity_id.in_([str(kid) for kid in kpi_ids]),
                EmbeddingRecord.is_deleted.is_(False),
            ).update(stamp, synchronize_session=False)
            db.query(ApprovalRequest).filter(
                ApprovalRequest.entity_type == "kpi",
                ApprovalRequest.entity_id.in_(kpi_ids),
                ApprovalRequest.is_deleted.is_(False),
            ).update(stamp, synchronize_session=False)

        db.query(KPIDefinition).filter(
            KPIDefinition.dataset_id.in_(dataset_ids), KPIDefinition.is_deleted.is_(False)
        ).update(stamp, synchronize_session=False)

        table_names = [
            row[0]
            for row in db.query(SchemaMetadata.table_name)
            .filter(
                SchemaMetadata.dataset_id.in_(dataset_ids), SchemaMetadata.is_deleted.is_(False)
            )
            .all()
        ]
        if table_names:
            db.query(EmbeddingRecord).filter(
                EmbeddingRecord.entity_type == "schema_description",
                EmbeddingRecord.entity_id.in_(table_names),
                EmbeddingRecord.is_deleted.is_(False),
            ).update(stamp, synchronize_session=False)
        db.query(SchemaMetadata).filter(
            SchemaMetadata.dataset_id.in_(dataset_ids), SchemaMetadata.is_deleted.is_(False)
        ).update(stamp, synchronize_session=False)

        db.query(DatasetRecord).filter(
            DatasetRecord.dataset_id.in_(dataset_ids), DatasetRecord.is_deleted.is_(False)
        ).update(stamp, synchronize_session=False)
        db.query(Dataset).filter(
            Dataset.connector_id == connector_id, Dataset.is_deleted.is_(False)
        ).update(stamp, synchronize_session=False)
        db.flush()

    connector.is_deleted = True
    connector.deleted_at = now
    db.commit()


def restore_connector(db: Session, connector_id: uuid.UUID) -> DataConnector:
    connector = get_connector_or_404(db, connector_id, include_deleted=True)
    if not connector.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Connector is not deleted"
        )
    if connector.deleted_at is None or connector.deleted_at < datetime.now(UTC) - timedelta(
        days=SOFT_DELETE_WINDOW_DAYS
    ):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Restore window has expired (7 days). Data has been permanently removed.",
        )

    restore = {"is_deleted": False, "deleted_at": None}

    dataset_ids = [
        row[0]
        for row in db.query(Dataset.id)
        .filter(Dataset.connector_id == connector_id, Dataset.is_deleted.is_(True))
        .all()
    ]
    if dataset_ids:
        kpi_ids = [
            row[0]
            for row in db.query(KPIDefinition.id)
            .filter(KPIDefinition.dataset_id.in_(dataset_ids), KPIDefinition.is_deleted.is_(True))
            .all()
        ]
        if kpi_ids:
            insight_ids = [
                row[0]
                for row in db.query(InsightEvent.id)
                .filter(InsightEvent.kpi_id.in_(kpi_ids), InsightEvent.is_deleted.is_(True))
                .all()
            ]
            if insight_ids:
                db.query(InsightExplanation).filter(
                    InsightExplanation.insight_event_id.in_(insight_ids)
                ).update(restore, synchronize_session=False)
                db.query(DecisionRecord).filter(
                    DecisionRecord.insight_event_id.in_(insight_ids)
                ).update(restore, synchronize_session=False)
            db.query(InsightEvent).filter(InsightEvent.kpi_id.in_(kpi_ids)).update(
                restore, synchronize_session=False
            )
            db.query(KPISnapshot).filter(KPISnapshot.kpi_id.in_(kpi_ids)).update(
                restore, synchronize_session=False
            )
            db.query(KPIVersion).filter(KPIVersion.kpi_id.in_(kpi_ids)).update(
                restore, synchronize_session=False
            )
            db.query(EmbeddingRecord).filter(
                EmbeddingRecord.entity_type == "kpi_definition",
                EmbeddingRecord.entity_id.in_([str(kid) for kid in kpi_ids]),
            ).update(restore, synchronize_session=False)
            db.query(ApprovalRequest).filter(
                ApprovalRequest.entity_type == "kpi",
                ApprovalRequest.entity_id.in_(kpi_ids),
            ).update(restore, synchronize_session=False)

        db.query(KPIDefinition).filter(KPIDefinition.dataset_id.in_(dataset_ids)).update(
            restore, synchronize_session=False
        )

        table_names = [
            row[0]
            for row in db.query(SchemaMetadata.table_name)
            .filter(SchemaMetadata.dataset_id.in_(dataset_ids))
            .all()
        ]
        if table_names:
            db.query(EmbeddingRecord).filter(
                EmbeddingRecord.entity_type == "schema_description",
                EmbeddingRecord.entity_id.in_(table_names),
            ).update(restore, synchronize_session=False)
        db.query(SchemaMetadata).filter(SchemaMetadata.dataset_id.in_(dataset_ids)).update(
            restore, synchronize_session=False
        )

        db.query(DatasetRecord).filter(DatasetRecord.dataset_id.in_(dataset_ids)).update(
            restore, synchronize_session=False
        )
        db.query(Dataset).filter(Dataset.connector_id == connector_id).update(
            restore, synchronize_session=False
        )
        db.flush()

    connector.is_deleted = False
    connector.deleted_at = None
    db.commit()
    db.refresh(connector)
    return connector


def _connection_kwargs(connector: DataConnector, password: str) -> dict[str, Any]:
    return {
        "host": connector.host,
        "port": connector.port,
        "dbname": connector.database_name,
        "user": connector.username,
        "password": password,
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,
    }


def test_connection(connector: DataConnector, password: str | None = None) -> tuple[bool, str]:
    """Attempt to open and immediately close a connection to the source database."""
    resolved_password = password if password is not None else get_decrypted_password(connector)

    try:
        conn = psycopg2.connect(**_connection_kwargs(connector, resolved_password))
        conn.close()
    except psycopg2.OperationalError as exc:
        return False, str(exc).strip()

    return True, "Connection successful"


def test_connection_raw(
    host: str,
    port: int,
    database_name: str,
    username: str,
    password: str,
) -> tuple[bool, str]:
    """Test a connection without a saved connector record."""
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=database_name,
            user=username,
            password=password,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
        )
        conn.close()
    except psycopg2.OperationalError as exc:
        return False, str(exc).strip()
    return True, "Connection successful"


def list_tables(connector: DataConnector) -> list[dict[str, Any]]:
    """Return public tables from the source DB with approximate row counts.

    ``pg_stat_user_tables.n_live_tup`` is a planner statistic that stays at 0 for
    freshly loaded tables until autovacuum/ANALYZE runs, so a real ``COUNT(*)`` is
    used as a fallback whenever the estimate is missing or zero for a base table.
    """
    rows = extract_rows(
        connector,
        """
        SELECT
            t.table_name,
            t.table_type,
            s.n_live_tup AS row_estimate
        FROM information_schema.tables t
        LEFT JOIN pg_stat_user_tables s ON s.relname = t.table_name
        WHERE t.table_schema = 'public'
        ORDER BY t.table_name
        """,
    )

    for row in rows:
        if row.get("table_type") == "BASE TABLE" and not row.get("row_estimate"):
            # Double-quote the identifier to guard against reserved words / mixed case.
            safe_name = '"' + row["table_name"].replace('"', '""') + '"'
            try:
                count_rows = extract_rows(
                    connector, f"SELECT COUNT(*) AS exact_count FROM {safe_name}"
                )
                if count_rows:
                    row["row_estimate"] = count_rows[0]["exact_count"]
            except Exception:
                logger.warning(
                    "Exact row count failed for table %s — keeping estimate",
                    row["table_name"],
                    exc_info=True,
                )

    return rows


def get_table_schema(connector: DataConnector, table_name: str) -> list[dict[str, Any]]:
    """Return column definitions for a single table in the source DB."""
    rows = extract_rows(
        connector,
        """
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %(table_name)s
        ORDER BY ordinal_position
        """,
        {"table_name": table_name},
    )
    return rows


def _live_table_count(connector: DataConnector) -> int | None:
    try:
        return len(list_tables(connector))
    except Exception:
        return None


def _kpi_count(db: Session, connector_id: uuid.UUID) -> int:
    return (
        db.query(func.count(KPIDefinition.id))
        .join(Dataset, Dataset.id == KPIDefinition.dataset_id)
        .filter(Dataset.connector_id == connector_id, Dataset.is_deleted.is_(False))
        .filter(KPIDefinition.is_deleted.is_(False))
        .scalar()
    ) or 0


def _latest_quality_score(db: Session, connector_id: uuid.UUID) -> float | None:
    dataset = (
        db.query(Dataset)
        .filter(Dataset.connector_id == connector_id, Dataset.is_deleted.is_(False))
        .order_by(Dataset.created_at.desc())
        .first()
    )
    return dataset.quality_score if dataset else None


def enrich_connector(db: Session, connector: DataConnector) -> ConnectorResponse:
    return ConnectorResponse(
        id=connector.id,
        name=connector.name,
        connector_type=connector.connector_type,
        host=connector.host,
        port=connector.port,
        database_name=connector.database_name,
        username=connector.username,
        extra_config=connector.extra_config,
        is_active=connector.is_active,
        created_by=connector.created_by,
        created_at=connector.created_at,
        updated_at=connector.updated_at,
        table_count=_live_table_count(connector),
        kpi_count=_kpi_count(db, connector.id),
        quality_score=_latest_quality_score(db, connector.id),
    )


def extract_rows(
    connector: DataConnector, query: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Run a read-only query against the connector's source database and return rows as dicts."""
    password = get_decrypted_password(connector)

    conn = psycopg2.connect(**_connection_kwargs(connector, password))
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            columns = [col.name for col in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        conn.close()
