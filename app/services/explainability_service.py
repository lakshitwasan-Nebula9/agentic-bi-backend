"""Explainability Agent core — builds the receipt shown in the insight drill-down modal.

For a given InsightEvent it gathers deterministic context (KPI → Dataset → Connector),
derives the four modal values (confidence score, source dataset, data freshness, KPI
formula), then calls Gemini for a multi-paragraph narrative with identified business
drivers and recommended actions.
"""

import logging
import os

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud.dataset import get_dataset
from app.crud.explanation import upsert_explanation
from app.crud.kpi import get_kpi
from app.models.connector import DataConnector
from app.models.dataset import Dataset
from app.models.explanation import InsightExplanation
from app.models.insight import InsightEvent
from app.models.kpi import KPISnapshot
from app.prompts import load_prompt
from app.services.confidence_service import compute_confidence

logger = logging.getLogger(__name__)


class ExplainabilityNarrative(BaseModel):
    llm_explanation: str
    business_drivers: list[str]
    recommended_actions: list[str]


_prompt = load_prompt("explainability_narrative")
_session_service: InMemorySessionService = InMemorySessionService()
_agent: Agent = Agent(
    name="explainability_agent",
    model=settings.GEMINI_LLM_MODEL,
    instruction=_prompt["instruction"],
    output_schema=ExplainabilityNarrative,
)
_runner: Runner = Runner(
    agent=_agent,
    app_name="explainability_narrative",
    session_service=_session_service,
)


def _source_dataset(db: Session, kpi, dataset: Dataset | None) -> str | None:
    """Build "<database_name>.<table_name>" (e.g. "sales_db.orders")."""
    if kpi is None:
        return None
    connector = (
        db.query(DataConnector)
        .filter(DataConnector.id == dataset.connector_id, DataConnector.is_deleted.is_(False))
        .first()
        if dataset is not None
        else None
    )
    if connector is None:
        return kpi.table_name
    return f"{connector.database_name}.{kpi.table_name}"


def _get_12month_snapshots(db: Session, kpi_id) -> list[dict]:
    """Return up to the last 12 monthly snapshots as {period, value} dicts, oldest first."""
    rows = (
        db.query(KPISnapshot)
        .filter(
            KPISnapshot.kpi_id == kpi_id,
            KPISnapshot.period_start.isnot(None),
            KPISnapshot.is_deleted.is_(False),
        )
        .order_by(KPISnapshot.period_start.desc())
        .limit(12)
        .all()
    )
    return [{"period": s.period_start.isoformat(), "value": s.value} for s in reversed(rows)]


def _build_explainability_prompt(context: dict) -> str:
    history = context.get("snapshot_history") or []
    history_text = ", ".join(f"{h['period'][:7]}: {h['value']:.2f}" for h in history)
    breakdown = context.get("confidence_breakdown") or {}
    return f"""
Produce a drill-down explanation for the following KPI insight.

KPI: {context.get("kpi_name")}
Formula: {context.get("kpi_formula") or "n/a"}
Unit: {context.get("unit") or "n/a"}
Direction (which way is good): {context.get("direction") or "n/a"}

Current value: {context.get("current_value")}
Trend-expected value (baseline mean): {context.get("baseline_mean")}
z_score (deviation from trend): {context.get("z_score")}
Trend slope (% per month): {context.get("trend_slope")}

12-month snapshot history (oldest first): {history_text}

Confidence score: {context.get("confidence_score")}/100
Confidence breakdown: {breakdown}
Source dataset: {context.get("source_dataset") or "unknown"}
Data last synced at: {context.get("data_freshness_at") or "unknown"}

Return ONLY valid JSON.
""".strip()


async def _call_gemini_explainability(context: dict) -> ExplainabilityNarrative | None:
    """Call Gemini for a multi-paragraph drill-down narrative. Best-effort — returns None on failure."""
    if not settings.GEMINI_API_KEY:
        logger.info("Skipping explainability narration: GEMINI_API_KEY is not set")
        return None

    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)
    prompt = _build_explainability_prompt(context)

    try:
        session = await _session_service.create_session(
            app_name="explainability_narrative", user_id="system"
        )
        message = types.Content(role="user", parts=[types.Part(text=prompt)])

        response_text = ""
        async for event in _runner.run_async(
            user_id="system", session_id=session.id, new_message=message
        ):
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text

        return ExplainabilityNarrative.model_validate_json(response_text)
    except Exception:
        logger.warning(
            "Explainability narration failed — persisting without LLM fields", exc_info=True
        )
        return None


async def build_explanation(db: Session, insight: InsightEvent) -> InsightExplanation:
    """Compute and persist the explainability receipt for an insight."""
    kpi = get_kpi(db, insight.kpi_id)
    dataset = get_dataset(db, kpi.dataset_id) if kpi is not None else None

    num_snapshots = (
        db.query(KPISnapshot)
        .filter(KPISnapshot.kpi_id == insight.kpi_id, KPISnapshot.is_deleted.is_(False))
        .count()
    )

    data_freshness_at = dataset.last_synced_at if dataset is not None else None
    if data_freshness_at is None:
        latest = (
            db.query(KPISnapshot)
            .filter(KPISnapshot.kpi_id == insight.kpi_id, KPISnapshot.is_deleted.is_(False))
            .order_by(KPISnapshot.computed_at.desc())
            .first()
        )
        data_freshness_at = latest.computed_at if latest is not None else None

    score, breakdown = compute_confidence(insight, dataset, num_snapshots)
    source = _source_dataset(db, kpi, dataset)
    snapshot_history = _get_12month_snapshots(db, insight.kpi_id)

    narrative = await _call_gemini_explainability(
        {
            "kpi_name": kpi.display_name if kpi else None,
            "kpi_formula": kpi.formula if kpi else None,
            "unit": kpi.unit if kpi else None,
            "direction": kpi.direction if kpi else None,
            "current_value": insight.value,
            "baseline_mean": insight.baseline_mean,
            "z_score": insight.z_score,
            "trend_slope": insight.trend_slope,
            "snapshot_history": snapshot_history,
            "confidence_score": score,
            "confidence_breakdown": breakdown,
            "source_dataset": source,
            "data_freshness_at": data_freshness_at.isoformat() if data_freshness_at else None,
        }
    )

    return upsert_explanation(
        db,
        insight_event_id=insight.id,
        kpi_id=insight.kpi_id,
        confidence_score=score,
        confidence_breakdown=breakdown,
        source_dataset=source,
        data_freshness_at=data_freshness_at,
        kpi_formula=kpi.formula if kpi is not None else None,
        llm_explanation=narrative.llm_explanation if narrative else None,
        business_drivers=narrative.business_drivers if narrative else None,
        recommended_actions=narrative.recommended_actions if narrative else None,
    )
