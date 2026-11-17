import asyncio
import os
import re
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from shared.schemas import ExtractorOutput, Fact, ProspectResearch, ResearchFact, Tender
from research.audit import AuditLogger
from research.extractor import Extractor
from research.search import (
    SearchAuthError,
    SearchRateLimitError,
    SearchResult,
    SearchTool,
)
from shared import store as _store
from shared.store import get_tender, save_research

GAP_QUERIES: dict[str, str] = {
    "sector": "sector industry",
    "estimated_revenue": "estimated revenue annual budget",
    "past_projects": "past projects",
    "key_partners": "key partners",
}

# Defense in depth: SearchTool caps to 3 as well, but the orchestrator must not
# trust the tool alone — an alternate/injected search implementation returning
# more would otherwise widen both the token cost and the injection surface.
MAX_RESULTS_PER_QUERY = 3
RESEARCH_CACHE_TTL_SECONDS = int(os.environ.get("RESEARCH_CACHE_TTL_SECONDS", "3600"))

# --- Entity gate -----------------------------------------------------------
# The dominant "noisy web research data" failure is not injection, it is a
# clean page about the *wrong company*. The quarantined extractor cannot catch
# it: it never sees the issuer and is deliberately obedient, so an off-entity
# page yields confident facts and even raises compute_confidence() (distinct
# sources). The gate answers the one question the extractor cannot — is this
# page about our prospect at all — before extraction and before the URL is
# credited as a source.
#
# A snippet shorter than ENTITY_MIN_SNIPPET_CHARS cannot establish *which*
# entity it is about, so the gate abstains rather than risk discarding a real
# (if terse) source.
ENTITY_MIN_SNIPPET_CHARS = 80
ENTITY_MATCH_MIN_RATIO = 0.60
_ENTITY_STOPWORDS = frozenset(
    {
        "the", "and", "for", "des", "les", "de", "la", "le", "et", "du",
        "sa", "sarl", "ltd", "llc", "inc", "gmbh", "spa", "snc", "gie",
        "limited", "societe", "group", "groupe",
    }
)
_ENTITY_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class TenderNotFoundError(LookupError):
    """Raised when Runner.run() is asked for a tender that does not exist."""


def _fold(text: str) -> str:
    """Casefold and strip accents so ``Electricité`` matches ``Electricite``.

    Web snippets routinely drop diacritics; without folding, a French or
    Arabic issuer name would false-discard real, on-entity sources.
    """
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in folded if not unicodedata.combining(c))


def _entity_tokens(name: str) -> list[str]:
    """Identity-bearing words of an issuer name (casefolded, stopwords dropped)."""
    words = _ENTITY_TOKEN_RE.findall(_fold(name))
    return [w for w in words if len(w) >= 3 and w not in _ENTITY_STOPWORDS]


def entity_matches(issuer: str, content: str, url: str) -> bool:
    """Return True when ``content``/``url`` can be attributed to ``issuer``.

    Abstains (True) when it cannot judge: snippet shorter than
    ``ENTITY_MIN_SNIPPET_CHARS``, or an issuer with no significant tokens.
    Otherwise at least ``ENTITY_MATCH_MIN_RATIO`` of the issuer's tokens must
    appear in the snippet or the URL.
    """
    if len(content) < ENTITY_MIN_SNIPPET_CHARS:
        return True
    tokens = _entity_tokens(issuer)
    if not tokens:
        return True
    haystack = _fold(f"{content} {url}")
    hits = sum(1 for token in tokens if token in haystack)
    return hits / len(tokens) >= ENTITY_MATCH_MIN_RATIO


