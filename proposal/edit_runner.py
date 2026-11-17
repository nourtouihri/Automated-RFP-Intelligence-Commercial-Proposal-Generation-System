"""One prompt-edit against one stored deck.

edit_proposal is the worker main.prompt_edit_proposal awaits: it loads the
deck from the shared store, resolves the slide's write surface from
edit_agent.EDITABLE, hands the slide's whole value to the agent, replaces it
with the agent's whole reply, re-validates through the Proposal schema and
saves the whole deck back to the same row. No index: the agent decides from
CURRENT which items the prompt addresses.

Three guards keep a stray rewrite from landing: the reply may not reshape
anything (same keys, same list lengths — enforced in edit_agent), a pillar
may only cite evidence ids the deck itself already shows (same rule
compose's claim check enforces at generation time), and the saved deck is
the one the schema accepts, not whatever the agent produced. Fact and score
fields (slide 1's tender_title, reference, date, sample; the card slides'
cv_id, project_id, score, delivered) are code-owned outright: they are
copied back from the stored deck, so the agent's echo of them never lands.
An explicit no-change leaves the row untouched: no new updated_at stamp,
no save.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import edit_agent
from .compose import InputError
from .schemas import EditProposalRequest, EditProposalResult, NoBid, Proposal
from shared import store
from shared.errors import ApiError, ErrorCode

logger = logging.getLogger(__name__)

# Fields the LLM never owns, copied back from the stored deck: slide 1's
# fact fields by key, and the card slides' per-item fields by position (the
# same policy that keeps slides 4 and 5 out of EDITABLE).
OWNED: dict[int, tuple[str, ...]] = {
    1: ("tender_title", "reference", "date", "sample"),
    7: ("cv_id", "score"),
    8: ("project_id", "score", "delivered"),
}


def edit_proposal(tender_id: str, req: EditProposalRequest,
                  token: str = "") -> EditProposalResult:
    """Resolve the slide spec, run the agent, apply, save; see module docstring.

    token is accepted for endpoint-signature parity (the endpoint already
    checked require_internal_token) but unused here.
    """
    spec = edit_agent.EDITABLE.get(req.slide)
    if spec is None:
        # Slides 4 (buyer profile) and 5 (verification matrix) plus anything
        # off-deck are code-owned: no prompt rewrite, no agent call.
        raise InputError(f"slide {req.slide} has no prompt-editable fields")

    deck = store.get_deck_by_tender_id(tender_id)

    if deck is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No deck generated for tender",
                       status_code=404)

    if isinstance(deck, NoBid):
        # The no-bid deck is three code-written slides; there is nothing the
        # agent's prose could address without inventing a bid.
        raise InputError("Cannot edit no-bid deck.")

    d = deck.model_dump()
    current = d[spec.attr]

    logger.info("Attribute= %s, Value= %s", spec.attr, current)
    updated = edit_agent.EditAgent(edit_agent._llm()).edit(
        spec, current, req.prompt
    )

    ## If nothin changed, return this
    if updated is None:
        return EditProposalResult(updated=None, changed=False)

    ## Ask why this code here exists. Why not save proposal && return the change right here and there
    d[spec.attr] = _restore_owned(spec.n, updated, current)
    _guard_evidence(spec.n, d)

    out = Proposal.model_validate(d)
    out.updated_at = datetime.now(timezone.utc)
    # review_status explicitly carried over: save_proposal on update keeps it,
    # and a regenerated review cycle must not reset a reviewer's decision.
    store.save_deck(tender_id, out, review_status=out.review_status)
    return EditProposalResult(updated=updated, changed=True)


def _restore_owned(n: int, updated: Any, current: Any) -> Any:
    """Copy the code-owned fields back from the stored deck: slide 1's fact
    keys, card lists per item position (_check_edits_only pins the list
    lengths, so positions match). Any value the agent's reply wrote there is
    discarded, and every divergence from the stored value is logged."""
    if n == 1:
        for field in OWNED[1]:
            if updated[field] != (old := current.get(field)):
                logger.warning(
                    "slide 1: agent reply wrote the code-owned field '%s' "
                    "(%r over the stored %r); restored from the deck",
                    field, updated[field], old)
                updated[field] = old
        return updated
    if n not in (7, 8):
        return updated
    for i, (new, old) in enumerate(zip(updated, current)):
        for field in OWNED[n]:
            if new.get(field) != old.get(field):
                logger.warning(
                    "slide %d item %d: agent reply wrote the code-owned "
                    "field '%s' (%r over the stored %r); restored",
                    n, i, field, new.get(field), old.get(field))
                new[field] = old.get(field)
    return updated


def _guard_evidence(n: int, d: dict[str, Any]) -> None:
    """A pillar may only cite ids the deck itself already shows: matrix rows,
    team cards, reference cards. Anything else is an unsupported claim — the
    same rule compose's claim check enforces at generation time."""
    if n != 3:
        return
    claimed = [id_ for p in d["summary"]["pillars"]
               for id_ in p.get("evidence", [])]
    known = _known_evidence_ids(d)
    unknown = sorted(set(claimed) - known)
    if unknown:
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            "evidence cites ids the deck does not hold: " + ", ".join(unknown),
            status_code=400)


def _known_evidence_ids(d: dict[str, Any]) -> set[str]:
    rows = d["all_requirements"] or d["requirements"]
    ids = {r["evidence_id"] for r in rows if r.get("evidence_id")}
    ids |= {c["cv_id"] for c in d["team"] if c.get("cv_id")}
    ids |= {r["project_id"] for r in d["references"] if r.get("project_id")}
    return ids
