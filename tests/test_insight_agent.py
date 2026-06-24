"""
Unit tests for the Insight Agent GenAI layer — Gemini/ADK is mocked.

narrate() is async; tests drive it with asyncio.run() so they execute under the
plain pytest runner (this repo has no pytest-asyncio plugin configured).
"""

import asyncio
from unittest.mock import MagicMock, patch

from app.agents.insight_agent import InsightNarrative, _build_prompt, narrate

NARRATIVE_JSON = (
    '{"title": "Revenue spiked 38% in March", '
    '"category": "revenue surge", '
    '"severity": "warning", '
    '"summary": "March revenue jumped 38% above its trend line, a notable one-off '
    'spike worth investigating."}'
)


def _context() -> dict:
    return {
        "kpi_id": "11111111-1111-1111-1111-111111111111",
        "kpi_name": "Total Revenue",
        "kpi_category": "revenue",
        "unit": "$",
        "direction": "up_is_good",
        "value": 500000.0,
        "expected": 362000.0,
        "z_score": 3.31,
        "rolling_avg_3m": 410000.0,
        "rolling_avg_6m": 380000.0,
        "trend_slope": 9.44,
        "insight_type": "spike",
        "recent_values": [320000.0, 340000.0, 360000.0, 380000.0, 500000.0],
    }


def _final_event(text: str) -> MagicMock:
    event = MagicMock()
    event.is_final_response.return_value = True
    event.content.parts = [MagicMock(text=text)]
    return event


def test_narrate_returns_none_without_api_key():
    with patch("app.agents.insight_agent.settings") as mock_settings:
        mock_settings.GEMINI_API_KEY = None
        result = asyncio.run(narrate(_context()))
    assert result is None


def test_narrate_parses_llm_json():
    async def fake_run_async(**kwargs):
        yield _final_event(NARRATIVE_JSON)

    with (
        patch("app.agents.insight_agent._runner") as mock_runner,
        patch("app.agents.insight_agent.settings") as mock_settings,
    ):
        mock_settings.GEMINI_API_KEY = "test-key"
        mock_settings.GEMINI_LLM_MODEL = "gemini-2.0-flash"
        mock_runner.run_async = fake_run_async

        result = asyncio.run(narrate(_context()))

    assert isinstance(result, InsightNarrative)
    assert result.title == "Revenue spiked 38% in March"
    assert result.category == "revenue surge"
    assert result.severity == "warning"
    assert "38%" in result.summary


def test_narrate_returns_none_on_unparseable_response():
    async def fake_run_async(**kwargs):
        yield _final_event("not json at all")

    with (
        patch("app.agents.insight_agent._runner") as mock_runner,
        patch("app.agents.insight_agent.settings") as mock_settings,
    ):
        mock_settings.GEMINI_API_KEY = "test-key"
        mock_settings.GEMINI_LLM_MODEL = "gemini-2.0-flash"
        mock_runner.run_async = fake_run_async

        result = asyncio.run(narrate(_context()))

    assert result is None  # graceful degradation, no exception


def test_build_prompt_includes_key_signals():
    prompt = _build_prompt(_context())
    assert "Total Revenue" in prompt
    assert "spike" in prompt
    assert "up_is_good" in prompt
    # recent values are formatted into the prompt
    assert "500000.00" in prompt
