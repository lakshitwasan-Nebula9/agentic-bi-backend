"""
HITL Workflow Service — pure orchestration, no LLM calls, no event publishing.

Service functions return ApprovalOutcome which carries the AR and, when an event
should be emitted, the event_type + event_payload. The caller (router or agent)
is responsible for publishing the event; this keeps the service testable in isolation.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import kpi as kpi_crud
from app.crud.approval_request import (
    STAGE_SEQUENCE,
    advance_stage,
    close_approval,
    create_approval_request,
    get_approval_by_entity,
    get_approval_request,
    list_approvals,
)
from app.models.approval_request import ApprovalRequest


@dataclass
class ApprovalOutcome:
    ar: ApprovalRequest
    event_type: str | None = None
    event_payload: dict[str, Any] | None = field(default=None)


def create_kpi_approval(
    db: Session,
    kpi_id: uuid.UUID,
    priority: int = 2,
) -> ApprovalRequest:
    """Create an ApprovalRequest for a newly generated KPI. Idempotent — returns existing if pending."""
    existing = get_approval_by_entity(db, "kpi", kpi_id)
    if existing is not None:
        return existing
    deadline = datetime.now(UTC) + timedelta(hours=settings.HITL_SLA_ANALYST_HOURS)
    return create_approval_request(
        db,
        entity_type="kpi",
        entity_id=kpi_id,
        stage="analyst_review",
        priority=priority,
        sla_deadline=deadline,
    )


def process_approval(
    db: Session,
    ar_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_role: str,
    note: str | None = None,
) -> ApprovalOutcome:
    """Advance the approval one stage, or certify the KPI if on the final stage."""
    ar = get_approval_request(db, ar_id)
    if ar is None:
        raise HTTPException(status_code=404, detail=f"ApprovalRequest {ar_id} not found")
    if ar.status != "pending":
        raise HTTPException(status_code=409, detail=f"ApprovalRequest is already {ar.status}")
    if actor_role != ar.assigned_role:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Actor role '{actor_role}' cannot action this stage — "
                f"expected '{ar.assigned_role}'"
            ),
        )

    current_idx = STAGE_SEQUENCE.index(ar.current_stage)
    is_final = current_idx == len(STAGE_SEQUENCE) - 1

    if is_final:
        kpi = kpi_crud.get_kpi(db, ar.entity_id)
        if kpi is None:
            raise HTTPException(status_code=404, detail=f"KPI {ar.entity_id} not found")
        kpi_crud.certify_kpi(db, kpi, certified_by=actor_id)
        close_approval(db, ar, status="approved", resolved_by=actor_id, note=note)
        return ApprovalOutcome(
            ar=ar,
            event_type="kpi_certified",
            event_payload={
                "kpi_id": str(ar.entity_id),
                "ar_id": str(ar.id),
                "actor_id": str(actor_id),
            },
        )

    next_stage = STAGE_SEQUENCE[current_idx + 1]
    sla_hours = _stage_sla_hours(next_stage)
    new_deadline = datetime.now(UTC) + timedelta(hours=sla_hours)
    advance_stage(db, ar, next_stage, new_deadline)

    if next_stage == "certification_review":
        return ApprovalOutcome(
            ar=ar,
            event_type="kpi_approved",
            event_payload={
                "kpi_id": str(ar.entity_id),
                "ar_id": str(ar.id),
                "actor_id": str(actor_id),
            },
        )
    return ApprovalOutcome(ar=ar)


def process_rejection(
    db: Session,
    ar_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_role: str,
    reason: str,
) -> ApprovalOutcome:
    """Reject a KPI at any approval stage and close the ApprovalRequest."""
    ar = get_approval_request(db, ar_id)
    if ar is None:
        raise HTTPException(status_code=404, detail=f"ApprovalRequest {ar_id} not found")
    if ar.status != "pending":
        raise HTTPException(status_code=409, detail=f"ApprovalRequest is already {ar.status}")
    if actor_role != ar.assigned_role:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Actor role '{actor_role}' cannot action this stage — "
                f"expected '{ar.assigned_role}'"
            ),
        )

    kpi = kpi_crud.get_kpi(db, ar.entity_id)
    if kpi is None:
        raise HTTPException(status_code=404, detail=f"KPI {ar.entity_id} not found")
    kpi_crud.reject_kpi(db, kpi, rejected_by=actor_id, reason=reason)
    close_approval(db, ar, status="rejected", resolved_by=actor_id, note=reason)
    return ApprovalOutcome(
        ar=ar,
        event_type="kpi_rejected",
        event_payload={
            "kpi_id": str(ar.entity_id),
            "ar_id": str(ar.id),
            "actor_id": str(actor_id),
            "reason": reason,
        },
    )


def get_overdue_approvals(db: Session) -> list[ApprovalRequest]:
    """Return all pending ApprovalRequests whose SLA deadline has passed."""
    now = datetime.now(UTC)
    overdue = []
    for ar in list_approvals(db, status="pending"):
        deadline = ar.sla_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if deadline < now:
            overdue.append(ar)
    return overdue


def _stage_sla_hours(stage: str) -> int:
    return {
        "analyst_review": settings.HITL_SLA_ANALYST_HOURS,
        "business_owner_review": settings.HITL_SLA_BUSINESS_OWNER_HOURS,
        "certification_review": settings.HITL_SLA_CERTIFICATION_HOURS,
    }[stage]
