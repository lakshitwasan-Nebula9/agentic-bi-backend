"""Integration test for GET /insights/{id}/explanation through the ASGI stack.

Seeds a minimal connector → dataset → KPI → insight graph in the DB, then verifies
the lazy-build path (no receipt yet) returns the four modal values, and that a
second call is served idempotently (same receipt id).
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded_insight():
    """Insert a connector/dataset/KPI/insight graph; yield the insight id; clean up after."""
    from app.core.database import SessionLocal
    from app.models.connector import DataConnector
    from app.models.dataset import Dataset
    from app.models.explanation import InsightExplanation
    from app.models.insight import InsightEvent
    from app.models.kpi import KPIDefinition

    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    connector = DataConnector(
        name=f"conn_{suffix}",
        host="localhost",
        database_name="sales_db",
        username="u",
        encrypted_password="x",
    )
    db.add(connector)
    db.flush()

    dataset = Dataset(
        connector_id=connector.id,
        name=f"ds_{suffix}",
        source_query="SELECT * FROM orders",
        quality_score=0.92,
        last_synced_at=datetime.now(UTC),
    )
    db.add(dataset)
    db.flush()

    kpi = KPIDefinition(
        dataset_id=dataset.id,
        table_name="orders",
        name=f"revenue_{suffix}",
        display_name="Revenue",
        description="North region revenue",
        category="revenue",
        formula="SUM(revenue) WHERE region='North'",
        sql_expression="SUM(revenue)",
        direction="up_is_good",
        status="certified",
    )
    db.add(kpi)
    db.flush()

    insight = InsightEvent(
        kpi_id=kpi.id,
        period_start=datetime.now(UTC),
        value=1000.0,
        z_score=3.2,
        insight_type="dip",
        is_anomaly=True,
        llm_summary="North India revenue down 18% vs 30-day baseline.",
    )
    db.add(insight)
    db.commit()
    insight_id = insight.id

    yield insight_id

    # Delete children before parents and commit each step — there are no ORM
    # relationships between these tables, so the unit-of-work can't order the
    # deletes for us across the raw foreign keys.
    db.query(InsightExplanation).filter(InsightExplanation.insight_event_id == insight_id).delete()
    db.commit()
    for obj in (
        db.get(InsightEvent, insight_id),
        db.get(KPIDefinition, kpi.id),
        db.get(Dataset, dataset.id),
        db.get(DataConnector, connector.id),
    ):
        if obj is not None:
            db.delete(obj)
            db.commit()
    db.close()


def test_explanation_returns_404_for_unknown_insight(client):
    resp = client.get(f"/api/v1/insights/{uuid.uuid4()}/explanation")
    assert resp.status_code == 404


def test_explanation_lazy_builds_and_serves(client, seeded_insight):
    resp = client.get(f"/api/v1/insights/{seeded_insight}/explanation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_dataset"] == "sales_db.orders"
    assert body["kpi_formula"] == "SUM(revenue) WHERE region='North'"
    assert body["data_freshness_at"] is not None
    assert 0 <= body["confidence_score"] <= 100
    assert body["rationale"] == "North India revenue down 18% vs 30-day baseline."

    # Second call is served from the stored receipt (same id).
    again = client.get(f"/api/v1/insights/{seeded_insight}/explanation")
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]
