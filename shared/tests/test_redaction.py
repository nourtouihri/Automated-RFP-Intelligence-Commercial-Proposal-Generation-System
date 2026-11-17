"""Secret scrubbing of log records.

The guarantee under test is that no credential reaches a log stream, including
via a provider exception whose rendering we do not control.
"""

import logging
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.errors import install
from shared.redaction import REDACTED, SecretScrubber, scrub

SECRET = "sk-live-abcdef0123456789XYZ"
SAM_KEY = "SAM-0123456789abcdef"


def _record(msg="failed", args=None, exc_info=None):
    return logging.LogRecord(
        name="research.extractor", level=logging.WARNING, pathname=__file__,
        lineno=1, msg=msg, args=args, exc_info=exc_info,
    )


def test_scrub_replaces_a_known_secret():
    with patch.dict("os.environ", {"LLM_API_KEY": SECRET}):
        assert scrub(f"key={SECRET} end") == f"key={REDACTED} end"


def test_scrub_leaves_text_without_secrets_untouched():
    text = "extracted 3 facts for tender 42"
    with patch.dict("os.environ", {"LLM_API_KEY": SECRET}):
        assert scrub(text) == text


def test_short_env_values_are_not_treated_as_secrets():
    """A placeholder token must not blank out ordinary log text."""
    text = "retrying (dev build, x attempts)"
    with patch.dict("os.environ", {"INTERNAL_SERVICE_TOKEN": "x", "LLM_API_KEY": "dev"}):
        assert scrub(text) == text


def test_scrub_covers_every_configured_secret_var():
    for var in ("LLM_API_KEY", "TAVILY_API_KEY", "INTERNAL_SERVICE_TOKEN"):
        with patch.dict("os.environ", {var: SECRET}):
            assert scrub(SECRET) == REDACTED, f"{var} was not scrubbed"


def test_ingest_api_keys_are_scrubbed(monkeypatch):
    monkeypatch.setenv("INGEST_API_KEYS", ",SAM-0123456789abcdef")
    assert "SAM-0123456789abcdef" not in scrub("GET https://api.sam.gov/x?api_key=SAM-0123456789abcdef")


def test_ingest_api_keys_entries_are_stripped_and_empty_or_short_ones_skipped(monkeypatch):
    """An empty slot would otherwise blank the whole line; a short entry
    follows the same placeholder rule as every other secret."""
    monkeypatch.setenv("INGEST_API_KEYS", " , SAM-0123456789abcdef ,dev")
    text = "dev build, api_key=SAM-0123456789abcdef"
    assert scrub(text) == f"dev build, api_key={REDACTED}"


def test_filter_scrubs_interpolated_arguments():
    rec = _record(msg="calling api with %s", args=(f"x-api-key={SECRET}",))
    with patch.dict("os.environ", {"LLM_API_KEY": SECRET}):
        SecretScrubber().filter(rec)
    assert SECRET not in rec.getMessage()
    assert REDACTED in rec.getMessage()


def test_filter_scrubs_the_rendered_traceback_and_drops_raw_exception():
    """The traceback is the interesting vector, and the hardest to control.

    The filter must pre-render it scrubbed *and* clear exc_info, because
    logging.Formatter falls back to formatting exc_info whenever exc_text is
    empty -- which would undo the scrub.
    """
    try:
        raise RuntimeError(f"auth failed, x-api-key={SECRET}")
    except RuntimeError:
        import sys

        rec = _record(exc_info=sys.exc_info())

    with patch.dict("os.environ", {"LLM_API_KEY": SECRET}):
        SecretScrubber().filter(rec)
    assert rec.exc_info is None, "raw exception left available for re-rendering"
    assert SECRET not in (rec.exc_text or "")

    # What a real handler would print, via the real formatting path.
    printed = logging.Formatter("%(message)s").format(rec)
    assert SECRET not in printed
    assert REDACTED in printed


def test_filter_is_idempotent():
    rec = _record(msg=f"token {SECRET}")
    scrubber = SecretScrubber()
    with patch.dict("os.environ", {"LLM_API_KEY": SECRET}):
        scrubber.filter(rec)
    once = rec.getMessage()
    scrubber.filter(rec)
    assert rec.getMessage() == once


def test_filter_leaves_a_record_without_secrets_untouched():
    """uvicorn re-formats its colored startup lines from record.args, so a clean
    record must keep both its template and its arguments."""
    rec = _record(msg="Started server process [%d]", args=(4242,))
    with patch.dict("os.environ", {"LLM_API_KEY": SECRET}):
        SecretScrubber().filter(rec)
    assert rec.msg == "Started server process [%d]"
    assert rec.args == (4242,)
    assert rec.getMessage() == "Started server process [4242]"


def test_filter_still_folds_and_clears_args_that_carry_a_secret():
    rec = _record(msg="calling api with %s", args=(f"x-api-key={SECRET}",))
    with patch.dict("os.environ", {"LLM_API_KEY": SECRET}):
        SecretScrubber().filter(rec)
    assert rec.msg == f"calling api with x-api-key={REDACTED}"
    assert rec.args == ()


def _raise_chained_sam_error():
    """What fetch_url raises on a SAM 5xx: the URL, key included, sits in the cause."""
    try:
        raise RuntimeError(f"Server error '503' for url 'https://api.sam.gov/x?api_key={SAM_KEY}'")
    except RuntimeError as cause:
        raise ValueError("Fetch failed") from cause


def _logged_on(caplog, logger_name):
    records = [r for r in caplog.records if r.name == logger_name]
    assert records, f"nothing was logged on {logger_name}"
    return "\n".join(logging.Formatter("%(message)s").format(r) for r in records)


def test_unhandled_error_log_carries_no_ingest_key(monkeypatch, caplog):
    """The key is only in the chained cause, so this proves the whole traceback
    is scrubbed on the way out of install()'s handler, not just the message."""
    monkeypatch.setenv("INGEST_API_KEYS", f",{SAM_KEY}")
    app = FastAPI()
    install(app)

    @app.get("/boom")
    def boom():
        _raise_chained_sam_error()

    with caplog.at_level(logging.ERROR, logger="shared.errors"):
        TestClient(app, raise_server_exceptions=False).get("/boom")

    logged = _logged_on(caplog, "shared.errors")
    assert SAM_KEY not in logged
    assert f"api_key={REDACTED}" in logged
    assert "ValueError: Fetch failed" in logged, "the traceback must stay usable"


def test_uvicorn_error_log_carries_no_ingest_key(monkeypatch, caplog):
    """Starlette re-raises an unhandled error once the handler has answered, and
    uvicorn logs it again, with the traceback, on its own error logger."""
    monkeypatch.setenv("INGEST_API_KEYS", f",{SAM_KEY}")
    install(FastAPI())

    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        try:
            _raise_chained_sam_error()
        except ValueError:
            logging.getLogger("uvicorn.error").error("Exception in ASGI application\n", exc_info=True)

    logged = _logged_on(caplog, "uvicorn.error")
    assert SAM_KEY not in logged
    assert f"api_key={REDACTED}" in logged


def test_install_attaches_one_scrubber_to_each_error_logger():
    """Every service calls install(); repeated calls must not stack filters."""
    install(FastAPI())
    install(FastAPI())

    for name in ("shared.errors", "uvicorn.error"):
        attached = [f for f in logging.getLogger(name).filters if isinstance(f, SecretScrubber)]
        assert len(attached) == 1, name
