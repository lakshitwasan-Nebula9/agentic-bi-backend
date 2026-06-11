import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import org_settings as org_settings_crud
from app.crud import user as user_crud
from app.models.org_settings import OrgSettings
from app.models.user import User, UserRole
from app.schemas.auth import GoogleLoginRequest, LoginRequest, SignupRequest
from app.services.google_oauth_service import GoogleOAuthError, verify_google_id_token

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(*, user_id: uuid.UUID, role: str, is_admin: bool) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role,
        "is_admin": is_admin,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc


def signup_user(db: Session, payload: SignupRequest) -> User:
    if user_crud.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    is_first_user = not user_crud.has_any_user(db)
    if is_first_user:
        org_settings_crud.create_org_settings(
            db, OrgSettings(name=payload.org_name or "My Organization")
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=UserRole.EXECUTIVE if is_first_user else UserRole.ANALYST,
        is_admin=is_first_user,
    )
    return user_crud.create_user(db, user)


def authenticate_user(db: Session, payload: LoginRequest) -> User:
    user = user_crud.get_user_by_email(db, payload.email)
    if (
        user is None
        or not user.hashed_password
        or not verify_password(payload.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    return user


def login_with_google(db: Session, payload: GoogleLoginRequest) -> User:
    try:
        google_user = verify_google_id_token(payload.id_token)
    except GoogleOAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = user_crud.get_user_by_external_subject(db, "google", google_user.subject)

    if user is None:
        user = user_crud.get_user_by_email(db, google_user.email)
        if user is None:
            user = user_crud.create_user(
                db,
                User(
                    email=google_user.email,
                    hashed_password=None,
                    auth_provider="google",
                    external_subject=google_user.subject,
                    role=UserRole.ANALYST,
                    is_admin=False,
                ),
            )
        else:
            user = user_crud.update_user(
                db,
                user,
                {"auth_provider": "google", "external_subject": google_user.subject},
            )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    return user
