"""IMAP inbound mail over SSL."""

from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header, make_header
from email.message import Message
from typing import Any

from app.config import Settings, get_settings
from app.integrations.protocols import InboundEmail
from app.services.email_sanitize import strip_quoted_reply


class ImapMailer:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _connect(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port)
        client.login(self.settings.imap_user, self.settings.imap_password)
        client.select("INBOX")
        return client

    async def fetch_unseen(self) -> list[InboundEmail]:
        if self.settings.email_dry_run and not self.settings.imap_password:
            return []
        client = self._connect()
        try:
            typ, data = client.uid("search", None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                return []
            uids = data[0].split()
            results: list[InboundEmail] = []
            for uid in uids:
                typ, msg_data = client.uid("fetch", uid, "(BODY.PEEK[])")  # PEEK keeps the message unseen until processed
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                parsed = email.message_from_bytes(raw)
                results.append(self._to_inbound(parsed, uid.decode()))
            return results
        finally:
            try:
                client.logout()
            except Exception:
                pass

    async def mark_seen(self, uid: str) -> None:
        if self.settings.email_dry_run and not self.settings.imap_password:
            return
        client = self._connect()
        try:
            client.uid("store", uid, "+FLAGS", "(\\Seen)")
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def _to_inbound(self, msg: Message, uid: str) -> InboundEmail:
        headers = {k: str(v) for k, v in msg.items()}
        subject = _decode_header_value(msg.get("Subject", ""))
        from_addr = _extract_address(msg.get("From", ""))
        to_addr = _extract_address(msg.get("To", ""))
        message_id = (msg.get("Message-ID") or "").strip() or f"missing-{uid}"
        in_reply_to = (msg.get("In-Reply-To") or "").strip() or None
        references = _split_refs(msg.get("References", ""))
        body = _extract_text(msg)
        body = strip_quoted_reply(body)
        body = body[: get_settings().max_email_body_chars]
        return InboundEmail(
            message_id=message_id,
            from_address=from_addr,
            to_address=to_addr,
            subject=subject,
            body_text=body,
            in_reply_to=in_reply_to,
            references=references,
            headers=headers,
            uid=uid,
        )


def _decode_header_value(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_address(value: str) -> str:
    m = re.search(r"([\w.+-]+@[\w.-]+)", value or "")
    return (m.group(1) if m else value).strip().lower()


def _split_refs(value: str) -> list[str]:
    return [p for p in re.split(r"\s+", value or "") if p]


def _extract_text(msg: Message) -> str:
    if msg.is_multipart():
        plain = None
        html = None
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ctype == "text/plain" and plain is None:
                plain = text
            elif ctype == "text/html" and html is None:
                html = text
        if plain:
            return plain
        if html:
            return re.sub(r"<[^>]+>", " ", html)
        return ""
    try:
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:
        return str(msg.get_payload() or "")