def compute_confidence(facts: list[Fact], sources: set[str]) -> str:
    """Deterministic, evidence-based confidence a judge can point at.

    - "high":   >= 2 distinct contributing source_urls AND at least one
                medium/high-confidence fact.
    - "medium": exactly one contributing source but at least one
                medium/high-confidence fact (one solid single-source fact).
    - "low":    everything else (thin or contradictory evidence — e.g. only
                low-confidence facts, or no facts at all).

    Note this deliberately ignores the *count* of populated fields: four
    facts from a single source_url are "medium", never "high".
    """

    # Deliberately no tender-history bonus: confidence must stay explainable
    # from the evidence alone ("the code computes it this way"), not from a
    # hidden point system a judge cannot audit.
    solid = any(f.confidence in ("medium", "high") for f in facts)
    if len(sources) >= 2 and solid:
        return "high"
    if len(sources) >= 1 and solid:
        return "medium"
    return "low"


def _default_log_path() -> str:
    configured = os.environ.get("RESEARCH_AUDIT_LOG", "/var/log/oliveSoft/research.log")
    try:
        parent = Path(configured).parent
        parent.mkdir(parents=True, exist_ok=True)
        return configured
    except OSError:
        # Read-only container filesystem: never raise at construction;
        # fall back to the OS temp dir (always writable).
        fallback = Path(tempfile.gettempdir()) / "research-audit.log"
        try:
            fallback.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return str(fallback)

LOG_PATH = _default_log_path()

