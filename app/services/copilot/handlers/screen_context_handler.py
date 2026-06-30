"""
Screen Context handler.

The user is asking about something they are currently viewing on screen.
We fetch the exact entity from the DB and synthesise a natural language answer.
No semantic search — the frontend told us exactly what they're looking at.
"""

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.dashboard import Dashboard, DashboardWidget
from app.models.decision import DecisionRecord
from app.models.insight import InsightEvent
from app.models.kpi import KPIDefinition, KPISnapshot
from app.models.report import Report
from app.models.user import User
from app.schemas.copilot import ScreenContext, SourceReference, SuggestedAction
from app.services.copilot.gemini_client import generate_text
from app.services.copilot.handlers.base_handler import BaseHandler, HandlerResult

logger = logging.getLogger(__name__)

_SYSTEM = """You are the AI Copilot for an enterprise BI platform. Be concise and insight-driven.

Rules:
- Max 150 words for dashboard summaries unless the user asks for more detail.
- For chart widgets: describe the trend over time from the snapshot series — direction, slope, any reversal.
- For KPI tile widgets: state the current value and whether it is on track, at risk, or anomalous.
- Mention each alert only once. Do not restate the same finding in multiple bullet points.
- Name the KPI and its value explicitly. Round to 2 decimal places.
- Do not hallucinate values not present in the data.
- If data is insufficient, say so in one sentence."""


def _kpi_context(
    db: Session, kpi_id: uuid.UUID
) -> tuple[str, list[SourceReference], list[SuggestedAction]]:
    kpi: KPIDefinition | None = db.get(KPIDefinition, kpi_id)
    if kpi is None:
        return "KPI not found.", [], []

    snapshots = (
        db.query(KPISnapshot)
        .filter(KPISnapshot.kpi_id == kpi_id)
        .order_by(KPISnapshot.period_start.desc().nulls_last())
        .limit(6)
        .all()
    )
    snap_lines = [
        f"  - {s.period_start.strftime('%Y-%m') if s.period_start else 'full-dataset'}: {s.value}"
        for s in snapshots
    ]

    insights = (
        db.query(InsightEvent)
        .filter(InsightEvent.kpi_id == kpi_id)
        .order_by(InsightEvent.created_at.desc())
        .limit(3)
        .all()
    )
    insight_lines = []
    for ev in insights:
        severity = ev.llm_severity or "info"
        title = ev.llm_title or ev.insight_type
        insight_lines.append(
            f"  - [{severity.upper()}] {title} (z={ev.z_score:.2f}, anomaly={ev.is_anomaly})"
        )

    context = f"""KPI: {kpi.display_name}
Category: {kpi.category}
Status: {kpi.status}
Formula: {kpi.formula}
Direction: {kpi.direction}
Unit: {kpi.unit or 'n/a'}

Recent snapshots (newest first):
{chr(10).join(snap_lines) or '  No snapshots yet.'}

Recent insights:
{chr(10).join(insight_lines) or '  No insights detected yet.'}"""

    refs = [
        SourceReference(type="kpi", id=str(kpi_id), name=kpi.display_name, route=f"/kpis/{kpi_id}")
    ]
    for ev in insights:
        refs.append(
            SourceReference(
                type="insight",
                id=str(ev.id),
                name=ev.llm_title or ev.insight_type,
                route=f"/insights/{ev.id}",
            )
        )

    actions = [SuggestedAction(label="View KPI Detail", route=f"/kpis/{kpi_id}")]
    if insights:
        actions.append(SuggestedAction(label="View Insights", route=f"/insights?kpi_id={kpi_id}"))

    return context, refs, actions


