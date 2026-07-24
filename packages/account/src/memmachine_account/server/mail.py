"""SMTP email sending for verification/reset/lockout/email-change codes.

Send failures propagate rather than being swallowed (DESIGN.md §10): a
verification email that silently failed to send would strand the account
in a pending state with no way to recover except `resend-code`, which
would fail identically.
"""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from memmachine_account.server.config import SmtpSection


async def send_email(config: SmtpSection, to_address: str, subject: str, body: str) -> None:
    """Send a plaintext email via the configured SMTP server."""
    message = EmailMessage()
    message["From"] = config.from_address
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=config.host,
        port=config.port,
        username=config.username,
        password=config.password,
        use_tls=config.encryption == "ssl",
        start_tls=config.encryption == "starttls",
        timeout=config.timeout_seconds,
    )


def render_code_email(*, purpose: str, code: str, expiry_minutes: int) -> tuple[str, str]:
    """Render a (subject, body) pair for a verification/reset/lockout/change code."""
    subjects = {
        "signup_verification": "MemMachine account verification code",
        "password_reset": "MemMachine password reset code",
        "lockout_reset": "MemMachine account locked - unlock code",
        "email_change": "MemMachine email change verification code",
    }
    subject = subjects.get(purpose, "MemMachine verification code")
    body = (
        f"Your code is: {code}\n\n"
        f"This code expires in {expiry_minutes} minutes. "
        "If you did not request this, you can ignore this email."
    )
    return subject, body
