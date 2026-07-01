import uuid

from pydantic import BaseModel, ConfigDict, EmailStr

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
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str | None
    role: UserRole
    is_active: bool