def _insight_context(
    db: Session, insight_id: uuid.UUID
) -> tuple[str, list[SourceReference], list[SuggestedAction]]:
    ev: InsightEvent | None = db.get(InsightEvent, insight_id)
    if ev is None:
        return "Insight not found.", [], []

    kpi: KPIDefinition | None = db.get(KPIDefinition, ev.kpi_id)
    kpi_name = kpi.display_name if kpi else str(ev.kpi_id)

    decision: DecisionRecord | None = (
        db.query(DecisionRecord).filter(DecisionRecord.insight_event_id == insight_id).first()
    )
    decision_line = ""
    if decision:
        decision_line = f"\nDecision: {decision.action_type or 'pending'} (priority={decision.priority}, status={decision.status})"
        if decision.llm_rationale:
            decision_line += f"\nRationale: {decision.llm_rationale}"

    context = f"""Insight on KPI: {kpi_name}
Period: {ev.period_start.strftime('%Y-%m') if ev.period_start else 'n/a'}
Value: {ev.value}
Insight type: {ev.insight_type}
Is anomaly: {ev.is_anomaly}
Z-score: {ev.z_score}
Baseline mean: {ev.baseline_mean}
Trend slope: {ev.trend_slope}% per month
Rolling avg (3m): {ev.rolling_avg_3m}
Rolling avg (6m): {ev.rolling_avg_6m}
Severity: {ev.llm_severity or 'n/a'}
Summary: {ev.llm_summary or 'No AI summary yet.'}
{decision_line}"""

    refs = [
        SourceReference(
            type="insight",
            id=str(insight_id),
            name=ev.llm_title or ev.insight_type,
            route=f"/insights/{insight_id}",
        ),
        SourceReference(type="kpi", id=str(ev.kpi_id), name=kpi_name, route=f"/kpis/{ev.kpi_id}"),
    ]
    actions = [SuggestedAction(label="View KPI", route=f"/kpis/{ev.kpi_id}")]
    if decision:
        actions.append(SuggestedAction(label="View Decision", route=f"/decisions/{decision.id}"))

    return context, refs, actions


def _report_context(
    db: Session, report_id: uuid.UUID
) -> tuple[str, list[SourceReference], list[SuggestedAction]]:
    report: Report | None = db.get(Report, report_id)
    if report is None:
        return "Report not found.", [], []

    summary = report.executive_narrative or "No narrative available."
    kpi_section = ""
    if report.report_json and "kpi_scorecard" in report.report_json:
        kpi_lines = []
        for item in report.report_json["kpi_scorecard"][:5]:
            kpi_lines.append(
                f"  - {item.get('name')}: {item.get('current_value')} ({item.get('mom_change_pct', 0):+.1f}% MoM)"
            )
        kpi_section = "\nTop KPIs:\n" + "\n".join(kpi_lines)

    context = f"""Report: {report.title}
Period: {report.period_label or 'n/a'}
Status: {report.status}
Executive Summary: {summary}{kpi_section}"""

    refs = [
        SourceReference(
            type="report", id=str(report_id), name=report.title, route=f"/reports/{report_id}"
        )
    ]
    return context, refs, [SuggestedAction(label="View Full Report", route=f"/reports/{report_id}")]


def _decision_context(
    db: Session, decision_id: uuid.UUID
) -> tuple[str, list[SourceReference], list[SuggestedAction]]:
    dec: DecisionRecord | None = db.get(DecisionRecord, decision_id)
    if dec is None:
        return "Decision not found.", [], []

    ev: InsightEvent | None = db.get(InsightEvent, dec.insight_event_id)
    kpi: KPIDefinition | None = db.get(KPIDefinition, dec.kpi_id)

    context = f"""Decision for KPI: {kpi.display_name if kpi else str(dec.kpi_id)}
Priority: {dec.priority}
Status: {dec.status}
Action type: {dec.action_type or 'pending LLM'}
Decision type: {dec.decision_type or 'n/a'}
Owner role: {dec.recommended_owner_role}
SLA hours: {dec.sla_hours}
Due: {dec.suggested_due_date.strftime('%Y-%m-%d %H:%M UTC') if dec.suggested_due_date else 'n/a'}
Rationale: {dec.llm_rationale or 'No rationale yet.'}
Action summary: {dec.llm_action_summary or 'n/a'}
Business impact: {dec.llm_business_impact or 'n/a'}
Requires approval: {dec.requires_approval}"""

    if ev:
        context += f"\nLinked insight: {ev.llm_title or ev.insight_type} (z={ev.z_score})"

    refs = [
        SourceReference(type="decision", id=str(decision_id), route=f"/decisions/{decision_id}")
    ]
    if ev:
        refs.append(
            SourceReference(
                type="insight",
                id=str(ev.id),
                name=ev.llm_title or ev.insight_type,
                route=f"/insights/{ev.id}",
            )
        )

    return (
        context,
        refs,
        [SuggestedAction(label="View Decision", route=f"/decisions/{decision_id}")],
    )


def _time_series(db: Session, kpi_id: uuid.UUID) -> str:
    snaps = (
        db.query(KPISnapshot)
        .filter(KPISnapshot.kpi_id == kpi_id)
        .order_by(KPISnapshot.period_start.asc().nulls_last())
        .limit(12)
        .all()
    )
    if not snaps:
        return "no snapshot data"
    return ", ".join(
        f"{s.period_start.strftime('%Y-%m')}: {s.value:.2f}" if s.period_start else f"?: {s.value}"
        for s in snaps
    )


