"""
Email Service

Sends HTML emails via Gmail SMTP (aiosmtplib). Renders Jinja2 templates
from app/templates/email/. All calls are best-effort — errors are logged
but never raised to callers.
"""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader

from app.core.config import settings

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "email"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)


def _render(template_name: str, context: dict) -> str:
    return _jinja_env.get_template(template_name).render(**context)


async def send_email(to: str, subject: str, html: str) -> bool:
    """Send a single HTML email. Returns True on success."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP not configured — skipping email to %s", to)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


async def send_weekly_report(to: str, report_data: dict) -> bool:
    html = _render("weekly_report.html", {"report": report_data})
    return await send_email(
        to, f"Weekly Business Report — {report_data.get('period_label', '')}", html
    )


async def send_monthly_report(to: str, report_data: dict) -> bool:
    html = _render("monthly_report.html", {"report": report_data})
    return await send_email(
        to, f"Monthly Executive Report — {report_data.get('period_label', '')}", html
    )


_ROLE_TEMPLATE = {
    "executive": "executive_report.html",
    "manager": "manager_report.html",
    "analyst": "analyst_report.html",
}

_PERIOD_SUBJECT = {
    "weekly": "Weekly BI Report",
    "monthly": "Monthly BI Report",
}


async def send_personalized_report(to: str, role: str, report_data: dict) -> bool:
    """Send a role-specific personalized report email."""
    template = _ROLE_TEMPLATE.get(role, "manager_report.html")
    period_type = report_data.get("period_type", "weekly")
    period_label = report_data.get("period_label", "")
    subject = f"{_PERIOD_SUBJECT.get(period_type, 'BI Report')} — {period_label}"
    html = _render(template, {"report": report_data})
    return await send_email(to, subject, html)
