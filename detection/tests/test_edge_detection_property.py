"""Hypothesis property: the ingest boundary never raises an unexpected error.

Any payload — however malformed — must come back as either a ``Tender``
(possibly flagged degraded) or a ``ValidationError`` (the envelope-backed
``ApiError``; the handler maps it to 422). Any other exception class is a bug,
because it would surface as a raw 500 to n8n. The LLM transport is mocked so
the property is about the normalization logic, not the provider.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from shared import store
from shared.schemas import Tender
from detection.normalize import ValidationError, normalize_tender

# Surrogates excluded explicitly: SQLite cannot store lone surrogates, and
# their behavior in text strategies has changed across hypothesis versions.
_TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=80)


def _payload_strategy():
    return st.fixed_dictionaries(
        {
            "title": _TEXT,
            "issuer": _TEXT,
            "raw_text": st.one_of(
                st.none(),
                st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=200),
            ),
            "deadline": st.one_of(
                st.none(), st.dates(), st.datetimes(), st.text(max_size=12), st.integers()
            ),
            "requirements": st.one_of(
                st.none(),
                st.text(max_size=50),
                st.integers(),
                st.lists(
                    st.one_of(
                        st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=40),
                        st.integers(),
                    ),
                    max_size=5,
                ),
            ),
            "source": st.one_of(
                st.none(), st.sampled_from(["manual", "simulated_feed"]), st.text(max_size=10)
            ),
            "detected_at": st.one_of(st.none(), st.datetimes(), st.text(max_size=20)),
            "unknown_extra": st.text(max_size=10),
        }
    )


@pytest.fixture(scope="module", autouse=True)
def isolated_db(tmp_path_factory):
    """Module-scoped DB so hypothesis never fights pytest fixture scoping."""
    original = store.DB_PATH
    store.DB_PATH = tmp_path_factory.mktemp("hypothesis") / "property.db"
    store.init_db()
    yield
    store.DB_PATH = original


@given(payload=_payload_strategy())
@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_property_normalize_returns_tender_or_api_error(payload):
    with patch(
        "detection.normalize.llm_call",
        new_callable=AsyncMock,
        return_value='["do the thing"]',
    ):
        try:
            result = asyncio.run(normalize_tender(dict(payload)))
        except ValidationError:
            return

    tender, _is_existing = result
    assert isinstance(tender, Tender)
    # title + issuer are mandatory, so their weight (0.30) is the floor.
    assert 0.30 <= tender.quality.completeness <= 1.0
    assert isinstance(tender.quality.warnings, list)
    assert isinstance(tender.quality.missing_fields, list)
