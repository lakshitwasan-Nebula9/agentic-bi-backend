"""
Decision Service — orchestrates the full decision pipeline for one InsightEvent.

Execution order (see architecture proposal):
  1. Guard: skip if already decided
  2. Fetch InsightEvent + KPIDefinition
  3. derive_priority()       — pure Python, deterministic
  4. resolve_owner_role()    — config lookup, deterministic
  5. compute_due_date()      — config lookup, deterministic
  6. Write DecisionRecord (status=pending, LLM fields null) — crash-safe anchor
  7. call Gemini → DecisionOutput  — async, best-effort
  8. derive_decision_type()  — pure Python from priority + action_type
  9. Update record with LLM fields, decision_type, and final status
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.agents.decision_agent import DecisionOutput, recommend
from app.core.config import settings
from app.crud import decision as decision_crud
from app.crud.kpi import get_kpi
from app.models.decision import DecisionRecord
from app.models.insight import InsightEvent
from app.models.kpi import KPIDefinition
from app.services.audit_service import SYSTEM_ROLE, record_audit

logger = logging.getLogger(__name__)

_SLA_MAP = {
    "P1": settings.DECISION_SLA_HOURS_P1,
    "P2": settings.DECISION_SLA_HOURS_P2,
    "P3": settings.DECISION_SLA_HOURS_P3,
}


# ---------------------------------------------------------------------------
# Rule engine — deterministic, no LLM
# ---------------------------------------------------------------------------


def derive_priority(event: InsightEvent) -> str:
    """Classify P1/P2/P3 from anomaly flag, severity, and trend slope.

    Rules (applied in order, first match wins):
    - P1: confirmed anomaly AND critical severity
    - P2: confirmed anomaly AND warning severity
    - P2: non-anomaly but adverse trend slope beyond threshold
    - P3: everything else (info severity, stable, positive movements)
    """
    severity = (event.llm_severity or "info").lower()
    slope = event.trend_slope or 0.0

    if event.is_anomaly and severity == "critical":
        return "P1"
    if event.is_anomaly and severity == "warning":
        return "P2"
    if not event.is_anomaly and abs(slope) >= settings.DECISION_ADVERSE_SLOPE_THRESHOLD:
        return "P2"
    return "P3"


def resolve_owner_role(kpi: KPIDefinition | None, priority: str) -> str:
    """Map KPI category to an owner role using config.

    P1 always routes to the P1 override role (executive by default)
    regardless of category.
    """
    if priority == "P1":
        return settings.DECISION_P1_OWNER_OVERRIDE

    if kpi is None:
        return settings.DECISION_DEFAULT_OWNER_ROLE

    category_key = (kpi.category or "").lower().replace(" ", "_")
    return settings.DECISION_CATEGORY_OWNER_MAP.get(
        category_key, settings.DECISION_DEFAULT_OWNER_ROLE
    )


def compute_due_date(priority: str) -> tuple[int, datetime]:
    """Return (sla_hours, suggested_due_date) from config."""
    sla_hours = _SLA_MAP.get(priority, settings.DECISION_SLA_HOURS_P3)
    due = datetime.now(UTC) + timedelta(hours=sla_hours)
    return sla_hours, due


def derive_decision_type(priority: str, action_type: str | None) -> str:
    """Map priority + action_type to a decision_type enum value."""
    if priority == "P1":
        return "approval_required"
    if action_type in ("investigate", "optimize") and priority == "P2":
        return "corrective"
    if action_type == "optimize" and priority == "P3":
        return "preventive"
    return "informational"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def make_decision(db: Session, insight_event_id: uuid.UUID) -> DecisionRecord | None:
    """Run the full decision pipeline for one InsightEvent.

    Returns the existing record if already decided (idempotent).
    Returns None if the InsightEvent does not exist.
    """
    # 1. Idempotency guard
    existing = decision_crud.get_decision_by_insight(db, insight_event_id)
    if existing is not None:
        logger.info("Decision already exists for insight %s — skipping", insight_event_id)
        return existing

    # 2. Fetch context
    event: InsightEvent | None = (
        db.query(InsightEvent)
        .filter(InsightEvent.id == insight_event_id, InsightEvent.is_deleted.is_(False))
        .first()
    )
    if event is None:
        logger.warning("InsightEvent %s not found — cannot make decision", insight_event_id)
        return None

    kpi: KPIDefinition | None = get_kpi(db, event.kpi_id)

    # 3-5. Deterministic rule engine
    priority = derive_priority(event)
    owner_role = resolve_owner_role(kpi, priority)
    sla_hours, due_date = compute_due_date(priority)

    # 6. Write pending record before LLM call — crash-safe anchor
    record = DecisionRecord(
        insight_event_id=insight_event_id,
        kpi_id=event.kpi_id,
        priority=priority,
        recommended_owner_role=owner_role,
        sla_hours=sla_hours,
        suggested_due_date=due_date,
        requires_approval=(priority == "P1"),
        status="pending",
    )
    decision_crud.create_decision(db, record)

    # 7. LLM recommendation (best-effort)
    context = {
        "insight_event_id": str(insight_event_id),
        "kpi_name": kpi.display_name if kpi else None,
        "kpi_category": kpi.category if kpi else None,
        "unit": kpi.unit if kpi else None,
        "direction": kpi.direction if kpi else None,
        "period_start": event.period_start.isoformat(),
        "value": event.value,
        "baseline_mean": event.baseline_mean,
        "z_score": event.z_score,
        "is_anomaly": event.is_anomaly,
        "insight_type": event.insight_type,
        "trend_slope": event.trend_slope,
        "rolling_avg_3m": event.rolling_avg_3m,
        "rolling_avg_6m": event.rolling_avg_6m,
        "recent_values": [],  # InsightEvent doesn't store raw values; context is sufficient
        "llm_title": event.llm_title,
        "llm_category": event.llm_category,
        "llm_severity": event.llm_severity,
        "llm_summary": event.llm_summary,
        "priority": priority,
        "recommended_owner_role": owner_role,
    }
    output: DecisionOutput | None = await recommend(context)

    # 8. Derive decision_type from rule output + LLM action_type
    action_type = output.action_type if output else None
    decision_type = derive_decision_type(priority, action_type)

    # 9. Update record with LLM fields and final status
    new_status = "awaiting_approval" if priority == "P1" else "decided"
    update_kwargs: dict = {
        "action_type": action_type,
        "decision_type": decision_type,
        "status": new_status,
        "decided_at": datetime.now(UTC),
    }
    if output is not None:
        update_kwargs.update(
            {
                "llm_rationale": output.rationale,
                "llm_action_summary": output.action_summary,
                "llm_business_impact": output.business_impact,
                "llm_confidence": output.confidence,
            }
        )

    record = decision_crud.update_decision(db, record, **update_kwargs)
    record_audit(
        db,
        action="decision.created",
        entity_type="decision",
        entity_id=record.id,
        actor_role=SYSTEM_ROLE,
        summary=f"AI decision {priority}/{action_type} for KPI {event.kpi_id}",
        details={
            "insight_event_id": str(insight_event_id),
            "kpi_id": str(event.kpi_id),
            "priority": priority,
            "action_type": action_type,
            "status": new_status,
        },
    )
    logger.info(
        "Decision made for insight %s: priority=%s, action=%s, status=%s",
        insight_event_id,
        priority,
        action_type,
        new_status,
    )
    return record


async def make_decisions_for_all_pending(db: Session) -> list[DecisionRecord]:
    """Run decision pipeline for all InsightEvents that have no decision yet.

    Useful for batch backfill via the REST trigger endpoint.
    """
    from sqlalchemy import select

    from app.models.insight import InsightEvent as IE

    undecided = db.scalars(
        select(IE).where(
            ~IE.id.in_(select(DecisionRecord.insight_event_id)),
            IE.is_deleted.is_(False),
        )
    ).all()

    results: list[DecisionRecord] = []
    for event in undecided:
        try:
            record = await make_decision(db, event.id)
            if record is not None:
                results.append(record)
        except Exception:
            logger.exception("Decision failed for insight %s — continuing", event.id)
    return results
