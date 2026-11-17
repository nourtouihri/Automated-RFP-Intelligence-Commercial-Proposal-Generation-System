"""Proposal API. All endpoints except /health require X-Internal-Token.

Generates the proposal deck (or no-bid deck) for a stored tender. The caller
(n8n, after detection, research and RAG) posts the two team match lists in the
body; each hit already embeds its source record in metadata, so compose() draws
every fact from the posted hits and every number from code. Per-requirement RAG
queries the service runs itself, one per requirement of the tender it loads
from the shared sqlite store.
"""

import asyncio
import dataclasses
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, List

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictBool

from . import render
from .build import DeckRejected, build
from .compose import InputError, StepError, Trace, compose, record_id
from .config import DEFAULT, Config
from .export import to_pdf
from .llm_adapter import Adapter, LLMError, openai_call, same_model_note, verifier_call
from .measure import FontNotFound, font_gaps
from .verifier import Verifier
from .schemas import EditProposalRequest, EditProposalResult, NoBid, Proposal,Strict,Signatory
from shared import store
from shared.auth import require_internal_token
from shared.errors import ApiError, ErrorCode, install
from .edit_runner import edit_proposal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


load_dotenv()

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.environ.get("PROPOSAL_OUTPUT_DIR", "/data/proposals"))
RAG_URL = os.environ.get("RAG_URL", "http://rag:8001")
# Tender ids become file names under OUTPUT_DIR, so anything that escapes the
# directory is refused before the first lookup.
TENDER_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MEDIA_TYPES = {
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    # Font gaps are logged, not fatal: the slim image may lack the brand fonts,
    # and refusing to boot would take the whole service down. build() re-checks
    # per deck, names any substitute in a bid warning, and fails cleanly when no
    # font at all is found.
    for gap in _font_problems():
        logger.warning("proposal template: %s", gap)
    yield


def _font_problems() -> list[str]:
    try:
        gaps = font_gaps((render.FONT, render.HEAD_FONT))
    except FontNotFound as e:
        return [f"fonts missing: {e}; deck builds will fail until fonts are installed"]
    return [f"font not installed: {g}; the PDF may use a substitute" for g in gaps]


app = FastAPI(title="Proposal Deck Service API", lifespan=lifespan)

# Same envelope + X-Request-ID contract as the other services: a caller branches
# on a stable `code`/`retryable` and stitches one trigger's log lines together
# across services, whichever one answered.
install(app)


class DeckSettings(Strict):
    """Per-run overrides of the deck's OliveSoft-specific values (Config). Every
    field is optional; an unset one keeps the default. Unknown fields are refused,
    so a caller cannot invent a parameter the deck does not read."""

    signatory_name: str | None = Field(default=None, min_length=1)
    signatory_role: str | None = Field(default=None, min_length=1)
    signatory_contact: str | None = Field(default=None, min_length=1)
    letter_title: str | None = Field(default=None, min_length=1)
    currency: str | None = Field(default=None, min_length=1)
    day_rate: float | None = Field(default=None, gt=0)
    team_size: int | None = Field(default=None, ge=1)
    investment_note: str | None = Field(default=None, min_length=1)

    def to_config(self) -> Config:
        given = self.model_dump(exclude_none=True)
        overrides = {k: v for k, v in given.items() if not k.startswith("signatory_")}
        signatory = {k.removeprefix("signatory_"): v for k, v in given.items()
                     if k.startswith("signatory_")}
        if signatory:
            overrides["signatory"] = Signatory(
                **{**DEFAULT.signatory.model_dump(), **signatory})
        return dataclasses.replace(DEFAULT, **overrides)


class ProposalRequest(BaseModel):
    """The team matches n8n aggregated for one tender: cv_matches and
    project_matches from the one "Prepare RAG Context" query. Hits carry the
    source record in metadata (rag.ingest_json embeds it), which is where every
    fact is read from. The per-requirement hits are the service's own job: one
    RAG query per tender requirement, built by _requirement_matches().
    """

    cv_matches: list[dict] = Field(default_factory=list)
    project_matches: list[dict] = Field(default_factory=list)
    settings: DeckSettings | None = None
    # Bid on a tender the retrieval gate would answer with a no-bid; spends model budget.
    force_bid: StrictBool = False
    # Also check every written sentence for claims its sources do not contain.
    claim_check: StrictBool = False
    # Optional human resolution of a research-sector conflict.
    sector: str | None = Field(default=None, min_length=1)


SectionId = Literal["letter", "summary", "buyer", "matrix", "approach", "team",
                    "references", "investment", "warnings"]


class Review(Strict):
    """Reviewer state for one stored deck. The sign-off is a typed name, not an
    account; deck_generated_at ties it to the deck it was made on."""

    deck_generated_at: str=""
    sections: dict[SectionId, Literal["draft", "review", "approved", "work"]] = {}
    signed_off_by: str | None = Field(default=None, min_length=1, max_length=80)
    signed_off_at: str | None = None


class ProposalAcceptResult(BaseModel):
    tender_id: str
    # "rejected": the deck was composed but the validator refused the pptx for
    # slide/cell/palette issues; the composed deck and each issue come back so
    # the caller can show why instead of dead-ending in a 422.
    kind: Literal["proposal", "no_bid", "rejected"]
    deck: dict[str, object]
    warnings: list[str] = []
    artifacts: dict[str, str | None] = {}
    # What actually ran on this deck; {} for a result stored before checks were reported.
    checks: dict[str, bool] = {}
    # compose()'s per-step record; [] for a result stored before the trace was returned.
    trace: list[dict] = []
    generated_at: str


class ProposalRefuseResult(BaseModel):
    """What a refusal changes: the stored row's review state. The deck itself,
    its warnings and its artifact index stay exactly as they were saved."""

    tender_id: str
    kind: Literal["proposal", "no_bid"]
    review_status: Literal["refused"]


class ProposalResult(BaseModel):
    body: str


class ProposalListItem(BaseModel):
    """One stored deck row for the review screen: row identity plus the deck.

    The deck model has no tender_id of its own (the row key identifies it),
    and a row's kind is always "no_bid" or "proposal", never "rejected": a
    deck that failed render validation was never stored.
    """

    tender_id: str
    kind: Literal["proposal", "no_bid"]
    review_status: str = "draft"
    warnings: List[str]
    deck: Proposal | NoBid


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _search(client: httpx.Client, token: str, query: str, top_k: int,
            doc_type: str | None) -> list[dict]:
    resp = client.post(f"{RAG_URL}/query",
                       headers={"X-Internal-Token": token},
                       json={"text": query, "top_k": top_k, "doc_type": doc_type})
    if resp.status_code < 400:
        return resp.json()
    if resp.status_code >= 500:
        # A transient dependency fault worth retrying, not a bad request; the
        # message stays generic so no provider detail leaks into the envelope.
        raise ApiError(ErrorCode.UPSTREAM_UNAVAILABLE,
                       f"retrieval unavailable (HTTP {resp.status_code})",
                       status_code=503, retryable=True)
    raise ApiError(ErrorCode.BAD_REQUEST,
                   "RAG rejected the internal token" if resp.status_code == 401
                   else f"retrieval rejected the query (HTTP {resp.status_code})",
                   status_code=400)


def _requirement_matches(client: httpx.Client, token: str,
                         requirements: list[str]) -> dict[str, list[dict]]:
    """One RAG query per tender requirement, the run the matrix scores from:
    compose() labels each row Strong/Partial/Gap from its best hit's similarity
    against the 0.55/0.40 cutoffs, and the no-bid gate needs every row. A too-
    short requirement has nothing the rag /query contract can embed (>= 3
    chars); it gets no hits instead of failing the deck: a Gap row."""
    return {req: _search(client, token, req, 5, None) if len(req.strip()) >= 3 else []
            for req in requirements}


def _create_deck(tender_id: str, body: ProposalRequest, token: str) -> ProposalResult:
    tender = store.get_tender(tender_id)
    if tender is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Tender not found", status_code=404)
    research = store.get_research(tender_id)
    if research is not None and body.sector:
        research = research.model_copy(update={"sector": body.sector})
    td = tender.model_dump()

    with httpx.Client(timeout=60.0) as client:
        requirement_matches = _requirement_matches(client, token, td["requirements"])

    ## TODO: Find the purpose of this line.
    #given = {record_id(h) for hits in (*requirement_matches.values(), body.cv_matches,
    #                                   body.project_matches) for h in hits}
    trace = Trace()
    llm = _llm()
    config = body.settings.to_config() if body.settings else DEFAULT
    verifier_model, judge = verifier_call()
    verifier = Verifier(judge=judge, model=verifier_model) if judge is not None else None
    try:
        # records=None: every fact comes from the hit metadata the caller embedded.
        deck = compose(td, research.model_dump() if research else None,
                       requirement_matches, body.cv_matches, body.project_matches,
                       llm, records=None, trace=trace, config=config,
                       claim_check=body.claim_check, verifier=verifier,
                       force_bid=body.force_bid)
    except StepError as e:
        # The reply that made the step fail is exactly what a diagnosis needs:
        # the adapter records every reply it successfully fetched, including
        # the rejects run_step retried on, so the last one is the offender.
        # Without this the caller gets a blind 503 and the reply is lost.
        if llm.calls:
            logger.warning("proposal %s: %s; last reply: %.400s", tender_id, e,
                           str(llm.calls[-1].get("reply", "")))
        raise
    ## The Proposal gets saved in DB, for review
    ## Defailt review_status = "draft"
    store.save_deck(tender_id, deck, trace=trace.steps)
    ## Then returns result
    return ProposalResult(body="Proposal Saved for review")



def _generate_pptx_and_pdf_from_deck(tender_id: str, deck:Proposal | NoBid) -> ProposalAcceptResult:
    ## Here, the deck gets prepped to be rendered as pptx
    trace = Trace()
    verifier_model, judge = verifier_call()
    verifier = Verifier(judge=judge, model=verifier_model) if judge is not None else None
    checks = _checks(deck, verifier=verifier, trace=trace)
    notes = _verifier_notes(deck, verifier_model, verifier)
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        built = build(deck, OUTPUT_DIR / f"{tender_id}.pptx",trace=trace)
    except DeckRejected as e:
        # The validator gate means "no pptx written", not "call failed": the
        # composition itself succeeded, so the caller gets a 200 with the
        # composed deck and each issue in warnings. Nothing is stored.
        warnings = [f"no deck written: {i}" for i in e.issues] + notes
        logger.warning("proposal %s: deck rejected: %s", tender_id, e.issues)
        return ProposalAcceptResult(
            tender_id=tender_id, kind="rejected", deck=deck.model_dump(),
            warnings=warnings, artifacts={}, checks=checks, trace=trace.steps,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

    artifacts: dict[str, str | None] = {"pptx": built.path.name, "csv": built.csv.name,
                                        "pdf": None}
    try:
        artifacts["pdf"] = to_pdf(built.path).name
    except (FileNotFoundError, OSError, RuntimeError) as e:
        # LibreOffice absent or slow: the pptx and CSV exist and are valid; only
        # the PDF conversion is skipped, the same way the demo reports it.
        built.warnings.append(f"PDF skipped: {e}")
    built.warnings.extend(notes)
    result = ProposalAcceptResult(
        tender_id=tender_id,
        kind="no_bid" if isinstance(deck, NoBid) else "proposal",
        deck=deck.model_dump(),
        warnings=built.warnings,
        artifacts=artifacts,
        checks=checks,
        trace=trace.steps,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


    ## Save deck's metadata (not the deck itself, since it's already saved)
    #store.save_deck(deck, checks=checks, warnings=built.warnings, artifacts=artifacts)
    return result

def _checks(deck, body: ProposalRequest | None = None, verifier: Verifier | None = None,
            trace: Trace | None = None) -> dict[str, bool]:
    """What actually ran. A no-bid makes no model call, so nothing ran. The
    verifier counts as run only when it delivered a verdict and no step's judge
    failed; a judge that could not answer shows as "grounding check unavailable"
    warnings, and "ran" would then overstate the check."""
    trace = trace or Trace()
    if isinstance(deck, NoBid):
        return {"verifier": False, "claim_check": False}
    entries = [s["verifier"] for s in trace.steps if "verifier" in s]
    delivered = any(isinstance(e, list) and e for e in entries)
    failed = any(isinstance(e, dict) for e in entries)
    return {"verifier": verifier is not None and delivered and not failed,
            "claim_check": body.claim_check if body is not None else False}


def _verifier_notes(deck, model: str | None, verifier: Verifier | None) -> list[str]:
    """The same-model note, only where a judge could have run (not on a no-bid)."""
    note = same_model_note(model) if verifier is not None and not isinstance(deck, NoBid) else None
    return [note] if note else []

# A run spends RAG, LLM and LibreOffice budget on one tender; single-flight
# shares the running task among concurrent triggers the way research does.
_async_locks: dict[str, asyncio.Task] = {}


def _llm() -> Adapter:
    """The model transport the deck's prose steps run against.

    detection's llm_call, the default, caps every reply at max_tokens=1024 —
    reasoning models can spend that entire budget on thinking and return prose
    or nothing, which fails the JSON checks ("no JSON object in the reply").
    The adapter's own request, the transport every measured run used, doubles
    the room and lowers the reasoning effort. It speaks the OpenAI-compatible
    wire, so it only applies when a URL is set: PROPOSAL_LLM_URL wins over the
    shared LLM_URL (same rule for every PROPOSAL_LLM_* override); with both
    unset, anthropic/openai provider defaults keep the default transport."""
    if os.environ.get("PROPOSAL_LLM_URL") or os.environ.get("LLM_URL"):
        return Adapter(call=openai_call(2048, "low"))
    return Adapter()


def _verifier() -> tuple[Verifier | None, str | None]:
    """The grounding judge and its note, or (None, note) when it is off. Needs
    PROPOSAL_VERIFIER_LLM_MODEL; it deliberately never falls back to the
    writer's model - a same-model check is no different-model guard. The
    judge's own failures reach warnings through compose and the trace and do
    not fail the deck; a verdict that exists is never retried."""
    model, adapter = verifier_call()
    if adapter is None:
        return None, "verifier: off (no PROPOSAL_VERIFIER_LLM_MODEL)"
    return Verifier(judge=adapter, model=model), same_model_note(model)


@app.post("/proposal/{tender_id}", response_model=ProposalResult)
async def run_proposal(
    tender_id: str,
    body: ProposalRequest,
    token: str = Depends(require_internal_token),
) -> ProposalResult:
    """Creates a deck (either a proposal or a NoBid) based on the provided tender_id"""
    if not TENDER_ID_RE.fullmatch(tender_id):
        raise ApiError(ErrorCode.BAD_REQUEST, "invalid tender id", field="tender_id",
                       status_code=400)
    if tender_id in _async_locks:
        return await _async_locks[tender_id]
    task = asyncio.create_task(asyncio.to_thread(_create_deck, tender_id, body, token))
    _async_locks[tender_id] = task
    try:
        return await task
    except InputError as e:
        # Raised before any model call, for a tender without title, issuer or
        # requirements, or a malformed hit (no metadata.record_id, similarity
        # outside 0..1): the caller's data, not the provider's.
        raise ApiError(ErrorCode.BAD_REQUEST, str(e), status_code=400) from e
    except FontNotFound as e:
        # No font at all: the deck would be rendered blind; fixing is an
        # operator task (install fonts), so not retryable.
        raise ApiError(ErrorCode.INTERNAL, f"no deck written: {e}", status_code=500,
                       retryable=False) from e
    except (StepError, LLMError) as e:
        # The compose steps and the adapter retry first; what escapes here is a
        # provider fault the caller can re-trigger, not a bad tender.
        raise ApiError(ErrorCode.UPSTREAM_UNAVAILABLE, str(e), status_code=503,
                       retryable=True) from e
    finally:
        _async_locks.pop(tender_id, None)


class GetDeckResponse(BaseModel):
    tender_id: str
    kind: Literal["proposal", "no_bid", "rejected"]
    #deck: dict[str, object]
    deck: Proposal | NoBid
    warnings: list[str] = []
    artifacts: dict[str, str | None] = {}
    # What actually ran on this deck; {} for a result stored before checks were reported.
    checks: dict[str, bool] = {}
    # compose()'s per-step record; [] for a result stored before the trace was returned.
    trace: list[dict] = []
    generated_at: str

@app.get("/proposal/{tender_id}", response_model=GetDeckResponse)
def get_stored_proposal(
    tender_id: str,
    _token: str = Depends(require_internal_token),
) -> GetDeckResponse:
    """Fetches stored proposal"""
    if not TENDER_ID_RE.fullmatch(tender_id):
        raise ApiError(ErrorCode.BAD_REQUEST, "invalid tender id", field="tender_id",
                       status_code=400)
    res, artifacts, checks, trace = store.get_deck_by_tender_id_and_metadata(tender_id)
    if res is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No deck found for tender "+tender_id, status_code=404)
    return GetDeckResponse(
        tender_id=tender_id,
        kind="proposal" if isinstance(res, Proposal) else "no_bid",
        artifacts=artifacts,
        checks=checks,
        trace=trace,
        deck=res,
        warnings=res.input_warnings,
        generated_at=res.updated_at.isoformat()
    )

@app.get("/proposal/{tender_id}/files/{name:path}")
def get_proposal_file(
    tender_id: str,
    name: str,
    _token: str = Depends(require_internal_token),
) -> FileResponse:
    """This fetches the files associated to proposals.
    For now, we only fetch those of accepted proposals because they are the only ones who get their files generated
    """
    if not TENDER_ID_RE.fullmatch(tender_id):
        raise ApiError(ErrorCode.BAD_REQUEST, "invalid tender id", field="tender_id",
                       status_code=400)
    not_found = ApiError(ErrorCode.NOT_FOUND, "File not found", status_code=404)
    # Only accepted decks have generated files, and only a name the row's
    # artifact index lists is served: the sqlite store itself and anything
    # else under OUTPUT_DIR are never reachable, and a listed name that
    # resolves outside OUTPUT_DIR is refused as well.

    ## TODO: This should also fetch No-Bid, so I set
    stored = store.get_deck_by_tender_id_and_review_status(tender_id, "accepted")
    if stored is None:
        raise not_found
    artifacts = store.get_deck_artifacts(tender_id) or {}
    if name not in {v for v in artifacts.values() if v}:
        raise not_found
    path = (OUTPUT_DIR / name).resolve()
    if path.parent != OUTPUT_DIR.resolve() or not path.is_file():
        raise not_found
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise not_found
    return FileResponse(path, media_type=media_type, filename=path.name,
                        content_disposition_type="attachment")

def _review_path(tender_id: str) -> Path:
    return OUTPUT_DIR / "reviews" / f"{tender_id}.json"


def _stored_review(tender_id: str) -> Review | None :
    path = _review_path(tender_id)
    if not path.is_file():
        return None
    try:
        return Review.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        logger.warning("ignoring unreadable review file %s", path.name)
        return None


@app.get("/proposal/{tender_id}/review", response_model=Review)
def get_review(
    tender_id: str,
    _token: str = Depends(require_internal_token),
) -> Review:
    res = _stored_review(tender_id)
    if(res is None):
        raise ApiError(ErrorCode.NOT_FOUND, "Review on "+ tender_id+" proposal doesn't exist")
    
    return res


@app.put("/proposal/{tender_id}/review", response_model=Review)
def put_review(
    tender_id: str,
    body: Review,
    _token: str = Depends(require_internal_token),
) -> Review:
    """This is for storing the review metadata (signed when and by who, )"""
    deck = store.get_deck_by_tender_id(tender_id)
    if(deck is None):
        raise ApiError(ErrorCode.NOT_FOUND, "Deck of id="+tender_id+" doesn't exist", status_code=404)
    ## TODO: Removed this. Dunno what this would entail.
    # try:
    #     token = datetime.fromisoformat(body.deck_generated_at.replace("Z", "+00:00"))
    # except ValueError:
    #     token = None

    # if token is None or token != deck.updated_at:
    #     raise ApiError(ErrorCode.BAD_REQUEST, "The deck was edited; reload the review",
    #                    status_code=409)
    previous = _stored_review(tender_id)
    if body.signed_off_by is None:
        signed_at = None
    elif previous and previous.signed_off_by == body.signed_off_by and previous.signed_off_at:
        signed_at = previous.signed_off_at
    else:
        signed_at = datetime.now(timezone.utc).isoformat()
    saved = body.model_copy(update={"signed_off_at": signed_at})

    ## This uses file storage to store review signature of each slide
    target = _review_path(tender_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(saved.model_dump_json(), encoding="utf-8")
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return saved


@app.get("/proposal", response_model=List[ProposalListItem])
def list_proposals(
    _token: str = Depends(require_internal_token),
) -> List[ProposalListItem]:
    """Every stored deck with its row identity, newest first."""
    return store.list_decks_entries()

## If the proposal is accepted, it continues the previous halted workflow of _generate_backeup

## The first endpoint is PUT /proposal/edit/{proposal_id}. It includes in the body which slide to change, proposal_id, and the prompt.
## It should return string representing the result of the prompt (the modified value)
@app.put("/proposal/edit/{tender_id}", response_model=EditProposalResult)
async def prompt_edit_proposal(
    tender_id: str,
    body: EditProposalRequest,
    token: str = Depends(require_internal_token),
) -> EditProposalResult:
    if not TENDER_ID_RE.fullmatch(tender_id):
        raise ApiError(ErrorCode.BAD_REQUEST, "invalid tender id", field="tender_id",
                       status_code=400)
    if tender_id in _async_locks:
        return await _async_locks[tender_id]
    task = asyncio.create_task(asyncio.to_thread(edit_proposal, tender_id, body, token))
    _async_locks[tender_id] = task
    try:
        return await task
    except InputError as e:
        # Raised before any model call, for a tender without title, issuer or
        # requirements, or a malformed hit (no metadata.record_id, similarity
        # outside 0..1): the caller's data, not the provider's.
        raise ApiError(ErrorCode.BAD_REQUEST, str(e), status_code=400) from e
    except FontNotFound as e:
        # No font at all: the deck would be rendered blind; fixing is an
        # operator task (install fonts), so not retryable.
        raise ApiError(ErrorCode.INTERNAL, f"no deck written: {e}", status_code=500,
                       retryable=False) from e
    except (StepError, LLMError) as e:
        # The compose steps and the adapter retry first; what escapes here is a
        # provider fault the caller can re-trigger, not a bad tender.
        raise ApiError(ErrorCode.UPSTREAM_UNAVAILABLE, str(e), status_code=503,
                       retryable=True) from e
    finally:
        _async_locks.pop(tender_id, None)

## the PUT /proposal/accept/{tender_id}. No body, just that.
## It changes fetches the stored proposal by tender_id and kind = proposal and review_status = draft.
## Then it sets its review_status to accepted, generates the pptx and pdf (uses build and to_pdf inside _generate_backup method) They should be as sophisticated as it is.
@app.put("/proposal/accept/{tender_id}", response_model=ProposalAcceptResult)
async def accept_proposal(
    tender_id: str,
    token: str = Depends(require_internal_token),
) -> ProposalAcceptResult:
    """Accept a stored proposal: mark it accepted, then regenerate pptx + pdf.
    This just flags that the deck has pptx/pdf.
    """
    
    if not TENDER_ID_RE.fullmatch(tender_id):
        raise ApiError(ErrorCode.BAD_REQUEST, "invalid tender id", field="tender_id",
                       status_code=400)

    stored = store.get_deck_by_tender_id_and_review_status(tender_id)
    if stored is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No stored draft proposal to accept", status_code=404)
    
    ## TODO: No-bid can be accepted (a status for generating pptx)
    # if not isinstance(stored, Proposal):
    #     raise ApiError(ErrorCode.BAD_REQUEST, "Only a proposal deck can be accepted",
    #                    status_code=400)
    if stored.review_status != "draft":
        raise ApiError(ErrorCode.BAD_REQUEST, f"Proposal already {stored.review_status}",
                       status_code=409)

    # Generate pptx & pdf off the event loop: the build plus the LibreOffice
    # conversion are synchronous and take seconds.
    result = await asyncio.to_thread(_generate_pptx_and_pdf_from_deck, tender_id, stored)

    ## There are problems in building the deck, so it gets rejected
    if result.kind == "rejected":
        # Nothing valid was written; the deck stays "draft" so a corrected
        # retry is accepted instead of blocked by the status guard above.
        return result

    # Save: status flip plus the artifact index the /files endpoint serves
    # from. Without artifacts= the generated pptx/pdf would exist on disk
    # but be unreachable.

    store.save_deck(tender_id, stored, review_status="accepted",
                        warnings=result.warnings, artifacts=result.artifacts,
                        checks=result.checks, trace=result.trace)    
    return result


## the PUT /proposal/refuse/{tender_id}. No body, just that.
## It fetches the stored deck (a Proposal or a NoBid) by tender_id and flips its
## review_status to refused. Nothing else is touched: no pptx/pdf is built and
## warnings/artifacts stay as they were saved (save_deck COALESCEs them).
@app.put("/proposal/refuse/{tender_id}", response_model=ProposalRefuseResult)
def refuse_proposal(
    tender_id: str,
    _token: str = Depends(require_internal_token),
) -> ProposalRefuseResult:
    """Refuse a stored proposal or no-bid deck: set review_status to refused."""

    if not TENDER_ID_RE.fullmatch(tender_id):
        raise ApiError(ErrorCode.BAD_REQUEST, "invalid tender id", field="tender_id",
                       status_code=400)

    stored = store.get_deck_by_tender_id(tender_id)
    if stored is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No stored proposal to refuse",
                       status_code=404)
    if stored.review_status == "refused":
        raise ApiError(ErrorCode.BAD_REQUEST, f"Proposal already {stored.review_status}",
                       status_code=409)
    if stored.review_status !="draft":
        raise ApiError(ErrorCode.BAD_REQUEST, f"Deck id={tender_id} isn't of draft status" ,
                       status_code=409)
    store.save_deck(tender_id, stored, review_status="refused")
    return ProposalRefuseResult(
        tender_id=tender_id,
        kind="no_bid" if isinstance(stored, NoBid) else "proposal",
        review_status="refused")



## Note that proposal_id is the same as tender_id.
