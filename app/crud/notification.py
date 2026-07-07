import uuid

from sqlalchemy.orm import Session

from app.models.notification import Notification


def create_notification(
    db: Session,
    user_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str | None = None,
    severity: str = "info",
    source_id: str | None = None,
    source_type: str | None = None,
) -> Notification:
    n = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        body=body,
        severity=severity,
        source_id=source_id,
        source_type=source_type,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def list_notifications(
    db: Session,
    user_id: uuid.UUID,
    unread_only: bool = False,
    limit: int = 50,
) -> list[Notification]:
    q = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    return q.order_by(Notification.created_at.desc()).limit(limit).all()


def get_unread_count(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
        .count()
    )


def mark_read(db: Session, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification | None:
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if n:
        n.is_read = True
        db.commit()
        db.refresh(n)
    return n


def mark_all_read(db: Session, user_id: uuid.UUID) -> int:
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
        .update({"is_read": True})
    )
    db.commit()
    return updated


def get_latest_for_source(
    db: Session,
    user_id: uuid.UUID,
    notification_type: str,
    source_type: str,
    source_id: str,
) -> Notification | None:
    """Most recent notification for one (user, type, source) triple.

    Used to upsert-in-place for repeat actions on the same underlying event
    (e.g. re-submitting the same insight-feedback rating just to attach a
    comment) instead of spamming a duplicate notification per call.
    """
    return (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.notification_type == notification_type,
            Notification.source_type == source_type,
            Notification.source_id == source_id,
        )
        .order_by(Notification.created_at.desc())
        .first()
    )


def update_notification(
    db: Session,
    notification: Notification,
    *,
    title: str | None = None,
    body: str | None = None,
    severity: str | None = None,
) -> Notification:
    if title is not None:
        notification.title = title
    if body is not None:
        notification.body = body
    if severity is not None:
        notification.severity = severity
    db.commit()
    db.refresh(notification)
    return notification


def delete_notification(db: Session, notification: Notification) -> None:
    db.delete(notification)
    db.commit()
