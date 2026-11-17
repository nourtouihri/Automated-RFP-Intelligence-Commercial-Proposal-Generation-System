"""Turn pipeline output (tender + research + RAG matches) into a Proposal.

Decision D6: no single agent writes the whole deck. The work is a fixed
pipeline of small steps, each with a narrow input and a strict JSON output:

  0. inputs    code only: a tender that cannot make a deck raises InputError before
               any call; hits are de-duplicated by record id; an empty CV or
               project list becomes a placeholder card and a bid warning
  1. facts     code only: buyer profile, scores, CVs, projects, statuses
  2. brief     one call: headline, subtitle, three key messages, tone
  3. sections  one call each, seeing only its own inputs plus the brief:
               letter, summary, needs, evidence (one per requirement), approach
  4. check     every cited id must be among that step's own inputs
  5. assemble  code builds the Proposal; render.py draws it

A step that fails parsing or the citation check is retried on its own, up to
MAX_ATTEMPTS, then raises StepError naming the step. When no requirement reaches
Partial, no step runs: compose() returns a NoBid (cover, matrix, warnings, a line
written by code) unless force_bid is set. An optional verifier judges every
accepted reply against the sources it cites, on a different model; verdicts are
observations for the sales manager (bid warnings), they never rewrite text.

Input shapes follow the code on main: research returns sector /
estimated_revenue / past_projects / key_partners; RAG hits are
shared.schemas.QueryResult (id, content, doc_type, source_file, metadata,
similarity, ranking_score), where metadata.record_id names the source record.
The chunk metadata is thin (a CV hit has person/role/skills, a project hit
only client_sector/tech_stack), so names, years, outcomes and statuses are
read from the source records ("Cvs dataset/*.json") via load_records().
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .claims import support_text, unsupported
from .config import DEFAULT, Config
from .estimate import estimate_partners, estimate_sector, estimate_size
from .schemas import (
    MATRIX_ROWS, PARTIAL_AT, STRONG_AT, UNKNOWN, Approach, BuyerProfile, BuyerUnderstanding, Consultant,
    CoverLetter, ExecutiveSummary, Investment, Meta, Need, NoBid, Phase, Pillar, PriceLine, Proposal,
    Reference, RequirementRow,
)
from .verifier import Verifier

LLM = Callable[[str, str], str]  # (system, user) -> raw text holding one JSON object
MAX_ATTEMPTS = 3
MARGIN = 0.85  # prompts aim this far under each maxLength; the schema limits stay hard


def _aim(limit: int) -> int:
    return int(limit * MARGIN)


# Wording the prompt forbids and bid_warnings checks for, as canonical name -> pattern
# (matched on lowercase text with dashes normalised; "seamlessly" and "zero service
# disruption" count).
BANNED_WORDS = {
    "proven": r"\bproven\b",
    "seamless": r"\bseamless\w*",
    "real-time": r"\breal[- ]time\b",
    "zero disruption": r"\bzero\s+(?:\w+\s+)?disruption\b",
    "guarantee": r"\bguarantee\w*",
    "best-in-class": r"\bbest[- ]in[- ]class\b",
    "world-class": r"\bworld[- ]class\b",
    "cutting-edge": r"\bcutting[- ]edge\b",
    "unmatched": r"\bunmatched\b",
    "leading": r"\bleading\b",
}
INVALID_JSON_FIX = "your last reply was not valid JSON; return one JSON object only"


class StepError(RuntimeError):
    pass


class InputError(ValueError):
    """The input cannot make a deck; raised before any LLM call, naming the field."""


# ---------- step outputs ----------

class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BriefOut(_Out):
    headline: str = Field(max_length=60)
    subtitle: str = Field(max_length=80)
    key_messages: list[str] = Field(min_length=3, max_length=3)
    tone: str = Field(max_length=80)


class LetterOut(_Out):
    salutation: str
    paragraphs: list[Annotated[str, Field(max_length=220)]] = Field(min_length=1, max_length=2)
    closing: str


class SummaryOut(_Out):
    title: str = Field(max_length=53)
    pillars: list[Pillar] = Field(min_length=3, max_length=3)
    why_us: str = Field(max_length=190)


class NeedsOut(_Out):
    needs: list[Need] = Field(min_length=1, max_length=3)


class EvidenceOut(_Out):
    line: str = Field(max_length=55)


class ApproachOut(_Out):
    phases: list[Phase] = Field(min_length=2, max_length=4)


# ---------- prompts ----------

def rules(config: Config = DEFAULT) -> str:
    return ("You write one part of a commercial proposal for " + config.company_sentence + """. Plain, specific,
