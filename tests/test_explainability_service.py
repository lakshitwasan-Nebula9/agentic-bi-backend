"""Unit tests for explainability_service.build_explanation — dependencies mocked."""

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.explainability_service import build_explanation


def _insight():
    return SimpleNamespace(
        id=uuid.uuid4(),
        kpi_id=uuid.uuid4(),
        z_score=3.0,
        trend_slope=None,
        value=500_000.0,
        baseline_mean=360_000.0,
    )


def test_build_explanation_derives_modal_values():
    insight = _insight()
    kpi = SimpleNamespace(
        table_name="orders",
        formula="SUM(revenue) WHERE region='North'",
        dataset_id=uuid.uuid4(),
        display_name="Total Revenue",
        unit="$",
        direction="up_is_good",
    )
    synced = datetime.now(UTC)
    dataset = SimpleNamespace(connector_id=uuid.uuid4(), last_synced_at=synced, quality_score=0.9)
    connector = SimpleNamespace(database_name="sales_db")

    db = MagicMock()
    db.query.return_value.filter.return_value.count.return_value = 12
    db.query.return_value.filter.return_value.first.return_value = connector

    with (
        patch("app.services.explainability_service.get_kpi", return_value=kpi),
        patch("app.services.explainability_service.get_dataset", return_value=dataset),
        patch(
            "app.services.explainability_service._call_gemini_explainability",
            new=AsyncMock(return_value=None),
        ),
        patch("app.services.explainability_service.upsert_explanation") as mock_upsert,
    ):
        asyncio.run(build_explanation(db, insight))

    kwargs = mock_upsert.call_args.kwargs
    assert kwargs["source_dataset"] == "sales_db.orders"
    assert kwargs["kpi_formula"] == "SUM(revenue) WHERE region='North'"
    assert kwargs["data_freshness_at"] == synced
    assert kwargs["insight_event_id"] == insight.id
    assert kwargs["kpi_id"] == insight.kpi_id
    assert 0 <= kwargs["confidence_score"] <= 100


def test_build_explanation_handles_missing_connector():
    insight = _insight()
    kpi = SimpleNamespace(
        table_name="orders",
        formula="SUM(x)",
        dataset_id=uuid.uuid4(),
        display_name="Orders",
        unit="units",
        direction="up_is_good",
    )
    dataset = SimpleNamespace(
        connector_id=uuid.uuid4(), last_synced_at=datetime.now(UTC), quality_score=0.5
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.count.return_value = 6
    db.query.return_value.filter.return_value.first.return_value = None

    with (
        patch("app.services.explainability_service.get_kpi", return_value=kpi),
        patch("app.services.explainability_service.get_dataset", return_value=dataset),
        patch(
            "app.services.explainability_service._call_gemini_explainability",
            new=AsyncMock(return_value=None),
        ),
        patch("app.services.explainability_service.upsert_explanation") as mock_upsert,
    ):
        asyncio.run(build_explanation(db, insight))

    # Falls back to the bare table name when the connector can't be resolved.
    assert mock_upsert.call_args.kwargs["source_dataset"] == "orders"
