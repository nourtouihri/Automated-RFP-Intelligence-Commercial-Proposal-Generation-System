import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import Body, FastAPI
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles

from shared.errors import ApiError, ErrorCode, current_request_id, error_envelope, install

from .config import Settings, load_settings
from .ids import is_deck_safe, is_plain_file_name, require_deck_safe
from .n8n_setup import repair_pipeline_webhook
from .rag_context import hits_by_record, team_matches
from .upstream import Upstream, _unavailable

UI_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)
HEALTH_PATHS = {"n8n": "/healthz"}
INGEST_SOURCES = {"TED", "SAM"}
PIPELINE_WEBHOOK = "/webhook/olivesoft-pipeline"
WEBHOOK_SETTLE_TRIES = 5
WEBHOOK_SETTLE_SECONDS = 1.0
# n8n's execution statuses, folded into the three the UI shows.
RUN_STATUS = {
    "new": "running",
    "running": "running",
    "waiting": "running",
    "success": "success",
    "error": "error",
    "crashed": "error",
    "canceled": "error",
}


class PipelineRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    limit: int = Field(3, ge=1, le=10)


class GenerateDeckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An object only; the proposal service owns the field list and refuses unknown ones.
    settings: dict | None = None
    # Strict booleans: "true" or 1 is a client bug to refuse, not to coerce. Sent on only when present.
    force_bid: StrictBool = False
    claim_check: StrictBool = False
    sector: str | None = None


