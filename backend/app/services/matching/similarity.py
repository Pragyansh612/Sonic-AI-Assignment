"""
Name similarity techniques.

Why these were kept / rejected
------------------------------
- token_set_ratio (rapidfuzz): Kept. Handles reordered / extra tokens
  ("SAFFRON PEAK HOSP OCT DUES" vs "SAFFRON PEAK HOSPITALITY"). Pure
  Levenshtein alone is weak when banks append method noise or dues labels.
- Jaro-Winkler: Kept. Good for short typos and prefix-heavy brand names
  ("QUILLON" vs "QUILON", "REDWOOD CLINIC" vs "REDWOOD CLINICS").
- Char 2–4-gram TF-IDF cosine: Kept (lightweight pure-Python). Catches
  abbreviations and partial string overlap ("ORBIS PKG" vs "ORBIS PACKAGING")
  without needing a trained model. sklearn was rejected as a hard dependency
  for this small corpus; a local Counter-based TF weighting is enough.
- Plain Levenshtein / ratio alone: Rejected as primary score — fails when
  narration has extra words; still available indirectly via JW on short aliases.
- sentence-transformers MiniLM: Optional behind ENABLE_EMBEDDINGS; useful as a
  soft signal only. Default off to keep matching deterministic and offline.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from app.services.matching import config as cfg

_embedder = None
_embedder_failed = False


def name_similarity(a: str, b: str, *, use_embeddings: bool = False) -> float:
    """Combined similarity 0–100 between two name strings."""
    left = _prep(a)
    right = _prep(b)
    if not left or not right:
        return 0.0

    token = float(fuzz.token_set_ratio(left, right))
    jw = JaroWinkler.similarity(left, right) * 100.0
    ngram = _ngram_tfidf_cosine(left, right) * 100.0

    blended = (
        cfg.SIM_TOKEN_SET_WEIGHT * token
        + cfg.SIM_JARO_WEIGHT * jw
        + cfg.SIM_NGRAM_WEIGHT * ngram
    )
    # Also take the max so a single strong technique can carry a clear match
    score = max(blended, token * 0.92, jw * 0.9, ngram * 0.88)

    if use_embeddings:
        emb = _embedding_similarity(left, right)
        if emb is not None:
            score = max(score, (1 - cfg.SIM_EMBEDDING_WEIGHT) * score + cfg.SIM_EMBEDDING_WEIGHT * emb)

    return float(min(100.0, max(0.0, score)))


def best_alias_similarity(
    payer: str,
    aliases: dict[str, str],
    *,
    use_embeddings: bool = False,
) -> tuple[float, str, str]:
    """
    Return (best_score, best_alias, source) for payer vs alias map.
    source is company|contact|"".
    """
    if not payer or not aliases:
        return 0.0, "", ""

    best = 0.0
    best_alias = ""
    best_source = ""
    for alias, source in aliases.items():
        score = name_similarity(payer, alias, use_embeddings=use_embeddings)
        # Soft-penalize contact-only matches so company wins ties
        adjusted = score if source == "company" else score * 0.92
        if adjusted > best:
            best = score  # report raw score
            best_alias = alias
            best_source = source
    return best, best_alias, best_source


def _prep(s: str) -> str:
    s = s.upper()
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _char_ngrams(text: str, n_min: int = 2, n_max: int = 4) -> Counter[str]:
    compact = text.replace(" ", "")
    counts: Counter[str] = Counter()
    for n in range(n_min, n_max + 1):
        if len(compact) < n:
            continue
        for i in range(len(compact) - n + 1):
            counts[compact[i : i + n]] += 1
    # Also include space-aware bigrams of tokens for short strings
    tokens = text.split()
    for i in range(len(tokens) - 1):
        counts[f"{tokens[i]}_{tokens[i+1]}"] += 1
    return counts


def _ngram_tfidf_cosine(a: str, b: str) -> float:
    """Local TF cosine on char n-grams (IDF approximated as log-smoothed TF)."""
    ca, cb = _char_ngrams(a), _char_ngrams(b)
    if not ca or not cb:
        return 0.0

    def weighted(counter: Counter[str]) -> dict[str, float]:
        total = sum(counter.values()) or 1
        return {
            k: (v / total) * math.log(1 + total / v)
            for k, v in counter.items()
        }

    wa, wb = weighted(ca), weighted(cb)
    keys = set(wa) | set(wb)
    dot = sum(wa.get(k, 0.0) * wb.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in wa.values())) or 1.0
    nb = math.sqrt(sum(v * v for v in wb.values())) or 1.0
    return max(0.0, min(1.0, dot / (na * nb)))


def _embedding_similarity(a: str, b: str) -> float | None:
    global _embedder, _embedder_failed
    if _embedder_failed:
        return None
    try:
        model = _get_embedder()
        if model is None:
            return None
        vectors = model.encode([a, b])
        va, vb = vectors[0], vectors[1]
        dot = float(sum(x * y for x, y in zip(va, vb, strict=True)))
        na = math.sqrt(float(sum(x * x for x in va))) or 1.0
        nb = math.sqrt(float(sum(x * x for x in vb))) or 1.0
        return max(0.0, min(100.0, (dot / (na * nb)) * 100.0))
    except Exception:
        _embedder_failed = True
        return None


@lru_cache(maxsize=1)
def _get_embedder():  # type: ignore[no-untyped-def]
    global _embedder, _embedder_failed
    if _embedder_failed:
        return None
    try:
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        return _embedder
    except Exception:
        _embedder_failed = True
        return None
