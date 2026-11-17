"""The OliveSoft logo on every slide, and a clear error when a logo file is missing or broken."""

import dataclasses
import json

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from proposal import render
from proposal.build import build
from proposal.config import DEFAULT
from proposal.schemas import NoBid, Proposal
from proposal.validate import check_logo_overlap, validate

PX = 9525


@pytest.fixture(autouse=True, scope="module")
def website_theme():
    render.apply_theme("website")


@pytest.fixture
def sample():
    with open("proposal/sample_maison_aurele.json", encoding="utf-8") as f:
        return Proposal.model_validate(json.load(f))


@pytest.fixture
def no_bid(sample):
    rows = [r.model_copy(update={"score": 0.2, "fit": "Gap"}) for r in sample.requirements]
    return NoBid(meta=sample.meta, requirements=rows, warnings=["no-bid recommendation"],
                 recommendation="Do not bid.")


def pictures(path, n):
    return {sh.name: sh for sh in Presentation(str(path)).slides[n - 1].shapes
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE}


def box(sh):
    return (sh.left / PX, sh.top / PX, sh.width / PX, sh.height / PX)


def test_the_logo_files_live_in_the_config_and_exist():
    assert DEFAULT.logo_lockup.is_file() and DEFAULT.logo_symbol.is_file()
    assert DEFAULT.logo_lockup.parent.name == "assets"


def test_the_cover_shows_the_lockup_in_place_of_the_text_wordmark(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    logo = pictures(path, 1)["logo-lockup"]
    x, y, w, h = box(logo)
    iw, ih = Image.open(DEFAULT.logo_lockup).size
    assert round(x) == 86 and abs(w / h - iw / ih) < 0.01
    texts = [sh.text_frame.text for sh in Presentation(str(path)).slides[0].shapes
             if sh.has_text_frame]
    assert "OliveSoft" not in texts


def test_every_other_slide_shows_the_symbol_in_the_footer_corner(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    iw, ih = Image.open(DEFAULT.logo_symbol).size
    for n in range(2, 10):
        x, y, w, h = box(pictures(path, n)["logo-symbol"])
        assert abs(w / h - iw / ih) < 0.01
        assert 650 <= y and y + h <= 684 and x + w <= 1195.5, n


def test_the_no_bid_deck_gets_the_same_logos(no_bid, tmp_path):
    path = tmp_path / "n.pptx"
    render.render_no_bid(no_bid, str(path))
    assert "logo-lockup" in pictures(path, 1)
    assert all("logo-symbol" in pictures(path, n) for n in (2, 3))


def test_no_logo_overlaps_text_and_the_decks_pass_the_validator(sample, no_bid, tmp_path):
    for deck, draw in ((sample, render.render), (no_bid, render.render_no_bid)):
        path = tmp_path / "x.pptx"
        draw(deck, str(path))
        assert check_logo_overlap(str(path)) == []
        assert validate(str(path)) == []


def test_the_overlap_check_catches_a_logo_on_top_of_text(sample, tmp_path):
    path = tmp_path / "d.pptx"
    render.render(sample, str(path))
    prs = Presentation(str(path))
    logo = next(sh for sh in prs.slides[1].shapes if sh.name == "logo-symbol")
    logo.left, logo.top = 90 * PX, 660 * PX  # onto the footer text
    prs.save(str(path))
    issues = check_logo_overlap(str(path))
    assert [(i.slide, i.kind) for i in issues] == [(2, "overlap")]
    assert "logo-symbol" in issues[0].detail and "footer" in issues[0].detail


@pytest.mark.parametrize("which", ["logo_lockup", "logo_symbol"])
def test_a_missing_logo_is_a_clear_error_and_no_file_is_written(sample, tmp_path, which):
    missing = tmp_path / "nope.png"
    config = dataclasses.replace(DEFAULT, **{which: missing})
    out = tmp_path / "out"
    with pytest.raises(render.LogoError, match="logo file not found: .*nope.png"):
        build(sample, out / "d.pptx", config=config)
    assert not out.exists() or list(out.iterdir()) == []


@pytest.mark.parametrize("content", [b"not a png at all", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40])
def test_a_corrupt_logo_is_a_clear_error_and_no_file_is_written(sample, tmp_path, content):
    bad = tmp_path / "bad.png"
    bad.write_bytes(content)
    out = tmp_path / "out"
    with pytest.raises(render.LogoError, match="logo file is not a readable image: .*bad.png"):
        build(sample, out / "d.pptx", config=dataclasses.replace(DEFAULT, logo_symbol=bad))
    assert not out.exists() or list(out.iterdir()) == []


def test_render_checks_the_logos_before_writing_anything(sample, tmp_path):
    path = tmp_path / "d.pptx"
    with pytest.raises(render.LogoError):
        render.render(sample, str(path), config=dataclasses.replace(DEFAULT, logo_lockup=tmp_path))
    assert not path.exists()
