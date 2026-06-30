"""
Greeting / Conversation handler.

Handles casual messages, capability questions, and general chat.
No DB reads needed — just Gemini + platform context.
"""

import logging

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.copilot import ScreenContext
from app.services.copilot.gemini_client import generate_text
from app.services.copilot.handlers.base_handler import BaseHandler, HandlerResult

logger = logging.getLogger(__name__)

_SYSTEM = """You are the AI Copilot for an enterprise Business Intelligence platform.
You help business users understand their data, KPIs, insights, and reports.

You can:
- Answer questions about KPIs, insights, decisions, and reports stored in the platform
- Explain anomalies and trends detected in the data
- Generate SQL queries and run them against connected data sources
- Summarise what is shown on the current screen (dashboard, KPI detail, report)
- Guide users through the platform capabilities

You cannot:
- Access external websites or real-time information outside the platform
- Perform destructive database operations
- Provide personal, legal, or medical advice

Keep responses concise (3–5 sentences) unless the user asks for detail.
Be friendly, professional, and action-oriented."""


def _build_prompt(message: str, user_name: str | None, current_page: str | None) -> str:
    context_line = f"The user is currently on the '{current_page}' page." if current_page else ""
    name_line = f"The user's name is {user_name}." if user_name else ""
    return f"{name_line} {context_line}\n\nUser: {message}".strip()


class GreetingHandler(BaseHandler):
    async def handle(
        self,
        message: str,
        screen_context: ScreenContext | None,
        history: list[dict],
        current_user: User,
        db: Session,
    ) -> HandlerResult:
        current_page = screen_context.current_page if screen_context else None
        prompt = _build_prompt(message, current_user.name, current_page)
        response = await generate_text(prompt, system_instruction=_SYSTEM)
        if response is None:
            response = (
                "Hi! I'm the BI Copilot. I can help you understand your KPIs, "
                "explore insights, review decisions, and query your data. What would you like to know?"
            )
        return HandlerResult(response=response)
