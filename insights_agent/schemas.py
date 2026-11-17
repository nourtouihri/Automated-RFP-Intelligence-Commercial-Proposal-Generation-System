"""Output schemas for the Competitor & Budget Insights agent.

Design rules enforced here, not just documented:
- a budget with ``method == "none"`` carries NO numbers (never an invented range);
- a budget with numbers is always ordered ``min <= likely <= max``;
- a competitor without at least one http(s) evidence URL cannot exist;
- a workload proposed by the LLM is rejected whole if any value is absurd.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Confidence = Literal["low", "medium", "high"]
BudgetMethod = Literal["explicit", "comparables", "effort", "none"]
InsightsStatus = Literal["complete", "partial", "unavailable"]
InsightCategory = Literal[
    "comparable_budget", "competitor", "competitor_strength", "competitor_weakness"
]
COMPETITOR_CATEGORIES = ("competitor", "competitor_strength", "competitor_weakness")


class InsightFact(BaseModel):
    """One fact copied out of a web page by the quarantined extractor.

    The model supplies text spans only. Amounts are re-parsed by the code
    (budget.parse_amounts) and the source URL is attached by the runner, never
    taken from the model, so a page cannot smuggle in a URL or a number.
    """

    model_config = ConfigDict(strict=True, extra="forbid")
    category: InsightCategory
    # Span copied from the source; for a competitor it is the supporting sentence.
    value: str = Field(min_length=1, max_length=500)
    # Competitor company name exactly as written in the source; None otherwise.
    name: str | None = Field(default=None, max_length=200)
    confidence: Confidence

    @field_validator("value")
    @classmethod
    def _value_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("fact value must not be blank")
        return stripped

    @field_validator("name")
    @classmethod
    def _name_stripped(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None

    @model_validator(mode="after")
    def _name_matches_category(self) -> "InsightFact":
        if self.category in COMPETITOR_CATEGORIES:
            if self.name is None:
                raise ValueError("a competitor fact requires a name")
        else:
            self.name = None
        return self


class InsightExtractorOutput(BaseModel):
    """Strict schema for the quarantined extractor. No other output allowed.

    Same fail-closed contract as shared.schemas.ExtractorOutput: an unexpected
    key discards the whole reply, and the drift is logged by the extractor.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    facts: list[InsightFact]


class BudgetEstimate(BaseModel):
    model_config = ConfigDict(strict=True)

    currency: Literal["TND"] = "TND"
    min: float | None = None
    likely: float | None = None
    max: float | None = None
    method: BudgetMethod
    assumptions: list[str] = Field(default_factory=list)
    confidence: Confidence
    sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coherent(self) -> "BudgetEstimate":
        values = (self.min, self.likely, self.max)
        if self.method == "none":
            if any(v is not None for v in values):
                raise ValueError("method 'none' must not carry any amount")
            return self
        if any(v is None for v in values):
            raise ValueError("min, likely and max are all required unless method is 'none'")
        if not (0 <= self.min <= self.likely <= self.max):  # type: ignore[operator]
            raise ValueError("amounts must satisfy 0 <= min <= likely <= max")
        return self


class Competitor(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=200)
    why_likely: str = Field(min_length=1, max_length=500)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    # At least one source: a competitor nobody can verify is an invention.
    evidence: list[str] = Field(min_length=1)

    @field_validator("evidence")
    @classmethod
    def _urls_only(cls, urls: list[str]) -> list[str]:
        for url in urls:
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"evidence must be an http(s) URL, got {url!r}")
        return urls


class Positioning(BaseModel):
    model_config = ConfigDict(strict=True)

    olivesoft_advantages: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommended_strategy: str = ""
    differentiators_to_emphasize: list[str] = Field(default_factory=list)


class TenderInsights(BaseModel):
    """Final output of the Competitor & Budget Insights agent."""

    model_config = ConfigDict(strict=True)

    tender_id: str
    issuer: str
    budget: BudgetEstimate
    competitors: list[Competitor] = Field(default_factory=list)
    positioning: Positioning = Field(default_factory=Positioning)
    notes: str = ""
    # Computed by the runner from the evidence, never self-reported by the model.
    confidence: Confidence
    status: InsightsStatus | None = None
    completed_at: datetime | None = None


# --------------------------------------------------------------------------
# Workload proposed by the LLM (validated before any arithmetic is done)
# --------------------------------------------------------------------------

MAX_TASK_DAYS = 200      # a single task above this is absurd
MAX_TOTAL_DAYS = 1_000   # so is a whole project above this
MAX_TASKS = 40

WorkloadProfile = Literal["junior", "standard", "senior", "expert"]
# Placeholders: replace with OliveSoft's real rate grid.
PROFILE_MULTIPLIERS = {"junior": 0.7, "standard": 1.0, "senior": 1.4, "expert": 1.8}


class WorkloadTask(BaseModel):
    """One task proposed by the LLM. The days are a proposal, not a fact."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(min_length=3, max_length=200)
    days: float = Field(gt=0, le=MAX_TASK_DAYS)
    profile: WorkloadProfile = "standard"
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("name", "reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class Workload(BaseModel):
    """The task list the LLM proposes. Rejected whole if any value is absurd."""

    model_config = ConfigDict(strict=True, extra="forbid")

    tasks: list[WorkloadTask] = Field(min_length=1, max_length=MAX_TASKS)

    @model_validator(mode="after")
    def _total_is_plausible(self) -> "Workload":
        total = sum(t.days for t in self.tasks)
        if total > MAX_TOTAL_DAYS:
            raise ValueError(f"total of {total:g} days exceeds the {MAX_TOTAL_DAYS} limit")
        return self