"""Provider-agnostic OpenAI-compatible LLM client with JSON output."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings, get_settings


class LlmError(Exception):
    pass


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
        for _ in range(2):
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise LlmError("LLM JSON was not an object")
                return parsed
            except Exception as exc:  # noqa: BLE001 — retry then escalate
                last_err = exc
        raise LlmError(f"LLM failed: {last_err}")
