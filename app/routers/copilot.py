import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.copilot import (
    ChatMessageResponse,
    ChatSessionDetailResponse,
    ChatSessionResponse,
    CreateSessionRequest,
    SendMessageRequest,
    SendMessageResponse,
    UpdateSessionRequest,
)
from app.services.copilot import copilot_service

router = APIRouter(prefix="/copilot", tags=["copilot"])


@router.post("/sessions", response_model=ChatSessionResponse, status_code=201)
async def create_session(
    req: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = copilot_service.create_session(db, current_user, req.screen_context)
    resp = ChatSessionResponse.model_validate(session)
    return resp


@router.get("/sessions", response_model=list[ChatSessionResponse])
def list_sessions(
    dashboard_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return copilot_service.list_sessions(db, current_user, dashboard_id=dashboard_id)


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
def get_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = copilot_service.get_session(db, session_id, current_user)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return result


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
def update_session(
    session_id: uuid.UUID,
    req: UpdateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = copilot_service.update_session_title(db, session_id, req.title, current_user)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return ChatSessionResponse.model_validate(session)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted = copilot_service.delete_session(db, session_id, current_user)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")


@router.post("/sessions/{session_id}/messages", response_model=SendMessageResponse)
async def send_message(
    session_id: uuid.UUID,
    req: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = await copilot_service.send_message(
        db=db,
        session_id=session_id,
        message=req.message,
        screen_context=req.screen_context,
        current_user=current_user,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return result


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
def list_messages(
    session_id: uuid.UUID,
    offset: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    messages = copilot_service.list_messages(
        db, session_id, current_user, offset=offset, limit=limit
    )
    if messages is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return messages


@router.post("/sessions/{session_id}/messages/stream")
async def stream_message(
    session_id: uuid.UUID,
    req: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    SSE endpoint — streams the assistant response token-by-token.

    Event types emitted:
      data: {"type": "token",  "content": "<chunk>"}
      data: {"type": "done",   "session_id": "...", "message_id": "...",
                               "intent": "...", "generation_time_ms": 1234,
                               "source_references": [...], "suggested_actions": [...],
                               "sql_generated": null}
      data: {"type": "error",  "detail": "<message>"}
    """

    async def _event_stream():
        result = await copilot_service.send_message_stream(
            db=db,
            session_id=session_id,
            message=req.message,
            screen_context=req.screen_context,
            current_user=current_user,
        )
        if result is None:
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Session not found'})}\n\n"
            return

        # Stream the response text word-by-word so the frontend can render progressively.
        words = result.response.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == 0 else " " + word
            yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

        # Final event carries all metadata
        done_payload = {
            "type": "done",
            "session_id": str(result.session_id),
            "message_id": str(result.message_id),
            "intent": result.intent,
            "generation_time_ms": result.generation_time_ms,
            "source_references": [r.model_dump() for r in result.source_references],
            "suggested_actions": [a.model_dump() for a in result.suggested_actions],
            "sql_generated": result.sql_generated,
        }
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
