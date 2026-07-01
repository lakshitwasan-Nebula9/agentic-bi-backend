import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.hitl_workflow_service import (
    create_kpi_approval,
    process_approval,
    process_rejection,
)


def _make_ar(stage: str = "analyst_review", status: str = "pending", entity_id=None):
    ar = MagicMock()
    ar.id = uuid.uuid4()
    ar.entity_id = entity_id or uuid.uuid4()
    ar.entity_type = "kpi"
    ar.current_stage = stage
    ar.status = status
    ar.assigned_role = {
        "analyst_review": "analyst",
        "business_owner_review": "business_owner",
        "certification_review": "executive",
    }[stage]
    return ar


def test_hitl_creates_approval_requests_on_kpi_generated():
    from app.agents.hitl_workflow_agent import generate_kpi_approvals

    db = MagicMock()
    kpi_ids = [uuid.uuid4(), uuid.uuid4()]
    fake_ar = _make_ar()

    with patch(
        "app.agents.hitl_workflow_agent.create_kpi_approval", return_value=fake_ar
    ) as mock_create:
        ars = generate_kpi_approvals(db, kpi_ids)

    assert mock_create.call_count == 2
    assert len(ars) == 2


def test_hitl_skips_duplicate_for_existing_pending_approval():
    db = MagicMock()
    kpi_id = uuid.uuid4()
    existing_ar = _make_ar()

    with patch(
        "app.services.hitl_workflow_service.get_approval_by_entity", return_value=existing_ar
    ):
        result = create_kpi_approval(db, kpi_id)

    assert result is existing_ar


def test_advance_to_final_stage_certifies_kpi_and_closes_ar():
    db = MagicMock()
    ar = _make_ar(stage="certification_review")
    actor_id = uuid.uuid4()
    kpi = MagicMock()
    kpi.id = ar.entity_id

    with (
        patch("app.services.hitl_workflow_service.get_approval_request", return_value=ar),
        patch("app.services.hitl_workflow_service.kpi_crud.get_kpi", return_value=kpi),
        patch("app.services.hitl_workflow_service.kpi_crud.certify_kpi") as mock_certify,
        patch("app.services.hitl_workflow_service.close_approval") as mock_close,
    ):
        outcome = process_approval(db, ar.id, actor_id, "executive")

    mock_certify.assert_called_once_with(db, kpi, certified_by=actor_id)
    mock_close.assert_called_once()
    assert outcome.event_type == "kpi_certified"
    assert outcome.event_payload["kpi_id"] == str(ar.entity_id)


def test_rejection_at_any_stage_rejects_kpi_and_closes_ar():
    db = MagicMock()
    ar = _make_ar(stage="analyst_review")
    actor_id = uuid.uuid4()
    kpi = MagicMock()
    kpi.id = ar.entity_id

    with (
        patch("app.services.hitl_workflow_service.get_approval_request", return_value=ar),
        patch("app.services.hitl_workflow_service.kpi_crud.get_kpi", return_value=kpi),
        patch("app.services.hitl_workflow_service.kpi_crud.reject_kpi") as mock_reject,
        patch("app.services.hitl_workflow_service.close_approval") as mock_close,
    ):
        outcome = process_rejection(db, ar.id, actor_id, "analyst", "Formula is wrong")

    mock_reject.assert_called_once_with(db, kpi, rejected_by=actor_id, reason="Formula is wrong")
    mock_close.assert_called_once()
    assert outcome.event_type == "kpi_rejected"
    assert outcome.event_payload["reason"] == "Formula is wrong"


def test_junior_role_raises_403_on_approve():
    # Rank-based guard: a role less senior than the stage's assigned role is denied.
    db = MagicMock()
    ar = _make_ar(stage="certification_review")  # assigned executive
    actor_id = uuid.uuid4()

    with patch("app.services.hitl_workflow_service.get_approval_request", return_value=ar):
        with pytest.raises(HTTPException) as exc_info:
            process_approval(db, ar.id, actor_id, "analyst")

    assert exc_info.value.status_code == 403


def test_senior_role_can_action_lower_assigned_stage():
    # Rank-based guard: a more senior role may action a stage assigned to a junior role.
    db = MagicMock()
    ar = _make_ar(stage="certification_review")
    ar.assigned_role = "manager"
    actor_id = uuid.uuid4()
    kpi = MagicMock()
    kpi.id = ar.entity_id

    with (
        patch("app.services.hitl_workflow_service.get_approval_request", return_value=ar),
        patch("app.services.hitl_workflow_service.kpi_crud.get_kpi", return_value=kpi),
        patch("app.services.hitl_workflow_service.kpi_crud.certify_kpi") as mock_certify,
        patch("app.services.hitl_workflow_service.close_approval"),
    ):
        outcome = process_approval(db, ar.id, actor_id, "executive")

    mock_certify.assert_called_once_with(db, kpi, certified_by=actor_id)
    assert outcome.event_type == "kpi_certified"


def test_wrong_role_raises_403_on_reject():
    db = MagicMock()
    ar = _make_ar(stage="certification_review")
    actor_id = uuid.uuid4()

    with patch("app.services.hitl_workflow_service.get_approval_request", return_value=ar):
        with pytest.raises(HTTPException) as exc_info:
            process_rejection(db, ar.id, actor_id, "analyst", "Not my call")

    assert exc_info.value.status_code == 403
