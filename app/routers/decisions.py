import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_executive, require_manager
from app.crud import decision as decision_crud
from app.models.user import User
from app.schemas.decision import (
    DecisionRecordResponse,
    DecisionRejectRequest,
)
from app.services import decision_service

router = APIRouter(tags=["decisions"])


@router.get("/decisions", response_model=list[DecisionRecordResponse])
def list_decisions(
    priority: str | None = None,
    status: str | None = Query(default=None),
    action_type: str | None = None,
    decision_type: str | None = None,
    kpi_id: uuid.UUID | None = None,
    limit: int = 100,
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return decision_crud.list_decisions(
        db,
        priority=priority,
        status=status,
        action_type=action_type,
        decision_type=decision_type,
        kpi_id=kpi_id,
        limit=limit,
        include_deleted=include_deleted,
    )


@router.get("/decisions/{decision_id}", response_model=DecisionRecordResponse)
def get_decision(
    decision_id: uuid.UUID,
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    record = decision_crud.get_decision(db, decision_id, include_deleted=include_deleted)
    if record is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return record


@router.get("/decisions/insight/{insight_id}", response_model=DecisionRecordResponse)
def get_decision_for_insight(
    insight_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    record = decision_crud.get_decision_by_insight(db, insight_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No decision found for this insight")
    return record


@router.post(
    "/decisions/trigger/{insight_id}",
    response_model=DecisionRecordResponse,
    status_code=201,
)
async def trigger_decision(
    insight_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager),
):
    """On-demand: run the decision pipeline for an existing InsightEvent.

    Idempotent — returns the existing record if already decided.
    """
    record = await decision_service.make_decision(db, insight_id)
    if record is None:
        raise HTTPException(status_code=404, detail="InsightEvent not found")
    return record


@router.post("/decisions/{decision_id}/approve", response_model=DecisionRecordResponse)
def approve_decision(
    decision_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_executive),
):
    """Approve a P1 decision that is awaiting human sign-off."""
    record = decision_crud.get_decision(db, decision_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if record.status != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Decision is not awaiting approval (current status: {record.status})",
        )
    return decision_crud.update_decision(
        db,
        record,
        status="approved",
        approved_by=current_user.id,
        approved_at=datetime.now(UTC),
    )


@router.post("/decisions/{decision_id}/reject", response_model=DecisionRecordResponse)
def reject_decision(
    decision_id: uuid.UUID,
    body: DecisionRejectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_executive),
):
    """Reject a P1 decision with a mandatory reason."""
    record = decision_crud.get_decision(db, decision_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if record.status != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Decision is not awaiting approval (current status: {record.status})",
        )
    return decision_crud.update_decision(
        db,
        record,
        status="rejected",
        approved_by=current_user.id,
        approved_at=datetime.now(UTC),
        rejection_reason=body.reason,
    )
