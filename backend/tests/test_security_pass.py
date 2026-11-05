"""Phase 5a security checklist tests against the assignment brief."""

from __future__ import annotations

import io

import pytest
from httpx import AsyncClient

from app.integrations.smtp_client import strip_crlf
from app.security import reject_mongo_operators
from app.services.statement_parser import validate_upload_meta
from app.services.matching import config as match_cfg
from fastapi import HTTPException


def test_mongo_operator_injection_rejected_nested() -> None:
    with pytest.raises(HTTPException) as exc:
        reject_mongo_operators({"contact_email": {"$ne": None}})
    assert exc.value.status_code == 400


def test_header_injection_stripped_from_smtp_fields() -> None:
    evil = "victim@example.com\r\nBcc: attacker@evil.com"
    assert "\r" not in strip_crlf(evil)
    assert "\n" not in strip_crlf(evil)
    assert strip_crlf(evil) == "victim@example.comBcc: attacker@evil.com"


def test_upload_rejects_oversized_and_non_csv() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        validate_upload_meta(
            filename="big.csv",
            content_type="text/csv",
            size=match_cfg.MAX_UPLOAD_BYTES + 1,
        )
    with pytest.raises(ValueError, match="Only .csv"):
        validate_upload_meta(
            filename="payload.exe",
            content_type="application/octet-stream",
            size=100,
        )


@pytest.mark.asyncio
async def test_mutating_routes_require_admin_token(client: AsyncClient) -> None:
    paths = [
        ("POST", "/api/v1/collections/reminders/send"),
        ("POST", "/api/v1/collections/inbox/check"),
        ("POST", "/api/v1/admin/reset", {"confirm": True}),
    ]
    for method, path, *rest in paths:
        body = rest[0] if rest else None
        if method == "POST":
            r = await client.post(path, json=body)
        else:
            r = await client.request(method, path)
        assert r.status_code == 401, path


@pytest.mark.asyncio
async def test_cors_allows_only_configured_origin(client: AsyncClient) -> None:
    # Starlette echoes ACAO only when Origin matches allow_origins
    ok = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"

    bad = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert bad.headers.get("access-control-allow-origin") is None


@pytest.mark.asyncio
async def test_upload_rate_limit(
    client: AsyncClient, admin_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.rate_limit import upload_limiter

    # Tighten limiter for the test
    monkeypatch.setattr(upload_limiter, "max_calls", 2)
    monkeypatch.setattr(upload_limiter, "window", 60.0)
    upload_limiter._hits.clear()

    csv_bytes = (
        b"date,narration,reference,credit,debit,currency\n"
        b"2026-10-01,TEST,R1,100,,INR\n"
    )
    for i in range(2):
        r = await client.post(
            "/api/v1/reconciliation/upload",
            headers=admin_headers,
            files={"file": (f"t{i}.csv", io.BytesIO(csv_bytes), "text/csv")},
        )
        assert r.status_code in (200, 400), r.text  # parse may warn but accept
    blocked = await client.post(
        "/api/v1/reconciliation/upload",
        headers=admin_headers,
        files={"file": ("t3.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert blocked.status_code == 429
    upload_limiter._hits.clear()


@pytest.mark.asyncio
async def test_customer_isolation_llm_context_excludes_others(db) -> None:
    """LLM user prompt must not include other customers' invoice numbers."""
    from app.config import get_settings
    from app.integrations.fakes import FakeImap, FakeLlm, FakeSmtp
    from app.integrations.protocols import InboundEmail
    from app.services.inbound_service import InboundService

    get_settings.cache_clear()
    await db.customers.update_one(
        {"customer_id": "C002"},
        {"$set": {"contact_email": "arjun@test.example"}},
    )
    llm = FakeLlm(
        [
            {
                "intent": "balance_query",
                "confidence": 0.95,
                "needs_human": False,
                "reason": "ok",
                "referenced_invoices": [],
                "prose_reply": "Here.",
            }
        ]
    )
    imap = FakeImap(
        [
            InboundEmail(
                message_id="<iso@test>",
                from_address="arjun@test.example",
                to_address="accounts@test",
                subject="balance",
                body_text="What do I owe?",
                in_reply_to=None,
                references=[],
                headers={},
                uid="iso1",
            )
        ]
    )
    await InboundService(
        db,
        imap=imap,
        smtp=FakeSmtp(),
        llm=llm,
        settings=get_settings(),
    ).check_inbox()
    prompt = llm.calls[0]["user"]
    assert "INV-1004" in prompt or "INV-1005" in prompt
    assert "INV-1002" not in prompt  # Brightline
    assert "Brightline" not in prompt


def test_frontend_api_client_has_no_secret_imports() -> None:
    from pathlib import Path

    api = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"
    text = api.read_text(encoding="utf-8")
    assert "ADMIN_TOKEN" not in text or "Never imports ADMIN_TOKEN" in text
    assert "process.env" not in text
    assert "NEXT_PUBLIC" not in text


def test_no_dangerously_set_inner_html_in_frontend() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    offenders = []
    for path in root.rglob("*.tsx"):
        if "dangerouslySetInnerHTML" in path.read_text(encoding="utf-8"):
            offenders.append(str(path))
    assert offenders == []
