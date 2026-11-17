"""Canonical forms for tender identity (dedup key + near-duplicate scoring).

Lives in shared/ rather than detection/normalize.py because two very different
callers need it: the ingest pipeline (detection) and the SQLite v2 migration
(shared/store.py), which must recompute stored ``dedup_hash`` values with the
same function. store must not import the detection package (normalize already
imports store), so the canonicalization is hoisted here.

Key rules, in order: NFKD-normalize, strip combining marks (accent fold),
casefold, punctuation -> space, drop legal-suffix tokens, collapse whitespace.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

# Suffixes that carry no identifying weight. "SAS" is deliberately absent: in
# English text it usually means the analytics vendor, and stripping it would
# collapse "SAS Institute" onto every other "Institute". "société" is listed
# in its folded form because the NFKD step below removes the accent.
LEGAL_SUFFIXES: frozenset[str] = frozenset(
    {
        "sa", "sarl", "spa", "suarl", "snc", "gie",
        "ltd", "llc", "gmbh", "inc", "limited", "societe",
    }
)


def canonical_text(value: str) -> str:
    """Return the identity-bearing form of a title or issuer name."""
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.casefold()
    # Keep unicode word characters (Arabic, French, digits) and whitespace;
    # everything else (dashes, slashes, quotes, underscores) becomes a space.
    folded = re.sub(r"[^\w\s]|_", " ", folded)
    tokens = [token for token in folded.split() if token not in LEGAL_SUFFIXES]
    return " ".join(tokens)


def canonical_key(title: str, issuer: str) -> str:
    """32-hex SHA-256 natural key over the canonical ``title|issuer`` pair.

    32 hex (128 bits) rather than the old 16 keeps accidental or adversarial
    collisions negligible now that accent folding and suffix stripping make
    many cosmetic variants land on one key.
    """
    return hashlib.sha256(
        f"{canonical_text(title)}|{canonical_text(issuer)}".encode("utf-8")
    ).hexdigest()[:32]


def title_similarity(left: str, right: str) -> float:
    """SequenceMatcher ratio over canonical titles (0.0-1.0).

    Used only for the warning-level near-duplicate flag; never for identity —
    near-duplicates are flagged, never merged (phase-2 §4.2).
    """
    return SequenceMatcher(None, canonical_text(left), canonical_text(right)).ratio()
