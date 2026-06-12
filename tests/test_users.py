import uuid

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.user import User, UserRole

client = TestClient(app)


def _signup(email: str, password: str = "password123") -> dict:
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201
    return response.json()


def _login(email: str, password: str = "password123") -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _promote(email: str, role: UserRole, is_admin: bool = True) -> str:
    """Set a user's role/is_admin directly in the DB and return a fresh token."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        user.role = role
        user.is_admin = is_admin
        db.commit()
    finally:
        db.close()
    return _login(email)


def _make_admin(email: str) -> str:
    return _promote(email, UserRole.EXECUTIVE, is_admin=True)


def test_only_admin_can_list_users():
    admin_email = f"admin-{uuid.uuid4().hex}@example.com"
    _signup(admin_email)
    admin_token = _make_admin(admin_email)

    member_email = f"member-{uuid.uuid4().hex}@example.com"
    member_token = _signup(member_email)["access_token"]

    forbidden_response = client.get("/api/v1/users", headers=_auth_headers(member_token))
    assert forbidden_response.status_code == 403

    ok_response = client.get("/api/v1/users", headers=_auth_headers(admin_token))
    assert ok_response.status_code == 200
    emails = [u["email"] for u in ok_response.json()]
    assert admin_email in emails
    assert member_email in emails


def test_admin_can_update_another_users_role():
    admin_email = f"admin-{uuid.uuid4().hex}@example.com"
    _signup(admin_email)
    admin_token = _make_admin(admin_email)

    member_email = f"member-{uuid.uuid4().hex}@example.com"
    _signup(member_email)

    admin_headers = _auth_headers(admin_token)
    list_response = client.get("/api/v1/users", headers=admin_headers)
    member_id = next(u["id"] for u in list_response.json() if u["email"] == member_email)

    update_response = client.patch(
        f"/api/v1/users/{member_id}",
        headers=admin_headers,
        json={"role": "manager", "is_admin": True},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["role"] == "manager"
    assert updated["is_admin"] is True


def test_admin_cannot_update_own_account():
    admin_email = f"admin-{uuid.uuid4().hex}@example.com"
    _signup(admin_email)
    admin_token = _make_admin(admin_email)
    admin_headers = _auth_headers(admin_token)

    list_response = client.get("/api/v1/users", headers=admin_headers)
    admin_id = next(u["id"] for u in list_response.json() if u["email"] == admin_email)

    response = client.patch(
        f"/api/v1/users/{admin_id}",
        headers=admin_headers,
        json={"is_admin": False},
    )
    assert response.status_code == 400


def test_non_admin_cannot_update_users():
    admin_email = f"admin-{uuid.uuid4().hex}@example.com"
    _signup(admin_email)
    admin_token = _make_admin(admin_email)

    member_email = f"member-{uuid.uuid4().hex}@example.com"
    member_token = _signup(member_email)["access_token"]

    admin_headers = _auth_headers(admin_token)
    list_response = client.get("/api/v1/users", headers=admin_headers)
    member_id = next(u["id"] for u in list_response.json() if u["email"] == member_email)

    response = client.patch(
        f"/api/v1/users/{member_id}",
        headers=_auth_headers(member_token),
        json={"role": "manager"},
    )
    assert response.status_code == 403


def test_manager_admin_can_only_manage_analysts():
    manager_email = f"manager-{uuid.uuid4().hex}@example.com"
    _signup(manager_email)
    manager_token = _promote(manager_email, UserRole.MANAGER, is_admin=True)
    manager_headers = _auth_headers(manager_token)

    exec_email = f"exec-{uuid.uuid4().hex}@example.com"
    _signup(exec_email)
    _promote(exec_email, UserRole.EXECUTIVE, is_admin=True)

    analyst_email = f"analyst-{uuid.uuid4().hex}@example.com"
    _signup(analyst_email)

    list_response = client.get("/api/v1/users", headers=manager_headers)
    users_by_email = {u["email"]: u["id"] for u in list_response.json()}

    # Cannot modify an EXECUTIVE (higher rank)
    forbidden_response = client.patch(
        f"/api/v1/users/{users_by_email[exec_email]}",
        headers=manager_headers,
        json={"is_active": False},
    )
    assert forbidden_response.status_code == 403

    # Cannot promote an ANALYST to its own role or above
    promote_response = client.patch(
        f"/api/v1/users/{users_by_email[analyst_email]}",
        headers=manager_headers,
        json={"role": "manager"},
    )
    assert promote_response.status_code == 403

    # Can manage an ANALYST (lower rank)
    ok_response = client.patch(
        f"/api/v1/users/{users_by_email[analyst_email]}",
        headers=manager_headers,
        json={"is_active": False},
    )
    assert ok_response.status_code == 200
    assert ok_response.json()["is_active"] is False
