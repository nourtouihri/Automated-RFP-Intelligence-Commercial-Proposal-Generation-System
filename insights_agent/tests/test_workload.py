"""Workload schema + effort budget: absurd LLM values are rejected, arithmetic is ours."""

import pytest
from pydantic import ValidationError

from insights_agent.budget import (
    check_against_reference,
    total_person_days,
    workload_to_budget,
)
from insights_agent.schemas import Workload, WorkloadTask


def make(days_list):
    return Workload(tasks=[
        WorkloadTask(name=f"Tâche {i}", days=d, reason="Justification détaillée")
        for i, d in enumerate(days_list)
    ])


def test_total_person_days():
    assert total_person_days(make([25, 30, 15])) == 70


def test_workload_becomes_an_effort_budget():
    result = workload_to_budget(make([25, 30, 15]), daily_rate=400)
    assert result.method == "effort"
    assert result.likely == 28_000
    assert result.min == pytest.approx(22_400)
    assert result.max == pytest.approx(39_200)
    assert result.confidence == "low"


def test_budget_assumptions_list_the_tasks():
    result = workload_to_budget(make([10]), daily_rate=400)
    assert any("Tâche 0" in a for a in result.assumptions)


def test_empty_workload_rejected():
    with pytest.raises(ValidationError):
        Workload(tasks=[])


def test_absurd_task_days_rejected():
    with pytest.raises(ValidationError):
        make([5000])


def test_negative_or_zero_days_rejected():
    with pytest.raises(ValidationError):
        make([-3])
    with pytest.raises(ValidationError):
        make([0])


def test_task_without_reason_rejected():
    with pytest.raises(ValidationError):
        WorkloadTask(name="Dashboard", days=10, reason="")


def test_total_over_limit_rejected():
    with pytest.raises(ValidationError):
        make([200] * 6)   # 1200 days


def test_unknown_key_from_llm_is_rejected():
    with pytest.raises(ValidationError):
        WorkloadTask(name="Dashboard", days=10, reason="Trois rôles utilisateurs", price=5)


def test_estimate_far_below_past_projects_is_suspicious():
    r = check_against_reference(28_000, [90_000])
    assert r["checked"] and r["suspicious"]
    assert r["ratio"] > 1


def test_estimate_close_to_reference_is_fine():
    r = check_against_reference(80_000, [90_000])
    assert r["checked"] and not r["suspicious"]


def test_no_reference_means_no_verdict():
    r = check_against_reference(28_000, [])
    assert r == {"checked": False, "suspicious": False, "ratio": None, "reference": None}