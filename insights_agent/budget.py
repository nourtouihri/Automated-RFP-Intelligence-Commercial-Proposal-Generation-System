"""Deterministic budget engine.

The LLM never produces a number. The extractor (added later) may only copy
text spans; every amount, conversion and range below is computed by this code,
the same way ``compute_confidence`` in research/runner.py keeps confidence out
of the model's hands. That makes each figure auditable: a judge can point at
the sentence it came from and the arithmetic applied to it.

Method priority: explicit figure in the tender > comparables > effort > none.
When nothing supports a number, the answer is ``method="none"`` with no
amounts. We do not invent a "wide range" to look complete.
"""

from __future__ import annotations

import os
import re
import statistics
import unicodedata
from dataclasses import dataclass
from typing import Sequence

from insights_agent.schemas import PROFILE_MULTIPLIERS, BudgetEstimate, Workload

# Outside this band a figure is noise (a page count, a phone number, a typo),
# not a tender budget.
MIN_PLAUSIBLE_TND = 1_000.0
MAX_PLAUSIBLE_TND = 5_000_000_000.0

# Placeholder rates: override with INSIGHTS_FX_EUR_TND / INSIGHTS_FX_USD_TND.
DEFAULT_RATES_TO_TND: dict[str, float] = {"TND": 1.0, "EUR": 3.4, "USD": 3.1}
DEFAULT_DAILY_RATE_TND = 400.0

# Effort estimates are asymmetric on purpose: projects overrun more than they
# underrun.
EFFORT_MIN_FACTOR = 0.8
EFFORT_MAX_FACTOR = 1.4

# A lone comparable is a point, not a distribution: widen it and say so.
SINGLE_COMPARABLE_MIN_FACTOR = 0.7
SINGLE_COMPARABLE_MAX_FACTOR = 1.5

# The agent re-examines its own estimate when it is this far from a reference.
SANITY_TOLERANCE = 3.0


def fx_rates() -> dict[str, float]:
    rates = dict(DEFAULT_RATES_TO_TND)
    for cur in ("EUR", "USD"):
        raw = os.environ.get(f"INSIGHTS_FX_{cur}_TND")
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if value > 0:
            rates[cur] = value
    return rates


def daily_rate_tnd() -> float:
    raw = os.environ.get("INSIGHTS_DAILY_RATE_TND")
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_DAILY_RATE_TND


# --------------------------------------------------------------------------
# Amount parsing
# --------------------------------------------------------------------------

_NUM = r"(?:\d{1,3}(?:[ \u00a0\u202f.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?)"
_MULT = r"(?:milliards?|millions?|milliers?|mille|billions?|mio|k|m)"
_CUR = (
    r"(?:ktnd|mtnd|kdt|mdt|md|tnd|dt|dinars?|eur(?:os?)?|€|usd|us\$|dollars?|\$)"
)

# "150 000 TND", "1,2 M€", "2 MD", "500 KDT", "1.5 million EUR"
_AFTER = re.compile(
    rf"(?<![\w.,])(?P<num>{_NUM})\s*(?:(?P<mult>{_MULT})\s*)?(?P<cur>{_CUR})(?![A-Za-z])",
    re.IGNORECASE,
)
# "€1.2M", "$ 500,000", "TND 150 000"
_BEFORE = re.compile(
    rf"(?<![A-Za-z])(?P<cur>{_CUR})\s*(?P<num>{_NUM})(?:\s*(?P<mult>{_MULT}))?(?!\w)",
    re.IGNORECASE,
)

