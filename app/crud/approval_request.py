import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.approval_request import ApprovalRequest

# DEMO: collapsed to executive-only approval; analyst and business owner stages commented out
STAGE_SEQUENCE = [
    # "analyst_review",
    # "business_owner_review",
    "certification_review",
]
STAGE_ROLES: dict[str, str] = {
    # "analyst_review": "analyst",
    # "business_owner_review": "business_owner",
    "certification_review": "executive",
}


def create_approval_request(
    db: Session,
    entity_type: str,
    entity_id: uuid.UUID,
    stage: str,
    priority: int,
    sla_deadline: datetime,
    tenant_id: uuid.UUID | None = None,
) -> ApprovalRequest:
    ar = ApprovalRequest(
        entity_type=entity_type,
        entity_id=entity_id,
        current_stage=stage,
        status="pending",
        priority=priority,
        assigned_role=STAGE_ROLES[stage],
        sla_deadline=sla_deadline,
        tenant_id=tenant_id,
    )
    db.add(ar)
    db.commit()
    db.refresh(ar)
    return ar


def get_approval_request(db: Session, ar_id: uuid.UUID) -> ApprovalRequest | None:
    return db.get(ApprovalRequest, ar_id)


def get_approval_by_entity(
    db: Session,
    entity_type: str,
    entity_id: uuid.UUID,
    status: str = "pending",
) -> ApprovalRequest | None:
    return (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.entity_type == entity_type,
            ApprovalRequest.entity_id == entity_id,
            ApprovalRequest.status == status,
        )
        .first()
    )


def list_approvals(
    db: Session,
    status: str | None = None,
    entity_type: str | None = None,
    assigned_role: str | None = None,
) -> list[ApprovalRequest]:
    q = db.query(ApprovalRequest)
    if status is not None:
        q = q.filter(ApprovalRequest.status == status)
    if entity_type is not None:
        q = q.filter(ApprovalRequest.entity_type == entity_type)
    if assigned_role is not None:
        q = q.filter(ApprovalRequest.assigned_role == assigned_role)
    return q.order_by(ApprovalRequest.created_at.desc()).all()


def advance_stage(
    db: Session,
    ar: ApprovalRequest,
    next_stage: str,
    new_sla_deadline: datetime,
) -> ApprovalRequest:
    ar.current_stage = next_stage
    ar.assigned_role = STAGE_ROLES[next_stage]
    ar.sla_deadline = new_sla_deadline
    db.commit()
    db.refresh(ar)
    return ar


def close_approval(
    db: Session,
    ar: ApprovalRequest,
    status: str,
    resolved_by: uuid.UUID,
    note: str | None = None,
) -> ApprovalRequest:
    ar.status = status
    ar.resolved_at = datetime.now(UTC)
    ar.resolved_by = resolved_by
    ar.resolution_note = note
    db.commit()
    db.refresh(ar)
    return ar
