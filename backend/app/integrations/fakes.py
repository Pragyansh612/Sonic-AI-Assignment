"""Test doubles for SMTP/IMAP/LLM."""

from __future__ import annotations

from typing import Any

from app.integrations.protocols import InboundEmail, OutboundEmail


class FakeSmtp:
    def __init__(self) -> None:
        self.sent: list[OutboundEmail] = []

    async def send(self, email: OutboundEmail) -> str:
        self.sent.append(email)
        return email.message_id


class FakeImap:
    def __init__(self, messages: list[InboundEmail] | None = None) -> None:
        self.messages = list(messages or [])
        self.seen: list[str] = []

    async def fetch_unseen(self) -> list[InboundEmail]:
        return [m for m in self.messages if m.uid not in self.seen]

    async def mark_seen(self, uid: str) -> None:
        self.seen.append(uid)


class FakeLlm:
    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        *,
        raw_responses: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.raw_responses = list(raw_responses or [])
        self.error = error
        self.calls: list[dict[str, str]] = []

    async def complete_json(
        self, *, system: str, user: str, schema_hint: dict[str, Any]
    ) -> dict[str, Any]:
        from app.integrations.llm_client import parse_llm_json_content

        self.calls.append({"system": system, "user": user})
        if self.error:
            raise self.error
        if self.raw_responses:
            return parse_llm_json_content(
                self.raw_responses.pop(0), schema_hint=schema_hint
            )
        if not self.responses:
            raise RuntimeError("FakeLlm has no responses left")
        return self.responses.pop(0)
