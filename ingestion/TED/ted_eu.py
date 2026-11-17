import asyncio
import json
import sys
from datetime import date
from typing import Any

from pydantic import BaseModel

from ..base_handler import BaseHandler
from ..base_ingest import BaseIngest
from research.tools.fetch import fetch_url
from egressweave import EgressNotAllowedError
from ..utils.schema import Notice, TedBatchResponse, MappedBatch, TedNotice
from ..utils.helpers import (
    format_TED_date, 
    english_text, 
    parse_date, 
    fetch_description,
    split_description,
    source_limit
)

RAW_TEXT_MAX_CHARS = 20_000
REQUIREMENT_MAX_CHARS = 20_000
# A real TED search page is about 300 KiB, over fetch_url's 256 KiB default.
TED_MAX_BYTES = 4 * 1024 * 1024


class TedBatchIngestionHandler(BaseIngest):
    """Handler which fetches TED-specific (Europe) tenders."""

    ## @TODO: Find a way to fetch notices that didn't pass their deadline
    #  without fighting the deadline attribute
    TED_QUERY = (
        "contract-nature=services AND classification-cpv IN (48000000 72000000)"
        f" AND official-language=ENG "
        "AND notice-type IN (pin-cfc-standard pin-cfc-social pin-rtl compl) "
        "SORT BY publication-date DESC"
    )

    ## Per-page fetch limit, adjustable via INGEST_LIMITS (see source_limit)
    TED_PAGE_LIMIT = source_limit("TED")

    TED_FIELDS = [
        "notice-identifier",
        "notice-title",
        "organisation-name-buyer",
        "organisation-country-buyer",
        "deadline-receipt-request",
        "publication-date",
        "description-part",
        "description-proc",
        "description-lot",
        "description-glo",
        "notice-type"
    ]

    TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
    
    async def _fetch_tenders_async(self, page: int = 1) -> TedBatchResponse:
        payload = {
            "query": TedBatchIngestionHandler.TED_QUERY,
            "fields": TedBatchIngestionHandler.TED_FIELDS,
            "page": page,
            "limit": TedBatchIngestionHandler.TED_PAGE_LIMIT,
            "checkQuerySyntax": False,
        }
        raw = await fetch_url(
            TedBatchIngestionHandler.TED_SEARCH_URL, 
            "POST", 
            json_body=payload,
            max_bytes=TED_MAX_BYTES
        )
        return TedBatchResponse.model_validate_json(raw)

    def ingest(self, page: int = 1) -> TedBatchResponse:
        """Fetches TED tenders"""
        return asyncio.run(self._fetch_tenders_async(page))

class TedBatchMappingHandler(BaseHandler):
    """Handler which normalizes TED-specific (Europe's) tenders."""

    def _map(self, batch: TedBatchResponse)-> MappedBatch:
        """This maps TedBatchResponse to TedMappedBatch
        TedBatchResponse.notices are mapped to match TedMappedBatch.notices
        The Mapping strategy is as follows:
        ============
        Notice ; TedNotice
        id = notice_identifier; 
        title = notice_title.eng; 
        issuer = organisation_name_buyer.eng[0]; 
        issuer_country = organisation_country_buyer[0]; 
        source = "TED"; 
        notice_type = notice-type; 
        deadline =deadline_receipt_request[0]; # in ISO YYYY-MM-DD forma; 
        published_at = publication_date; #parsed as ISO YYYY-MM-DD
        raw_text = description # truncated to 20,000 characters; 
        requirements = [for sentence in description] # Each item(sentence) shouldn't exceed 20_000 by regular English
        """
        notices = [self._map_notice(notice) for notice in batch.notices]
        limit = TedBatchIngestionHandler.TED_PAGE_LIMIT
        page_cap = (batch.total_notice_count + limit - 1) // limit

        return MappedBatch(notices=notices, page_cap=page_cap)

    @staticmethod
    def _map_notice(notice: TedNotice) -> Notice:
        """Apply the mapping strategy documented on ``_map`` to one notice."""
        description = fetch_description(
            english_text(notice.description_glo),
            english_text(notice.description_proc),
            english_text(notice.description_lot),
        )
        return Notice(
            id=notice.notice_identifier,
            title=english_text(notice.notice_title),
            raw_text=description[:RAW_TEXT_MAX_CHARS],
            #requirements= split_description(description),
            # [
            #     text[:REQUIREMENT_MAX_CHARS] for text in descriptions
            issuer=(notice.organisation_name_buyer.get("eng") or [""])[0],
            issuer_country=(notice.organisation_country_buyer or [""])[0],
            source="TED",
            notice_type=notice.notice_type or "",
            deadline=parse_date(notice.deadline_receipt_request[0])
            if notice.deadline_receipt_request
            else date.today(),
            published_at=parse_date(notice.publication_date),
            links=notice.links
        )
    
    def handle(self, batch: TedBatchResponse) -> MappedBatch:
        normalized = self._map(batch)  
        
        return super().handle(normalized)

if __name__ == "__main__":
    # quick manual test -- run: uv run python -m ingestion.ted_eu | jq
    ingestion = TedBatchIngestionHandler(TedBatchMappingHandler())

    try:
        result = ingestion.run()
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