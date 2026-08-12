"""Optional email delivery for password resets. Free/dev mode prints the link."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger("squadforge.mail")


def send_password_reset_email(*, to_email: str, reset_url: str, display_name: str) -> bool:
    """Send reset mail when SMTP is configured. Returns True if sent."""
    host = (settings.smtp_host or "").strip()
    if not host:
        log.info("Password reset for %s → %s", to_email, reset_url)
        return False

    msg = EmailMessage()
    msg["Subject"] = f"{settings.app_name} password reset"
    msg["From"] = settings.smtp_from or settings.smtp_user or "noreply@squadforge.local"
    msg["To"] = to_email
    msg.set_content(
        f"Hi {display_name},\n\n"
        f"Reset your {settings.app_name} password using this link (expires in 2 hours):\n\n"
        f"{reset_url}\n\n"
        f"If you didn't ask for this, you can ignore the email.\n"
    )

    port = settings.smtp_port or 587
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)
    return True