_CUR_MAP: dict[str, tuple[str, float]] = {
    "tnd": ("TND", 1.0), "dt": ("TND", 1.0), "dinar": ("TND", 1.0), "dinars": ("TND", 1.0),
    "ktnd": ("TND", 1e3), "kdt": ("TND", 1e3),
    "mtnd": ("TND", 1e6), "mdt": ("TND", 1e6), "md": ("TND", 1e6),
    "eur": ("EUR", 1.0), "euro": ("EUR", 1.0), "euros": ("EUR", 1.0), "€": ("EUR", 1.0),
    "usd": ("USD", 1.0), "us$": ("USD", 1.0), "dollar": ("USD", 1.0),
    "dollars": ("USD", 1.0), "$": ("USD", 1.0),
}
_MULT_MAP: dict[str, float] = {
    "milliard": 1e9, "milliards": 1e9, "billion": 1e9, "billions": 1e9,
    "million": 1e6, "millions": 1e6, "mio": 1e6, "m": 1e6,
    "mille": 1e3, "millier": 1e3, "milliers": 1e3, "k": 1e3,
}


@dataclass(frozen=True)
class Amount:
    raw: str
    currency: str       # original currency: TND / EUR / USD
    value: float        # in the original currency, multiplier applied
    value_tnd: float    # converted with the configured rates
    start: int
    end: int


def _parse_number(token: str) -> float | None:
    """Parse '150 000', '150.000', '1,2', '1.500,75', '1,500.75'.

    Known ambiguity: a lone separator followed by exactly three digits
    ('1.500') is read as a thousands separator. Tunisian prices can use three
    decimals (millimes); a figure read that way is orders of magnitude off,
    which is why plausibility bounds are applied afterwards.
    """
    s = token.strip().replace("\u00a0", " ").replace("\u202f", " ").replace(" ", "")
    if not s:
        return None
    if "." in s and "," in s:
        decimal = "." if s.rfind(".") > s.rfind(",") else ","
        thousands = "," if decimal == "." else "."
        s = s.replace(thousands, "").replace(decimal, ".")
    elif "." in s or "," in s:
        sep = "." if "." in s else ","
        parts = s.split(sep)
        if len(parts) > 2:
            s = "".join(parts)
        elif len(parts[1]) == 3 and 1 <= len(parts[0]) <= 3 and not parts[0].startswith("0"):
            s = "".join(parts)
        else:
            s = f"{parts[0]}.{parts[1]}"
    try:
        return float(s)
    except ValueError:
        return None


def parse_amounts(text: str, rates: dict[str, float] | None = None) -> list[Amount]:
    """Every monetary amount in ``text``, converted to TND. Order of appearance."""
    rates = rates or fx_rates()
    found: list[Amount] = []
    spans: list[tuple[int, int]] = []
    for rx in (_AFTER, _BEFORE):
        for m in rx.finditer(text):
            start, end = m.span()
            if any(start < pe and ps < end for ps, pe in spans):
                continue
            number = _parse_number(m.group("num"))
            if number is None:
                continue
            currency, cur_mult = _CUR_MAP[m.group("cur").lower()]
            mult = _MULT_MAP.get((m.group("mult") or "").lower(), 1.0)
            value = number * mult * cur_mult
            rate = rates.get(currency)
            if rate is None:
                continue
            spans.append((start, end))
            found.append(
                Amount(
                    raw=m.group(0).strip(),
                    currency=currency,
                    value=value,
                    value_tnd=round(value * rate, 2),
                    start=start,
                    end=end,
                )
            )
    found.sort(key=lambda a: a.start)
    return found


# --------------------------------------------------------------------------
# Explicit budget detection
# --------------------------------------------------------------------------

# Folded (lowercase, accent-free) substrings. "estim" covers estimation /
# estimé / estimated / estimatif.
BUDGET_KEYWORDS = (
    "budget", "enveloppe", "estim", "plafond", "ceiling", "contract value",
    "valeur du marche", "valeur du contrat", "montant du marche",
    "previsionnel",
)
# An amount in the same sentence as one of these is NOT the project budget:
# guarantees, tender-document fees, and eligibility thresholds.
EXCLUDE_KEYWORDS = (
    "caution", "garantie", "bid bond", "performance bond", "penalite", "penalty",
    "retenue", "frais de dossier", "frais d'obtention", "prix du dossier",
    "droit d'inscription", "registration fee", "participation fee", "tender fee",
    "chiffre d'affaires", "turnover", "revenue",
)


