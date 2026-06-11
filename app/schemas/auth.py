import uuid

from pydantic import BaseModel, EmailStr

from app.models.user import UserRole


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    org_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    id_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: UserRole
    is_admin: bool
    is_active: bool

    class Config:
        from_attributes = True