def _widget_context(
    db: Session,
    widget_id: uuid.UUID,
) -> tuple[str, list[SourceReference], list[SuggestedAction]]:
    widget: DashboardWidget | None = db.get(DashboardWidget, widget_id)
    if widget is None:
        return "Widget not found.", [], []

    kpi_id_raw = (widget.config or {}).get("kpi_id")
    if not kpi_id_raw:
        return f"Widget '{widget.title or widget.widget_type}' has no KPI linked yet.", [], []

    try:
        kpi_id = uuid.UUID(str(kpi_id_raw))
    except (ValueError, AttributeError):
        return "Widget has an invalid KPI reference.", [], []

    kpi: KPIDefinition | None = db.get(KPIDefinition, kpi_id)
    if kpi is None:
        return "KPI not found.", [], []

    insights = (
        db.query(InsightEvent)
        .filter(InsightEvent.kpi_id == kpi_id)
        .order_by(InsightEvent.created_at.desc())
        .limit(3)
        .all()
    )
    insight_lines = [
        f"  [{(ev.llm_severity or 'info').upper()}] {ev.llm_title or ev.insight_type} (z={ev.z_score:.2f})"
        for ev in insights
    ]

    context = (
        f"Widget: {widget.title or kpi.display_name}\n"
        f"Widget type (from DB): {widget.widget_type}\n"
        f"KPI: {kpi.display_name} | direction={kpi.direction} | unit={kpi.unit or 'n/a'} | status={kpi.status}\n\n"
        f"12-month time series (oldest → newest):\n{_time_series(db, kpi_id)}\n\n"
        f"Alerts:\n" + ("\n".join(insight_lines) or "  None")
    )
    refs = [
        SourceReference(type="kpi", id=str(kpi_id), name=kpi.display_name, route=f"/kpis/{kpi_id}")
    ]
    return context, refs, [SuggestedAction(label="View KPI Detail", route=f"/kpis/{kpi_id}")]


def _dashboard_context(
    db: Session,
    dashboard_id: uuid.UUID,
    visible_kpi_ids: list[uuid.UUID] | None,
    visible_insight_ids: list[uuid.UUID] | None,
) -> tuple[str, list[SourceReference], list[SuggestedAction]]:
    dashboard: Dashboard | None = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        return "Dashboard not found.", [], []

    refs: list[SourceReference] = [
        SourceReference(
            type="dashboard",
            id=str(dashboard_id),
            name=dashboard.name,
            route=f"/dashboards/{dashboard_id}",
        )
    ]

    # --- Resolve KPI IDs server-side from widget configs ---
    # Widget config stores the KPI under the key "kpi_id" (canonical field name).
    # This works even when the user is not on the dashboard page and visible_kpi_ids is empty.
    server_kpi_ids: list[uuid.UUID] = []
    for widget in dashboard.widgets or []:
        if widget.config and widget.config.get("kpi_id"):
            try:
                server_kpi_ids.append(uuid.UUID(str(widget.config["kpi_id"])))
            except (ValueError, AttributeError):
                pass

    # Fall back to frontend-supplied list only if widget scan yielded nothing
    resolved_kpi_ids = server_kpi_ids if server_kpi_ids else (visible_kpi_ids or [])

    # Build a map of kpi_id → widget_type so the LLM knows tile vs chart
    widget_type_by_kpi: dict[uuid.UUID, str] = {}
    for widget in dashboard.widgets or []:
        kpi_id_raw = (widget.config or {}).get("kpi_id")
        if kpi_id_raw:
            try:
                widget_type_by_kpi[uuid.UUID(str(kpi_id_raw))] = widget.widget_type or "unknown"
            except (ValueError, AttributeError):
                pass

    kpi_lines = []
    if resolved_kpi_ids:
        kpis = db.query(KPIDefinition).filter(KPIDefinition.id.in_(resolved_kpi_ids)).all()
        for kpi in kpis:
            series = _time_series(db, kpi.id)
            widget_type = widget_type_by_kpi.get(kpi.id, "unknown")
            kpi_lines.append(
                f"  - {kpi.display_name} ({kpi.category}) | widget={widget_type}"
                f" | direction={kpi.direction} | status={kpi.status}\n"
                f"    series: {series}"
            )
            refs.append(
                SourceReference(
                    type="kpi", id=str(kpi.id), name=kpi.display_name, route=f"/kpis/{kpi.id}"
                )
            )

    # Fetch insights.
    # Priority 1: frontend sent stable UUIDs via visible_insight_ids — use them directly.
    # Priority 2: resolved KPI IDs from widget config scan.
    # Priority 3: join dashboard_widgets config JSONB to find any linked KPI IDs we missed.
    insight_lines = []
    if visible_insight_ids:
        insight_q = (
            db.query(InsightEvent)
            .filter(InsightEvent.id.in_(visible_insight_ids))
            .order_by(InsightEvent.created_at.desc())
        )
    elif resolved_kpi_ids:
        insight_q = (
            db.query(InsightEvent)
            .filter(InsightEvent.kpi_id.in_(resolved_kpi_ids))
            .order_by(InsightEvent.created_at.desc())
            .limit(20)
        )
    else:
        # Fallback: pull KPI IDs from widget config JSONB directly via SQL
        kpi_ids_from_widgets = (
            db.execute(
                text(
                    "SELECT DISTINCT (config->>'kpi_id')::uuid "
                    "FROM dashboard_widgets "
                    "WHERE dashboard_id = :did AND config->>'kpi_id' IS NOT NULL"
                ),
                {"did": str(dashboard_id)},
            )
            .scalars()
            .all()
        )
        if kpi_ids_from_widgets:
            insight_q = (
                db.query(InsightEvent)
                .filter(InsightEvent.kpi_id.in_(kpi_ids_from_widgets))
                .order_by(InsightEvent.created_at.desc())
                .limit(20)
            )
        else:
            insight_q = None

    if insight_q is not None:
        for ev in insight_q.all():
            severity = ev.llm_severity or "info"
            title = ev.llm_title or ev.insight_type
            insight_lines.append(
                f"  - [{severity.upper()}] {title} (anomaly={ev.is_anomaly}, z={ev.z_score})"
            )
            refs.append(
                SourceReference(
                    type="insight", id=str(ev.id), name=title, route=f"/insights/{ev.id}"
                )
            )

    widget_count = len(dashboard.widgets) if dashboard.widgets else 0
    context = f"""Dashboard: {dashboard.name}
Total widgets: {widget_count}

KPIs on this dashboard (live values):
{chr(10).join(kpi_lines) or '  No KPIs configured on this dashboard yet.'}

Active insights:
{chr(10).join(insight_lines) or '  No insights visible.'}"""

    return context, refs, []


