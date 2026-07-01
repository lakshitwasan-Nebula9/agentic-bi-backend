import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud import notification as notification_crud
from app.crud import user as user_crud
from app.schemas.notification import NotificationResponse, UnreadCountResponse
from app.services.auth_service import decode_access_token

router = APIRouter(tags=["notifications"])

_optional_bearer = HTTPBearer(auto_error=False)


def _resolve_user(
    credentials: HTTPAuthorizationCredentials | None,
    token: str | None,
    db: Session,
):
    raw_token = (credentials.credentials if credentials else None) or token
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(raw_token)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from err
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = user_crud.get_user_by_id(db, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    token: str | None = Query(default=None),
):
    user = _resolve_user(credentials, token, db)
    return UnreadCountResponse(unread_count=notification_crud.get_unread_count(db, user.id))


@router.get("/notifications", response_model=list[NotificationResponse])
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    token: str | None = Query(default=None),
):
    user = _resolve_user(credentials, token, db)
    return notification_crud.list_notifications(db, user.id, unread_only=unread_only, limit=limit)


@router.patch("/notifications/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    token: str | None = Query(default=None),
):
    user = _resolve_user(credentials, token, db)
    updated = notification_crud.mark_all_read(db, user.id)
    return {"marked_read": updated}


@router.patch("/notifications/{notification_id}/read", response_model=NotificationResponse)
def mark_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    token: str | None = Query(default=None),
):
    user = _resolve_user(credentials, token, db)
    n = notification_crud.mark_read(db, notification_id, user.id)
    if n is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return n
