import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.messaging import AgentPublisher
from app.core.database import get_db
from app.crud.approval_request import get_approval_request, list_approvals
from app.crud.kpi import list_kpis
from app.schemas.approval_request import (
    ApprovalActionRequest,
    ApprovalRejectRequest,
    ApprovalRequestResponse,
)
from app.services import hitl_workflow_service as svc

logger = logging.getLogger(__name__)
router = APIRouter(tags=["approvals"])
_publisher = AgentPublisher()


class SeedApprovalsRequest(BaseModel):
    kpi_ids: list[uuid.UUID] | None = None
    dataset_id: uuid.UUID | None = None


@router.post("/approvals/seed", response_model=list[ApprovalRequestResponse])
def seed_approvals(req: SeedApprovalsRequest, db: Session = Depends(get_db)):
    """Create ApprovalRequests for pending_review KPIs. Use when the HITL agent is not running."""
    if req.kpi_ids:
        kpi_ids = req.kpi_ids
    elif req.dataset_id:
        kpis = list_kpis(db, dataset_id=req.dataset_id, status="pending_review")
        kpi_ids = [k.id for k in kpis]
    else:
        kpis = list_kpis(db, status="pending_review")
        kpi_ids = [k.id for k in kpis]

    if not kpi_ids:
        raise HTTPException(status_code=404, detail="No pending_review KPIs found")

    ars = []
    for kpi_id in kpi_ids:
        ar = svc.create_kpi_approval(db, kpi_id)
        ars.append(ar)
    return ars


@router.get("/approvals", response_model=list[ApprovalRequestResponse])
def list_approval_requests(
    status: str | None = None,
    entity_type: str | None = None,
    assigned_role: str | None = None,
    overdue: bool = False,
    db: Session = Depends(get_db),
):
    if overdue:
        ars = svc.get_overdue_approvals(db)
        for ar in ars:
            _publish_overdue(ar)
        return ars
    return list_approvals(db, status=status, entity_type=entity_type, assigned_role=assigned_role)


@router.get("/approvals/{ar_id}", response_model=ApprovalRequestResponse)
def get_approval(ar_id: uuid.UUID, db: Session = Depends(get_db)):
    ar = get_approval_request(db, ar_id)
    if ar is None:
        raise HTTPException(status_code=404, detail=f"ApprovalRequest {ar_id} not found")
    return ar


@router.post("/approvals/{ar_id}/approve", response_model=ApprovalRequestResponse)
def approve_request(
    ar_id: uuid.UUID,
    req: ApprovalActionRequest,
    db: Session = Depends(get_db),
):
    outcome = svc.process_approval(db, ar_id, req.actor_id, req.actor_role, req.note)
    _maybe_publish(outcome.event_type, outcome.event_payload)
    return outcome.ar


@router.post("/approvals/{ar_id}/reject", response_model=ApprovalRequestResponse)
def reject_request(
    ar_id: uuid.UUID,
    req: ApprovalRejectRequest,
    db: Session = Depends(get_db),
):
    outcome = svc.process_rejection(db, ar_id, req.actor_id, req.actor_role, req.rejection_reason)
    _maybe_publish(outcome.event_type, outcome.event_payload)
    return outcome.ar


def _maybe_publish(event_type: str | None, payload: dict | None) -> None:
    if not event_type:
        return
    try:
        _publisher.publish(event_type, payload or {})
    except Exception:
        logger.warning("Failed to publish event '%s'", event_type, exc_info=True)


def _publish_overdue(ar) -> None:
    try:
        _publisher.publish(
            "approval_overdue",
            {
                "ar_id": str(ar.id),
                "entity_type": ar.entity_type,
                "entity_id": str(ar.entity_id),
                "current_stage": ar.current_stage,
                "assigned_role": ar.assigned_role,
                "sla_deadline": ar.sla_deadline.isoformat(),
            },
        )
    except Exception:
        logger.warning("Failed to publish approval_overdue for AR %s", ar.id, exc_info=True)
