"""Synthetic labelled evaluation + sample CSV behavioural smoke tests."""

from __future__ import annotations

import json

from app.services.matching import match_credit
from app.services.statement_parser import parse_statement_csv
from tests.helpers_matching import FIXTURES, ROOT, load_customers, load_open_invoices


def test_synthetic_eval_zero_wrong_matches() -> None:
    invoices = load_open_invoices()
    customers = load_customers()
    parsed = parse_statement_csv((FIXTURES / "eval_statement.csv").read_bytes())
    labels = json.loads((FIXTURES / "eval_labels.json").read_text(encoding="utf-8"))
    by_row = {row.row_number: row for row in parsed.transactions}

    matched = 0
    correct_positive = 0
    wrong = 0
    true_none = 0
    false_none = 0
    failures: list[str] = []

    print("\n=== Synthetic evaluation ===")
    print(f"{'row':>3} {'expect':>7} {'got':>7} {'conf':>5} invoices  note")

    for label in labels:
        row = by_row[label["row"]]
        expect = label["expect"]

        if expect == "debit" or row.is_debit:
            got = "debit" if row.is_debit else "credit?"
            ok = row.is_debit and expect == "debit"
            print(f"{label['row']:3d} {expect:>7} {got:>7} {0:5.1f} []  # {label['note']}")
            if not ok:
                failures.append(f"row {label['row']}: expected debit")
                wrong += 1
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
                true_none += 1
            else:
                wrong += 1
                failures.append(
                    f"row {label['row']}: expected none, got {got} {nums} ({label['note']})"
                )
            continue

        # expect single/multi
        if got == "none":
            false_none += 1
            failures.append(
                f"row {label['row']}: missed {expect} {label['invoices']} ({label['note']})"
            )
            continue

        matched += 1
        if got == expect and set(nums) == set(label["invoices"]):
            correct_positive += 1
        else:
            wrong += 1
            failures.append(
                f"row {label['row']}: expect {expect} {label['invoices']} "
                f"got {got} {nums} ({label['note']})"
            )

    should = sum(1 for lab in labels if lab["expect"] in {"single", "multi"})
    precision = correct_positive / matched if matched else 1.0
    recall = correct_positive / should if should else 1.0
    no_match = true_none + false_none

    print("\n=== Evaluation table ===")
    print(
        f"rows={len(labels)} matched={matched} correct={correct_positive} "
        f"wrong={wrong} no_match={no_match} true_none={true_none} misses={false_none}"
    )
    print(f"precision={precision:.3f} recall={recall:.3f}")

    assert wrong == 0, "Wrong matches on synthetic set:\n" + "\n".join(failures)
    assert precision == 1.0
    assert recall >= 0.7


def test_sample_csv_behaviours() -> None:
    invoices = load_open_invoices()
    customers = load_customers()
    parsed = parse_statement_csv(
        (ROOT / "data" / "bank_statement_sample.csv").read_bytes()
    )
    assert parsed.ok_rows == 14

    results = []
    for row in parsed.transactions:
        if row.is_debit:
            results.append(("debit", [], 0.0, "debit"))
            continue
        r = match_credit(
            narration=row.narration,
            payment_minor=row.credit_minor or 0,
            currency=row.currency,
            txn_date=row.txn_date,
            invoices=invoices,
            customers=customers,
        )
        results.append(
            (r.suggestion_type.value, r.invoice_numbers, r.confidence, r.reason)
        )

    print("\n=== Sample CSV suggestions ===")
    for i, (stype, nums, conf, reason) in enumerate(results, start=1):
        print(f"{i:2d} {stype:6} {conf:5.1f} {nums} | {reason}")

    assert results[7][0] == "debit"
    assert results[10][0] == "debit"
    assert results[12][0] == "none"  # Maple
    assert results[13][0] == "none"  # interest
    assert results[11][0] == "none"  # R K Sharma

    assert results[2][0] == "single"
    assert results[2][1] == ["INV-1007"]
    assert "TDS" in results[2][3]

    assert results[9][0] == "multi"
    assert set(results[9][1]) == {"INV-1010", "INV-1011", "INV-1012"}

    assert results[0][1] == ["INV-1004"]
    assert results[5][1] == ["INV-1002"]
