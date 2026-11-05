"""
Score candidates and apply hard decision gates.

Weighted formula (before caps), max ≈ 100:
  confidence ≈
      invoice_ref_points          # WEIGHT_INVOICE_REF or WEIGHT_WEAK_INVOICE_REF
    + WEIGHT_PAYER_SIM * (payer_sim/100)
    + WEIGHT_AMOUNT * amount_factor
    + WEIGHT_DATE * date_factor

Hard gates (evaluated first / can force none):
  - currency mismatch → reject candidate
  - payment date < invoice_date → reject candidate
  - no invoice hint AND payer_sim < threshold → no match overall
  - amount equal but payer unknown → no match (never amount-alone)
  - confidence < REVIEW_MIN → present as none (best guess in details)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from app.money import format_money
from app.services.matching import config as cfg
from app.services.matching.aliases import build_aliases
from app.services.matching.candidates import (
    classify_amount,
    invoices_by_number,
    multi_invoice_sets,
    open_invoices_only,
)
from app.services.matching.normalize import normalize_narration
from app.services.matching.similarity import best_alias_similarity
from app.services.matching.types import (
    AmountMatchKind,
    CustomerInfo,
    Evidence,
    InvoiceHintStrength,
    MatchCandidate,
    MatchResult,
    NormalizedNarration,
    OpenInvoice,
    SuggestionType,
)

_AMOUNT_FACTOR = {
    AmountMatchKind.EXACT_OUTSTANDING: cfg.AMOUNT_EXACT_OUTSTANDING,
    AmountMatchKind.EXACT_TOTAL: cfg.AMOUNT_EXACT_TOTAL,
    AmountMatchKind.TDS_ADJUSTED: cfg.AMOUNT_TDS_ADJUSTED,
    AmountMatchKind.PARTIAL: cfg.AMOUNT_PARTIAL,
    AmountMatchKind.OVERPAY: cfg.AMOUNT_OVERPAY,
    AmountMatchKind.MISMATCH: cfg.AMOUNT_MISMATCH,
    AmountMatchKind.MULTI_EXACT: cfg.AMOUNT_EXACT_OUTSTANDING,
    AmountMatchKind.MULTI_TDS: cfg.AMOUNT_TDS_ADJUSTED,
}


def match_credit(
    *,
    narration: str,
    payment_minor: int,
    currency: str,
    txn_date: str,
    invoices: Sequence[OpenInvoice],
    customers: Sequence[CustomerInfo],
    use_embeddings: bool = False,
) -> MatchResult:
    """Pure matching entrypoint for one credit row."""
    open_invs = open_invoices_only(invoices)
    known_numbers = [i.invoice_number for i in invoices]
    norm = normalize_narration(narration, known_invoice_numbers=known_numbers)
    customer_map = {c.customer_id: c for c in customers}

    # Best payer match across all customers
    best_payer_sim = 0.0
    best_payer_customer = ""
    best_payer_alias = ""
    best_payer_source = ""
    for cust in customers:
        aliases = build_aliases(cust)
        score, alias, source = best_alias_similarity(
            norm.payer_candidate, aliases, use_embeddings=use_embeddings
        )
        if score > best_payer_sim:
            best_payer_sim = score
            best_payer_customer = cust.customer_id
            best_payer_alias = alias
            best_payer_source = source

    payer_clears_gate = _payer_gate(best_payer_sim, best_payer_source)
    has_hint = len(norm.invoice_hints) > 0

    # Soft amount/narrative hints for the reviewer — never raise confidence.
    soft_alts = _soft_alternatives(
        payment_minor=payment_minor,
        currency=currency,
        open_invs=open_invs,
        norm=norm,
        customer_map=customer_map,
    )

    # Hard gate: unknown payer + no invoice hint
    if not has_hint and not payer_clears_gate:
        return _none_result(
            reason="Payer not recognized",
            evidence=Evidence(
                payer_sim=best_payer_sim,
                payer_source=best_payer_source,
                payer_alias=best_payer_alias,
                hard_reject_reason="no_hint_and_payer_below_threshold",
                components={"payer_sim": best_payer_sim},
            ),
            alternatives=soft_alts,
        )

    candidates = _build_candidates(
        norm=norm,
        payment_minor=payment_minor,
        currency=currency,
        txn_date=txn_date,
        open_invs=open_invs,
        customer_map=customer_map,
        best_payer_sim=best_payer_sim,
        best_payer_customer=best_payer_customer,
        best_payer_alias=best_payer_alias,
        best_payer_source=best_payer_source,
        payer_clears_gate=payer_clears_gate,
        use_embeddings=use_embeddings,
    )

    if not candidates:
        return _none_result(
            reason=_fallback_reason(norm, best_payer_sim, best_payer_alias),
            evidence=Evidence(
                payer_sim=best_payer_sim,
                payer_source=best_payer_source,
                payer_alias=best_payer_alias,
                hard_reject_reason="no_viable_candidate",
                components={"payer_sim": best_payer_sim},
            ),
            alternatives=soft_alts,
        )

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    top = candidates[0]
    alternatives = [
        {
            "invoice_numbers": list(c.invoice_numbers),
            "confidence": round(c.confidence, 1),
            "reason": c.reason,
            "customer_id": c.customer_id,
        }
        for c in candidates[:3]
    ]

    # Band / gate: below REVIEW_MIN → none
    if top.confidence < cfg.REVIEW_MIN:
        return MatchResult(
            suggestion_type=SuggestionType.NONE,
            invoice_numbers=[],
            confidence=0.0,
            reason="No confident match",
            evidence={
                **top.evidence.to_dict(),
                "best_guess": {
                    "invoice_numbers": list(top.invoice_numbers),
                    "confidence": round(top.confidence, 1),
                    "reason": top.reason,
                },
            },
            alternatives=alternatives,
            band="none",
        )

    band = "high" if top.confidence >= cfg.HIGH_CONFIDENCE else "review"
    return MatchResult(
        suggestion_type=top.suggestion_type,
        invoice_numbers=list(top.invoice_numbers),
        confidence=top.confidence,
        reason=top.reason,
        evidence=top.evidence.to_dict(),
        alternatives=alternatives,
        band=band,
    )


def _payer_gate(sim: float, source: str) -> bool:
    if source == "contact":
        return sim >= cfg.CONTACT_PAYER_SIM_THRESHOLD
    return sim >= cfg.PAYER_SIM_THRESHOLD


def _build_candidates(
    *,
    norm: NormalizedNarration,
    payment_minor: int,
    currency: str,
    txn_date: str,
    open_invs: list[OpenInvoice],
    customer_map: dict[str, CustomerInfo],
    best_payer_sim: float,
    best_payer_customer: str,
    best_payer_alias: str,
    best_payer_source: str,
    payer_clears_gate: bool,
    use_embeddings: bool,
) -> list[MatchCandidate]:
    by_num = invoices_by_number(open_invs)
    out: list[MatchCandidate] = []

    # Hints that point at non-open invoices (paid/draft/unknown) — caution flag
    dead_hint_customers: set[str] = set()
    known_all = {i.invoice_number.upper(): i for i in open_invs}
    # We only have open_invs here; dead detection uses hint numbers absent from open set
    open_numbers = set(known_all)
    for hint in norm.invoice_hints:
        if hint.invoice_number.upper() not in open_numbers:
            # Try to infer customer from hint text is unavailable; mark globally
            dead_hint_customers.add("*")

    # --- Hint-driven singletons ---
    for hint in norm.invoice_hints:
        inv = by_num.get(hint.invoice_number.upper())
        if inv is None:
            continue
        if inv.currency != currency:
            continue
        cand = _score_singleton(
            inv=inv,
            payment_minor=payment_minor,
            txn_date=txn_date,
            norm=norm,
            hint_strength=hint.strength,
            customer_map=customer_map,
            global_payer_sim=best_payer_sim,
            global_payer_customer=best_payer_customer,
            global_payer_alias=best_payer_alias,
            global_payer_source=best_payer_source,
            use_embeddings=use_embeddings,
        )
        if cand:
            out.append(cand)

    # --- Payer-driven singletons (only if payer gate cleared) ---
    if payer_clears_gate and best_payer_customer:
        for inv in open_invs:
            if inv.customer_id != best_payer_customer:
                continue
            if inv.currency != currency:
                continue
            # Skip if already added via hint
            if any(
                c.invoice_numbers == (inv.invoice_number,) for c in out
            ):
                continue
            cand = _score_singleton(
                inv=inv,
                payment_minor=payment_minor,
                txn_date=txn_date,
                norm=norm,
                hint_strength=None,
                customer_map=customer_map,
                global_payer_sim=best_payer_sim,
                global_payer_customer=best_payer_customer,
                global_payer_alias=best_payer_alias,
                global_payer_source=best_payer_source,
                use_embeddings=use_embeddings,
            )
            if not cand:
                continue
            # If narration references a paid/unknown invoice, do not auto-suggest
            # PARTIAL payments onto other open invoices of the same customer.
            if (
                "*" in dead_hint_customers
                and cand.evidence.amount_kind == AmountMatchKind.PARTIAL.value
            ):
                continue
            out.append(cand)

    # Ambiguity handling among equal-amount same-customer singletons
    out = _apply_uniqueness(out, open_invs, norm)

    # --- Multi-invoice sets (payer gate required) ---
    if payer_clears_gate:
        for combo, kind in multi_invoice_sets(
            open_invs, payment_minor, currency=currency
        ):
            # Only propose when all invoices belong to payer's customer
            cust_ids = {i.customer_id for i in combo}
            if len(cust_ids) != 1:
                continue
            customer_id = next(iter(cust_ids))
            if customer_id != best_payer_customer:
                continue
            # Date check: payment must be >= max invoice_date? >= each
            if any(
                not _date_ok(txn_date, inv.invoice_date) for inv in combo
            ):
                continue
            numbers = tuple(sorted(i.invoice_number for i in combo))
            evidence = Evidence(
                invoice_ref_score=0.0,
                payer_sim=best_payer_sim,
                payer_source=best_payer_source,
                payer_alias=best_payer_alias,
                amount_kind=kind.value,
                amount_score=cfg.WEIGHT_AMOUNT
                * _AMOUNT_FACTOR[kind],
                date_score=cfg.WEIGHT_DATE * 0.7,
                currency_ok=True,
            )
            conf = (
                cfg.WEIGHT_PAYER_SIM * (best_payer_sim / 100.0)
                + evidence.amount_score
                + evidence.date_score
            )
            if best_payer_sim >= cfg.STRONG_PAYER_FOR_SYNERGY:
                conf += cfg.PAYER_AMOUNT_SYNERGY
            # Bonus if any invoice number appears in narration
            hinted = {
                h.invoice_number.upper() for h in norm.invoice_hints
            }
            if any(n.upper() in hinted for n in numbers):
                conf += cfg.WEIGHT_WEAK_INVOICE_REF
                evidence.invoice_ref_score = cfg.WEIGHT_WEAK_INVOICE_REF

            evidence.components = {
                "payer": cfg.WEIGHT_PAYER_SIM * (best_payer_sim / 100.0),
                "amount": evidence.amount_score,
                "date": evidence.date_score,
                "invoice_ref": evidence.invoice_ref_score,
                "synergy": cfg.PAYER_AMOUNT_SYNERGY
                if best_payer_sim >= cfg.STRONG_PAYER_FOR_SYNERGY
                else 0.0,
            }
            cust_name = customer_map[customer_id].name if customer_id in customer_map else customer_id
            short = _short_name(cust_name)
            joined = " + ".join(numbers)
            if kind == AmountMatchKind.MULTI_TDS:
                reason = (
                    f"Payer matches {short} ({best_payer_sim:.0f}), "
                    f"amount equals {joined} less TDS"
                )
            else:
                reason = (
                    f"Payer matches {short} ({best_payer_sim:.0f}), "
                    f"amount equals {joined}"
                )
            out.append(
                MatchCandidate(
                    invoice_numbers=numbers,
                    customer_id=customer_id,
                    confidence=min(99.0, conf),
                    reason=reason,
                    evidence=evidence,
                    suggestion_type=SuggestionType.MULTI,
                )
            )

    # Drop zero / rejected
    return [c for c in out if c.confidence > 0 and not c.evidence.hard_reject_reason]


def _score_singleton(
    *,
    inv: OpenInvoice,
    payment_minor: int,
    txn_date: str,
    norm: NormalizedNarration,
    hint_strength: InvoiceHintStrength | None,
    customer_map: dict[str, CustomerInfo],
    global_payer_sim: float,
    global_payer_customer: str,
    global_payer_alias: str,
    global_payer_source: str,
    use_embeddings: bool,
) -> MatchCandidate | None:
    evidence = Evidence()

    if not _date_ok(txn_date, inv.invoice_date):
        evidence.hard_reject_reason = "payment_before_invoice_date"
        evidence.currency_ok = True
        return MatchCandidate(
            invoice_numbers=(inv.invoice_number,),
            customer_id=inv.customer_id,
            confidence=0.0,
            reason="Payment date before invoice date",
            evidence=evidence,
            suggestion_type=SuggestionType.SINGLE,
        )

    # Per-invoice payer score (prefer this customer's aliases)
    cust = customer_map.get(inv.customer_id)
    if cust:
        aliases = build_aliases(cust)
        payer_sim, payer_alias, payer_source = best_alias_similarity(
            norm.payer_candidate, aliases, use_embeddings=use_embeddings
        )
    else:
        payer_sim, payer_alias, payer_source = 0.0, "", ""

    # If this invoice's customer scores poorly but global best is elsewhere,
    # keep the per-invoice score for honesty.
    evidence.payer_sim = payer_sim
    evidence.payer_alias = payer_alias
    evidence.payer_source = payer_source

    amount_kind = classify_amount(payment_minor, inv)
    evidence.amount_kind = amount_kind.value
    amount_factor = _AMOUNT_FACTOR[amount_kind]
    evidence.amount_score = cfg.WEIGHT_AMOUNT * amount_factor

    # Invoice ref points
    ref_points = 0.0
    if hint_strength == InvoiceHintStrength.STRONG:
        ref_points = cfg.WEIGHT_INVOICE_REF
    elif hint_strength == InvoiceHintStrength.WEAK:
        ref_points = cfg.WEIGHT_WEAK_INVOICE_REF
    evidence.invoice_ref_score = ref_points

    # Date soft score
    date_factor = _date_factor(txn_date, inv.due_date, inv.invoice_date)
    evidence.date_score = cfg.WEIGHT_DATE * date_factor

    payer_points = cfg.WEIGHT_PAYER_SIM * (payer_sim / 100.0)
    synergy = 0.0
    if amount_kind in {
        AmountMatchKind.EXACT_OUTSTANDING,
        AmountMatchKind.EXACT_TOTAL,
        AmountMatchKind.TDS_ADJUSTED,
        AmountMatchKind.PARTIAL,
    } and _payer_gate(payer_sim, payer_source):
        # Full synergy for strong payer; half when payer clears the gate but is typo'd/weaker.
        synergy = (
            cfg.PAYER_AMOUNT_SYNERGY
            if payer_sim >= cfg.STRONG_PAYER_FOR_SYNERGY
            else cfg.PAYER_AMOUNT_SYNERGY * 0.5
        )
    confidence = (
        ref_points
        + payer_points
        + evidence.amount_score
        + evidence.date_score
        + synergy
    )

    # Conflict: hint points to invoice whose customer ≠ best payer customer
    conflict = False
    if hint_strength is not None and global_payer_customer:
        if (
            global_payer_sim >= cfg.PAYER_SIM_THRESHOLD
            and inv.customer_id != global_payer_customer
        ):
            conflict = True
            confidence = min(confidence, cfg.HINT_CUSTOMER_CONFLICT_CAP)
            evidence.uniqueness_note = (
                f"conflict: invoice {inv.invoice_number} customer "
                f"{inv.customer_id} vs payer customer {global_payer_customer}"
            )

    # Overpayments are never auto-suggested (human can Choose manually).
    if amount_kind == AmountMatchKind.OVERPAY:
        return None

    # Without hint, require amount to be at least partial + payer gate
    if hint_strength is None:
        if amount_kind == AmountMatchKind.MISMATCH:
            return None
        # Never suggest on amount alone: payer must clear gate for this customer
        if not _payer_gate(payer_sim, payer_source):
            return None

    # Weak RE/bare-number hints without a payer match must not auto-suggest
    # (stops UTR-embedded suffixes from matching on amount alone).
    if hint_strength == InvoiceHintStrength.WEAK and not _payer_gate(
        payer_sim, payer_source
    ):
        confidence = min(confidence, cfg.REVIEW_MIN - 1.0)

    evidence.components = {
        "invoice_ref": ref_points,
        "payer": payer_points,
        "amount": evidence.amount_score,
        "date": evidence.date_score,
        "synergy": synergy,
    }

    reason = _singleton_reason(
        inv=inv,
        payer_sim=payer_sim,
        payer_alias=payer_alias,
        amount_kind=amount_kind,
        hint_strength=hint_strength,
        conflict=conflict,
        customer_map=customer_map,
    )

    return MatchCandidate(
        invoice_numbers=(inv.invoice_number,),
        customer_id=inv.customer_id,
        confidence=min(99.5, max(0.0, confidence)),
        reason=reason,
        evidence=evidence,
        suggestion_type=SuggestionType.SINGLE,
    )


def _apply_uniqueness(
    candidates: list[MatchCandidate],
    open_invs: list[OpenInvoice],
    norm: NormalizedNarration,
) -> list[MatchCandidate]:
    """
    When several same-customer invoices share the same outstanding and there
    is no unique invoice hint, prefer earliest due date and cap confidence.
    """
    by_num = invoices_by_number(open_invs)
    hinted = {h.invoice_number.upper() for h in norm.invoice_hints}

    # Group singleton candidates by (customer, outstanding)
    singles = [c for c in candidates if len(c.invoice_numbers) == 1]
    multi = [c for c in candidates if len(c.invoice_numbers) != 1]

    groups: dict[tuple[str, int], list[MatchCandidate]] = {}
    for c in singles:
        inv = by_num.get(c.invoice_numbers[0].upper())
        if not inv:
            continue
        key = (inv.customer_id, inv.outstanding_minor)
        groups.setdefault(key, []).append(c)

    resolved: list[MatchCandidate] = []
    seen_nums: set[str] = set()
    for _key, group in groups.items():
        if len(group) <= 1:
            for c in group:
                resolved.append(c)
                seen_nums.add(c.invoice_numbers[0])
            continue

        # Prefer one with explicit hint
        hinted_group = [
            c for c in group if c.invoice_numbers[0].upper() in hinted
        ]
        if len(hinted_group) == 1:
            resolved.append(hinted_group[0])
            seen_nums.add(hinted_group[0].invoice_numbers[0])
            continue

        # Earliest due date
        def due_key(c: MatchCandidate) -> str:
            inv = by_num[c.invoice_numbers[0].upper()]
            return inv.due_date

        group_sorted = sorted(group, key=due_key)
        winner = group_sorted[0]
        rivals = [c.invoice_numbers[0] for c in group_sorted]
        winner.confidence = min(winner.confidence, cfg.AMBIGUOUS_CONFIDENCE_CAP)
        winner.evidence.uniqueness_note = (
            f"ambiguous between {'/'.join(rivals)}; earliest due chosen"
        )
        winner.reason = (
            f"{winner.reason} (ambiguous between {'/'.join(rivals)}, "
            f"earliest due chosen)"
        )
        resolved.append(winner)
        seen_nums.add(winner.invoice_numbers[0])

    # Keep any singles not grouped (shouldn't happen) + multi
    for c in singles:
        if c.invoice_numbers[0] not in seen_nums and c not in resolved:
            # already handled
            pass
    return resolved + multi


def _singleton_reason(
    *,
    inv: OpenInvoice,
    payer_sim: float,
    payer_alias: str,
    amount_kind: AmountMatchKind,
    hint_strength: InvoiceHintStrength | None,
    conflict: bool,
    customer_map: dict[str, CustomerInfo],
) -> str:
    short = _short_name(
        customer_map[inv.customer_id].name
        if inv.customer_id in customer_map
        else inv.customer_name
    )
    parts: list[str] = []
    if hint_strength == InvoiceHintStrength.STRONG:
        parts.append("Invoice number found")
    elif hint_strength == InvoiceHintStrength.WEAK:
        parts.append("Weak invoice reference found")

    if payer_sim >= cfg.PAYER_SIM_THRESHOLD:
        parts.append(f"Payer matches {short} ({payer_sim:.0f})")
    elif payer_alias:
        parts.append(f"Weak payer signal {short} ({payer_sim:.0f})")

    if amount_kind == AmountMatchKind.EXACT_OUTSTANDING:
        parts.append("exact amount" if hint_strength else f"amount equals {inv.invoice_number} outstanding")
    elif amount_kind == AmountMatchKind.EXACT_TOTAL:
        parts.append("amount equals invoice total")
    elif amount_kind == AmountMatchKind.TDS_ADJUSTED:
        parts.append(
            f"amount equals {inv.invoice_number} total less 10% TDS "
            f"({format_money(payment_amount_for_tds_display(inv), inv.currency)})"
        )
    elif amount_kind == AmountMatchKind.PARTIAL:
        parts.append("partial payment vs outstanding")
    elif amount_kind == AmountMatchKind.OVERPAY:
        parts.append("overpayment vs outstanding")

    if conflict:
        parts.append("payer/invoice customer conflict")

    if not parts:
        return "Possible match"
    # Prefer classic phrasing when strong hint + exact
    if (
        hint_strength == InvoiceHintStrength.STRONG
        and amount_kind == AmountMatchKind.EXACT_OUTSTANDING
        and not conflict
    ):
        return "Invoice number found, exact amount"
    return ", ".join(parts)


def payment_amount_for_tds_display(inv: OpenInvoice) -> int:
    from app.money import tds_expected_payment_minor

    return (
        tds_expected_payment_minor(
            total_minor=inv.total_minor,
            subtotal_minor=inv.subtotal_minor,
            currency=inv.currency,
        )
        or 0
    )


def _short_name(name: str) -> str:
    tokens = [
        t
        for t in name.replace(",", " ").split()
        if t.upper()
        not in {
            "PVT",
            "LTD",
            "LIMITED",
            "PRIVATE",
            "LLC",
            "INC",
            "GMBH",
            "LLP",
            "CO",
            "CORP",
        }
    ]
    return " ".join(tokens[:3]) if tokens else name


def _date_ok(txn_date: str, invoice_date: str) -> bool:
    try:
        return _parse_date(txn_date) >= _parse_date(invoice_date)
    except ValueError:
        return True


def _date_factor(txn_date: str, due_date: str, invoice_date: str) -> float:
    try:
        txn = _parse_date(txn_date)
        due = _parse_date(due_date)
        inv = _parse_date(invoice_date)
    except ValueError:
        return 0.4
    if txn < inv:
        return 0.0
    delta = abs((txn - due).days)
    if delta <= cfg.DATE_DUE_PROXIMITY_DAYS:
        return 1.0
    if delta <= 45:
        return 0.7
    return 0.4


def _parse_date(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def _soft_alternatives(
    *,
    payment_minor: int,
    currency: str,
    open_invs: list[OpenInvoice],
    norm: NormalizedNarration,
    customer_map: dict[str, CustomerInfo],
) -> list[dict]:
    """
    Top-3 reviewer hints for no-match rows (amount / weak narrative overlap).

    Ranked for display only — never becomes a suggestion and never raises confidence.
    """
    payer_tokens = set(norm.cleaned_tokens)
    ranked: list[tuple[float, dict]] = []
    for inv in open_invs:
        if inv.currency != currency:
            continue
        kind = classify_amount(payment_minor, inv)
        if kind in {
            AmountMatchKind.MISMATCH,
            AmountMatchKind.OVERPAY,
        }:
            continue
        rank = {
            AmountMatchKind.EXACT_OUTSTANDING: 50.0,
            AmountMatchKind.EXACT_TOTAL: 45.0,
            AmountMatchKind.TDS_ADJUSTED: 48.0,
            AmountMatchKind.PARTIAL: 25.0,
        }.get(kind, 10.0)
        # Narrative token overlap with customer/company words (e.g. CLINIC)
        cust = customer_map.get(inv.customer_id)
        name_tokens = set()
        if cust:
            name_tokens = {
                t
                for t in cust.name.upper().replace(",", " ").split()
                if len(t) >= 4
            }
            # singular/plural loose match
            for t in list(name_tokens):
                if t.endswith("S"):
                    name_tokens.add(t[:-1])
                else:
                    name_tokens.add(t + "S")
        overlap = payer_tokens & name_tokens
        if overlap:
            rank += 15.0
        for hint in norm.invoice_hints:
            if hint.invoice_number.upper() == inv.invoice_number.upper():
                rank += 20.0
        reason_bits = [f"amount {kind.value}"]
        if overlap:
            reason_bits.append(f"narration tokens {sorted(overlap)}")
        ranked.append(
            (
                rank,
                {
                    "invoice_numbers": [inv.invoice_number],
                    "confidence": 0.0,
                    "reason": "; ".join(reason_bits),
                    "customer_id": inv.customer_id,
                    "soft_hint": True,
                },
            )
        )
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in ranked[:3]]


def _none_result(
    *,
    reason: str,
    evidence: Evidence,
    alternatives: list[dict],
) -> MatchResult:
    return MatchResult(
        suggestion_type=SuggestionType.NONE,
        invoice_numbers=[],
        confidence=0.0,
        reason=reason,
        evidence=evidence.to_dict(),
        alternatives=alternatives,
        band="none",
    )


def _fallback_reason(
    norm: NormalizedNarration, payer_sim: float, alias: str
) -> str:
    if norm.invoice_hints:
        return "Invoice reference found but no open matching invoice"
    if payer_sim > 0 and alias:
        return f"Payer resembles {alias} ({payer_sim:.0f}) but amount does not match open invoices"
    return "Payer not recognized"
