"""Budget engine + output-schema contract.

Core promise under test: every number comes from text or arithmetic, never
from a guess, and when there is nothing to go on the answer is "none".
"""

import pytest
from pydantic import ValidationError

from insights_agent.budget import (
    find_explicit_budget,
    parse_amounts,
    resolve_budget,
)
from insights_agent.schemas import BudgetEstimate, Competitor

RATES = {"TND": 1.0, "EUR": 3.5, "USD": 3.0}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, currency, value",
    [
        ("Budget: 150 000 TND", "TND", 150_000),
        ("Budget: 150.000 DT", "TND", 150_000),
        ("Budget: 150000 dinars", "TND", 150_000),
        ("1,2 M€ HT", "EUR", 1_200_000),
        ("€1.2M", "EUR", 1_200_000),
        ("2 MD", "TND", 2_000_000),
        ("500 KDT", "TND", 500_000),
        ("1.5 million EUR", "EUR", 1_500_000),
        ("$ 500,000", "USD", 500_000),
        ("1 200 000,50 dinars", "TND", 1_200_000.5),
    ],
)
def test_parse_amounts_formats(text, currency, value):
    amounts = parse_amounts(text, RATES)
    assert len(amounts) == 1, amounts
    assert amounts[0].currency == currency
    assert amounts[0].value == pytest.approx(value)


def test_parse_converts_to_tnd_with_given_rates():
    [amount] = parse_amounts("100 000 EUR", RATES)
    assert amount.value_tnd == pytest.approx(350_000)


def test_parse_ignores_numbers_without_currency():
    assert parse_amounts("Le projet couvre 10 000 utilisateurs et 12 modules.", RATES) == []


def test_two_amounts_in_one_text_are_both_found():
    amounts = parse_amounts("Lot 1: 150 000 TND. Lot 2: 200 000 TND.", RATES)
    assert [a.value for a in amounts] == [150_000, 200_000]


# ---------------------------------------------------------------------------
# Explicit budget detection
# ---------------------------------------------------------------------------


def test_explicit_budget_is_found():
    found = find_explicit_budget("Budget estimé : 500 000 TND.", RATES)
    assert [a.value_tnd for a in found] == [500_000]


def test_guarantees_and_document_fees_are_not_the_budget():
    text = (
        "Budget estimé : 500 000 TND. Cautionnement provisoire : 5 000 TND. "
        "Frais d'obtention du cahier des charges : 200 DT."
    )
    found = find_explicit_budget(text, RATES)
    assert [a.value_tnd for a in found] == [500_000]


def test_eligibility_turnover_is_not_the_budget():
    text = "Budget: 200 000 TND; chiffre d'affaires annuel minimum exigé : 800 000 TND."
    found = find_explicit_budget(text, RATES)
    assert [a.value_tnd for a in found] == [200_000]


def test_amount_without_budget_wording_is_not_linked():
    assert find_explicit_budget("Le candidat a réalisé un projet de 900 000 TND.", RATES) == []


def test_implausibly_small_amounts_are_dropped():
    assert find_explicit_budget("Budget: 50 TND", RATES) == []


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_single_explicit_budget_is_high_confidence():
    explicit = find_explicit_budget("Budget estimé : 500 000 TND.", RATES)
    result = resolve_budget(explicit=explicit, tender_source="tender:t1")
    assert result.method == "explicit"
    assert (result.min, result.likely, result.max) == (500_000, 500_000, 500_000)
    assert result.confidence == "high"
    assert result.sources == ["tender:t1"]


def test_foreign_currency_explicit_budget_drops_to_medium_and_says_why():
    explicit = find_explicit_budget("Estimated budget: 100 000 EUR.", RATES)
    result = resolve_budget(explicit=explicit)
    assert result.likely == pytest.approx(350_000)
    assert result.confidence == "medium"
    assert any("rate" in a.lower() for a in result.assumptions)


