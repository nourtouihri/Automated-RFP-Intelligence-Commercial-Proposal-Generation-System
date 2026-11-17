"""Agent E: the grounding verifier, a judge on a model different from the writers.

The gate checks that a reply is valid JSON and that cited ids exist in a step's
inputs; the claim check checks textual containment. Neither reads the source and
asks whether it actually supports what was written - this does. After a step's
reply is accepted, its checked prose fields (same scoping as compose._CHECKED)
are judged, claim by claim, against what the writer was shown:

  input   each field's text plus exactly its cited sources - an id gives that
          asset's chunk text and its source record; a field without cited ids
          is judged against the step's own input payload (tender, research)
  output  one verdict per field: supported (the source states it, and code
          re-finds the verbatim quote), partial (the source is on topic but
          says less: for a person to review), unsupported (nothing in the
          source states it, or a source contradicts it)
  guard   the judge is a different model than the writer (see
          llm_adapter.verifier_call); the judge gets no tools and no output
          channel: verdicts are observations, they land in the trace and come
          out as bid warnings (compose.bid_warnings); deck text is untouched.

A "supported" verdict must carry a quote; code re-finds that quote inside the
very support strings the judge was shown (dashes, case and spacing normalised,
then a spacing-free pass). A supported without a findable quote is downgraded
to partial: the judge overstated, so a person checks. Only syntax is retried
(invalid JSON, schema, count or order), never a verdict: a retry cannot make a
second reading honest. A judge that fails after MAX_ATTEMPTS, or on transport,
does not stop the deck - the trace says the grounding check was unavailable,
like a skipped PDF.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .claims import _DASH
from .config import Config, DEFAULT

MAX_ATTEMPTS = 3
INVALID_JSON_FIX = "your last reply was not valid JSON; return one JSON object only"

LLM = Callable[[str, str], str]  # (system, user) -> raw text holding one JSON object

# The judge's own reply schema: one row per FIELDS item, in FIELDS order.
VERDICTS = Literal["supported", "partial", "unsupported"]


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Annotated[str, Field(max_length=60)]
    verdict: VERDICTS
    quote: Annotated[str | None, Field(max_length=240)] = None
    reason: Annotated[str, Field(max_length=160)] = ""


class VerifierReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdicts: list[Verdict] = Field(min_length=1, max_length=12)


# What the judge may look at in each step's output: sentences, not titles or
# labels. Same scoping as compose._CHECKED; that dict serves the regex claim
# check, this one the verifier, and compose imports this module, so the copies
# stand (an import from compose would be circular).
FIELD_PATTERNS = {"brief": r"key_messages\[\d+\]$",
                  "letter": r"paragraphs\[\d+\]$|closing$",
                  "summary": r"pillars\[\d+\]\.body$|why_us$",
                  "needs": r"needs\[\d+\]\.body$",
                  "approach": r"phases\[\d+\]\.body$",
                  "evidence": r"line$"}


def _strings(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _strings(value, f"{path}[{i}]")


def _cited_ids(name: str, dump: dict, payload: dict) -> dict[str, list[str]]:
    """field path -> the ids that field cites: its own evidence, nothing else."""
    if name == "summary":
        return {f"pillars[{i}].body": list(p.get("evidence") or [])
                for i, p in enumerate(dump.get("pillars") or [])}
    if name == "evidence":
        asset = payload.get("ASSET") or {}
        return {"line": [asset["id"]] if asset.get("id") else []}
    return {}


def _fields(name: str, dump: dict, payload: dict) -> list[dict]:
    """The checked prose fields, as [{field, text, ids}] in the dump's order."""
    cites = _cited_ids(name, dump, payload)
    out = []
    for path, text in _strings(dump):
        if re.search(FIELD_PATTERNS[name], path):
            out.append({"field": path, "text": text, "ids": cites.get(path, [])})
    return out


def _support(name: str, fields: list[dict], payload: dict,
             records: dict) -> tuple[dict, dict[str, list[str]]]:
    """SOURCES and, per field path, the exact strings a quote may come from.

    A cited field is judged against only what it cites (its chunk and its
    source record); a field without ids is judged against the step's input
    payload, the same support the claim check uses. Nothing else is shown."""
    chunks_text = {a["id"]: a.get("text") or "" for a in
                   (payload.get("ASSETS") or ([payload["ASSET"]] if "ASSET" in payload else []))
                   if a.get("id")}
    sources: dict = {}
    hay: dict[str, list[str]] = {}
    if any(not f["ids"] for f in fields):
        sources["INPUT"] = payload
        hay["INPUT"] = [json.dumps(payload, ensure_ascii=False)]
    for f in fields:
        found = []
        for rid in f["ids"]:
            if rid not in sources:
                source: dict = {}
                if rid in chunks_text:
                    source["chunk"] = chunks_text[rid]
                record = records.get(rid)
                if record is not None:
                    source["record"] = record
                sources[rid] = source
            source = sources[rid]
            found += [*([source["chunk"]] if "chunk" in source else []),
                      *(json.dumps(source["record"], ensure_ascii=False)
                        if "record" in source else [])]
        if not f["ids"]:
            found += hay["INPUT"]
        hay[f["field"]] = found
    return sources, hay


