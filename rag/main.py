"""
FastAPI service exposing the RAG retrieval as an HTTP endpoint.

Run locally with:
    uvicorn rag.main:app --reload --port 8001

n8n (or your teammates' agents) can then POST to:
    http://localhost:8001/query
"""


from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field
from rag.embeddings import EmbeddingError, get_model
from shared.errors import ApiError, ErrorCode, install
from shared.schemas import QueryRequest, QueryResult
from rag.query import RetrievalError, query_knowledge_base
from rag.storage import StatsError, count_records
from rag.supabase_client import RagConfigurationError, get_supabase
from shared.auth import require_internal_token

load_dotenv()

app = FastAPI(title="OliveSoft RAG Retrieval Service")

# Registered here too (detection and research already do): every service must
# answer 4xx/5xx in the one envelope with a stable `code`/`retryable` and echo
# X-Request-ID, so a caller never has to parse two response shapes.
install(app)



@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Report readiness only after the embedding model can be constructed."""
    try:
        get_model()
    except EmbeddingError as exc:
        raise ApiError(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            str(exc),
            status_code=503,
            retryable=True,
        ) from exc
    return {"status": "ready"}


@app.post("/query", response_model=list[QueryResult])
def query(
    request: QueryRequest,
    _token: str = Depends(require_internal_token),
) -> list[dict]:
    try:
        return query_knowledge_base(
            text=request.text,
            top_k=request.top_k,
            doc_type=request.doc_type,
            similarity_threshold=request.similarity_threshold,
        )
    except (RagConfigurationError, EmbeddingError, RetrievalError) as exc:
        # Do not expose provider URLs, credentials, or SDK exception details.
        # 503 + UPSTREAM_UNAVAILABLE tells the caller this is a transient
        # dependency fault worth retrying, not a bad request.
        raise ApiError(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            str(exc),
            status_code=503,
            retryable=True,
        ) from exc


@app.get("/stats")
def stats(_token: str = Depends(require_internal_token)) -> dict[str, int]:
    try:
        return count_records(get_supabase())
    except (RagConfigurationError, StatsError) as exc:
        raise ApiError(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            str(exc),
            status_code=503,
            retryable=True,
        ) from exc
