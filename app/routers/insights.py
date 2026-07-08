import asyncio
import uuid
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.agents.messaging import INSIGHT_DETECTED, stream_name
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.security import get_current_user, require_manager
from app.crud import insight as insight_crud
from app.crud import user as user_crud
from app.crud.explanation import get_by_insight
from app.models.insight import InsightEvent
from app.models.user import User
from app.schemas.explanation import InsightExplanationResponse
from app.schemas.insight import InsightEventResponse
from app.schemas.insight_feedback import (
    InsightFeedbackCreate,
    InsightFeedbackResponse,
    InsightFeedbackSummary,
)
from app.schemas.insight_guidance import InsightGuidanceResponse
from app.services import insight_feedback_service, insight_guidance_service, insight_service
from app.services.auth_service import decode_access_token
from app.services.explainability_service import build_explanation

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
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return insight_service.list_insights(
        db,
        kpi_id=kpi_id,
        insight_type=insight_type,
        is_anomaly=is_anomaly,
        limit=limit,
        include_deleted=include_deleted,
    )


@router.get("/insights/kpi/{kpi_id}", response_model=list[InsightEventResponse])
def list_insights_for_kpi(
    kpi_id: uuid.UUID,
    limit: int = 50,
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return insight_service.list_insights(
        db, kpi_id=kpi_id, limit=limit, include_deleted=include_deleted
    )


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
    """SSE stream of new InsightEvents — Redis-driven, no DB polling.

    On connect, replays anything since ``?since=<ISO-timestamp>`` from the DB so a
    reconnecting client catches up, then tails the Redis ``insight_detected`` stream
    and pushes each insight the instant it is detected. EventSource cannot set
    headers, so the JWT may be passed as ``?token=`` (a Bearer header also works).
    A ``:keepalive`` comment is emitted on idle to keep proxies from timing out.
    """
    raw_token = (credentials.credentials if credentials else None) or token
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    _resolve_sse_user(raw_token, db)

    async def event_generator():
        # 1. Catch-up: replay events the client missed since `since` (DB read, once).
        if since is not None:
            replay_db: Session = SessionLocal()
            try:
                for event in insight_crud.list_insight_events_since(replay_db, since):
                    payload = InsightEventResponse.model_validate(event).model_dump_json()
                    yield f"data: {payload}\n\n"
            finally:
                replay_db.close()

        # 2. Live: tail the Redis stream — event-driven push, no polling.
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        stream = stream_name(INSIGHT_DETECTED)
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
                        if payload:  # already an InsightEventResponse JSON string
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


@router.get("/insights/{insight_id}/explanation", response_model=InsightExplanationResponse)
async def get_insight_explanation(insight_id: uuid.UUID, db: Session = Depends(get_db)):
    """Explainability receipt for the insight drill-down modal.

    Normally written by the Explainability Agent on the ``insight_detected`` event;
    if the receipt is missing (worker not yet processed, or broker down) it is built
    lazily on first request so the modal always has data.
    """
    insight = (
        db.query(InsightEvent)
        .filter(InsightEvent.id == insight_id, InsightEvent.is_deleted.is_(False))
        .first()
    )
    if insight is None:
        raise HTTPException(status_code=404, detail=f"Insight {insight_id} not found")

    record = get_by_insight(db, insight_id) or await build_explanation(db, insight)

    response = InsightExplanationResponse.model_validate(record)
    response.rationale = insight.llm_summary
    return response


def _get_insight_or_404(db: Session, insight_id: uuid.UUID) -> InsightEvent:
    insight = (
        db.query(InsightEvent)
        .filter(InsightEvent.id == insight_id, InsightEvent.is_deleted.is_(False))
        .first()
    )
    if insight is None:
        raise HTTPException(status_code=404, detail=f"Insight {insight_id} not found")
    return insight


@router.post(
    "/insights/{insight_id}/feedback",
    response_model=InsightFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_insight_feedback(
    insight_id: uuid.UUID,
    payload: InsightFeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Thumbs up/down + optional comment. Upserts — a second call from the same
    user updates their existing vote rather than creating a duplicate."""
    insight = _get_insight_or_404(db, insight_id)
    return insight_feedback_service.submit_feedback(
        db,
        insight=insight,
        user=current_user,
        rating=payload.rating,
        comment=payload.comment,
    )


@router.get("/insights/{insight_id}/feedback", response_model=InsightFeedbackSummary)
def get_insight_feedback(
    insight_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_insight_or_404(db, insight_id)
    return insight_feedback_service.get_summary(db, insight_id=insight_id, user_id=current_user.id)


@router.delete("/insights/{insight_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def retract_insight_feedback(
    insight_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_insight_or_404(db, insight_id)
    removed = insight_feedback_service.retract_feedback(
        db, insight_id=insight_id, user=current_user
    )
    if not removed:
        raise HTTPException(status_code=404, detail="No feedback to retract")


@router.get("/insights/guidance", response_model=InsightGuidanceResponse | None)
def get_current_guidance(
    _: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Current prompt guidance the Insight Agent is following, derived from
    accumulated user feedback. Manager+ only — visibility into what's steering
    the agent's narration."""
    from app.crud import insight_guidance as guidance_crud

    return guidance_crud.get_active(db)


@router.post(
    "/insights/guidance/generate",
    response_model=InsightGuidanceResponse | None,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_guidance_generation(
    _: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Force a guidance regeneration cycle now instead of waiting for the
    weekly cron. Returns null if there wasn't enough new feedback to update it."""
    return await insight_guidance_service.generate_guidance(db)
