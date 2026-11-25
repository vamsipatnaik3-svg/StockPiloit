
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import quote

from app.core.config import settings


class EmailDeliveryNotConfigured(Exception):
    """Raised when SMTP settings are incomplete."""


def send_password_reset_email(
    recipient_email: str,
    raw_token: str,
) -> None:
    """
    Send a password reset email.

    The raw token is included only in the email link.
    It is never logged or returned by this service.
    """

    required_settings = (
        settings.smtp_host,
        settings.smtp_from_email,
    )

    if not all(required_settings):
        raise EmailDeliveryNotConfigured(
            "SMTP host and sender email must be configured."
        )

    if bool(settings.smtp_username) != bool(settings.smtp_password):
        raise EmailDeliveryNotConfigured(
            "SMTP username and password must both be configured."
        )

    reset_url = (
        f"{settings.frontend_origin.rstrip('/')}"
        f"/reset-password?token={quote(raw_token, safe='')}"
    )

    message = EmailMessage()
    message["Subject"] = "Reset your Tavuno password"
    message["From"] = settings.smtp_from_email
    message["To"] = recipient_email

    message.set_content(
        f"""Hello,

We received a request to reset your Tavuno password.

Use the link below to choose a new password:

{reset_url}

This link expires in 30 minutes and can only be used once.

If you did not request this password reset, you can safely ignore
this email.

Tavuno Support
"""
    )

    message.add_alternative(
        f"""
        <html>
          <body>
            <h2>Reset your Tavuno password</h2>
            <p>
              We received a request to reset your Tavuno password.
            </p>
            <p>
              <a href="{reset_url}">Reset my password</a>
            </p>
            <p>
              This link expires in 30 minutes and can only be used once.
            </p>
            <p>
              If you did not request this, you can safely ignore this email.
            </p>
            <p>Tavuno Support</p>
          </body>
        </html>
        """,
        subtype="html",
    )

    context = ssl.create_default_context()

    with smtplib.SMTP(
        settings.smtp_host,
        settings.smtp_port,
        timeout=settings.smtp_timeout,
    ) as smtp:
        smtp.ehlo()

        if settings.smtp_use_tls:
            smtp.starttls(context=context)
            smtp.ehlo()

        if settings.smtp_username and settings.smtp_password:
            smtp.login(
                settings.smtp_username,
                settings.smtp_password,
            )

        smtp.send_message(message)
