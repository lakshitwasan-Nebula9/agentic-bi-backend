"""
Report Scheduler

Runs two scheduled jobs via APScheduler:
  - Weekly  : every Monday 08:00 UTC  → operational summary to Managers + Analysts
  - Monthly : 1st of each month 08:00 UTC → full executive report to Executives + Managers

Each job generates a report, shapes the data for the email template, then
sends to every active user in the target roles.
"""

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import SessionLocal
from app.models.user import User, UserRole
from app.services import email_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _weekly_period_label() -> str:
    now = datetime.now(UTC)
    # ISO week start (Monday) and end (Sunday)
    monday = now - __import__("datetime").timedelta(days=now.weekday())
    sunday = monday + __import__("datetime").timedelta(days=6)
    return f"Week of {monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}"


def _monthly_period_label() -> str:
    now = datetime.now(UTC)
    # Previous month
    if now.month == 1:
        month, year = 12, now.year - 1
    else:
        month, year = now.month - 1, now.year
    import calendar

    return f"{calendar.month_name[month]} {year}"


def _shape_weekly(report_json: dict) -> dict:
    """Extract the weekly-relevant fields from a full ReportData JSON."""
    exec_summary = report_json.get("executive_summary", {})

    # Flatten all insights, keep only anomalies / warning / critical
    all_insights = [
        ins
        for section in report_json.get("insight_sections", [])
        for ins in section.get("insights", [])
    ]
    anomalies = [
        {
            "title": i.get("title", ""),
            "summary": i.get("description", ""),
            "severity": i.get("severity", "info"),
        }
        for i in all_insights
        if i.get("is_anomaly") or i.get("severity") in ("critical", "warning")
    ]

    # KPI week-over-week (use mom_change_pct as the closest available)
    kpi_changes = [
        {
            "name": k.get("display_name") or k.get("name", ""),
            "current_value": _fmt(k.get("current_value"), k.get("unit")),
            "wow_change": k.get("mom_change_pct"),
        }
        for k in report_json.get("kpi_scorecard", [])
        if k.get("current_value") is not None
    ]

    # P1 and P2 actions only
    open_actions = [
        {
            "priority": a.get("priority", "P3"),
            "description": a.get("action_title", ""),
        }
        for a in report_json.get("decision_actions", [])
        if a.get("priority") in ("P1", "P2") and a.get("status") == "pending"
    ]

    return {
        "period_label": report_json.get("period_label", ""),
        "executive_summary": exec_summary.get("narrative", ""),
        "anomalies": anomalies[:10],
        "kpi_changes": kpi_changes[:10],
        "open_actions": open_actions,
    }


def _shape_monthly(report_json: dict) -> dict:
    """Extract the monthly/executive fields from a full ReportData JSON."""
    exec_summary = report_json.get("executive_summary", {})

    headline_metrics = [
        {
            "name": m.get("label", ""),
            "current_value": m.get("value", ""),
            "mom_change": None,  # headline_metrics in schema stores formatted string; skip numeric
        }
        for m in exec_summary.get("headline_metrics", [])
    ]

    kpi_scorecard = [
        {
            "name": k.get("display_name") or k.get("name", ""),
            "current_value": _fmt(k.get("current_value"), k.get("unit")),
            "mom_change": k.get("mom_change_pct"),
            "yoy_change": k.get("yoy_change_pct"),
        }
        for k in report_json.get("kpi_scorecard", [])
        if k.get("current_value") is not None
    ]

    all_insights = [
        {
            "title": i.get("title", ""),
            "summary": i.get("description", ""),
            "severity": i.get("severity", "info"),
        }
        for section in report_json.get("insight_sections", [])
        for i in section.get("insights", [])
    ]

    decision_actions = [
        {
            "priority": a.get("priority", "P3"),
            "description": a.get("action_title", ""),
        }
        for a in report_json.get("decision_actions", [])
    ]

    appendix_raw = report_json.get("appendix", {})
    appendix = {
        "total_kpis": appendix_raw.get("certified_kpi_count", 0),
        "anomaly_count": appendix_raw.get("anomaly_count", 0),
        "source_count": len(appendix_raw.get("data_sources", [])),
    }

    return {
        "period_label": report_json.get("period_label", ""),
        "headline_metrics": headline_metrics,
        "executive_narrative": exec_summary.get("narrative", ""),
        "key_wins": exec_summary.get("key_wins", []),
        "key_risks": exec_summary.get("key_risks", []),
        "kpi_scorecard": kpi_scorecard,
        "insights": all_insights[:20],
        "decision_actions": decision_actions,
        "appendix": appendix,
    }


def _fmt(value: float | None, unit: str | None) -> str:
    if value is None:
        return "—"
    if unit and "%" in unit:
        return f"{value:.1f}%"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------


async def _run_weekly_job() -> None:
    logger.info("Weekly report job started")
    from app.services.personalized_report_service import build_user_weekly_data

    db = SessionLocal()
    try:
        users = (
            db.query(User)
            .filter(
                User.role.in_([UserRole.MANAGER, UserRole.ANALYST]),
                User.is_active.is_(True),
            )
            .all()
        )
        sent = 0
        for user in users:
            data = build_user_weekly_data(db, user)
            if data is None:
                continue
            ok = await email_service.send_personalized_report(user.email, user.role.value, data)
            if ok:
                sent += 1
        logger.info("Weekly personalized reports sent to %d/%d users", sent, len(users))
    except Exception:
        logger.exception("Weekly report job failed")
    finally:
        db.close()


async def _run_monthly_job() -> None:
    logger.info("Monthly report job started")
    from app.services.personalized_report_service import build_user_monthly_data

    db = SessionLocal()
    try:
        users = (
            db.query(User)
            .filter(
                User.role.in_([UserRole.EXECUTIVE, UserRole.MANAGER]),
                User.is_active.is_(True),
            )
            .all()
        )
        sent = 0
        for user in users:
            data = build_user_monthly_data(db, user)
            if data is None:
                continue
            ok = await email_service.send_personalized_report(user.email, user.role.value, data)
            if ok:
                sent += 1
        logger.info("Monthly personalized reports sent to %d/%d users", sent, len(users))
    except Exception:
        logger.exception("Monthly report job failed")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    # Weekly: every Monday at 08:00 UTC
    scheduler.add_job(_run_weekly_job, "cron", day_of_week="mon", hour=8, minute=0)
    # Monthly: 1st of each month at 08:00 UTC
    scheduler.add_job(_run_monthly_job, "cron", day=1, hour=8, minute=0)
    return scheduler
