"""
Reporting Agent (GenAI layer) — generates the executive narrative for a report
using Gemini via ADK.

Best-effort: if GEMINI_API_KEY is not configured or the LLM call fails,
``generate_narrative`` returns None and the caller falls back to a templated
summary so the report is always persisted.
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


class ReportNarrative(BaseModel):
    narrative: str
    key_wins: list[str]
    key_risks: list[str]
    critical_actions: list[str]


_prompt = load_prompt("executive_narrative")

_session_service: InMemorySessionService = InMemorySessionService()
_agent: Agent = Agent(
    name="reporting_agent",
    model=settings.GEMINI_LLM_MODEL,
    instruction=_prompt["instruction"],
    output_schema=ReportNarrative,
)
_runner: Runner = Runner(
    agent=_agent,
    app_name="executive_narrative",
    session_service=_session_service,
)


def _build_prompt(context: dict) -> str:
    certified_kpis = context.get("certified_kpi_count", 0)
    anomaly_count = context.get("anomaly_count", 0)
    insight_count = context.get("total_insight_count", 0)
    period = context.get("period_label", "current period")

    kpi_lines = "\n".join(context.get("kpi_bullets", []) or ["  (no certified KPIs)"])
    insight_lines = "\n".join(context.get("insight_bullets", []) or ["  (no insights detected)"])

    return f"""
Generate an executive business performance report narrative for the {period}.

Summary:
- Certified KPIs: {certified_kpis}
- Total insights detected: {insight_count}
- Anomalies requiring attention: {anomaly_count}

Certified KPI snapshot (name | value | MoM change):
{kpi_lines}

Key insight findings (severity | KPI | type | title):
{insight_lines}

Return ONLY valid JSON matching the required schema.
""".strip()


async def generate_narrative(context: dict) -> ReportNarrative | None:
    """Generate an executive narrative for the full report.

    Best-effort: returns None when GEMINI_API_KEY is unset or the call fails,
    so the caller can persist a fallback templated summary instead.
    """
    if not settings.GEMINI_API_KEY:
        logger.info("Skipping report narration: GEMINI_API_KEY is not set")
        return None

    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)
    prompt = _build_prompt(context)

    lf = get_langfuse()
    trace_cm = (
        lf.start_as_current_observation(
            as_type="trace",
            name="executive_narrative",
            metadata={"period_label": context.get("period_label")},
        )
        if lf
        else nullcontext()
    )

    try:
        with trace_cm as lf_trace:
            gen_cm = (
                lf.start_as_current_observation(
                    as_type="generation",
                    name="gemini_executive_narrative",
                    model=settings.GEMINI_LLM_MODEL,
                )
                if lf
                else nullcontext()
            )
            with gen_cm as lf_gen:
                if lf_gen:
                    lf_gen.update(input=prompt)

                session = await _session_service.create_session(
                    app_name="executive_narrative", user_id="system"
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

            narrative = ReportNarrative.model_validate_json(response_text)
            if lf_trace:
                lf_trace.update(output=narrative.model_dump())
            return narrative

    except Exception:
        logger.warning("Report narration failed — using fallback summary", exc_info=True)
        return None
