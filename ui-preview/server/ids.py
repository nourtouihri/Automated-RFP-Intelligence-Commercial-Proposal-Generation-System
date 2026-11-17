import re

from shared.errors import ApiError, ErrorCode

TENDER_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def is_deck_safe(tender_id: str) -> bool:
    # An id of only dots is collapsed as a dot-segment by httpx, which would
    # send the request to a different upstream route than the one asked for.
    return TENDER_ID_RE.fullmatch(tender_id) is not None and tender_id.strip(".") != ""


def is_plain_file_name(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name and name.strip(".") != ""


def require_deck_safe(tender_id: str) -> str:
    if not is_deck_safe(tender_id):
        raise ApiError(ErrorCode.BAD_REQUEST, "invalid tender id", field="tender_id", status_code=400)
    return tender_id
