"""
Insight Agent (GenAI layer) — turns a KPI's statistical signals into a
business-facing narrative using Gemini via ADK.

Unlike the KPI Agent, narration is **best-effort**: if Gemini is not configured
or the call fails, ``narrate`` returns ``None`` and the caller persists the
math-only InsightEvent. The math layer never depends on the LLM being available.
"""

import logging
import os
from contextlib import nullcontext

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings
from app.prompts import load_prompt
from app.services.langfuse_service import get_langfuse

logger = logging.getLogger(__name__)


class InsightNarrative(BaseModel):
    title: str
    category: str
    severity: str  # info | warning | critical
    summary: str


_prompt = load_prompt("insight_narrative")

_session_service: InMemorySessionService = InMemorySessionService()
_agent: Agent = Agent(
    name="insight_agent",
    model=settings.GEMINI_LLM_MODEL,
    instruction=_prompt["instruction"],
    output_schema=InsightNarrative,
)
_runner: Runner = Runner(
    agent=_agent,
    app_name="insight_narrative",
    session_service=_session_service,
)


def _build_prompt(context: dict) -> str:
    recent = context.get("recent_values") or []
    recent_text = ", ".join(f"{v:.2f}" for v in recent)
    return f"""
Summarize the latest period for this KPI.

KPI: {context.get("kpi_name")}
Business category: {context.get("kpi_category")}
Unit: {context.get("unit") or "n/a"}
Direction (which way is good): {context.get("direction") or "n/a"}

Current value: {context.get("value")}
Trend-expected value: {context.get("expected")}
z_score (deviation from trend): {context.get("z_score")}
3-month rolling average: {context.get("rolling_avg_3m")}
6-month rolling average: {context.get("rolling_avg_6m")}
trend_slope_pct (per month): {context.get("trend_slope")}
insight_type: {context.get("insight_type")}

Recent monthly values (oldest first): {recent_text}

Return ONLY valid JSON.
""".strip()


async def narrate(context: dict) -> InsightNarrative | None:
    """Generate a business narrative for one detected insight.

    Best-effort: returns None when GEMINI_API_KEY is unset or the LLM call /
    JSON parse fails, so the caller can still persist the math-only event.
    """
    if not settings.GEMINI_API_KEY:
        logger.info("Skipping insight narration: GEMINI_API_KEY is not set")
        return None

    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)
    prompt = _build_prompt(context)

    lf = get_langfuse()
    trace_cm = (
        lf.start_as_current_observation(
            as_type="trace",
            name="insight_narrative",
            metadata={
                "kpi_id": str(context.get("kpi_id")),
                "insight_type": context.get("insight_type"),
            },
        )
        if lf
        else nullcontext()
    )

    try:
        with trace_cm as lf_trace:
            gen_cm = (
                lf.start_as_current_observation(
                    as_type="generation",
                    name="gemini_insight_narrative",
                    model=settings.GEMINI_LLM_MODEL,
                )
                if lf
                else nullcontext()
            )
            with gen_cm as lf_gen:
                if lf_gen:
                    lf_gen.update(input=prompt)

                session = await _session_service.create_session(
                    app_name="insight_narrative", user_id="system"
                )
                message = types.Content(role="user", parts=[types.Part(text=prompt)])

                response_text = ""
                async for event in _runner.run_async(
                    user_id="system", session_id=session.id, new_message=message
                ):
                    if event.is_final_response() and event.content and event.content.parts:
                        response_text = event.content.parts[0].text

                if lf_gen:
                    lf_gen.update(output=response_text)

            narrative = InsightNarrative.model_validate_json(response_text)
            if lf_trace:
                lf_trace.update(output=narrative.model_dump())
            return narrative
    except Exception:
        logger.warning(
            "Insight narration failed for KPI %s — persisting math-only event",
            context.get("kpi_id"),
            exc_info=True,
        )
        return None
