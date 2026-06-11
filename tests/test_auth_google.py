import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import auth_service, google_oauth_service

client = TestClient(app)


def _mock_google_user(monkeypatch, *, subject: str, email: str):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_ALLOWED_DOMAIN", None)

    def fake_verify(token, request, audience):
        return {
            "iss": "https://accounts.google.com",
            "email_verified": True,
            "sub": subject,
            "email": email,
            "hd": "example.com",
        }

    monkeypatch.setattr(google_oauth_service.id_token, "verify_oauth2_token", fake_verify)


def test_google_login_creates_new_analyst_user(monkeypatch):
    subject = f"google-{uuid.uuid4().hex}"
    email = f"google-new-{uuid.uuid4().hex}@example.com"
    _mock_google_user(monkeypatch, subject=subject, email=email)

    response = client.post("/api/v1/auth/google", json={"id_token": "fake-token"})

    assert response.status_code == 200
    token = response.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == email
    assert body["role"] == "analyst"
    assert body["is_admin"] is False


def test_google_login_links_existing_local_account(monkeypatch):
    email = f"google-link-{uuid.uuid4().hex}@example.com"
    signup = client.post("/api/v1/auth/signup", json={"email": email, "password": "password123"})
    assert signup.status_code == 201

    subject = f"google-{uuid.uuid4().hex}"
    _mock_google_user(monkeypatch, subject=subject, email=email)

    response = client.post("/api/v1/auth/google", json={"id_token": "fake-token"})
    assert response.status_code == 200
    token = response.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_google_login_existing_google_user_logs_in_again(monkeypatch):
    subject = f"google-{uuid.uuid4().hex}"
    email = f"google-repeat-{uuid.uuid4().hex}@example.com"
    _mock_google_user(monkeypatch, subject=subject, email=email)

    first = client.post("/api/v1/auth/google", json={"id_token": "fake-token"})
    assert first.status_code == 200
    first_user_id = auth_service.decode_access_token(first.json()["access_token"])["sub"]

    second = client.post("/api/v1/auth/google", json={"id_token": "fake-token"})
    assert second.status_code == 200
    second_user_id = auth_service.decode_access_token(second.json()["access_token"])["sub"]

    assert first_user_id == second_user_id


def test_google_login_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_ALLOWED_DOMAIN", None)

    def fake_verify(token, request, audience):
        raise ValueError("invalid token")

    monkeypatch.setattr(google_oauth_service.id_token, "verify_oauth2_token", fake_verify)

    response = client.post("/api/v1/auth/google", json={"id_token": "bad-token"})
    assert response.status_code == 401
