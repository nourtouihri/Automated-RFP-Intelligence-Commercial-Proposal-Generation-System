"""
Tender normalization: sanitize → validate → dedup → extract requirements → tag sector.

Boundary rules implemented here (phase-2 §4.2 matrix):

- Accept / accept-with-flags / reject are the only outcomes; nothing raises a
  raw 500. Rejects are ``ApiError`` and are rendered through the shared
  envelope in ``shared/errors.py``.
- Untrusted text is sanitized (HTML unwrapped, invisible/format characters
  dropped, NBSP folded to space) *before* it is validated, stored, or handed
  to an LLM. Sanitization is reported via quality warnings, never silent.
- Deadlines are parsed against an explicit allowlist; compact (20261120) and
  week-date (2026-W47-5) forms are rejected.
- Missing optional inputs (deadline / raw_text / requirements) degrade to a
  low-completeness ``incomplete`` record instead of rejecting the ingest.
- Validation and dedup run before any paid call; a duplicate ingest returns
  the stored row without touching the LLM (n8n fires triggers more than once).
- LLM failures (transport, auth/config, garbage output) fall back to
  deterministic extraction with an ``llm_unavailable`` warning.
"""

import json
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from html import unescape as _html_unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from shared.dedup import canonical_key, canonical_text, title_similarity
from shared.errors import ApiError, ErrorCode, request_id_var
from shared.schemas import CAPABILITY_TAXONOMY, DataQuality, Tender
from shared import store
from detection.llm import llm_call

logger = logging.getLogger(__name__)

# Historical name for validation rejects (phase-2 §T2 line: "a valid Tender or
# a ValidationError"). It is the same object as the shared envelope type, kept
# as an import-compatible alias for scripts/tests that caught the old name.
ValidationError = ApiError

RAW_TEXT_MAX_CHARS = 20_000
TITLE_MAX_CHARS = 400
ISSUER_MAX_CHARS = 200
REQUIREMENT_MAX_CHARS = 1_000
REQUIREMENTS_MAX_ITEMS = 100
NOTICE_TEXT_MAX_CHARS = 100
LINK_MAX_CHARS = 2_000
LINKS_MAX_ITEMS = 20
NEAR_DUPLICATE_RATIO = 0.90
TEXT_TOO_SHORT_CHARS = 40
TEXT_ALNUM_RATIO_MIN = 0.30

# Warnings that describe the *incoming payload* but may be contradicted by the
# stored row during a merge-on-update. They are dropped and recomputed against
# the merged record so a sparse re-trigger does not keep stale "missing" flags.
_MERGE_DERIVED_WARNINGS = frozenset(
    {
        "no_raw_text",
        "missing_deadline",
        "text_too_short",
        "text_mostly_symbols",
        "deadline_in_past",
    }
)

# Input-completeness weights, summing to 1.0. Sector is deliberately excluded:
# it is derived (keyphrase or LLM), not supplied, and counting it would let a
# title+issuer-only record reach 0.40 — the matrix requires *below* 0.4 for
# that case ("Only title + issuer -> completeness below 0.4"). A full payload
# therefore scores exactly 1.0.
COMPLETENESS_WEIGHTS = {
    "title": 0.15,
    "issuer": 0.15,
    "raw_text": 0.30,
    "requirements": 0.25,
    "deadline": 0.15,
}

# Known ingest fields; anything else is ignored but reported (matrix row:
# "Unknown extra fields -> ignored, listed in warnings").
KNOWN_FIELDS = frozenset(
    {"id", "title", "issuer", "issuer_country", "notice_type", "published_at", "links", "sector",
     "requirements", "deadline", "raw_text", "source", "detected_at"}
)

# Keyphrases per service line, drawn from the tools OliveSoft publishes against
# each line. Declaration order here is not the tie-break authority — CAPABILITY_TAXONOMY
# is, and the drift guard below keeps the two key sets identical.
SECTOR_KEYPHRASES: dict[str, list[str]] = {
    "Data Integration": [
        "mulesoft", "talend", "ssis", "boomi", "workato", "n8n",
        "data integration", "integration platform", "api integration",
        "system integration", "erp integration", "crm integration",
        "etl", "elt", "esb", "middleware",
    ],
    "AI Development": [
        "artificial intelligence", "machine learning", "deep learning", "neural network",
        "natural language processing", "nlp", "computer vision", "generative ai",
        "large language model", "llm", "retrieval augmented generation", "rag",
        "chatbot", "conversational ai", "predictive analytics", "predictive model",
        "forecasting", "demand prediction", "anomaly detection", "text classification",
        "text mining", "mlops",
    ],
    "BI & Dashboarding": [
        "power bi", "tableau", "qlik", "qlik sense", "looker studio", "business intelligence",
        "dashboard", "dashboards", "semantic model", "data visualization",
        "data visualisation", "kpi", "reporting layer",
    ],
    "Salesforce Ecosystem": [
        "salesforce", "sales cloud", "service cloud", "marketing cloud", "commerce cloud",
        "crm analytics", "crm", "customer relationship management",
    ],
    "Data Platform": [
        "snowflake", "databricks", "kafka", "bigquery", "azure data", "azure synapse",
        "gcp", "google cloud", "data platform", "data warehouse", "data lake",
        "lakehouse", "data lakehouse", "cloud data", "analytics platform",
    ],
}

