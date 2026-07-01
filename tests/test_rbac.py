"""RBAC endpoint-guard checks for the role-only model.

Verifies the capability matrix at the HTTP boundary: FastAPI resolves the role
guard (require_manager / require_executive) before the path handler runs, so a
random entity UUID is enough to prove whether the guard admits or rejects a
caller — an admitted caller falls through to a 404 (entity missing), never a 403.

The rank-based *internal* HITL stage check is covered separately by
tests/test_hitl_workflow_agent.py.

Follows the CLAUDE.md test contract: each test creates its own users with unique
emails and removes them in teardown (no unscoped deletes, no count assertions).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.user import User, UserRole

client = TestClient(app)

_created_emails: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup_users():
    yield
    if not _created_emails:
        return
    db = SessionLocal()
    try:
        db.query(User).filter(User.email.in_(_created_emails)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
        _created_emails.clear()


def _token(role: UserRole) -> str:
    """Sign up a fresh user, force its role in the DB, and return a bearer token."""
    email = f"rbac-{role.value}-{uuid.uuid4().hex}@example.com"
    _created_emails.append(email)
    signup = client.post("/api/v1/auth/signup", json={"email": email, "password": "password123"})
    assert signup.status_code == 201

    # First-ever user becomes EXECUTIVE; otherwise ANALYST. Force the target role.
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


def _rand() -> str:
    return str(uuid.uuid4())


# --- KPI certify / reject / delete → Manager+ ------------------------------


def test_analyst_cannot_certify_kpi():
    token = _token(UserRole.ANALYST)
    r = client.post(f"/api/v1/kpis/{_rand()}/certify", headers=_headers(token), json={})
    assert r.status_code == 403


def test_manager_passes_certify_guard():
    token = _token(UserRole.MANAGER)
    r = client.post(f"/api/v1/kpis/{_rand()}/certify", headers=_headers(token), json={})
    # Guard admits the manager; handler then 404s on the missing KPI.
    assert r.status_code != 403


def test_analyst_cannot_reject_kpi():
    token = _token(UserRole.ANALYST)
    r = client.post(f"/api/v1/kpis/{_rand()}/reject", headers=_headers(token), json={})
    assert r.status_code == 403


def test_analyst_cannot_delete_kpi():
    token = _token(UserRole.ANALYST)
    r = client.delete(f"/api/v1/kpis/{_rand()}", headers=_headers(token))
    assert r.status_code == 403


def test_manager_passes_delete_guard():
    token = _token(UserRole.MANAGER)
    r = client.delete(f"/api/v1/kpis/{_rand()}", headers=_headers(token))
    assert r.status_code != 403


# --- HITL approve / reject → Manager+ (token-derived actor) -----------------


def test_analyst_cannot_approve_hitl():
    token = _token(UserRole.ANALYST)
    r = client.post(f"/api/v1/approvals/{_rand()}/approve", headers=_headers(token), json={})
    assert r.status_code == 403


def test_manager_approve_hitl_uses_token_actor_not_body():
    token = _token(UserRole.MANAGER)
    # Body carries no actor fields anymore; an empty body must not 422, and the
    # guard must admit the manager (handler then 404s on the missing request).
    r = client.post(f"/api/v1/approvals/{_rand()}/approve", headers=_headers(token), json={})
    assert r.status_code not in (403, 422)


def test_executive_passes_hitl_approve_guard():
    token = _token(UserRole.EXECUTIVE)
    r = client.post(f"/api/v1/approvals/{_rand()}/approve", headers=_headers(token), json={})
    assert r.status_code not in (403, 422)


# --- Report generation → Manager+ ------------------------------------------


def test_analyst_cannot_generate_report():
    token = _token(UserRole.ANALYST)
    r = client.post("/api/v1/reports", headers=_headers(token), json={})
    assert r.status_code == 403


# --- Decision approve / reject → Executive only -----------------------------


def test_manager_cannot_approve_decision():
    token = _token(UserRole.MANAGER)
    r = client.post(f"/api/v1/decisions/{_rand()}/approve", headers=_headers(token))
    assert r.status_code == 403


def test_executive_passes_decision_approve_guard():
    token = _token(UserRole.EXECUTIVE)
    r = client.post(f"/api/v1/decisions/{_rand()}/approve", headers=_headers(token))
    # Executive clears the guard; handler then 404s on the missing decision.
    assert r.status_code != 403


def test_manager_cannot_reject_decision():
    token = _token(UserRole.MANAGER)
    r = client.post(
        f"/api/v1/decisions/{_rand()}/reject",
        headers=_headers(token),
        json={"reason": "no"},
    )
    assert r.status_code == 403


# --- User management → Executive only ---------------------------------------


def test_analyst_and_manager_cannot_list_users():
    for role in (UserRole.ANALYST, UserRole.MANAGER):
        token = _token(role)
        r = client.get("/api/v1/users", headers=_headers(token))
        assert r.status_code == 403, role


def test_executive_can_list_users():
    token = _token(UserRole.EXECUTIVE)
    r = client.get("/api/v1/users", headers=_headers(token))
    assert r.status_code == 200
