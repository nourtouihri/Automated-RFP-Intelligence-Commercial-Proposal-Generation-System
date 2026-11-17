"""
Fetch active notices/opportunities from SAM.gov.

Requires:
    pip install requests

Get a public API key at https://sam.gov -> Account Settings -> API Key.
The spec requires `postedFrom` / `postedTo` (mm/dd/yyyy) whenever `limit` is sent,
so this script always sends a date window (defaults to the last 30 days).
It also filters by response deadline (`rdlfrom` = today) so only still-active
notices are returned.
"""
import os
from dotenv import load_dotenv
from pydantic import BaseModel
import sys
from datetime import datetime, timedelta
import json
import requests
from egressweave import EgressNotAllowedError
from ..base_ingest import BaseIngest
from ..base_handler import BaseHandler
from typing import List
from ..utils.schema import (
    SamNotice, 
    SamBatchResponse,
    MappedBatch,
    Notice
)
from  ..utils.helpers import parse_date, extract_sam_description, source_limit
from research.tools.fetch import fetch_url
from shared.redaction import scrub
from urllib.parse import urlencode
import urllib.parse
import asyncio
import logging

load_dotenv()
logger = logging.getLogger(__name__)
"""
NAICS:
541512 - Computer Systems Design Services
541511 - Custom Computer Programming Services
541519 - Other Computer Related Services
541715 - Research and Development in the Physical, Engineering, and Life Sciences (except Nanotechnology and Biotechnology)
541611 - Administrative Management and General Management Consulting Services 

PSC:
DA10 - IT AND TELECOM - BUSINESS APPLICATION/APPLICATION DEVELOPMENT SOFTWARE AS A SERVICE
DD01 - IT AND TELECOM - SERVICE DELIVERY SUPPORT SERVICES: ITSM, OPERATIONS CENTER, PROJECT/PM (LABOR)
DH01 - IT AND TELECOM - PLATFORM SUPPORT SERVICES: DATABASE, MAINFRAME, MIDDLEWARE (LABOR)
DH10 - IT AND TELECOM - PLATFORM AS A SERVICE: DATABASE, MAINFRAME, MIDDLEWARE 
"""

"""
Difference between postedFrom and postedTo is capped at 1 year
limit is a MUST if you provide limit
"""

BASE_URL = "https://api.sam.gov/opportunities/v2/search"
# API pages, not web pages: SAM keeps the 64 MiB its fetches ran with rather
# than fetch_url's 256 KiB default.
SAM_MAX_BYTES = 64 * 1024 * 1024
class SamBatchIngestionHandler(BaseIngest):
    """Handler which fetches TED-specific (Europe) tenders."""

    SAM_SEARCH_BASE_URL = "https://api.sam.gov/opportunities/v2/search"
    ## Per-page fetch limit, adjustable via INGEST_LIMITS (see source_limit)
    LIMIT = source_limit("SAM")
    async def _fetch_tenders_async(self, page: int = 1) -> List[SamNotice]:
        today = datetime.now()
        posted_from = today - timedelta(days=364)
        params = {
            "api_key": self._api_key,
            "limit": str(SamBatchIngestionHandler.LIMIT),
            "offset": str(page - 1),
            # Required when limit is provided (per spec)
            "postedFrom": posted_from.strftime("%m/%d/%Y"),
            "postedTo": today.strftime("%m/%d/%Y"),
            # Only include notices whose response deadline hasn't passed
            "rdlfrom": today.strftime("%m/%d/%Y"),
            "ncode": "541"
        }
        #url = f"{SamBatchIngestionHandler.SAM_SEARCH_BASE_URL}?{urlencode(params, quote_via=urllib.parse.quote, safe='/')}"
        
        raw = await fetch_url(
            SamBatchIngestionHandler.SAM_SEARCH_BASE_URL,
            params=params,
            max_bytes=SAM_MAX_BYTES
        )

        return SamBatchResponse.model_validate_json(raw)

    def ingest(self, page: int = 1) -> SamNotice:
        """Fetches TED tenders"""
        return asyncio.run(self._fetch_tenders_async(page))

class SamBatchMappingHandler(BaseHandler):
    def _map(self, batch: SamBatchResponse)-> MappedBatch:
        """This maps SamBatchResponse to SamMappedBatch
        SamBatchResponse.opportunities_data are mapped to match SamMappedBatch.notices
        The Mapping strategy is as follows:
        ============
        Notice ; SamNotice
        id = notice_id; 
        title = title; 
        issuer = full_parent_path_name; 
        issuer_country = office_address.countryCode; 
        source = "SAM"; 
        notice_type = notice_type; 
        deadline = response_deadline; # in ISO YYYY-MM-DD forma; 
        published_at = publication_date; #parsed as ISO YYYY-MM-DD
        raw_text = fetches description # Here, the description is a link, so it fetches it to display it. Capped at 20_000 chars
        """
        notices = [self._map_notice(notice) for notice in batch.opportunities_data]
        limit = SamBatchIngestionHandler.LIMIT
        page_cap = ((batch.total_records + limit - 1) // limit) # Decrement because offset starts with 0, not 1

        return MappedBatch(notices=notices, page_cap=page_cap)

    def __init__(self, next_handler: "BaseHandler | None" = None, api_key: str = "") -> None:
        super().__init__(next_handler)
        self._api_key = api_key

    def _fetch_description(self, url: str) -> str:
        # fetch_url refuses URLs carrying a query string, so the
        # ``noticedesc?noticeid=...`` link travels as base URL + params.
        parts = urllib.parse.urlsplit(url)
        params = dict(urllib.parse.parse_qsl(parts.query))
        params["api_key"] = self._api_key
        base = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        res = asyncio.run(fetch_url(base, params=params, max_bytes=SAM_MAX_BYTES))
        return extract_sam_description(json.loads(res).get("description"))

    def _map_notice(self, notice: SamNotice) -> Notice:
        """Apply the mapping strategy documented on ``_map`` to one notice."""
        raw_text = ""
        if notice.description:
            try:
                raw_text = self._fetch_description(notice.description)
            except Exception as exc:
                logger.warning("SAM description fetch failed for %s: %s", notice.notice_id, scrub(str(exc)))

        return Notice(
            id=notice.notice_id,
            title=notice.title,
            raw_text=raw_text,
            issuer=notice.full_parent_path_name,
            issuer_country=notice.office_address.get("countryCode") or "USA",
            source="SAM",
            notice_type=notice.notice_type or "",
            deadline=parse_date(notice.response_deadline),
            published_at=parse_date(notice.posted_date),
            links=notice.resource_links or [],
        )
    
    def handle(self, batch: SamBatchResponse) -> MappedBatch:
        normalized = self._map(batch)  
        
        return super().handle(normalized)

if __name__ == "__main__":
    
    API_KEY = os.getenv("INGEST_API_KEYS").split(",")[1]
    # quick manual test -- run: uv run python -m ingestion.ted_eu | jq
    ingestion = SamBatchIngestionHandler(SamBatchMappingHandler(api_key=API_KEY), API_KEY)

    try:
        result = ingestion.run(2)
    except EgressNotAllowedError as e:
        print(f"egress blocked (cause: {e.__cause__!r})", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"chain FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if isinstance(result, BaseModel):
        sys.stdout.write(result.model_dump_json(by_alias=True) + "\n")
    else:
        sys.stdout.write(json.dumps(result, default=str) + "\n")
