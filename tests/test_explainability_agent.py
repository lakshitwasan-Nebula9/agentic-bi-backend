"""Unit tests for ExplainabilityAgent.handle_event — DB and build step mocked.

handle_event is invoked unbound so the test never touches Redis (AgentSubscriber
construction creates consumer groups, which would require a broker).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.explainability_agent import ExplainabilityAgent
from app.agents.messaging import AgentEvent


def _event(payload: dict) -> AgentEvent:
    return AgentEvent(
        message_id="1-0",
        event_type="insight_detected",
        event_id=str(uuid.uuid4()),
        produced_at="2026-06-25T00:00:00Z",
        payload=payload,
    )


def test_handle_event_builds_explanation_for_insight():
    insight_id = uuid.uuid4()
    insight = MagicMock()
    db = MagicMock()
    db.get.return_value = insight

    with (
        patch("app.agents.explainability_agent.SessionLocal", return_value=db),
        patch(
            "app.agents.explainability_agent.build_explanation",
            new=AsyncMock(return_value=MagicMock(confidence_score=91)),
        ) as mock_build,
    ):
        ExplainabilityAgent.handle_event(MagicMock(), _event({"id": str(insight_id)}))

    mock_build.assert_called_once_with(db, insight)
    db.close.assert_called_once()


def test_handle_event_skips_when_id_missing():
    with (
        patch("app.agents.explainability_agent.SessionLocal") as mock_session,
        patch("app.agents.explainability_agent.build_explanation") as mock_build,
    ):
        ExplainabilityAgent.handle_event(MagicMock(), _event({}))

    mock_session.assert_not_called()
    mock_build.assert_not_called()


def test_handle_event_skips_when_insight_not_found():
    db = MagicMock()
    db.get.return_value = None

    with (
        patch("app.agents.explainability_agent.SessionLocal", return_value=db),
        patch("app.agents.explainability_agent.build_explanation") as mock_build,
    ):
        ExplainabilityAgent.handle_event(MagicMock(), _event({"id": str(uuid.uuid4())}))

    mock_build.assert_not_called()
    db.close.assert_called_once()