class ScreenContextHandler(BaseHandler):
    async def handle(
        self,
        message: str,
        screen_context: ScreenContext | None,
        history: list[dict],
        current_user: User,
        db: Session,
    ) -> HandlerResult:
        if screen_context is None:
            return HandlerResult(
                response="I can see you're asking about something on screen, but I don't have your screen context. Could you describe what you're looking at?"
            )

        entity_context = ""
        refs: list[SourceReference] = []
        actions: list[SuggestedAction] = []

        if screen_context.widget_id:
            entity_context, refs, actions = _widget_context(db, screen_context.widget_id)
        elif screen_context.kpi_id:
            entity_context, refs, actions = _kpi_context(db, screen_context.kpi_id)
        elif screen_context.insight_id:
            entity_context, refs, actions = _insight_context(db, screen_context.insight_id)
        elif screen_context.report_id:
            entity_context, refs, actions = _report_context(db, screen_context.report_id)
        elif screen_context.decision_id:
            entity_context, refs, actions = _decision_context(db, screen_context.decision_id)
        elif screen_context.dashboard_id:
            entity_context, refs, actions = _dashboard_context(
                db,
                screen_context.dashboard_id,
                screen_context.visible_kpi_ids,
                screen_context.visible_insight_ids,
            )
        else:
            return HandlerResult(
                response="I can see you're on the platform, but I don't have a specific entity to refer to. Try clicking on a KPI, insight, or report, then ask your question."
            )

        prompt = f"""Data from the platform:
{entity_context}

User question: {message}

Instructions:
- For dashboard summaries: group your answer by widget type (tile widgets = current value snapshot; chart/bar/line widgets = trend over time; table widgets = data overview). Do not list every KPI in a flat bullet list.
- Lead with the most important signal (highest severity alert or biggest trend movement), then cover the rest briefly.
- Max 150 words. Each alert mentioned only once.

Answer the question based on the data above."""

        response = await generate_text(prompt, system_instruction=_SYSTEM)
        if response is None:
            response = (
                "I'm having trouble reaching the AI service right now. Here's the raw data I fetched:\n\n"
                + entity_context
            )

        return HandlerResult(
            response=response,
            source_references=refs,
            suggested_actions=actions,
        )
