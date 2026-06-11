import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _signup_and_get_token() -> str:
    email = f"connector-test-{uuid.uuid4().hex}@example.com"
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_connector_crud_flow():
    token = _signup_and_get_token()
    headers = _auth_headers(token)

    create_response = client.post(
        "/api/v1/connectors",
        headers=headers,
        json={
            "name": f"warehouse-{uuid.uuid4().hex}",
            "host": "localhost",
            "port": 5432,
            "database_name": "agentic_bi",
            "username": "user",
            "password": "password",
        },
    )
    assert create_response.status_code == 201
    connector = create_response.json()
    assert "password" not in connector
    assert "encrypted_password" not in connector
    connector_id = connector["id"]

    list_response = client.get("/api/v1/connectors", headers=headers)
    assert list_response.status_code == 200
    assert any(c["id"] == connector_id for c in list_response.json())

    get_response = client.get(f"/api/v1/connectors/{connector_id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["host"] == "localhost"

    update_response = client.patch(
        f"/api/v1/connectors/{connector_id}",
        headers=headers,
        json={"host": "db", "password": "new-password"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["host"] == "db"

    delete_response = client.delete(f"/api/v1/connectors/{connector_id}", headers=headers)
    assert delete_response.status_code == 204

    get_after_delete = client.get(f"/api/v1/connectors/{connector_id}", headers=headers)
    assert get_after_delete.status_code == 404


def test_connector_test_endpoint_reports_failure_for_unreachable_host():
    token = _signup_and_get_token()
    headers = _auth_headers(token)

    create_response = client.post(
        "/api/v1/connectors",
        headers=headers,
        json={
            "name": f"unreachable-{uuid.uuid4().hex}",
            "host": "localhost",
            "port": 1,
            "database_name": "agentic_bi",
            "username": "user",
            "password": "password",
        },
    )
    assert create_response.status_code == 201
    connector_id = create_response.json()["id"]

    test_response = client.post(f"/api/v1/connectors/{connector_id}/test", headers=headers)
    assert test_response.status_code == 200
    body = test_response.json()
    assert body["success"] is False
    assert body["message"]

    delete_response = client.delete(f"/api/v1/connectors/{connector_id}", headers=headers)
    assert delete_response.status_code == 204


def test_connector_requires_authentication():
    response = client.get("/api/v1/connectors")
    assert response.status_code in (401, 403)
