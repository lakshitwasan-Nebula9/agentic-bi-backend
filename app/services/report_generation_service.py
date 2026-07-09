"""
Report Generation Service — assembles a full structured ReportData from:
  - Certified KPIs + their snapshots
  - InsightEvents (from the Insight Agent)
  - Dataset metadata + quality scores
  - Gemini-generated executive narrative (via reporting_agent)

The service is async because it awaits the Gemini call. It persists the report
as "ready" when done, or "failed" on unrecoverable error, so the caller always
gets a persisted record.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.crud import kpi as kpi_crud
from app.crud import report as report_crud
from app.models.dataset import Dataset
from app.models.insight import InsightEvent
from app.models.kpi import KPIDefinition, KPISnapshot
from app.models.report import Report
from app.schemas.report import (
    AppendixDataSource,
    DecisionAction,
    HeadlineMetric,
    InsightItem,
    InsightSection,
    KPIScorecardItem,
    ReportAppendix,
    ReportData,
    ReportExecutiveSummary,
    TimeIntelligenceItem,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category normalisation
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, str] = {
    "revenue": "revenue",
    "sales": "revenue",
    "income": "revenue",
    "operational": "operational",
    "operations": "operational",
    "fulfillment": "operational",
    "supply": "operational",
    "inventory": "operational",
    "logistics": "operational",
    "delivery": "operational",
    "customer": "customer",
    "customers": "customer",
    "churn": "customer",
    "nps": "customer",
    "retention": "customer",
    "financial": "financial",
    "finance": "financial",
    "margin": "financial",
    "profit": "financial",
    "cost": "financial",
    "expense": "financial",
}

_SECTION_DISPLAY: dict[str, str] = {
    "revenue": "Revenue Insights",
    "operational": "Operational Insights",
    "customer": "Customer Insights",
    "financial": "Financial Insights",
    "other": "Other Insights",
}


def _normalize_category(raw: str | None) -> str:
    if not raw:
        return "other"
    lower = raw.lower()
    for keyword, bucket in _CATEGORY_MAP.items():
        if keyword in lower:
            return bucket
    return "other"


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _pct_change(current: float, previous: float) -> float | None:
    if previous and previous != 0:
        return round((current - previous) / abs(previous) * 100, 2)
    return None


def _confidence_from_z(z_score: float | None) -> float | None:
    if z_score is None:
        return None
    # abs(z) * 25 → z=1 → 25%, z=2 → 50%, z=4 → 100%
    return round(min(100.0, abs(z_score) * 25), 1)


def _format_value(value: float | None, unit: str | None) -> str:
    if value is None:
        return "—"
    if unit and "%" in unit:
        return f"{value:.1f}%"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def _format_delta(pct: float | None) -> str | None:
    if pct is None:
        return None
    arrow = "▲" if pct > 0 else "▼"
    return f"{arrow} {abs(pct):.1f}% MoM"


def _delta_direction(pct: float | None, direction: str) -> str:
    if pct is None:
        return "neutral"
    positive_move = pct > 0
    higher_is_better = direction != "lower_is_better"
    if positive_move == higher_is_better:
        return "up"
    return "down"


# ---------------------------------------------------------------------------
# Scorecard builder
# ---------------------------------------------------------------------------


def _build_scorecard(
    kpis: list[KPIDefinition],
    snapshots_by_kpi: dict[uuid.UUID, list[KPISnapshot]],
) -> list[KPIScorecardItem]:
    items: list[KPIScorecardItem] = []
    for kpi in kpis:
        snaps = snapshots_by_kpi.get(kpi.id, [])
        current_val = snaps[-1].value if snaps else None
        prev_val = snaps[-2].value if len(snaps) >= 2 else None
        qoq_val = snaps[-4].value if len(snaps) >= 4 else None
        yoy_val = snaps[-13].value if len(snaps) >= 13 else None

        items.append(
            KPIScorecardItem(
                kpi_id=kpi.id,
                name=kpi.name,
                display_name=kpi.display_name,
                category=kpi.category,
                unit=kpi.unit,
                direction=kpi.direction,
                status=kpi.status,
                current_value=current_val,
                previous_value=prev_val,
                mom_change_pct=(
                    _pct_change(current_val, prev_val)
                    if current_val is not None and prev_val is not None
                    else None
                ),
                qoq_change_pct=(
                    _pct_change(current_val, qoq_val)
                    if current_val is not None and qoq_val is not None
                    else None
                ),
                yoy_change_pct=(
                    _pct_change(current_val, yoy_val)
                    if current_val is not None and yoy_val is not None
                    else None
                ),
            )
        )
    return items


# ---------------------------------------------------------------------------
# Insight sections builder
# ---------------------------------------------------------------------------


def _build_insight_sections(
    events: list[InsightEvent],
    kpi_map: dict[uuid.UUID, KPIDefinition],
) -> list[InsightSection]:
    buckets: dict[str, list[InsightItem]] = {}

    for event in events:
        kpi = kpi_map.get(event.kpi_id)
        if kpi is None:
            continue

        category = _normalize_category(kpi.category)
        title = event.llm_title or f"{event.insight_type.replace('_', ' ').title()} detected"
        description = event.llm_summary or (
            f"{kpi.display_name} recorded a value of {event.value:.2f}"
            f"{' ' + kpi.unit if kpi.unit else ''}."
        )
        severity = event.llm_severity or ("critical" if event.is_anomaly else "info")

        item = InsightItem(
            insight_id=event.id,
            kpi_id=event.kpi_id,
            kpi_name=kpi.name,
            kpi_display_name=kpi.display_name,
            title=title,
            description=description,
            severity=severity,
            confidence_score=_confidence_from_z(event.z_score),
            insight_type=event.insight_type,
            is_anomaly=event.is_anomaly,
            category=category,
            period_start=event.period_start,
            value=event.value,
            baseline_mean=event.baseline_mean,
            z_score=event.z_score,
        )
        buckets.setdefault(category, []).append(item)

    # Sort each bucket: critical first, then anomalies, then by period desc
    def _sort_key(i: InsightItem) -> tuple:
        sev_rank = {"critical": 0, "warning": 1, "info": 2}.get(i.severity, 3)
        return (sev_rank, not i.is_anomaly)

    # Preserve a canonical category order
    order = ["revenue", "operational", "customer", "financial", "other"]
    sections: list[InsightSection] = []
    for cat in order:
        if cat in buckets:
            sorted_items = sorted(buckets[cat], key=_sort_key)
            sections.append(
                InsightSection(
                    category=cat,
                    display_name=_SECTION_DISPLAY.get(cat, "Other Insights"),
                    insights=sorted_items,
                )
            )
    return sections


# ---------------------------------------------------------------------------
# Time intelligence builder
# ---------------------------------------------------------------------------


def _build_time_intelligence(
    events: list[InsightEvent],
    kpi_map: dict[uuid.UUID, KPIDefinition],
    scorecard: list[KPIScorecardItem],
) -> list[TimeIntelligenceItem]:
    # Use the latest event per KPI for trend data
    latest_event_by_kpi: dict[uuid.UUID, InsightEvent] = {}
    for event in sorted(events, key=lambda e: e.period_start):
        latest_event_by_kpi[event.kpi_id] = event

    mom_by_kpi = {item.kpi_id: item.mom_change_pct for item in scorecard}

    items: list[TimeIntelligenceItem] = []
    for kpi_id, event in latest_event_by_kpi.items():
        kpi = kpi_map.get(kpi_id)
        if kpi is None:
            continue
        items.append(
            TimeIntelligenceItem(
                kpi_id=kpi_id,
                kpi_name=kpi.name,
                kpi_display_name=kpi.display_name,
                unit=kpi.unit,
                direction=kpi.direction,
                latest_value=event.value,
                trend_slope=event.trend_slope,
                mom_change_pct=mom_by_kpi.get(kpi_id),
                rolling_avg_3m=event.rolling_avg_3m,
                rolling_avg_6m=event.rolling_avg_6m,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Decision actions builder
# ---------------------------------------------------------------------------


def _build_decision_actions(
    events: list[InsightEvent],
    kpi_map: dict[uuid.UUID, KPIDefinition],
) -> list[DecisionAction]:
    # Only surface anomalies or warning/critical events as action items
    actionable = [e for e in events if e.is_anomaly or e.llm_severity in ("critical", "warning")]

    def _priority(event: InsightEvent) -> str:
        if event.llm_severity == "critical" or (event.z_score and abs(event.z_score) >= 3):
            return "P1"
        if event.llm_severity == "warning" or (event.z_score and abs(event.z_score) >= 2):
            return "P2"
        return "P3"

    actions: list[DecisionAction] = []
    for event in actionable:
        kpi = kpi_map.get(event.kpi_id)
        if kpi is None:
            continue

        title = (
            event.llm_title
            or f"{event.insight_type.replace('_', ' ').title()} — {kpi.display_name}"
        )
        actions.append(
            DecisionAction(
                insight_id=event.id,
                kpi_name=kpi.display_name,
                action_title=title,
                priority=_priority(event),
                assigned_owner=kpi.owner_name,
                status="pending",
                severity=event.llm_severity or ("critical" if event.is_anomaly else "warning"),
            )
        )

    # Sort P1 first
    actions.sort(key=lambda a: ("P1", "P2", "P3").index(a.priority))
    return actions


# ---------------------------------------------------------------------------
# Headline metrics (top 5 KPIs by scorecard order)
# ---------------------------------------------------------------------------


def _build_headline_metrics(scorecard: list[KPIScorecardItem]) -> list[HeadlineMetric]:
    metrics: list[HeadlineMetric] = []
    for item in scorecard[:5]:
        if item.current_value is None:
            continue
        metrics.append(
            HeadlineMetric(
                label=item.display_name,
                value=_format_value(item.current_value, item.unit),
                delta=_format_delta(item.mom_change_pct),
                direction=_delta_direction(item.mom_change_pct, item.direction),
            )
        )
    return metrics


# ---------------------------------------------------------------------------
# Appendix builder
# ---------------------------------------------------------------------------


def _build_appendix(
    datasets: list[Dataset],
    connector_type_by_dataset: dict[uuid.UUID, str],
    certified_kpi_count: int,
    total_insight_count: int,
    anomaly_count: int,
) -> ReportAppendix:
    sources = [
        AppendixDataSource(
            dataset_id=ds.id,
            name=ds.name,
            connector_type=connector_type_by_dataset.get(ds.id, "unknown"),
            quality_score=ds.quality_score,
            last_synced_at=ds.last_synced_at,
            row_count=ds.row_count,
            status=ds.status,
        )
        for ds in datasets
    ]
    return ReportAppendix(
        data_sources=sources,
        certified_kpi_count=certified_kpi_count,
        total_insight_count=total_insight_count,
        anomaly_count=anomaly_count,
        generated_at=datetime.now(UTC),
        methodology=(
            "All figures are drawn from Certified KPIs that have passed the "
            "Human-in-the-Loop governance workflow (Analyst → Business Owner approval). "
            "Insights are generated by the Insight Agent using z-score anomaly detection, "
            "rolling averages, and trend slope analysis. "
            "Narrative is generated by the Reporting Agent using Google Gemini."
        ),
    )


# ---------------------------------------------------------------------------
# Narrative context builder (for the Gemini prompt)
# ---------------------------------------------------------------------------


def _build_narrative_context(
    scorecard: list[KPIScorecardItem],
    insight_sections: list[InsightSection],
    anomaly_count: int,
    period_label: str,
) -> dict:
    kpi_bullets = [
        (
            f"  {item.display_name} ({item.category}): "
            f"{_format_value(item.current_value, item.unit)}"
            + (f" {_format_delta(item.mom_change_pct)}" if item.mom_change_pct is not None else "")
        )
        for item in scorecard
    ]

    insight_bullets = []
    for section in insight_sections:
        for ins in section.insights[:3]:
            conf = f" ({ins.confidence_score:.0f}% conf)" if ins.confidence_score else ""
            insight_bullets.append(
                f"  [{ins.severity.upper()}] {ins.kpi_display_name} | "
                f"{ins.insight_type} | {ins.title}{conf}"
            )

    all_insights = [ins for s in insight_sections for ins in s.insights]
    return {
        "period_label": period_label,
        "certified_kpi_count": len(scorecard),
        "total_insight_count": len(all_insights),
        "anomaly_count": anomaly_count,
        "kpi_bullets": kpi_bullets,
        "insight_bullets": insight_bullets,
    }


# ---------------------------------------------------------------------------
# Fallback narrative when Gemini is unavailable
# ---------------------------------------------------------------------------


def _fallback_narrative(certified_kpis: int, anomaly_count: int, insight_count: int) -> dict:
    return {
        "narrative": (
            f"This report covers {certified_kpis} certified KPI"
            f"{'s' if certified_kpis != 1 else ''}. "
            f"The Insight Agent detected {insight_count} insight"
            f"{'s' if insight_count != 1 else ''}, "
            f"of which {anomaly_count} represent statistical anomal"
            f"{'ies' if anomaly_count != 1 else 'y'} requiring attention. "
            "Refer to the KPI Scorecard and Insight Sections below for detailed findings."
        ),
        "key_wins": [],
        "key_risks": [],
        "critical_actions": [],
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def generate_report(
    db: Session,
    report_id: uuid.UUID,
    title: str,
    period_label: str,
    *,
    scope: str = "global",
    dashboard_id: uuid.UUID | None = None,
    connector_id: uuid.UUID | None = None,
) -> Report:
    """Assemble, narrate, and persist the full report. Always returns a Report row.

    ``scope`` selects which certified KPIs the report covers:
      - ``global``    (default): every certified KPI and every dataset.
      - ``dashboard`` : only the KPIs referenced by ``dashboard_id``'s widgets.
      - ``database``  : all certified KPIs reachable from ``connector_id``'s datasets.
    Insights, scorecard, time-intelligence, decision-actions, and the appendix all
    key off the resulting KPI set, so they narrow automatically.
    """
    report = report_crud.get_report(db, report_id)
    if report is None:
        raise ValueError(f"Report {report_id} not found")

    try:
        from app.crud.dataset import list_datasets

        # 1. Fetch the certified KPIs in scope
        if scope == "dashboard" and dashboard_id is not None:
            from app.services.report_scope import kpi_ids_for_dashboard

            wanted = kpi_ids_for_dashboard(db, dashboard_id)
            certified_kpis: list[KPIDefinition] = [
                k for k in kpi_crud.list_kpis(db, status="certified") if k.id in wanted
            ]
        elif scope == "database" and connector_id is not None:
            from app.services.report_scope import certified_kpis_for_connector

            certified_kpis = certified_kpis_for_connector(db, connector_id)
        else:
            certified_kpis = kpi_crud.list_kpis(db, status="certified")

        kpi_map: dict[uuid.UUID, KPIDefinition] = {k.id: k for k in certified_kpis}

        # 2. Fetch snapshots for each KPI
        snapshots_by_kpi: dict[uuid.UUID, list[KPISnapshot]] = {
            kpi.id: kpi_crud.list_snapshots(db, kpi.id) for kpi in certified_kpis
        }

        # 3. Fetch all InsightEvents for certified KPIs (most recent first, cap 200)
        from app.services.insight_service import list_insights

        all_events: list[InsightEvent] = list_insights(db, limit=200)
        # Keep only events for in-scope certified KPIs
        events = [e for e in all_events if e.kpi_id in kpi_map]

        # 4. Fetch datasets for the appendix, scoped to the KPIs in the report
        all_datasets: list[Dataset] = list_datasets(db)
        if scope == "global":
            datasets: list[Dataset] = all_datasets
        else:
            scoped_dataset_ids = {k.dataset_id for k in certified_kpis}
            datasets = [ds for ds in all_datasets if ds.id in scoped_dataset_ids]

        # Build connector type lookup
        from app.crud.connector import get_connector

        connector_type_by_dataset: dict[uuid.UUID, str] = {}
        for ds in datasets:
            conn = get_connector(db, ds.connector_id)
            if conn:
                connector_type_by_dataset[ds.id] = conn.connector_type

        # 5. Build structured sections
        scorecard = _build_scorecard(certified_kpis, snapshots_by_kpi)
        insight_sections = _build_insight_sections(events, kpi_map)
        time_intelligence = _build_time_intelligence(events, kpi_map, scorecard)
        decision_actions = _build_decision_actions(events, kpi_map)
        headline_metrics = _build_headline_metrics(scorecard)

        anomaly_count = sum(1 for e in events if e.is_anomaly)
        all_flat_insights = [ins for s in insight_sections for ins in s.insights]

        appendix = _build_appendix(
            datasets=datasets,
            connector_type_by_dataset=connector_type_by_dataset,
            certified_kpi_count=len(certified_kpis),
            total_insight_count=len(all_flat_insights),
            anomaly_count=anomaly_count,
        )

        # 6. Generate executive narrative via Gemini
        from app.agents.reporting_agent import generate_narrative

        narrative_context = _build_narrative_context(
            scorecard, insight_sections, anomaly_count, period_label
        )
        llm_result = await generate_narrative(narrative_context)

        if llm_result is not None:
            narr_dict = llm_result.model_dump()
        else:
            narr_dict = _fallback_narrative(
                len(certified_kpis), anomaly_count, len(all_flat_insights)
            )

        executive_summary = ReportExecutiveSummary(
            narrative=narr_dict["narrative"],
            key_wins=narr_dict.get("key_wins", []),
            key_risks=narr_dict.get("key_risks", []),
            critical_actions=narr_dict.get("critical_actions", []),
            headline_metrics=headline_metrics,
        )

        # 7. Assemble final ReportData
        report_data = ReportData(
            report_id=report_id,
            title=title,
            period_label=period_label,
            generated_at=datetime.now(UTC),
            executive_summary=executive_summary,
            kpi_scorecard=scorecard,
            insight_sections=insight_sections,
            time_intelligence=time_intelligence,
            decision_actions=decision_actions,
            appendix=appendix,
        )

        # 8. Persist
        report_crud.update_report(
            db,
            report,
            status="ready",
            executive_narrative=narr_dict["narrative"],
            report_json=report_data.model_dump(mode="json"),
        )
        logger.info(
            "Report %s generated successfully (%d KPIs, %d insights)",
            report_id,
            len(certified_kpis),
            len(all_flat_insights),
        )

    except Exception:
        logger.exception("Report generation failed for %s", report_id)
        report_crud.update_report(db, report, status="failed")

    return report_crud.get_report(db, report_id)
