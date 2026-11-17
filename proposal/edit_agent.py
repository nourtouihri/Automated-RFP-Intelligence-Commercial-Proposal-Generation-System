"""One reviewer prompt against one slide's whole value.

Mirrors research.extractor's fail-closed reply handling: the reply must be a
JSON value with the same shape as the slide's current value (the same keys,
the same list lengths), and it must re-validate against the schemas.py model
that types that slide; anything else (bad JSON, a shape mismatch, an invalid
value) is logged and ignored, so the stored deck is never touched by a
half-meaningful rewrite. The EDITABLE table is the write-surface policy: it
names the only slide value a prompt may replace, and the slide's per-item
models keep verification results, ids, scores and delivery flags code-owned
— the runner copies them back from the current items, so whatever the LLM
echoes there is overwritten (see edit_runner._restore_owned). Slides 4 and 5
(buyer profile, verification matrix) are code-owned wholesale and have no
entry at all.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, NamedTuple

from .compose import BANNED_WORDS
from .config import DEFAULT, Config
from .llm_adapter import Adapter, openai_call
from .schemas import (Approach, Consultant, CoverLetter, ExecutiveSummary,
                      Investment, Meta, Reference)

logger = logging.getLogger(__name__)


def _check_no_blanks(value: Any, name: str = "$") -> None:
    """No blank string anywhere in a returned whole value: a blank rewrite
    would silently weaken the deck without the reviewer noticing."""
    if isinstance(value, str):
        if not value.strip():
            raise ValueError(f"{name}: blank string")
    elif isinstance(value, dict):
        for k, v in value.items():
            _check_no_blanks(v, f"{name}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_no_blanks(v, f"{name}[{i}]")


def _check_edits_only(value: Any, current: Any, name: str = "$") -> None:
    """The whole-value reply may rewrite, but never reshape: every list must
    hold exactly as many items as the current value does (the agent cannot
    add or drop facts by editing), and a numeric leaf never takes a boolean
    (True is an int in Python, and pydantic's lax mode would read it as 1)."""
    if isinstance(current, list):
        if not isinstance(value, list):
            raise ValueError(f"{name}: the reply is not a list "
                             f"where the current value holds {len(current)}")
        if len(value) != len(current):
            raise ValueError(f"{name}: the reply holds {len(value)} item(s); "
                             f"the current value holds {len(current)}")
        for i, (new, old) in enumerate(zip(value, current)):
            _check_edits_only(new, old, f"{name}[{i}]")
    elif isinstance(current, bool):
        # a boolean leaf stays a boolean (True echoes as True, False as False;
        # a numeric reply here would weaken a flag silently)
        if not isinstance(value, bool):
            raise ValueError(f"{name}: expected a boolean, "
                             f"got {type(value).__name__}")
    elif isinstance(current, (int, float)):
        # pydantic's lax mode reads True as 1 and "2" as 2; the reply narrows
        # to the current scalar type instead
        if isinstance(value, bool) or not isinstance(value, type(current)):
            raise ValueError(f"{name}: expected {type(current).__name__}, "
                             f"got {type(value).__name__}")
    elif isinstance(current, dict):
        if not isinstance(value, dict):
            raise ValueError(f"{name}: not an object like the current value")
        for k, old in current.items():
            if k not in value:
                # schemas gives every key a value in the stored deck; the
                # reply must echo them all, so the runner merges by replace.
                raise ValueError(f"{name}: the reply lacks the key '{k}'")
            _check_edits_only(value[k], old, f"{name}.{k}")


@dataclass(frozen=True)
class WholeSpec:
    """One slide's write surface: the reviewer edits the deck member `attr`
    as a whole, and the reply must re-validate against `model` (a schemas.py
    model for payload slides, a per-item model for the deck's card lists)."""

    n: int
    label: str
    attr: str
    model: type | None  # None for the string-list slides (team, references)


# The whole write surface, slide number -> spec. Slides 4 and 5 are absent on
# purpose: the buyer profile is copied from research and the verification
# matrix is composed from retrieval scores; a prompt must not rewrite facts.
EDITABLE: dict[int, WholeSpec] = {
    1: WholeSpec(n=1, label="Cover", attr="meta", model=Meta),
    2: WholeSpec(n=2, label="Cover letter", attr="letter", model=CoverLetter),
    3: WholeSpec(n=3, label="Executive summary", attr="summary",
                 model=ExecutiveSummary),
    6: WholeSpec(n=6, label="Approach and timeline", attr="approach",
                 model=Approach),
    7: WholeSpec(n=7, label="Team", attr="team", model=Consultant),
    8: WholeSpec(n=8, label="References", attr="references", model=Reference),
    9: WholeSpec(n=9, label="Investment and next steps", attr="investment",
                 model=Investment),
}


def rules(label: str, config: Config = DEFAULT) -> str:
    """The system prompt: compose's voice and banned words, scoped to one
    slide's whole value and to the no-new-facts rule."""

    return (
        "You edit one slide at a time of a commercial proposal deck for " +
        config.company_sentence +
        """. Plain, specific, confident English.
The slide is: """ + label + """.
You are given the slide's current value (CURRENT) and one edit instruction
(EDIT); change only what EDIT asks for and keep the rest, item counts and
ids included. Never invent facts, numbers or names the input does not give;
never use these words:
""" + ", ".join(BANNED_WORDS) + """.
Return the slide's complete new value, one JSON value of exactly the same
shape as CURRENT (same keys, same list lengths), nothing else. If EDIT asks
for no change, return JSON null."""
    )


def _strip_fences(text: str) -> str:
    """Tolerate a model that wrapped its value in prose or markdown fences,
    the way compose's own checks do. The value's opening bracket decides the
    slice: a dict reply unwraps from the braces, a list reply from the
    brackets (a list of objects holds braces, so leading '{' would mis-slice
    a list reply wrapped in prose)."""
    brace, bracket = text.find("{"), text.find("[")
    if brace == -1 and bracket == -1:
        return text
    if bracket != -1 and (brace == -1 or bracket < brace):
        start, end = bracket, text.rfind("]")
        if end > start:
            return text[start:end + 1]
    else:
        start, end = brace, text.rfind("}")
        if end > start:
            return text[start:end + 1]
    return text


def _reject(problem: str, raw: str) -> None:
    """One warning per rejected reply — the reviewer's prompt is trusted, the
    reply is quarantined to the log, no partial rewrite ever lands."""
    logger.warning("edit agent rejected reply (%s): %.200s", problem, raw)

## TODO: Find out how to display the error in the UI
class EditAgent:
    """Turns one reviewer prompt into a whole new slide value, or None.

    The llm callable is the same Adapter(other) shape every prose consumer in
    this service takes; edit_runner builds it with _llm() like main does.
    """

    def __init__(self, llm: Adapter, config: Config = DEFAULT):
        self.llm = llm
        self.config = config

    def edit(self, spec: WholeSpec, current: Any, prompt: str) -> Any | None:
        """Return the slide's complete new value, or None.

        None means "no change": the model said so, replied with the current
        value back, or everything it wrote was unusable — all leave the deck
        untouched. The reply is checked three ways before it counts: it must
        keep the current shape (same keys, same list lengths), it must pass
        the slide's schemas.py model, and it must hold no blank string; one
        failure rejects the whole reply.
        """
        system = rules(spec.label, self.config)

        logger.info("label=%s config=%s rules=%s", spec.label, self.config, system)
        user = (f"CURRENT = {json.dumps(current, ensure_ascii=False, default=str)}\n"
                f"EDIT = {prompt}")  # the reviewer's own words, user role only

        logger.info("user prompt=%s", user)

        ## Returns llm output
        raw = str(self.llm(system, user))
        logger.info("raw llm resp=%s", raw)
        
        try:
            stripped = _strip_fences(raw)
            logger.info("stripped=%s", stripped)
            data = json.loads(stripped)
        except ValueError:
            _reject("not valid JSON", raw)
            return None
        if data is None:  # explicit no-change
            return None
        try:
            ## Recursively check dtypes of current and editted attributes
            _check_edits_only(data, current)

            ## Recursively check if the fields are empty or not.
            _check_no_blanks(data)
        except ValueError as e:
            _reject(f"shape mismatch: {e}", raw)
            return None
        try:
            ## Deserialize llm response into python dtype
            if isinstance(current, list):
                out = [spec.model.model_validate(item).model_dump()
                       for item in data]
            else:
                out = spec.model.model_validate(data).model_dump()
        except ValueError as e:
            _reject(f"invalid value: {e}", raw)
            return None
        
        if out == current:
            logger.info("edit agent echoed the current value (slide %d); "
                        "treated as no change: %.200s", spec.n, raw)
            return None
        
        ## Compare and check what changed
        changed = [k for k, v in out.items() if v != current.get(k)] \
            if isinstance(out, dict) else None
        logger.info("edit agent rewrote slide %d (%s): %s",
                    spec.n, spec.label,
                    ", ".join(changed) if changed else "items updated")
        
        return out


def _llm() -> Adapter:
    """Same rule as main._llm: the adapter transport only when a URL is set,
    PROPOSAL_LLM_URL winning over the shared LLM_URL (every PROPOSAL_LLM_*
    override wins the same way); whole-slide edits still get the doubled
    max_tokens room and the low reasoning effort the measured runs used."""
    if os.environ.get("PROPOSAL_LLM_URL") or os.environ.get("LLM_URL"):
        return Adapter(call=openai_call(2048, "low"))
    return Adapter()
