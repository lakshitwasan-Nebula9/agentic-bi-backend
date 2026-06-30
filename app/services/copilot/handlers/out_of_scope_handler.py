"""
Out-of-Scope handler.

Politely declines and redirects to what the Copilot can actually help with.
No LLM call needed — static response.
"""

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.copilot import ScreenContext, SuggestedAction
from app.services.copilot.handlers.base_handler import BaseHandler, HandlerResult

_RESPONSE = (
    "That's outside what I can help with — I'm focused on your business intelligence platform. "
    "I can answer questions about your KPIs, insights, decisions, and reports, "
    "query your connected data sources, or explain what's shown on your current screen. "
    "What would you like to know about your data?"
)


class OutOfScopeHandler(BaseHandler):
    async def handle(
        self,
        message: str,
        screen_context: ScreenContext | None,
        history: list[dict],
        current_user: User,
        db: Session,
    ) -> HandlerResult:
        return HandlerResult(
            response=_RESPONSE,
            suggested_actions=[
                SuggestedAction(label="View KPIs", route="/kpis"),
                SuggestedAction(label="View Insights", route="/insights"),
            ],
        )
