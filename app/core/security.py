import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud import user as user_crud
from app.models.user import ROLE_RANK, User, UserRole
from app.services.auth_service import decode_access_token

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise credentials_exception from exc

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = user_crud.get_user_by_id(db, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise credentials_exception

    return user


def require_min_role(minimum: UserRole):
    """Dependency that requires the caller's role to be at least ``minimum``.

    Uses ``ROLE_RANK`` (lower number = higher authority), so a caller passes
    when their rank is <= the minimum's rank (i.e. equal or more senior).
    """

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK[current_user.role] > ROLE_RANK[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return dependency


require_manager = require_min_role(UserRole.MANAGER)
require_executive = require_min_role(UserRole.EXECUTIVE)


def require_role(*allowed_roles: UserRole):
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return dependency
