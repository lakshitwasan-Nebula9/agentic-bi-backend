import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.crud import user as user_crud
from app.models.user import ROLE_RANK, User
from app.schemas.users import UserCreateRequest, UserUpdateRequest
from app.services.auth_service import hash_password


def list_users(db: Session) -> list[User]:
    return user_crud.list_users(db)


def create_user(db: Session, payload: UserCreateRequest, current_user: User) -> User:
    if user_crud.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Same rank rule as update_user: a creator cannot mint a role at or above their own.
    if ROLE_RANK[current_user.role] >= ROLE_RANK[payload.role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot create a user at or above your own role level",
        )

    user = User(
        email=payload.email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
        auth_provider="local",
        role=payload.role,
        is_active=True,
    )
    return user_crud.create_user(db, user)


def get_user_or_404(db: Session, user_id: uuid.UUID) -> User:
    user = user_crud.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def update_user(
    db: Session, user_id: uuid.UUID, payload: UserUpdateRequest, current_user: User
) -> User:
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role or active status",
        )

    user = get_user_or_404(db, user_id)

    if ROLE_RANK[current_user.role] >= ROLE_RANK[user.role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify a user at or above your role level",
        )

    updates = payload.model_dump(exclude_unset=True)
    if "role" in updates and ROLE_RANK[current_user.role] >= ROLE_RANK[updates["role"]]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot promote a user to your role level or above",
        )

    if not updates:
        return user

    return user_crud.update_user(db, user, updates)
