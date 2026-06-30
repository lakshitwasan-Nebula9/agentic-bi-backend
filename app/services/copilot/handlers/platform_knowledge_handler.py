"""
Platform Knowledge handler.

Answers questions about objects already stored in the platform:
KPIs, insights, decisions, reports. All data is fetched directly from
the DB — no vector search, no re-generation.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.decision import DecisionRecord
from app.models.insight import InsightEvent
from app.models.kpi import KPIDefinition, KPISnapshot
from app.models.report import Report
from app.models.user import User
from app.schemas.copilot import ScreenContext, SourceReference, SuggestedAction
from app.services.copilot.gemini_client import generate_text
from app.services.copilot.handlers.base_handler import BaseHandler, HandlerResult

logger = logging.getLogger(__name__)

_SYSTEM = """You are the AI Copilot for an enterprise BI platform.
You have been given a snapshot of data retrieved from the platform database.
Answer the user's question based strictly on this data.
Be concise (3–6 sentences). Use plain business English.
If the data is insufficient, say so. Do not invent numbers or KPI names."""

_LIMIT = 10


def _kpi_summary(db: Session) -> tuple[str, list[SourceReference]]:
    kpis = db.query(KPIDefinition).order_by(KPIDefinition.updated_at.desc()).limit(_LIMIT).all()
    if not kpis:
        return "No KPIs found.", []

    lines, refs = [], []
    for kpi in kpis:
        snap = (
            db.query(KPISnapshot)
            .filter(KPISnapshot.kpi_id == kpi.id)
            .order_by(KPISnapshot.period_start.desc().nulls_last())
            .first()
        )
        val = f"{snap.value:.2f}" if snap else "no data"
        lines.append(f"  - {kpi.display_name} [{kpi.status}] ({kpi.category}): {val}")
        refs.append(
            SourceReference(
                type="kpi", id=str(kpi.id), name=kpi.display_name, route=f"/kpis/{kpi.id}"
            )
        )

    return "KPIs (most recently updated):\n" + "\n".join(lines), refs


def _insight_summary(db: Session) -> tuple[str, list[SourceReference]]:
    since = datetime.now(UTC) - timedelta(days=30)
    events = (
        db.query(InsightEvent)
        .filter(InsightEvent.created_at >= since)
        .order_by(InsightEvent.created_at.desc())
        .limit(_LIMIT)
        .all()
    )
    if not events:
        return "No insights detected in the last 30 days.", []

    lines, refs = [], []
    for ev in events:
        severity = ev.llm_severity or "info"
        title = ev.llm_title or ev.insight_type
        kpi = db.get(KPIDefinition, ev.kpi_id)
        kpi_name = kpi.display_name if kpi else str(ev.kpi_id)
        lines.append(f"  - [{severity.upper()}] {title} on {kpi_name} (anomaly={ev.is_anomaly})")
        refs.append(
            SourceReference(type="insight", id=str(ev.id), name=title, route=f"/insights/{ev.id}")
        )

    return "Recent insights (last 30 days):\n" + "\n".join(lines), refs


def _decision_summary(db: Session) -> tuple[str, list[SourceReference]]:
    decisions = (
        db.query(DecisionRecord)
        .filter(DecisionRecord.status.in_(["pending", "decided", "awaiting_approval"]))
        .order_by(DecisionRecord.created_at.desc())
        .limit(_LIMIT)
        .all()
    )
    if not decisions:
        return "No open decisions.", []

    lines, refs = [], []
    for dec in decisions:
        kpi = db.get(KPIDefinition, dec.kpi_id)
        kpi_name = kpi.display_name if kpi else str(dec.kpi_id)
        action = dec.action_type or "pending"
        lines.append(
            f"  - [{dec.priority}] {action} on {kpi_name} — status: {dec.status}, "
            f"due: {dec.suggested_due_date.strftime('%Y-%m-%d') if dec.suggested_due_date else 'n/a'}"
        )
        refs.append(SourceReference(type="decision", id=str(dec.id), route=f"/decisions/{dec.id}"))

    return "Open decisions:\n" + "\n".join(lines), refs


def _report_summary(db: Session) -> tuple[str, list[SourceReference]]:
    reports = (
        db.query(Report)
        .filter(Report.status == "ready")
        .order_by(Report.created_at.desc())
        .limit(5)
        .all()
    )
    if not reports:
        return "No completed reports found.", []

    lines, refs = [], []
    for r in reports:
        lines.append(
            f"  - {r.title} ({r.period_label or 'n/a'}) — {r.created_at.strftime('%Y-%m-%d')}"
        )
        refs.append(
            SourceReference(type="report", id=str(r.id), name=r.title, route=f"/reports/{r.id}")
        )

    return "Recent reports:\n" + "\n".join(lines), refs


def _build_platform_context(
    message: str, db: Session
) -> tuple[str, list[SourceReference], list[SuggestedAction]]:
    """
    Cheaply decide which platform sections to include based on keywords in the message,
    then fetch only those sections.
    """
    msg_lower = message.lower()
    sections: list[str] = []
    all_refs: list[SourceReference] = []
    actions: list[SuggestedAction] = []

    wants_kpi = any(
        w in msg_lower
        for w in ["kpi", "metric", "measure", "indicator", "certified", "performance"]
    )
    wants_insight = any(
        w in msg_lower
        for w in ["insight", "anomaly", "spike", "dip", "trend", "alert", "risk", "issue"]
    )
    wants_decision = any(
        w in msg_lower
        for w in ["decision", "action", "pending", "approval", "priority", "p1", "p2"]
    )
    wants_report = any(
        w in msg_lower for w in ["report", "summary", "executive", "weekly", "monthly"]
    )

    # Default: include everything when no clear signal
    if not any([wants_kpi, wants_insight, wants_decision, wants_report]):
        wants_kpi = wants_insight = wants_decision = True

    if wants_kpi:
        text, refs = _kpi_summary(db)
        sections.append(text)
        all_refs.extend(refs)
        actions.append(SuggestedAction(label="View All KPIs", route="/kpis"))

    if wants_insight:
        text, refs = _insight_summary(db)
        sections.append(text)
        all_refs.extend(refs)
        actions.append(SuggestedAction(label="View Insights", route="/insights"))

    if wants_decision:
        text, refs = _decision_summary(db)
        sections.append(text)
        all_refs.extend(refs)
        actions.append(SuggestedAction(label="View Decisions", route="/decisions"))

    if wants_report:
        text, refs = _report_summary(db)
        sections.append(text)
        all_refs.extend(refs)
        actions.append(SuggestedAction(label="View Reports", route="/reports"))

    return "\n\n".join(sections), all_refs, actions


class PlatformKnowledgeHandler(BaseHandler):
    async def handle(
        self,
        message: str,
        screen_context: ScreenContext | None,
        history: list[dict],
        current_user: User,
        db: Session,
    ) -> HandlerResult:
        platform_context, refs, actions = _build_platform_context(message, db)

        prompt = f"""Platform data:
{platform_context}

User question: {message}

Answer based on the platform data above."""

        response = await generate_text(prompt, system_instruction=_SYSTEM)
        if response is None:
            response = (
                "I'm having trouble reaching the AI service right now. Here's a summary of what I found:\n\n"
                + platform_context
            )

        return HandlerResult(
            response=response,
            source_references=refs,
            suggested_actions=actions,
        )
