from typing import Literal, Optional, List, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from datetime import date, datetime
from .helpers import only_english
import hashlib
import logging
import uuid

logger = logging.getLogger(__name__)

class TedLinks(BaseModel):
    """English (ENG) pdfs/html links for a notice; other children ignored."""

    pdfs: dict[str, str] = Field(default_factory=dict)
    html: dict[str, str] = Field(default_factory=dict)

    @field_validator("pdfs", "html", mode="before")
    @classmethod
    def _keep_english(cls, value: Any) -> Any:
        return only_english(value)


class Notice(BaseModel):
    model_config = ConfigDict(strict=True)

    id: str
    title: str
    raw_text: str         # size cap enforced in normalize.py (20_000 chars)
    # TED notices can carry no requirements at all (`list[str] | None` without
    # a default still made it required); None flows through normalize, which
    # extracts requirements from raw_text when none are supplied.
    requirements: list[str] | None = None

    issuer: str           # explicit, never inferred
    issuer_country:str

    source: Literal["simulated_feed", "TED", "SAM"]
    notice_type:str

    deadline: date
    published_at: date
    links: TedLinks | List[str]


class TedNotice(BaseModel):
    """A single TED notice as returned by the search endpoint."""
    model_config = ConfigDict(populate_by_name=True)

    notice_identifier: str = Field(alias="notice-identifier")
    notice_type: str | None = Field(default=None, alias="notice-type")
    notice_title: dict[str, str] = Field(default_factory=dict, alias="notice-title")

    publication_number: str | None = Field(default=None, alias="publication-number")
    publication_date: str | None = Field(default=None, alias="publication-date")

    deadline_receipt_request: list[str] = Field(
        default_factory=list, alias="deadline-receipt-request"
    )
    
    organisation_country_buyer: list[str] = Field(
        default_factory=list, alias="organisation-country-buyer"
    )
    organisation_name_buyer: dict[str, list[str]] = Field(
        default_factory=dict, alias="organisation-name-buyer"
    )
    description_part: dict[str, Any] = Field(
        default_factory=dict, alias="description-part"
    )
    description_proc: dict[str, Any] = Field(
        default_factory=dict, alias="description-proc"
    )
    description_lot: dict[str, Any] = Field(
        default_factory=dict, alias="description-lot"
    )
    description_glo: dict[str, Any] = Field(
        default_factory=dict, alias="description-glo"
    )

    links: TedLinks = Field(default_factory=TedLinks)

    ## Mechanism that defines notice-identifier if they're missing
    @model_validator(mode="before")
    @classmethod
    def _ensure_notice_identifier(cls, data: Any) -> Any:
        """Inject a deterministic synthetic ID when TED omits notice-identifier."""
        if not isinstance(data, dict):
            return data

        # Skip if a real identifier already exists
        existing = data.get("notice-identifier", None)
        if isinstance(existing, str) and existing.strip():
            return data

        # Collect the parts we can derive a stable ID from
        ## We need notice-title, notice-type, and publication-date
        title_raw = data.get("notice-title", None)
        title = ""
        if isinstance(title_raw, dict):
            title = title_raw.get("eng", "")

        elif isinstance(title_raw, str):
            title = title_raw.strip()

        notice_type = data.get("notice-type")

        lower_parts = [p.lower() for p in (title, notice_type) if p]

        # 3. Deterministic hash when we have any material, uuid only as last resort
        if (len(lower_parts)==2):
            seed = "|".join(lower_parts)
            synthetic = "synthetic-" + hashlib.sha256(seed.encode()).hexdigest()[:32]
            logger.warning("Notice without identifier: derived sy nthetic id %s from %s",
                           synthetic, list(lower_parts))
        else:
            synthetic = "synthetic-" + str(uuid.uuid4())
            logger.warning("Notice without identifier and no title/type/date; falling back to random uuid %s",
                           synthetic)
        
        # Assign new id to notice-identifier
        data["notice-identifier"] = synthetic
        return data

    @field_validator("notice_title", mode="before")
    @classmethod
    def _keep_english_title(cls, value: Any) -> Any:
        return only_english(value)


class TedBatchResponse(BaseModel):
    """Envelope returned by the TED notices search endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    notices: list[TedNotice] = Field(default_factory=list)
    total_notice_count: int = Field(default=0, alias="totalNoticeCount")
    
    timed_out: bool = Field(default=False, alias="timedOut")

class SamNotice(BaseModel):
    """A single SAM.gov notice as returned by the opportunities endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    notice_id: str = Field(alias="noticeId")
    title: str = Field(default="", alias="title")
    notice_type: str = Field(default="", alias="type")

    description: str = Field(default="", alias="description")
    full_parent_path_name: str = Field(default="", alias="fullParentPathName")

    office_address: dict[str, Any] = Field(default_factory=dict, alias="officeAddress")
    point_of_contact: list[dict[str, Any]] | None = Field(
        default=None, alias="pointOfContact"
    )

    posted_date: str | None = Field(default=None, alias="postedDate")
    response_deadline: str | None = Field(default=None, alias="responseDeadLine")

    resource_links: list[str] | None = Field(default_factory=list, alias="resourceLinks")

    ui_link: str = Field(default="", alias="uiLink")


class SamBatchResponse(BaseModel):

    model_config = ConfigDict(populate_by_name=True)

    opportunities_data: list[SamNotice] = Field(default_factory=list, alias="opportunitiesData")
    total_records: int = Field(default=0, alias="totalRecords")

class MappedBatch(BaseModel):
    notices: list[Notice]= Field(default_factory=list)

    # ============= TED ================
    ## In mapping handler, this is total_notice_count / page
    ## Note that TedBatchResponse needs to have an attribute called page fetched from page parameter in _fetch_tenders_async
    # ============= SAM ================
    ## totalRecords are the number of total notices for a given query. 
    ## if limit is 2, total is 4, and offset is 0, it will display the first 2 notices
    ## To pass to the next page, we increment offset by 1. 
    ## Offset is just the page, it isn't the actual offset definition as we know it.
    # this is computed similarily to TED one, but we increment offset beforehand to match TED's.
    page_cap: int 
