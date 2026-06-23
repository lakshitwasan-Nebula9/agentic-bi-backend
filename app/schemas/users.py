from pydantic import BaseModel

from app.models.user import UserRole


class UserUpdateRequest(BaseModel):
    name: str | None = None
    role: UserRole | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
