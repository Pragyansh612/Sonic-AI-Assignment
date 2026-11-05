"""
Matching thresholds and weights — single source of truth.

Philosophy: wrong matches cost more than missed matches. Prefer "no match"
over a risky guess. Amount alone never matches a payment.
"""

from __future__ import annotations

# --- Hard gates ---
# Below this payer similarity (0-100), and no invoice hint → no match.
PAYER_SIM_THRESHOLD: float = 72.0
# Contact-name-only matches are weaker; require a higher bar to clear the gate.
CONTACT_PAYER_SIM_THRESHOLD: float = 88.0
# Optional relaxation (exact amount + clear margin over 2nd-best customer only):
CONTACT_PAYER_SIM_RELAXED: float = 80.0
CONTACT_PAYER_SECOND_BEST_MARGIN: float = 10.0
# Invoice-hint + payer conflict: cap confidence at this when names disagree.
HINT_CUSTOMER_CONFLICT_CAP: float = 55.0

# --- Confidence bands (applied after scoring) ---
HIGH_CONFIDENCE: float = 85.0  # present as solid suggestion
REVIEW_MIN: float = 60.0  # 60-84: suggest but "review carefully"
# Below REVIEW_MIN → suggestion_type=none (best guess kept in details only)

# --- Component weights (sum ≈ 100 before uniqueness/date adjustments) ---
WEIGHT_INVOICE_REF: float = 38.0  # explicit INV token in narration
WEIGHT_WEAK_INVOICE_REF: float = 18.0  # bare RE/REF/number suffix hint
WEIGHT_PAYER_SIM: float = 35.0
WEIGHT_AMOUNT: float = 28.0
WEIGHT_DATE: float = 5.0
# Extra when payer is strong AND amount is exact/TDS/partial (not mismatch/overpay)
PAYER_AMOUNT_SYNERGY: float = 8.0
STRONG_PAYER_FOR_SYNERGY: float = 85.0

# Amount sub-scores as fraction of WEIGHT_AMOUNT
AMOUNT_EXACT_OUTSTANDING: float = 1.0
AMOUNT_EXACT_TOTAL: float = 0.90
AMOUNT_TDS_ADJUSTED: float = 1.0
AMOUNT_PARTIAL: float = 0.72  # payment < outstanding (not TDS)
AMOUNT_OVERPAY: float = 0.15  # penalize heavily
AMOUNT_MISMATCH: float = 0.0

# Date: payment before invoice_date → reject candidate
# Soft bonus when within N days of due date
DATE_DUE_PROXIMITY_DAYS: int = 14

# Ambiguity: same-customer equal outstanding, no unique invoice hint.
# Policy: do NOT auto-suggest. Cap confidence below REVIEW_MIN so the result is
# type "none", with every sibling named in reason + alternatives for the reviewer.
AMBIGUOUS_CONFIDENCE_CAP: float = 59.0  # must be < REVIEW_MIN (60)
AMBIGUOUS_RIVAL_CONFIDENCE_DELTA: float = 1.0

# Multi-invoice subset-sum
MULTI_MIN_SIZE: int = 2
MULTI_MAX_SIZE: int = 5
MULTI_MAX_COMBINATIONS: int = 2000  # hard cap per customer group

# Similarity blend: max of techniques (kept for robustness), with light weighting
SIM_TOKEN_SET_WEIGHT: float = 0.40
SIM_JARO_WEIGHT: float = 0.30
SIM_NGRAM_WEIGHT: float = 0.30
# Optional embedding (feature-flagged); blended in only when available
SIM_EMBEDDING_WEIGHT: float = 0.15

# TDS tolerance when approving close_tds (1 minor unit)
TDS_TOLERANCE_MINOR: int = 1

# Optional boost when a prior inbound payment email cites the same invoice/ref.
# Capped low enough that evidence alone cannot clear REVIEW_MIN from a no-match.
EMAIL_EVIDENCE_BOOST: float = 5.0

# Upload limits
MAX_UPLOAD_BYTES: int = 2 * 1024 * 1024
MAX_CSV_ROWS: int = 5_000
ALLOWED_UPLOAD_EXTENSIONS: frozenset[str] = frozenset({".csv"})
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "text/plain",
        "application/octet-stream",
    }
)
