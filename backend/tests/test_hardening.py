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
