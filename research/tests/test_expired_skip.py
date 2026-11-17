"""F6: expired-class tenders are skipped unless ``force=true``.

A trigger can fire for a tender whose deadline has already passed. Spending
search/LLM budget on a closed opportunity is waste, and worse, persisting a
research row for it can clobber evidence gathered while it was live. The
runner therefore short-circuits *before* the cache/search path and returns an
explicit, non-persisted ``unavailable`` record; ``force=true`` overrides.
"""

from datetime import date

import pytest

from shared.schemas import DataQuality
from research.tests.test_runner import make_runner, make_tender


def _expired_tender():
    tender = make_tender()
    tender.deadline = date(2020, 1, 1)
    tender.quality = DataQuality(
        completeness=1.0, missing_fields=[], warnings=[], is_expired=True
    )
    return tender


@pytest.mark.asyncio
async def test_expired_is_skipped_and_not_persisted():
    runner = make_runner(_expired_tender())
    result = await runner.run("t1")

    assert result.status == "unavailable"
    assert "force=true" in result.notes
    assert runner.saved == []  # never overwrites (or seeds) real research
    assert any(e.tool_name == "research_expired_skip" for e in runner.audit.entries)


@pytest.mark.asyncio
async def test_force_overrides_the_skip():
    runner = make_runner(_expired_tender())

    async def _no_results(query):
        return []

    result = await runner.run("t1", search_fn=_no_results, force=True)

    assert "Skipped" not in result.notes
    assert len(runner.saved) == 1  # actually ran
    assert not any(e.tool_name == "research_expired_skip" for e in runner.audit.entries)


@pytest.mark.asyncio
async def test_live_tender_is_not_skipped():
    runner = make_runner(make_tender())  # deadline 2026-12-01, is_expired False

    async def _no_results(query):
        return []

    result = await runner.run("t1", search_fn=_no_results)

    assert "Skipped" not in result.notes
    assert len(runner.saved) == 1
