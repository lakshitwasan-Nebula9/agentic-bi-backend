import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.user import User, UserRole
from app.schemas.connector import (
    ColumnInfo,
    ConnectionTestRequest,
    ConnectionTestResult,
    ConnectorCreate,
    ConnectorResponse,
    ConnectorUpdate,
    TableInfo,
)
from app.services import connector_service

router = APIRouter(prefix="/connectors", tags=["connectors"])

MANAGE_ROLES = (UserRole.ANALYST, UserRole.MANAGER, UserRole.EXECUTIVE)


@router.post("", response_model=ConnectorResponse, status_code=status.HTTP_201_CREATED)
def create_connector(
    payload: ConnectorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    return connector_service.create_connector(db, payload, created_by=current_user.id)


@router.get("", response_model=list[ConnectorResponse])
def list_connectors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connectors = connector_service.list_connectors(db)
    return [connector_service.enrich_connector(db, c) for c in connectors]


@router.get("/{connector_id}", response_model=ConnectorResponse)
def get_connector(
    connector_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = connector_service.get_connector_or_404(db, connector_id)
    return connector_service.enrich_connector(db, connector)


@router.patch("/{connector_id}", response_model=ConnectorResponse)
def update_connector(
    connector_id: uuid.UUID,
    payload: ConnectorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    return connector_service.update_connector(db, connector_id, payload)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connector(
    connector_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    connector_service.delete_connector(db, connector_id)


@router.post("/test", response_model=ConnectionTestResult)
def test_connection_raw(
    payload: ConnectionTestRequest,
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    """Test credentials before saving a connector."""
    success, message = connector_service.test_connection_raw(
        host=payload.host,
        port=payload.port,
        database_name=payload.database_name,
        username=payload.username,
        password=payload.password,
    )
    return ConnectionTestResult(success=success, message=message)


@router.post("/{connector_id}/test", response_model=ConnectionTestResult)
def test_connector_connection(
    connector_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    """Test the connection for an already-saved connector."""
    connector = connector_service.get_connector_or_404(db, connector_id)
    success, message = connector_service.test_connection(connector)
    return ConnectionTestResult(success=success, message=message)


@router.get("/{connector_id}/tables", response_model=list[TableInfo])
def list_connector_tables(
    connector_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List public tables in the source database with approximate row counts."""
    connector = connector_service.get_connector_or_404(db, connector_id)
    rows = connector_service.list_tables(connector)
    return [
        TableInfo(
            table_name=r["table_name"],
            table_type=r["table_type"],
            row_estimate=r.get("row_estimate"),
        )
        for r in rows
    ]


@router.get("/{connector_id}/tables/{table_name}/schema", response_model=list[ColumnInfo])
def get_connector_table_schema(
    connector_id: uuid.UUID,
    table_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return column definitions for a single table in the source database."""
    connector = connector_service.get_connector_or_404(db, connector_id)
    rows = connector_service.get_table_schema(connector, table_name)
    return [
        ColumnInfo(
            column_name=r["column_name"],
            data_type=r["data_type"],
            is_nullable=r["is_nullable"] == "YES",
            column_default=r.get("column_default"),
        )
        for r in rows
    ]
