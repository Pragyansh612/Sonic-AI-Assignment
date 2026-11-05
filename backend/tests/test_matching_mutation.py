"""Mutation robustness: correct matches must never flip to a *different* invoice.

For every correctly matched row from the sample CSV, synthetic eval, and holdout
fixtures, apply deterministic (seeded) narration mutations. A mutated row may
keep the original match or downgrade to none — never a different invoice/customer.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass

from app.services.matching import match_credit
from app.services.statement_parser import parse_statement_csv
from tests.helpers_matching import FIXTURES, ROOT, load_customers, load_open_invoices

MUTATION_SEED = 20261105
NOISE_WORDS = (
    "PAYMENT",
    "REF",
    "ONLINE",
    "BANK",
    "TRANSFER",
    "CUST",
    "TXN",
    "SETTLEMENT",
    "RECVD",
)


@dataclass(frozen=True)
class CorrectCase:
    source: str
    row: int
    narration: str
    payment_minor: int
    currency: str
    txn_date: str
    invoice_numbers: tuple[str, ...]
    customer_ids: tuple[str, ...]


def _customer_ids_for(
    invoice_numbers: list[str], invoices
) -> tuple[str, ...]:
    by_num = {i.invoice_number: i.customer_id for i in invoices}
    return tuple(sorted({by_num[n] for n in invoice_numbers if n in by_num}))


def _collect_correct_cases() -> list[CorrectCase]:
    invoices = load_open_invoices()
    customers = load_customers()
    cases: list[CorrectCase] = []

    # --- Sample CSV: take rows the matcher currently gets right ---
    sample = parse_statement_csv(
        (ROOT / "data" / "bank_statement_sample.csv").read_bytes()
    )
    for row in sample.transactions:
        if row.is_debit or not row.is_credit or row.credit_minor is None:
            continue
        result = match_credit(
            narration=row.narration,
            payment_minor=row.credit_minor,
            currency=row.currency,
            txn_date=row.txn_date,
            invoices=invoices,
            customers=customers,
        )
        if result.suggestion_type.value == "none" or not result.invoice_numbers:
            continue
        cases.append(
            CorrectCase(
                source="sample",
                row=row.row_number,
                narration=row.narration,
                payment_minor=row.credit_minor,
                currency=row.currency,
                txn_date=row.txn_date,
                invoice_numbers=tuple(result.invoice_numbers),
                customer_ids=_customer_ids_for(result.invoice_numbers, invoices),
            )
        )

    # --- Labelled fixtures (synthetic + holdout): expect single/multi ---
    for csv_name, label_name, source in (
        ("eval_statement.csv", "eval_labels.json", "synthetic"),
        ("eval_holdout.csv", "eval_holdout_labels.json", "holdout"),
    ):
        parsed = parse_statement_csv((FIXTURES / csv_name).read_bytes())
        labels = json.loads((FIXTURES / label_name).read_text(encoding="utf-8"))
        by_row = {r.row_number: r for r in parsed.transactions}
        for label in labels:
            if label["expect"] not in {"single", "multi"}:
                continue
            row = by_row[label["row"]]
            if row.is_debit or row.credit_minor is None:
                continue
            result = match_credit(
                narration=row.narration,
                payment_minor=row.credit_minor,
                currency=row.currency,
                txn_date=row.txn_date,
                invoices=invoices,
                customers=customers,
            )
            expected = set(label["invoices"])
            if (
                result.suggestion_type.value != label["expect"]
                or set(result.invoice_numbers) != expected
            ):
                # Only mutate rows that are currently correct
                continue
            cases.append(
                CorrectCase(
                    source=source,
                    row=label["row"],
                    narration=row.narration,
                    payment_minor=row.credit_minor,
                    currency=row.currency,
                    txn_date=row.txn_date,
                    invoice_numbers=tuple(sorted(expected)),
                    customer_ids=_customer_ids_for(list(expected), invoices),
                )
            )

    return cases


def _typo_payer_tokens(rng: random.Random, narration: str) -> str:
    """Introduce 1–2 character typos in alphabetic payer-like tokens."""
    tokens = narration.split()
    alpha_idxs = [
        i
        for i, t in enumerate(tokens)
        if sum(c.isalpha() for c in t) >= 4
        and not re.match(r"(?i)^inv", t)
        and t.upper()
        not in {
            "NEFT",
            "RTGS",
            "IMPS",
            "UPI",
            "SWIFT",
            "SEPA",
            "PAYMENT",
            "PART",
        }
    ]
    if not alpha_idxs:
        return narration
    for _ in range(min(2, len(alpha_idxs))):
        i = rng.choice(alpha_idxs)
        chars = list(tokens[i])
        letter_pos = [j for j, c in enumerate(chars) if c.isalpha()]
        if not letter_pos:
            continue
        j = rng.choice(letter_pos)
        # swap with neighbor or replace with nearby letter
        if len(letter_pos) > 1 and rng.random() < 0.5:
            k = letter_pos[letter_pos.index(j) - 1]
            chars[j], chars[k] = chars[k], chars[j]
        else:
            base = chars[j]
            offset = rng.choice([-1, 1, 2])
            if base.isupper():
                chars[j] = chr(((ord(base) - 65 + offset) % 26) + 65)
            else:
                chars[j] = chr(((ord(base) - 97 + offset) % 26) + 97)
        tokens[i] = "".join(chars)
    return " ".join(tokens)


def _reorder_tokens(rng: random.Random, narration: str) -> str:
    tokens = narration.split()
    if len(tokens) < 3:
        return narration
    # Keep first method-ish token stable when present; shuffle the rest lightly
    head, rest = tokens[0], tokens[1:]
    if len(rest) >= 2:
        i, j = rng.sample(range(len(rest)), 2)
        rest[i], rest[j] = rest[j], rest[i]
    return " ".join([head, *rest])


_LEGAL_RE = re.compile(
    r"\b(PVT|PRIVATE|LTD|LIMITED|LLC|INC|GMBH|LLP)\b",
    re.IGNORECASE,
)


def _drop_legal_suffixes(narration: str) -> str:
    cleaned = _LEGAL_RE.sub(" ", narration)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _add_noise_words(rng: random.Random, narration: str) -> str:
    words = [rng.choice(NOISE_WORDS) for _ in range(rng.randint(1, 2))]
    tokens = narration.split()
    for w in words:
        pos = rng.randint(0, len(tokens))
        tokens.insert(pos, w)
    return " ".join(tokens)


_INV_TOKEN_RE = re.compile(r"\b(INV)([-\s]?)(\d{3,6})\b", re.IGNORECASE)


def _space_hyphen_invoice_tokens(rng: random.Random, narration: str) -> str:
    def repl(m: re.Match[str]) -> str:
        choice = rng.choice(["space", "hyphen", "compact", "spaced_digits"])
        digits = m.group(3)
        prefix = m.group(1)
        if choice == "space":
            return f"{prefix} {digits}"
        if choice == "hyphen":
            return f"{prefix}-{digits}"
        if choice == "compact":
            return f"{prefix}{digits}"
        # insert hyphen/space inside digit run when long enough
        if len(digits) >= 4:
            cut = len(digits) // 2
            sep = rng.choice(["-", " "])
            return f"{prefix}{sep}{digits[:cut]}{sep}{digits[cut:]}"
        return f"{prefix} {digits}"

    if _INV_TOKEN_RE.search(narration):
        return _INV_TOKEN_RE.sub(repl, narration, count=1)
    # Also mutate bare RE/REF forms
    bare = re.compile(r"\b(RE|REF)([-\s]?)(\d{3,6})\b", re.IGNORECASE)

    def repl2(m: re.Match[str]) -> str:
        return f"{m.group(1)} {m.group(3)[:2]}-{m.group(3)[2:]}" if len(m.group(3)) >= 4 else f"{m.group(1)}-{m.group(3)}"

    if bare.search(narration):
        return bare.sub(repl2, narration, count=1)
    return narration


def _insert_utr_noise(rng: random.Random, narration: str) -> str:
    digits = "".join(str(rng.randint(0, 9)) for _ in range(rng.choice([10, 12, 14])))
    prefix = rng.choice(["UTR", "REF", "RRN", ""])
    blob = f"{prefix}{digits}" if prefix else digits
    tokens = narration.split()
    pos = rng.randint(0, len(tokens))
    tokens.insert(pos, blob)
    return " ".join(tokens)


def _mutations_for(rng: random.Random, narration: str) -> list[tuple[str, str]]:
    """Return named mutated narrations (deterministic given rng state)."""
    return [
        ("typo_payer", _typo_payer_tokens(rng, narration)),
        ("reorder", _reorder_tokens(rng, narration)),
        ("drop_suffix", _drop_legal_suffixes(narration)),
        ("noise_words", _add_noise_words(rng, narration)),
        ("inv_spacing", _space_hyphen_invoice_tokens(rng, narration)),
        ("utr_insert", _insert_utr_noise(rng, narration)),
        # Combined mild compound mutation
        (
            "compound",
            _insert_utr_noise(
                rng,
                _add_noise_words(
                    rng, _drop_legal_suffixes(_typo_payer_tokens(rng, narration))
                ),
            ),
        ),
    ]


def _classify_downgrade(
    *,
    case: CorrectCase,
    mutated: str,
    result,
    invoices,
    known_nums: list[str],
) -> str:
    """Group a downgrade: ambiguity | payer_below_gate | hint_lost | other."""
    from app.services.matching import config as cfg
    from app.services.matching.normalize import normalize_narration

    orig = normalize_narration(case.narration, known_invoice_numbers=known_nums)
    mut = normalize_narration(mutated, known_invoice_numbers=known_nums)
    expected = set(case.invoice_numbers)
    orig_hints = {h.invoice_number for h in orig.invoice_hints}
    mut_hints = {h.invoice_number for h in mut.invoice_hints}
    hint_lost = bool(orig_hints & expected) and not bool(mut_hints & expected)
    hard = (result.evidence or {}).get("hard_reject_reason") or ""
    payer_sim = float((result.evidence or {}).get("payer_sim") or 0)
    siblings = [
        i
        for i in invoices
        if i.customer_id in case.customer_ids
        and int(i.outstanding_minor) == int(case.payment_minor)
        and i.status == "sent"
        and int(i.outstanding_minor) > 0
    ]

    reason_l = (result.reason or "").lower()
    if hard == "no_hint_and_payer_below_threshold" or "payer not recognized" in reason_l:
        return "payer_below_gate"
    if hint_lost and len(siblings) >= 2 and not (mut_hints & expected):
        return "ambiguity"
    if hint_lost:
        return "hint_lost"
    if hard == "no_viable_candidate" or "amount does not match" in reason_l:
        return "other"
    # Soft miss: typo knocked confidence under REVIEW_MIN ("No confident match")
    if "no confident match" in reason_l:
        return "payer_below_gate"
    if payer_sim and payer_sim < cfg.PAYER_SIM_THRESHOLD and not mut_hints:
        return "payer_below_gate"
    return "other"


def test_mutation_never_wrong_match() -> None:
    invoices = load_open_invoices()
    customers = load_customers()
    cases = _collect_correct_cases()
    assert len(cases) >= 20, f"expected a rich base set, got {len(cases)}"

    same = 0
    downgraded = 0
    wrong = 0
    wrong_details: list[str] = []
    downgrade_details: list[dict[str, str]] = []
    total = 0

    print("\n=== Mutation robustness ===")
    print(f"base_correct_rows={len(cases)} seed={MUTATION_SEED}")

    known_nums = [i.invoice_number for i in invoices]
    for case in cases:
        # Independent RNG stream per case for stability if cases reorder slightly
        rng = random.Random(f"{MUTATION_SEED}:{case.source}:{case.row}:{case.narration}")
        for name, mutated in _mutations_for(rng, case.narration):
            if mutated.strip() == case.narration.strip():
                continue
            total += 1
            result = match_credit(
                narration=mutated,
                payment_minor=case.payment_minor,
                currency=case.currency,
                txn_date=case.txn_date,
                invoices=invoices,
                customers=customers,
            )
            got_type = result.suggestion_type.value
            got_nums = set(result.invoice_numbers)
            expected = set(case.invoice_numbers)

            if got_type == "none" or not got_nums:
                downgraded += 1
                downgrade_details.append(
                    {
                        "cause": _classify_downgrade(
                            case=case,
                            mutated=mutated,
                            result=result,
                            invoices=invoices,
                            known_nums=known_nums,
                        ),
                        "source": case.source,
                        "row": str(case.row),
                        "mutation": name,
                        "mut": mutated,
                    }
                )
                continue

            if got_nums == expected:
                same += 1
                continue

            # Different invoice set → wrong (also check customer drift)
            got_cust = set(_customer_ids_for(list(got_nums), invoices))
            wrong += 1
            detail = (
                f"{case.source} row {case.row} [{name}]: "
                f"expected {sorted(expected)} cust={list(case.customer_ids)} "
                f"got {sorted(got_nums)} cust={sorted(got_cust)} "
                f"narration={mutated!r}"
            )
            wrong_details.append(detail)

    print(
        f"mutations={total} same={same} downgraded-to-none={downgraded} wrong={wrong}"
    )
    if wrong_details:
        print("--- wrong matches ---")
        for d in wrong_details[:40]:
            print(d)
        if len(wrong_details) > 40:
            print(f"... and {len(wrong_details) - 40} more")

    # Cause breakdown for downgrades (informational; printed with -s)
    if downgrade_details:
        from collections import Counter

        causes = Counter(d["cause"] for d in downgrade_details)
        print("--- downgraded-to-none by cause ---")
        for cause, n in causes.most_common():
            print(f"  {cause}: {n}")
        for d in downgrade_details:
            print(
                f"  [{d['cause']}] {d['source']} r{d['row']} "
                f"{d['mutation']}: {d['mut']!r}"
            )

    assert wrong == 0, (
        f"{wrong} mutation(s) produced a different invoice/customer:\n"
        + "\n".join(wrong_details[:20])
    )
