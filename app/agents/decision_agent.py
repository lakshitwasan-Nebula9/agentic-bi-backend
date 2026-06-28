"""
Decision Agent (GenAI layer) — given a pre-classified InsightEvent (priority,
owner role, and SLA already set by the rule engine), chooses the best action
type and produces a plain-English rationale + recommendation via Gemini/ADK.

Like the Insight Agent, the LLM call is best-effort: if Gemini is not
configured or fails, ``recommend`` returns ``None`` and the caller persists the
rule-only DecisionRecord.  The rule engine output is never gated on the LLM.
"""

import asyncio
import logging
import os
import uuid
from contextlib import nullcontext

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from app.agents.messaging import AgentEvent, AgentPublisher, AgentSubscriber
from app.core.config import settings
from app.core.database import SessionLocal
from app.prompts import load_prompt
from app.services.langfuse_service import get_langfuse

logger = logging.getLogger(__name__)

EVENT_INSIGHT_DETECTED = "insight_detected"
EVENT_DECISION_MADE = "decision_made"
EVENT_DECISION_APPROVAL_REQUIRED = "decision_approval_required"


class DecisionOutput(BaseModel):
    action_type: str  # monitor | investigate | optimize | escalate
    rationale: str
    action_summary: str
    business_impact: str
    confidence: float


_prompt = load_prompt("decision_making")

_session_service: InMemorySessionService = InMemorySessionService()
_agent: Agent = Agent(
    name="decision_agent",
    model=settings.GEMINI_LLM_MODEL,
    instruction=_prompt["instruction"],
    output_schema=DecisionOutput,
)
_runner: Runner = Runner(
    agent=_agent,
    app_name="decision_making",
    session_service=_session_service,
)


def _build_prompt(context: dict) -> str:
    recent = context.get("recent_values") or []
    recent_text = ", ".join(f"{v:.2f}" for v in recent)
    pct_deviation = ""
    value = context.get("value")
    expected = context.get("baseline_mean")
    if value is not None and expected and expected != 0:
        pct_deviation = f"{((value - expected) / expected) * 100:+.1f}%"

    return f"""
Evaluate this business insight and recommend the appropriate action.

KPI: {context.get("kpi_name")}
Category: {context.get("kpi_category")}
Unit: {context.get("unit") or "n/a"}
Direction (which way is good): {context.get("direction") or "n/a"}
Period: {context.get("period_start")}

Value: {value}
Expected (trend baseline): {expected} (deviation: {pct_deviation})
Z-score: {context.get("z_score")}
Is anomaly: {context.get("is_anomaly")}
Insight type: {context.get("insight_type")}
Trend slope (% per month): {context.get("trend_slope")}
Rolling 3M average: {context.get("rolling_avg_3m")}
Rolling 6M average: {context.get("rolling_avg_6m")}
Recent monthly values (oldest first): {recent_text}

Insight Agent narrative:
  Title: {context.get("llm_title") or "n/a"}
  Category: {context.get("llm_category") or "n/a"}
  Severity: {context.get("llm_severity") or "n/a"}
  Summary: {context.get("llm_summary") or "n/a"}

System-assigned priority: {context.get("priority")}
System-assigned owner role: {context.get("recommended_owner_role")}

Return ONLY valid JSON.
""".strip()


async def recommend(context: dict) -> DecisionOutput | None:
    """Generate action recommendation for one insight.

    Best-effort: returns None when GEMINI_API_KEY is unset or the LLM call /
    JSON parse fails, so the caller can still persist the rule-only record.
    """
    if not settings.GEMINI_API_KEY:
        logger.info("Skipping decision narration: GEMINI_API_KEY is not set")
        return None

    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)
    prompt = _build_prompt(context)

    lf = get_langfuse()
    trace_cm = (
        lf.start_as_current_observation(
            as_type="trace",
            name="decision_making",
            metadata={
                "insight_event_id": str(context.get("insight_event_id")),
                "priority": context.get("priority"),
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
                    name="gemini_decision_making",
                    model=settings.GEMINI_LLM_MODEL,
                )
                if lf
                else nullcontext()
            )
            with gen_cm as lf_gen:
                if lf_gen:
                    lf_gen.update(input=prompt)

                session = await _session_service.create_session(
                    app_name="decision_making", user_id="system"
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

            output = DecisionOutput.model_validate_json(response_text)
            if lf_trace:
                lf_trace.update(output=output.model_dump())
            return output
    except Exception:
        logger.warning(
            "Decision recommendation failed for insight %s — persisting rule-only record",
            context.get("insight_event_id"),
            exc_info=True,
        )
        return None


class DecisionAgent(AgentSubscriber):
    """Worker that consumes insight_detected events and produces DecisionRecords."""

    def __init__(self, consumer_name: str = "decision-agent-worker-1") -> None:
        super().__init__(
            group_name="decision-agent",
            consumer_name=consumer_name,
            event_types=[EVENT_INSIGHT_DETECTED],
        )
        self._publisher = AgentPublisher(self._redis)

    def handle_event(self, event: AgentEvent) -> None:
        insight_id_raw = event.payload.get("id")
        if not insight_id_raw:
            logger.warning("insight_detected event missing id: %s", event.event_id)
            return

        try:
            insight_id = uuid.UUID(str(insight_id_raw))
        except ValueError:
            logger.error("Invalid insight id in event %s: %s", event.event_id, insight_id_raw)
            return

        logger.info("Processing decision for insight %s", insight_id)

        db = SessionLocal()
        try:
            from app.services.decision_service import make_decision

            decision = asyncio.run(make_decision(db, insight_id))
        except Exception:
            logger.exception("Decision processing failed for insight %s", insight_id)
            return
        finally:
            db.close()

        if decision is None:
            return

        self._publisher.publish(
            EVENT_DECISION_MADE,
            {
                "decision_id": str(decision.id),
                "insight_event_id": str(decision.insight_event_id),
                "kpi_id": str(decision.kpi_id),
                "priority": decision.priority,
                "decision_type": decision.decision_type,
                "action_type": decision.action_type,
                "status": decision.status,
                "recommended_owner_role": decision.recommended_owner_role,
                "suggested_due_date": decision.suggested_due_date.isoformat(),
            },
        )
        logger.info(
            "Published decision_made for insight %s (priority=%s, action=%s)",
            insight_id,
            decision.priority,
            decision.action_type,
        )

        if decision.priority == "P1":
            self._publisher.publish(
                EVENT_DECISION_APPROVAL_REQUIRED,
                {
                    "decision_id": str(decision.id),
                    "insight_event_id": str(decision.insight_event_id),
                    "priority": decision.priority,
                    "recommended_owner_role": decision.recommended_owner_role,
                    "llm_action_summary": decision.llm_action_summary,
                    "suggested_due_date": decision.suggested_due_date.isoformat(),
                },
            )
            logger.info("Published decision_approval_required for decision %s", decision.id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = DecisionAgent()
    logger.info("Decision Agent started")
    agent.run()
