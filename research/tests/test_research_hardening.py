"""T3 research hardening (§4.3): transport taxonomy and the entity gate.

These cover the three essential deltas against "noisy web research data":

* ``SearchTool`` really caps ``max_results`` (the runner's 3-attempt loop was
  inert while the tool hard-coded 1).
* 401/403 stops the run as ``unavailable`` with a note and no retry; 429
  honours ``Retry-After`` when it fits the budget and otherwise degrades.
* A clean page about the *wrong company* is discarded before it reaches the
  extractor, with an ``entity_mismatch`` audit entry.

The last section pins the fetch tool's body cap: research reads untrusted pages
through it, so a silently larger default widens what the open web can send.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from research.runner import Runner, entity_matches
from research.search import (
    SearchAuthError,
    SearchRateLimitError,
    SearchResult,
    SearchTool,
    _classify_client_error,
)
from research.tests.test_runner import (
    FakeAuditLogger,
    make_fact,
    make_output,
    make_runner,
    make_tender,
)
from research.tools import fetch
from shared import store
from shared.schemas import ProspectResearch


def _status_error(status: int, headers: dict | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.tavily.com/search")
    response = httpx.Response(status, request=request, headers=headers or {})
    return httpx.HTTPStatusError("boom", request=request, response=response)


# A realistic off-entity snippet: long enough to judge, about another company.
LONG_OFF_ENTITY = (
    "Acme Rival Holdings announced a record annual budget of two billion "
    "dollars for its transport division, alongside new partner agreements "
    "across the region. "
) * 2

# A realistic on-entity snippet: mentions the issuer (MetroDOT).
LONG_ON_ENTITY = (
    "MetroDOT will invest in the Metro City transit corridor, expanding its "
    "sector operations and confirming new key partners for the coming year. "
) * 2


# ---------------------------------------------------------------------------
# max_results is real (D8)
# ---------------------------------------------------------------------------


def test_search_tool_default_caps_max_results_to_three():
    assert SearchTool().max_results == 3


def test_search_tool_clamps_max_results_to_at_least_one():
    assert SearchTool(max_results=0).max_results == 1
    assert SearchTool(max_results=99).max_results == 3


# ---------------------------------------------------------------------------
# Client-error taxonomy
# ---------------------------------------------------------------------------


def test_classify_client_error_maps_auth_and_rate_limit():
    assert isinstance(_classify_client_error(_status_error(401)), SearchAuthError)
    assert isinstance(_classify_client_error(_status_error(403)), SearchAuthError)

    err = _classify_client_error(_status_error(429, {"Retry-After": "2"}))
    assert isinstance(err, SearchRateLimitError)
    assert err.retry_after == 2.0

    # A 429 without a usable header still surfaces as a rate-limit error.
    no_header = _classify_client_error(_status_error(429))
    assert isinstance(no_header, SearchRateLimitError)
    assert no_header.retry_after is None

    # Anything else stays a plain client error (re-raised unchanged).
    assert _classify_client_error(_status_error(400)) is None


# ---------------------------------------------------------------------------
# Auth (401/403): stop, do not retry, leave an explanatory note
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_research_auth_failure_is_unavailable_and_not_retried():
    tender = make_tender()
    calls = []

    async def fake_search(query):
        calls.append(query)
        raise SearchAuthError("search credential rejected (401)")

    runner = make_runner(tender)
    result = await runner.run(tender.id, search_fn=fake_search)

    assert len(calls) == 1, "401/403 must not be retried"
    assert result.status == "unavailable"
    assert "401/403" in result.notes
    assert any(e.tool_name == "search_auth_error" for e in runner.audit.entries)
    # Degraded runs are returned, not persisted: a 401 must never overwrite
    # real evidence gathered by an earlier successful run.
    assert runner.saved == []


# ---------------------------------------------------------------------------
# Rate limit (429)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_research_rate_limit_honors_retry_after_within_budget():
    tender = make_tender()
    calls = []

    async def fake_search(query):
        calls.append(query)
        if len(calls) == 1:
            raise SearchRateLimitError(0)
        return [SearchResult(url="http://src", content="x")]

    async def fake_extract(content, url):
        return make_output(make_fact("sector", "Transport"))

    runner = make_runner(tender, iteration_cap=2, timeout_seconds=5)
    result = await runner.run(tender.id, search_fn=fake_search, extract_fn=fake_extract)

    assert len(calls) == 2, "429 inside budget must be retried once"
    assert result.sector == "Transport"
    assert any(e.tool_name == "search_rate_limited" for e in runner.audit.entries)


@pytest.mark.asyncio
async def test_edge_research_rate_limit_without_retry_after_degrades():
    tender = make_tender()
    calls = []

    async def fake_search(query):
        calls.append(query)
        raise SearchRateLimitError(None)

    runner = make_runner(tender)
    result = await runner.run(tender.id, search_fn=fake_search)

    assert len(calls) == 1, "no Retry-After means no wait and no retry"
    assert result.status == "unavailable"
    assert "429" in result.notes
    assert runner.saved == []


@pytest.mark.asyncio
async def test_edge_research_rate_limit_beyond_budget_degrades():
    tender = make_tender()
    calls = []

    async def fake_search(query):
        calls.append(query)
        raise SearchRateLimitError(9999)

    runner = make_runner(tender, timeout_seconds=5)
    result = await runner.run(tender.id, search_fn=fake_search)

    assert len(calls) == 1, "a Retry-After past the budget must not be slept on"
    assert result.status == "unavailable"
    assert "429" in result.notes
    assert runner.saved == []


# ---------------------------------------------------------------------------
# Entity gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_research_off_entity_snippet_is_discarded_with_audit():
    tender = make_tender()  # issuer = MetroDOT
    extract_calls = []

    async def fake_search(query):
        return [
            SearchResult(url="https://rival.example/about", content=LONG_OFF_ENTITY)
        ]

    async def fake_extract(content, url):
        extract_calls.append(url)
        return make_output(make_fact("sector", "COMPROMISED"))

    runner = make_runner(tender, iteration_cap=4)
    result = await runner.run(tender.id, search_fn=fake_search, extract_fn=fake_extract)

    assert extract_calls == [], "off-entity snippet must never reach the extractor"
    assert result.sector is None
    assert result.status == "unavailable"
    assert any(e.tool_name == "entity_mismatch" for e in runner.audit.entries)


@pytest.mark.asyncio
async def test_edge_research_on_entity_snippet_is_kept():
    tender = make_tender()  # issuer = MetroDOT

    async def fake_search(query):
        return [SearchResult(url="https://news.example/m", content=LONG_ON_ENTITY)]

    async def fake_extract(content, url):
        return make_output(make_fact("sector", "Transport"))

    runner = make_runner(tender, iteration_cap=1)
    result = await runner.run(tender.id, search_fn=fake_search, extract_fn=fake_extract)

    assert result.sector == "Transport"
    assert not any(e.tool_name == "entity_mismatch" for e in runner.audit.entries)


def test_entity_matches_abstains_on_short_snippet():
    # Below the judgeable length the gate must not discard: a terse snippet
    # cannot establish which entity it is about.
    assert entity_matches("MetroDOT", "about a totally different company", "http://x")


def test_entity_matches_abstains_when_issuer_has_no_significant_tokens():
    assert entity_matches("SA", LONG_OFF_ENTITY, "http://x")


def test_entity_matches_requires_sixty_percent_of_tokens():
    issuer = "Societe Tunisienne de l'Electricite"
    # One of two significant tokens present -> 50% < 60% -> discarded.
    assert not entity_matches(
        issuer, ("La Tunisienne works across the region. " * 4), "http://x"
    )
    # Both present (accent-insensitive) -> kept.
    assert entity_matches(
        issuer, ("Tunisienne Electricite utility update. " * 4), "http://x"
    )


# ---------------------------------------------------------------------------
# Producer side: the SDK's own exception classes reach the same taxonomy
# ---------------------------------------------------------------------------
#
# tavily-python translates HTTP status to its *own* exceptions and never raises
# httpx.HTTPStatusError for 4xx, so a classifier test built on a hand-made
# httpx error proves nothing about production. These drive the real
# SearchTool.search() with the SDK client faked to answer like the real one.


def _install_rejecting_client(monkeypatch, exc):
    tavily = pytest.importorskip("tavily")
    calls = {"n": 0}

    class RejectingClient:
        def __init__(self, api_key=None, **kwargs):
            pass

        async def search(self, query, **kwargs):
            calls["n"] += 1
            raise exc

    monkeypatch.setattr(tavily, "AsyncTavilyClient", RejectingClient, raising=True)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    return calls


@pytest.mark.asyncio
async def test_search_tool_maps_sdk_auth_errors_without_retry(monkeypatch):
    errors = pytest.importorskip("tavily.errors")
    for exc in (errors.InvalidAPIKeyError("bad key"), errors.ForbiddenError("nope")):
        calls = _install_rejecting_client(monkeypatch, exc)
        with pytest.raises(SearchAuthError):
            await SearchTool().search("MetroDOT sector")
        assert calls["n"] == 1, f"{type(exc).__name__} must not be retried"


@pytest.mark.asyncio
async def test_search_tool_maps_sdk_rate_limit(monkeypatch):
    errors = pytest.importorskip("tavily.errors")
    calls = _install_rejecting_client(
        monkeypatch, errors.UsageLimitExceededError("slow down")
    )
    with pytest.raises(SearchRateLimitError) as excinfo:
        await SearchTool().search("MetroDOT sector")
    assert calls["n"] == 1
    # The API-key UsageLimitExceededError carries no Retry-After, so this path
    # can only degrade with a note (the Runner cannot wait on a number it was
    # never given).
    assert excinfo.value.retry_after is None


@pytest.mark.asyncio
async def test_search_tool_maps_sdk_bad_request_without_retry(monkeypatch):
    errors = pytest.importorskip("tavily.errors")
    calls = _install_rejecting_client(monkeypatch, errors.BadRequestError("bad query"))
    with pytest.raises(errors.BadRequestError):
        await SearchTool().search("MetroDOT sector")
    assert calls["n"] == 1, "a 4xx is a client error, never retried"


# ---------------------------------------------------------------------------
# Persistence: the control for the degraded-run rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_run_is_persisted():
    tender = make_tender()

    async def fake_search(query):
        return [SearchResult(url="http://src", content="x")]

    async def fake_extract(content, url):
        return make_output(make_fact("sector", "Transport"))

    runner = make_runner(tender, iteration_cap=1)
    await runner.run(tender.id, search_fn=fake_search, extract_fn=fake_extract)

    assert len(runner.saved) == 1
    assert runner.saved[-1][1].sector == "Transport"


# ---------------------------------------------------------------------------
# A zero-fact refresh must not erase stored evidence
# ---------------------------------------------------------------------------


@pytest.fixture
def research_db(tmp_path, monkeypatch):
    """Real store on a throwaway DB: the preservation guard reads stored rows."""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    store.init_db()
    yield


def _seed_stored_evidence(tender_id: str) -> ProspectResearch:
    stored = ProspectResearch(
        tender_id=tender_id,
        issuer="MetroDOT",
        sector="transport",
        estimated_revenue="$1B",
        past_projects=["Metro line extension"],
        key_partners=["Acme"],
        notes="",
        confidence="high",
        sources=["https://example.com/metro"],
        status="complete",
        # Older than the 1h cache TTL, so fetch_cached does not short-circuit
        # the run -- the "stale row + failing refresh" trigger.
        completed_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )
    store.save_research(tender_id, stored)
    return stored


@pytest.mark.asyncio
async def test_zero_fact_refresh_keeps_stored_evidence(research_db):
    """Empty search results (no exception, no transport note) are still an
    outage-shaped result: the zero-fact `unavailable` row must not INSERT OR
    REPLACE evidence a successful run already gathered."""
    tender = make_tender()
    store.save_tender(tender, "h")
    stored = _seed_stored_evidence(tender.id)

    async def empty_search(query):
        return []

    runner = Runner(audit=FakeAuditLogger(), iteration_cap=1, timeout_seconds=5)
    result = await runner.run(tender.id, search_fn=empty_search)

    assert result.status == "partial"
    assert "kept evidence" in result.notes
    assert result.key_partners == ["Acme"]
    assert any(e.tool_name == "research_evidence_preserved" for e in runner.audit.entries)

    after = store.get_research_by_tender_id(tender.id)
    assert after is not None
    assert after.status == "complete"
    assert after.key_partners == ["Acme"]
    assert after.notes == stored.notes


@pytest.mark.asyncio
async def test_first_zero_fact_run_still_persists_unavailable(research_db):
    """With no prior evidence there is nothing to preserve: the `unavailable`
    row is still written (and never served), so the failure stays visible."""
    tender = make_tender()
    store.save_tender(tender, "h")

    async def empty_search(query):
        return []

    runner = Runner(audit=FakeAuditLogger(), iteration_cap=1, timeout_seconds=5)
    result = await runner.run(tender.id, search_fn=empty_search)

    assert result.status == "unavailable"
    stored = store.get_research_by_tender_id(tender.id)
    assert stored is not None
    assert stored.status == "unavailable"
    assert runner.fetch_cached(tender.id) is None


# ---------------------------------------------------------------------------
# Fetch body cap
# ---------------------------------------------------------------------------


def test_default_fetch_cap_is_256_kib():
    assert fetch.FETCH_MAX_BYTES == 256 * 1024


class _FakeEgressClient:
    """Client, stream and response in one: a 200 whose body arrives in chunks."""

    is_redirect = False
    status_code = 200

    def __init__(self, chunks):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        return self

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_explicit_max_bytes_overrides_the_default_cap(monkeypatch):
    """A body over the default cap comes back cut at the cap; a caller that
    sizes its own API page with ``max_bytes`` gets all of it."""
    monkeypatch.delenv("FETCH_MAX_BYTES", raising=False)
    chunk = b"x" * 64 * 1024

    async def passes_the_guard(url, *, policy):
        return url, _FakeEgressClient([chunk] * 8)  # a 512 KiB body

    monkeypatch.setattr(fetch, "build_egress_http_client", passes_the_guard)

    default = await fetch.fetch_url("https://public.example/search")
    raised = await fetch.fetch_url("https://public.example/search", max_bytes=1024 * 1024)

    assert len(default) == 256 * 1024
    assert len(raised) == 512 * 1024
