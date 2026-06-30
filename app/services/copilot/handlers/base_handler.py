"""Base class shared by all Copilot intent handlers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.copilot import ScreenContext, SourceReference, SuggestedAction


@dataclass
class HandlerResult:
    response: str
    source_references: list[SourceReference] = field(default_factory=list)
    suggested_actions: list[SuggestedAction] = field(default_factory=list)
    sql_generated: str | None = None


class BaseHandler(ABC):
    @abstractmethod
    async def handle(
        self,
        message: str,
        screen_context: ScreenContext | None,
        history: list[dict],
        current_user: User,
        db: Session,
    ) -> HandlerResult:
        """Process the message and return a HandlerResult."""
