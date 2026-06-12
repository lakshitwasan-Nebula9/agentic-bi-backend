from pydantic import BaseModel

from app.models.user import UserRole


class UserUpdateRequest(BaseModel):
    role: UserRole | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
