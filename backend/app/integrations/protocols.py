from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class OutboundEmail:
    to_address: str
    subject: str
    body: str
    message_id: str
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    conversation_id: str | None = None


@dataclass
class InboundEmail:
    message_id: str
    from_address: str
    to_address: str
    subject: str
    body_text: str
    in_reply_to: str | None
    references: list[str]
    headers: dict[str, str]
    uid: str | None = None


class SmtpClient(Protocol):
    async def send(self, email: OutboundEmail) -> str:
        """Send and return the Message-ID used."""
        ...


class ImapClient(Protocol):
    async def fetch_unseen(self) -> list[InboundEmail]:
        ...

    async def mark_seen(self, uid: str) -> None:
        ...


class LlmClient(Protocol):
    async def complete_json(
        self, *, system: str, user: str, schema_hint: dict[str, Any]
    ) -> dict[str, Any]:
        ...
