"""Missing or broken template assets (logo, fonts, LibreOffice): a clear message, a non-zero
exit, and no partial file left in the output folder."""

import dataclasses
import json
import os
import shutil
import subprocess
import sys

import pytest

from proposal import demo, export, measure, render
from proposal.build import build
from proposal.config import DEFAULT
from proposal.schemas import Proposal


@pytest.fixture(autouse=True)
def website_theme():
    render.apply_theme("website")


@pytest.fixture
def sample():
    with open("proposal/sample_maison_aurele.json", encoding="utf-8") as f:
        return Proposal.model_validate(json.load(f))


@pytest.fixture
def fonts(monkeypatch, tmp_path):
    """Point font lookup at a folder holding only the given font files."""
    def use(*files):
        folder = tmp_path / "fonts"
        folder.mkdir(exist_ok=True)
        for f in files:
            shutil.copy(f, folder)
        monkeypatch.setattr(measure, "FONT_DIRS", [str(folder)])
        measure.font_file.cache_clear()
        measure._font.cache_clear()
    yield use
    measure.font_file.cache_clear()
    measure._font.cache_clear()


@pytest.fixture
def quiet_demo(monkeypatch, tmp_path):
    monkeypatch.setattr(demo, "_load_dotenv", lambda: None)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    return tmp_path / "out"


def files_in(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_a_missing_brand_font_is_reported_with_the_file_used_instead(sample, fonts, tmp_path):
    windows = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    arial = [os.path.join(windows, f) for f in ("arial.ttf", "arialbd.ttf")]
    if not all(map(os.path.isfile, arial)):
        pytest.skip("Arial is not installed here")
    fonts(*arial)
    built = build(sample, tmp_path / "d.pptx")
    gaps = [w for w in built.warnings if w.startswith("font not installed")]
    assert any("Inter" in w and "arial" in w.lower() for w in gaps)
    assert any("Montserrat" in w for w in gaps)


def test_installed_brand_fonts_raise_no_font_warning(sample, tmp_path):
    if not measure.font_file("Inter", False) or "Inter" not in measure.font_file("Inter", False):
        pytest.skip("Inter is not installed here")
    built = build(sample, tmp_path / "d.pptx")
    assert not any(w.startswith("font not installed") for w in built.warnings)


def test_the_demo_stops_before_writing_when_a_logo_is_missing(monkeypatch, quiet_demo, tmp_path,
                                                              capsys):
    gone = tmp_path / "gone.png"
    monkeypatch.setattr(demo, "DEFAULT", dataclasses.replace(DEFAULT, logo_lockup=gone))
    assert demo.main(["tender-014", "--replay", "--out", str(quiet_demo)]) == 2
    assert f"logo file not found: {gone}" in capsys.readouterr().err
    assert files_in(quiet_demo) == []


def test_the_demo_stops_before_writing_when_a_logo_is_corrupt(monkeypatch, quiet_demo, tmp_path,
                                                              capsys):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    monkeypatch.setattr(demo, "DEFAULT", dataclasses.replace(DEFAULT, logo_symbol=bad))
    assert demo.main(["tender-014", "--replay", "--out", str(quiet_demo)]) == 2
    assert "logo file is not a readable image" in capsys.readouterr().err
    assert files_in(quiet_demo) == []


def test_the_demo_stops_before_writing_when_no_font_is_installed(fonts, quiet_demo, capsys):
    fonts()
    assert demo.main(["tender-014", "--replay", "--out", str(quiet_demo)]) == 2
    assert "no font file" in capsys.readouterr().err
    assert files_in(quiet_demo) == []


def test_without_libreoffice_the_demo_writes_pptx_and_csv_and_says_pdf_skipped(monkeypatch,
                                                                             quiet_demo, capsys):
    def missing():
        raise FileNotFoundError("LibreOffice not found: put soffice on PATH or set SOFFICE_PATH")
    monkeypatch.setattr(export, "soffice_path", missing)
    assert demo.main(["tender-014", "--replay", "--out", str(quiet_demo)]) == 0
    assert "PDF skipped: LibreOffice not found" in capsys.readouterr().out
    assert files_in(quiet_demo) == ["tender-014.matrix.csv", "tender-014.pptx"]


def test_the_cli_reports_no_fonts_with_exit_code_2_and_writes_nothing(tmp_path):
    empty = tmp_path / "empty"
    (empty / "Fonts").mkdir(parents=True)
    env = {**os.environ, "WINDIR": str(empty), "LOCALAPPDATA": str(empty)}
    out = tmp_path / "out" / "d.pptx"
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "proposal",
                        "proposal/sample_maison_aurele.json", str(out)],
                       capture_output=True, text=True, env=env)
    if sys.platform != "win32":
        pytest.skip("font folders come from WINDIR only on Windows")
    assert r.returncode == 2 and "no deck written: no font file" in r.stderr
    assert "Traceback" not in r.stderr and not out.exists()
