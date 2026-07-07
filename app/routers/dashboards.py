import asyncio
import json
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.agents.messaging import DASHBOARD_PERMISSION_CHANGED, stream_name
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, resolve_sse_user
from app.models.user import User
from app.schemas.dashboard import (
    DashboardCreate,
    DashboardDetailResponse,
    DashboardPermissionResponse,
    DashboardPermissionUpsert,
    DashboardResponse,
    DashboardUpdate,
    WidgetCreate,
    WidgetLayoutUpdate,
    WidgetResponse,
    WidgetUpdate,
)
from app.services import dashboard_service, insight_service

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

_optional_bearer = HTTPBearer(auto_error=False)


@router.post("", response_model=DashboardResponse, status_code=status.HTTP_201_CREATED)
def create_dashboard(
    payload: DashboardCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dashboard = dashboard_service.create_dashboard(db, payload, owner_id=current_user.id)
    # Kick off a fresh insight-detection pass so the new dashboard surfaces
    # up-to-date KPI insights — scoped to the chosen connector when given.
    background_tasks.add_task(insight_service.run_detection_bg, payload.connector_id)
    return dashboard


@router.get("", response_model=list[DashboardResponse])
def list_dashboards(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.list_dashboards(db, current_user)


@router.get("/stream")
async def stream_permission_changes(
    token: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    """SSE stream of the caller's dashboard permission changes — Redis-driven.

    Tails the ``dashboard_permission_changed`` stream and forwards only events
    addressed to the authenticated user, so their UI can refetch access the
    instant a grant/upgrade/revoke happens. EventSource cannot set headers, so
    the JWT may be passed as ``?token=`` (a Bearer header also works). A
    ``:keepalive`` comment is emitted on idle to keep proxies from timing out.

    Declared before ``/{dashboard_id}`` so the literal path isn't shadowed.
    """
    raw_token = (credentials.credentials if credentials else None) or token
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = resolve_sse_user(raw_token, db)
    user_id = str(user.id)

    async def event_generator():
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        stream = stream_name(DASHBOARD_PERMISSION_CHANGED)
        last_id = "$"  # only events produced after this connection opens
        try:
            while True:
                try:
                    response = await client.xread({stream: last_id}, block=15000, count=10)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 — survive transient broker errors
                    await asyncio.sleep(1.0)
                    continue

                if not response:
                    yield ": keepalive\n\n"  # XREAD block timed out → idle keepalive
                    continue

                for _stream, messages in response:
                    for message_id, fields in messages:
                        last_id = message_id
                        payload = fields.get("payload")
                        if not payload:
                            continue
                        try:
                            data = json.loads(payload)
                        except ValueError:
                            continue
                        if data.get("user_id") == user_id:
                            yield f"data: {payload}\n\n"
        finally:
            await client.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{dashboard_id}", response_model=DashboardDetailResponse)
def get_dashboard(
    dashboard_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.get_viewable_dashboard_or_404(db, dashboard_id, current_user)


@router.patch("/{dashboard_id}", response_model=DashboardResponse)
def update_dashboard(
    dashboard_id: uuid.UUID,
    payload: DashboardUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.update_dashboard(db, dashboard_id, payload, actor=current_user)


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dashboard(
    dashboard_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dashboard_service.delete_dashboard(db, dashboard_id, owner_id=current_user.id)


@router.put("/{dashboard_id}/layout", response_model=DashboardDetailResponse)
def save_layout(
    dashboard_id: uuid.UUID,
    payload: list[WidgetLayoutUpdate],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.save_layout(db, dashboard_id, payload, actor=current_user)


@router.post(
    "/{dashboard_id}/widgets", response_model=WidgetResponse, status_code=status.HTTP_201_CREATED
)
def add_widget(
    dashboard_id: uuid.UUID,
    payload: WidgetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.add_widget(db, dashboard_id, payload, actor=current_user)


@router.patch("/{dashboard_id}/widgets/{widget_id}", response_model=WidgetResponse)
def update_widget(
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    payload: WidgetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.update_widget(db, dashboard_id, widget_id, payload, actor=current_user)


@router.delete("/{dashboard_id}/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_widget(
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dashboard_service.delete_widget(db, dashboard_id, widget_id, actor=current_user)


@router.get("/{dashboard_id}/permissions", response_model=list[DashboardPermissionResponse])
def list_dashboard_permissions(
    dashboard_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.list_permissions(db, dashboard_id, actor=current_user)


@router.put(
    "/{dashboard_id}/permissions/{user_id}",
    response_model=DashboardPermissionResponse,
)
def upsert_dashboard_permission(
    dashboard_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: DashboardPermissionUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.grant_permission(
        db, dashboard_id, user_id, payload.access_level, actor=current_user
    )


@router.delete(
    "/{dashboard_id}/permissions/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_dashboard_permission(
    dashboard_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dashboard_service.revoke_permission(db, dashboard_id, user_id, actor=current_user)
