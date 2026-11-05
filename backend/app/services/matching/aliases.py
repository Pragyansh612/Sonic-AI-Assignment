"""Customer alias generation (company + contact name variants)."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from app.services.matching.normalize import METHOD_TOKENS, NOISE_ALWAYS
from app.services.matching.types import CustomerInfo

logger = logging.getLogger(__name__)

# Legal / corporate suffixes stripped when building aliases.
_LEGAL_SUFFIXES = frozenset(
    {
        "PVT",
        "PRIVATE",
        "LTD",
        "LIMITED",
        "LLC",
        "INC",
        "INCORPORATED",
        "GMBH",
        "LLP",
        "PLC",
        "CO",
        "COMPANY",
        "CORP",
        "CORPORATION",
        "AG",
        "SA",
        "BV",
        "NV",
        "LP",
        "PC",
    }
)

# Small configurable abbreviation expansions / contractions.
# Keys and values are uppercase tokens.
ABBREVIATION_MAP: dict[str, frozenset[str]] = {
    "PKG": frozenset({"PACKAGING", "PACKAGE", "PACK"}),
    "PACKAGING": frozenset({"PKG", "PACK"}),
    "HOSP": frozenset({"HOSPITAL", "HOSPITALITY", "HOSP"}),
    "HOSPITALITY": frozenset({"HOSP", "HOSPITAL"}),
    "HOSPITAL": frozenset({"HOSP"}),
    "SVCS": frozenset({"SERVICES", "SERVICE", "SVCS"}),
    "SERVICES": frozenset({"SVCS", "SERVICE"}),
    "SERVICE": frozenset({"SVCS", "SERVICES"}),
    "TECH": frozenset({"TECHNOLOGIES", "TECHNOLOGY", "TECH"}),
    "TECHNOLOGIES": frozenset({"TECH", "TECHNOLOGY"}),
    "TECHNOLOGY": frozenset({"TECH", "TECHNOLOGIES"}),
    "ANALYTICS": frozenset({"ANALYTIC"}),
    "CLINICS": frozenset({"CLINIC"}),
    "CLINIC": frozenset({"CLINICS"}),
    "MEDIA": frozenset({"MEDIA"}),
    "FOODS": frozenset({"FOOD"}),
    "FOOD": frozenset({"FOODS"}),
    "LOGISTICS": frozenset({"LOGISTIC", "LOGIX"}),
}

# Extra banking words that must never become payer aliases (beyond narration noise).
_BANKING_STOPLIST = frozenset(
    {
        "CR",
        "DR",
        "RC",
        "REF",
        "REFERENCE",
        "UTR",
        "RRN",
        "PAY",
        "BANK",
        "TRF",
        "FROM",
        "TO",
        "AC",
        "A/C",
        "CHQ",
        "CHEQUE",
        "FT",
        "FX",
        "INB",
        "MOB",
        "ACH",
        "WIRE",
        "DEPOSIT",
        "WITHDRAWAL",
        "CREDIT",
        "DEBIT",
        "CUST",
        "RECVD",
        "RECEIVED",
        "ONLINE",
        "TXN",
        "SETTLEMENT",
    }
)

MIN_ACRONYM_LEN = 3

FORBIDDEN_ALIAS_TOKENS: frozenset[str] = frozenset(
    {t.upper() for t in (METHOD_TOKENS | NOISE_ALWAYS | _BANKING_STOPLIST)}
)


def build_aliases(customer: CustomerInfo) -> dict[str, str]:
    """
    Return alias → source ("company"|"contact") for a customer.

    Company aliases are stronger evidence than contact-name aliases.
    Aliases that collide with bank noise / method tokens / banking stoplist,
    or short acronyms (< MIN_ACRONYM_LEN letters), are dropped and logged.
    """
    aliases: dict[str, str] = {}

    for alias in _company_aliases(customer.name):
        aliases[alias] = "company"

    for alias in _contact_aliases(customer.contact_name):
        # Do not overwrite a company alias with a weaker contact one
        aliases.setdefault(alias, "contact")

    return _sanitize_aliases(customer.customer_id, aliases)


def build_alias_index(
    customers: Iterable[CustomerInfo],
) -> dict[str, list[tuple[str, str, str]]]:
    """
    Map normalized alias → list of (customer_id, alias, source).
    Used for reverse lookup during scoring.
    """
    index: dict[str, list[tuple[str, str, str]]] = {}
    for customer in customers:
        for alias, source in build_aliases(customer).items():
            key = _norm(alias)
            index.setdefault(key, []).append((customer.customer_id, alias, source))
    return index


def alias_violation_reason(alias: str) -> str | None:
    """
    Return a short reason if `alias` is unsafe as a payer alias, else None.

    Rules:
    - any token in FORBIDDEN_ALIAS_TOKENS
    - single letter-only token shorter than MIN_ACRONYM_LEN (short acronym)
    """
    tokens = _alias_tokens(alias)
    if not tokens:
        return "empty"
    if (
        len(tokens) == 1
        and tokens[0].isalpha()
        and len(tokens[0]) < MIN_ACRONYM_LEN
    ):
        return f"short_acronym<{MIN_ACRONYM_LEN}"
    for tok in tokens:
        if tok in FORBIDDEN_ALIAS_TOKENS:
            return f"forbidden_token:{tok}"
    return None


def assert_customer_aliases_safe(
    customers: Iterable[CustomerInfo],
) -> None:
    """
    Seed / startup invariant: every retained alias is free of bank-noise tokens
    and short acronyms. `build_aliases` already drops violators; this asserts
    nothing forbidden slipped through.
    """
    for customer in customers:
        for alias in build_aliases(customer):
            reason = alias_violation_reason(alias)
            assert reason is None, (
                f"unsafe alias {alias!r} for {customer.customer_id} "
                f"({customer.name}): {reason}"
            )


def _sanitize_aliases(
    customer_id: str, aliases: dict[str, str]
) -> dict[str, str]:
    kept: dict[str, str] = {}
    for alias, source in aliases.items():
        reason = alias_violation_reason(alias)
        if reason is not None:
            logger.warning(
                "Dropping unsafe customer alias customer_id=%s alias=%r "
                "source=%s reason=%s",
                customer_id,
                alias,
                source,
                reason,
            )
            continue
        kept[alias] = source
    return kept


def _alias_tokens(alias: str) -> list[str]:
    return [t for t in re.split(r"[^A-Z0-9]+", alias.upper()) if t]


def _company_aliases(name: str) -> set[str]:
    tokens = _tokenize(name)
    core = [t for t in tokens if t not in _LEGAL_SUFFIXES]
    aliases: set[str] = set()

    if not core:
        return aliases

    joined = " ".join(core)
    aliases.add(joined)
    aliases.add("".join(core))
    # Two-letter acronyms (RC, BL, …) collide with bank noise / reordered CR/DR
    # tokens and create false high-scoring payer matches.
    acr = _acronym(core)
    if len(acr) >= MIN_ACRONYM_LEN:
        aliases.add(acr)

    # Singular / plural variants of last significant token
    for i, tok in enumerate(core):
        variants = _singular_plural(tok) | set(ABBREVIATION_MAP.get(tok, ()))
        for v in variants:
            alt = list(core)
            alt[i] = v
            aliases.add(" ".join(alt))
            aliases.add("".join(alt))

    # First word alone (e.g. KESTREL) — useful for short narrations
    if len(core[0]) >= 4:
        aliases.add(core[0])

    # First two words
    if len(core) >= 2:
        aliases.add(f"{core[0]} {core[1]}")

    return {a for a in aliases if a and len(a) >= 2}


def _contact_aliases(contact_name: str) -> set[str]:
    """
    Initials + surname permutations, e.g.
    "Dr. Anil Menon" → ANIL MENON, A MENON, A M, etc.
    "R K Sharma" style when contact is multi-part.
    """
    raw = re.sub(r"\b(?:DR|MR|MRS|MS|PROF)\b\.?", " ", contact_name.upper())
    parts = [p for p in re.split(r"[^A-Z]+", raw) if p]
    if not parts:
        return set()

    aliases: set[str] = set()
    aliases.add(" ".join(parts))
    surname = parts[-1]
    given = parts[:-1]

    if given:
        initials = " ".join(p[0] for p in given)
        aliases.add(f"{initials} {surname}")
        aliases.add(f"{''.join(p[0] for p in given)} {surname}")
        aliases.add(f"{given[0][0]} {surname}")
        aliases.add(f"{given[0]} {surname}")
        if len(given) >= 2:
            aliases.add(f"{given[0][0]} {given[1][0]} {surname}")

    aliases.add(surname)
    return {a for a in aliases if a and len(a) >= 2}


def _tokenize(name: str) -> list[str]:
    upper = name.upper()
    upper = re.sub(r"[^A-Z0-9\s]", " ", upper)
    return [t for t in upper.split() if t]


def _acronym(tokens: list[str]) -> str:
    return "".join(t[0] for t in tokens if t)


def _singular_plural(token: str) -> set[str]:
    out = {token}
    if token.endswith("IES") and len(token) > 4:
        out.add(token[:-3] + "Y")
    elif token.endswith("S") and len(token) > 3 and not token.endswith("SS"):
        out.add(token[:-1])
    else:
        out.add(token + "S")
        if token.endswith("Y") and len(token) > 2:
            out.add(token[:-1] + "IES")
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.upper().strip())
