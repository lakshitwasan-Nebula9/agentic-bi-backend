from pydantic import BaseModel, EmailStr

from app.models.user import UserRole


class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str
    role: UserRole
    name: str | None = None


class UserUpdateRequest(BaseModel):
    name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
