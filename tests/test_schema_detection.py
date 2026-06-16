import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.schema_detection import ColumnInput, SchemaDetectRequest

_FAKE_JSON = """{
  "entity_type": "orders",
  "description": "Transactional order records linking customers to purchased items.",
  "columns": [
    {"name": "id", "label": "Order ID", "business_definition": "Unique order identifier", "role": "identifier"},
    {"name": "customer_id", "label": "Customer", "business_definition": "Reference to the purchasing customer", "role": "identifier"},
    {"name": "total_amount", "label": "Order Value", "business_definition": "Total monetary value of the order", "role": "measure"},
    {"name": "created_at", "label": "Order Date", "business_definition": "Timestamp when the order was placed", "role": "date"}
  ],
  "identifiers": ["id", "customer_id"],
  "dimensions": [],
  "measures": ["total_amount"],
  "date_columns": ["created_at"],
  "suggested_kpis": ["Total Revenue", "Average Order Value", "Number of Orders"],
  "business_questions": [
    "What is the total revenue in a given period?",
    "How many orders were placed per customer?",
    "What is the average order value?"
  ]
}"""


def _make_request() -> SchemaDetectRequest:
    return SchemaDetectRequest(
        table_name="orders",
        columns=[
            ColumnInput(name="id", type="uuid"),
            ColumnInput(name="customer_id", type="uuid"),
            ColumnInput(name="total_amount", type="numeric"),
            ColumnInput(name="created_at", type="timestamp"),
        ],
    )


def _fake_final_event(text: str) -> MagicMock:
    part = MagicMock()
    part.text = text
    content = MagicMock()
    content.parts = [part]
    event = MagicMock()
    event.is_final_response.return_value = True
    event.content = content
    return event


async def _async_events(events: list):
    for e in events:
        yield e


def test_detect_returns_structured_response():
    request = _make_request()
    fake_id = uuid.uuid4()
    fake_record = MagicMock()
    fake_record.id = fake_id
    fake_schema_meta = MagicMock()
    fake_schema_meta.id = uuid.uuid4()

    async def run():
        with (
            patch("app.agents.schema_detection_agent.settings") as mock_cfg,
            patch("app.agents.schema_detection_agent._runner") as mock_runner,
            patch("app.agents.schema_detection_agent._session_service") as mock_ss,
            patch(
                "app.agents.schema_detection_agent.upsert_embedding",
                return_value=fake_record,
            ),
            patch(
                "app.agents.schema_detection_agent.upsert_schema_metadata",
                return_value=fake_schema_meta,
            ),
        ):
            mock_cfg.GEMINI_API_KEY = "fake-key"
            mock_cfg.GEMINI_LLM_MODEL = "gemini-1.5-flash"

            mock_session = MagicMock()
            mock_session.id = "sess-1"
            mock_ss.create_session = AsyncMock(return_value=mock_session)
            mock_runner.run_async.return_value = _async_events([_fake_final_event(_FAKE_JSON)])

            from app.agents.schema_detection_agent import detect

            return await detect(MagicMock(), request)

    response = asyncio.run(run())
    assert response.table_name == "orders"
    assert response.entity_type == "orders"
    assert len(response.columns) == 4
    assert response.columns[0].role == "identifier"
    assert response.columns[2].role == "measure"
    assert response.columns[3].role == "date"
    assert response.identifiers == ["id", "customer_id"]
    assert response.measures == ["total_amount"]
    assert response.date_columns == ["created_at"]
    assert "Total Revenue" in response.suggested_kpis
    assert len(response.business_questions) == 3
    assert response.embedding_id == fake_id


def test_detect_auto_embeds_with_correct_args():
    request = _make_request()
    fake_record = MagicMock()
    fake_record.id = uuid.uuid4()
    fake_schema_meta = MagicMock()
    fake_schema_meta.id = uuid.uuid4()
    captured = {}

    async def run():
        with (
            patch("app.agents.schema_detection_agent.settings") as mock_cfg,
            patch("app.agents.schema_detection_agent._runner") as mock_runner,
            patch("app.agents.schema_detection_agent._session_service") as mock_ss,
            patch(
                "app.agents.schema_detection_agent.upsert_embedding",
                return_value=fake_record,
            ) as mock_embed,
            patch(
                "app.agents.schema_detection_agent.upsert_schema_metadata",
                return_value=fake_schema_meta,
            ),
        ):
            mock_cfg.GEMINI_API_KEY = "fake-key"
            mock_cfg.GEMINI_LLM_MODEL = "gemini-1.5-flash"

            mock_session = MagicMock()
            mock_session.id = "sess-2"
            mock_ss.create_session = AsyncMock(return_value=mock_session)
            mock_runner.run_async.return_value = _async_events([_fake_final_event(_FAKE_JSON)])

            from app.agents.schema_detection_agent import detect

            await detect(MagicMock(), request)
            captured["call_args"] = mock_embed.call_args

    asyncio.run(run())
    args = captured["call_args"][0]
    assert args[1] == "schema_description"
    assert args[2] == "orders"
    # embed content should include key semantic fields for downstream RAG
    embed_text = args[3]
    assert "orders" in embed_text
    assert "total_amount" in embed_text


def test_detect_raises_503_when_api_key_missing():
    request = _make_request()

    async def run():
        with patch("app.agents.schema_detection_agent.settings") as mock_cfg:
            mock_cfg.GEMINI_API_KEY = None
            from app.agents.schema_detection_agent import detect

            return await detect(MagicMock(), request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status_code == 503


def test_detect_raises_502_on_unparseable_response():
    request = _make_request()

    async def run():
        with (
            patch("app.agents.schema_detection_agent.settings") as mock_cfg,
            patch("app.agents.schema_detection_agent._runner") as mock_runner,
            patch("app.agents.schema_detection_agent._session_service") as mock_ss,
        ):
            mock_cfg.GEMINI_API_KEY = "fake-key"
            mock_session = MagicMock()
            mock_session.id = "sess-3"
            mock_ss.create_session = AsyncMock(return_value=mock_session)
            mock_runner.run_async.return_value = _async_events(
                [_fake_final_event("not valid json {{")]
            )

            from app.agents.schema_detection_agent import detect

            return await detect(MagicMock(), request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status_code == 502
