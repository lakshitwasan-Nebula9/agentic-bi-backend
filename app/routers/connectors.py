import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.security import get_current_user, require_role
from app.crud import sync_log as sync_log_crud
from app.crud import user as user_crud
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
from app.schemas.sync_log import SyncLogResponse
from app.services import connector_service
from app.services.auth_service import decode_access_token

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
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connectors = connector_service.list_connectors(db, include_deleted=include_deleted)
    return [connector_service.enrich_connector(db, c) for c in connectors]


@router.get("/{connector_id}", response_model=ConnectorResponse)
def get_connector(
    connector_id: uuid.UUID,
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = connector_service.get_connector_or_404(
        db, connector_id, include_deleted=include_deleted
    )
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


@router.post("/{connector_id}/restore", response_model=ConnectorResponse)
def restore_connector(
    connector_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*MANAGE_ROLES)),
):
    connector = connector_service.restore_connector(db, connector_id)
    return connector_service.enrich_connector(db, connector)


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


@router.get("/{connector_id}/sync-logs", response_model=list[SyncLogResponse])
def list_connector_sync_logs(
    connector_id: uuid.UUID,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated sync log history for a connector."""
    connector_service.get_connector_or_404(db, connector_id)
    return sync_log_crud.list_sync_logs(db, connector_id, limit=limit, offset=offset)


def _resolve_sse_user(token: str, db: Session) -> User:
    """Validate a raw JWT string and return the User — used by the SSE endpoint
    which receives the token as a query param because EventSource cannot set headers."""
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = decode_access_token(token)
    except ValueError:
        raise exc from None
    user_id = payload.get("sub")
    if not user_id:
        raise exc
    user = user_crud.get_user_by_id(db, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise exc
    return user


_optional_bearer = HTTPBearer(auto_error=False)


@router.get("/{connector_id}/sync-logs/stream")
async def stream_sync_logs(
    connector_id: uuid.UUID,
    since: datetime | None = Query(default=None),
    token: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    """SSE stream that pushes new SyncLog entries in real time.

    EventSource cannot set headers, so the JWT may be passed as ``?token=``.
    A standard ``Authorization: Bearer`` header is also accepted.
    Send ``?since=<ISO-timestamp>`` to replay entries the client may have missed.
    A ``:keepalive`` comment is sent every 15 s to prevent proxy timeouts.
    """
    raw_token = (credentials.credentials if credentials else None) or token
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    _resolve_sse_user(raw_token, db)

    async def event_generator():
        last_seen: datetime = since or datetime.now(UTC)
        keepalive_counter = 0

        while True:
            poll_db: Session = SessionLocal()
            try:
                new_logs = sync_log_crud.list_sync_logs_since(poll_db, connector_id, last_seen)
                for log in new_logs:
                    payload = SyncLogResponse.model_validate(log).model_dump_json()
                    yield f"data: {payload}\n\n"
                    last_seen = log.created_at
            finally:
                poll_db.close()

            await asyncio.sleep(2)
            keepalive_counter += 1
            if keepalive_counter >= 8:  # every ~15 s
                yield ": keepalive\n\n"
                keepalive_counter = 0

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
