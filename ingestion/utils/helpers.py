from datetime import datetime, timedelta, date
from typing import Any
import os
import re
from dotenv import load_dotenv
from detection.normalize import clean_untrusted_text

def source_limit(source: str, default: int = 30) -> int:
    """Per-source fetch limit from ``INGEST_LIMITS``.

    ``INGEST_LIMITS`` is comma-separated and follows the same positional order
    as ``INGEST_SOURCES`` (e.g. ``INGEST_SOURCES=TED,SAM`` +
    ``INGEST_LIMITS=15,30`` fetches 15 notices per TED page and 30 per SAM
    page). Falls back to ``default`` when the source is missing or its limit
    is not a positive integer.
    """
    load_dotenv()
    sources = (os.getenv("INGEST_SOURCES") or "").split(",")
    limits = (os.getenv("INGEST_LIMITS") or "").split(",")
    for i, entry in enumerate(sources):
        if entry.strip().upper() == source and i < len(limits):
            raw = limits[i].strip()
            if raw.isdigit() and int(raw) > 0:
                return int(raw)
    return default

def format_TED_date(months_in_future=6):
    # now + 6 months
    future_date = datetime.now() + timedelta(days=30*6)

    # Format as YYYYMMDD (for example: 20270101)
    return future_date.strftime("%Y%m%d")

def only_english(value: Any) -> Any:
    """Keep just the English entry of a language-keyed mapping, keyed as ``eng``."""
    if not isinstance(value, dict):
        return value
    for key, entry in value.items():
        if key.lower() == "eng":
            return {"eng": entry}
    return {}

def english_text(value: Any) -> str:
    """English string of a language-keyed mapping (first item if it is a list)."""
    if not isinstance(value, dict):
        return ""
    eng = value.get("eng")
    if isinstance(eng, list):
        return str(eng[0]) if eng else ""
    if isinstance(eng, str):
        return eng
    return ""

def parse_date(value: str | None) -> date:
    """Parse a TED date (``YYYY-MM-DD`` prefix of an ISO-8601 value)."""
    if not value:
        return date.today()
    return date.fromisoformat(value[:10])

def fetch_description(*desc:str):
    """This returns the value of the none-null none-empty description
    There are 4 types of description, but you can't determine which one would be empty.
    One would be empty while the other isn't. There might be 2 that are none-empty.
    They could all be empty.

    This methods returns only one none-enmpty field.
    """
    for value in desc:
        if value is not None and value.strip():
            return value
    return ""

def split_description(desc: str):
    """
    This function splits description (paragraph) into list of sentences
    It returns a list whose elements are sentences of the description
    """
    if not desc or not desc.strip():
        return []
    # Split after sentence-ending punctuation followed by whitespace and a
    # new sentence start, while avoiding splits triggered by common
    # abbreviations (e.g. "i.a. in connection", "cf. DFØ's ...").
    parts = re.split(
        r"(?<=[.!?])(?<!\bcf\.)(?<!\bi\.a\.)(?<!\be\.g\.)(?<!\betc\.)(?<!\bvs\.)"
        r"\s+(?=[A-ZÆØËÉ0-9§])",
        desc.strip(),
    )
    return [part.strip() for part in parts if part.strip()]

def extract_sam_description(description:str)->str:
    """This methods takes a description
    First of, it checks the index of the word Description. If it's -1, it returns the entire description as-is
    else, it would return everything that comes after "Description"
    """
    if not description:
        return ""
    d, _ = clean_untrusted_text(description)
    marker = "Description"
    idx = d.find(marker)
    if idx == -1:
        return d
    return d[idx + len(marker):].lstrip(" :-\t").strip()