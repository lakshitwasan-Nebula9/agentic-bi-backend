import uuid

from sqlalchemy.orm import Session

from app.models.user import User


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_user_by_external_subject(
    db: Session, auth_provider: str, external_subject: str
) -> User | None:
    return (
        db.query(User)
        .filter(
            User.auth_provider == auth_provider,
            User.external_subject == external_subject,
        )
        .first()
    )


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.created_at).all()


def has_any_user(db: Session) -> bool:
    return db.query(User).first() is not None


def create_user(db: Session, user: User) -> User:
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user: User, updates: dict) -> User:
    for field, value in updates.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user
