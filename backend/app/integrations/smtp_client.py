"""SMTP outbound mail (TLS/STARTTLS) with header sanitization."""

from __future__ import annotations

import smtplib
import uuid
from email.message import EmailMessage
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings, get_settings
from app.integrations.protocols import OutboundEmail
from app.clock import utc_now


def strip_crlf(value: str) -> str:
    return value.replace("\r", "").replace("\n", "").strip()


class SmtpMailer:
    def __init__(
        self,
        settings: Settings | None = None,
        db: AsyncIOMotorDatabase[Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db = db

    async def send(self, email: OutboundEmail) -> str:
        to_addr = strip_crlf(email.to_address)
        subject = strip_crlf(email.subject)
        message_id = strip_crlf(email.message_id) or f"<{uuid.uuid4().hex}@acmecorp.local>"
        if not message_id.startswith("<"):
            message_id = f"<{message_id}>"

        msg = EmailMessage()
        msg["From"] = (
            f"{strip_crlf(self.settings.email_from_name)} "
            f"<{strip_crlf(self.settings.smtp_user)}>"
        )
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Message-ID"] = message_id
        if email.in_reply_to:
            msg["In-Reply-To"] = strip_crlf(email.in_reply_to)
        if email.references:
            msg["References"] = " ".join(strip_crlf(r) for r in email.references)
        msg.set_content(email.body[: self.settings.max_email_body_chars])

        if self.settings.email_dry_run:
            if self.db is not None:
                await self.db.email_outbox.insert_one(
                    {
                        "message_id": message_id,
                        "to": to_addr,
                        "subject": subject,
                        "body": email.body,
                        "in_reply_to": email.in_reply_to,
                        "references": email.references,
                        "conversation_id": email.conversation_id,
                        "created_at": utc_now().isoformat(),
                    }
                )
            return message_id

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(self.settings.smtp_user, self.settings.smtp_password)
            smtp.send_message(msg)
        return message_id
