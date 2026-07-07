"""Unit tests for the periodic feedback -> guidance learning loop.
Gemini and DB calls are mocked (async narrate-style pattern, per test_insight_agent.py)."""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.agents.insight_guidance_agent import GuidanceSummary
from app.services import insight_guidance_service as svc


def _feedback_row(insight_id, rating="down", comment=None, created_at=None):
    row = MagicMock()
    row.insight_id = insight_id
    row.rating = rating
    row.comment = comment
    row.created_at = created_at or datetime.now(UTC)
    return row


def test_generate_guidance_skips_when_too_little_feedback():
    db = MagicMock()
    with (
        patch("app.services.insight_guidance_service.guidance_crud") as mock_guidance_crud,
        patch("app.services.insight_guidance_service.list_since", return_value=[]),
    ):
        mock_guidance_crud.get_active.return_value = None
        result = asyncio.run(svc.generate_guidance(db, min_feedback=10))
    assert result is None
    mock_guidance_crud.create.assert_not_called()


def test_generate_guidance_skips_when_llm_returns_no_bullets():
    db = MagicMock()
    rows = [_feedback_row(uuid.uuid4()) for _ in range(10)]
    db.query.return_value.filter.return_value.all.return_value = []

    async def fake_summarize(*_a, **_kw):
        return GuidanceSummary(bullets=[])

    with (
        patch("app.services.insight_guidance_service.guidance_crud") as mock_guidance_crud,
        patch("app.services.insight_guidance_service.list_since", return_value=rows),
        patch(
            "app.services.insight_guidance_service.summarize_guidance", side_effect=fake_summarize
        ),
    ):
        mock_guidance_crud.get_active.return_value = None
        result = asyncio.run(svc.generate_guidance(db, min_feedback=5))

    assert result is None
    mock_guidance_crud.create.assert_not_called()


def test_generate_guidance_creates_row_when_bullets_returned():
    db = MagicMock()
    insight_id = uuid.uuid4()
    rows = [_feedback_row(insight_id, comment="too generic") for _ in range(5)]
    db.query.return_value.filter.return_value.all.return_value = []  # InsightEvent lookup

    async def fake_summarize(prior, items):
        assert len(items) == 5
        return GuidanceSummary(bullets=["Prefer root-cause framing over KPI restatement"])

    with (
        patch("app.services.insight_guidance_service.guidance_crud") as mock_guidance_crud,
        patch("app.services.insight_guidance_service.list_since", return_value=rows),
        patch(
            "app.services.insight_guidance_service.summarize_guidance", side_effect=fake_summarize
        ),
        patch("app.services.insight_guidance_service.record_audit") as mock_audit,
    ):
        mock_guidance_crud.get_active.return_value = None
        mock_guidance_crud.create.return_value = MagicMock(id=uuid.uuid4())

        result = asyncio.run(svc.generate_guidance(db, min_feedback=5))

    assert result is mock_guidance_crud.create.return_value
    mock_guidance_crud.create.assert_called_once()
    kwargs = mock_guidance_crud.create.call_args.kwargs
    assert "Prefer root-cause framing" in kwargs["guidance_text"]
    assert kwargs["feedback_count_considered"] == 5
    mock_audit.assert_called_once()


def test_get_active_guidance_text_returns_none_when_no_active_row():
    db = MagicMock()
    with patch("app.services.insight_guidance_service.guidance_crud") as mock_guidance_crud:
        mock_guidance_crud.get_active.return_value = None
        assert svc.get_active_guidance_text(db) is None
