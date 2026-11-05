"""Bank reconciliation upload, matching, and human approval flow."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import HTTPException, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.clock import utc_now
from app.config import get_settings
from app.money import format_money, tds_amount_minor, tds_expected_payment_minor
from app.repositories.customer import CustomerRepository
from app.repositories.invoice import InvoiceRepository
from app.repositories.reconciliation import ReconciliationRepository
from app.services.matching import (
    CustomerInfo,
    OpenInvoice,
    match_credit,
)
from app.services.matching import config as match_cfg
from app.services.statement_parser import (
    parse_statement_csv,
    validate_upload_meta,
)

TdsMode = Literal["close_tds", "leave_open"]


class ReconciliationService:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db
        self._repo = ReconciliationRepository(db)
        self._invoices = InvoiceRepository(db)
        self._customers = CustomerRepository(db)

    async def upload(self, file: UploadFile) -> dict[str, Any]:
        raw = await file.read()
        filename = file.filename or "upload.csv"
        try:
            validate_upload_meta(
                filename=filename,
                content_type=file.content_type,
                size=len(raw),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        parsed = parse_statement_csv(raw, filename=filename)
        statement_id = f"stmt_{uuid.uuid4().hex[:12]}"
        now = utc_now().isoformat()

        invoice_docs = await self._invoices.list_all()
        customer_docs = await self._customers.list_all()
        open_models = [_to_open_invoice(d) for d in invoice_docs]
        customer_models = [_to_customer(d) for d in customer_docs]
        settings = get_settings()
        use_embeddings = settings.embeddings_enabled

        txn_docs: list[dict[str, Any]] = []
        suggestion_docs: list[dict[str, Any]] = []

        for row in parsed.transactions:
            transaction_id = f"txn_{uuid.uuid4().hex[:12]}"
            base = {
                "transaction_id": transaction_id,
                "statement_id": statement_id,
                **row.to_dict(),
                "status": "debit_skipped" if row.is_debit else "pending_match",
            }
            txn_docs.append(base)

            if row.is_debit or not row.is_credit or row.credit_minor is None:
                suggestion_docs.append(
                    {
                        "suggestion_id": f"sug_{uuid.uuid4().hex[:12]}",
                        "statement_id": statement_id,
                        "transaction_id": transaction_id,
                        "row_number": row.row_number,
                        "suggestion_type": "none",
                        "invoice_numbers": [],
                        "confidence": 0.0,
                        "reason": "Not a receipt (debit)",
                        "evidence": {"skipped": "debit"},
                        "alternatives": [],
                        "band": "none",
                        "status": "skipped",
                    }
                )
                continue

            result = match_credit(
                narration=row.narration,
                payment_minor=row.credit_minor,
                currency=row.currency,
                txn_date=row.txn_date,
                invoices=open_models,
                customers=customer_models,
                use_embeddings=use_embeddings,
            )
            suggestion_docs.append(
                {
                    "suggestion_id": f"sug_{uuid.uuid4().hex[:12]}",
                    "statement_id": statement_id,
                    "transaction_id": transaction_id,
                    "row_number": row.row_number,
                    "suggestion_type": result.suggestion_type.value,
                    "invoice_numbers": result.invoice_numbers,
                    "confidence": result.confidence,
                    "reason": result.reason,
                    "evidence": result.evidence,
                    "alternatives": result.alternatives,
                    "band": result.band,
                    "status": "pending",
                    "manual_choice": False,
                    "customer_mismatch": False,
                    "mismatch_warning": None,
                }
            )

        statement_doc = {
            "statement_id": statement_id,
            "filename": filename,
            "uploaded_at": now,
            "row_count": len(parsed.transactions),
            "error_count": len(parsed.errors),
            "parse_errors": [e.to_dict() for e in parsed.errors],
        }
        await self._repo.insert_statement(statement_doc)
        await self._repo.insert_transactions(txn_docs)
        await self._repo.insert_suggestions(suggestion_docs)
        await self._repo.insert_audit(
            {
                "action": "statement_upload",
                "statement_id": statement_id,
                "filename": filename,
                "created_at": now,
            }
        )

        return {
            "statement_id": statement_id,
            "filename": filename,
            "row_count": len(parsed.transactions),
            "error_count": len(parsed.errors),
            "parse_errors": [e.to_dict() for e in parsed.errors],
            "suggestion_count": len(
                [s for s in suggestion_docs if s["status"] == "pending"]
            ),
        }

    async def list_statements(self) -> list[dict[str, Any]]:
        return await self._repo.list_statements()

    async def get_statement_detail(self, statement_id: str) -> dict[str, Any]:
        stmt = await self._repo.get_statement(statement_id)
        if stmt is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found")
        txns = await self._repo.list_transactions(statement_id)
        suggestions = await self._repo.list_suggestions(statement_id)
        sug_by_txn = {s["transaction_id"]: s for s in suggestions}
        enriched = []
        for t in txns:
            sug = sug_by_txn.get(t["transaction_id"])
            enriched.append({**t, "suggestion": sug})
        return {
            **stmt,
            "transactions": enriched,
            "suggestions": suggestions,
        }

    async def list_open_invoices(self) -> list[dict[str, Any]]:
        docs = await self._repo.list_open_invoices()
        out = []
        for d in docs:
            currency = d["currency"]
            out.append(
                {
                    "invoice_number": d["invoice_number"],
                    "customer_id": d["customer_id"],
                    "customer_name": d["customer_name"],
                    "currency": currency,
                    "due_date": d["due_date"],
                    "outstanding": {
                        "minor": d["balance_due_minor"],
                        "currency": currency,
                        "formatted": format_money(d["balance_due_minor"], currency),
                    },
                    "subtotal_minor": d["subtotal_minor"],
                    "total_minor": d["total_minor"],
                    "tds_expected_payment_minor": tds_expected_payment_minor(
                        total_minor=d["total_minor"],
                        subtotal_minor=d["subtotal_minor"],
                        currency=currency,
                    ),
                }
            )
        return out

    async def reject(self, suggestion_id: str) -> dict[str, Any]:
        doc = await self._repo.reject_suggestion(suggestion_id)
        if doc is None:
            existing = await self._repo.get_suggestion(suggestion_id)
            if existing is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Suggestion not found")
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Suggestion is {existing.get('status')}, cannot reject",
            )
        await self._repo.insert_audit(
            {
                "action": "suggestion_reject",
                "suggestion_id": suggestion_id,
                "created_at": utc_now().isoformat(),
            }
        )
        return doc

    async def choose(
        self, suggestion_id: str, invoice_numbers: list[str]
    ) -> dict[str, Any]:
        if not invoice_numbers:
            raise HTTPException(400, "invoice_numbers required")
        sug = await self._repo.get_suggestion(suggestion_id)
        if sug is None:
            raise HTTPException(404, "Suggestion not found")
        if sug.get("status") not in {"pending", "chosen"}:
            raise HTTPException(409, f"Suggestion is {sug.get('status')}")

        txn = await self._db.bank_transactions.find_one(
            {"transaction_id": sug["transaction_id"]}, {"_id": 0}
        )
        if txn is None:
            raise HTTPException(404, "Transaction not found")

        invoices = []
        for num in invoice_numbers:
            inv = await self._repo.get_invoice(num)
            if inv is None:
                raise HTTPException(400, f"Invoice {num} not found")
            if inv["status"] != "sent" or inv["balance_due_minor"] <= 0:
                raise HTTPException(400, f"Invoice {num} is not open")
            invoices.append(inv)

        warning = None
        mismatch = False
        currencies = {i["currency"] for i in invoices}
        if txn["currency"] not in currencies or len(currencies) > 1:
            raise HTTPException(
                400,
                "Chosen invoice currency must match the payment currency "
                f"({txn['currency']})",
            )

        # Optional: detect payer mismatch using stored evidence customer
        # Compare chosen customer vs best alternative payer customer_id if any
        customers = {i["customer_id"] for i in invoices}
        if len(customers) > 1:
            warning = "Selected invoices belong to multiple customers"
            mismatch = True

        updated = await self._repo.update_suggestion_choice(
            suggestion_id,
            invoice_numbers,
            warning=warning,
            mismatch=mismatch,
        )
        if updated is None:
            raise HTTPException(409, "Could not update suggestion")
        await self._repo.insert_audit(
            {
                "action": "suggestion_choose",
                "suggestion_id": suggestion_id,
                "invoice_numbers": invoice_numbers,
                "created_at": utc_now().isoformat(),
            }
        )
        return updated

    async def approve(
        self,
        suggestion_id: str,
        *,
        invoice_numbers: list[str] | None = None,
        tds_mode: TdsMode | None = None,
    ) -> dict[str, Any]:
        # Idempotent: already approved
        existing = await self._repo.get_suggestion(suggestion_id)
        if existing is None:
            raise HTTPException(404, "Suggestion not found")
        if existing.get("status") == "approved":
            raise HTTPException(409, "Suggestion already approved")
        if existing.get("status") in {"rejected", "skipped", "failed"}:
            raise HTTPException(
                409, f"Suggestion is {existing.get('status')}, cannot approve"
            )

        claimed = await self._repo.claim_suggestion_for_approve(suggestion_id)
        if claimed is None:
            # Race: another approve in flight or status changed
            again = await self._repo.get_suggestion(suggestion_id)
            if again and again.get("status") == "approved":
                raise HTTPException(409, "Suggestion already approved")
            raise HTTPException(409, "Suggestion is not pending")

        txn_id = claimed["transaction_id"]
        prior = await self._repo.find_applied_payment_for_txn(txn_id)
        if prior is not None:
            await self._repo.mark_suggestion(suggestion_id, "failed", error="txn_already_applied")
            raise HTTPException(
                409, "This bank transaction was already applied to invoices"
            )

        txn = await self._db.bank_transactions.find_one(
            {"transaction_id": txn_id}, {"_id": 0}
        )
        if txn is None or not txn.get("is_credit") or txn.get("credit_minor") is None:
            await self._repo.mark_suggestion(suggestion_id, "failed", error="not_credit")
            raise HTTPException(400, "Transaction is not an approvable credit")

        numbers = invoice_numbers or list(claimed.get("invoice_numbers") or [])
        if not numbers:
            await self._repo.mark_suggestion(suggestion_id, "pending")
            raise HTTPException(400, "No invoices to apply")

        try:
            result = await self._apply_payment(
                txn=txn,
                invoice_numbers=numbers,
                tds_mode=tds_mode,
                suggestion_id=suggestion_id,
            )
        except HTTPException:
            await self._repo.mark_suggestion(suggestion_id, "pending")
            raise
        except Exception as exc:
            await self._repo.mark_suggestion(
                suggestion_id, "failed", error=str(exc)
            )
            raise

        await self._repo.mark_suggestion(
            suggestion_id,
            "approved",
            invoice_numbers=numbers,
            approved_at=utc_now().isoformat(),
            payment_id=result["payment_id"],
        )
        await self._db.bank_transactions.update_one(
            {"transaction_id": txn_id},
            {"$set": {"status": "applied", "payment_id": result["payment_id"]}},
        )
        await self._repo.insert_audit(
            {
                "action": "suggestion_approve",
                "suggestion_id": suggestion_id,
                "payment_id": result["payment_id"],
                "invoice_numbers": numbers,
                "tds_mode": tds_mode,
                "created_at": utc_now().isoformat(),
            }
        )
        return result

    async def _apply_payment(
        self,
        *,
        txn: dict[str, Any],
        invoice_numbers: list[str],
        tds_mode: TdsMode | None,
        suggestion_id: str,
    ) -> dict[str, Any]:
        payment_minor = int(txn["credit_minor"])
        currency = txn["currency"]

        invoices: list[dict[str, Any]] = []
        for num in invoice_numbers:
            inv = await self._repo.get_invoice(num)
            if inv is None:
                raise HTTPException(400, f"Invoice {num} not found")
            if inv["currency"] != currency:
                raise HTTPException(
                    400,
                    f"Currency mismatch: payment {currency} vs invoice "
                    f"{num} {inv['currency']}",
                )
            if inv["status"] != "sent" or inv["balance_due_minor"] <= 0:
                raise HTTPException(400, f"Invoice {num} is not open")
            invoices.append(inv)

        # Multi: payment must equal sum of outstandings (or TDS closes)
        if len(invoices) > 1:
            return await self._apply_multi(
                txn=txn,
                invoices=invoices,
                payment_minor=payment_minor,
                tds_mode=tds_mode,
                suggestion_id=suggestion_id,
            )

        inv = invoices[0]
        outstanding = int(inv["balance_due_minor"])
        paid_so_far = int(inv["amount_paid_minor"])
        tds_so_far = int(inv.get("tds_written_off_minor", 0))

        if payment_minor > outstanding:
            raise HTTPException(
                400,
                "Overpayment is not auto-applied; reduce selection or reject. "
                f"Payment {format_money(payment_minor, currency)} > outstanding "
                f"{format_money(outstanding, currency)}",
            )

        tds_delta = 0
        apply_amount = payment_minor
        close = False

        if payment_minor < outstanding:
            shortfall = outstanding - payment_minor
            expected_tds = tds_amount_minor(
                subtotal_minor=int(inv["subtotal_minor"]),
                currency=currency,
            )
            tds_ok = (
                currency == "INR"
                and abs(shortfall - expected_tds) <= match_cfg.TDS_TOLERANCE_MINOR
            )
            if tds_mode is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "tds_choice_required",
                        "message": "Partial payment requires tds_mode",
                        "outstanding_minor": outstanding,
                        "payment_minor": payment_minor,
                        "shortfall_minor": shortfall,
                        "tds_close_allowed": tds_ok,
                        "expected_tds_minor": expected_tds if currency == "INR" else None,
                    },
                )
            if tds_mode == "close_tds":
                if not tds_ok:
                    raise HTTPException(
                        400,
                        "Close invoice (TDS deducted) is only allowed when the "
                        "shortfall equals 10% of subtotal (INR) within tolerance",
                    )
                tds_delta = shortfall
                close = True
            elif tds_mode == "leave_open":
                close = False
            else:
                raise HTTPException(400, "Invalid tds_mode")

        new_paid = paid_so_far + apply_amount
        new_balance = outstanding - apply_amount - tds_delta
        if new_balance < 0:
            raise HTTPException(400, "Computed balance would be negative")
        if close or new_balance == 0:
            new_status = "paid"
            new_balance = 0
        else:
            new_status = "sent"

        snapshots = [
            {
                "invoice_number": inv["invoice_number"],
                "amount_paid_minor": paid_so_far,
                "balance_due_minor": outstanding,
                "status": inv["status"],
                "tds_written_off_minor": tds_so_far,
            }
        ]

        updated = await self._repo.apply_invoice_payment(
            invoice_number=inv["invoice_number"],
            expected_balance=outstanding,
            expected_paid=paid_so_far,
            new_paid=new_paid,
            new_balance=new_balance,
            new_status=new_status,
            tds_written_off_delta=tds_delta,
        )
        if updated is None:
            raise HTTPException(
                409, "Invoice changed concurrently; refresh and retry"
            )

        payment_id = f"pay_{uuid.uuid4().hex[:12]}"
        payment_doc = {
            "payment_id": payment_id,
            "bank_transaction_id": txn["transaction_id"],
            "suggestion_id": suggestion_id,
            "invoice_numbers": [inv["invoice_number"]],
            "allocations": [
                {
                    "invoice_number": inv["invoice_number"],
                    "applied_minor": apply_amount,
                    "tds_written_off_minor": tds_delta,
                }
            ],
            "amount_minor": payment_minor,
            "currency": currency,
            "tds_mode": tds_mode,
            "status": "applied",
            "created_at": utc_now().isoformat(),
        }
        try:
            await self._repo.insert_payment(payment_doc)
        except Exception:
            # rollback invoice
            snap = snapshots[0]
            await self._repo.restore_invoice(**snap)
            raise

        return {
            "payment_id": payment_id,
            "invoice_numbers": [inv["invoice_number"]],
            "allocations": payment_doc["allocations"],
            "invoices": [
                {
                    "invoice_number": inv["invoice_number"],
                    "status": new_status,
                    "balance_due_minor": new_balance,
                    "amount_paid_minor": new_paid,
                    "tds_written_off_minor": tds_so_far + tds_delta,
                }
            ],
        }

    async def _apply_multi(
        self,
        *,
        txn: dict[str, Any],
        invoices: list[dict[str, Any]],
        payment_minor: int,
        tds_mode: TdsMode | None,
        suggestion_id: str,
    ) -> dict[str, Any]:
        currency = txn["currency"]
        outstanding_sum = sum(int(i["balance_due_minor"]) for i in invoices)
        tds_sum = 0
        for inv in invoices:
            tds_sum += tds_amount_minor(
                subtotal_minor=int(inv["subtotal_minor"]),
                currency=currency,
            )
        expected_tds_payment = outstanding_sum - tds_sum

        use_tds = False
        if payment_minor == outstanding_sum:
            use_tds = False
        elif (
            currency == "INR"
            and abs(payment_minor - expected_tds_payment)
            <= match_cfg.TDS_TOLERANCE_MINOR
        ):
            use_tds = True
            if tds_mode is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "tds_choice_required",
                        "message": "Multi-invoice TDS settlement requires tds_mode=close_tds",
                        "tds_close_allowed": True,
                    },
                )
            if tds_mode != "close_tds":
                raise HTTPException(
                    400,
                    "For a multi-invoice TDS settlement use tds_mode=close_tds",
                )
        else:
            raise HTTPException(
                400,
                "Multi-invoice approval requires payment to equal the sum of "
                "outstandings (or their TDS-adjusted totals)",
            )

        snapshots = []
        allocations = []
        updated_views = []
        try:
            for inv in invoices:
                outstanding = int(inv["balance_due_minor"])
                paid_so_far = int(inv["amount_paid_minor"])
                tds_so_far = int(inv.get("tds_written_off_minor", 0))
                snapshots.append(
                    {
                        "invoice_number": inv["invoice_number"],
                        "amount_paid_minor": paid_so_far,
                        "balance_due_minor": outstanding,
                        "status": inv["status"],
                        "tds_written_off_minor": tds_so_far,
                    }
                )
                if use_tds:
                    tds_delta = tds_amount_minor(
                        subtotal_minor=int(inv["subtotal_minor"]),
                        currency=currency,
                    )
                    apply_amount = outstanding - tds_delta
                else:
                    tds_delta = 0
                    apply_amount = outstanding

                new_paid = paid_so_far + apply_amount
                updated = await self._repo.apply_invoice_payment(
                    invoice_number=inv["invoice_number"],
                    expected_balance=outstanding,
                    expected_paid=paid_so_far,
                    new_paid=new_paid,
                    new_balance=0,
                    new_status="paid",
                    tds_written_off_delta=tds_delta,
                )
                if updated is None:
                    raise HTTPException(
                        409, f"Invoice {inv['invoice_number']} changed concurrently"
                    )
                allocations.append(
                    {
                        "invoice_number": inv["invoice_number"],
                        "applied_minor": apply_amount,
                        "tds_written_off_minor": tds_delta,
                    }
                )
                updated_views.append(
                    {
                        "invoice_number": inv["invoice_number"],
                        "status": "paid",
                        "balance_due_minor": 0,
                        "amount_paid_minor": new_paid,
                        "tds_written_off_minor": tds_so_far + tds_delta,
                    }
                )
        except Exception:
            for snap in snapshots:
                await self._repo.restore_invoice(**snap)
            raise

        payment_id = f"pay_{uuid.uuid4().hex[:12]}"
        payment_doc = {
            "payment_id": payment_id,
            "bank_transaction_id": txn["transaction_id"],
            "suggestion_id": suggestion_id,
            "invoice_numbers": [i["invoice_number"] for i in invoices],
            "allocations": allocations,
            "amount_minor": payment_minor,
            "currency": currency,
            "tds_mode": tds_mode,
            "status": "applied",
            "created_at": utc_now().isoformat(),
        }
        try:
            await self._repo.insert_payment(payment_doc)
        except Exception:
            for snap in snapshots:
                await self._repo.restore_invoice(**snap)
            raise

        return {
            "payment_id": payment_id,
            "invoice_numbers": payment_doc["invoice_numbers"],
            "allocations": allocations,
            "invoices": updated_views,
        }


def _to_open_invoice(doc: dict[str, Any]) -> OpenInvoice:
    return OpenInvoice(
        invoice_number=doc["invoice_number"],
        customer_id=doc["customer_id"],
        customer_name=doc["customer_name"],
        currency=doc["currency"],
        invoice_date=doc["invoice_date"],
        due_date=doc["due_date"],
        outstanding_minor=int(doc["balance_due_minor"]),
        total_minor=int(doc["total_minor"]),
        subtotal_minor=int(doc["subtotal_minor"]),
        status=doc["status"],
    )


def _to_customer(doc: dict[str, Any]) -> CustomerInfo:
    return CustomerInfo(
        customer_id=doc["customer_id"],
        name=doc["name"],
        contact_name=doc["contact_name"],
        currency=doc["currency"],
    )