def fold_text(text: str) -> str:
    """Casefold, normalise apostrophes and strip accents (for keyword matching)."""
    text = text.replace("\u2019", "'").casefold()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _sentence_context(text: str, start: int, end: int) -> str:
    """The sentence around an amount, bounded by newline, ';' or '. '."""
    before = text[max(0, start - 200):start]
    cut = max(before.rfind("\n"), before.rfind(";"), before.rfind(". ") + 1 if ". " in before else -1)
    ctx_start = max(0, start - 200) + cut + 1 if cut >= 0 else max(0, start - 200)

    after = text[end:end + 200]
    ends = [i for i in (after.find("\n"), after.find(";"), after.find(". ")) if i >= 0]
    ctx_end = end + (min(ends) if ends else len(after))
    return text[ctx_start:ctx_end]


def find_explicit_budget(
    text: str, rates: dict[str, float] | None = None
) -> list[Amount]:
    """Amounts the tender text itself presents as the budget / value."""
    linked: list[Amount] = []
    for amount in parse_amounts(text, rates):
        if not (MIN_PLAUSIBLE_TND <= amount.value_tnd <= MAX_PLAUSIBLE_TND):
            continue
        context = fold_text(_sentence_context(text, amount.start, amount.end))
        if any(k in context for k in EXCLUDE_KEYWORDS):
            continue
        if any(k in context for k in BUDGET_KEYWORDS):
            linked.append(amount)
    return linked


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


def _plausible(values: Sequence[float]) -> list[float]:
    return [v for v in values if MIN_PLAUSIBLE_TND <= v <= MAX_PLAUSIBLE_TND]


def _dedupe(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))


def resolve_budget(
    *,
    explicit: Sequence[Amount] = (),
    comparable_values_tnd: Sequence[float] = (),
    comparable_sources: Sequence[str] = (),
    person_days: float | None = None,
    daily_rate: float | None = None,
    tender_source: str = "tender",
) -> BudgetEstimate:
    """Pick the best-supported method and return a justified range."""
    # 1. Explicit figure(s) stated in the tender.
    figures = sorted({round(a.value_tnd) for a in explicit
                      if MIN_PLAUSIBLE_TND <= a.value_tnd <= MAX_PLAUSIBLE_TND})
    if figures:
        raws = _dedupe([a.raw for a in explicit])[:3]
        assumptions = [f"Figure stated in the tender text: {', '.join(raws)}."]
        foreign = any(a.currency != "TND" for a in explicit)
        if foreign:
            assumptions.append(
                "Converted to TND at a configurable approximate rate "
                "(INSIGHTS_FX_EUR_TND / INSIGHTS_FX_USD_TND)."
            )
        if len(figures) == 1:
            low = likely = high = float(figures[0])
            confidence = "medium" if foreign else "high"
        else:
            low, high = float(figures[0]), float(figures[-1])
            likely = float(statistics.median(figures))
            confidence = "medium"
            assumptions.append(
                f"{len(figures)} distinct figures found: they may be separate lots or "
                "conflicting statements. The range spans them; they are not summed."
            )
        return BudgetEstimate(
            method="explicit", min=low, likely=likely, max=high,
            assumptions=assumptions, confidence=confidence, sources=[tender_source],
        )

    # 2. Comparable past projects / awards.
    values = sorted(_plausible(comparable_values_tnd))
    if values:
        n = len(values)
        if n == 1:
            likely = values[0]
            low = likely * SINGLE_COMPARABLE_MIN_FACTOR
            high = likely * SINGLE_COMPARABLE_MAX_FACTOR
            note = "Only one comparable: range widened by -30% / +50%."
            confidence = "low"
        elif n < 5:
            low, high = values[0], values[-1]
            likely = float(statistics.median(values))
            note = f"Range = min to max of {n} comparables, likely = median."
            confidence = "low" if n == 2 else "medium"
        else:
            # "inclusive" keeps every cut inside the observed range; the default
            # "exclusive" method extrapolates past the largest comparable.
            cuts = statistics.quantiles(values, n=10, method="inclusive")
            low, high = cuts[0], cuts[-1]
            likely = float(statistics.median(values))
            note = f"Range = P10 to P90 of {n} comparables, likely = median."
            confidence = "medium"
        return BudgetEstimate(
            method="comparables",
            min=round(low), likely=round(likely), max=round(high),
            assumptions=[note, "Comparables are not scaled for scope or year."],
            confidence=confidence,
            sources=_dedupe(list(comparable_sources)),
        )

    # 3. Effort-based estimate.
    if person_days is not None and person_days > 0:
        rate = daily_rate if daily_rate and daily_rate > 0 else daily_rate_tnd()
        likely = person_days * rate
        return BudgetEstimate(
            method="effort",
            min=round(likely * EFFORT_MIN_FACTOR),
            likely=round(likely),
            max=round(likely * EFFORT_MAX_FACTOR),
            assumptions=[
                f"{person_days:g} person-days x {rate:g} TND/day.",
                f"Range = {EFFORT_MIN_FACTOR:g}x to {EFFORT_MAX_FACTOR:g}x (overruns are likelier than underruns).",
                "Excludes licences, hosting, travel and support contracts.",
            ],
            confidence="low",
            sources=[],
        )

    # 4. Nothing supports a number.
    return BudgetEstimate(
        method="none",
        assumptions=[
            "No budget figure in the tender text, no comparable project and no "
            "effort estimate available. No range is given rather than inventing one."
        ],
        confidence="low",
        sources=[],
    )


