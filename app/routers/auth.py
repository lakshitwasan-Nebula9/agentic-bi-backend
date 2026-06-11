from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.org_settings import OrgSettings
from app.models.user import User, UserRole
from app.schemas.auth import (
    GoogleLoginRequest,
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import create_access_token, hash_password, verify_password
from app.services.google_oauth_service import GoogleOAuthError, verify_google_id_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    is_first_user = db.query(User).first() is None
    if is_first_user:
        db.add(OrgSettings(name=payload.org_name or "My Organization"))

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=UserRole.EXECUTIVE if is_first_user else UserRole.ANALYST,
        is_admin=is_first_user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user_id=user.id, role=user.role.value, is_admin=user.is_admin)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if (
        not user
        or not user.hashed_password
        or not verify_password(payload.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    token = create_access_token(user_id=user.id, role=user.role.value, is_admin=user.is_admin)
    return TokenResponse(access_token=token)


@router.post("/google", response_model=TokenResponse)
def google_login(payload: GoogleLoginRequest, db: Session = Depends(get_db)):
    try:
        google_user = verify_google_id_token(payload.id_token)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    user = (
        db.query(User)
        .filter(
            User.auth_provider == "google",
            User.external_subject == google_user.subject,
        )
        .first()
    )

    if user is None:
        user = db.query(User).filter(User.email == google_user.email).first()
        if user is None:
            user = User(
                email=google_user.email,
                hashed_password=None,
                auth_provider="google",
                external_subject=google_user.subject,
                role=UserRole.ANALYST,
                is_admin=False,
            )
            db.add(user)
        else:
            user.auth_provider = "google"
            user.external_subject = google_user.subject

        db.commit()
        db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    token = create_access_token(user_id=user.id, role=user.role.value, is_admin=user.is_admin)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user
