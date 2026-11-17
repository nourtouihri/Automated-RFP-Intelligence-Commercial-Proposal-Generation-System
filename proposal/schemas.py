"""Data contract for one commercial proposal deck.

Fields fall in two groups. Facts (scores, names, statuses, buyer profile)
are copied in by code from detection, research and RAG output; the LLM
never writes them. Prose (letter, summary, needs, phases) is written by the
LLM, and every prose item that makes a claim must cite the evidence ids it
rests on so the validator can reject unsupported claims.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime, timezone
# Empty research fields render as this marker instead of a guess.
UNKNOWN = "Not available"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Meta(Strict):
    buyer: str
    tender_title: str
    reference: str
    date: str
    # Limits measured against the slide boxes (feasibility/run_feasibility.py):
    # at these lengths text fits at full size or after at most a 20% shrink.
    headline: str = Field(max_length=60)
    subtitle: str = Field(max_length=80)
    sample: bool = False  # adds "Sample" to the footer and cover kicker


class Signatory(Strict):
    name: str
    role: str
    contact: str


class CoverLetter(Strict):
    salutation: str
    paragraphs: list[Annotated[str, Field(max_length=220)]] = Field(min_length=1, max_length=2)
    closing: str
    title: str


class Pillar(Strict):
    title: str = Field(max_length=28)
    body: str = Field(max_length=110)
    evidence: list[str] = []


class ExecutiveSummary(Strict):
    title: str = Field(max_length=53)
    pillars: list[Pillar] = Field(min_length=3, max_length=3)
    why_us: str = Field(max_length=190)


class BuyerProfile(Strict):
    """Copied from the research record; compose() estimates the missing values."""

    sector: str = UNKNOWN
    estimated_revenue: str = UNKNOWN
    key_partners: str = UNKNOWN


class Need(Strict):
    title: str = Field(max_length=40)
    body: str = Field(max_length=120)


class BuyerUnderstanding(Strict):
    profile: BuyerProfile
    needs: list[Need] = Field(min_length=1, max_length=3)
    researched: bool = True  # False: no usable research; the slide must not claim any


Fit = Literal["Strong", "Partial", "Gap"]


class RequirementRow(Strict):
    requirement: str
    evidence: str
    score: float = Field(ge=0, le=1)
    evidence_id: str | None = None  # None means nothing was retrieved

    @property
    def fit(self) -> Fit:
        return fit_for(self.score)


# Thresholds on RAG similarity (all-MiniLM-L6-v2 cosine). Kept in code, not
# the prompt, so the label is reproducible from the score shown next to it.
# Calibrated on real retrieval (feasibility/): at >= 0.55 the hit genuinely
# supported the requirement in 14 of 16 rows (2 partly) and was never wrong;
# 0.40-0.55 is mixed and needs a human check; below 0.40 it was the wrong asset
# in 10 of 17 rows.
STRONG_AT = 0.55
PARTIAL_AT = 0.40


def fit_for(score: float) -> Fit:
    if score >= STRONG_AT:
        return "Strong"
    if score >= PARTIAL_AT:
        return "Partial"
    return "Gap"


class Phase(Strict):
    name: str = Field(max_length=20)
    weeks: int = Field(ge=1)
    body: str = Field(max_length=100)


class Approach(Strict):
    title: str
    phases: list[Phase] = Field(min_length=2, max_length=4)
    milestones: str


class Consultant(Strict):
    cv_id: str | None  # None: no CV was retrieved and this card is a placeholder
    name: str
    role: str
    years: int | None = None  # not in the RAG metadata; from the CV record
    skills: str
    score: float = Field(ge=0, le=1)


class Reference(Strict):
    project_id: str | None  # None: no project was retrieved and this card is a placeholder
    title: str
    summary: str
    sector: str
    score: float = Field(ge=0, le=1)
    delivered: bool | None  # from the project record's status, never the LLM; None: unverified


class PriceLine(Strict):
    workstream: str
    days: float | None = None
    amount: float | None = None


class NextStep(Strict):
    title: str
    detail: str


class Investment(Strict):
    currency: str
    lines: list[PriceLine]
    note: str
    next_steps: list[NextStep] = Field(min_length=1, max_length=3)


# Rows the matrix slide can show; a tender with more requirements is ranked by score
# and the rest go to the CSV (compose.py).
MATRIX_ROWS = 7


class Proposal(Strict):
    meta: Meta ## Slide 1
    review_status: Literal["accepted","refused","draft"] ="draft"
    signatory: Signatory
    letter: CoverLetter ## Slide 2
    summary: ExecutiveSummary ## Slide 3
    buyer: BuyerUnderstanding ## Slide 4

    ## Slide 5
    requirements: list[RequirementRow] = Field(min_length=1, max_length=MATRIX_ROWS)
    all_requirements: list[RequirementRow] = []  # every requirement, shown or not (the CSV)

    approach: Approach ## Slide 6
    team: list[Consultant] = Field(min_length=1, max_length=3) ## Slide 7
    references: list[Reference] = Field(min_length=1, max_length=3) ## Slide 8
    investment: Investment ## Slide 9

    input_warnings: list[str] = []  # tender, research and speed-promise checks: for sales, not the deck
    estimated: list[str] = []  # field paths filled by a formula (estimate.py), for a reviewer to re-check

    updated_at: datetime | None = None
    created_at: datetime | None = None

class NoBid(Strict):
    """What compose() returns when no requirement reaches Partial: a short deck
    (cover, matrix, warnings) and no prose from the model."""

    meta: Meta
    requirements: list[RequirementRow] = Field(min_length=1, max_length=MATRIX_ROWS)
    all_requirements: list[RequirementRow] = []
    review_status: str ="draft"#Literal["accepted"] ="accepted"

    ## Slide 3
    input_warnings: list[str] = []
    recommendation: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


# --- the PUT /proposal/edit/{tender_id} contract: what the reviewer sends and
# what the edit claims to have changed (proposal/edit_agent.py enforces it) ---

class EditProposalRequest(Strict):
    """One reviewer prompt addressed to one slide of a stored deck.

    `slide` is the deck's 1-based slide number (render order) and `prompt` is
    the reviewer's instruction; the agent decides from the slide's current
    value which items the prompt addresses and returns the slide's complete
    new value (same shape, same list lengths — no index to get wrong).
    """

    slide: int = Field(ge=1, le=9)
    prompt: str = Field(min_length=1, max_length=2000)


class EditProposalResult(Strict):
    """The slide's complete new value a prompt produced and whether anything
    changed at all (changed=False: the agent answered "no change" or only
    unusable rewrites, and the stored deck was left untouched)."""

    updated: Any = None
    changed: bool = False