if set(SECTOR_KEYPHRASES) != set(CAPABILITY_TAXONOMY):
    _missing = sorted(set(CAPABILITY_TAXONOMY) - set(SECTOR_KEYPHRASES))
    _extra = sorted(set(SECTOR_KEYPHRASES) - set(CAPABILITY_TAXONOMY))
    raise RuntimeError(
        "SECTOR_KEYPHRASES and CAPABILITY_TAXONOMY have drifted apart. "
        f"No keyphrases for: {_missing}. Keyphrases for unknown categories: {_extra}."
    )


def _add_warning(warnings: list[str], code: str) -> None:
    """Append a warning code once, preserving first-seen order."""
    if code not in warnings:
        warnings.append(code)


def _log_extra() -> dict:
    """Attach the request id to log records when one is bound."""
    rid = request_id_var.get()
    return {"request_id": rid} if rid else {}


# --------------------------------------------------------------------------
# Sanitizer (untrusted text boundary)
# --------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """HTML -> text; <script>/<style> bodies are dropped, block tags break lines."""

    _SKIP_TAGS = frozenset({"script", "style"})
    _BLOCK_TAGS = frozenset({"br", "p", "div", "li", "tr", "table", "section"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):  # noqa: D102 (stdlib hook)
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):  # noqa: D102 (stdlib hook)
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data):  # noqa: D102 (stdlib hook)
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


# Characters that must never survive the boundary even if a future Unicode
# version reclassifies their category (Trojan Source / ATR invisible set).
_EXPLICIT_INVISIBLE = frozenset(
    {0x00AD, 0x180E, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF}
)


# A real tag is `<name ...>` / `</name>` / `<name/>`: a leading letter, then
# either the closing `>` or whitespace-separated attributes. This intentionally
# does NOT match `<contact@acme.tn>` or `Budget < 5000`, so prose that merely
# contains angle brackets is not run through the HTML parser (which would
# silently delete the email/placeholder and mangle the comparison).
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*)?/?>")

# ASCII whitespace only. NBSP and friends are deliberately excluded: they are
# folded to a real space by the sanitizer, and that fold is a *sanitization*
# event we must keep reporting, not housekeeping we normalize away.
_ASCII_WS_RE = re.compile(r"[ \t\n\r\f\v]+")


