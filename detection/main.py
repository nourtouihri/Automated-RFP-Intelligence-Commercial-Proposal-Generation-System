"""
Tender Detection API. All endpoints except /health require X-Internal-Token.
Failures are rendered through the shared error envelope (shared/errors.py):
never FastAPI's ``{"detail": ...}``, never a raw 500.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from shared.auth import require_internal_token
from shared.errors import install
from shared.schemas import Tender
from shared import store
from detection.normalize import normalize_tender

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    yield


app = FastAPI(title="Tender Detection Service API", lifespan=lifespan)

# Error envelope + X-Request-ID propagation for every response, including
# 401 (missing token), 404 and unhandled 500s. Must run before first request.
install(app)


@app.get("/health")
def health() -> dict:
    """Liveness health check endpoint."""
    return {"status": "ok"}


@app.post("/tenders/ingest", response_model=Tender)
async def ingest_tender(
    data: dict,
    _token: str = Depends(require_internal_token),
) -> Tender:
    """
    Ingests, validates, deduplicates, and classifies an incoming tender payload.

    Rejects (empty title/issuer, bad deadline, over-cap raw_text, wrong types)
    surface as HTTP 422 with the shared error envelope; degraded-but-valid
    payloads are accepted with quality warnings.
    """
    tender, _is_existing = await normalize_tender(data)
    return tender


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["archived", "active"]


@app.patch("/tenders/{tender_id:path}/status", response_model=Tender)
def change_status(
    tender_id: str,
    body: StatusChange,
    _token: str = Depends(require_internal_token),
) -> Tender:
    """Archives a tender, or restores the status derived from its data quality."""
    tender = store.get_tender(tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    status = body.status
    if status == "active":
        quality = tender.quality
        incomplete = quality.missing_fields or quality.completeness < 0.4
        status = "incomplete" if incomplete else "new"
    updated = store.set_status(tender_id, status)
    if not updated:
        raise HTTPException(status_code=404, detail="Tender not found")
    return updated


@app.get("/tenders/{tender_id:path}", response_model=Tender)
def get_tender(
    tender_id: str,
    _token: str = Depends(require_internal_token),
) -> Tender:
    """Retrieves a single tender by tender_id."""
    tender = store.get_tender(tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    return tender


@app.get("/tenders", response_model=list[Tender])
def list_tenders(
    status: Optional[str] = Query(None),
    _token: str = Depends(require_internal_token),
) -> list[Tender]:
    """Lists tenders, optionally filtered by status query parameter."""
    return store.list_tenders(status)


@app.post("/tenders/seed")
async def seed_tenders(
    _token: str = Depends(require_internal_token),
) -> dict:
    """
    Bulk-loads simulated tender JSON feeds for testing.
    A malformed file is recorded in the response rather than failing the whole seed.
    """
    feed_dir = Path(__file__).parent / "data" / "simulated_feed"
    if not feed_dir.exists():
        raise HTTPException(status_code=404, detail="Seed data directory not found")

    results = []
    for f in sorted(feed_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            tender, is_existing = await normalize_tender(data)
            results.append({
                "file": f.name,
                "id": tender.id,
                "title": tender.title,
                "existing": is_existing,
                "status": "success",
            })
        except Exception as exc:
            results.append({
                "file": f.name,
                "status": "error",
                "error": str(exc),
            })

    return {"seeded": len(results), "tenders": results}
