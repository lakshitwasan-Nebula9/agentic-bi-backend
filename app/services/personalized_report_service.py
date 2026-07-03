"""
Personalized Report Service

Builds per-user email content based on:
  - The user's role (executive / manager / analyst)
  - The dashboards they own or can view (role-hierarchy aware)
  - The certified KPIs on those dashboards
  - Recent insights and snapshots for those KPIs
"""

import calendar
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, selectinload

from app.models.dashboard import Dashboard
from app.models.insight import InsightEvent
from app.models.kpi import KPIDefinition, KPISnapshot
from app.models.user import ROLE_RANK, User, UserRole

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pct_change(current: float, previous: float) -> float | None:
    if previous and previous != 0:
        return round((current - previous) / abs(previous) * 100, 2)
    return None


def _fmt(value: float | None, unit: str | None = None) -> str:
    if value is None:
        return "—"
    if unit and "%" in unit:
        return f"{value:.1f}%"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def _weekly_label() -> str:
    now = datetime.now(UTC)
    monday = now - timedelta(days=now.weekday())
    sunday = monday + timedelta(days=6)
    return f"Week of {monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}"


def _monthly_label() -> str:
    now = datetime.now(UTC)
    month, year = (12, now.year - 1) if now.month == 1 else (now.month - 1, now.year)
    return f"{calendar.month_name[month]} {year}"


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


def _get_user_dashboards_and_kpi_ids(
    db: Session, user: User
) -> tuple[list[Dashboard], set[uuid.UUID]]:
    """Return dashboards the user can view (own + lower-ranked) with widgets loaded."""
    lower_roles = [r for r in UserRole if ROLE_RANK[r] > ROLE_RANK[user.role]]

    from sqlalchemy import or_

    conditions = [Dashboard.owner_id == user.id]
    if lower_roles:
        conditions.append(User.role.in_(lower_roles))

    dashboards = (
        db.query(Dashboard)
        .options(selectinload(Dashboard.widgets))
        .join(User, Dashboard.owner_id == User.id)
        .filter(or_(*conditions))
        .order_by(Dashboard.created_at)
        .all()
    )

    kpi_ids: set[uuid.UUID] = set()
    for dash in dashboards:
        for widget in dash.widgets:
            if widget.config and widget.config.get("kpi_id"):
                try:
                    kpi_ids.add(uuid.UUID(str(widget.config["kpi_id"])))
                except (ValueError, TypeError):
                    pass

    return dashboards, kpi_ids


def _fetch_certified_kpis(db: Session, kpi_ids: set[uuid.UUID]) -> list[KPIDefinition]:
    if not kpi_ids:
        return []
    return (
        db.query(KPIDefinition)
        .filter(
            KPIDefinition.id.in_(kpi_ids),
            KPIDefinition.status == "certified",
            KPIDefinition.is_deleted.is_(False),
        )
        .all()
    )


def _fetch_pending_kpis(db: Session, kpi_ids: set[uuid.UUID]) -> list[KPIDefinition]:
    if not kpi_ids:
        return []
    return (
        db.query(KPIDefinition)
        .filter(
            KPIDefinition.id.in_(kpi_ids),
            KPIDefinition.status == "pending_review",
            KPIDefinition.is_deleted.is_(False),
        )
        .all()
    )


def _fetch_insights(db: Session, kpi_ids: list[uuid.UUID], since: datetime) -> list[InsightEvent]:
    if not kpi_ids:
        return []
    return (
        db.query(InsightEvent)
        .filter(
            InsightEvent.kpi_id.in_(kpi_ids),
            InsightEvent.created_at >= since,
            InsightEvent.is_deleted.is_(False),
        )
        .order_by(InsightEvent.created_at.desc())
        .all()
    )


def _fetch_snapshots(
    db: Session, kpi_ids: list[uuid.UUID], limit_per_kpi: int = 13
) -> dict[uuid.UUID, list[KPISnapshot]]:
    result: dict[uuid.UUID, list[KPISnapshot]] = {}
    for kpi_id in kpi_ids:
        result[kpi_id] = (
            db.query(KPISnapshot)
            .filter(KPISnapshot.kpi_id == kpi_id)
            .order_by(KPISnapshot.period_start.desc())
            .limit(limit_per_kpi)
            .all()
        )
    return result


# ---------------------------------------------------------------------------
# Shape helpers
# ---------------------------------------------------------------------------


def _shape_kpi_changes(
    kpis: list[KPIDefinition],
    snapshots_by_kpi: dict[uuid.UUID, list[KPISnapshot]],
    num_snaps_for_prev: int = 1,
) -> list[dict]:
    rows = []
    for kpi in kpis:
        snaps = snapshots_by_kpi.get(kpi.id, [])
        current = snaps[0].value if snaps else None
        prev = snaps[num_snaps_for_prev].value if len(snaps) > num_snaps_for_prev else None
        rows.append(
            {
                "name": kpi.display_name or kpi.name,
                "category": kpi.category or "",
                "current_value": _fmt(current, kpi.unit),
                "mom_change": (
                    _pct_change(current, prev) if current is not None and prev is not None else None
                ),
                "yoy_change": (
                    _pct_change(current, snaps[12].value)
                    if len(snaps) > 12 and current is not None
                    else None
                ),
            }
        )
    return rows


