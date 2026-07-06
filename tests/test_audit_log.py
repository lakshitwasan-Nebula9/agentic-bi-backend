"""Tests for the append-only audit log: the record_audit writer, the
Executive-only viewer API with its filters, and the append-only guarantee
(no mutation routes).

Follows the CLAUDE.md test contract: each test creates its own rows with unique
identifiers and removes them in teardown — no unscoped deletes, no global count
assertions (the suite runs against Supabase).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole

client = TestClient(app)

_created_emails: list[str] = []
_created_audit_ids: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        if _created_audit_ids:
            db.query(AuditLog).filter(AuditLog.id.in_(_created_audit_ids)).delete(
                synchronize_session=False
            )
        if _created_emails:
            db.query(User).filter(User.email.in_(_created_emails)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
        _created_audit_ids.clear()
        _created_emails.clear()


def _token(role: UserRole) -> str:
    """Sign up a fresh user, force its role in the DB, and return a bearer token."""
    email = f"audit-{role.value}-{uuid.uuid4().hex}@example.com"
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


def _seed(action: str, entity_type: str, entity_id: uuid.UUID, **kwargs) -> uuid.UUID:
    """Insert one audit row via the service writer; track it for cleanup."""
    from app.services.audit_service import record_audit

    db = SessionLocal()
    try:
        entry = record_audit(
            db, action=action, entity_type=entity_type, entity_id=entity_id, **kwargs
        )
        assert entry is not None
        _created_audit_ids.append(entry.id)
        return entry.id
    finally:
        db.close()


# --- record_audit writer ----------------------------------------------------


def test_record_audit_inserts_retrievable_row():
    entity_id = uuid.uuid4()
    audit_id = _seed(
        "kpi.certified", "kpi", entity_id, actor_role="system", summary="unit-test row"
    )

    db = SessionLocal()
    try:
        row = db.get(AuditLog, audit_id)
        assert row is not None
        assert row.action == "kpi.certified"
        assert row.entity_type == "kpi"
        assert row.entity_id == entity_id
        assert row.actor_role == "system"
        assert row.created_at is not None
    finally:
        db.close()


# --- viewer API + filters ---------------------------------------------------


def test_executive_can_list_and_filter_audit_logs():
    token = _token(UserRole.EXECUTIVE)
    entity_id = uuid.uuid4()
    _seed("decision.created", "decision", entity_id, actor_role="system", summary="filter target")
    _seed("kpi.updated", "kpi", uuid.uuid4(), actor_role="system", summary="noise")

    # Filter by the unique entity_id → exactly our seeded decision row.
    r = client.get(
        "/api/v1/audit-logs",
        headers=_headers(token),
        params={"entity_id": str(entity_id)},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["action"] == "decision.created"
    assert body[0]["entity_type"] == "decision"
    assert body[0]["entity_id"] == str(entity_id)

    # Filter by action narrows to the decision event as well.
    r2 = client.get(
        "/api/v1/audit-logs",
        headers=_headers(token),
        params={"action": "decision.created", "entity_id": str(entity_id)},
    )
    assert r2.status_code == 200
    assert len(r2.json()) == 1

    # A non-matching entity_type filter yields nothing for this entity.
    r3 = client.get(
        "/api/v1/audit-logs",
        headers=_headers(token),
        params={"entity_id": str(entity_id), "entity_type": "kpi"},
    )
    assert r3.status_code == 200
    assert r3.json() == []


def test_limit_is_respected():
    token = _token(UserRole.EXECUTIVE)
    entity_id = uuid.uuid4()
    for _ in range(3):
        _seed("kpi.updated", "kpi", entity_id, actor_role="system")

    r = client.get(
        "/api/v1/audit-logs",
        headers=_headers(token),
        params={"entity_id": str(entity_id), "limit": 2},
    )
    assert r.status_code == 200
    assert len(r.json()) == 2


# --- role gating ------------------------------------------------------------


def test_manager_and_analyst_cannot_read_audit_logs():
    for role in (UserRole.ANALYST, UserRole.MANAGER):
        token = _token(role)
        r = client.get("/api/v1/audit-logs", headers=_headers(token))
        assert r.status_code == 403, role


# --- append-only guarantee --------------------------------------------------


def test_audit_log_resource_exposes_no_mutation_routes():
    mutating = {"POST", "PUT", "PATCH", "DELETE"}
    for route in app.routes:
        path = getattr(route, "path", "")
        if "audit-logs" in path:
            methods = getattr(route, "methods", set()) or set()
            assert not (methods & mutating), f"{path} exposes {methods & mutating}"
