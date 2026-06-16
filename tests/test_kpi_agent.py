"""
Unit tests for KPI Agent — all external dependencies (ADK, DB, embeddings) are mocked.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.agents.kpi_agent import generate_kpis_for_dataset


def _make_dataset(name: str = "orders") -> MagicMock:
    dataset = MagicMock()
    dataset.id = uuid.uuid4()
    dataset.name = name
    return dataset


def _make_schema_meta(table_name: str = "orders") -> MagicMock:
    meta = MagicMock()
    meta.table_name = table_name
    meta.entity_type = "transaction"
    meta.description = "Order records"
    meta.columns = [
        {"name": "total_amount", "role": "measure", "business_definition": "Order total"}
    ]
    meta.identifiers = ["order_id"]
    meta.dimensions = ["status"]
    meta.measures = ["total_amount"]
    meta.date_columns = ["created_at"]
    meta.suggested_kpis = ["Total Revenue"]
    meta.business_questions = ["What is the total revenue?"]
    return meta


LLM_JSON = '{"kpis": [{"name": "total_revenue", "display_name": "Total Revenue", "description": "Sum of all order amounts", "category": "revenue", "formula": "SUM(total_amount)", "sql_expression": "SUM(total_amount) AS total_revenue", "unit": "$", "direction": "up_is_good", "suggested_chart_type": "metric_card"}]}'


@pytest.mark.asyncio
async def test_generate_kpis_returns_structured_list():
    db = MagicMock()
    dataset = _make_dataset()
    schema_meta = _make_schema_meta()
    created_kpi = MagicMock()
    created_kpi.id = uuid.uuid4()
    created_kpi.name = "total_revenue"
    created_kpi.display_name = "Total Revenue"
    created_kpi.description = "Sum of all order amounts"
    created_kpi.category = "revenue"
    created_kpi.formula = "SUM(total_amount)"
    created_kpi.direction = "up_is_good"

    final_event = MagicMock()
    final_event.is_final_response.return_value = True
    final_event.content.parts = [MagicMock(text=LLM_JSON)]

    async def fake_run_async(**kwargs):
        yield final_event

    with (
        patch("app.agents.kpi_agent.get_dataset", return_value=dataset),
        patch("app.agents.kpi_agent.get_schema_metadata_by_table", return_value=schema_meta),
        patch("app.agents.kpi_agent.create_kpi", return_value=created_kpi),
        patch("app.agents.kpi_agent.compute_and_snapshot"),
        patch("app.agents.kpi_agent.upsert_embedding"),
        patch("app.agents.kpi_agent._runner") as mock_runner,
        patch("app.agents.kpi_agent.settings") as mock_settings,
    ):
        mock_settings.GEMINI_API_KEY = "test-key"
        mock_settings.GEMINI_LLM_MODEL = "gemini-2.0-flash"
        mock_runner.run_async = fake_run_async

        result = await generate_kpis_for_dataset(db, dataset.id)

    assert len(result) == 1
    assert result[0] == created_kpi.id


@pytest.mark.asyncio
async def test_generate_kpis_embeds_each_kpi():
    db = MagicMock()
    dataset = _make_dataset()
    schema_meta = _make_schema_meta()
    created_kpi = MagicMock()
    created_kpi.id = uuid.uuid4()
    created_kpi.name = "total_revenue"
    created_kpi.display_name = "Total Revenue"
    created_kpi.description = "Sum of all order amounts"
    created_kpi.category = "revenue"
    created_kpi.formula = "SUM(total_amount)"
    created_kpi.direction = "up_is_good"

    final_event = MagicMock()
    final_event.is_final_response.return_value = True
    final_event.content.parts = [MagicMock(text=LLM_JSON)]

    async def fake_run_async(**kwargs):
        yield final_event

    with (
        patch("app.agents.kpi_agent.get_dataset", return_value=dataset),
        patch("app.agents.kpi_agent.get_schema_metadata_by_table", return_value=schema_meta),
        patch("app.agents.kpi_agent.create_kpi", return_value=created_kpi),
        patch("app.agents.kpi_agent.compute_and_snapshot"),
        patch("app.agents.kpi_agent.upsert_embedding") as mock_embed,
        patch("app.agents.kpi_agent._runner") as mock_runner,
        patch("app.agents.kpi_agent.settings") as mock_settings,
    ):
        mock_settings.GEMINI_API_KEY = "test-key"
        mock_settings.GEMINI_LLM_MODEL = "gemini-2.0-flash"
        mock_runner.run_async = fake_run_async

        await generate_kpis_for_dataset(db, dataset.id)

    mock_embed.assert_called_once()
    call_args = mock_embed.call_args
    assert call_args[0][1] == "kpi_definition"
    assert call_args[0][2] == str(created_kpi.id)


@pytest.mark.asyncio
async def test_generate_kpis_raises_404_on_missing_dataset():
    from fastapi import HTTPException

    db = MagicMock()
    dataset_id = uuid.uuid4()

    with (
        patch("app.agents.kpi_agent.get_dataset", return_value=None),
        patch("app.agents.kpi_agent.settings") as mock_settings,
    ):
        mock_settings.GEMINI_API_KEY = "test-key"

        with pytest.raises(HTTPException) as exc_info:
            await generate_kpis_for_dataset(db, dataset_id)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_generate_kpis_raises_503_when_no_api_key():
    from fastapi import HTTPException

    db = MagicMock()
    dataset = _make_dataset()

    with (
        patch("app.agents.kpi_agent.get_dataset", return_value=dataset),
        patch("app.agents.kpi_agent.settings") as mock_settings,
    ):
        mock_settings.GEMINI_API_KEY = None

        with pytest.raises(HTTPException) as exc_info:
            await generate_kpis_for_dataset(db, dataset.id)

    assert exc_info.value.status_code == 503
