"""
Intent classifier — routes every user message to one of five intents.

Intent enum:
  greeting          — casual conversation, greetings, capability questions
  screen_context    — questions about what the user is currently viewing
  database_qa       — raw data questions requiring SQL execution
  platform_knowledge — questions about KPIs, insights, decisions, reports in the platform
  out_of_scope      — off-topic; politely declined
"""

import logging

from app.models.copilot import CopilotIntentEnum
from app.schemas.copilot import ScreenContext
from app.services.copilot.gemini_client import generate_json

logger = logging.getLogger(__name__)

_SYSTEM = """You are an intent classifier for an enterprise Business Intelligence (BI) platform copilot.
Classify the user's message into exactly one of these intents:

- greeting: casual conversation, greetings, thanks, "what can you do", "help me"
- screen_context: the user is asking about something they are CURRENTLY LOOKING AT on screen.
  Triggers:
  • screen_context contains dashboard_id, kpi_id, insight_id, report_id, or decision_id
  • AND the message uses words like "this", "here", "current", "shown", "on screen",
    "this dashboard", "this KPI", "this chart", "this insight", "summarise this",
    "elaborate", "explain this", "what does this mean", "tell me more"
  Examples: "summarise this dashboard", "elaborate the chart", "what is this KPI about",
            "explain this insight", "what does this mean", "tell me about this"
- database_qa: questions asking for raw data from the user's connected source database —
  requires SQL execution against the actual data warehouse / DB.
  Examples: "what is there in my data", "show me revenue last month", "how many orders",
  "what was total sales", "compare Q1 vs Q2", "list top customers",
  "what tables do I have", "query my data", "show me records", "count of transactions",
  "what products sold the most", "break down by region"
- platform_knowledge: questions about KPIs, insights, decisions, or reports stored in the
  platform — when there is NO specific entity in screen_context to refer to.
  Examples: "what are my KPIs", "show recent insights", "what decisions are pending",
  "list my reports", "which KPIs are certified"
- out_of_scope: anything unrelated to business intelligence, data, or the platform

Rules:
1. If screen_context has any entity id (dashboard_id, kpi_id, insight_id, report_id,
   decision_id) AND the message is asking about what is on screen → screen_context.
   This is the HIGHEST priority rule.
2. Words like "this", "here", "current", "elaborate", "summarise", "explain" combined
   with any entity in screen_context → always screen_context.
3. Raw data / SQL / source database questions → database_qa.
4. General platform object questions with no screen entity → platform_knowledge.
5. When uncertain between database_qa and platform_knowledge with "data"/"records"/"tables"
   → database_qa.

Respond with valid JSON only, no explanation:
{"intent": "<one of the five intents>", "confidence": <0.0-1.0>}"""


def _history_snippet(history: list[dict]) -> str:
    """Format last 6 messages for the classifier prompt."""
    lines = []
    for msg in history[-6:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")[:200]
        lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "No prior messages."


def _screen_context_summary(ctx: ScreenContext | None) -> str:
    if ctx is None:
        return "none"
    parts = [f"page={ctx.current_page}"]
    if ctx.dashboard_id:
        parts.append(f"dashboard_id={ctx.dashboard_id}")
    if ctx.kpi_id:
        parts.append(f"kpi_id={ctx.kpi_id}")
    if ctx.insight_id:
        parts.append(f"insight_id={ctx.insight_id}")
    if ctx.report_id:
        parts.append(f"report_id={ctx.report_id}")
    if ctx.decision_id:
        parts.append(f"decision_id={ctx.decision_id}")
    if ctx.visible_kpi_ids:
        parts.append(f"visible_kpis={len(ctx.visible_kpi_ids)}")
    if ctx.visible_insight_ids:
        parts.append(f"visible_insights={len(ctx.visible_insight_ids)}")
    return ", ".join(parts)


async def classify_intent(
    message: str,
    screen_context: ScreenContext | None,
    history: list[dict],
) -> CopilotIntentEnum:
    prompt = f"""Screen context: {_screen_context_summary(screen_context)}

Conversation history:
{_history_snippet(history)}

User message: "{message}"

Classify the intent."""

    result = await generate_json(prompt, system_instruction=_SYSTEM)

    if result and "intent" in result:
        raw = result["intent"]
        confidence = result.get("confidence", 1.0)
        try:
            intent = CopilotIntentEnum(raw)
            if confidence < 0.6:
                logger.info(
                    "Low-confidence classification (%s %.2f) — defaulting to platform_knowledge",
                    raw,
                    confidence,
                )
                return CopilotIntentEnum.platform_knowledge
            return intent
        except ValueError:
            logger.warning("Unknown intent value from LLM: %r", raw)

    # Fallback when LLM is down or returned garbage
    logger.warning("Intent classification failed — defaulting to platform_knowledge")
    return CopilotIntentEnum.platform_knowledge