def _shape_anomalies(
    insights: list[InsightEvent], kpi_map: dict[uuid.UUID, KPIDefinition]
) -> list[dict]:
    return [
        {
            "title": i.llm_title or f"{i.insight_type.replace('_', ' ').title()} detected",
            "summary": i.llm_summary,
            "severity": i.llm_severity or ("critical" if i.is_anomaly else "info"),
            "kpi_name": kpi_map[i.kpi_id].display_name if i.kpi_id in kpi_map else "",
        }
        for i in insights
        if i.is_anomaly or i.llm_severity in ("critical", "warning")
    ]


def _shape_actions(
    insights: list[InsightEvent], kpi_map: dict[uuid.UUID, KPIDefinition]
) -> list[dict]:
    actions = [
        {
            "priority": (
                "P1"
                if i.llm_severity == "critical" or (i.z_score and abs(i.z_score) >= 3)
                else "P2" if i.llm_severity == "warning" else "P3"
            ),
            "description": i.llm_title or "Review anomaly",
            "kpi_name": kpi_map[i.kpi_id].display_name if i.kpi_id in kpi_map else "",
        }
        for i in insights
        if i.is_anomaly
    ]
    actions.sort(key=lambda a: ("P1", "P2", "P3").index(a["priority"]))
    return actions


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_user_weekly_data(db: Session, user: User) -> dict | None:
    dashboards, kpi_ids = _get_user_dashboards_and_kpi_ids(db, user)

    if not kpi_ids:
        logger.info("No dashboard KPIs found for %s — skipping weekly email", user.email)
        return None

    certified_kpis = _fetch_certified_kpis(db, kpi_ids)
    certified_ids = [k.id for k in certified_kpis]
    kpi_map = {k.id: k for k in certified_kpis}

    since = datetime.now(UTC) - timedelta(days=7)
    insights = _fetch_insights(db, certified_ids, since)
    snapshots_by_kpi = _fetch_snapshots(db, certified_ids, limit_per_kpi=2)

    kpi_changes = _shape_kpi_changes(certified_kpis, snapshots_by_kpi)
    anomalies = _shape_anomalies(insights, kpi_map)
    urgent_actions = [a for a in _shape_actions(insights, kpi_map) if a["priority"] in ("P1", "P2")]

    # Analyst-only: pending review KPIs
    pending_kpis = []
    if user.role == UserRole.ANALYST:
        pending = _fetch_pending_kpis(db, kpi_ids)
        pending_kpis = [
            {"name": k.display_name or k.name, "category": k.category or ""} for k in pending
        ]

    return {
        "user_name": user.name or user.email.split("@")[0],
        "role": user.role.value,
        "period_type": "weekly",
        "period_label": _weekly_label(),
        "dashboard_count": len(dashboards),
        "kpi_count": len(certified_kpis),
        "kpi_changes": kpi_changes[:10],
        "anomalies": anomalies[:8],
        "urgent_actions": urgent_actions[:5],
        "pending_kpis": pending_kpis,
        "new_insight_count": len(insights),
        "anomaly_count": len(anomalies),
    }


def build_user_monthly_data(db: Session, user: User) -> dict | None:
    dashboards, kpi_ids = _get_user_dashboards_and_kpi_ids(db, user)

    if not kpi_ids:
        logger.info("No dashboard KPIs found for %s — skipping monthly email", user.email)
        return None

    certified_kpis = _fetch_certified_kpis(db, kpi_ids)
    certified_ids = [k.id for k in certified_kpis]
    kpi_map = {k.id: k for k in certified_kpis}

    since = datetime.now(UTC) - timedelta(days=30)
    insights = _fetch_insights(db, certified_ids, since)
    snapshots_by_kpi = _fetch_snapshots(db, certified_ids, limit_per_kpi=13)

    scorecard = _shape_kpi_changes(certified_kpis, snapshots_by_kpi)

    # Top 4 headline metrics by abs MoM movement
    headline = sorted(
        [s for s in scorecard if s["mom_change"] is not None],
        key=lambda s: abs(s["mom_change"]),
        reverse=True,
    )[:4]

    all_insights = [
        {
            "title": i.llm_title or f"{i.insight_type.replace('_', ' ').title()}",
            "summary": i.llm_summary,
            "severity": i.llm_severity or ("critical" if i.is_anomaly else "info"),
            "kpi_name": kpi_map[i.kpi_id].display_name if i.kpi_id in kpi_map else "",
        }
        for i in insights
    ]

    actions = _shape_actions(insights, kpi_map)
    anomaly_count = sum(1 for i in insights if i.is_anomaly)

    return {
        "user_name": user.name or user.email.split("@")[0],
        "role": user.role.value,
        "period_type": "monthly",
        "period_label": _monthly_label(),
        "dashboard_count": len(dashboards),
        "kpi_count": len(certified_kpis),
        "headline_metrics": headline,
        "kpi_scorecard": scorecard,
        "insights": all_insights[:20],
        "decision_actions": actions[:10],
        "anomaly_count": anomaly_count,
        "insight_count": len(insights),
    }
