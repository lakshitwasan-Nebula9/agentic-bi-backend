"""Redis-backed request rate limiting (Sprint 5 production hardening).

Fixed-window counters (INCR + EXPIRE) in Redis, three tiers:

- ``auth``    — unauthenticated brute-force targets (login/signup/google),
                keyed by client IP.
- ``llm``     — endpoints that trigger LLM calls (copilot messages, insight
                detection, KPI generation, report generation), keyed by user.
- ``default`` — every other API route, keyed by user (IP fallback).

Implemented as pure ASGI middleware so long-lived streaming responses pass
through untouched; SSE endpoints (paths ending in ``/stream``) are exempt
entirely, as are health/docs. Any Redis failure fails OPEN — rate limiting
must never become the outage it is meant to prevent.
"""

import asyncio
import logging
import re
import time
import weakref

import redis.asyncio as aioredis
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.auth_service import decode_access_token

logger = logging.getLogger(__name__)

_PREFIX = settings.API_V1_PREFIX

# Unauthenticated endpoints worth brute-forcing — strictest tier, keyed by IP.
_AUTH_PATHS = {
    f"{_PREFIX}/auth/login",
    f"{_PREFIX}/auth/signup",
    f"{_PREFIX}/auth/google",
}

# POST endpoints that fan out to Gemini/Claude — cost cap, keyed by user.
_LLM_PATTERNS = [
    re.compile(p)
    for p in (
        rf"^{_PREFIX}/copilot/sessions/[^/]+/messages$",
        rf"^{_PREFIX}/insights/detect$",
        rf"^{_PREFIX}/insights/kpi/[^/]+/detect$",
        rf"^{_PREFIX}/kpis/[^/]+/regen$",
        rf"^{_PREFIX}/kpis/[^/]+/recompute$",
        rf"^{_PREFIX}/datasets/[^/]+/kpis/generate$",
        rf"^{_PREFIX}/datasets/[^/]+/kpis/recompute$",
        rf"^{_PREFIX}/reports$",
        rf"^{_PREFIX}/reports/trigger/(weekly|monthly)$",
    )
]

_EXEMPT_PATHS = {"/", f"{_PREFIX}/health", "/docs", "/redoc", "/openapi.json"}

_RATE_RE = re.compile(r"^(\d+)/(second|minute|hour)$")
_WINDOW_SECONDS = {"second": 1, "minute": 60, "hour": 3600}

# Async clients cached per event loop (then URL): connections are bound to the
# loop they were created on, and TestClient runs each request on a fresh loop
# (production uvicorn has a single loop, so this stays a one-entry cache).
# Weak keys let dead test loops drop out instead of poisoning the cache.
_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, aioredis.Redis]] = (
    weakref.WeakKeyDictionary()
)


def _get_client() -> aioredis.Redis:
    loop = asyncio.get_running_loop()
    by_url = _clients.setdefault(loop, {})
    client = by_url.get(settings.REDIS_URL)
    if client is None:
        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        by_url[settings.REDIS_URL] = client
    return client


def _parse_rate(rate: str) -> tuple[int, int]:
    """'10/minute' → (10, 60). Falls back to a permissive limit on bad config."""
    match = _RATE_RE.match(rate.strip())
    if match is None:
        logger.warning("Invalid rate limit %r — falling back to 1000/minute", rate)
        return 1000, 60
    return int(match.group(1)), _WINDOW_SECONDS[match.group(2)]


def _header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


def _client_ip(scope: dict) -> str:
    # Behind a proxy/ALB the client addr is the proxy; prefer the first
    # X-Forwarded-For hop. (Trusting XFF is fine here — worst case an abuser
    # spoofing it just shards their own budget across fake keys per IP.)
    forwarded = _header(scope, b"x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


def _user_key(scope: dict) -> str | None:
    """User id from the bearer token (or SSE-style ?token=) — no DB hit."""
    token: str | None = None
    authorization = _header(scope, b"authorization")
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if token is None:
        return None
    try:
        return decode_access_token(token).get("sub")
    except ValueError:
        return None


def _resolve(scope: dict) -> tuple[str, str, str] | None:
    """Return (tier, rate, key) for this request, or None when exempt."""
    path: str = scope["path"].rstrip("/") or "/"
    method: str = scope["method"]

    if path in _EXEMPT_PATHS or path.endswith("/stream"):
        return None
    if not path.startswith(_PREFIX):
        return None

    if method == "POST" and path in _AUTH_PATHS:
        return "auth", settings.RATE_LIMIT_AUTH, _client_ip(scope)

    identity = _user_key(scope) or _client_ip(scope)
    if method == "POST" and any(p.match(path) for p in _LLM_PATTERNS):
        return "llm", settings.RATE_LIMIT_LLM, identity
    return "default", settings.RATE_LIMIT_DEFAULT, identity


async def _retry_after(tier: str, rate: str, key: str) -> int | None:
    """Seconds until the caller may retry, or None when under the limit.

    Fails open: any Redis error allows the request through with a warning.
    """
    limit, window = _parse_rate(rate)
    now = time.time()
    window_id = int(now // window)
    redis_key = f"ratelimit:{tier}:{key}:{window_id}"
    try:
        client = _get_client()
        async with client.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, window)
            count, _ = await pipe.execute()
    except Exception:  # noqa: BLE001 — never let the limiter take the API down
        logger.warning("Rate limiter Redis check failed — failing open", exc_info=True)
        return None
    if count <= limit:
        return None
    return max(1, int((window_id + 1) * window - now))


class RateLimitMiddleware:
    """Pure ASGI middleware — streaming responses pass through untouched."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not settings.RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return

        resolved = _resolve(scope)
        if resolved is None:
            await self.app(scope, receive, send)
            return

        retry_after = await _retry_after(*resolved)
        if retry_after is None:
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded. Try again in {retry_after} seconds."},
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)
