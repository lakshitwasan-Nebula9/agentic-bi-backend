"""Dashboard category: dynamic values + auto-derivation from the linked data source.

Categories mirror the GenAI-assigned KPI categories of a dashboard's connector, so
there is no fixed allow-list — an explicit category is accepted as-is, and when a
dashboard is created from a connector its category is inferred from that DB's KPIs.

Follows the CLAUDE.md test contract — each test creates its own rows with unique
identifiers and removes them in teardown (no unscoped deletes, no count assertions).
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.connector import DataConnector
from app.models.dashboard import Dashboard
from app.models.dataset import Dataset
from app.models.kpi import KPIDefinition
from app.models.user import User
from app.services import dashboard_service

client = TestClient(app)

_created_dashboard_ids: list[str] = []
_created_emails: list[str] = []
_created_connector_ids: list[uuid.UUID] = []
_created_dataset_ids: list[uuid.UUID] = []
_created_kpi_ids: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        if _created_dashboard_ids:
            db.query(Dashboard).filter(
                Dashboard.id.in_([uuid.UUID(d) for d in _created_dashboard_ids])
            ).delete(synchronize_session=False)
        if _created_kpi_ids:
            db.query(KPIDefinition).filter(KPIDefinition.id.in_(_created_kpi_ids)).delete(
                synchronize_session=False
            )
        if _created_dataset_ids:
            db.query(Dataset).filter(Dataset.id.in_(_created_dataset_ids)).delete(
                synchronize_session=False
            )
        if _created_connector_ids:
            db.query(DataConnector).filter(DataConnector.id.in_(_created_connector_ids)).delete(
                synchronize_session=False
            )
        if _created_emails:
            db.query(User).filter(User.email.in_(_created_emails)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
        for bucket in (
            _created_dashboard_ids,
            _created_emails,
            _created_connector_ids,
            _created_dataset_ids,
            _created_kpi_ids,
        ):
            bucket.clear()


def _headers() -> dict[str, str]:
    email = f"dash-cat-{uuid.uuid4().hex}@example.com"
    _created_emails.append(email)
    resp = client.post("/api/v1/auth/signup", json={"email": email, "password": "password123"})
    assert resp.status_code == 201
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create(headers: dict[str, str], **body) -> dict:
    body.setdefault("name", f"dash-{uuid.uuid4().hex}")
    resp = client.post("/api/v1/dashboards", headers=headers, json=body)
    if resp.status_code == 201:
        _created_dashboard_ids.append(resp.json()["id"])
    return resp


def _seed_connector(categories: list[str]) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Create a connector → dataset → one KPI per given category.

    Returns (connector_id, kpi_ids).
    """
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    try:
        connector = DataConnector(
            name=f"cat-conn-{suffix}",
            connector_type="postgres",
            host="localhost",
            port=5432,
            database_name="seed",
            username="seed",
            encrypted_password="x",
        )
        db.add(connector)
        db.flush()
        dataset = Dataset(
            connector_id=connector.id, name=f"cat-ds-{suffix}", source_query="SELECT 1"
        )
        db.add(dataset)
        db.flush()
        now = datetime.now(UTC)
        seeded_kpi_ids: list[uuid.UUID] = []
        for i, category in enumerate(categories):
            kpi = KPIDefinition(
                dataset_id=dataset.id,
                table_name=dataset.name,
                name=f"kpi-{suffix}-{i}",
                display_name=f"KPI {i}",
                description="seed",
                category=category,
                formula="SUM(amount)",
                sql_expression="SUM(amount)",
                direction="up_is_good",
                status="draft",
                created_at=now,
            )
            db.add(kpi)
            db.flush()
            _created_kpi_ids.append(kpi.id)
            seeded_kpi_ids.append(kpi.id)
        db.commit()
        _created_connector_ids.append(connector.id)
        _created_dataset_ids.append(dataset.id)
        return connector.id, seeded_kpi_ids
    finally:
        db.close()


def test_explicit_category_persists_and_round_trips():
    headers = _headers()
    resp = _create(headers, category="revenue")
    assert resp.status_code == 201
    assert resp.json()["category"] == "revenue"

    listed = client.get("/api/v1/dashboards", headers=headers).json()
    match = next(d for d in listed if d["id"] == resp.json()["id"])
    assert match["category"] == "revenue"


def test_category_is_normalized_case_insensitively():
    resp = _create(_headers(), category="  Operational  ")
    assert resp.status_code == 201
    assert resp.json()["category"] == "operational"


def test_no_category_and_no_connector_is_null():
    resp = _create(_headers())
    assert resp.status_code == 201
    assert resp.json()["category"] is None


def test_category_auto_derived_from_connector():
    # Dominant category among the connector's KPIs is "revenue" (3 vs 1).
    connector_id, _ = _seed_connector(["revenue", "revenue", "revenue", "operational"])
    resp = _create(_headers(), connector_id=str(connector_id))
    assert resp.status_code == 201
    assert resp.json()["category"] == "revenue"


def test_explicit_category_overrides_connector_derivation():
    connector_id, _ = _seed_connector(["revenue", "operational"])
    resp = _create(_headers(), connector_id=str(connector_id), category="customer")
    assert resp.status_code == 201
    assert resp.json()["category"] == "customer"


def test_dominant_category_derived_from_dashboard_widgets():
    # Backfill path: a blank dashboard's category is inferred from the KPIs its
    # widgets reference (2 distinct revenue vs 1 operational → revenue).
    _, kpi_ids = _seed_connector(["revenue", "revenue", "operational"])
    headers = _headers()
    dash_id = _create(headers).json()["id"]
    for kpi_id in kpi_ids:
        resp = client.post(
            f"/api/v1/dashboards/{dash_id}/widgets",
            headers=headers,
            json={
                "widget_type": "kpi_tile",
                "title": "w",
                "config": {"kpi_id": str(kpi_id)},
                "x": 0,
                "y": 0,
                "w": 2,
                "h": 2,
            },
        )
        assert resp.status_code == 201

    db = SessionLocal()
    try:
        derived = dashboard_service._dominant_category_from_widgets(db, uuid.UUID(dash_id))
    finally:
        db.close()
    assert derived == "revenue"


def test_update_sets_and_clears_category():
    headers = _headers()
    dash_id = _create(headers, category="marketing").json()["id"]

    updated = client.patch(
        f"/api/v1/dashboards/{dash_id}", headers=headers, json={"category": "operational"}
    )
    assert updated.status_code == 200
    assert updated.json()["category"] == "operational"

    cleared = client.patch(f"/api/v1/dashboards/{dash_id}", headers=headers, json={"category": ""})
    assert cleared.status_code == 200
    assert cleared.json()["category"] is None
