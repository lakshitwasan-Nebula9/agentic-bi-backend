"""Rate limiter tests.

The suite-wide conftest disables rate limiting; each test here re-enables it
by flipping the settings singleton and restores everything in teardown.
Counters live in the docker Redis; every test uses a unique client IP
(X-Forwarded-For) so runs never collide with each other or with real keys.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.user import User

client = TestClient(app)


@pytest.fixture
def rate_limits():
    """Enable rate limiting with tight test limits; restore on teardown."""
    saved = (
        settings.RATE_LIMIT_ENABLED,
        settings.RATE_LIMIT_AUTH,
        settings.RATE_LIMIT_LLM,
        settings.RATE_LIMIT_DEFAULT,
        settings.REDIS_URL,
    )
    settings.RATE_LIMIT_ENABLED = True
    settings.RATE_LIMIT_AUTH = "3/minute"
    settings.RATE_LIMIT_DEFAULT = "5/minute"
    yield
    (
        settings.RATE_LIMIT_ENABLED,
        settings.RATE_LIMIT_AUTH,
        settings.RATE_LIMIT_LLM,
        settings.RATE_LIMIT_DEFAULT,
        settings.REDIS_URL,
    ) = saved


def _fake_ip() -> dict[str, str]:
    """Unique per-test client IP so fixed-window counters never collide."""
    octets = uuid.uuid4().bytes[:3]
    return {"X-Forwarded-For": f"10.{octets[0]}.{octets[1]}.{octets[2]}"}


def _signup() -> tuple[str, str]:
    email = f"ratelimit-{uuid.uuid4().hex}@example.com"
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123"},
        headers=_fake_ip(),
    )
    assert resp.status_code == 201
    return resp.json()["access_token"], email


def _cleanup_users(emails: list[str]) -> None:
    db = SessionLocal()
    try:
        db.query(User).filter(User.email.in_(emails)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


class TestAuthTier:
    def test_login_bursts_hit_429_with_retry_after(self, rate_limits):
        # Limit is 3/minute; fire a few extra so a fixed-window rollover
        # mid-burst can't flake the test — at least one burst must trip it.
        ip = _fake_ip()
        payload = {"email": f"nobody-{uuid.uuid4().hex}@example.com", "password": "wrong"}
        responses = [client.post("/api/v1/auth/login", json=payload, headers=ip) for _ in range(6)]
        throttled = [r for r in responses if r.status_code == 429]
        assert throttled, "burst of 6 logins against a 3/minute limit never returned 429"
        assert {r.status_code for r in responses} <= {401, 429}
        assert int(throttled[0].headers["Retry-After"]) >= 1
        assert "Rate limit exceeded" in throttled[0].json()["detail"]

    def test_auth_tier_keyed_per_ip(self, rate_limits):
        payload = {"email": f"nobody-{uuid.uuid4().hex}@example.com", "password": "wrong"}
        ip_a = _fake_ip()
        responses = [
            client.post("/api/v1/auth/login", json=payload, headers=ip_a) for _ in range(6)
        ]
        assert any(r.status_code == 429 for r in responses)
        # A different client IP still has its own budget.
        resp = client.post("/api/v1/auth/login", json=payload, headers=_fake_ip())
        assert resp.status_code == 401


class TestDefaultTier:
    def test_default_tier_keyed_per_user(self, rate_limits):
        token_a, email_a = _signup()
        token_b, email_b = _signup()
        try:
            ip = _fake_ip()
            responses = [
                client.get(
                    "/api/v1/dashboards",
                    headers={"Authorization": f"Bearer {token_a}", **ip},
                )
                for _ in range(8)  # limit is 5/minute; extras absorb window rollover
            ]
            assert any(r.status_code == 429 for r in responses)
            assert {r.status_code for r in responses} <= {200, 429}
            # Same IP, different user: keyed by user id, so B is unaffected.
            resp = client.get(
                "/api/v1/dashboards", headers={"Authorization": f"Bearer {token_b}", **ip}
            )
            assert resp.status_code == 200
        finally:
            _cleanup_users([email_a, email_b])


class TestExemptions:
    def test_health_and_sse_streams_never_throttled(self, rate_limits):
        ip = _fake_ip()
        for _ in range(10):
            assert client.get("/api/v1/health", headers=ip).status_code == 200
        # SSE stream is exempt: unauthenticated hits keep returning 401, never 429.
        for _ in range(10):
            assert client.get("/api/v1/dashboards/stream", headers=ip).status_code == 401


class TestKillSwitchAndFailOpen:
    def test_disabled_limiter_never_throttles(self, rate_limits):
        settings.RATE_LIMIT_ENABLED = False
        ip = _fake_ip()
        payload = {"email": f"nobody-{uuid.uuid4().hex}@example.com", "password": "wrong"}
        for _ in range(6):
            assert client.post("/api/v1/auth/login", json=payload, headers=ip).status_code == 401

    def test_fails_open_when_redis_is_down(self, rate_limits):
        settings.REDIS_URL = "redis://localhost:6399/0"  # nothing listens here
        ip = _fake_ip()
        payload = {"email": f"nobody-{uuid.uuid4().hex}@example.com", "password": "wrong"}
        for _ in range(6):
            resp = client.post("/api/v1/auth/login", json=payload, headers=ip)
            assert resp.status_code == 401  # limiter fails open, auth still answers
