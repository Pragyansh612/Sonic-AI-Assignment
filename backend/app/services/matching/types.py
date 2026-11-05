from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SuggestionType(str, Enum):
    SINGLE = "single"
    MULTI = "multi"
    NONE = "none"


class AmountMatchKind(str, Enum):
    EXACT_OUTSTANDING = "exact_outstanding"
    EXACT_TOTAL = "exact_total"
    TDS_ADJUSTED = "tds_adjusted"
    PARTIAL = "partial"
    OVERPAY = "overpay"
    MISMATCH = "mismatch"
    MULTI_EXACT = "multi_exact"
    MULTI_TDS = "multi_tds"


class InvoiceHintStrength(str, Enum):
    STRONG = "strong"  # INV-1004 / INV1004 / INV 1004
    WEAK = "weak"  # RE 1024 / REF 1024 / bare digits matching a suffix


@dataclass(frozen=True)
class InvoiceHint:
    raw: str
    invoice_number: str  # canonical INV-####
    strength: InvoiceHintStrength


@dataclass(frozen=True)
class NormalizedNarration:
    original: str
    payer_candidate: str
    cleaned_tokens: tuple[str, ...]
    invoice_hints: tuple[InvoiceHint, ...]


@dataclass(frozen=True)
class OpenInvoice:
    invoice_number: str
    customer_id: str
    customer_name: str
    currency: str
    invoice_date: str  # YYYY-MM-DD
    due_date: str
    outstanding_minor: int
    total_minor: int
    subtotal_minor: int
    status: str


@dataclass(frozen=True)
class CustomerInfo:
    customer_id: str
    name: str
    contact_name: str
    currency: str


@dataclass
class AliasMatch:
    customer_id: str
    alias: str
    score: float
    source: str  # "company" | "contact"


@dataclass
class Evidence:
    invoice_ref_score: float = 0.0
    payer_sim: float = 0.0
    payer_source: str = ""
    payer_alias: str = ""
    amount_kind: str = AmountMatchKind.MISMATCH.value
    amount_score: float = 0.0
    date_score: float = 0.0
    uniqueness_note: str = ""
    currency_ok: bool = True
    hard_reject_reason: str = ""
    components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_ref_score": self.invoice_ref_score,
            "payer_sim": self.payer_sim,
            "payer_source": self.payer_source,
            "payer_alias": self.payer_alias,
            "amount_kind": self.amount_kind,
            "amount_score": self.amount_score,
            "date_score": self.date_score,
            "uniqueness_note": self.uniqueness_note,
            "currency_ok": self.currency_ok,
            "hard_reject_reason": self.hard_reject_reason,
            "components": self.components,
        }


@dataclass
class MatchCandidate:
    invoice_numbers: tuple[str, ...]
    customer_id: str
    confidence: float
    reason: str
    evidence: Evidence
    suggestion_type: SuggestionType


@dataclass
class MatchResult:
    suggestion_type: SuggestionType
    invoice_numbers: list[str]
    confidence: float
    reason: str
    evidence: dict[str, Any]
    alternatives: list[dict[str, Any]]
    band: str  # high | review | none

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestion_type": self.suggestion_type.value,
            "invoice_numbers": self.invoice_numbers,
            "confidence": round(self.confidence, 1),
            "reason": self.reason,
            "evidence": self.evidence,
            "alternatives": self.alternatives,
            "band": self.band,
        }
