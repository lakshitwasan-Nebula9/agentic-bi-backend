"""
Unit tests for the Decision Service and Decision Agent GenAI layer.

All DB and LLM calls are mocked — no Supabase or Gemini needed.
Async functions are driven with asyncio.run() (no pytest-asyncio required).
"""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.decision_agent import DecisionOutput, _build_prompt, recommend
from app.services.decision_service import (
    derive_decision_type,
    derive_priority,
    resolve_owner_role,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    is_anomaly: bool = True,
    llm_severity: str = "critical",
    trend_slope: float = 0.0,
    insight_type: str = "spike",
) -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.kpi_id = uuid.uuid4()
    event.is_anomaly = is_anomaly
    event.llm_severity = llm_severity
    event.trend_slope = trend_slope
    event.insight_type = insight_type
    event.value = 500_000.0
    event.baseline_mean = 360_000.0
    event.z_score = 3.1
    event.rolling_avg_3m = 410_000.0
    event.rolling_avg_6m = 380_000.0
    event.period_start = datetime(2026, 1, 1, tzinfo=UTC)
    event.llm_title = "Revenue spike"
    event.llm_category = "revenue surge"
    event.llm_summary = "Revenue jumped 38% above trend."
    return event


def _make_kpi(category: str = "revenue") -> MagicMock:
    kpi = MagicMock()
    kpi.id = uuid.uuid4()
    kpi.category = category
    kpi.display_name = "Total Revenue"
    kpi.unit = "$"
    kpi.direction = "up_is_good"
    return kpi


def _final_event(text: str) -> MagicMock:
    ev = MagicMock()
    ev.is_final_response.return_value = True
    ev.content.parts = [MagicMock(text=text)]
    return ev


DECISION_JSON = (
    '{"action_type": "investigate", '
    '"rationale": "Anomaly confirmed at critical severity.", '
    '"action_summary": "Assign analyst to identify root cause.", '
    '"business_impact": "Revenue leakage will continue unaddressed.", '
    '"confidence": 0.92}'
)

# ---------------------------------------------------------------------------
# derive_priority
# ---------------------------------------------------------------------------


def test_priority_p1_anomaly_critical():
    event = _make_event(is_anomaly=True, llm_severity="critical")
    assert derive_priority(event) == "P1"


def test_priority_p2_anomaly_warning():
    event = _make_event(is_anomaly=True, llm_severity="warning")
    assert derive_priority(event) == "P2"


def test_priority_p2_adverse_slope():
    event = _make_event(is_anomaly=False, llm_severity="info", trend_slope=-6.0)
    assert derive_priority(event) == "P2"


def test_priority_p3_stable():
    event = _make_event(is_anomaly=False, llm_severity="info", trend_slope=-2.0)
    assert derive_priority(event) == "P3"


def test_priority_p3_info_anomaly():
    # info severity overrides anomaly flag → P3 (not P1 or P2)
    event = _make_event(is_anomaly=True, llm_severity="info")
    assert derive_priority(event) == "P3"


# ---------------------------------------------------------------------------
# resolve_owner_role
# ---------------------------------------------------------------------------


def test_owner_p1_always_executive():
    kpi = _make_kpi(category="operational")
    assert resolve_owner_role(kpi, "P1") == "executive"


def test_owner_revenue_kpi_p2():
    kpi = _make_kpi(category="revenue")
    assert resolve_owner_role(kpi, "P2") == "executive"


def test_owner_operational_kpi_p2():
    kpi = _make_kpi(category="operational")
    assert resolve_owner_role(kpi, "P2") == "operations"


def test_owner_unknown_category_falls_back():
    kpi = _make_kpi(category="unknown_category_xyz")
    assert resolve_owner_role(kpi, "P2") == "analyst"


def test_owner_none_kpi_returns_default():
    assert resolve_owner_role(None, "P2") == "analyst"


# ---------------------------------------------------------------------------
# derive_decision_type
# ---------------------------------------------------------------------------


def test_decision_type_p1_is_approval_required():
    assert derive_decision_type("P1", "escalate") == "approval_required"
    assert derive_decision_type("P1", "investigate") == "approval_required"


def test_decision_type_p2_investigate_is_corrective():
    assert derive_decision_type("P2", "investigate") == "corrective"


def test_decision_type_p2_optimize_is_corrective():
    assert derive_decision_type("P2", "optimize") == "corrective"


def test_decision_type_p3_optimize_is_preventive():
    assert derive_decision_type("P3", "optimize") == "preventive"


def test_decision_type_p3_monitor_is_informational():
    assert derive_decision_type("P3", "monitor") == "informational"


def test_decision_type_none_action_is_informational():
    assert derive_decision_type("P3", None) == "informational"


# ---------------------------------------------------------------------------
# recommend() — LLM layer
# ---------------------------------------------------------------------------


def test_recommend_returns_none_without_api_key():
    with patch("app.agents.decision_agent.settings") as mock_settings:
        mock_settings.GEMINI_API_KEY = None
        result = asyncio.run(recommend({"insight_event_id": str(uuid.uuid4()), "priority": "P1"}))
    assert result is None


def test_recommend_parses_llm_json():
    async def fake_run_async(**kwargs):
        yield _final_event(DECISION_JSON)

    with (
        patch("app.agents.decision_agent._runner") as mock_runner,
        patch("app.agents.decision_agent.settings") as mock_settings,
    ):
        mock_settings.GEMINI_API_KEY = "test-key"
        mock_settings.GEMINI_LLM_MODEL = "gemini-2.0-flash"
        mock_runner.run_async = fake_run_async

        result = asyncio.run(recommend({"insight_event_id": str(uuid.uuid4()), "priority": "P1"}))

    assert isinstance(result, DecisionOutput)
    assert result.action_type == "investigate"
    assert result.confidence == pytest.approx(0.92)
    assert "analyst" in result.action_summary


