"""
Ingestion API. All endpoints except /health require X-Internal-Token.
Validation failures surface as HTTP 422.
"""
import os
from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from shared.auth import require_internal_token
from shared.redaction import scrub
from research.tools.fetch import FetchError
from .base_ingest import BaseIngest
from .TED.ted_eu import TedBatchIngestionHandler, TedBatchMappingHandler
from .USA.sam import SamBatchIngestionHandler, SamBatchMappingHandler
from .utils.schema import MappedBatch
from shared.errors import install, ApiError, ErrorCode
load_dotenv()


app = FastAPI(title="TED Ingestion Service API")

install(app)


@app.get("/health")
def health() -> dict:
    """Liveness health check endpoint."""
    return {"status": "ok"}


class IngestRequest(BaseModel):
    """POST /ingest body. ``page`` is required: a missing value fails validation."""

    page: int = Field(..., ge=1)


def _run(source: str, ingestion: BaseIngest, page: int) -> MappedBatch:
    """A refused or failed source fetch (429 quota, 5xx, timeout) is a retryable 503, not a 500."""
    try:
        return ingestion.run(page)
    except FetchError as exc:
        raise ApiError(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            f"{source} could not be fetched ({scrub(str(exc))}). Try again later.",
            status_code=503,
            retryable=True,
        ) from exc


@app.post("/ingest/TED", response_model=MappedBatch)
def ingest_ted(
    body: IngestRequest,
    _token: str = Depends(require_internal_token),
) -> MappedBatch:
    """
    Runs the ingestion chain for the requested TED page.

    Returns HTTP 401 on a missing/invalid X-Internal-Token, 422 when the
    body is invalid (including a missing ``page``) and 503 when TED fails.
    """
    return _run("TED", TedBatchIngestionHandler(TedBatchMappingHandler()), body.page)

@app.post("/ingest/SAM", response_model=MappedBatch)
def ingest_sam(
    body: IngestRequest,
    _token: str = Depends(require_internal_token),
) -> MappedBatch:
    """
    Runs the ingestion chain for the requested SAM.gov page.

    Returns HTTP 401 on a missing/invalid X-Internal-Token, 422 when the
    body is invalid (including a missing ``page``), 500 when the SAM key is
    not configured and 503 when SAM.gov fails (429 once the key's quota is spent).
    """
    api_keys = os.getenv("INGEST_API_KEYS")
    if((not api_keys) or (len(api_keys.split(",")) <2)):
        """ Raise an error, like how it's raised in detection module"""
        raise ApiError(
            ErrorCode.INTERNAL,
            "SAM API key missing: INGEST_API_KEYS must contain a SAM key as its second entry",
            status_code=500,
            retryable=False,
        )

    api_key = api_keys.split(",")[1]
    ingestion = SamBatchIngestionHandler(
        SamBatchMappingHandler(api_key=api_key),
        api_key=api_key
    )
    return _run("SAM.gov", ingestion, body.page)
