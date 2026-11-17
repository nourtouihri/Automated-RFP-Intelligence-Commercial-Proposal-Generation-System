from datetime import date, datetime, timezone
from typing import Literal, Optional, List, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Edit here if team skills change detection and agent both import this.
# These are OliveSoft's five published service lines, in the order they should
# win a tagging tie (earlier wins). Sector tagging targets work being bought,
# not the buyer's industry — that is ProspectResearch.sector, derived from the
# web by the agent and deliberately not constrained by this list.
CAPABILITY_TAXONOMY: list[str] = [
    "Data Integration",
    "AI Development",
    "BI & Dashboarding",
    "Salesforce Ecosystem",
    "Data Platform",
]

class DataQuality(BaseModel):
    """Ingest-boundary quality report, surfaced in every tender response.

    ``warnings`` is the machine-readable flag list (missing_deadline,
    sanitized_chars, llm_unavailable, possible_duplicate_of:<id>, ...) that
    turns a degraded-but-accepted ingest into something observable instead of
    silent. ``status == "incomplete"`` tells n8n to hold the record back until
    a human or a later feed fills the gaps.
    """

    model_config = ConfigDict(strict=True)

    completeness: float = 1.0
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    is_expired: bool = False


# @Todo: Remove comments
class Tender(BaseModel):
    model_config = ConfigDict(strict=True)

    id: str
    title: str
    issuer: str           # explicit, never inferred
    sector: str           # tagged against CAPABILITY_TAXONOMY; "unknown" when no match
    requirements: list[str]
    deadline: date | None = None  # optional: a missing deadline degrades to `incomplete`
    raw_text: str         # size cap enforced in normalize.py (20_000 chars); "" when absent
    source: Literal["simulated_feed", "manual", "TED", "SAM"]
    detected_at: datetime
    status: Literal["new", "incomplete", "processed", "archived"]
    issuer_country: str | None = None
    notice_type: str | None = None
    published_at: date | None = None
    links: list[str] = Field(default_factory=list)
    quality: DataQuality = Field(default_factory=DataQuality)


class Fact(BaseModel):
    model_config = ConfigDict(strict=True)

    # max_length bounds the injection surface: an attacker-controlled page
    # cannot smuggle arbitrarily large payloads through a single fact, and
    # the extractor prompt already asks for spans under 200 characters.
    value: str = Field(min_length=1, max_length=500)
    category: Literal["sector", "estimated_revenue", "past_projects", "key_partners"]
    confidence: Literal["low", "medium", "high"]

    @field_validator("value")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        # A blank fact is noise, and an attacker could pad facts=[] with empty
        # entries to make sparse output look evidence-rich.
        stripped = v.strip()
        if not stripped:
            raise ValueError("fact value must not be blank")
        return stripped


class ResearchFact(Fact):
    """A fact with the page the runner fetched it from (never a page-claimed URL)."""

    source: str = Field(min_length=1)


class ExtractorOutput(BaseModel):
    """Strict schema for the Quarantined Extractor. No other output allowed."""

    # extra="forbid" is a contract boundary, not pedantry. To be precise about
    # the threat: the old default (ignore) was NOT an exploitable hole here,
    # because nothing downstream ever read an undeclared key, so a smuggled
    # "command" or "source_url" could not reach the runner. What forbidding
    # buys is that an unrecognised key is now *observable* rather than silently
    # discarded -- so a model that starts emitting a different shape shows up
    # as a hard failure at this boundary instead of quietly drifting.
    #
    # The tradeoff is real: this is fail-closed, so a model that adds one
    # harmless "summary" key loses ALL facts for that snippet. That is why
    # research/tools/llm_contract_probe.py exists -- it detects exactly this
    # drift against the live model, which a fully mocked test suite cannot.
    model_config = ConfigDict(strict=True, extra="forbid")

    # Empty list, never null: "no fact found" is facts=[].
    facts: List[Fact]

ResearchStatus = Literal["complete", "partial", "unavailable"]


class ProspectResearch(BaseModel):
    """Final output of the Agentic Prospect Research."""

    model_config = ConfigDict(strict=True)
    tender_id: str
    issuer: str
    sector: str | None
    estimated_revenue: str | None
    past_projects: list[str]
    key_partners: list[str]
    notes: str
    confidence: Literal["low", "medium", "high"]  # computed by runner.py, not the model
    sources: list[str]  # only URLs that contributed a fact, not every URL searched
    status: ResearchStatus | None = None
    completed_at: datetime | None = None
    facts: list[ResearchFact] = []

class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=3, max_length=10_000)
    top_k: int = Field(default=5, ge=1, le=20)
    doc_type: Literal["cv", "project", "tool"] | None = None
    similarity_threshold: float = Field(default=0.0, ge=0.0, le=1.0)


class QueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    content: str
    doc_type: Literal["cv", "project", "tool"]
    source_file: str
    metadata: dict[str, Any]
    similarity: float
    ranking_score: float