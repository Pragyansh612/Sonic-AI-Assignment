"""Customer alias generation (company + contact name variants)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.services.matching.types import CustomerInfo

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


def build_aliases(customer: CustomerInfo) -> dict[str, str]:
    """
    Return alias → source ("company"|"contact") for a customer.

    Company aliases are stronger evidence than contact-name aliases.
    """
    aliases: dict[str, str] = {}

    for alias in _company_aliases(customer.name):
        aliases[alias] = "company"

    for alias in _contact_aliases(customer.contact_name):
        # Do not overwrite a company alias with a weaker contact one
        aliases.setdefault(alias, "contact")

    return aliases


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


def _company_aliases(name: str) -> set[str]:
    tokens = _tokenize(name)
    core = [t for t in tokens if t not in _LEGAL_SUFFIXES]
    aliases: set[str] = set()

    if not core:
        return aliases

    joined = " ".join(core)
    aliases.add(joined)
    aliases.add("".join(core))
    aliases.add(_acronym(core))

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