def test_several_explicit_figures_become_a_range_and_are_not_summed():
    text = "Budget lot 1 : 100 000 TND. Budget lot 2 : 300 000 TND."
    result = resolve_budget(explicit=find_explicit_budget(text, RATES))
    assert (result.min, result.likely, result.max) == (100_000, 200_000, 300_000)
    assert result.confidence == "medium"
    assert any("not summed" in a for a in result.assumptions)


def test_single_comparable_is_widened_and_low_confidence():
    result = resolve_budget(
        comparable_values_tnd=[100_000], comparable_sources=["https://x.example/a"]
    )
    assert result.method == "comparables"
    assert result.likely == 100_000
    assert result.min == pytest.approx(70_000)
    assert result.max == pytest.approx(150_000)
    assert result.confidence == "low"
    assert result.sources == ["https://x.example/a"]


def test_three_comparables_give_medium_confidence():
    result = resolve_budget(comparable_values_tnd=[100_000, 150_000, 200_000])
    assert (result.min, result.likely, result.max) == (100_000, 150_000, 200_000)
    assert result.confidence == "medium"


def test_many_comparables_stay_ordered_and_inside_the_observed_range():
    """A range must never claim a value above the largest comparable seen.

    Regression: statistics.quantiles() defaults to the "exclusive" method, which
    extrapolated P90 to 1.13M for data whose maximum was 900k.
    """
    values = [80_000, 90_000, 100_000, 110_000, 120_000, 900_000]
    result = resolve_budget(comparable_values_tnd=values)
    assert result.min <= result.likely <= result.max
    assert min(values) <= result.min
    assert result.max <= max(values)


def test_implausible_comparables_are_ignored():
    result = resolve_budget(comparable_values_tnd=[5, 10])
    assert result.method == "none"


def test_effort_estimate_is_asymmetric_and_low_confidence():
    result = resolve_budget(person_days=120, daily_rate=400)
    assert result.method == "effort"
    assert result.likely == 48_000
    assert result.min == pytest.approx(38_400)
    assert result.max == pytest.approx(67_200)
    assert result.confidence == "low"


def test_explicit_beats_comparables_and_effort():
    explicit = find_explicit_budget("Budget: 400 000 TND.", RATES)
    result = resolve_budget(
        explicit=explicit, comparable_values_tnd=[100_000], person_days=10
    )
    assert result.method == "explicit"
    assert result.likely == 400_000


def test_comparables_beat_effort():
    result = resolve_budget(comparable_values_tnd=[100_000, 120_000], person_days=10)
    assert result.method == "comparables"


def test_nothing_to_go_on_returns_no_numbers_not_a_guess():
    result = resolve_budget()
    assert result.method == "none"
    assert (result.min, result.likely, result.max) == (None, None, None)
    assert result.confidence == "low"
    assert result.assumptions


# ---------------------------------------------------------------------------
# Schema contract
# ---------------------------------------------------------------------------


def test_budget_none_must_not_carry_amounts():
    with pytest.raises(ValidationError):
        BudgetEstimate(method="none", min=1.0, likely=2.0, max=3.0, confidence="low")


def test_budget_with_method_requires_all_amounts():
    with pytest.raises(ValidationError):
        BudgetEstimate(method="explicit", min=1000.0, confidence="high")


def test_budget_amounts_must_be_ordered():
    with pytest.raises(ValidationError):
        BudgetEstimate(
            method="explicit", min=300.0, likely=200.0, max=100.0, confidence="low"
        )


def test_competitor_requires_evidence():
    with pytest.raises(ValidationError):
        Competitor(name="Acme IT", why_likely="Won similar tenders", evidence=[])


def test_competitor_evidence_must_be_http_url():
    with pytest.raises(ValidationError):
        Competitor(name="Acme IT", why_likely="x", evidence=["trust me"])


def test_competitor_with_evidence_is_valid():
    c = Competitor(
        name="Acme IT", why_likely="Won similar tenders",
        evidence=["https://example.com/award"],
    )
    assert c.strengths == [] and c.weaknesses == []