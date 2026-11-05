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