def _system(config: Config = DEFAULT) -> str:
    return f"""You are the grounding verifier for a proposal written for {config.company_sentence}.
You check written claims against the sources they cite, and you judge only: you have no
tools, you never rewrite text, you invent nothing.
Each item in FIELDS gives field (where the text sits), text (the written claim) and ids
(the sources it cites). SOURCES holds those sources: "chunk" is the retrieved text and
"record" is its source record; a field whose ids are empty is judged against the INPUT
source, the very material its step was written from.
supported: a source states it, so that quoting a span of that source proves the claim;
put that exact span in "quote", as written there. partial: the source is on topic but
the claim says more, or more strongly, than the source does - tell what in "reason".
unsupported: no source states it, or a source contradicts it - say which in "reason".
Never invent a quote: find it in the source first.
Return one JSON object matching this JSON Schema and nothing else:
"""


def _task(n: int) -> str:
    return (f"Judge each item in FIELDS, in order: one verdict per item, {n} "
            f"item{'s' if n != 1 else ''}.")


def _norm(text: str) -> str:
    t = text.translate(_DASH).lower()
    return re.sub(r"\s+", " ", t).strip()


def _quote_found(quote: str, hay: list[str]) -> bool:
    """The quote appears in one of the field's support strings: normalised
    first, then spacing-free (a record quoted across JSON separators)."""
    q = _norm(quote)
    if not q:
        return False
    if any(q in _norm(h) for h in hay):
        return True
    flat = q.replace(" ", "")
    return any(flat in re.sub(r"\s+", "", _norm(h)) for h in hay)


def _rail(v: Verdict, hay: list[str]) -> Verdict:
    """Code's check on the judge: a supported verdict proves itself with a
    quote code can find; otherwise the judge overstated, and a person checks."""
    if v.verdict != "supported" or _quote_found(v.quote or "", hay):
        return v
    return Verdict(field=v.field, verdict="partial", quote=v.quote,
                   reason="code could not find the quote in the cited source; "
                          f"{v.reason or 'check by hand'}")


class Verifier:
    """Runs the judge over one accepted step reply and returns the verdicts.

    judge is the same (system, user) -> text callable as a writer step's llm,
    but bound to a different model (llm_adapter.verifier_call). Verdicts are
    records, not edits: the caller puts them in the trace, and from there they
    surface as bid warnings; nothing else reads them."""

    def __init__(self, judge: LLM, model: str = ""):
        self._judge, self.model = judge, model
        self.calls: list[dict] = []

    def verify(self, name: str, payload: dict, out: BaseModel, *,
               records: dict | None = None, config: Config = DEFAULT):
        """Verdict dicts per field, or {"error": ...} when the judge could not
        deliver one. An empty field list calls nothing and returns []."""
        fields = _fields(name, out.model_dump(), payload)
        if not fields:
            return []
        sources, hay = _support(name, fields, payload, records or {})
        system = (_system(config) + json.dumps(VerifierReply.model_json_schema())
                  + "\nTASK: " + _task(len(fields)))
        offered = [f["field"] for f in fields]
        base = {"STEP": name, "FIELDS": fields, "SOURCES": sources}
        failures, fix, verdicts = [], [], None
        for _ in range(MAX_ATTEMPTS):
            user = json.dumps({**base, "FIX_PREVIOUS_REPLY": fix} if fix else base,
                              ensure_ascii=False)
            try:
                raw = self._judge(system, user)
            except (RuntimeError, OSError) as e:  # transport, quota, provider 4xx
                self.calls.append({"step": name, "ok": False, "user": user,
                                   "error": str(e)[:200]})
                return {"error": f"judge call failed: {str(e)[:120]}"}
            self.calls.append({"step": name, "ok": True, "user": user, "reply": raw})
            fix = []
            try:
                parsed = VerifierReply.model_validate_json(_json_object(raw))
            except ValidationError as e:
                if all(x["type"] == "json_invalid" for x in e.errors()):
                    failures.append("not valid JSON")
                    fix = [INVALID_JSON_FIX]
                else:
                    failures.append(str(e)[:200])
                    fix = [str(e.errors()[0])[:200]]
                continue
            except ValueError as e:
                failures.append(str(e)[:200])
                fix = [INVALID_JSON_FIX]
                continue
            given = [v.field for v in parsed.verdicts]
            if given != offered:
                failures.append(f"verdict fields {given} do not match FIELDS {offered}")
                fix = ["return exactly one verdict per FIELDS item, in this order: "
                       + ", ".join(offered)]
                continue
            verdicts = [self._row(_rail(v, hay[f["field"]]))
                        for f, v in zip(fields, parsed.verdicts)]
            break
        if verdicts is None:
            return {"error": f"after {MAX_ATTEMPTS} attempts: {failures[-1]}"}
        return verdicts

    def _row(self, v: Verdict) -> dict:
        row = {"field": v.field, "verdict": v.verdict, "reason": v.reason}
        if v.quote:
            row["quote"] = v.quote
        if self.model:
            row["judge"] = self.model
        return row


def _json_object(raw: str) -> str:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return raw[start:end + 1]