def test_recommend_returns_none_on_bad_json():
    async def fake_run_async(**kwargs):
        yield _final_event("not json")

    with (
        patch("app.agents.decision_agent._runner") as mock_runner,
        patch("app.agents.decision_agent.settings") as mock_settings,
    ):
        mock_settings.GEMINI_API_KEY = "test-key"
        mock_settings.GEMINI_LLM_MODEL = "gemini-2.0-flash"
        mock_runner.run_async = fake_run_async

        result = asyncio.run(recommend({"insight_event_id": str(uuid.uuid4()), "priority": "P2"}))

    assert result is None


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_includes_key_signals():
    context = {
        "kpi_name": "Total Revenue",
        "kpi_category": "revenue",
        "unit": "$",
        "direction": "up_is_good",
        "period_start": "2026-01-01T00:00:00+00:00",
        "value": 500_000.0,
        "baseline_mean": 360_000.0,
        "z_score": 3.1,
        "is_anomaly": True,
        "insight_type": "spike",
        "trend_slope": 9.4,
        "rolling_avg_3m": 410_000.0,
        "rolling_avg_6m": 380_000.0,
        "recent_values": [320_000.0, 360_000.0, 500_000.0],
        "llm_title": "Revenue spike",
        "llm_severity": "critical",
        "llm_summary": "Revenue jumped 38% above trend.",
        "priority": "P1",
        "recommended_owner_role": "executive",
        "insight_event_id": str(uuid.uuid4()),
        "llm_category": "revenue surge",
    }
    prompt = _build_prompt(context)
    assert "Total Revenue" in prompt
    assert "P1" in prompt
    assert "spike" in prompt
    assert "executive" in prompt
    assert "500000.00" in prompt


# ---------------------------------------------------------------------------
# make_decision() — service integration (DB mocked)
# ---------------------------------------------------------------------------


def test_make_decision_p1_sets_awaiting_approval():
    from app.services import decision_service

    insight_id = uuid.uuid4()
    event = _make_event(is_anomaly=True, llm_severity="critical")
    event.id = insight_id
    kpi = _make_kpi("revenue")

    saved = {}

    def fake_create(db, record):
        saved["record"] = record
        record.id = uuid.uuid4()
        return record

    def fake_update(db, record, **kwargs):
        for k, v in kwargs.items():
            setattr(record, k, v)
        saved["updated"] = record
        return record

    with (
        patch.object(
            decision_crud := __import__("app.crud.decision", fromlist=["decision_crud"]),
            "get_decision_by_insight",
            return_value=None,
        ),
        patch.object(decision_crud, "create_decision", side_effect=fake_create),
        patch.object(decision_crud, "update_decision", side_effect=fake_update),
        patch("app.services.decision_service.get_kpi", return_value=kpi),
        patch("app.services.decision_service.recommend", new=AsyncMock(return_value=None)),
    ):
        # db.get returns the event
        db = MagicMock()
        db.get.return_value = event

        result = asyncio.run(decision_service.make_decision(db, insight_id))

    assert result is not None
    assert result.priority == "P1"
    assert result.status == "awaiting_approval"
    assert result.requires_approval is True
    assert result.recommended_owner_role == "executive"


def test_make_decision_p3_sets_decided():
    from app.services import decision_service

    insight_id = uuid.uuid4()
    event = _make_event(is_anomaly=False, llm_severity="info", trend_slope=1.0)
    event.id = insight_id
    kpi = _make_kpi("operational")

    saved = {}

    def fake_create(db, record):
        saved["record"] = record
        record.id = uuid.uuid4()
        return record

    def fake_update(db, record, **kwargs):
        for k, v in kwargs.items():
            setattr(record, k, v)
        return record

    with (
        patch.object(
            decision_crud := __import__("app.crud.decision", fromlist=["decision_crud"]),
            "get_decision_by_insight",
            return_value=None,
        ),
        patch.object(decision_crud, "create_decision", side_effect=fake_create),
        patch.object(decision_crud, "update_decision", side_effect=fake_update),
        patch("app.services.decision_service.get_kpi", return_value=kpi),
        patch("app.services.decision_service.recommend", new=AsyncMock(return_value=None)),
    ):
        db = MagicMock()
        db.get.return_value = event

        result = asyncio.run(decision_service.make_decision(db, insight_id))

    assert result is not None
    assert result.priority == "P3"
    assert result.status == "decided"
    assert result.requires_approval is False


def test_make_decision_idempotent():
    from app.services import decision_service

    existing = MagicMock()
    existing.id = uuid.uuid4()

    with patch("app.services.decision_service.decision_crud") as mock_crud:
        mock_crud.get_decision_by_insight.return_value = existing
        db = MagicMock()
        result = asyncio.run(decision_service.make_decision(db, uuid.uuid4()))

    assert result is existing
    mock_crud.create_decision.assert_not_called()


def test_make_decision_returns_none_for_missing_insight():
    from app.services import decision_service

    with patch("app.services.decision_service.decision_crud") as mock_crud:
        mock_crud.get_decision_by_insight.return_value = None
        db = MagicMock()
        db.get.return_value = None
        result = asyncio.run(decision_service.make_decision(db, uuid.uuid4()))

    assert result is None
