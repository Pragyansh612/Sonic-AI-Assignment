"""Regression tests for the pre-submission audit findings."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.integrations.fakes import FakeImap, FakeLlm, FakeSmtp
from app.integrations.protocols import InboundEmail
from app.services.email_templates import compose_customer_reply
from app.services.inbound_service import InboundService
from app.services.reply_validator import validate_reply_draft


def mail(mid, frm, subj, body, uid, *, irt=None, refs=None, headers=None):
    return InboundEmail(
        message_id=mid,
        from_address=frm,
        to_address="acc@test",
        subject=subj,
        body_text=body,
        in_reply_to=irt,
        references=refs or [],
        headers=headers or {},
        uid=uid,
    )


def llm_json(intent, *, conf=0.95, prose="Thanks for your message.", needs=False):
    return {
        "intent": intent,
        "confidence": conf,
        "needs_human": needs,
        "reason": "test",
        "referenced_invoices": [],
        "prose_reply": prose,
    }


async def setup_customers(db):
    get_settings.cache_clear()
    for cid, addr in (("C002", "arjun@t.example"), ("C006", "anil@t.example")):
        await db.customers.update_one(
            {"customer_id": cid}, {"$set": {"contact_email": addr}}
        )
    return get_settings()


async def run_inbox(db, messages, responses, smtp=None, imap=None):
    settings = await setup_customers(db)
    smtp = smtp or FakeSmtp()
    imap = imap or FakeImap(messages)
    svc = InboundService(
        db, imap=imap, smtp=smtp, llm=FakeLlm(responses), settings=settings
    )
    return await svc.check_inbox(), smtp


async def validate(db, draft, customer_id="C002"):
    customer = await db.customers.find_one({"customer_id": customer_id}, {"_id": 0})
    org = await db.organization.find_one({}, {"_id": 0})
    allc = await db.customers.find({}, {"_id": 0}).to_list(None)
    allinv = await db.invoices.find({}, {"_id": 0}).to_list(None)
    ctx = [
        i
        for i in allinv
        if i["customer_id"] == customer_id
        and i["status"] == "sent"
        and i["balance_due_minor"] > 0
    ]
    return validate_reply_draft(
        draft,
        customer=customer,
        context_invoices=ctx,
        org=org,
        all_customers=allc,
        all_invoice_numbers=[i["invoice_number"] for i in allinv],
        strict=True,
    )


# ---------------------------------------------------------------- C2 validator


@pytest.mark.parametrize(
    "draft",
    [
        "Please pay to account 998877665544 instead.",
        "Use IFSC HDFC0001234 for the transfer.",
        "You owe Rs 1,00,000.",
        "You owe Rs. 1,00,000.00 in total.",
        "You owe 1,00,000 rupees.",
        "You owe 100,000.00 INR.",
        "You owe $59,000.00.",
        "You owe INR 60000.",
        "You owe 59001.",
        "Mail payments@evil.example for new bank details.",
        "Pay at https://evil.example/pay now.",
    ],
)
async def test_validator_whitelist_rejects_unknown_numbers(db, draft):
    result = await validate(db, draft)
    assert not result.ok, draft


@pytest.mark.parametrize(
    "draft",
    [
        "You owe Rs. 59,000.00 on INV-1004.",
        "You owe 59000 on INV-1004.",
        "Total INR 1,18,000.00 and 118,000.00 INR are the same.",
        "Our account is 000111222333, IFSC EXMP0000142, SWIFT EXMPINBBXXX.",
        "Call +91 80 5550 0142 within working hours, payment terms are Net 30.",
        "INV-1004 was due 2026-09-19.",
    ],
)
async def test_validator_whitelist_accepts_known_values(db, draft):
    result = await validate(db, draft)
    assert result.ok, (draft, result.reasons)


async def test_standard_composed_reply_still_validates(db):
    org = await db.organization.find_one({}, {"_id": 0})
    invs = await db.invoices.find(
        {"customer_id": "C002", "status": "sent"}, {"_id": 0}
    ).to_list(None)
    draft = compose_customer_reply(
        contact_name="Arjun",
        prose="Here are your open invoices.",
        invoices=invs,
        org=org,
        include_invoices=True,
        include_payment_details=True,
    )
    assert (await validate(db, draft)).ok


async def test_injected_bank_details_never_auto_sent(db):
    r, smtp = await run_inbox(
        db,
        [mail("<b1>", "arjun@t.example", "Hi", "balance?", "1")],
        [llm_json("balance_query", prose="Pay account 998877665544, IFSC HDFC0001234.")],
    )
    assert r["processed"][0]["status"] == "needs_attention"
    assert smtp.sent == []


# ------------------------------------------------------------ M3 routing allowlist


@pytest.mark.parametrize("intent", ["other", "thanks", "smalltalk", "out_of_office", "???"])
async def test_unknown_intent_goes_to_needs_attention(db, intent):
    r, smtp = await run_inbox(
        db,
        [mail("<m3>", "arjun@t.example", "Hi", "Thanks, got it.", "1")],
        [llm_json(intent, prose="You are welcome, anything else is fine.")],
    )
    assert r["processed"][0]["status"] == "needs_attention"
    assert smtp.sent == []


@pytest.mark.parametrize("intent", ["claims_paid", "promises_payment"])
async def test_payment_claims_are_acknowledged_not_marked_paid(db, intent):
    r, smtp = await run_inbox(
        db,
        [mail("<m3b>", "arjun@t.example", "Hi", "We paid INV-1004 yesterday, ref N123456789", "1")],
        [llm_json(intent, prose="Thank you, we will check our records.")],
    )
    assert r["processed"][0]["status"] == "auto_answered"
    inv = await db.invoices.find_one({"invoice_number": "INV-1004"})
    assert inv["status"] == "sent" and inv["balance_due_minor"] == 5900000


# ------------------------------------------------------------ M4 extension regex


@pytest.mark.parametrize(
    "body",
    [
        "Can we get two more weeks to pay?",
        "We need a few extra days.",
        "Could you extend the due date?",
        "Please allow a grace period.",
        "Can we pay next month instead?",
        "Can we split this into instalments?",
        "We need 10 more days please",
        "Any chance of a later date for payment?",
    ],
)
async def test_extension_phrases_always_need_attention(db, body):
    r, smtp = await run_inbox(
        db,
        [mail("<m4>", "arjun@t.example", "Hi", body, "1")],
        [llm_json("balance_query")],
    )
    assert r["processed"][0]["status"] == "needs_attention"
    assert smtp.sent == []


# ------------------------------------------------------------ M5 other-company


@pytest.mark.parametrize(
    "body",
    [
        "What does Redwood owe you?",
        "what does REDWOOD clinics owe",
        "Is Nordlys paying on time?",
        "Please send the statement for Thornfield.",
    ],
)
async def test_single_token_other_company_needs_attention(db, body):
    r, smtp = await run_inbox(
        db,
        [mail("<m5>", "arjun@t.example", "Hi", body, "1")],
        [llm_json("balance_query")],
    )
    assert r["processed"][0]["status"] == "needs_attention"
    assert smtp.sent == []


@pytest.mark.parametrize(
    "body",
    [
        "Kestrel here: what is our balance?",
        "Kestrel Foods wants to know the amount pending, packaging and logistics costs included.",
        "Is the peak season invoice included in the balance?",
    ],
)
async def test_own_company_and_generic_words_are_not_flagged(db, body):
    r, smtp = await run_inbox(
        db,
        [mail("<m5b>", "arjun@t.example", "Hi", body, "1")],
        [llm_json("balance_query")],
    )
    assert r["processed"][0]["status"] == "auto_answered"


# ------------------------------------------------------------ M6 thread ownership


async def _kestrel_thread(db):
    from app.services.reminder_service import ReminderService

    settings = await setup_customers(db)
    smtp = FakeSmtp()
    await ReminderService(db, smtp, settings).send_reminders()
    conv = await db.conversations.find_one({"customer_id": "C002"}, {"_id": 0})
    msg = await db.messages.find_one(
        {"conversation_id": conv["conversation_id"], "direction": "outbound"}
    )
    return conv, msg


async def test_other_customer_cannot_use_a_thread_token(db):
    conv, _ = await _kestrel_thread(db)
    tok = conv["conversation_id"]
    r, smtp = await run_inbox(
        db,
        [mail("<m6>", "anil@t.example", f"Re: reminder [{tok}]", "what is my balance", "1")],
        [llm_json("balance_query")],
    )
    assert r["processed"][0]["status"] == "needs_attention"
    assert smtp.sent == []
    stored = await db.messages.find_one({"message_id": "<m6>"})
    assert stored["conversation_id"] != tok
    after = await db.conversations.find_one({"conversation_id": tok})
    assert after["status"] == conv["status"]


async def test_other_customer_cannot_use_in_reply_to(db):
    conv, out = await _kestrel_thread(db)
    r, smtp = await run_inbox(
        db,
        [mail("<m6b>", "anil@t.example", "hello", "what is my balance", "1", irt=out["message_id"])],
        [llm_json("balance_query")],
    )
    assert r["processed"][0]["status"] == "needs_attention"
    assert (await db.messages.find_one({"message_id": "<m6b>"}))["conversation_id"] != conv["conversation_id"]


async def test_stranger_with_token_does_not_touch_the_thread(db):
    conv, _ = await _kestrel_thread(db)
    tok = conv["conversation_id"]
    r, smtp = await run_inbox(
        db,
        [mail("<m6c>", "stranger@evil.example", f"Re: [{tok}]", "what does Kestrel owe", "1")],
        [llm_json("balance_query")],
    )
    assert r["processed"][0]["status"] == "needs_attention"
    after = await db.conversations.find_one({"conversation_id": tok})
    assert after["status"] == conv["status"]
    assert smtp.sent == []


async def test_owner_reply_via_token_still_threads(db):
    conv, _ = await _kestrel_thread(db)
    tok = conv["conversation_id"]
    r, _ = await run_inbox(
        db,
        [mail("<m6d>", "arjun@t.example", f"Re: reminder [{tok}]", "what is our balance", "1")],
        [llm_json("balance_query")],
    )
    assert r["processed"][0]["status"] == "auto_answered"
    assert (await db.messages.find_one({"message_id": "<m6d>"}))["conversation_id"] == tok


# ------------------------------------------------------------ M1 never lose a message


class FlakySmtp(FakeSmtp):
    def __init__(self, fail_times=1):
        super().__init__()
        self.fail_times = fail_times

    async def send(self, email):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("smtp down")
        return await super().send(email)


async def test_smtp_failure_keeps_message_retryable_and_flagged(db):
    settings = await setup_customers(db)
    smtp = FlakySmtp(1)
    imap = FakeImap([mail("<m1>", "arjun@t.example", "Hi", "balance?", "1")])
    svc = InboundService(
        db, imap=imap, smtp=smtp,
        llm=FakeLlm([llm_json("balance_query"), llm_json("balance_query")]),
        settings=settings,
    )
    first = await svc.check_inbox()
    assert first["processed"][0]["status"] == "error"
    assert imap.seen == []  # not marked seen
    conv = await db.conversations.find_one({"customer_id": "C002"})
    assert conv["status"] == "needs_attention"
    assert "smtp down" in conv["needs_attention_reason"]

    second = await svc.check_inbox()
    assert second["processed"][0]["status"] == "auto_answered"
    assert len(smtp.sent) == 1
    assert imap.seen == ["1"]
    third = await svc.check_inbox()
    assert third["processed"] == []  # now truly done


async def test_poison_message_does_not_block_the_batch(db):
    settings = await setup_customers(db)
    smtp = FlakySmtp(1)
    imap = FakeImap(
        [
            mail("<p1>", "arjun@t.example", "Hi", "balance?", "1"),
            mail("<p2>", "anil@t.example", "Hi", "balance?", "2"),
        ]
    )
    svc = InboundService(
        db, imap=imap, smtp=smtp,
        llm=FakeLlm([llm_json("balance_query"), llm_json("balance_query")]),
        settings=settings,
    )
    res = await svc.check_inbox()
    assert [p["status"] for p in res["processed"]] == ["error", "auto_answered"]
    assert imap.seen == ["2"]


# ------------------------------------------------------------ M2 BODY.PEEK


async def test_imap_fetch_does_not_set_seen_flag(monkeypatch):
    import imaplib

    from app.integrations import imap_client

    fetched: list[str] = []
    raw = b"From: a@b.example\r\nSubject: s\r\nMessage-ID: <x@y>\r\n\r\nhello"

    class FakeConn:
        def __init__(self, *a, **k): ...
        def login(self, *a): return ("OK", [])
        def select(self, *a, **k): return ("OK", [])
        def logout(self): ...
        def uid(self, cmd, *args):
            if cmd == "search":
                return ("OK", [b"7"])
            if cmd == "fetch":
                fetched.append(args[1])
                return ("OK", [(b"7 (BODY[] {1}", raw)])
            return ("OK", [])

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeConn)
    get_settings.cache_clear()
    settings = get_settings().model_copy(
        update={"email_dry_run": False, "imap_password": "x", "imap_user": "u"}
    )
    out = await imap_client.ImapMailer(settings).fetch_unseen()
    assert len(out) == 1
    assert fetched and "PEEK" in fetched[0].upper() and "RFC822" not in fetched[0].upper()


# ------------------------------------------------------------ M7 reminders vs needs_attention


async def test_reminder_does_not_reset_needs_attention(db):
    from datetime import timedelta

    from app.clock import utc_now
    from app.services.reminder_service import ReminderService

    settings = await setup_customers(db)
    await ReminderService(db, FakeSmtp(), settings).send_reminders()
    conv = await db.conversations.find_one({"customer_id": "C002"})
    await db.conversations.update_one(
        {"conversation_id": conv["conversation_id"]},
        {"$set": {
            "status": "needs_attention",
            "needs_attention_reason": "customer asked something odd",
            "last_reminder_at": (utc_now() - timedelta(days=10)).isoformat(),
        }},
    )
    res = await ReminderService(db, FakeSmtp(), settings).send_reminders()
    assert any(s["customer_id"] == "C002" for s in res["sent"])
    after = await db.conversations.find_one({"conversation_id": conv["conversation_id"]})
    assert after["status"] == "needs_attention"
    assert after["needs_attention_reason"] == "customer asked something odd"


# ------------------------------------------------------------ M9 auto-reply detection


@pytest.mark.parametrize(
    "headers,subject,sender,kind",
    [
        ({"Auto-submitted": "auto-replied"}, "Re: x", "a@b.example", "auto_reply"),
        ({"auto-submitted": "auto-generated"}, "Re: x", "a@b.example", "auto_reply"),
        ({"X-AUTOREPLY": "yes"}, "Re: x", "a@b.example", "auto_reply"),
        ({"precedence": "Bulk"}, "Re: x", "a@b.example", "auto_reply"),
        ({}, "Automatic reply: Payment reminder", "a@b.example", "auto_reply"),
        ({}, "Autoreply: away", "a@b.example", "auto_reply"),
        ({"content-type": "multipart/report; report-type=delivery-status"}, "x", "a@b.example", "bounce"),
        ({}, "Delivery Status Notification (Failure)", "Mailer-Daemon@googlemail.com", "bounce"),
    ],
)
def test_auto_reply_detection_is_case_insensitive(headers, subject, sender, kind):
    from app.services.safety_keywords import is_auto_reply_or_bounce

    assert is_auto_reply_or_bounce(subject=subject, from_address=sender, headers=headers) == (True, kind)


def test_normal_mail_is_not_flagged_as_auto():
    from app.services.safety_keywords import is_auto_reply_or_bounce

    assert is_auto_reply_or_bounce(
        subject="Re: Payment reminder", from_address="a@b.example",
        headers={"Auto-Submitted": "no"},
    ) == (False, None)


# ------------------------------------------------------------ M10 parser robustness


@pytest.mark.parametrize("value", ["NaN", "nan", "Infinity", "-Infinity", "1e30", "9" * 40])
def test_non_finite_or_huge_amounts_are_row_errors(value):
    from app.services.statement_parser import parse_statement_csv

    csv_text = (
        "txn_date,narration,reference,credit,debit,currency\n"
        f"2026-09-05,NEFT X,R1,{value},,INR\n"
        "2026-09-06,NEFT Y,R2,500,,INR\n"
    )
    res = parse_statement_csv(csv_text)
    assert len(res.errors) == 1 and res.errors[0].row_number == 1
    assert [t.credit_minor for t in res.transactions] == [50000]


# ------------------------------------------------------------ M8 human Send needs acknowledgement


async def _needs_attention_conv(db):
    r, _ = await run_inbox(
        db,
        [mail("<m8>", "arjun@t.example", "Hi", "Can we get two more weeks?", "1")],
        [llm_json("extension_request", needs=True, prose="We will check.")],
    )
    return (await db.conversations.find_one({"customer_id": "C002"}))["conversation_id"]


BAD_DRAFT = "Pay account 5555 now. We extend your due date to 2030-01-01."


async def test_human_send_blocked_when_validator_fails(client, db, admin_headers):
    cid = await _needs_attention_conv(db)
    res = await client.post(
        f"/api/v1/collections/needs-attention/{cid}/send",
        json={"draft": BAD_DRAFT}, headers=admin_headers,
    )
    assert res.status_code == 409
    body = res.json()["detail"]
    assert body["code"] == "validation_warnings" and body["warnings"]
    assert await db.email_outbox.count_documents({}) == 0
    assert (await db.conversations.find_one({"conversation_id": cid}))["status"] == "needs_attention"


async def test_human_send_allowed_with_acknowledgement(client, db, admin_headers):
    cid = await _needs_attention_conv(db)
    res = await client.post(
        f"/api/v1/collections/needs-attention/{cid}/send",
        json={"draft": BAD_DRAFT, "acknowledge_warnings": True}, headers=admin_headers,
    )
    assert res.status_code == 200 and res.json()["warnings"]
    assert await db.email_outbox.count_documents({}) == 1


async def test_clean_human_draft_sends_without_acknowledgement(client, db, admin_headers):
    cid = await _needs_attention_conv(db)
    res = await client.post(
        f"/api/v1/collections/needs-attention/{cid}/send",
        json={"draft": "Dear Arjun, we have noted your request and will revert shortly."},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text


# ------------------------------------------------------------ M12 reads need the admin token


@pytest.mark.parametrize(
    "path",
    ["/api/v1/organization", "/api/v1/customers", "/api/v1/customers/C002",
     "/api/v1/invoices", "/api/v1/invoices/INV-1004"],
)
async def test_data_reads_require_admin_token(client, admin_headers, path):
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers={"X-Admin-Token": "wrong"})).status_code == 401
    assert (await client.get(path, headers=admin_headers)).status_code == 200


async def test_health_stays_public(client):
    assert (await client.get("/api/v1/health")).status_code == 200


# ------------------------------------------------------------ minor: no chasing during dispute/legal


@pytest.mark.parametrize(
    "body,intent",
    [("We dispute this invoice, the amount is incorrect.", "dispute"),
     ("Our lawyer will contact you.", "legal")],
)
async def test_reminders_skip_customers_in_dispute_or_legal(db, body, intent):
    from app.services.reminder_service import ReminderService

    await run_inbox(
        db, [mail("<d1>", "arjun@t.example", "Hi", body, "1")],
        [llm_json(intent, needs=True)],
    )
    smtp = FakeSmtp()
    res = await ReminderService(db, smtp, get_settings()).send_reminders()
    assert all(s["customer_id"] != "C002" for s in res["sent"])
    assert {"customer_id": "C002", "reason": "dispute_or_legal"} in res["skipped"]
    assert all("Arjun" not in e.body for e in smtp.sent)
    assert any(s["customer_id"] == "C001" for s in res["sent"])  # others still chased


async def test_extension_request_does_not_stop_reminders(db):
    from app.services.reminder_service import ReminderService

    await run_inbox(
        db, [mail("<d2>", "arjun@t.example", "Hi", "Could we get more time?", "1")],
        [llm_json("extension_request", needs=True)],
    )
    res = await ReminderService(db, FakeSmtp(), get_settings()).send_reminders()
    assert any(s["customer_id"] == "C002" for s in res["sent"])


# ------------------------------------------------------------ follow-up 1: payment reference extraction


@pytest.mark.parametrize(
    "body,refs",
    [
        ("We paid INV-1004 yesterday, reference N123456789", ["N123456789"]),
        ("paid, ref: N123456789", ["N123456789"]),
        ("Paid via NEFT UTR 12345 today", ["12345"]),
        ("UTR-AB12CD34", ["AB12CD34"]),
        ("Reference no. 9988776655", ["9988776655"]),
        ("We have your reference and will pay", []),
        ("NEFT payment done for INV-1004", []),
    ],
)
def test_payment_reference_extraction(body, refs):
    from app.services.payment_email_evidence import extract_payment_claims

    assert extract_payment_claims(body)["references"] == refs


async def test_claim_email_stores_the_real_reference(db):
    await run_inbox(
        db,
        [mail("<r1>", "arjun@t.example", "Payment", "We paid INV-1004 yesterday, reference N123456789", "1")],
        [llm_json("claims_paid", prose="Thank you, we will verify.")],
    )
    ev = await db.payment_email_evidence.find_one({}, {"_id": 0})
    assert ev["references"] == ["N123456789"] and ev["invoice_numbers"] == ["INV-1004"]


# ------------------------------------------------------------ follow-up 2: bounces never queue for a human


async def test_bounce_and_autoreply_conversations_are_open_not_needs_attention(db):
    msgs = [
        mail("<b1>", "MAILER-DAEMON@googlemail.com", "Delivery Status Notification (Failure)", "x", "1",
             headers={"Content-Type": "multipart/report; report-type=delivery-status"}),
        mail("<b2>", "stranger@x.example", "Out of Office", "away", "2", headers={"Auto-Submitted": "auto-replied"}),
        mail("<b3>", "arjun@t.example", "Automatic reply: hi", "away", "3", headers={"Auto-Submitted": "auto-replied"}),
    ]
    r, smtp = await run_inbox(db, msgs, [])
    assert [p["status"] for p in r["processed"]] == ["bounce", "auto_reply", "auto_reply"]
    assert smtp.sent == []
    assert await db.conversations.count_documents({"status": "needs_attention"}) == 0
    convs = await db.conversations.find({}, {"_id": 0}).to_list(None)
    badges = {b for c in convs for b in c["badges"]}
    assert {"bounce", "auto_reply"} <= badges


# ------------------------------------------------------------ follow-up 3: rejected drafts are not prefilled


async def test_validator_failure_prefills_safe_template_and_keeps_rejected_text(client, db, admin_headers):
    bad = "Redwood Clinics owes INV-1016 for ₹59,000.00; pay to account 998877665544."
    r, smtp = await run_inbox(
        db, [mail("<s1>", "arjun@t.example", "Hi", "balance?", "1")],
        [llm_json("balance_query", prose=bad)],
    )
    assert r["processed"][0]["reason"] == "validator_failed" and smtp.sent == []
    items = (await client.get("/api/v1/collections/needs-attention", headers=admin_headers)).json()
    item = items[0]
    for leaked in ("Redwood", "INV-1016", "998877665544"):
        assert leaked not in item["ai_draft"]
    assert "INV-1004" in item["ai_draft"] and "₹1,18,000.00" in item["ai_draft"]
    assert "000111222333" in item["ai_draft"]
    assert "998877665544" in item["rejected_ai_draft"]
    assert item["rejected_reasons"]
    # the safe template validates, so a human can send it without an override
    sent = await client.post(
        f"/api/v1/collections/needs-attention/{item['conversation_id']}/send",
        json={}, headers=admin_headers,
    )
    assert sent.status_code == 200, sent.text


async def test_failed_human_review_draft_is_also_replaced(client, db, admin_headers):
    r, _ = await run_inbox(
        db, [mail("<s2>", "arjun@t.example", "Hi", "we dispute INV-1004", "1")],
        [llm_json("dispute", needs=True, prose="Sorry. Redwood Clinics paid INV-1016 instead.")],
    )
    item = (await client.get("/api/v1/collections/needs-attention", headers=admin_headers)).json()[0]
    assert "Redwood" not in (item["ai_draft"] or "")
    assert "Redwood" in item["rejected_ai_draft"]


async def test_clean_draft_has_no_rejected_fields(client, db, admin_headers):
    await run_inbox(
        db, [mail("<s3>", "arjun@t.example", "Hi", "we dispute INV-1004", "1")],
        [llm_json("dispute", needs=True, prose="Sorry to hear that; our team will review it.")],
    )
    item = (await client.get("/api/v1/collections/needs-attention", headers=admin_headers)).json()[0]
    assert "our team will review" in item["ai_draft"]
    assert not item.get("rejected_ai_draft") and not item.get("rejected_reasons")


# ------------------------------------------------------------ LLM 404 / 401 are explained, not swallowed


def _llm_with_status(monkeypatch, status, body=None):
    import httpx

    from app.integrations import llm_client

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body or {"error": {"message": "x"}})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        llm_client.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    get_settings.cache_clear()
    settings = get_settings().model_copy(update={"llm_api_key": "sk-secret-123"})
    return llm_client.OpenAICompatibleLlm(settings), calls


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (404, {"error": {"message": "models/foo is not found"}}, "LLM model not found: check LLM_MODEL"),
        (400, {"error": {"message": "The model `foo` does not exist"}}, "LLM model not found: check LLM_MODEL"),
        (401, {"error": {"message": "bad"}}, "LLM key rejected: check LLM_API_KEY"),
        (403, {"error": {"message": "denied"}}, "LLM key rejected: check LLM_API_KEY"),
        (400, {"error": {"message": "API key not valid. Please pass a valid API key."}}, "LLM key rejected: check LLM_API_KEY"),
    ],
)
async def test_llm_misconfiguration_gives_one_clear_line(monkeypatch, caplog, status, body, expected):
    from app.integrations.llm_client import LlmError

    llm, calls = _llm_with_status(monkeypatch, status, body)
    with caplog.at_level("ERROR", logger="app.llm"):
        with pytest.raises(LlmError) as exc:
            await llm.complete_json(system="s", user="u", schema_hint={"intent": ""})
    assert str(exc.value) == expected
    assert len(calls) == 1  # misconfiguration is not retried
    lines = [r.getMessage() for r in caplog.records if r.name == "app.llm"]
    assert lines == [expected]
    assert "sk-secret-123" not in caplog.text


async def test_transient_llm_errors_are_still_retried(monkeypatch):
    from app.integrations.llm_client import LlmError

    llm, calls = _llm_with_status(monkeypatch, 503)
    with pytest.raises(LlmError):
        await llm.complete_json(system="s", user="u", schema_hint={"intent": ""})
    assert len(calls) == 2


@pytest.mark.parametrize("status", [404, 401])
async def test_llm_misconfiguration_routes_email_to_needs_attention(db, monkeypatch, status):
    llm, _ = _llm_with_status(monkeypatch, status)
    settings = await setup_customers(db)
    smtp, imap = FakeSmtp(), FakeImap([mail("<l1>", "arjun@t.example", "Hi", "balance?", "1")])
    res = await InboundService(db, imap=imap, smtp=smtp, llm=llm, settings=settings).check_inbox()
    assert res["processed"][0]["status"] == "needs_attention"
    assert smtp.sent == []
    conv = await db.conversations.find_one({"customer_id": "C002"})
    assert conv["status"] == "needs_attention"
    want = "LLM model not found: check LLM_MODEL" if status == 404 else "LLM key rejected: check LLM_API_KEY"
    assert want in conv["needs_attention_reason"]
    assert "sk-secret-123" not in conv["needs_attention_reason"]
