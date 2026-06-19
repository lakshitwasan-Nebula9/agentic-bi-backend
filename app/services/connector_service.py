import uuid
from typing import Any

import psycopg2
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.crud import connector as connector_crud
from app.models.connector import DataConnector
from app.schemas.connector import ConnectorCreate, ConnectorUpdate
from app.services.encryption_service import decrypt_value, encrypt_value

CONNECT_TIMEOUT_SECONDS = 5


def get_decrypted_password(connector: DataConnector) -> str:
    return decrypt_value(connector.encrypted_password)


def encrypt_password(password: str) -> str:
    return encrypt_value(password)


def get_connector_or_404(db: Session, connector_id: uuid.UUID) -> DataConnector:
    connector = connector_crud.get_connector(db, connector_id)
    if connector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    return connector


def list_connectors(db: Session) -> list[DataConnector]:
    return connector_crud.list_connectors(db)


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
    connector_crud.delete_connector(db, connector)


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
    """Return public tables from the source DB with approximate row counts."""
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
