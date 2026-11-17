"""Formula estimates for buyer facts the inputs lack. Each one is listed in
Proposal.estimated and marked "(est.)" on its slide, for a reviewer to re-check."""

from __future__ import annotations

import re
from collections.abc import Iterable

# First match wins, issuer before title before tender text, so "Health Authority" is Healthcare.
SECTOR_RULES = (
    ("Healthcare", r"health|hospital|clinic|patient|medical"),
    ("Public sector", r"ministry|municipal|council|government|public|authority"),
    ("Consumer goods", r"consumer goods|retail|fashion|fmcg|e-commerce"),
    ("Utilities", r"\bwater\b|energy|electricity|utilit"),
    ("Logistics", r"logistic|transport|freight|shipping"),
    ("Financial services", r"\bbank|insurance|financ"),
    ("Manufacturing", r"manufactur|factory|industrial"),
)
FALLBACK_SECTOR = "Cross-sector"

_COUNT_WORDS = "zero one two three four five six seven eight nine ten eleven twelve".split()
_NUMBER = r"(\d[\d,]*|" + "|".join(_COUNT_WORDS) + r")"
_EMPLOYEES = re.compile(_NUMBER + r"\s+(?:employees|staff|people)\b", re.I)
_SITES = re.compile(_NUMBER + r"\s+(hospital sites|hospitals|sites|stores|plants|branches|clinics)\b",
                    re.I)
_COUNTRIES = re.compile(_NUMBER + r"\s+countries\b", re.I)
# The EU SME definition (Recommendation 2003/361/EC): fewer than 250 employees.
SME_LIMIT = 250


def estimate_sector(tender: dict) -> str:
    for part in (tender.get("issuer"), tender.get("title"), tender.get("raw_text")):
        for sector, pattern in SECTOR_RULES:
            if part and re.search(pattern, part, re.I):
                return sector
    return FALLBACK_SECTOR


def _count(match: re.Match) -> int:
    word = match.group(1).lower()
    return _COUNT_WORDS.index(word) if word in _COUNT_WORDS else int(word.replace(",", ""))


def estimate_size(tender: dict) -> str:
    """The size the tender states: headcount with its EU band, else sites, plus countries.
    No revenue is guessed from it."""
    text = tender.get("raw_text") or ""
    parts = []
    if m := _EMPLOYEES.search(text):
        n = _count(m)
        parts.append(f"{'SME' if n < SME_LIMIT else 'Large'}: {n:,} staff")
    elif m := _SITES.search(text):
        parts.append(f"{_count(m)} {m.group(2).lower()}")
    if m := _COUNTRIES.search(text):
        parts.append(f"{_count(m)} countries")
    return ", ".join(parts) or "Size not stated in the tender"


def _is_product_name(term: str) -> bool:
    words = term.split()
    return 0 < len(words) <= 2 and all(w[0].isupper() or w[0].isdigit() for w in words)


def estimate_partners(tender: dict, vocabulary: Iterable[str]) -> str:
    """The products from our own records that the tender names, in the order it names them."""
    text = " ".join([tender.get("raw_text") or "", *map(str, tender.get("requirements") or [])])
    found = {}
    for term in {t for t in vocabulary if isinstance(t, str) and _is_product_name(t)}:
        if m := re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.I):
            found[term] = m.start()
    named = sorted(found, key=found.get)[:3]
    return ", ".join(named) if named else "None named in the tender"
