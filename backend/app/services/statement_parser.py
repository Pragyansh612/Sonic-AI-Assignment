"""CSV bank statement ingestion with row-level error collection."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.money import major_to_minor
from app.services.matching import config as cfg

REQUIRED_HEADERS = ("txn_date", "narration", "reference", "credit", "debit", "currency")

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "SEPT": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


@dataclass
class ParseError:
    row_number: int  # 1-based data row (header is 0)
    field: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "field": self.field,
            "message": self.message,
        }


@dataclass
class ParsedTransaction:
    row_number: int
    txn_date: str  # ISO YYYY-MM-DD
    narration: str
    reference: str
    credit_minor: int | None
    debit_minor: int | None
    currency: str
    is_credit: bool
    is_debit: bool
    possible_duplicate: bool = False
    parse_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "txn_date": self.txn_date,
            "narration": self.narration,
            "reference": self.reference,
            "credit_minor": self.credit_minor,
            "debit_minor": self.debit_minor,
            "currency": self.currency,
            "is_credit": self.is_credit,
            "is_debit": self.is_debit,
            "possible_duplicate": self.possible_duplicate,
            "parse_warnings": self.parse_warnings,
        }


@dataclass
class ParseResult:
    transactions: list[ParsedTransaction]
    errors: list[ParseError]
    filename: str

    @property
    def ok_rows(self) -> int:
        return len(self.transactions)


def validate_upload_meta(*, filename: str, content_type: str | None, size: int) -> None:
    if size <= 0:
        raise ValueError("Empty upload")
    if size > cfg.MAX_UPLOAD_BYTES:
        raise ValueError(f"File exceeds {cfg.MAX_UPLOAD_BYTES} bytes")
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in cfg.ALLOWED_UPLOAD_EXTENSIONS):
        raise ValueError("Only .csv files are accepted")
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct and ct not in cfg.ALLOWED_CONTENT_TYPES:
            raise ValueError(f"Unsupported content type: {ct}")


def parse_statement_csv(
    content: bytes | str,
    *,
    filename: str = "upload.csv",
) -> ParseResult:
    if isinstance(content, bytes):
        text = content.decode("utf-8-sig", errors="replace")
    else:
        text = content

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return ParseResult(
            transactions=[],
            errors=[ParseError(0, None, "CSV has no header row")],
            filename=filename,
        )

    headers = [_norm_header(h) for h in reader.fieldnames]
    missing = [h for h in REQUIRED_HEADERS if h not in headers]
    if missing:
        return ParseResult(
            transactions=[],
            errors=[
                ParseError(
                    0,
                    None,
                    f"Missing required columns: {', '.join(missing)}",
                )
            ],
            filename=filename,
        )

    # Map normalized header → original
    header_map = {_norm_header(h): h for h in reader.fieldnames}

    transactions: list[ParsedTransaction] = []
    errors: list[ParseError] = []
    seen_keys: dict[tuple[str, str, int, str], int] = {}

    for idx, raw_row in enumerate(reader, start=1):
        if idx > cfg.MAX_CSV_ROWS:
            errors.append(
                ParseError(
                    idx,
                    None,
                    f"Row cap exceeded ({cfg.MAX_CSV_ROWS}); remaining rows skipped",
                )
            )
            break

        row = {
            _norm_header(k): (v.strip() if isinstance(v, str) else v)
            for k, v in raw_row.items()
            if k is not None
        }

        try:
            txn = _parse_row(idx, row, header_map)
        except RowParseError as exc:
            errors.append(ParseError(idx, exc.field, exc.message))
            continue

        key = (
            txn.txn_date,
            txn.narration,
            txn.credit_minor or txn.debit_minor or 0,
            txn.reference,
        )
        if key in seen_keys:
            txn.possible_duplicate = True
            txn.parse_warnings.append(
                f"Possible duplicate of row {seen_keys[key]}"
            )
        else:
            seen_keys[key] = idx
        transactions.append(txn)

    return ParseResult(transactions=transactions, errors=errors, filename=filename)


class RowParseError(Exception):
    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


def _parse_row(
    row_number: int, row: dict[str, Any], _header_map: dict[str, str]
) -> ParsedTransaction:
    date_raw = row.get("txn_date") or ""
    narration = row.get("narration") or ""
    reference = row.get("reference") or ""
    credit_raw = row.get("credit") or ""
    debit_raw = row.get("debit") or ""
    currency_raw = (row.get("currency") or "").strip().upper()

    if not date_raw:
        raise RowParseError("Missing txn_date", "txn_date")
    try:
        txn_date = parse_date(str(date_raw))
    except ValueError as exc:
        raise RowParseError(str(exc), "txn_date") from exc

    if not narration.strip():
        raise RowParseError("Missing narration", "narration")

    if not currency_raw:
        raise RowParseError("Missing currency", "currency")

    credit_minor = _parse_money_optional(str(credit_raw), field="credit")
    debit_minor = _parse_money_optional(str(debit_raw), field="debit")

    if credit_minor is None and debit_minor is None:
        raise RowParseError("Both credit and debit are blank", None)
    if credit_minor is not None and debit_minor is not None:
        raise RowParseError("Both credit and debit are set", None)

    is_credit = credit_minor is not None and credit_minor > 0
    is_debit = debit_minor is not None and debit_minor > 0
    if credit_minor == 0 or debit_minor == 0:
        raise RowParseError("Zero-value movement is invalid", None)

    return ParsedTransaction(
        row_number=row_number,
        txn_date=txn_date,
        narration=str(narration).strip(),
        reference=str(reference).strip(),
        credit_minor=credit_minor,
        debit_minor=debit_minor,
        currency=currency_raw,
        is_credit=bool(is_credit),
        is_debit=bool(is_debit),
    )


def _parse_money_optional(raw: str, *, field: str) -> int | None:
    cleaned = raw.strip()
    if cleaned == "":
        return None
    try:
        # Indian grouping: strip all commas ("2,36,000.00" → "236000.00")
        normalized = cleaned.replace(",", "")
        amount = Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:
        raise RowParseError(f"Invalid {field} amount: {raw!r}", field) from exc
    if amount < 0:
        raise RowParseError(f"Negative {field} not allowed", field)
    return major_to_minor(amount)


def parse_date(value: str) -> str:
    """Parse multiple date formats into YYYY-MM-DD."""
    v = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue

    m = re.match(
        r"^(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})$",
        v,
    )
    if m:
        day = int(m.group(1))
        mon = _MONTHS.get(m.group(2)[:4].upper()) or _MONTHS.get(m.group(2)[:3].upper())
        year = int(m.group(3))
        if mon:
            return datetime(year, mon, day).date().isoformat()

    raise ValueError(f"Unrecognized date format: {value!r}")


def _norm_header(h: str | None) -> str:
    return (h or "").strip().lower().replace(" ", "_")
