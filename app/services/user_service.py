import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.crud import user as user_crud
from app.models.user import User, UserRole
from app.schemas.users import UserUpdateRequest

# Lower rank number = higher authority (EXECUTIVE > MANAGER > ANALYST).
ROLE_RANK = {UserRole.EXECUTIVE: 0, UserRole.MANAGER: 1, UserRole.ANALYST: 2}


def list_users(db: Session) -> list[User]:
    return user_crud.list_users(db)


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
            detail="Admins cannot change their own role, admin status, or active status",
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
