import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserRole(str, enum.Enum):
    EXECUTIVE = "executive"
    MANAGER = "manager"
    ANALYST = "analyst"


# Lower rank number = higher authority (EXECUTIVE > MANAGER > ANALYST).
# Canonical home for the role hierarchy: lives on the model so both routers
# (via security.py) and pure services (hitl_workflow_service) can import it
# without creating an import cycle.
ROLE_RANK = {UserRole.EXECUTIVE: 0, UserRole.MANAGER: 1, UserRole.ANALYST: 2}


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String, nullable=True)
    auth_provider: Mapped[str] = mapped_column(String, default="local", nullable=False)
    external_subject: Mapped[str | None] = mapped_column(
        String, unique=True, nullable=True, index=True
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole, name="user_role", values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        nullable=False,
        default=UserRole.ANALYST,
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