class Runner:
    def __init__(
        self,
        search_tool: Optional[SearchTool] = None,
        extractor: Optional[Extractor] = None,
        save_prospect: Optional[Callable[[str, ProspectResearch], None]] = None,
        audit: Optional[AuditLogger] = None,
        iteration_cap: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        fetch_tender: Optional[Callable[[str], Optional[Tender]]] = None,
    ):
        self.search_tool = search_tool or SearchTool()
        self.extractor = extractor or Extractor()

        # Audit log points at a configured/data volume, never the source tree,
        # so a read-only container filesystem can't 500 every request.
        
        self.audit = audit or AuditLogger(log_path=LOG_PATH)
        self.fetch_tender = fetch_tender or get_tender
        self.save_research = save_prospect or save_research
        # Server budget sits under the n8n node's 45s client timeout:
        # worst case 35s + one 8s in-flight call = 43s, so n8n never aborts
        # mid-run while the server keeps burning search/LLM budget.
        self.iteration_cap = iteration_cap or int(os.environ.get("MAX_SEARCH_ITERATIONS", "4"))
        self.timeout_seconds = timeout_seconds or float(os.environ.get("TOTAL_RUN_TIMEOUT_SECONDS", "35"))
        self.accumulated_facts: dict[str, list[Fact]] = {}
        self.sources: set[str] = set()
        self.research_facts: list[ResearchFact] = []
        # Current-run context (set at the top of run(); also the fallback
        # that lets finalize() be called with no args, as the tests do).
        self._current_tender_id: Optional[str] = None
        self._current_issuer: str = ""
        # Human-readable explanation of a transport-level degradation
        # (auth rejected, rate-limit budget exhausted); appended to notes by
        # finalize() so the failure reason reaches n8n/UI, not just the audit.
        self._degraded_note: str = ""

    def _missing_fields(self) -> list[str]:
        """Fields not yet backed by any accumulated fact, in GAP_QUERIES order."""
        return [k for k in GAP_QUERIES if not self.accumulated_facts.get(k)]

    def _build_query(self, issuer: str, gap: str) -> str:
        label = GAP_QUERIES.get(gap)
        return f"{issuer} {label}"

    def _all_facts(self) -> list[Fact]:
        return [f for items in self.accumulated_facts.values() for f in items]

    def finalize(
        self,
        tender_id: Optional[str] = None,
        issuer: Optional[str] = None,
        persist: bool = True,
    ) -> ProspectResearch:
        tid = tender_id or self._current_tender_id or ""
        iss = issuer if issuer is not None else (self._current_issuer or "")
        if not iss and tid:
            # finalize(tender_id) without a prior run(): resolve the issuer
            # best-effort so ProspectResearch.issuer is never silently blank.
            try:
                tender = self.fetch_tender(tid)
                if tender is not None:
                    iss = tender.issuer
            except Exception:
                pass

        def first(field: str) -> Optional[str]:
            items = self.accumulated_facts.get(field) or []
            return items[0].value if items else None

        sector = first("sector")
        estimated_revenue = first("estimated_revenue")
        past_projects = [f.value for f in self.accumulated_facts.get("past_projects", [])]
        key_partners = [f.value for f in self.accumulated_facts.get("key_partners", [])]

        # Sector disagreement is recorded in notes (required behavior).
        sector_values = [f.value for f in self.accumulated_facts.get("sector", [])]
        distinct_sectors = set(sector_values)
        if len(distinct_sectors) > 1:
            notes = "Sector disagreement across sources: " + "; ".join(distinct_sectors)
        else:
            notes = ""
        if self._degraded_note:
            notes = f"{notes} {self._degraded_note}".strip()

        confidence = compute_confidence(self._all_facts(), self.sources)
        all_facts = self._all_facts()
        if len(all_facts) == 0:
            status = "unavailable"
        elif sector is not None and estimated_revenue is not None and len(past_projects) > 0 and len(key_partners) > 0:
            status = "complete"
        else:
            status = "partial"

        if persist and status == "unavailable":
            # A zero-fact run that still reached the persist step (empty
            # search results, every extraction failed, or the deadline cut
            # the loop short) follows the same rule as the transport
            # degradations above: an outage-shaped result never INSERT OR
            # REPLACEs evidence a successful run already gathered. The stored
            # row is returned flagged instead of being written over.
            previous = self._previous_evidence(tid)
            if previous is not None:
                stored_at = (
                    previous.completed_at.strftime("%Y-%m-%d %H:%M UTC")
                    if previous.completed_at is not None
                    else "an earlier run"
                )
                note = f"Refresh produced no facts; kept evidence stored {stored_at}."
                self.audit.log("research_evidence_preserved", {"tender_id": tid}, note)
                return previous.model_copy(
                    update={
                        "tender_id": tid,
                        "status": "partial",
                        "notes": f"{previous.notes} | {note}" if previous.notes else note,
                    }
                )

        pr = ProspectResearch(
            tender_id=tid,
            issuer=iss,
            sector=sector,
            estimated_revenue=estimated_revenue,
            past_projects=past_projects,
            key_partners=key_partners,
            notes=notes,
            confidence=confidence,  # type: ignore[arg-type]
            sources=list(self.sources),
            status=status,
            completed_at=datetime.now(timezone.utc),
            facts=list(self.research_facts),
        )
        if persist:
            self.save_research(tid, pr)
        return pr

    @staticmethod
    def _previous_evidence(tid: str) -> Optional[ProspectResearch]:
        """Stored research that already holds facts, or None.

        A best-effort lookup like ``fetch_cached``: a missing row, an
        un-initialized DB, or any storage error must not break the run.
        """
        if not tid:
            return None
        try:
            row = _store.get_research_by_tender_id(tid)
        except Exception:
            return None
        if row is None:
            return None
        if row.sector or row.estimated_revenue or row.past_projects or row.key_partners:
            return row
        return None

    def fetch_cached(self, tender_id: str) -> Optional[ProspectResearch]:
        """Tender-keyed cache: an unchanged retry is cheap, and
        opportunity-specific evidence never leaks across separate RFPs
        from the same issuer."""
        try:
            cached = _store.get_research_by_tender_id(tender_id)
        except Exception:
            cached = None
        if cached is None:
            return None
        try:
            if cached.status == "unavailable":
                return None
            if RESEARCH_CACHE_TTL_SECONDS > 0 and cached.completed_at is not None:
                age = (datetime.now(timezone.utc) - cached.completed_at.replace(tzinfo=timezone.utc) if cached.completed_at.tzinfo is None else (datetime.now(timezone.utc) - cached.completed_at.astimezone(timezone.utc))).total_seconds()
                if age > RESEARCH_CACHE_TTL_SECONDS:
                    return None
            all_facts_count = len(cached.past_projects) + len(cached.key_partners) + (1 if cached.sector else 0) + (1 if cached.estimated_revenue else 0)
            if cached.status == "partial" and all_facts_count < 1:
                return None
        except Exception:
            return None
        return cached
        
    async def run(
        self,
        tender_id: str,
        search_fn: Optional[Callable[[str], Awaitable[list[SearchResult]]]] = None,
        extract_fn: Optional[Callable[..., Awaitable[object]]] = None,
        force: bool = False,
    ) -> ProspectResearch:
        # Reset per-run state so a reused Runner never leaks facts between tenders.
        self.accumulated_facts = {}
        self.research_facts = []
        self.sources = set()
        self._current_tender_id = tender_id
        self._degraded_note = ""

        start = time.monotonic()
        search = search_fn or self.search_tool.search
        tender = self.fetch_tender(tender_id)
        if tender is None:
            try:
                self.audit.log("tender_missing", {"tender_id": tender_id}, "")
            finally:
                raise TenderNotFoundError(f"Tender not found: {tender_id}")
        issuer = tender.issuer
        self._current_issuer = issuer

        if not force and tender.quality.is_expired:
            # Closed opportunity: skip the paid run so a stale trigger cannot
            # burn search/LLM budget. The skip is returned, never persisted --
            # a tender can expire *after* it was researched, and an ephemeral
            # response must not overwrite (or cache over) that real evidence.
            self.audit.log("research_expired_skip", {"tender_id": tender_id}, "")
            return ProspectResearch(
                tender_id=tender_id,
                issuer=issuer,
                sector=None if tender.sector == "unknown" else tender.sector,
                estimated_revenue=None,
                past_projects=[],
                key_partners=[],
                notes=(
                    "Skipped: tender deadline has passed "
                    "(pass force=true to research anyway)."
                ),
                confidence="low",
                sources=[],
                status="unavailable",
                completed_at=datetime.now(timezone.utc),
            )

        # Tender-keyed cache: an unchanged retry is served without
        # re-spending search/LLM budget, making the operation idempotent
        # across retries. Detection invalidates this row after a material
        # tender revision.
        cached = self.fetch_cached(tender_id)
        if cached is not None:
            self.audit.log("fetch_cache", {"tender_id": tender_id, "issuer": issuer}, "")
            # The cached record carries the tender_id it was first researched
            # under; return restamped copy in-memory without writing back to DB.
            restamped = cached.model_copy(update={"tender_id": tender_id})
            return restamped
        self.audit.log("research_run_start", {"tender_id": tender_id, "issuer": issuer}, "")
        
        iterations = 0
        # One Tavily call per gap max: a gap already searched is never
        # re-queried, even if it yielded nothing (un-fillable gaps must not
        # starve the others, and filled gaps must not be revisited). With
        # SEARCH_MAX_RESULTS>=2, we also allow trying multiple results per gap
        # before abandoning that gap.
        searched: set[str] = set()
        # Track how many result-attempts we've spent on the current gap
        _gap_attempts: dict[str, int] = {}
        # A 429 Retry-After is honored at most once per run: honoring it again
        # in a tight loop would just trade a rate-limit failure for a hang.
        rate_limit_honored = False
        while iterations < self.iteration_cap:
            if time.monotonic() - start >= self.timeout_seconds:
                # Stops loop because exceeded timeout
                break
            # This returns list of missing fields (sector, estimated_revenue, key_partners, past_projects)
            missing = self._missing_fields()
            if not missing:
                # There's no missing facts
                self.audit.log("missing_fields", {}, "There's no missing field!")
                break

            # First unsearched gap in canonical GAP_QUERIES order. Using the
            # stable canonical order (not missing[iterations % len(missing)])
            # matters: the missing list shrinks as gaps fill, so a modulo
            # index drifts — it re-searches an already-tried gap while
            # starving one never attempted.
            missing_set = set(missing)
            todo = [g for g in GAP_QUERIES if g in missing_set and g not in searched]
            if not todo:
                break
            gap = todo[0]
            gap_attempts = _gap_attempts.get(gap, 0)
            max_attempts_per_gap = max(1, MAX_RESULTS_PER_QUERY)

            # Builds a query: <issuer, gap>
            query = self._build_query(issuer, gap)
            results=[]
            try:
                # Performs a web search using Tavily
                results = await search(query)

            except SearchAuthError as e:
                # A rejected credential fails every remaining query too, so
                # stop the run instead of burning the rest of the budget. No
                # retry: the note and the zero-fact `unavailable` status are
                # what n8n branches on.
                self.audit.log("search_auth_error", {"query": query}, str(e))
                self._degraded_note = (
                    "Search provider rejected the credential (401/403); "
                    "run stopped without retry."
                )
                break
            except SearchRateLimitError as e:
                wait = e.retry_after
                can_wait = (
                    not rate_limit_honored
                    and wait is not None
                    and wait >= 0
                    and (time.monotonic() - start) + wait < self.timeout_seconds
                )
                if can_wait:
                    rate_limit_honored = True
                    self.audit.log(
                        "search_rate_limited",
                        {"query": query, "retry_after": wait},
                        "waiting within budget",
                    )
                    await asyncio.sleep(wait)
                    iterations += 1
                    continue  # retry the same gap; do not mark it searched
                self.audit.log(
                    "search_rate_limited",
                    {"query": query, "retry_after": wait},
                    "budget exhausted",
                )
                self._degraded_note = (
                    "Search provider rate limited (429) and Retry-After did "
                    "not fit the run budget."
                )
                searched.add(gap)
                iterations += 1
                break
            except Exception as e:
                self.audit.log("Search Error", {"query": query}, str(e))
                searched.add(gap)
                iterations += 1
                continue
            
            if not results or len(results) == 0:
                searched.add(gap)
                iterations += 1
                continue
            # Process results in order until one yields a fact (>=1 new fact)
            added_any = False
            for r in results[:max_attempts_per_gap]:
                gap_attempts += 1
                _gap_attempts[gap] = gap_attempts
                if time.monotonic() - start >= self.timeout_seconds:
                    break
                self.audit.log("search", {"query": query}, r.content)

                # Entity gate: the quarantined extractor never sees the issuer
                # and is deliberately obedient, so an off-entity page yields
                # confident facts and even raises confidence (distinct
                # sources). Discard it here, before extraction and before the
                # URL is credited. The `search` audit above still records every
                # snippet that reached evaluation.
                if not entity_matches(issuer, r.content, r.url):
                    self.audit.log(
                        "entity_mismatch",
                        {"tender_id": tender_id, "url": r.url},
                        r.content,
                    )
                    continue

                try:
                    if extract_fn is not None:
                        out = await extract_fn(r.content, r.url)
                    else:
                        out = await self.extractor.extract(r.content, r.url)
                except Exception:
                    continue

                for fact in out.facts:
                    if fact.category not in GAP_QUERIES:
                        continue
                    bucket = self.accumulated_facts.setdefault(fact.category, [])
                    if any(
                        existing.value.strip().casefold() == fact.value.strip().casefold()
                        for existing in bucket
                    ):
                        continue
                    bucket.append(fact)
                    self.research_facts.append(
                        ResearchFact(
                            value=fact.value,
                            category=fact.category,
                            confidence=fact.confidence,
                            source=r.url,
                        )
                    )
                    self.sources.add(r.url)
                    added_any = True
                if added_any:
                    break
            # If we tried up to max_attempts_per_gap results and got nothing new for this gap, abandon it
            if not added_any:
                searched.add(gap)
            iterations += 1

        # A degraded run stopped early on a transport failure (rejected
        # credential or an unbudgeted Retry-After), so its result is
        # epistemically incomplete. Returning it is useful — the caller still
        # gets status/notes/facts — but persisting it would INSERT OR REPLACE
        # real evidence gathered by an earlier successful run. Same rule the
        # expired-skip path already follows: an ephemeral response must never
        # overwrite real evidence.
        return self.finalize(tender_id, persist=not self._degraded_note)
