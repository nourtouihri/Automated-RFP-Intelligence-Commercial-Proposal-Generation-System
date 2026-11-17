"""
Prospect Research API. All endpoints except /health require X-Internal-Token.
Runs the agentic Runner for a stored tender and returns ProspectResearch.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException

from shared import store
from shared.errors import install
from research import runner
from research.audit_reader import read_run
from research.runner import Runner, TenderNotFoundError
from shared.auth import require_internal_token
from shared.schemas import ProspectResearch

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    yield


app = FastAPI(title="Prospect Research Service API", lifespan=lifespan)

# Same envelope + X-Request-ID contract as the detection app: a caller must be
# able to branch on a stable `code`/`retryable` and stitch one trigger's log
# lines together, whichever service answered. The previous local handler
# returned a bare {"error": ...} with no request id, breaking both.
install(app)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/research", response_model=dict[str, ProspectResearch])
def list_research(
    _token: str = Depends(require_internal_token),
) -> dict[str, ProspectResearch]:
    return store.list_research()


# Single-flight guard for concurrent runs on the same tender_id
_async_locks: dict[str, asyncio.Task] = {}


@app.post("/research/{tender_id:path}", response_model=ProspectResearch)
async def run_research(
    tender_id: str,
    force: bool = False,
    _token: str = Depends(require_internal_token),
) -> ProspectResearch:
    """Run (or re-run) prospect research.

    POST because a run spends search + LLM budget: it is neither safe nor
    idempotent-by-default, so it must not be a GET (prefetchers, crawlers
    and browser retries fire GETs). Exact-tender caching inside Runner makes
    unchanged repeated triggers cheap without reusing opportunity-specific
    evidence across separate RFPs from the same issuer.

    A tender whose deadline has passed is skipped (``status=unavailable``)
    rather than spending budget on a closed opportunity; ``?force=true``
    overrides for a deliberate re-run.
    """
    try:
        # Single-flight: share the running task for concurrent requests
        if tender_id in _async_locks:
            task = _async_locks[tender_id]
            return await task
        task = asyncio.create_task(Runner().run(tender_id, force=force))
        _async_locks[tender_id] = task
        try:
            result = await task
            return result
        finally:
            _async_locks.pop(tender_id, None)
    except TenderNotFoundError:
        raise HTTPException(status_code=404, detail="Tender not found")


@app.get("/research/{tender_id:path}/audit")
def get_research_audit(
    tender_id: str,
    _token: str = Depends(require_internal_token),
) -> dict:
    entries = read_run(Path(runner.LOG_PATH), tender_id)
    run_id = entries[0]["params"].get("run_id") if entries else None
    return {"run_id": run_id, "entries": entries}


@app.get("/research/{tender_id:path}", response_model=ProspectResearch)
def get_stored_research(
    tender_id: str,
    _token: str = Depends(require_internal_token),
) -> ProspectResearch:
    result = store.get_research(tender_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No research found for tender")
    return result


