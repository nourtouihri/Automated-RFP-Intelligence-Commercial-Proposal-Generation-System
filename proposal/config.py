"""Everything OliveSoft-specific that a proposal says or shows, in one object.

compose() and render() take a Config; DEFAULT holds today's OliveSoft values, so
passing nothing changes nothing. A different company passes its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .schemas import NextStep, Signatory

ASSETS = Path(__file__).resolve().parent / "assets"


@dataclass(frozen=True)
class Config:
    company: str = "OliveSoft"
    # The one fact about the company the model is told; the claim check treats it as support.
    company_sentence: str = "OliveSoft, a Data & AI consulting firm (Paris, Sfax, Tunis, Dubai)"
    prepared_by: str = "OliveSoft · Data & AI"
    letter_title: str = "A partner for your data journey"
    signatory: Signatory = field(default_factory=lambda: Signatory(
        name="OliveSoft Sales Team", role="Sales, OliveSoft", contact="olivesoft.fr"))
    currency: str = "€"
    # Placeholder figures until sales supplies a real rate card. Each phase is priced as
    # weeks × 5 days × team_size × day_rate, so every line is filled in.
    day_rate: float = 650
    team_size: int = 2
    # The model writes the weeks, so the price grows with them; past this, sales is warned.
    long_plan_weeks: int = 26
    investment_note: str = ("Indicative: days × blended day rate. "
                            "Final quote after scoping.")
    next_steps: tuple[NextStep, ...] = (
        NextStep(title="Discovery session", detail="30 minutes, this week"),
        NextStep(title="Express data audit", detail="Within 10 days"),
        NextStep(title="Sign and kick off", detail="Team starts the following week"),
    )
    proposal_footer: str = "{company} · Proposal for {buyer}"
    research_source: str = "Source: agentic prospect research"
    no_research_source: str = "Source: the tender text; prospect research was unavailable"
    matrix_source: str = "Source: RAG retrieval over the {company} knowledge base"
    team_source: str = "Source: CV bank retrieval"
    references_source: str = "Source: project index"
    # Both PNGs were rendered once from OliveSoft_Horizontal_Lockup.svg, transparent. The
    # symbol is the lockup's own symbol, cropped: the supplied OliveSoft_Symbol.png has an
    # opaque white background, which shows as a box on the off-white slides.
    logo_lockup: Path = ASSETS / "OliveSoft_Horizontal_Lockup.png"
    logo_symbol: Path = ASSETS / "OliveSoft_Symbol_from_svg.png"


DEFAULT = Config()
