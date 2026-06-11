import pytest

from app.core.config import settings
from app.services import google_oauth_service
from app.services.google_oauth_service import GoogleOAuthError, verify_google_id_token


def test_verify_google_id_token_returns_user_info(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_ALLOWED_DOMAIN", None)

    def fake_verify(token, request, audience):
        assert token == "token"
        assert audience == "client-id"
        return {
            "iss": "https://accounts.google.com",
            "email_verified": True,
            "sub": "google-subject",
            "email": "user@gmail.com",
        }

    monkeypatch.setattr(google_oauth_service.id_token, "verify_oauth2_token", fake_verify)

    user_info = verify_google_id_token("token")

    assert user_info.subject == "google-subject"
    assert user_info.email == "user@gmail.com"


def test_verify_google_id_token_rejects_wrong_workspace_domain(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_ALLOWED_DOMAIN", "company.com")

    def fake_verify(token, request, audience):
        return {
            "iss": "accounts.google.com",
            "email_verified": True,
            "sub": "google-subject",
            "email": "user@example.com",
            "hd": "other.com",
        }

    monkeypatch.setattr(google_oauth_service.id_token, "verify_oauth2_token", fake_verify)

    with pytest.raises(GoogleOAuthError, match="domain is not allowed"):
        verify_google_id_token("token")


def test_verify_google_id_token_requires_verified_email(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_ALLOWED_DOMAIN", None)

    def fake_verify(token, request, audience):
        return {
            "iss": "accounts.google.com",
            "email_verified": False,
            "sub": "google-subject",
            "email": "user@example.com",
        }

    monkeypatch.setattr(google_oauth_service.id_token, "verify_oauth2_token", fake_verify)

    with pytest.raises(GoogleOAuthError, match="email is not verified"):
        verify_google_id_token("token")


def test_verify_google_id_token_rejects_non_authoritative_email(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_ALLOWED_DOMAIN", None)

    def fake_verify(token, request, audience):
        return {
            "iss": "accounts.google.com",
            "email_verified": True,
            "sub": "google-subject",
            "email": "user@example.com",
        }

    monkeypatch.setattr(google_oauth_service.id_token, "verify_oauth2_token", fake_verify)

    with pytest.raises(GoogleOAuthError, match="not authoritative"):
        verify_google_id_token("token")
