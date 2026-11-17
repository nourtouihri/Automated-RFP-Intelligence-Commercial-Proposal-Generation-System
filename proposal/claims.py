"""Hallucination check: claims in model prose that the step's inputs do not contain.

The model may only rephrase what it was given. This extracts what looks like a
fact (numbers, percentages, years, money, ISO and certification claims, words
like "delivered" and "certified", proper names) from each prose field and
reports every one that does not appear in the step's inputs. It is a check, not
a fix: each hit becomes a bid warning for the sales manager. Matching is
textual, so a fair paraphrase that changes the form of a fact ("one day" as
"24 hours") is reported too.

Names are the noisy part, so only three kinds are checked: CamelCase and
ACRONYM tokens (absent from the inputs), and runs of two or more capitalised
words in a sentence, when none of the words is in any input. A single
capitalised word is not checked, so an invented one-word client is missed.
Callers pass running text only (see compose._CHECKED); titles and labels are
out of scope. Numbers are compared as values, not by what they count.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import Decimal

_DASH = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_NUM = r"\d{1,3}(?:[,  ]\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?"
_NUM_CLAIM = re.compile(rf"(?<![\w.,])(?:{_NUM})(?!\w)")
_NUM_SUPPORT = re.compile(rf"(?<![\w.,-])(?:{_NUM})(?!\w)")
_PERCENT = re.compile(rf"(?<![\w.,])(?:{_NUM})\s?(?:%|percent\b|per cent\b|pct\b)", re.I)
_MONEY = re.compile(
    rf"[€$£]\s?(?:{_NUM})|(?<![\w.,])(?:{_NUM})\s?(?:(?:million|billion|m|k)\s)?"
    r"(?:EUR|USD|GBP|TND|AED|euros?|dollars?|pounds?|dinars?|dirhams?)\b", re.I)
_ISO = re.compile(r"\bISO(?:/IEC)?[ -]?(\d{3,5})\b")
_STATUS = re.compile(r"\b(delivered|certified|certifications?|accredited|accreditation|"
                     r"awarded|award-winning)\b|\bISO\b", re.I)
_STEM = {"delivered": r"\bdelivered\b", "certified": r"\bcertif\w*", "certification": r"\bcertif\w*",
         "certifications": r"\bcertif\w*", "accredited": r"\baccredit\w*",
         "accreditation": r"\baccredit\w*", "awarded": r"\baward\w*",
         "award-winning": r"\baward\w*", "iso": r"\biso\b"}
_ONES = dict(zip("one two three four five six seven eight nine".split(), range(1, 10)))
_UNITS = dict(zip("two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                  "fifteen sixteen seventeen eighteen nineteen".split(), range(2, 20)))
_TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
_WORDNUM = re.compile(rf"\b(?:({'|'.join(_TENS)})(?:[- ]({'|'.join(_ONES)}))?|({'|'.join(_UNITS)}))\b",
                      re.I)
_TOKEN = re.compile(r"[^\W_]+")


def _canon(token: str) -> str:
    token = token.replace(" ", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", token):
        token = token.replace(",", "")
    return format(Decimal(token.replace(",", ".")).normalize(), "f")


def _word_value(m: re.Match) -> str:
    tens, ones, unit = m.groups()
    return str(_UNITS[unit.lower()] if unit else _TENS[tens.lower()] + (_ONES[ones.lower()] if ones else 0))


def extract(text: str) -> list[dict]:
    """Claims in text as {kind, claim, key}; key is what support must contain."""
    t = text.translate(_DASH)
    out, taken = [], []

    def add(kind, claim, key, span):
        taken.append(span)
        out.append({"kind": kind, "claim": claim, "key": key})

    def free(span):
        return not any(s < span[1] and span[0] < e for s, e in taken)

    for m in _ISO.finditer(t):
        add("certification", m.group(0), ("c", m.group(1)), m.span())
    for m in _MONEY.finditer(t):
        if free(m.span()):
            add("money", m.group(0), ("n", _canon(_NUM_CLAIM.search(m.group(0)).group(0))), m.span())
    for m in _PERCENT.finditer(t):
        if free(m.span()):
            add("percentage", m.group(0), ("n", _canon(_NUM_CLAIM.search(m.group(0)).group(0))), m.span())
    for m in _STATUS.finditer(t):
        if free(m.span()):
            word = m.group(0).lower()
            add("status", word, ("s", word), m.span())
    for m in _NUM_CLAIM.finditer(t):
        if free(m.span()):
            kind = "year" if re.fullmatch(r"(?:19|20)\d{2}", m.group(0)) else "number"
            add(kind, m.group(0), ("n", _canon(m.group(0))), m.span())
    for m in _WORDNUM.finditer(t):
        if free(m.span()):
            add("number", m.group(0), ("n", _word_value(m)), m.span())

    tokens = list(_TOKEN.finditer(t))

    def starts_sentence(i):
        return i == 0 or re.search(r"[.!?:;\n(\"“]", t[tokens[i - 1].end():tokens[i].start()])

    long_words = [m.group(0) for i, m in enumerate(tokens)
                  if m.group(0).isalpha() and len(m.group(0)) >= 4 and not starts_sentence(i)]
    title_case = len(long_words) >= 4 and sum(w[0].isupper() for w in long_words) / len(long_words) >= 0.6
    run, last = [], -2

    def flush():
        if len(run) >= 2:
            out.append({"kind": "name", "claim": t[run[0].start():run[-1].end()],
                        "key": ("w", [x.group(0).lower() for x in run], "any")})
        run.clear()

    for i, m in enumerate(tokens):
        tok = m.group(0)
        if not free(m.span()) or tok.isdigit():
            flush()
            continue
        shaped = tok[1:] != tok[1:].lower() or (any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok))
        if tok[0].isupper() and not shaped and not starts_sentence(i) and not title_case:
            if run and not (last == i - 1 and t[tokens[last].end():m.start()] == " "):
                flush()
            run.append(m)
            last = i
            continue
        flush()
        if shaped:
            out.append({"kind": "name", "claim": tok, "key": ("w", [tok.lower()], "all")})
    flush()
    return out


class _Support:
    def __init__(self, text: str):
        t = text.translate(_DASH)
        self.lower = t.lower()
        self.words = {m.group(0).lower() for m in _TOKEN.finditer(t)}
        self.nums = {_canon(m.group(0)) for m in _NUM_SUPPORT.finditer(t)}
        self.nums |= {_word_value(m) for m in _WORDNUM.finditer(t)}

    def has(self, key) -> bool:
        kind, value, *mode = key
        if kind == "n":
            return value in self.nums
        if kind == "c":
            return re.search(rf"\biso(?:/iec)?[ -]?{value}\b", self.lower) is not None
        if kind == "s":
            return re.search(_STEM[value], self.lower) is not None
        found = [w in self.words or w.rstrip("s") in self.words or f"{w}s" in self.words
                 for w in value]
        return any(found) if mode == ["any"] else all(found)


def unsupported(fields: dict[str, str], support: str, ignore: Iterable[str] = ()) -> list[dict]:
    """Claims in the given {field: text} that the support text does not contain,
    once per field and claim, as {field, kind, claim}. Strings in `ignore` (the
    ids of the assets the text cites) are removed before looking for claims."""
    s, out, seen = _Support(support), [], set()
    skip = [i.translate(_DASH) for i in ignore if i]
    for field, text in fields.items():
        text = (text or "").translate(_DASH)
        for i in skip:
            text = text.replace(i, " ")
        for c in extract(text):
            ident = (field, c["kind"], c["claim"].lower())
            if ident not in seen and not s.has(c["key"]):
                seen.add(ident)
                out.append({"field": field, "kind": c["kind"], "claim": c["claim"]})
    return out


def support_text(rules: str, task: str, payload: dict, records: dict) -> str:
    """What the model was shown: its rules, its task (size limits removed, they are
    not facts), its input payload, and the source records of the assets in it."""
    assets = payload.get("ASSETS") or ([payload["ASSET"]] if "ASSET" in payload else [])
    sources = [json.dumps(records[a["id"]], ensure_ascii=False)
               for a in assets if a.get("id") in records]
    return "\n".join([rules, re.sub(r"\d+", " ", task), json.dumps(payload, ensure_ascii=False),
                      *sources])
