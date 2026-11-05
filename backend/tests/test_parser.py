from __future__ import annotations

from app.money import major_to_minor
from app.services.statement_parser import parse_date, parse_statement_csv


def test_parse_indian_amount_and_dates() -> None:
    csv = """txn_date,narration,reference,credit,debit,currency
2026-09-30,NEFT CR-TEST,abc,"2,36,000.00",,INR
30/09/2026,NEFT CR-TEST2,def,1000,,USD
30 Sep 2026,NEFT CR-TEST3,,500,,EUR
"""
    result = parse_statement_csv(csv)
    assert result.ok_rows == 3
    assert result.transactions[0].credit_minor == major_to_minor(236000)
    assert result.transactions[1].txn_date == "2026-09-30"
    assert result.transactions[2].txn_date == "2026-09-30"


def test_row_errors_do_not_abort() -> None:
    csv = """txn_date,narration,reference,credit,debit,currency
2026-09-30,OK ROW,abc,100,,INR
not-a-date,BAD DATE,abc,100,,INR
2026-09-30,BOTH,abc,100,50,INR
"""
    result = parse_statement_csv(csv)
    assert result.ok_rows == 1
    assert len(result.errors) == 2


def test_duplicate_flagged_not_dropped() -> None:
    csv = """txn_date,narration,reference,credit,debit,currency
2026-09-30,NEFT CR-X,abc,100,,INR
2026-09-30,NEFT CR-X,abc,100,,INR
"""
    result = parse_statement_csv(csv)
    assert result.ok_rows == 2
    assert result.transactions[1].possible_duplicate is True


def test_parse_date_formats() -> None:
    assert parse_date("2026-09-30") == "2026-09-30"
    assert parse_date("30-09-2026") == "2026-09-30"
    assert parse_date("30/09/2026") == "2026-09-30"
    assert parse_date("30 Sep 2026") == "2026-09-30"
