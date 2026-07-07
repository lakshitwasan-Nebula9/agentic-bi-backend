"""Unit tests for the feedback service: upsert/retract, and the suppression
heuristic. DB and embedding calls are mocked (same convention as
test_embedding_service.py / test_insight_agent.py) so these run fast and
without a live model load.
"""

import uuid
from unittest.mock import MagicMock, patch

from app.models.insight import InsightEvent
from app.models.insight_feedback import InsightFeedback
from app.models.user import User, UserRole
from app.services import insight_feedback_service as svc


def _insight(**overrides) -> InsightEvent:
    defaults = dict(
        id=uuid.uuid4(),
        kpi_id=uuid.uuid4(),
        insight_type="dip",
        llm_category="demand drop",
        llm_title="Orders dipped 20%",
    )
    defaults.update(overrides)
    return InsightEvent(**defaults)


def _user() -> User:
    return User(id=uuid.uuid4(), email="u@example.com", role=UserRole.ANALYST)


def test_submit_feedback_upserts_and_audits():
    insight = _insight()
    user = _user()
    db = MagicMock()

    with (
        patch("app.services.insight_feedback_service.feedback_crud") as mock_crud,
        patch("app.services.insight_feedback_service.record_audit") as mock_audit,
        patch.object(svc, "_store_suppression_vector") as mock_store_vec,
    ):
        mock_crud.upsert.return_value = MagicMock(spec=InsightFeedback)
        result = svc.submit_feedback(db, insight=insight, user=user, rating="up", comment="great")

    mock_crud.upsert.assert_called_once_with(
        db, insight_id=insight.id, user_id=user.id, rating="up", comment="great"
    )
    mock_audit.assert_called_once()
    mock_store_vec.assert_not_called()  # only "down" votes feed the suppression vector
    assert result is mock_crud.upsert.return_value


def test_submit_down_feedback_stores_suppression_vector():
    insight = _insight()
    user = _user()
    db = MagicMock()

    with (
        patch("app.services.insight_feedback_service.feedback_crud"),
        patch("app.services.insight_feedback_service.record_audit"),
        patch.object(svc, "_store_suppression_vector") as mock_store_vec,
    ):
        svc.submit_feedback(db, insight=insight, user=user, rating="down", comment="too generic")

    mock_store_vec.assert_called_once_with(db, insight, "too generic")


def test_retract_feedback_returns_false_when_nothing_active():
    db = MagicMock()
    user = _user()
    with patch("app.services.insight_feedback_service.feedback_crud") as mock_crud:
        mock_crud.get_active.return_value = None
        assert svc.retract_feedback(db, insight_id=uuid.uuid4(), user=user) is False


def test_retract_feedback_soft_deletes_existing():
    db = MagicMock()
    user = _user()
    existing = MagicMock(spec=InsightFeedback)
    with (
        patch("app.services.insight_feedback_service.feedback_crud") as mock_crud,
        patch("app.services.insight_feedback_service.record_audit") as mock_audit,
    ):
        mock_crud.get_active.return_value = existing
        assert svc.retract_feedback(db, insight_id=uuid.uuid4(), user=user) is True
    mock_crud.soft_delete.assert_called_once_with(db, existing)
    mock_audit.assert_called_once()


def _vote(insight_id: uuid.UUID, user_id: uuid.UUID | None = None) -> MagicMock:
    vote = MagicMock()
    vote.insight_id = insight_id
    vote.user_id = user_id or uuid.uuid4()
    return vote


def test_compute_suppression_flags_when_similar_downvotes_from_two_users():
    new_insight = _insight()
    db = MagicMock()

    prior_insight_id = uuid.uuid4()
    down_votes = [_vote(prior_insight_id), _vote(prior_insight_id)]  # 2 distinct users

    with (
        patch("app.services.insight_feedback_service.feedback_crud") as mock_crud,
        patch(
            "app.services.insight_feedback_service.embedding_service.generate_embedding",
            return_value=[0.0] * 384,
        ),
    ):
        mock_crud.list_ratings_since.side_effect = [down_votes, []]  # down, then up
        # Very similar (low cosine distance), well under the suppression threshold.
        db.query.return_value.filter.return_value.all.return_value = [(str(prior_insight_id), 0.02)]

        is_suppressed, score = svc.compute_suppression(db, new_insight)

    assert is_suppressed is True
    assert score > 0


def test_compute_suppression_not_flagged_with_single_user():
    new_insight = _insight()
    db = MagicMock()
    prior_insight_id = uuid.uuid4()
    down_votes = [_vote(prior_insight_id)]  # only 1 distinct user

    with (
        patch("app.services.insight_feedback_service.feedback_crud") as mock_crud,
        patch(
            "app.services.insight_feedback_service.embedding_service.generate_embedding",
            return_value=[0.0] * 384,
        ),
    ):
        mock_crud.list_ratings_since.side_effect = [down_votes, []]
        db.query.return_value.filter.return_value.all.return_value = [(str(prior_insight_id), 0.02)]

        is_suppressed, _score = svc.compute_suppression(db, new_insight)

    assert is_suppressed is False


def test_compute_suppression_upvotes_counteract_downvotes():
    new_insight = _insight()
    db = MagicMock()
    down_insight_id = uuid.uuid4()
    up_insight_id = uuid.uuid4()
    down_votes = [_vote(down_insight_id), _vote(down_insight_id)]
    up_votes = [_vote(up_insight_id), _vote(up_insight_id)]

    with (
        patch("app.services.insight_feedback_service.feedback_crud") as mock_crud,
        patch(
            "app.services.insight_feedback_service.embedding_service.generate_embedding",
            return_value=[0.0] * 384,
        ),
    ):
        mock_crud.list_ratings_since.side_effect = [down_votes, up_votes]
        # Equal down/up weight at the same similarity fully cancels out.
        db.query.return_value.filter.return_value.all.return_value = [
            (str(down_insight_id), 0.02),
            (str(up_insight_id), 0.02),
        ]

        is_suppressed, score = svc.compute_suppression(db, new_insight)

    assert is_suppressed is False
    assert score == 0.0


def test_compute_suppression_swallows_errors():
    new_insight = _insight()
    db = MagicMock()
    with patch("app.services.insight_feedback_service.feedback_crud") as mock_crud:
        mock_crud.list_ratings_since.side_effect = RuntimeError("db down")
        is_suppressed, score = svc.compute_suppression(db, new_insight)
    assert is_suppressed is False
    assert score == 0.0