confident English.
Use only the INPUT given. Never state numbers (revenue, scores, prices, headcount);
code fills them. Never call a project delivered. No superlatives or self-praise.
Never use these words: """ + ", ".join(BANNED_WORDS) + """.
Never promise more than the INPUT supports: no "instant" or guarantees where the
tender sets a deadline or says nothing; use its own terms.
Every maxLength is a hard limit in characters, spaces included; the TASK gives
a lower target for each field, keep to it. If FIX_PREVIOUS_REPLY is present,
your last reply was rejected: do what it says (shorten the named fields by at
least that much, cite only the ids it lists, or return valid JSON).
Return one JSON object matching this JSON Schema and nothing else:
""")


def tasks(config: Config = DEFAULT) -> dict[str, str]:
    return {
        "brief": f"Set the deck's headline (at most {_aim(60)} characters), subtitle (at most "
                 f"{_aim(80)} characters, about 10 words), three key messages and tone (at most "
                 f"{_aim(80)} characters) for this tender.",
        "letter": f"Write the cover letter body: salutation, one or two short paragraphs (each at most "
                  f"{_aim(220)} characters, about 30 words), a closing line.",
        "summary": f"Write a title (at most {_aim(53)} characters), three executive-summary pillars "
                   f"(title at most {_aim(28)} characters, body at most {_aim(110)} characters, about "
                   f"14 words) and a 'Why {config.company}' line (at most {_aim(190)} characters). "
                   "Each pillar must list in 'evidence' the ids of the ASSETS it relies on. "
                   "COMPANY_PAGES, if given, may inform only the 'Why' line and are never cited.",
        "needs": f"Describe up to three needs of the buyer (title at most {_aim(40)} characters, body "
                 f"at most {_aim(120)} characters, about 15 words), from the tender and the research "
                 "only.",
        "evidence": f"In one line of at most {_aim(55)} characters, say what the ASSET shows for this "
                    "requirement.",
        "approach": "Plan two to four delivery phases with week counts and one-line descriptions "
                    f"(name at most {_aim(20)} characters, description at most {_aim(100)} "
                    "characters).",
    }


TASKS = tasks(DEFAULT)  # the default config's tasks; steps use tasks(config)


@dataclass
class Trace:
    """Per-step record, for the report: attempts and failures per step."""
    steps: list[dict] = field(default_factory=list)


def _json_object(raw: str) -> str:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return raw[start:end + 1]


def _cited(out: BaseModel) -> set[str]:
    if isinstance(out, SummaryOut):
        return {e for p in out.pillars for e in p.evidence}
    return set()


def _stray_citations(out: BaseModel, allowed: set[str]) -> list[tuple[str, str]]:
    if not isinstance(out, SummaryOut):
        return []
    return [(f"pillars[{i}].evidence", e) for i, p in enumerate(out.pillars) for e in p.evidence
            if e not in allowed]


# Prose a claim can be checked in: sentences, not titles or labels.
_CHECKED = {"brief": r"key_messages\[\d+\]$", "letter": r"paragraphs\[\d+\]$|closing$",
            "summary": r"pillars\[\d+\]\.body$|why_us$", "needs": r"needs\[\d+\]\.body$",
            "approach": r"phases\[\d+\]\.body$", "evidence": r"line$"}


def _overlong(e: ValidationError) -> list[dict] | None:
    """The too-long strings and lists, or None when anything else is wrong too."""
    errors = e.errors()
    if not all(x["type"] in ("string_too_long", "too_long") for x in errors):
        return None
    return [{"loc": x["loc"], "length": len(x["input"]), "limit": x["ctx"]["max_length"],
             "kind": "list" if x["type"] == "too_long" else "string"} for x in errors]


def _feedback(o: dict) -> str:
    name, over = ".".join(map(str, o["loc"])), o["length"] - o["limit"]
    if o["kind"] == "list":
        return f"{name} has {o['length']} items, limit {o['limit']}: remove at least {over}"
    return (f"{name} has {o['length']} characters, limit {o['limit']}: remove at least {over} "
            f"(aim for {_aim(o['limit'])})")


def _cut(text: str, limit: int) -> tuple[str, str]:
    """Cut at the last sentence end that fits, else at the last whole word."""
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", text) if m.end() <= limit]
    if ends:
        return text[:ends[-1]], "sentence"
    head = text[:limit + 1]
    if " " not in head:
        return text[:limit], "hard"
    return head.rsplit(" ", 1)[0].rstrip(" ,;:-–"), "word"


def _trim(data: dict, overlong: list[dict]) -> list[dict]:
    """Lists keep their first items; strings are cut. Lists go first, so a string
    inside an item the list lost is skipped instead of cut for nothing."""
    trimmed = []
    for o in sorted(overlong, key=lambda o: o["kind"] != "list"):
        *path, key = o["loc"]
        node = data
        try:
            for part in path:
                node = node[part]
            if o["kind"] == "list":
                node[key], how = node[key][:o["limit"]], "list"
            else:
                node[key], how = _cut(node[key], o["limit"])
        except (IndexError, KeyError):
            continue
        trimmed.append({"field": ".".join(map(str, o["loc"])), "from": o["length"],
                        "to": len(node[key]), "how": how})
    return trimmed


def _strings(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _strings(value, f"{path}[{i}]")


def run_step(name: str, schema: type[_Out], payload: dict, llm: LLM, trace: Trace,
             allowed_ids: set[str] = frozenset(), records: dict | None = None, *,
             config: Config = DEFAULT, claim_check: bool = False,
             verifier: Verifier | None = None) -> _Out:
    """Up to MAX_ATTEMPTS replies; a retry is told exactly which strings or lists
    ran over, or that its reply was not JSON. If the last reply only ran over,
    code cuts those strings and lists to fit as a last resort and the trace (and
    so bid_warnings) records each cut. A retry after an invented citation is told
    the exact ids it may cite; code never maps a wrong id to a near one. With
    claim_check, every accepted reply's sentences are also checked for claims
    (numbers, years, names, "delivered") that this step's inputs do not contain;
    the trace records them under "unsupported". With a verifier, every accepted
    reply is also judged, claim by claim, against the sources it cites (a judge
    on a model other than this llm's); the trace records the verdicts under
    "verifier"."""
    task = tasks(config)[name]
    system = rules(config) + json.dumps(schema.model_json_schema()) + "\nTASK: " + task
    failures, fix, candidates = [], [], []

    def accept(out, attempts, **extra):
        entry = {"step": name, "attempts": attempts, "ok": True, "failures": failures, **extra}
        if claim_check:
            texts = {k: v for k, v in _strings(out.model_dump()) if re.search(_CHECKED[name], k)}
            assets = payload.get("ASSETS") or ([payload["ASSET"]] if "ASSET" in payload else [])
            found = unsupported(texts, support_text(config.company_sentence, task, payload, records or {}),
                                ignore=[a["id"] for a in assets])
            if found:
                entry["unsupported"] = [{**f, "text": texts[f["field"]]} for f in found]
        if verifier is not None:
            entry["verifier"] = verifier.verify(name, payload, out,
                                                records=records or {}, config=config)
        trace.steps.append(entry)
        return out

    for attempt in range(1, MAX_ATTEMPTS + 1):
        user = json.dumps({**payload, "FIX_PREVIOUS_REPLY": fix} if fix else payload,
                          ensure_ascii=False)
        reply = llm(system, user)  # outside the try: a transport error is not a parse failure
        fix = []
        try:
            out = schema.model_validate_json(_json_object(reply))
        except ValidationError as e:
            failures.append({"kind": "parse", "error": str(e)[:300]})
            overlong = _overlong(e)
            if overlong:
                candidates.append((sum(o["length"] - o["limit"] for o in overlong), -attempt,
                                   attempt, json.loads(_json_object(reply)), overlong))
                fix = [_feedback(o) for o in overlong]
            elif all(x["type"] == "json_invalid" for x in e.errors()):
                fix = [INVALID_JSON_FIX]
            continue
        except ValueError as e:
            failures.append({"kind": "parse", "error": str(e)[:300]})
            fix = [INVALID_JSON_FIX]
            continue
        stray = _stray_citations(out, set(allowed_ids))
        if stray:
            failures.append({"kind": "citation",
                             "error": f"cites ids outside its input: {sorted({e for _, e in stray})}"})
            may = f"cite only these ids: {sorted(allowed_ids)}, or leave the list empty"
            fix = [f"{path} cites {e}, which is not one of your input assets; {may}"
                   for path, e in stray]
            continue
        return accept(out, attempt)
    # Last resort: cut the reply that was only over-length and ran over the least, from any
    # attempt (not just the last, which may be truncated or invalid), and say which one.
    for _, _, attempt, data, overlong in sorted(candidates, key=lambda c: c[:2]):
        trimmed, out = _trim(data, overlong), None
        for _ in range(3):
            # Cutting a list can expose a too-long item that the first error never
            # reached (pydantic reports the list's length first), so check again.
            try:
                out = schema.model_validate(data)
                break
            except ValidationError as e:
                more = _overlong(e)
                if not more:
                    break
                trimmed += _trim(data, more)
        if out is not None and not _stray_citations(out, set(allowed_ids)):
            return accept(out, MAX_ATTEMPTS, trimmed=trimmed, trim_attempt=attempt)
    last = failures[-1]["error"]
    trace.steps.append({"step": name, "attempts": MAX_ATTEMPTS, "ok": False,
                        "failures": failures, "error": last})
    raise StepError(f"step '{name}' failed after {MAX_ATTEMPTS} attempts: {last}")


# ---------- facts (code only) ----------

def _profile(research: dict | None, tender: dict,
             vocabulary: set[str]) -> tuple[BuyerProfile, list[str]]:
    """Research values where present; the rest estimated from the tender. Returns
    the profile and the paths of the estimated fields. An estimated revenue is the
    size the tender states, never a figure in money."""
    r = research or {}

    def val(key):
        v = r.get(key)
        if isinstance(v, list):
            v = ", ".join(map(str, v[:3]))
        return str(v) if v else None

    found = {"sector": val("sector"), "estimated_revenue": val("estimated_revenue"),
             "key_partners": val("key_partners")}
    estimates = {"sector": estimate_sector(tender),
                 "estimated_revenue": estimate_size(tender),
                 "key_partners": estimate_partners(tender, vocabulary)}
    profile = BuyerProfile(**{k: found[k] or estimates[k] for k in found})
    return profile, [f"buyer.profile.{k}" for k in found if not found[k]]


def _vocabulary(hits: list[dict], records: dict[str, dict]) -> set[str]:
    """Every product and skill name in our own records, for estimate_partners."""
    sources = [h.get("metadata") or {} for h in hits] + list(records.values())
    return {t for s in sources for key in ("tech_stack", "skills")
            if isinstance(s.get(key), list) for t in s[key]}


RESEARCH_FIELDS = ("sector", "estimated_revenue", "key_partners", "past_projects")


def _research_gaps(research: dict | None) -> list[str]:
    """One warning naming every field usable research left empty."""
    if research is None:
        return []
    missing = [k for k in RESEARCH_FIELDS if not research.get(k)]
    return [f"research incomplete: {', '.join(missing)}"] if missing else []


DATASET_FILES = ("fake_cvs.json", "fake_projects.json", "olivesoft_projects.json",
                 "fake_tools.json")


ID_KEYS = ("cv_id", "project_id", "tool_id", "client_id", "id")


def load_records(dataset_dir: str | Path, files: tuple[str, ...] = DATASET_FILES) -> dict[str, dict]:
    """record_id -> source record, from the same files rag ingests. A record with
    none of the ID_KEYS is skipped."""
    records = {}
    for name in files:
        data = json.loads((Path(dataset_dir) / name).read_text(encoding="utf-8"))
        data = data if isinstance(data, list) else next(iter(data.values()))
        for rec in data:
            rid = next((rec[k] for k in ID_KEYS if rec.get(k)), None)
            if rid is not None:
                records[str(rid)] = rec
    return records


def record_id(hit: dict) -> str:
    rid = (hit.get("metadata") or {}).get("record_id")
    if not rid:
        raise InputError(f"hit {hit.get('id')!r} has no metadata.record_id; "
                         "refusing to guess a record from the chunk id")
    return str(rid)


def is_idea(rec: dict) -> bool:
    """An OliveSoft PFE internship idea: not proof that OliveSoft can deliver."""
    return "pfe_internship_project" in (rec.get("relationship"), rec.get("project_kind"))


_DONE = {"completed", "complete", "delivered", "production", "live", "done", "closed"}
# Outcome text that says the project did not finish, at the start or as "not completed".
_NOT_DONE = re.compile(
    r"^\W*(?:cancel\w*|abandon\w*|on hold|in progress|ongoing|planned|proposed|pending|postponed|"
    r"suspended|withdrawn|failed)\b|\bnot\s+(?:yet\s+)?(?:completed?|delivered|finished|live|done)\b",
    re.I)


def is_delivered(rec: dict) -> bool | None:
    """Decision F6: status comes from data, read from the source record or,
    failing that, the hit metadata. An explicit status (status, evidence_status,
    is_completed) decides. Free text never proves delivery: an outcome that says
    the work was not completed, cancelled, in progress or only proposed gives
    False, and any other outcome, or none, gives None (unverified), as for the
    synthetic projects. olivesoft_projects are PFE ideas and never delivered."""
    if is_idea(rec):
        return False
    for key in ("status", "evidence_status"):
        status = rec.get(key)
        if isinstance(status, str) and status.strip():
            return status.strip().lower() in _DONE
    if isinstance(rec.get("is_completed"), bool):
        return rec["is_completed"]
    outcome = rec.get("outcome")
    if isinstance(outcome, str) and _NOT_DONE.search(outcome):
        return False
    return None


# fix/data-rag folds website and client pages into the cv/project/tool doc types and keeps the
# source type in metadata.original_doc_type; they describe OliveSoft but prove no delivery.
COMPANY_PAGE_KINDS = {"company_profile", "tools_tech_stack", "client", "client_portfolio",
                      "project_reference"}


def kind(hit: dict) -> str | None:
    return (hit.get("metadata") or {}).get("original_doc_type") or hit.get("doc_type")


def is_record(hit: dict, *kinds: str) -> bool:
    return kind(hit) in kinds and not is_idea(hit.get("metadata") or {})


def evidence_hit(hits: list[dict]) -> dict | None:
    """Decision F11: the best hit that is real evidence, a CV or project record.
    PFE ideas get a ranking boost in rag/ranking.py but prove nothing; tools and
    website pages describe, they do not prove. All are skipped."""
    return next((h for h in hits if is_record(h, "cv", "project")), None)


def _asset_view(a: dict) -> dict:
    return {"id": record_id(a), "type": a.get("doc_type"), "text": (a.get("content") or "")[:500]}


# ---------- inputs ----------

SIMILARITY_NOISE = 1e-6  # float error around 0 and 1 is clipped; anything further out is an error


def _check_tender(tender, requirement_matches) -> None:
    for key in ("title", "issuer"):
        value = tender.get(key) if isinstance(tender, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise InputError(f"tender.{key} is missing or empty")
    if not requirement_matches:
        raise InputError("the tender has no requirements: requirement_matches is empty")


def _incomplete_warning(tender: dict) -> list[str]:
    """phase2 detection accepts a degraded tender with status "incomplete" and a
    quality report; the deck is still written, and sales is told what is missing."""
    if tender.get("status") != "incomplete":
        return []
    quality = tender.get("quality") or {}
    missing = [str(f) for f in quality.get("missing_fields") or []]
    if missing:
        return [f"tender is incomplete: missing {', '.join(missing)}"]
    completeness = quality.get("completeness")
    if isinstance(completeness, (int, float)) and not isinstance(completeness, bool):
        return [f"tender is incomplete: completeness {completeness:.2f}"]
    return ["tender is incomplete"]


def _ingest_warnings(tender: dict) -> list[str]:
    """phase2 detection's quality.warnings (llm_unavailable, sanitized_chars, ...), one each."""
    flags = (tender.get("quality") or {}).get("warnings") or []
    return [f"tender ingest warning: {f}" for f in flags if isinstance(f, str) and f.strip()]


def _expired_warning(tender: dict) -> list[str]:
    """A deadline before today, read from the tender or phase2's quality.is_expired."""
    try:
        deadline = date.fromisoformat(str(tender.get("deadline") or "")[:10])
    except ValueError:
        deadline = None
    if deadline and deadline < date.today():
        return [f"tender deadline has passed ({deadline.isoformat()})"]
    if (tender.get("quality") or {}).get("is_expired") is True:
        return ["tender deadline has passed"]
    return []


_NUM = (r"(?:\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        r"twenty-four|forty-eight)")
_UNIT = r"(?:minute|hour|day|week|month|year)s?"
# Only explicit timing phrases: "14 years of history" or "parcels a day" state no delivery time.
_DURATION = re.compile(
    rf"\b(?:within|in under|in less than|ends? in|ending in|up to|at most)\s+{_NUM}\s+"
    rf"(?:business\s+|working\s+)?{_UNIT}\b|\bno later than\s+[^.;,\n]+|\bdeadline\b", re.I)
_SPEED = re.compile(r"\b(?:same[- ]day|immediate(?:ly)?|instant(?:ly|aneous(?:ly)?)?|real[- ]?time)\b",
                    re.I)
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")


def _tender_text(tender: dict) -> str:
    return "\n".join([str(tender.get("title") or ""), str(tender.get("raw_text") or ""),
                      *map(str, tender.get("requirements") or [])]).translate(_DASHES)


def tender_duration(tender: dict) -> str | None:
    """The first duration or deadline the tender text states, as written."""
    m = _DURATION.search(_tender_text(tender))
    return m.group(0).strip() if m else None


# An evidence line that says the asset does not support the requirement.
DISCLAIMS = re.compile(
    r"^\W*(?:(?:not applicable|n/?a|none|not relevant|unrelated"
    r"|no (?:relevant |direct )?(?:evidence|match|asset))\W*$"
    r"|(?:not relevant to|does not (?:show|cover|address|support))\s)", re.I)


def speed_promises(texts: list[tuple[str, str]], tender: dict) -> list[str]:
    """Prose promising faster delivery (same-day, immediately, instant, real-time) than a
    duration or deadline the tender states. A word the tender itself uses is not flagged."""
    stated = tender_duration(tender)
    if not stated:
        return []
    flat = re.sub(r"[- ]", "", _tender_text(tender).lower())
    out = []
    for where, text in texts:
        for m in _SPEED.finditer(text.translate(_DASHES)):
            word = m.group(0).lower()
            if re.sub(r"(?:ly|aneous|aneously)$", "", re.sub(r"[- ]", "", word)) not in flat:
                out.append(f'speed promise "{word}" in {where}; the tender states "{stated}"')
    return out


def research_problem(research) -> str | None:
    """Why research cannot be used, or None. Main's ProspectResearch has no status;
    phase2 adds status (complete, partial, unavailable) and completed_at. A partial
    result is used for the facts it found."""
    if research is None:
        return "no research result"
    if not isinstance(research, dict):
        return "research result is not an object"
    if isinstance(research.get("error"), dict):
        return f"research failed: {research['error'].get('code', 'unknown error')}"
    if "detail" in research and "tender_id" not in research:  # FastAPI's error shape on main
        return f"research failed: {research['detail']}"
    status = research.get("status")
    if status is None:
        return None
    if status not in ("complete", "partial"):
        return f"research status is {status}"
    if not research.get("completed_at"):
        return "research has not completed"
    return None


def _similarity(hit: dict, where: str) -> float:
    s = hit.get("similarity")
    if isinstance(s, bool) or not isinstance(s, (int, float)) or s != s:
        raise InputError(f"{where}: similarity must be a number, got {s!r}")
    if -SIMILARITY_NOISE <= s < 0:
        return 0.0
    if 1 < s <= 1 + SIMILARITY_NOISE:
        return 1.0
    if not 0 <= s <= 1:
        raise InputError(f"{where}: similarity {s} is outside 0..1")
    return float(s)


def _clean_hits(hits: list[dict], where: str) -> list[dict]:
    """Every hit checked, then de-duplicated by record id (the first, best-ranked one stays)."""
    seen, out = set(), []
    for h in hits:
        if not isinstance(h, dict):
            raise InputError(f"{where}: a hit must be an object, got {type(h).__name__}")
        rid = record_id(h)
        similarity = _similarity(h, f"{where} hit {rid}")
        if rid not in seen:
            seen.add(rid)
            out.append({**h, "similarity": similarity})
    return out


def _to_be_staffed(requirement: str) -> Consultant:
    return Consultant(cv_id=None, name="To be staffed", role=f"Consultant for {requirement}",
                      skills=requirement, score=0.0)


def _no_reference() -> Reference:
    return Reference(project_id=None, title="No matching project", summary="No matching project found",
                     sector=UNKNOWN, score=0.0, delivered=False)


def _team(cvs: list[dict], rec) -> list[Consultant]:
    skill_lists = [rec(c).get("skills", []) for c in cvs]
    shared = set.intersection(*map(set, skill_lists)) if len(skill_lists) > 1 else set()
    team = []
    for c, skills in zip(cvs, skill_lists):
        r = rec(c)
        # Matched CVs often come from one past team with the same leading
        # skills; list what sets each person apart first.
        skills = [k for k in skills if k not in shared] + [k for k in skills if k in shared]
        team.append(Consultant(cv_id=record_id(c), name=r.get("name") or r.get("person") or UNKNOWN,
                               role=r.get("role") or UNKNOWN, years=r.get("years_experience"),
                               skills=", ".join(skills[:5]) or UNKNOWN,
                               score=round(c["similarity"], 2)))
    return team


def _references(projects: list[dict], rec) -> list[Reference]:
    refs = []
    for p in projects:
        r = rec(p)
        refs.append(Reference(project_id=record_id(p),
                              title=r.get("name") or r.get("summary") or record_id(p),
                              summary=r.get("description") or r.get("outcome") or "",
                              sector=r.get("client_sector") or ", ".join(r.get("domain", [])),
                              score=round(p["similarity"], 2), delivered=is_delivered(r)))
    return refs


_COUNT_WORDS = "zero one two three four five six seven eight nine ten eleven twelve".split()


def approach_title(n: int) -> str:
    word = _COUNT_WORDS[n].capitalize() if 0 <= n < len(_COUNT_WORDS) else str(n)
    return f"{word} phase{'' if n == 1 else 's'}, a working release at each"


# ---------- pipeline ----------

def compose(tender: dict, research: dict | None, requirement_matches: dict[str, list[dict]],
            cv_matches: list[dict], project_matches: list[dict], llm: LLM,
            records: dict[str, dict] | None = None, reference: str | None = None,
            trace: Trace | None = None, *,
            config: Config = DEFAULT, claim_check: bool = False,
            verifier: Verifier | None = None, force_bid: bool = False) -> Proposal | NoBid:
    """requirement_matches maps each tender requirement to its ranked RAG hits;
    records is load_records() output, the source of every fact shown. A verifier
    (a different model than llm) judges every accepted reply against its cited
    sources, recorded in the trace and surfaced as bid warnings; without one, or
    with verifier None, nothing is judged.

    Raises InputError, before any LLM call, for a tender without title, issuer or
    requirements, a hit with no metadata.record_id, or a similarity outside 0..1.
    An empty cv_matches or project_matches gives a placeholder card and a bid
    warning. With more than MATRIX_ROWS requirements the best-scoring ones are
    shown and a bid warning says how many are not. If no requirement reaches
    Partial, returns a NoBid without calling the model, unless force_bid."""
    trace = trace if trace is not None else Trace()
    records = records or {}
    _check_tender(tender, requirement_matches)
    matches = {req: _clean_hits(hits, f"requirement {req!r}")
               for req, hits in requirement_matches.items()}
    cvs = [h for h in _clean_hits(cv_matches, "cv_matches") if is_record(h, "cv")]
    projects = _clean_hits(project_matches, "project_matches")
    pages = [h for h in projects if kind(h) in COMPANY_PAGE_KINDS]
    # Decision F10 keeps PFE ideas as references that fill empty slots.
    projects = [h for h in projects if is_record(h, "project") or is_idea(h.get("metadata") or {})]
    buyer = tender["issuer"]
    problem = research_problem(research)
    if problem:
        research = None
    no_research = [f"research unavailable ({problem})"] if problem else []
    tender_warnings = (_incomplete_warning(tender) + _expired_warning(tender)
                       + _ingest_warnings(tender))
    input_warnings = tender_warnings + [
        f"{w}: the buyer profile is estimated from the tender" for w in no_research
    ] + _research_gaps(research)

    def rec(hit: dict) -> dict:
        return {**(hit.get("metadata") or {}), **records.get(record_id(hit), {})}

    best = {req: evidence_hit(hits) for req, hits in matches.items()}
    score = {req: round(hit["similarity"], 2) if hit else 0.0 for req, hit in best.items()}
    order = list(best)
    shown = order if len(order) <= MATRIX_ROWS else [order[i] for i in sorted(
        sorted(range(len(order)), key=lambda i: -score[order[i]])[:MATRIX_ROWS])]

    def code_row(req: str) -> RequirementRow | None:
        """The rows no model writes: nothing retrieved, or a weak hit. A weak hit
        is usually the wrong asset (feasibility run: wrong in 10 of 17 rows below
        0.40); asking the model to describe it invites a claim the asset does not
        support, so code writes the cell."""
        hit = best[req]
        if hit is None:
            return RequirementRow(requirement=req, evidence="", score=0.0, evidence_id=None)
        if score[req] < PARTIAL_AT:
            return RequirementRow(requirement=req, evidence="Weak match only, flagged for review",
                                  score=score[req], evidence_id=record_id(hit))
        return None

    # Decision F10: delivered references first, then unverified; PFE ideas only fill empty slots.
    projects = sorted(projects, key=lambda h: {True: 0, None: 1, False: 2}[is_delivered(rec(h))])
    team = _team(cvs[:3], rec) or [_to_be_staffed(max(order, key=lambda r: score[r]))]
    refs = _references(projects[:3], rec) or [_no_reference()]
    when = date.today()

    def meta(headline: str, subtitle: str) -> Meta:
        return Meta(buyer=buyer, tender_title=tender["title"],
                    reference=reference or tender.get("id", UNKNOWN),
                    date=f"{when.day} {when:%B %Y}", headline=headline, subtitle=subtitle)

    if not force_bid and all(score[r] < PARTIAL_AT for r in order):
        all_rows = [code_row(r) for r in order]
        rows = [code_row(r) for r in shown]
        return NoBid(
            meta=meta("No-bid recommendation",
                      f"Evidence is too weak to bid: best match below {PARTIAL_AT:.2f}"),
            requirements=rows, all_requirements=all_rows,
            input_warnings=[f"no-bid recommendation: every requirement is a Gap (best match below "
                      f"{PARTIAL_AT:.2f})", *tender_warnings, *no_research, *_research_gaps(research),
                      *_hidden_warning(all_rows, rows),
                      *_structural(all_rows, team, refs)],
            recommendation=f"The best match for every requirement is below {PARTIAL_AT:.2f}, so "
                           f"{config.company}'s indexed assets do not support a bid on this tender. "
                           "Review the matrix; a full proposal can still be generated on request.")

    tender_view = {"title": tender.get("title"), "issuer": buyer, "requirements": shown,
                   "text": (tender.get("raw_text") or "")[:3000]}
    research_view = {k: (research or {}).get(k) for k in
                     ("sector", "past_projects", "key_partners", "notes")}
    kw = {"records": records, "config": config, "claim_check": claim_check, "verifier": verifier}

    brief = run_step("brief", BriefOut, {"TENDER": tender_view, "RESEARCH": research_view},
                     llm, trace, **kw)
    ctx = {"BRIEF": brief.model_dump()}

    letter = run_step("letter", LetterOut, {**ctx, "BUYER": buyer,
                                            "TENDER_TITLE": tender.get("title")}, llm, trace, **kw)

    summary_assets = [_asset_view(a) for a in (cvs[:3] + projects[:3])]
    company_pages = {"COMPANY_PAGES": [_asset_view(a) for a in pages[:3]]} if pages else {}
    summary = run_step("summary", SummaryOut, {**ctx, "ASSETS": summary_assets, **company_pages},
                       llm, trace,
                       allowed_ids={a["id"] for a in summary_assets}, **kw)

    needs = run_step("needs", NeedsOut, {**ctx, "TENDER": tender_view,
                                         "RESEARCH": research_view}, llm, trace, **kw)

    written, disclaimed = {}, []
    for req in shown:
        row = code_row(req)
        if row is None:
            hit = best[req]
            ev = run_step("evidence", EvidenceOut, {"REQUIREMENT": req, "ASSET": _asset_view(hit)},
                          llm, trace, **kw)
            line = ev.line
            if DISCLAIMS.search(line):
                disclaimed.append(f'evidence for "{req}" disclaimed by the model: "{line}"')
                line = "Related asset only, flagged for review"
            row = RequirementRow(requirement=req, evidence=line, score=score[req],
                                 evidence_id=record_id(hit))
        written[req] = row
    # Rows the matrix cannot show are not described by the model; the CSV lists them.
    all_rows = [written.get(r) or code_row(r) or RequirementRow(
        requirement=r, evidence="", score=score[r], evidence_id=record_id(best[r])) for r in order]

    approach = run_step("approach", ApproachOut, {**ctx, "REQUIREMENTS": shown}, llm, trace, **kw)
    weeks = sum(p.weeks for p in approach.phases)
    hits = [*cvs, *projects, *(h for hs in matches.values() for h in hs)]
    profile, estimated = _profile(research, tender, _vocabulary(hits, records))
    estimated += ["team[0]"] * (team[0].cv_id is None) + ["investment.lines"]

    p = Proposal(
        meta=meta(brief.headline, brief.subtitle),
        signatory=config.signatory,
        letter=CoverLetter(title=config.letter_title, salutation=letter.salutation,
                           paragraphs=letter.paragraphs, closing=letter.closing),
        summary=ExecutiveSummary(title=summary.title, pillars=summary.pillars,
                                 why_us=summary.why_us),
        buyer=BuyerUnderstanding(profile=profile, needs=needs.needs,
                                 researched=problem is None),
        requirements=[written[r] for r in shown], all_requirements=all_rows,
        approach=Approach(title=approach_title(len(approach.phases)), phases=approach.phases,
                          milestones=f"Milestones: kickoff week 1, go-live week {weeks}."),
        team=team, references=refs, input_warnings=input_warnings, estimated=estimated,
        investment=Investment(
            currency=config.currency, note=config.investment_note,
            lines=[_price(ph, config) for ph in approach.phases],
            next_steps=list(config.next_steps)
        ),
        review_status="draft"
    )
    p.input_warnings += disclaimed + speed_promises(llm_texts(p), tender)
    if weeks > config.long_plan_weeks:
        p.input_warnings.append(f"the plan runs {weeks} weeks, over {config.long_plan_weeks}: "
                                "check the indicative price")
    return p


def _price(phase: Phase, config: Config) -> PriceLine:
    days = phase.weeks * 5 * config.team_size
    return PriceLine(workstream=phase.name, days=days, amount=days * config.day_rate)


def llm_texts(p: Proposal) -> list[tuple[str, str]]:
    """Every text the model wrote, as (field path, text). Code-written cells
    (weak-match rows, buyer profile, names, statuses) are left out."""
    out = [("meta.headline", p.meta.headline), ("meta.subtitle", p.meta.subtitle),
           ("letter.salutation", p.letter.salutation)]
    out += [(f"letter.paragraphs[{i}]", t) for i, t in enumerate(p.letter.paragraphs)]
    out += [("letter.closing", p.letter.closing), ("summary.title", p.summary.title)]
    out += [(f"summary.pillars[{i}].{k}", getattr(pl, k))
            for i, pl in enumerate(p.summary.pillars) for k in ("title", "body")]
    out += [("summary.why_us", p.summary.why_us)]
    out += [(f"buyer.needs[{i}].{k}", getattr(n, k))
            for i, n in enumerate(p.buyer.needs) for k in ("title", "body")]
    out += [(f"requirements[{i}].evidence", r.evidence) for i, r in enumerate(p.requirements)
            if r.evidence_id and r.score >= PARTIAL_AT]
    out += [(f"approach.phases[{i}].{k}", getattr(ph, k))
            for i, ph in enumerate(p.approach.phases) for k in ("name", "body")]
    return out


def banned_wording(p: Proposal) -> list[str]:
    """One entry per (field, banned word): 'proven in meta.headline'."""
    dash = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
    return [f'banned wording "{word}" in {where}'
            for where, text in llm_texts(p)
            for word, rx in BANNED_WORDS.items()
            if re.search(rx, text.translate(dash).lower())]


def _hidden_warning(all_rows: list[RequirementRow], shown: list[RequirementRow]) -> list[str]:
    names = {r.requirement for r in shown}
    hidden = [r for r in all_rows if r.requirement not in names]
    if not hidden:
        return []
    gap = sum(r.fit == "Gap" for r in hidden)
    return [f"{len(shown)} of {len(all_rows)} requirements shown; the full list is in the CSV; "
            f"{gap} of the {len(hidden)} hidden requirements are Gap"]


def _structural(requirements: list[RequirementRow], team: list[Consultant],
                references: list[Reference]) -> list[str]:
    out = []
    if not any(r.score >= STRONG_AT for r in requirements):
        out.append("no requirement has strong evidence")
    refs = [r for r in references if r.project_id is not None]
    if not refs:
        out.append("no project matched: the references slide is a placeholder")
    elif all(r.delivered is False for r in refs):
        out.append("no delivered reference project")
    members = [c for c in team if c.cv_id is not None]
    if not members:
        out.append("no CV matched: the team slide is a placeholder")
    elif all(c.score < PARTIAL_AT for c in members):
        out.append("every matched consultant is a weak match")
    return out


def _from_verifier(steps: list[dict]) -> list[str]:
    """One entry per judged field the grounding verifier could not support, and
    one when the grounding check itself was unavailable. Supported claims are
    silent; partial and unsupported reach the sales manager like every check."""
    out = []
    for s in steps:
        v = s.get("verifier")
        if isinstance(v, dict) and v.get("error"):
            out.append(f'grounding check unavailable: {s["step"]}: {v["error"]}')
            continue
        for row in v or []:
            where = f'{s["step"]}.{row["field"]}'
            reason = row.get("reason") or "no reason given"
            if row["verdict"] == "unsupported":
                out.append(f'verifier: unsupported claim in {where}: {reason}')
            elif row["verdict"] == "partial":
                out.append(f'verifier: partial support in {where}: {reason}')
    return out


def bid_warnings(p: Proposal | NoBid, trace: Trace | None = None) -> list[str]:
    """Signals that this tender is outside what the evidence supports, that code
    cut the model's prose or hid requirements, that the prose used a banned
    word or a claim the step's inputs do not contain, or that the grounding
    verifier would not support a claim; the sales manager sees them before the
    deck goes anywhere."""
    if isinstance(p, NoBid):
        return list(p.input_warnings)
    out = list(p.input_warnings)
    steps = trace.steps if trace else []
    cut = [f"{s['step']}.{t['field']}" for s in steps for t in s.get("trimmed", [])
           if t["how"] != "list"]
    short = [f"{s['step']}.{t['field']} {t['from']} -> {t['to']}" for s in steps
             for t in s.get("trimmed", []) if t["how"] == "list"]
    if cut:
        out.append(f"{len(cut)} text field{'s' if len(cut) > 1 else ''} cut by code to fit: "
                   + ", ".join(cut))
    if short:
        out.append(f"{len(short)} list{'s' if len(short) > 1 else ''} shortened by code "
                   "(first items kept): " + ", ".join(short))
    out += _hidden_warning(p.all_requirements or p.requirements, p.requirements)
    out += _structural(p.requirements, p.team, p.references)
    claims = [f'unsupported {c["kind"]} "{c["claim"]}" in {s["step"]}.{c["field"]}'
              for s in steps for c in s.get("unsupported", [])]
    return out + _from_verifier(steps) + banned_wording(p) + claims


def retrieved_ids(p: Proposal) -> set[str]:
    return ({r.evidence_id for r in p.requirements if r.evidence_id}
            | {c.cv_id for c in p.team if c.cv_id} | {r.project_id for r in p.references if r.project_id})
