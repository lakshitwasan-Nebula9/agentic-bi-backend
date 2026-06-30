import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.connector import DataConnector
from app.models.dataset import Dataset
from app.models.kpi import KPIDefinition, KPISnapshot

client = TestClient(app)


def _signup_and_get_token() -> str:
    email = f"dashboard-test-{uuid.uuid4().hex}@example.com"
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_dashboard(headers: dict[str, str], name: str | None = None) -> dict:
    response = client.post(
        "/api/v1/dashboards",
        headers=headers,
        json={"name": name or f"dashboard-{uuid.uuid4().hex}"},
    )
    assert response.status_code == 201
    return response.json()


def test_dashboard_crud_flow():
    token = _signup_and_get_token()
    headers = _auth_headers(token)

    dashboard = _create_dashboard(headers, name="My Dashboard")
    assert dashboard["name"] == "My Dashboard"
    assert dashboard["is_default"] is False
    dashboard_id = dashboard["id"]

    list_response = client.get("/api/v1/dashboards", headers=headers)
    assert list_response.status_code == 200
    assert any(d["id"] == dashboard_id for d in list_response.json())

    get_response = client.get(f"/api/v1/dashboards/{dashboard_id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["widgets"] == []

    update_response = client.patch(
        f"/api/v1/dashboards/{dashboard_id}",
        headers=headers,
        json={"name": "Renamed Dashboard", "is_default": True},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Renamed Dashboard"
    assert update_response.json()["is_default"] is True

    delete_response = client.delete(f"/api/v1/dashboards/{dashboard_id}", headers=headers)
    assert delete_response.status_code == 204

    get_after_delete = client.get(f"/api/v1/dashboards/{dashboard_id}", headers=headers)
    assert get_after_delete.status_code == 404


def test_widget_crud_flow():
    token = _signup_and_get_token()
    headers = _auth_headers(token)
    dashboard_id = _create_dashboard(headers)["id"]

    create_response = client.post(
        f"/api/v1/dashboards/{dashboard_id}/widgets",
        headers=headers,
        json={
            "widget_type": "kpi_card",
            "title": "Revenue",
            "config": {"kpi": "revenue"},
            "x": 0,
            "y": 0,
            "w": 2,
            "h": 2,
        },
    )
    assert create_response.status_code == 201
    widget = create_response.json()
    assert widget["dashboard_id"] == dashboard_id
    widget_id = widget["id"]

    get_response = client.get(f"/api/v1/dashboards/{dashboard_id}", headers=headers)
    assert get_response.status_code == 200
    assert len(get_response.json()["widgets"]) == 1

    update_response = client.patch(
        f"/api/v1/dashboards/{dashboard_id}/widgets/{widget_id}",
        headers=headers,
        json={"title": "Total Revenue", "w": 4},
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "Total Revenue"
    assert update_response.json()["w"] == 4

    delete_response = client.delete(
        f"/api/v1/dashboards/{dashboard_id}/widgets/{widget_id}", headers=headers
    )
    assert delete_response.status_code == 204

    get_after_delete = client.get(f"/api/v1/dashboards/{dashboard_id}", headers=headers)
    assert get_after_delete.json()["widgets"] == []


def test_save_layout_updates_widget_coordinates():
    token = _signup_and_get_token()
    headers = _auth_headers(token)
    dashboard_id = _create_dashboard(headers)["id"]

    widget_a = client.post(
        f"/api/v1/dashboards/{dashboard_id}/widgets",
        headers=headers,
        json={"widget_type": "line_chart", "x": 0, "y": 0, "w": 4, "h": 4},
    ).json()
    widget_b = client.post(
        f"/api/v1/dashboards/{dashboard_id}/widgets",
        headers=headers,
        json={"widget_type": "bar_chart", "x": 4, "y": 0, "w": 4, "h": 4},
    ).json()

    layout_response = client.put(
        f"/api/v1/dashboards/{dashboard_id}/layout",
        headers=headers,
        json=[
            {"id": widget_a["id"], "x": 0, "y": 4, "w": 6, "h": 3},
            {"id": widget_b["id"], "x": 6, "y": 4, "w": 6, "h": 3},
        ],
    )
    assert layout_response.status_code == 200
    widgets_by_id = {w["id"]: w for w in layout_response.json()["widgets"]}
    assert widgets_by_id[widget_a["id"]]["y"] == 4
    assert widgets_by_id[widget_a["id"]]["w"] == 6
    assert widgets_by_id[widget_b["id"]]["x"] == 6


def test_save_layout_rejects_unknown_widget_id():
    token = _signup_and_get_token()
    headers = _auth_headers(token)
    dashboard_id = _create_dashboard(headers)["id"]

    layout_response = client.put(
        f"/api/v1/dashboards/{dashboard_id}/layout",
        headers=headers,
        json=[{"id": str(uuid.uuid4()), "x": 0, "y": 0, "w": 1, "h": 1}],
    )
    assert layout_response.status_code == 404


def test_dashboard_not_visible_to_other_users():
    owner_token = _signup_and_get_token()
    other_token = _signup_and_get_token()
    dashboard_id = _create_dashboard(_auth_headers(owner_token))["id"]

    response = client.get(f"/api/v1/dashboards/{dashboard_id}", headers=_auth_headers(other_token))
    assert response.status_code == 404


def test_dashboards_require_authentication():
    response = client.get("/api/v1/dashboards")
    assert response.status_code in (401, 403)


@pytest.fixture
def certified_kpi_connector():
    """Seed a connector → dataset → certified KPIs (+ snapshots) and clean up after."""
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    connector = DataConnector(
        name=f"preconfig-conn-{suffix}",
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
        connector_id=connector.id,
        name=f"preconfig-ds-{suffix}",
        source_query="SELECT 1",
    )
    db.add(dataset)
    db.flush()

    # One KPI per suggested_chart hint plus an unknown hint (→ kpi_tile fallback).
    chart_hints = ["line", "bar", "metric_card", "scatter"]
    kpis = []
    now = datetime.now(UTC).replace(day=1)
    for i, hint in enumerate(chart_hints):
        kpi = KPIDefinition(
            dataset_id=dataset.id,
            table_name=dataset.name,
            name=f"kpi-{suffix}-{i}",
            display_name=f"KPI {i}",
            description="seed",
            category="finance",
            formula="SUM(amount)",
            sql_expression="SUM(amount)",
            direction="up_is_good",
            suggested_chart=hint,
            status="certified",
            certified_at=now - timedelta(days=i),
        )
        db.add(kpi)
        db.flush()
        # Two monthly snapshots so enrichment yields current_value + MoM.
        db.add_all(
            [
                KPISnapshot(
                    kpi_id=kpi.id,
                    dataset_id=dataset.id,
                    value=200.0,
                    period_start=now,
                    period_end=now,
                ),
                KPISnapshot(
                    kpi_id=kpi.id,
                    dataset_id=dataset.id,
                    value=100.0,
                    period_start=now - timedelta(days=31),
                    period_end=now - timedelta(days=31),
                ),
            ]
        )
        kpis.append(kpi)
    db.commit()

    yield {"connector_id": connector.id, "kpi_ids": [k.id for k in kpis]}

    db.query(KPISnapshot).filter(KPISnapshot.kpi_id.in_([k.id for k in kpis])).delete(
        synchronize_session=False
    )
    db.query(KPIDefinition).filter(KPIDefinition.id.in_([k.id for k in kpis])).delete(
        synchronize_session=False
    )
    db.query(Dataset).filter(Dataset.id == dataset.id).delete(synchronize_session=False)
    db.query(DataConnector).filter(DataConnector.id == connector.id).delete(
        synchronize_session=False
    )
    db.commit()
    db.close()


def test_create_dashboard_preconfigures_widgets_from_connector(certified_kpi_connector):
    headers = _auth_headers(_signup_and_get_token())
    connector_id = str(certified_kpi_connector["connector_id"])

    create_response = client.post(
        "/api/v1/dashboards",
        headers=headers,
        json={"name": "Preconfigured", "connector_id": connector_id},
    )
    assert create_response.status_code == 201
    dashboard_id = create_response.json()["id"]

    detail = client.get(f"/api/v1/dashboards/{dashboard_id}", headers=headers).json()
    widgets = detail["widgets"]
    assert len(widgets) == 4

    types_by_kpi = {w["config"]["kpi_id"]: w["widget_type"] for w in widgets}
    kpi_ids = [str(k) for k in certified_kpi_connector["kpi_ids"]]
    assert types_by_kpi[kpi_ids[0]] == "line_chart"
    assert types_by_kpi[kpi_ids[1]] == "bar_chart"
    assert types_by_kpi[kpi_ids[2]] == "kpi_tile"
    assert types_by_kpi[kpi_ids[3]] == "kpi_tile"  # unknown hint → tile fallback

    # Tiles carry display fields; current_value 200 with prior 100 → +100% MoM.
    tile = next(w for w in widgets if w["widget_type"] == "kpi_tile")
    assert tile["config"]["value"] == 200.0
    assert tile["config"]["trend"] == 100.0
    assert tile["config"]["label"]

    # Every widget gets a grid slot and none overflow the 12-column grid.
    for w in widgets:
        assert w["x"] + w["w"] <= 12

    client.delete(f"/api/v1/dashboards/{dashboard_id}", headers=headers)


def test_create_dashboard_without_connector_stays_blank():
    headers = _auth_headers(_signup_and_get_token())
    dashboard_id = _create_dashboard(headers)["id"]
    detail = client.get(f"/api/v1/dashboards/{dashboard_id}", headers=headers).json()
    assert detail["widgets"] == []
    client.delete(f"/api/v1/dashboards/{dashboard_id}", headers=headers)


@pytest.fixture
def metric_card_series_connector():
    """Seed a connector whose certified KPIs are all metric_card but carry a
    monthly time series — exercises tile→line_chart promotion past the quota."""
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    connector = DataConnector(
        name=f"promote-conn-{suffix}",
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
        connector_id=connector.id,
        name=f"promote-ds-{suffix}",
        source_query="SELECT 1",
    )
    db.add(dataset)
    db.flush()

    now = datetime.now(UTC).replace(day=1)
    kpis = []
    for i in range(5):
        kpi = KPIDefinition(
            dataset_id=dataset.id,
            table_name=dataset.name,
            name=f"mc-{suffix}-{i}",
            display_name=f"Metric {i}",
            description="seed",
            category="finance",
            formula="SUM(amount)",
            sql_expression="SUM(amount)",
            direction="up_is_good",
            suggested_chart="metric_card",
            status="certified",
            certified_at=now - timedelta(days=i),
        )
        db.add(kpi)
        db.flush()
        # Three monthly snapshots → has_series is True.
        db.add_all(
            [
                KPISnapshot(
                    kpi_id=kpi.id,
                    dataset_id=dataset.id,
                    value=100.0 + 10 * m,
                    period_start=now - timedelta(days=31 * m),
                    period_end=now - timedelta(days=31 * m),
                )
                for m in range(3)
            ]
        )
        kpis.append(kpi)
    db.commit()

    yield {"connector_id": connector.id, "kpi_ids": [k.id for k in kpis]}

    db.query(KPISnapshot).filter(KPISnapshot.kpi_id.in_([k.id for k in kpis])).delete(
        synchronize_session=False
    )
    db.query(KPIDefinition).filter(KPIDefinition.id.in_([k.id for k in kpis])).delete(
        synchronize_session=False
    )
    db.query(Dataset).filter(Dataset.id == dataset.id).delete(synchronize_session=False)
    db.query(DataConnector).filter(DataConnector.id == connector.id).delete(
        synchronize_session=False
    )
    db.commit()
    db.close()


def test_metric_card_kpis_with_series_promote_to_line_charts(metric_card_series_connector):
    headers = _auth_headers(_signup_and_get_token())
    connector_id = str(metric_card_series_connector["connector_id"])

    create_response = client.post(
        "/api/v1/dashboards",
        headers=headers,
        json={"name": "Promotion", "connector_id": connector_id},
    )
    assert create_response.status_code == 201
    dashboard_id = create_response.json()["id"]

    detail = client.get(f"/api/v1/dashboards/{dashboard_id}", headers=headers).json()
    types_by_kpi = {w["config"]["kpi_id"]: w["widget_type"] for w in detail["widgets"]}
    kpi_ids = [str(k) for k in metric_card_series_connector["kpi_ids"]]
    # KPIs are ordered newest-certified first: first 3 stay headline tiles, the
    # remaining time-series KPIs are promoted to charts, alternating line/bar.
    assert [types_by_kpi[k] for k in kpi_ids] == [
        "kpi_tile",
        "kpi_tile",
        "kpi_tile",
        "line_chart",
        "bar_chart",
    ]

    client.delete(f"/api/v1/dashboards/{dashboard_id}", headers=headers)
