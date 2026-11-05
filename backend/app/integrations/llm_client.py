"""Provider-agnostic OpenAI-compatible LLM client with tolerant JSON output."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings, get_settings


class LlmError(Exception):
    pass


class LlmReplyPayload(BaseModel):
    """Validated shape returned by the collections agent LLM."""

    model_config = ConfigDict(extra="ignore")

    intent: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human: bool = False
    reason: str = ""
    referenced_invoices: list[str] = Field(default_factory=list)
    prose_reply: str = ""


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def extract_json_object(text: str) -> str:
    """Strip code fences / prose and return the first JSON object substring."""
    raw = (text or "").strip()
    if not raw:
        raise LlmError("Empty LLM content")

    fence = _FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()

    if raw.startswith("{") and raw.endswith("}"):
        return raw

    match = _OBJECT_RE.search(raw)
    if not match:
        raise LlmError("No JSON object found in LLM content")
    return match.group(0)


def parse_llm_json_content(
    content: str, *, schema_hint: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Tolerant parse: fences, surrounding prose, then pydantic validation."""
    snippet = extract_json_object(content)
    try:
        parsed = json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise LlmError(f"Invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LlmError("LLM JSON was not an object")

    # Merge schema defaults for optional keys when present in hint
    if schema_hint:
        for key, default in schema_hint.items():
            parsed.setdefault(key, default)

    try:
        validated = LlmReplyPayload.model_validate(parsed)
    except ValidationError as exc:
        raise LlmError(f"LLM JSON failed schema validation: {exc}") from exc
    return validated.model_dump()


class OpenAICompatibleLlm:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def complete_json(
        self, *, system: str, user: str, schema_hint: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.settings.llm_api_key:
            raise LlmError("LLM_API_KEY is not configured")

        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": user
                    + "\n\nRespond with JSON only matching keys: "
                    + ", ".join(schema_hint.keys()),
                },
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        last_err: Exception | None = None
        # One network/parse attempt + one retry
        for _ in range(2):
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return parse_llm_json_content(content, schema_hint=schema_hint)
            except Exception as exc:  # noqa: BLE001 — retry then escalate
                last_err = exc
        raise LlmError(f"LLM failed: {last_err}")
