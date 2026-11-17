"""F4: sanitizer fidelity — no over-eager HTML parsing, no warning noise.

Two defects the adversarial audit reproduced on the previous sanitizer:

- ``if "<" in value or "&" in value: _html_to_text(value)`` sent *any* angle
  bracket to the HTML parser. ``<contact@acme.tn>`` is not a tag, so the parser
  dropped the email — real client contact detail vanished and the record still
  looked clean.
- ``changed = value != original.strip()`` was true after CRLF/space collapsing,
  so every Windows/spreadsheet row raised ``sanitized_chars``. A warning that
  fires on ordinary payloads stops signalling that something actually ran.

These pin the fix: prose angle brackets are preserved, real markup is still
unwrapped, and only *semantic* changes flag the warning.
"""

import pytest

from detection.normalize import clean_untrusted_text


@pytest.mark.parametrize(
    "raw",
    [
        "Contact <contact@acme.tn> for the RFP pack.",
        "Budget < 5000 TND for phase one.",
        "a < b and c > d",
        "Delivery window 09:00 < 12:00 > 09:00.",
    ],
)
def test_angle_brackets_that_are_not_html_are_preserved(raw):
    cleaned, changed = clean_untrusted_text(raw)
    assert cleaned == raw
    assert changed is False


def test_real_markup_is_still_unwrapped_and_script_dropped():
    cleaned, changed = clean_untrusted_text(
        "<p>Deliver <b>MuleSoft</b>.</p><script>alert('xss')</script>"
    )
    assert cleaned == "Deliver MuleSoft."
    assert "alert" not in cleaned
    assert changed is True


@pytest.mark.parametrize(
    "raw",
    [
        "Line one\r\nLine two",
        "Double  space",
        "  padded  ",
        "tab\there",
    ],
)
def test_pure_whitespace_normalization_is_not_a_sanitization_event(raw):
    # The result may differ in whitespace; it must not claim a sanitization.
    _, changed = clean_untrusted_text(raw)
    assert changed is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a\u200bb", "ab"),                       # zero-width space
        ("a\u202eb", "ab"),                       # bidi override (Trojan Source)
        ("Réglementation\u00a0n°2", "Réglementation n°2"),  # NBSP fold
    ],
)
def test_semantic_sanitization_still_reports_changed(raw, expected):
    cleaned, changed = clean_untrusted_text(raw)
    assert cleaned == expected
    assert changed is True


def test_entities_without_markup_are_decoded():
    assert clean_untrusted_text("AT&amp;T bid") == ("AT&T bid", True)


@pytest.mark.parametrize("raw", ["R&D", "a & b", "Smith & Wesson"])
def test_bare_ampersand_is_not_an_entity(raw):
    cleaned, changed = clean_untrusted_text(raw)
    assert cleaned == raw
    assert changed is False
