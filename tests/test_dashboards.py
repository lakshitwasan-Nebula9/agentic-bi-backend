import uuid

from fastapi.testclient import TestClient

from app.main import app

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
