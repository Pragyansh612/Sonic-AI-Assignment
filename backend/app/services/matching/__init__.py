"""Local bank-statement matching (no LLM / no DB inside)."""

from app.services.matching.scoring import match_credit
from app.services.matching.types import (
    CustomerInfo,
    MatchResult,
    OpenInvoice,
    SuggestionType,
)

__all__ = [
    "CustomerInfo",
    "MatchResult",
    "OpenInvoice",
    "SuggestionType",
    "match_credit",
]