# --------------------------------------------------------------------------
# Workload -> effort budget
# --------------------------------------------------------------------------


def total_person_days(workload: Workload) -> float:
    """Sum of the days of every task. The code adds, the LLM never does."""
    return round(sum(t.days for t in workload.tasks), 2)


def weighted_days(workload: Workload) -> float:
    """Days weighted by profile: a senior day costs more than a junior day."""
    return round(sum(t.days * PROFILE_MULTIPLIERS[t.profile] for t in workload.tasks), 2)


def workload_to_budget(
    workload: Workload, daily_rate: float | None = None
) -> BudgetEstimate:
    """Effort-based budget from an LLM workload, via the normal rules.

    Only the effort method is used here. Choosing between explicit,
    comparables and effort is the runner's job (resolve_budget priority).
    """
    days = total_person_days(workload)
    weighted = weighted_days(workload)
    estimate = resolve_budget(person_days=weighted, daily_rate=daily_rate)
    breakdown = [
        f"{t.name}: {t.days:g} d, profile {t.profile} x{PROFILE_MULTIPLIERS[t.profile]:g} ({t.reason})"
        for t in workload.tasks
    ]
    extra = [
        f"{days:g} working days = {weighted:g} standard-equivalent days after profile weighting.",
        "Workload: " + "; ".join(breakdown),
    ]
    return estimate.model_copy(update={"assumptions": estimate.assumptions + extra})


def check_against_reference(
    effort_likely_tnd: float,
    reference_values_tnd: Sequence[float],
    tolerance: float = SANITY_TOLERANCE,
) -> dict:
    """Is the effort estimate far from comparables or past projects?

    This is what lets the agent notice "70 days x 400 = 28 000 but past
    projects were 90 000, something is off" and revise. The code computes the
    verdict; the LLM only decides what to do about it.
    """
    refs = _plausible(reference_values_tnd)
    if not refs or effort_likely_tnd <= 0:
        return {"checked": False, "suspicious": False, "ratio": None, "reference": None}
    reference = float(statistics.median(refs))
    ratio = reference / effort_likely_tnd
    return {
        "checked": True,
        "suspicious": ratio > tolerance or ratio < 1 / tolerance,
        "ratio": round(ratio, 2),   # >1 means the estimate is below the reference
        "reference": round(reference),
    }