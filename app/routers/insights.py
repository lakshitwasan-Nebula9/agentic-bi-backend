import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.crud import insight as insight_crud
from app.crud import user as user_crud
from app.schemas.insight import InsightEventResponse
from app.services import insight_service
from app.services.auth_service import decode_access_token
from app.ws.connection_manager import connection_manager

router = APIRouter(tags=["insights"])

_optional_bearer = HTTPBearer(auto_error=False)


def _resolve_sse_user(token: str, db: Session):
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


@router.websocket("/insights/ws")
async def insights_ws(websocket: WebSocket) -> None:
    """Live insight feed for the frontend.

    Clients connect and receive ``{"type": "insight_detected", "data": {...}}``
    messages (the InsightEventResponse payload) as detection runs. Inbound
    messages are ignored — they only serve to detect a client disconnect.
    """
    await connection_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket)


@router.post("/insights/detect", response_model=list[InsightEventResponse], status_code=201)
async def detect_insights(db: Session = Depends(get_db)):
    """Run anomaly detection across all certified KPIs and persist new InsightEvents.

    Each new event is narrated by Gemini in the same pass (best-effort).
    Idempotent — skips KPIs whose latest period has already been analysed.
    """
    return await insight_service.detect_all(db)


@router.get("/insights", response_model=list[InsightEventResponse])
def list_insights(
    kpi_id: uuid.UUID | None = None,
    insight_type: str | None = None,
    is_anomaly: bool | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return insight_service.list_insights(
        db, kpi_id=kpi_id, insight_type=insight_type, is_anomaly=is_anomaly, limit=limit
    )


@router.get("/insights/kpi/{kpi_id}", response_model=list[InsightEventResponse])
def list_insights_for_kpi(kpi_id: uuid.UUID, limit: int = 50, db: Session = Depends(get_db)):
    return insight_service.list_insights(db, kpi_id=kpi_id, limit=limit)


@router.post("/insights/kpi/{kpi_id}/detect", response_model=InsightEventResponse | None)
async def detect_for_kpi(kpi_id: uuid.UUID, db: Session = Depends(get_db)):
    """Run detection for a single KPI. Returns null when conditions aren't met."""
    return await insight_service.detect_for_kpi(db, kpi_id)


@router.get("/insights/stream")
async def stream_insights(
    since: datetime | None = Query(default=None),
    token: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    """SSE stream that pushes new InsightEvent rows in real time.

    EventSource cannot set headers, so the JWT may be passed as ``?token=``.
    A standard ``Authorization: Bearer`` header is also accepted.
    Send ``?since=<ISO-timestamp>`` to replay events the client may have missed.
    A ``:keepalive`` comment is sent every ~15 s to prevent proxy timeouts.
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
                new_events = insight_crud.list_insight_events_since(poll_db, last_seen)
                for event in new_events:
                    payload = InsightEventResponse.model_validate(event).model_dump_json()
                    yield f"data: {payload}\n\n"
                    last_seen = event.created_at
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
