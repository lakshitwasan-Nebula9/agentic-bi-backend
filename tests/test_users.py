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


def _promote(email: str, role: UserRole) -> str:
    """Set a user's role directly in the DB and return a fresh token."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        user.role = role
        db.commit()
    finally:
        db.close()
    return _login(email)


def _make_admin(email: str) -> str:
    return _promote(email, UserRole.EXECUTIVE)


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
        json={"role": "manager"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["role"] == "manager"
    assert "is_admin" not in updated


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
        json={"is_active": False},
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


def test_manager_cannot_access_user_management():
    # User management is Executive-only in the role-only model.
    manager_email = f"manager-{uuid.uuid4().hex}@example.com"
    _signup(manager_email)
    manager_token = _promote(manager_email, UserRole.MANAGER)

    response = client.get("/api/v1/users", headers=_auth_headers(manager_token))
    assert response.status_code == 403


def test_executive_rank_limits_when_managing_users():
    exec_email = f"exec-{uuid.uuid4().hex}@example.com"
    _signup(exec_email)
    exec_token = _promote(exec_email, UserRole.EXECUTIVE)
    exec_headers = _auth_headers(exec_token)

    peer_exec_email = f"exec2-{uuid.uuid4().hex}@example.com"
    _signup(peer_exec_email)
    _promote(peer_exec_email, UserRole.EXECUTIVE)

    analyst_email = f"analyst-{uuid.uuid4().hex}@example.com"
    _signup(analyst_email)

    list_response = client.get("/api/v1/users", headers=exec_headers)
    users_by_email = {u["email"]: u["id"] for u in list_response.json()}

    # Cannot modify a peer EXECUTIVE (equal rank)
    forbidden_response = client.patch(
        f"/api/v1/users/{users_by_email[peer_exec_email]}",
        headers=exec_headers,
        json={"is_active": False},
    )
    assert forbidden_response.status_code == 403

    # Cannot promote an ANALYST to its own (top) role
    promote_response = client.patch(
        f"/api/v1/users/{users_by_email[analyst_email]}",
        headers=exec_headers,
        json={"role": "executive"},
    )
    assert promote_response.status_code == 403

    # Can manage an ANALYST (lower rank)
    ok_response = client.patch(
        f"/api/v1/users/{users_by_email[analyst_email]}",
        headers=exec_headers,
        json={"is_active": False},
    )
    assert ok_response.status_code == 200
    assert ok_response.json()["is_active"] is False


def _delete_users(*emails: str) -> None:
    db = SessionLocal()
    try:
        db.query(User).filter(User.email.in_(emails)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_analyst_cannot_create_user():
    analyst_email = f"analyst-{uuid.uuid4().hex}@example.com"
    analyst_token = _signup(analyst_email)["access_token"]
    try:
        response = client.post(
            "/api/v1/users",
            headers=_auth_headers(analyst_token),
            json={
                "email": f"new-{uuid.uuid4().hex}@example.com",
                "password": "password123",
                "role": "analyst",
            },
        )
        assert response.status_code == 403
    finally:
        _delete_users(analyst_email)


def test_manager_cannot_create_user():
    manager_email = f"manager-{uuid.uuid4().hex}@example.com"
    _signup(manager_email)
    manager_token = _promote(manager_email, UserRole.MANAGER)
    try:
        response = client.post(
            "/api/v1/users",
            headers=_auth_headers(manager_token),
            json={
                "email": f"new-{uuid.uuid4().hex}@example.com",
                "password": "password123",
                "role": "analyst",
            },
        )
        assert response.status_code == 403
    finally:
        _delete_users(manager_email)


def test_executive_creates_manager_who_can_log_in():
    exec_email = f"exec-{uuid.uuid4().hex}@example.com"
    _signup(exec_email)
    exec_token = _make_admin(exec_email)

    new_email = f"created-mgr-{uuid.uuid4().hex}@example.com"
    try:
        response = client.post(
            "/api/v1/users",
            headers=_auth_headers(exec_token),
            json={"email": new_email, "password": "temp-pass-123", "role": "manager"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["role"] == "manager"
        assert body["email"] == new_email
        assert "is_admin" not in body

        # The created user can log in with the temp password and is a manager.
        new_token = _login(new_email, "temp-pass-123")
        me = client.get("/api/v1/users/me", headers=_auth_headers(new_token))
        assert me.status_code == 200
        assert me.json()["role"] == "manager"
    finally:
        _delete_users(exec_email, new_email)


def test_executive_cannot_create_executive():
    exec_email = f"exec-{uuid.uuid4().hex}@example.com"
    _signup(exec_email)
    exec_token = _make_admin(exec_email)
    try:
        response = client.post(
            "/api/v1/users",
            headers=_auth_headers(exec_token),
            json={
                "email": f"new-exec-{uuid.uuid4().hex}@example.com",
                "password": "password123",
                "role": "executive",
            },
        )
        assert response.status_code == 403
    finally:
        _delete_users(exec_email)


def test_create_user_rejects_duplicate_email():
    exec_email = f"exec-{uuid.uuid4().hex}@example.com"
    _signup(exec_email)
    exec_token = _make_admin(exec_email)

    dup_email = f"dup-{uuid.uuid4().hex}@example.com"
    try:
        first = client.post(
            "/api/v1/users",
            headers=_auth_headers(exec_token),
            json={"email": dup_email, "password": "password123", "role": "analyst"},
        )
        assert first.status_code == 201

        second = client.post(
            "/api/v1/users",
            headers=_auth_headers(exec_token),
            json={"email": dup_email, "password": "password123", "role": "analyst"},
        )
        assert second.status_code == 400
    finally:
        _delete_users(exec_email, dup_email)
