"""Archive & Recovery surface: deleted-state passthrough, /connectors/archived, and purge.

Follows the CLAUDE.md test contract — each test creates its own users/connectors with
unique identifiers and removes them in teardown (no unscoped deletes, no count assertions).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.connector import DataConnector
from app.models.user import User, UserRole

client = TestClient(app)

_created_emails: list[str] = []
_created_connector_ids: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        if _created_connector_ids:
            db.query(DataConnector).filter(
                DataConnector.id.in_([uuid.UUID(cid) for cid in _created_connector_ids])
            ).delete(synchronize_session=False)
        if _created_emails:
            db.query(User).filter(User.email.in_(_created_emails)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
        _created_connector_ids.clear()
        _created_emails.clear()


def _token(role: UserRole) -> str:
    """Sign up a fresh user, force its role in the DB, and return a bearer token."""
    email = f"archive-{role.value}-{uuid.uuid4().hex}@example.com"
    _created_emails.append(email)
    signup = client.post("/api/v1/auth/signup", json={"email": email, "password": "password123"})
    assert signup.status_code == 201

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        user.role = role
        db.commit()
    finally:
        db.close()

    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200
    return login.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_connector(headers: dict[str, str]) -> str:
    resp = client.post(
        "/api/v1/connectors",
        headers=headers,
        json={
            "name": f"archive-src-{uuid.uuid4().hex}",
            "host": "localhost",
            "port": 5432,
            "database_name": "agentic_bi",
            "username": "user",
            "password": "password",
        },
    )
    assert resp.status_code == 201
    connector_id = resp.json()["id"]
    _created_connector_ids.append(connector_id)
    return connector_id


def test_deleted_state_is_reported_in_include_deleted_listing():
    headers = _headers(_token(UserRole.MANAGER))
    connector_id = _create_connector(headers)

    assert client.delete(f"/api/v1/connectors/{connector_id}", headers=headers).status_code == 204

    resp = client.get("/api/v1/connectors?include_deleted=true", headers=headers)
    assert resp.status_code == 200
    match = next((c for c in resp.json() if c["id"] == connector_id), None)
    assert match is not None
    assert match["is_deleted"] is True
    assert match["deleted_at"] is not None


def test_archived_endpoint_lists_deleted_and_excludes_live():
    headers = _headers(_token(UserRole.MANAGER))
    archived_id = _create_connector(headers)
    live_id = _create_connector(headers)

    assert client.delete(f"/api/v1/connectors/{archived_id}", headers=headers).status_code == 204

    resp = client.get("/api/v1/connectors/archived", headers=headers)
    assert resp.status_code == 200
    body = resp.json()

    match = next((c for c in body if c["id"] == archived_id), None)
    assert match is not None
    assert match["expires_at"] is not None
    assert isinstance(match["kpi_count"], int)
    assert isinstance(match["table_count"], int)

    assert all(c["id"] != live_id for c in body)


def test_purge_removes_archived_connector():
    headers = _headers(_token(UserRole.MANAGER))
    connector_id = _create_connector(headers)
    assert client.delete(f"/api/v1/connectors/{connector_id}", headers=headers).status_code == 204

    purge = client.delete(f"/api/v1/connectors/{connector_id}/purge", headers=headers)
    assert purge.status_code == 204

    archived = client.get("/api/v1/connectors/archived", headers=headers)
    assert all(c["id"] != connector_id for c in archived.json())

    include_deleted = client.get("/api/v1/connectors?include_deleted=true", headers=headers)
    assert all(c["id"] != connector_id for c in include_deleted.json())


def test_purge_rejects_live_connector():
    headers = _headers(_token(UserRole.MANAGER))
    connector_id = _create_connector(headers)

    resp = client.delete(f"/api/v1/connectors/{connector_id}/purge", headers=headers)
    assert resp.status_code == 400


def test_purge_requires_manager():
    manager_headers = _headers(_token(UserRole.MANAGER))
    connector_id = _create_connector(manager_headers)
    assert (
        client.delete(f"/api/v1/connectors/{connector_id}", headers=manager_headers).status_code
        == 204
    )

    analyst_headers = _headers(_token(UserRole.ANALYST))
    resp = client.delete(f"/api/v1/connectors/{connector_id}/purge", headers=analyst_headers)
    assert resp.status_code == 403
