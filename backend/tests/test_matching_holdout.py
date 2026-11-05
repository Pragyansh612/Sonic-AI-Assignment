"""Held-out adversarial evaluation — labels written independently of thresholds."""

from __future__ import annotations

import json

from app.services.matching import match_credit
from app.services.matching.candidates import classify_amount
from app.services.matching.types import AmountMatchKind
from app.services.statement_parser import parse_statement_csv
from tests.helpers_matching import FIXTURES, load_customers, load_open_invoices


def test_holdout_eval() -> None:
    invoices = load_open_invoices()
    customers = load_customers()
    parsed = parse_statement_csv((FIXTURES / "eval_holdout.csv").read_bytes())
    labels = json.loads(
        (FIXTURES / "eval_holdout_labels.json").read_text(encoding="utf-8")
    )
    by_row = {row.row_number: row for row in parsed.transactions}

    failures: list[str] = []
    tp = fp = fn = tn = 0

    print("\n=== Holdout evaluation ===")
    print(f"{'row':>3} {'expect':>7} {'got':>7} {'conf':>5} invoices  # note")

    for label in labels:
        row = by_row[label["row"]]
        expect = label["expect"]

        if expect == "debit" or row.is_debit:
            print(f"{label['row']:3d} {expect:>7} {'debit':>7} {0:5.1f} []  # {label['note']}")
            if not (row.is_debit and expect == "debit"):
                failures.append(f"row {label['row']}: expected debit")
            continue

        result = match_credit(
            narration=row.narration,
            payment_minor=row.credit_minor or 0,
            currency=row.currency,
            txn_date=row.txn_date,
            invoices=invoices,
            customers=customers,
        )
        got = result.suggestion_type.value
        nums = result.invoice_numbers
        print(
            f"{label['row']:3d} {expect:>7} {got:>7} {result.confidence:5.1f} "
            f"{nums}  # {label['note']}"
        )

        if expect == "none":
            if got == "none":
                tn += 1
            else:
                fp += 1
                failures.append(
                    f"row {label['row']}: expected none got {got} {nums} ({label['note']})"
                )
            continue

        if got == "none":
            fn += 1
            failures.append(
                f"row {label['row']}: missed {expect} {label['invoices']} ({label['note']})"
            )
            continue

        if got == expect and set(nums) == set(label["invoices"]):
            tp += 1
        else:
            fp += 1
            failures.append(
                f"row {label['row']}: expect {expect} {label['invoices']} "
                f"got {got} {nums} ({label['note']})"
            )

    harbour = next(i for i in invoices if i.invoice_number == "INV-1021")
    assert classify_amount(1_125_000, harbour) == AmountMatchKind.PARTIAL

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    print("\n=== Holdout table ===")
    print(f"tp={tp} fp={fp} fn={fn} tn={tn}")
    print(f"precision={precision:.3f} recall={recall:.3f}")

    assert fp == 0, "Holdout wrong matches:\n" + "\n".join(failures)
    assert precision == 1.0
    assert recall >= 0.75, "Holdout misses:\n" + "\n".join(failures)
