"""Guidance Agent — merges new insight feedback into updated prompt guidance.

Runs periodically (see app.services.insight_guidance_service), not per-request.
Like the Insight Agent's narration, this is best-effort: if Gemini is not
configured or the call fails, ``summarize_guidance`` returns None and the
caller keeps the previous guidance in effect.
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


class GuidanceSummary(BaseModel):
    bullets: list[str]


_prompt = load_prompt("insight_feedback_guidance")

_session_service: InMemorySessionService = InMemorySessionService()
_agent: Agent = Agent(
    name="insight_guidance_agent",
    model=settings.GEMINI_LLM_MODEL,
    instruction=_prompt["instruction"],
    output_schema=GuidanceSummary,
)
_runner: Runner = Runner(
    agent=_agent,
    app_name="insight_feedback_guidance",
    session_service=_session_service,
)


def _build_prompt(prior_guidance: str, feedback_items: list[dict]) -> str:
    lines = []
    for item in feedback_items:
        lines.append(
            f"- title={item.get('title')!r} category={item.get('category')!r} "
            f"insight_type={item.get('insight_type')!r} rating={item.get('rating')!r} "
            f"comment={item.get('comment')!r}"
        )
    feedback_text = "\n".join(lines) if lines else "(none)"

    return f"""
PRIOR GUIDANCE:
{prior_guidance or "(none yet)"}

NEW FEEDBACK ({len(feedback_items)} entries):
{feedback_text}

Return ONLY valid JSON.
""".strip()


async def summarize_guidance(
    prior_guidance: str, feedback_items: list[dict]
) -> GuidanceSummary | None:
    """Merge new feedback into updated guidance bullets.

    Best-effort: returns None when GEMINI_API_KEY is unset or the LLM call /
    JSON parse fails, so the caller keeps the previous guidance unchanged.
    """
    if not settings.GEMINI_API_KEY:
        logger.info("Skipping guidance generation: GEMINI_API_KEY is not set")
        return None

    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)
    prompt = _build_prompt(prior_guidance, feedback_items)

    lf = get_langfuse()
    trace_cm = (
        lf.start_as_current_observation(
            as_type="trace",
            name="insight_feedback_guidance",
            metadata={"feedback_count": len(feedback_items)},
        )
        if lf
        else nullcontext()
    )

    try:
        with trace_cm as lf_trace:
            gen_cm = (
                lf.start_as_current_observation(
                    as_type="generation",
                    name="gemini_insight_feedback_guidance",
                    model=settings.GEMINI_LLM_MODEL,
                )
                if lf
                else nullcontext()
            )
            with gen_cm as lf_gen:
                if lf_gen:
                    lf_gen.update(input=prompt)

                session = await _session_service.create_session(
                    app_name="insight_feedback_guidance", user_id="system"
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

            summary = GuidanceSummary.model_validate_json(response_text)
            if lf_trace:
                lf_trace.update(output=summary.model_dump())
            return summary
    except Exception:
        logger.warning("Guidance generation failed — keeping previous guidance", exc_info=True)
        return None
