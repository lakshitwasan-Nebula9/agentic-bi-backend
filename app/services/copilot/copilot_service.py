"""
Copilot Service — session management and message orchestration.

Responsibilities:
  - Create / list / get / delete chat sessions
  - Persist user and assistant messages
  - Route messages through intent classification → handler → response
"""

import logging
import time
import uuid

from sqlalchemy.orm import Session

from app.models.copilot import ChatMessage, ChatSession
from app.models.dashboard import Dashboard
from app.models.user import User
from app.schemas.copilot import (
    ChatMessageResponse,
    ChatSessionDetailResponse,
    ChatSessionResponse,
    ScreenContext,
    SendMessageResponse,
)
from app.services.copilot.handlers.database_qa_handler import DatabaseQAHandler
from app.services.copilot.handlers.greeting_handler import GreetingHandler
from app.services.copilot.handlers.out_of_scope_handler import OutOfScopeHandler
from app.services.copilot.handlers.platform_knowledge_handler import PlatformKnowledgeHandler
from app.services.copilot.handlers.screen_context_handler import ScreenContextHandler
from app.services.copilot.intent_router import classify_intent

logger = logging.getLogger(__name__)

_HISTORY_WINDOW = 20  # max messages loaded as LLM context per turn

_HANDLERS = {
    "greeting": GreetingHandler(),
    "screen_context": ScreenContextHandler(),
    "database_qa": DatabaseQAHandler(),
    "platform_knowledge": PlatformKnowledgeHandler(),
    "out_of_scope": OutOfScopeHandler(),
}


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


def create_session(
    db: Session, current_user: User, screen_context: ScreenContext | None = None
) -> ChatSession:
    primary_dashboard_id = None
    primary_dashboard_name = None
    if screen_context and screen_context.dashboard_id:
        dashboard: Dashboard | None = db.get(Dashboard, screen_context.dashboard_id)
        if dashboard:
            primary_dashboard_id = dashboard.id
            primary_dashboard_name = dashboard.name

    session = ChatSession(
        user_id=current_user.id,
        primary_dashboard_id=primary_dashboard_id,
        primary_dashboard_name=primary_dashboard_name,
        last_screen_context=screen_context.model_dump(mode="json") if screen_context else None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(
    db: Session, current_user: User, dashboard_id: uuid.UUID | None = None
) -> list[ChatSessionResponse]:
    q = db.query(ChatSession).filter(
        ChatSession.user_id == current_user.id, ChatSession.is_active.is_(True)
    )
    if dashboard_id is not None:
        q = q.filter(ChatSession.primary_dashboard_id == dashboard_id)
    sessions = q.order_by(ChatSession.updated_at.desc()).all()
    results = []
    for s in sessions:
        last_msg = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == s.id)
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        resp = ChatSessionResponse.model_validate(s)
        if last_msg:
            resp.last_message_preview = last_msg.content[:100]
        results.append(resp)
    return results


def get_session(
    db: Session, session_id: uuid.UUID, current_user: User
) -> ChatSessionDetailResponse | None:
    session = _get_session_or_none(db, session_id, current_user)
    if session is None:
        return None
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    resp = ChatSessionDetailResponse.model_validate(session)
    resp.messages = [ChatMessageResponse.model_validate(m) for m in messages]
    return resp


def update_session_title(
    db: Session, session_id: uuid.UUID, title: str, current_user: User
) -> ChatSession | None:
    session = _get_session_or_none(db, session_id, current_user)
    if session is None:
        return None
    session.title = title
    db.commit()
    db.refresh(session)
    return session


def delete_session(db: Session, session_id: uuid.UUID, current_user: User) -> bool:
    session = _get_session_or_none(db, session_id, current_user)
    if session is None:
        return False
    session.is_active = False
    db.commit()
    return True


def list_messages(
    db: Session,
    session_id: uuid.UUID,
    current_user: User,
    offset: int = 0,
    limit: int = 50,
) -> list[ChatMessageResponse] | None:
    session = _get_session_or_none(db, session_id, current_user)
    if session is None:
        return None
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [ChatMessageResponse.model_validate(m) for m in messages]


# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------


async def send_message(
    db: Session,
    session_id: uuid.UUID,
    message: str,
    screen_context: ScreenContext | None,
    current_user: User,
) -> SendMessageResponse | None:
    session = _get_session_or_none(db, session_id, current_user)
    if session is None:
        return None

    # Update last known screen context on the session
    if screen_context is not None:
        session.last_screen_context = screen_context.model_dump(mode="json")
        db.flush()

    # Persist user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=message,
        screen_context=screen_context.model_dump(mode="json") if screen_context else None,
    )
    db.add(user_msg)
    db.flush()

    # Load history window for intent + handler context
    history_rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(_HISTORY_WINDOW)
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in history_rows]

    # Intent classification
    intent = await classify_intent(message, screen_context, history)
    logger.info("Copilot intent for session %s: %s", session_id, intent.value)

    # Route to handler (timed)
    handler = _HANDLERS[intent.value]
    _t0 = time.monotonic()
    result = await handler.handle(message, screen_context, history, current_user, db)
    generation_time_ms = int((time.monotonic() - _t0) * 1000)

    # Persist assistant message
    assistant_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=result.response,
        intent=intent.value,
        metadata_json={
            "sql_generated": result.sql_generated,
            "source_references": [r.model_dump() for r in result.source_references],
            "suggested_actions": [a.model_dump() for a in result.suggested_actions],
        },
    )
    db.add(assistant_msg)

    # Auto-set session title from first user message (first turn only)
    if session.title is None:
        session.title = message[:60].strip()

    db.commit()
    db.refresh(assistant_msg)

    return SendMessageResponse(
        session_id=session_id,
        message_id=assistant_msg.id,
        response=result.response,
        intent=intent.value,
        source_references=result.source_references,
        suggested_actions=result.suggested_actions,
        sql_generated=result.sql_generated,
        generation_time_ms=generation_time_ms,
    )


async def send_message_stream(
    db: Session,
    session_id: uuid.UUID,
    message: str,
    screen_context: ScreenContext | None,
    current_user: User,
) -> SendMessageResponse | None:
    """Same as send_message — the router handles word-by-word SSE chunking."""
    return await send_message(db, session_id, message, screen_context, current_user)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_session_or_none(
    db: Session, session_id: uuid.UUID, current_user: User
) -> ChatSession | None:
    return (
        db.query(ChatSession)
        .filter(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
            ChatSession.is_active.is_(True),
        )
        .first()
    )