def create_app(
    settings: Settings | None = None, transport: httpx.BaseTransport | None = None
) -> FastAPI:
    settings = settings or load_settings()
    upstream = Upstream(settings, transport)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        upstream.close()

    app = FastAPI(title="OliveSoft UI Proxy", lifespan=lifespan)
    install(app)
    app.state.settings = settings
    app.state.upstream = upstream

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/health")
    def services_health() -> list[dict]:
        names = list(settings.services)
        with ThreadPoolExecutor(max_workers=len(names)) as pool:
            statuses = pool.map(
                lambda name: upstream.probe(name, HEALTH_PATHS.get(name, "/health"), timeout=2.0),
                names,
            )
            return [
                {"id": name, "up": status is not None and 200 <= status < 300, "status": status}
                for name, status in zip(names, statuses)
            ]

    def read(service: str, path: str, params: dict | None = None):
        return upstream.call(service, "GET", path, params=params)[1]

    def encoded(tender_id: str) -> str:
        return quote(tender_id, safe="")

    @app.get("/api/tenders")
    def tenders(status: str | None = None):
        return read("detection", "/tenders", {"status": status} if status else None)

    @app.get("/api/tenders/{tender_id:path}")
    def tender(tender_id: str):
        return read("detection", f"/tenders/{encoded(tender_id)}")

    @app.get("/api/research")
    def research_all():
        return read("research", "/research")

    @app.get("/api/research/{tender_id:path}/audit")
    def research_audit(tender_id: str):
        return read("research", f"/research/{encoded(tender_id)}/audit")

    @app.get("/api/research/{tender_id:path}")
    def research(tender_id: str):
        return read("research", f"/research/{encoded(tender_id)}")

    @app.get("/api/insights")
    def insights_all() -> dict:
        """Stored competitor & budget insights per tender. A tender the agent
        has not run for simply stays out, the way proposals() skips them."""
        out = {}
        for item in read("detection", "/tenders"):
            tender_id = item["id"]
            try:
                out[tender_id] = read("insights", f"/insights/{encoded(tender_id)}")
            except ApiError as error:
                if error.status_code != 404:
                    raise
        return out

    @app.get("/api/insights/{tender_id:path}")
    def insights(tender_id: str):
        return read("insights", f"/insights/{encoded(tender_id)}")

    @app.post("/api/insights/{tender_id:path}")
    def run_insights(tender_id: str):
        # A run spends search and model budget, so it is a POST like research.
        return post("insights", f"/insights/{encoded(tender_id)}", timeout="insights")

    @app.get("/api/proposals")
    def proposals() -> dict:
        decks = {}
        for item in read("detection", "/tenders"):
            tender_id = item["id"]
            if not is_deck_safe(tender_id):
                continue
            try:
                decks[tender_id] = read("proposal", f"/proposal/{tender_id}")
            except ApiError as error:
                if error.status_code != 404:
                    raise
        return decks

    @app.get("/api/proposal/{tender_id}/review")
    def review(tender_id: str):
        return read("proposal", f"/proposal/{encoded(require_deck_safe(tender_id))}/review")

    @app.put("/api/proposal/{tender_id}/review")
    def save_review(tender_id: str, body: dict = Body(...)):
        return upstream.call(
            "proposal", "PUT", f"/proposal/{encoded(require_deck_safe(tender_id))}/review", json=body
        )[1]

    ## This sends & injects the api call into the js
    @app.put("/api/proposal/edit/{tender_id}")
    def prompt_edit_proposal(tender_id:str, body:dict=Body(...)):
        return upstream.call(
            "proposal", 
            "PUT", 
            f"/proposal/edit/{encoded(require_deck_safe(tender_id))}",
            json=body
        )[1]

    ## This sends & injects the api call into the js
    @app.put("/api/proposal/accept/{tender_id}")
    def accept_proposal(tender_id: str):
        return upstream.call(
            "proposal",
            "PUT",
            f"/proposal/accept/{encoded(require_deck_safe(tender_id))}",
        )[1]

    ## This sends & injects the api call into the js
    @app.put("/api/proposal/refuse/{tender_id}")
    def refuse_proposal(tender_id: str):
        return upstream.call(
            "proposal",
            "PUT",
            f"/proposal/refuse/{encoded(require_deck_safe(tender_id))}",
        )[1]

    @app.get("/api/proposal/{tender_id:path}")
    def proposal(tender_id: str):
        return read("proposal", f"/proposal/{encoded(require_deck_safe(tender_id))}")

    def post(service: str, path: str, *, json=None, params: dict | None = None, timeout: str = "default"):
        return upstream.call(
            service, "POST", path, json=json, params=params, timeout=settings.timeouts[timeout]
        )[1]

    @app.patch("/api/tenders/{tender_id:path}/status")
    def change_tender_status(tender_id: str, body: dict = Body(...)):
        return upstream.call("detection", "PATCH", f"/tenders/{encoded(tender_id)}/status", json=body)[1]

    @app.post("/api/tenders/ingest")
    def ingest_tender(body: dict = Body(...)):
        return post("detection", "/tenders/ingest", json=body)

    @app.post("/api/tenders/seed")
    def seed_tenders():
        return post("detection", "/tenders/seed", timeout="ingest")

    @app.post("/api/ingest/{source}")
    def ingest(source: str, page: int = Body(embed=True)):
        if source not in INGEST_SOURCES:
            raise ApiError(
                ErrorCode.BAD_REQUEST,
                f"Unknown source; expected one of {', '.join(sorted(INGEST_SOURCES))}.",
                field="source",
                status_code=400,
            )
        return post("ingestion", f"/ingest/{source}", json={"page": page}, timeout="ingest")

    @app.post("/api/notices/send")
    def send_notices(notices: list[dict] = Body(embed=True)) -> dict:
        results = []
        for notice in notices:
            row = {"id": str(notice.get("id", "")), "ok": True, "tender": None, "error": None}
            try:
                row["tender"] = post("detection", "/tenders/ingest", json=notice)
            except ApiError as error:
                row["ok"] = False
                row["error"] = error_envelope(
                    error.code,
                    error.message,
                    field=error.field,
                    retryable=error.retryable,
                    request_id=current_request_id() or None,
                )
            results.append(row)
        return {"results": results}

    @app.post("/api/research/{tender_id:path}")
    def run_research(tender_id: str, force: bool | None = None):
        return post(
            "research",
            f"/research/{encoded(tender_id)}",
            params={"force": force} if force is not None else None,
            timeout="research",
        )

    @app.post("/api/proposal/{tender_id:path}")
    def generate_deck(tender_id: str, body: GenerateDeckBody | None = None):
        safe_id = require_deck_safe(tender_id)
        tender = read("detection", f"/tenders/{encoded(safe_id)}")
        cv_matches, project_matches = team_matches(upstream, tender, None)
        payload = {"cv_matches": cv_matches, "project_matches": project_matches}
        if body and body.settings is not None:
            payload["settings"] = body.settings
        if body:
            payload.update({flag: getattr(body, flag) for flag in ("force_bid", "claim_check", "sector")
                            if flag in body.model_fields_set})
        deck = post("proposal", f"/proposal/{encoded(safe_id)}", json=payload, timeout="deck")
        return {**deck, "hits": hits_by_record(cv_matches, project_matches)}

    @app.get("/api/files/{tender_id}/{name:path}")
    def deck_file(tender_id: str, name: str):
        if not is_deck_safe(tender_id) or not is_plain_file_name(name):
            raise ApiError(ErrorCode.NOT_FOUND, "File not found", status_code=404)
        response = upstream.stream("proposal", f"/proposal/{encoded(tender_id)}/files/{encoded(name)}")
        chunks = response.iter_bytes()
        try:
            first = next(chunks, b"")
        except httpx.HTTPError:
            response.close()
            raise _unavailable("proposal", "could not be reached.") from None

        def body():
            try:
                yield first
                yield from chunks
            finally:
                response.close()

        passed = ("content-type", "content-disposition")
        if "content-encoding" not in response.headers:
            passed += ("content-length",)
        headers = {key: response.headers[key] for key in passed if key in response.headers}
        return StreamingResponse(body(), headers=headers, background=BackgroundTask(response.close))

    @app.post("/api/query")
    def query(body: dict = Body(...)):
        return post("rag", "/query", json=body)

    @app.get("/api/library/stats")
    def library_stats():
        return read("rag", "/stats")

    def pipeline_refusal(error: ApiError) -> ApiError:
        if error.status_code == 404:
            return ApiError(
                ErrorCode.NOT_FOUND,
                "The n8n pipeline is not active: import Phase 2 RFP Orchestration in n8n and switch it to Active.",
                status_code=404,
            )
        if error.status_code in (401, 403):
            return ApiError(
                ErrorCode.UNAUTHORIZED,
                "n8n refused the call: give its Webhook node a Header Auth credential named X-Internal-Token holding INTERNAL_SERVICE_TOKEN.",
                status_code=error.status_code,
            )
        if error.status_code == 503 and "answered 500" in error.message:
            return ApiError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "n8n's Webhook node has no credential: set UIP_N8N_API_KEY so the UI can add it from .env, or add a Header Auth credential named X-Internal-Token holding INTERNAL_SERVICE_TOKEN.",
                status_code=503,
            )
        return error

    @app.post("/api/pipeline/run", status_code=202)
    def run_pipeline(body: PipelineRunBody | None = None):
        payload = (body or PipelineRunBody()).model_dump()
        try:
            return post("n8n", PIPELINE_WEBHOOK, json=payload)
        except ApiError as error:
            refused = error
        # n8n answers 404 for an unpublished workflow, 401/403 for a wrong token and 500 (seen here as 503)
        # when the Webhook node has no credential: each is repaired from .env once, then the call is retried.
        if settings.n8n_api_key and refused.status_code in (401, 403, 404, 503):
            try:
                repaired = repair_pipeline_webhook(
                    upstream, settings, token_refused=refused.status_code in (401, 403)
                )
            except ApiError as error:
                logger.warning("Could not repair the n8n pipeline webhook: %s", error.message)
                repaired = False
            # n8n swaps in a re-published webhook a moment later; until then it answers 404, or 500 for the
            # credential it had before, so those are retried briefly.
            for _ in range(WEBHOOK_SETTLE_TRIES if repaired else 0):
                try:
                    return post("n8n", PIPELINE_WEBHOOK, json=payload)
                except ApiError as error:
                    refused = error
                if not (refused.status_code == 404 or "answered 500" in refused.message):
                    break
                time.sleep(WEBHOOK_SETTLE_SECONDS)
        raise pipeline_refusal(refused) from None

    @app.get("/api/pipeline/runs/{execution_id}")
    def pipeline_run(execution_id: str) -> dict:
        if not settings.n8n_api_key:
            raise ApiError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "UIP_N8N_API_KEY is not set, so the run's progress in n8n cannot be read.",
                status_code=503,
            )
        if not execution_id.isdigit():
            raise ApiError(ErrorCode.NOT_FOUND, "Run not found", status_code=404)
        headers = {"X-N8N-API-KEY": settings.n8n_api_key}
        path = f"/api/v1/executions/{execution_id}"
        run = upstream.call("n8n", "GET", path, headers=headers)[1]
        status = RUN_STATUS.get(run.get("status"), "running")
        error = failed_node = None
        if status == "error":
            # Only a failed run is re-read with its data, which holds every node's output.
            data = upstream.call("n8n", "GET", path, params={"includeData": "true"}, headers=headers)[1]
            result = ((data.get("data") or {}).get("resultData") or {})
            error = (result.get("error") or {}).get("message") or "The run stopped in n8n."
            failed_node = result.get("lastNodeExecuted")
        return {
            "id": execution_id,
            "status": status,
            "started_at": run.get("startedAt"),
            "stopped_at": run.get("stoppedAt"),
            "workflow_id": run.get("workflowId"),
            "error": error,
            "failed_node": failed_node,
        }

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(UI_ROOT / "index.html")

    app.mount("/src", StaticFiles(directory=UI_ROOT / "src"), name="src")
    app.mount("/vendor", StaticFiles(directory=UI_ROOT / "vendor"), name="vendor")
    return app


app = create_app()
