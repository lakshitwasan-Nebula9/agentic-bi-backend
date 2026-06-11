from dataclasses import dataclass

from google.auth.transport import requests
from google.oauth2 import id_token

from app.core.config import settings


class GoogleOAuthError(ValueError):
    pass


@dataclass(frozen=True)
class GoogleUserInfo:
    subject: str
    email: str


def verify_google_id_token(token: str) -> GoogleUserInfo:
    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise GoogleOAuthError("Google OAuth is not configured")

    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            requests.Request(),
            settings.GOOGLE_OAUTH_CLIENT_ID,
        )
    except ValueError as exc:
        raise GoogleOAuthError("Invalid Google ID token") from exc

    if idinfo.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise GoogleOAuthError("Invalid Google token issuer")

    if not idinfo.get("email_verified"):
        raise GoogleOAuthError("Google email is not verified")

    subject = idinfo.get("sub")
    email = idinfo.get("email")
    if not subject or not email:
        raise GoogleOAuthError("Google token is missing required identity claims")

    hosted_domain = idinfo.get("hd")
    allowed_domain = settings.GOOGLE_OAUTH_ALLOWED_DOMAIN
    if allowed_domain and hosted_domain != allowed_domain:
        raise GoogleOAuthError("Google account domain is not allowed")

    if not allowed_domain and not email.endswith("@gmail.com") and not hosted_domain:
        raise GoogleOAuthError("Google is not authoritative for this email")

    return GoogleUserInfo(subject=subject, email=email)