def _html_to_text(value: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(value)
        parser.close()
        return parser.text()
    except Exception:
        # Sanitization must never be the reason an ingest fails.
        logger.warning("HTML sanitization failed; falling back to tag stripping")
        return re.sub(r"<[^>]{0,1000}>", " ", value)


def _canonical_whitespace(value: str) -> str:
    """Collapse ASCII whitespace runs so whitespace-only edits compare equal."""
    return " ".join(part for part in _ASCII_WS_RE.split(value) if part)


def _strip_invisible_chars(value: str) -> str:
    kept: list[str] = []
    for char in value:
        if char in "\n\t":
            kept.append(char)
            continue
        codepoint = ord(char)
        if codepoint in _EXPLICIT_INVISIBLE or 0xE0000 <= codepoint <= 0xE007F:
            continue
        category = unicodedata.category(char)
        if category in ("Cf", "Cc"):  # bidi/format controls, NUL & friends
            continue
        if category == "Zs":  # NBSP family -> plain space (French typography)
            kept.append(" ")
            continue
        kept.append(char)
    return "".join(kept)


def clean_untrusted_text(value: str) -> tuple[str, bool]:
    """Return ``(cleaned, changed)`` for any inbound string; total, never raises.

    Order matters (canonicalize before validate — OWASP): unwrap HTML/entities,
    NFC-normalize, drop invisible/control characters, fold exotic spaces,
    collapse whitespace runs. Legitimate Arabic/French letters, harakat and
    ordinary punctuation (including em dashes) are never touched.

    ``changed`` reports *semantic* sanitization (HTML unwrapped, entities
    decoded, invisible/control characters dropped, NBSP folded, NFC). Pure
    whitespace normalization — CRLF, double spaces, surrounding padding — is
    housekeeping and stays silent, so a Windows/spreadsheet payload does not
    raise ``sanitized_chars`` on every ordinary ingest.
    """
    original = value
    if _HTML_TAG_RE.search(value):
        value = _html_to_text(value)
    elif "&" in value:
        # Entities with no markup (e.g. "AT&amp;T"): decode character
        # references only -- never infer tag semantics from an ampersand.
        value = _html_unescape(value)
    value = unicodedata.normalize("NFC", value)
    value = _strip_invisible_chars(value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)  # at most one blank line
    value = value.strip()
    changed = _canonical_whitespace(value) != _canonical_whitespace(original)
    return value, changed


# --------------------------------------------------------------------------
# Deadline parsing (explicit allowlist; rejects compact/week-date forms)
# --------------------------------------------------------------------------

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
_DAY_FIRST_RE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
_DEADLINE_HINT = "Expected YYYY-MM-DD, an ISO-8601 datetime, or DD/MM/YYYY."


def parse_deadline(value) -> tuple[date | None, list[str]]:
    """Parse a deadline against an explicit allowlist.

    The regex gate runs BEFORE ``fromisoformat`` on purpose: Python 3.11+
    fromisoformat also accepts compact (``20261120``) and week-date
    (``2026-W47-5``) forms, which must be rejected so a plausible-but-wrong
    date never silently wins. DD/MM/YYYY is parsed day-first and flagged,
    because 01/02/2026 is ambiguous and the feed is francophone.
    """
    warnings: list[str] = []
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, ["missing_deadline"]
    if isinstance(value, datetime):
        return value.date(), warnings
    if isinstance(value, date):
        return value, warnings
    if not isinstance(value, str):
        raise ApiError(
            ErrorCode.TENDER_INVALID_DEADLINE,
            f"Invalid deadline date format: '{value}'. {_DEADLINE_HINT}",
            field="deadline",
        )

    raw = value.strip()
    try:
        if _ISO_DATE_RE.match(raw):
            return date.fromisoformat(raw), warnings
        if _ISO_DATETIME_RE.match(raw):
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date(), warnings
        day_first = _DAY_FIRST_RE.match(raw)
        if day_first:
            day, month, year = (int(group) for group in day_first.groups())
            return date(year, month, day), ["deadline_day_first"]
    except ValueError:
        pass
    raise ApiError(
        ErrorCode.TENDER_INVALID_DEADLINE,
        f"Invalid deadline date format: '{value}'. {_DEADLINE_HINT}",
        field="deadline",
    )


# --------------------------------------------------------------------------
# Payload preparation (validation + sanitization, no I/O, no LLM)
# --------------------------------------------------------------------------

@dataclass
class PreparedPayload:
    """Validated, sanitized ingest payload ready for dedup/extraction."""

    title: str
    issuer: str
    raw_text: str
    deadline: date | None
    supplied_requirements: list[str] | None
    source: str | None
    detected_at: datetime | None
    explicit_id: str | None
    warnings: list[str]
    missing_fields: list[str]
    is_expired: bool
    issuer_country: str | None = None
    notice_type: str | None = None
    published_at: date | None = None
    links: list[str] = field(default_factory=list)


def _clean_required_text(data: dict, field: str, warnings: list[str], max_chars: int) -> str:
    value = data.get(field)
    if value is None:
        raise ApiError(
            ErrorCode.TENDER_INVALID_FIELD,
            f"Missing required field: {field}",
            field=field,
        )
    if not isinstance(value, str):
        raise ApiError(
            ErrorCode.TENDER_INVALID_FIELD,
            f"{field} must be a string",
            field=field,
        )
    cleaned, changed = clean_untrusted_text(value)
    if changed:
        _add_warning(warnings, "sanitized_chars")
    if not cleaned:
        raise ApiError(
            ErrorCode.TENDER_INVALID_FIELD,
            f"Missing required field: {field}",
            field=field,
        )
    if len(cleaned) > max_chars:
        raise ApiError(
            ErrorCode.TENDER_INVALID_FIELD,
            f"{field} exceeds {max_chars} character cap ({len(cleaned)} chars)",
            field=field,
        )
    return cleaned


def _clean_supplied_requirements(value, warnings: list[str]) -> list[str] | None:
    """Validate an inbound requirements list. Supplied data is rejected, not repaired."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ApiError(
            ErrorCode.TENDER_INVALID_REQUIREMENTS,
            "requirements must be a list of strings",
            field="requirements",
        )
    if len(value) > REQUIREMENTS_MAX_ITEMS:
        raise ApiError(
            ErrorCode.TENDER_INVALID_REQUIREMENTS,
            f"requirements exceeds {REQUIREMENTS_MAX_ITEMS} item cap ({len(value)} items)",
            field="requirements",
        )
    cleaned_items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ApiError(
                ErrorCode.TENDER_INVALID_REQUIREMENTS,
                "each requirement must be a non-empty string",
                field="requirements",
            )
        cleaned, changed = clean_untrusted_text(item)
        if changed:
            _add_warning(warnings, "sanitized_chars")
        if not cleaned:
            raise ApiError(
                ErrorCode.TENDER_INVALID_REQUIREMENTS,
                "each requirement must be a non-empty string",
                field="requirements",
            )
        if len(cleaned) > REQUIREMENT_MAX_CHARS:
            raise ApiError(
                ErrorCode.TENDER_INVALID_REQUIREMENTS,
                f"each requirement must be at most {REQUIREMENT_MAX_CHARS} characters "
                f"({len(cleaned)} chars)",
                field="requirements",
            )
        cleaned_items.append(cleaned)
    return cleaned_items or None


def _clean_notice_text(data: dict, field: str, warnings: list[str]) -> str | None:
    """An optional notice string: cleaned and capped; empty or invalid reads as omitted."""
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        _add_warning(warnings, f"invalid_{field}")
        return None
    cleaned, changed = clean_untrusted_text(value)
    if changed:
        _add_warning(warnings, "sanitized_chars")
    return cleaned[:NOTICE_TEXT_MAX_CHARS] or None


def _clean_published_at(value, warnings: list[str]) -> date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return parse_deadline(value)[0]
    except ApiError:
        _add_warning(warnings, "invalid_published_at")
        return None


def _clean_links(value, warnings: list[str]) -> list[str]:
    """Flatten TED's pdfs/html maps (or take a list), keep only bounded http(s) URLs."""
    if value is None:
        return []
    if isinstance(value, dict):
        candidates = [
            url
            for group in ("pdfs", "html")
            if isinstance(value.get(group), dict)
            for url in value[group].values()
        ]
    elif isinstance(value, list):
        candidates = value
    else:
        _add_warning(warnings, "links_trimmed")
        return []
    links: list[str] = []
    for url in candidates:
        if not isinstance(url, str) or len(url) > LINK_MAX_CHARS:
            _add_warning(warnings, "links_trimmed")
            continue
        url = url.strip()
        try:
            parsed = urlsplit(url)
        except ValueError:
            parsed = None
        if parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
            _add_warning(warnings, "links_trimmed")
        elif url not in links:
            links.append(url)
    if len(links) > LINKS_MAX_ITEMS:
        _add_warning(warnings, "links_trimmed")
    return links[:LINKS_MAX_ITEMS]


def prepare_payload(data: dict) -> PreparedPayload:
    """Validate + sanitize an inbound payload. Raises ``ApiError`` on rejects.

    Deliberately free of I/O and LLM calls: everything rejected here is
    rejected before a single byte is persisted or a single token is spent.
    """
    warnings: list[str] = []
    missing_fields: list[str] = []

    unknown_fields = sorted(set(data) - KNOWN_FIELDS)
    if unknown_fields:
        _add_warning(warnings, "unknown_fields")

    title = _clean_required_text(data, "title", warnings, TITLE_MAX_CHARS)
    issuer = _clean_required_text(data, "issuer", warnings, ISSUER_MAX_CHARS)

    # raw_text is optional: a notice without body text is still a lead as long
    # as title/issuer identify it. Clean BEFORE the cap so invisible padding
    # cannot dodge (or trip) the 20 000-char limit.
    raw_value = data.get("raw_text")
    if raw_value is not None and not isinstance(raw_value, str):
        raise ApiError(
            ErrorCode.TENDER_INVALID_FIELD, "raw_text must be a string", field="raw_text"
        )
    raw_text = ""
    if raw_value is not None:
        raw_text, changed = clean_untrusted_text(raw_value)
        if changed:
            _add_warning(warnings, "sanitized_chars")
    if not raw_text:
        # Blank-after-clean text (only invisibles/HTML) is treated exactly like
        # missing text: `no_raw_text` plus a missing-fields entry.
        _add_warning(warnings, "no_raw_text")
        missing_fields.append("raw_text")
    elif len(raw_text) > RAW_TEXT_MAX_CHARS:
        raise ApiError(
            ErrorCode.RAW_TEXT_TOO_LONG,
            f"raw_text exceeds {RAW_TEXT_MAX_CHARS} character cap ({len(raw_text)} chars)",
            field="raw_text",
        )
    else:
        if len(raw_text) < TEXT_TOO_SHORT_CHARS:
            _add_warning(warnings, "text_too_short")
        alnum = sum(char.isalnum() for char in raw_text)
        if alnum / len(raw_text) < TEXT_ALNUM_RATIO_MIN:
            _add_warning(warnings, "text_mostly_symbols")

    deadline, deadline_warnings = parse_deadline(data.get("deadline"))
    for warning in deadline_warnings:
        _add_warning(warnings, warning)
    is_expired = False
    if deadline is None:
        missing_fields.append("deadline")
    elif deadline < date.today():
        is_expired = True
        _add_warning(warnings, "deadline_in_past")

    supplied_requirements = _clean_supplied_requirements(
        data.get("requirements"), warnings
    )

    source = data.get("source")
    if source is not None:
        ## SOURCE
        if not isinstance(source, str) or source not in {"TED", "SAM", "manual", "simulated_feed"}:
            raise ApiError(
                ErrorCode.TENDER_INVALID_FIELD,
                "source must be 'TED', 'SAM', 'manual', or 'simulated_feed'",
                field="source",
            )

    explicit_id = data.get("id")
    if explicit_id is not None and (
        not isinstance(explicit_id, str) or not explicit_id.strip()
    ):
        raise ApiError(
            ErrorCode.TENDER_INVALID_FIELD,
            "id must be a non-empty string when supplied",
            field="id",
        )

    detected_at = data.get("detected_at")
    if detected_at is not None:
        if isinstance(detected_at, str):
            try:
                detected_at = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ApiError(
                    ErrorCode.TENDER_INVALID_FIELD,
                    "Invalid detected_at timestamp",
                    field="detected_at",
                ) from exc
        elif not isinstance(detected_at, datetime):
            raise ApiError(
                ErrorCode.TENDER_INVALID_FIELD,
                "detected_at must be an ISO-8601 timestamp",
                field="detected_at",
            )

    return PreparedPayload(
        title=title,
        issuer=issuer,
        raw_text=raw_text,
        deadline=deadline,
        supplied_requirements=supplied_requirements,
        source=source,
        detected_at=detected_at,
        explicit_id=explicit_id.strip() if isinstance(explicit_id, str) else None,
        warnings=warnings,
        missing_fields=missing_fields,
        is_expired=is_expired,
        issuer_country=_clean_notice_text(data, "issuer_country", warnings),
        notice_type=_clean_notice_text(data, "notice_type", warnings),
        published_at=_clean_published_at(data.get("published_at"), warnings),
        links=_clean_links(data.get("links"), warnings),
    )


# --------------------------------------------------------------------------
# Sector tagging (keyphrase first, LLM only as a last resort)
# --------------------------------------------------------------------------

def tag_sector(raw_text: str, title: str) -> str:
    """
    Best-keyphrase-matching service line, or 'unknown' when nothing matches.

    Highest score wins. Ties go to whichever category comes first in
    CAPABILITY_TAXONOMY, so the result depends on the declared taxonomy order
    and not on the order keyphrases happen to be listed in.
    """
    text_lower = f"{title} {raw_text}".lower()
    scores: dict[str, int] = {}

    for category, keyphrases in SECTOR_KEYPHRASES.items():
        count = 0
        for phrase in keyphrases:
            pattern = r"\b" + re.escape(phrase) + r"\b"
            if re.search(pattern, text_lower):
                count += 1
        if count > 0:
            scores[category] = count

    if not scores:
        return "unknown"

    precedence = {category: rank for rank, category in enumerate(CAPABILITY_TAXONOMY)}
    return min(scores, key=lambda category: (-scores[category], precedence[category]))


def _normalize_sector_name(value: str) -> str:
    """Casefold/punctuation-fold a category name so 'BI and Dashboarding' matches."""
    normalized = re.sub(r"[^a-z0-9 ]+", " ", value.casefold())
    normalized = " ".join(normalized.split())
    return normalized.replace(" and ", " ")


_SECTOR_LOOKUP: dict[str, str] = {
    _normalize_sector_name(name): name for name in CAPABILITY_TAXONOMY
}


async def tag_sector_llm(raw_text: str, title: str) -> tuple[str, list[str]]:
    """Fallback LLM sector classification. Returns ``(sector, warnings)``; never raises.

    A misconfigured key (ValueError from the transport) or an unreachable
    provider degrades to ``unknown`` + ``llm_unavailable``: the matrix says
    bad key -> deterministic fallback + warning, never 500.
    """
    categories_str = "\n".join(f"- {c}" for c in CAPABILITY_TAXONOMY)
    prompt = (
        f"Classify this tender into exactly one category. Return only the category name.\n\n"
        f"Categories:\n{categories_str}\n\n"
        f"Title: {title}\nText:\n{raw_text[:3000]}"
    )
    try:
        result = (await llm_call(prompt)).strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        logger.error(
            "sector classification LLM unavailable (%s: %s); sector stays unknown",
            type(exc).__name__, exc, extra=_log_extra(),
        )
        return "unknown", ["llm_unavailable"]

    normalized = _normalize_sector_name(result)
    if normalized in _SECTOR_LOOKUP:
        return _SECTOR_LOOKUP[normalized], []
    # Providers sometimes answer with a sentence around the category; a
    # containment check can still recover it without accepting arbitrary text.
    for name in CAPABILITY_TAXONOMY:
        if name.casefold() in result.casefold():
            return name, []
    logger.warning(
        "sector classification LLM returned an unrecognized category: %r", result[:80],
        extra=_log_extra(),
    )
    return "unknown", ["llm_unavailable"]


# --------------------------------------------------------------------------
# Requirement extraction (deterministic fallback + strict LLM output handling)
# --------------------------------------------------------------------------

_REQUIREMENT_CHATTER_PREFIXES = (
    "here are", "here is", "sure,", "sure:", "of course", "certainly",
    "the requirements are",
)


def _fallback_requirements(raw_text: str) -> list[str]:
    """Deterministic sentence split — used whenever the LLM cannot deliver."""
    sentences = [
        " ".join(item.split()).strip(" -•\t")
        for item in re.split(r"(?<=[.!?;])\s+|\n+", raw_text)
    ]
    usable = [item[:300] for item in sentences if len(item) >= 12]
    return usable[:6] or ["General technical requirement compliance"]


def extract_json_payload(text: str) -> str:
    """Return the first decodable JSON array (then object) embedded in ``text``.

    A regex cannot do this correctly: ``["SSO [SAML]", "x"]`` or a quoted
    requirement containing an email breaks non-greedy ``\\[.*?\\]`` matching
    (D11). Instead we walk every opener position and let json's own parser
    find the extent of the first valid document — ``raw_decode`` stops exactly
    at its end, so trailing prose is ignored. Arrays are preferred over
    objects so a JSON envelope like ``{"reqs": [...]}`` yields the list.
    """
    decoder = json.JSONDecoder()
    for opener in "[{":
        for index, char in enumerate(text):
            if char != opener:
                continue
            try:
                _value, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                continue
            return text[index:end]
    # No embedded JSON: fall back to Markdown-fence content, then raw text.
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    return text.strip()


def _parse_llm_requirements_json(result: str) -> list[str] | None:
    try:
        parsed = json.loads(extract_json_payload(result))
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return parsed
    return None


def _salvage_requirement_lines(result: str) -> list[str]:
    """Non-JSON LLM output: one requirement per non-decorative line."""
    lines: list[str] = []
    for line in result.strip().splitlines():
        cleaned_line = line.strip(" `*-\t\r\n")
        if cleaned_line and not cleaned_line.startswith(("[", "]", "```")):
            lines.append(cleaned_line)
    return lines


def _sanitize_llm_requirements(items: list[str]) -> tuple[list[str], list[str]]:
    """Bound LLM-produced requirements: strip, dedupe, trim, cap.

    This is the "bounded repair" half of the Guardrails pattern: model output
    is repaired where it is cheaply repairable (lengths, duplicates, chatter),
    never trusted and never fatal (phase-2 §4.2 row 14).
    """
    warnings: list[str] = []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        text, _changed = clean_untrusted_text(item)
        text = " ".join(text.split())  # flatten bullet-internal newlines
        if not text or text.startswith("```"):
            continue
        if text.casefold().startswith(_REQUIREMENT_CHATTER_PREFIXES):
            continue
        if len(text) > REQUIREMENT_MAX_CHARS:
            text = text[:REQUIREMENT_MAX_CHARS].rstrip()
            _add_warning(warnings, "requirements_trimmed")
        folded = text.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        cleaned.append(text)
    if len(cleaned) > REQUIREMENTS_MAX_ITEMS:
        cleaned = cleaned[:REQUIREMENTS_MAX_ITEMS]
        _add_warning(warnings, "requirements_capped")
    return cleaned, warnings


async def extract_requirements_llm(raw_text: str) -> tuple[list[str], list[str]]:
    """Extract requirement bullets via LLM. Returns ``(requirements, warnings)``.

    Degradation tiers (each ends in a usable list, never a 500):
    strict JSON -> line-scan salvage -> deterministic sentence split. Any
    tier below strict JSON adds the ``llm_unavailable`` warning.
    """
    prompt = (
        "Extract 3-6 concise bullet-point requirements from this tender text. "
        "Return a JSON array of strings, nothing else.\n\n"
        f"Text:\n{raw_text[:5000]}"
    )
    try:
        result = await llm_call(prompt)
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        # ValueError covers transport-level config problems (bad/missing key).
        # Misconfiguration stays loud in the logs but must not masquerade as
        # a 500 on the ingest path (matrix: bad key -> fallback + warning).
        logger.error(
            "requirement extraction LLM unavailable (%s: %s); "
            "using deterministic fallback",
            type(exc).__name__, exc, extra=_log_extra(),
        )
        return _fallback_requirements(raw_text), ["llm_unavailable"]

    parsed = _parse_llm_requirements_json(result)
    if parsed is not None:
        cleaned, cleaned_warnings = _sanitize_llm_requirements(parsed)
        if cleaned:
            return cleaned, cleaned_warnings

    salvaged, salvaged_warnings = _sanitize_llm_requirements(
        _salvage_requirement_lines(result)
    )
    if salvaged:
        logger.warning(
            "requirement extraction LLM returned non-JSON output; salvaged %d line(s)",
            len(salvaged), extra=_log_extra(),
        )
        return salvaged, ["llm_unavailable"] + salvaged_warnings

    logger.warning(
        "requirement extraction LLM output unusable; using deterministic fallback",
        extra=_log_extra(),
    )
    return _fallback_requirements(raw_text), ["llm_unavailable"]


# --------------------------------------------------------------------------
# Dedup helpers
# --------------------------------------------------------------------------

def compute_dedup_hash(title: str, issuer: str) -> str:
    """Natural key for tenders — v2 canonicalization, see ``shared.dedup``."""
    return canonical_key(title, issuer)


def _find_possible_duplicate(title: str, issuer: str) -> str | None:
    """Warning-level near-duplicate flag: same canonical issuer, close title.

    Returns the id of the best candidate, or None. This never merges and
    never blocks — "Lot 2" of the same notice is a different procurement and
    must remain a separate row.
    """
    canonical_issuer = canonical_text(issuer)
    best_ratio = 0.0
    best_id: str | None = None
    for candidate in store.list_tenders():
        if canonical_text(candidate.issuer) != canonical_issuer:
            continue
        ratio = title_similarity(title, candidate.title)
        if ratio >= NEAR_DUPLICATE_RATIO and ratio > best_ratio:
            best_ratio = ratio
            best_id = candidate.id
    return best_id


def _compute_completeness(
    *, raw_text: str, requirements: list[str], deadline: date | None
) -> float:
    """Title/issuer are mandatory, so their weight is always counted."""
    score = COMPLETENESS_WEIGHTS["title"] + COMPLETENESS_WEIGHTS["issuer"]
    if raw_text:
        score += COMPLETENESS_WEIGHTS["raw_text"]
    if requirements:
        score += COMPLETENESS_WEIGHTS["requirements"]
    if deadline is not None:
        score += COMPLETENESS_WEIGHTS["deadline"]
    return round(score, 2)


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

async def normalize_tender(data: dict) -> tuple[Tender, bool]:
    """
    Executes tender ingestion and normalization pipeline.

    Returns:
        tuple[Tender, is_existing]: Tender model and a boolean indicating whether a duplicate
        was retrieved from store without re-processing.
    """
    prepared = prepare_payload(data)
    title = prepared.title
    issuer = prepared.issuer
    warnings = list(prepared.warnings)
    dedup_hash = compute_dedup_hash(title, issuer)

    explicit_id = prepared.explicit_id
    existing_by_id = store.get_tender(explicit_id) if explicit_id else None
    existing_by_hash = store.find_by_hash(dedup_hash)
    if (
        existing_by_id is not None
        and existing_by_hash is not None
        and existing_by_id.id != existing_by_hash.id
    ):
        raise ApiError(
            ErrorCode.TENDER_INVALID_FIELD,
            "Tender id and title/issuer identify different existing records",
            field="id",
        )
    existing = existing_by_id or existing_by_hash

    # ------------------------------------------------------------------
    # Merge-on-update: a re-trigger that omits optional fields (the common
    # n8n / sheet-re-read shape) must never downgrade a stored record. Fill
    # every gap from the row we already hold *before* deciding what changed,
    # so a sparse payload cannot wipe raw_text/requirements, flip the status
    # to `incomplete`, or invalidate the derived research.
    # ------------------------------------------------------------------
    raw_text = prepared.raw_text or (existing.raw_text if existing else "")
    deadline = prepared.deadline if prepared.deadline is not None else (
        existing.deadline if existing else None
    )
    source = prepared.source or (existing.source if existing else "manual")
    issuer_country = prepared.issuer_country or (existing.issuer_country if existing else None)
    notice_type = prepared.notice_type or (existing.notice_type if existing else None)
    published_at = prepared.published_at or (existing.published_at if existing else None)
    links = prepared.links or (list(existing.links) if existing else [])
    supplied_requirements = prepared.supplied_requirements

    unchanged = existing is not None and all(
        (
            existing.title == title,
            existing.issuer == issuer,
            existing.deadline == deadline,
            existing.raw_text == raw_text,
            existing.source == source,
            existing.issuer_country == issuer_country,
            existing.notice_type == notice_type,
            existing.published_at == published_at,
            existing.links == links,
            supplied_requirements in (None, [])
            or existing.requirements == supplied_requirements,
        )
    )
    if unchanged:
        # Duplicate ingest (n8n retries, sheet re-reads): return the stored
        # record without re-spending LLM budget or touching research.
        assert existing is not None  # narrowed by `unchanged`
        return existing, True

    if existing is not None:
        # Recompute the derived quality report against the *merged* record.
        # ``prepared.missing_fields``/``prepared.warnings`` describe only this
        # payload, which may have omitted fields the stored row still has.
        missing_fields = []
        if not raw_text:
            missing_fields.append("raw_text")
        if deadline is None:
            missing_fields.append("deadline")
        warnings = [w for w in prepared.warnings if w not in _MERGE_DERIVED_WARNINGS]
        if not raw_text:
            _add_warning(warnings, "no_raw_text")
        else:
            if len(raw_text) < TEXT_TOO_SHORT_CHARS:
                _add_warning(warnings, "text_too_short")
            alnum = sum(char.isalnum() for char in raw_text)
            if alnum / len(raw_text) < TEXT_ALNUM_RATIO_MIN:
                _add_warning(warnings, "text_mostly_symbols")
        if deadline is None:
            _add_warning(warnings, "missing_deadline")
        elif deadline < date.today():
            _add_warning(warnings, "deadline_in_past")
        is_expired = deadline is not None and deadline < date.today()
    else:
        missing_fields = list(prepared.missing_fields)
        is_expired = prepared.is_expired

    # The stored row's text and title are the same inputs the extraction and
    # tagging already ran against, so reuse their results instead of paying for
    # the LLM again on a cosmetic variant or a deadline-only re-announcement.
    text_unchanged = (
        existing is not None
        and existing.raw_text == raw_text
        and existing.title == title
    )

    requirements = list(supplied_requirements) if supplied_requirements else []
    if not requirements and raw_text:
        if existing is not None and existing.raw_text == raw_text and existing.requirements:
            requirements = list(existing.requirements)
        else:
            # No raw_text means nothing to extract from — and the matrix is
            # explicit that a title+issuer-only record must not reach the LLM.
            requirements, llm_warnings = await extract_requirements_llm(raw_text)
            for warning in llm_warnings:
                _add_warning(warnings, warning)

    if text_unchanged and existing.sector:
        sector = existing.sector
    else:
        sector = tag_sector(raw_text, title)
        if sector == "unknown" and raw_text:
            sector, llm_warnings = await tag_sector_llm(raw_text, title)
            for warning in llm_warnings:
                _add_warning(warnings, warning)

    if existing is None:
        duplicate_of = _find_possible_duplicate(title, issuer)
        if duplicate_of is not None:
            warnings.append(f"possible_duplicate_of:{duplicate_of}")

    if prepared.detected_at is not None:
        detected_at = prepared.detected_at
    elif existing is not None:
        detected_at = existing.detected_at
    else:
        detected_at = datetime.now(timezone.utc)

    completeness = _compute_completeness(
        raw_text=raw_text, requirements=requirements, deadline=deadline
    )
    # `incomplete` tells downstream (and n8n) this record was accepted with
    # gaps; it is not an error state. Only a brand-new row derives it here: an
    # existing row keeps the lifecycle state it was advanced to, so an n8n
    # re-trigger (or a material revision) cannot reset `processed`/`archived`
    # back to `new`. The one transition allowed from this path is leaving
    # `incomplete` once the merged record is complete — a repair ingest that
    # fills a gap upgrades the record without a full re-run.
    derived_status = "incomplete" if (missing_fields or completeness < 0.4) else "new"
    if existing is None:
        status = derived_status
    else:
        status = existing.status
        if status == "incomplete" and derived_status == "new":
            status = "new"

    # `is_existing` means "no new row": the natural key already identified a
    # tender. A re-announcement with new scope still refreshes the stored row
    # (a new deadline must take effect) but stays the same tender.
    is_existing = existing is not None

    tender = Tender(
        id=existing.id if existing else (explicit_id or str(uuid.uuid4())),
        title=title,
        issuer=issuer,
        sector=sector,
        requirements=requirements,
        deadline=deadline,
        raw_text=raw_text,
        source=source,
        detected_at=detected_at,
        status=status,
        issuer_country=issuer_country,
        notice_type=notice_type,
        published_at=published_at,
        links=links,
        quality=DataQuality(
            completeness=completeness,
            missing_fields=missing_fields,
            warnings=warnings,
            is_expired=is_expired,
        ),
    )

    store.save_tender(tender, dedup_hash)
    logger.info(
        "ingest outcome=%s tender_id=%s warnings=%s completeness=%.2f",
        "updated" if is_existing else "created", tender.id,
        ",".join(warnings) or "-", completeness,
        extra=_log_extra(),
    )
    if is_existing:
        assert existing is not None  # narrowed by `is_existing`
        # Invalidate derived research only when its actual inputs changed.
        # Deadline/raw_text-only edits (the re-announcement case) refresh the
        # row without forcing a full research re-run on every schedule poll.
        research_inputs_changed = (
            existing.issuer != issuer
            or existing.title != title
            or existing.requirements != requirements
            or existing.sector != sector
        )
        if research_inputs_changed:
            store.delete_research(tender.id)
    return tender, is_existing
