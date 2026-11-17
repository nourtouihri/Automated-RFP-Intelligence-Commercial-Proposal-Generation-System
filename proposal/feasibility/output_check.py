"""Matrix A checks A7 (output validity) and A8 (missing or broken template assets).

    python -X utf8 proposal/feasibility/output_check.py [<out.md>]

A7 opens the three showcase decks: slide count (python-pptx), the PDF and its page
count (pypdf), and the matrix CSV's row count against the tender's requirement count.

A8 runs `python -m proposal.demo tender-014 --replay` as a separate process, each time
on a temporary copy of the package with one asset broken (the real files are never
touched), and records the message shown, the exit code and the files left in --out.
Default output: proposal/feasibility/results/output_check.md.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pptx import Presentation
from pypdf import PdfReader

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "proposal"
SHOWCASE = PKG / "showcase"
EXPECTED_SLIDES = {"proposal": 9, "no_bid": 3}


def a7() -> list[dict]:
    rows = []
    for rec_path in sorted((SHOWCASE / "recordings").glob("*.json")):
        tid = rec_path.stem
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        kind = "no_bid" if rec["source"]["kind"] == "no_bid" else "proposal"
        pptx, pdf, csv_path = (SHOWCASE / f"{tid}{ext}" for ext in (".pptx", ".pdf", ".matrix.csv"))
        slides = len(Presentation(str(pptx)).slides) if pptx.is_file() else None
        pages = len(PdfReader(str(pdf)).pages) if pdf.is_file() else None
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            csv_rows = sum(1 for _ in csv.DictReader(f))
        reqs = len(rec["tender"]["requirements"])
        ok = slides == pages == EXPECTED_SLIDES[kind] and csv_rows == reqs
        rows.append({"deck": tid, "kind": kind, "slides": slides, "pdf": pdf.is_file(),
                     "pdf_pages": pages, "csv_rows": csv_rows, "requirements": reqs, "ok": ok})
    return rows


def _fonts_dir(root: Path, files: list[Path]) -> Path:
    windir = root / "windows"
    (windir / "Fonts").mkdir(parents=True)
    for f in files:
        shutil.copy(f, windir / "Fonts")
    return windir


def a8() -> list[dict]:
    windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    arial = [windows_fonts / "arial.ttf", windows_fonts / "arialbd.ttf"]
    scenarios = [
        ("none (control)", None),
        ("(a) logo file missing", "logo_missing"),
        ("(b) logo file corrupt", "logo_corrupt"),
        ("(c) Montserrat and Inter missing, Arial present", "brand_fonts_missing"),
        ("(c') no font installed at all", "no_fonts"),
        ("(d) LibreOffice missing", "no_libreoffice"),
    ]
    rows = []
    for label, case in scenarios:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copytree(PKG, tmp / "proposal",
                            ignore=shutil.ignore_patterns("__pycache__", "results", "tests"))
            out = tmp / "out"
            env = {k: v for k, v in os.environ.items() if k != "LLM_API_KEY"}
            if case == "logo_missing":
                (tmp / "proposal" / "assets" / "OliveSoft_Horizontal_Lockup.png").unlink()
            if case == "logo_corrupt":
                path = tmp / "proposal" / "assets" / "OliveSoft_Symbol_from_svg.png"
                path.write_bytes(path.read_bytes()[:200])  # a truncated download
            if case in ("brand_fonts_missing", "no_fonts"):
                files = arial if case == "brand_fonts_missing" else []
                if not all(f.is_file() for f in files):
                    rows.append({"case": label, "skipped": "Arial not installed here"})
                    continue
                env["WINDIR"] = str(_fonts_dir(tmp, files))
                env["LOCALAPPDATA"] = str(tmp / "no-user-fonts")
            if case == "no_libreoffice":
                env.pop("SOFFICE_PATH", None)
                env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                              if not (Path(p) / "soffice.exe").exists()
                                              and not (Path(p) / "soffice").exists())
            r = subprocess.run([sys.executable, "-X", "utf8", "-m", "proposal.demo", "tender-014",
                                "--replay", "--out", str(out)], cwd=tmp, env=env,
                               capture_output=True, text=True, timeout=600)
            lines = [ln.strip() for ln in (r.stderr + "\n" + r.stdout).splitlines()]
            shown = [ln for ln in lines if ln.startswith(("error:", "PDF skipped", "warning: font",
                                                           "no deck written", "Traceback"))]
            left = sorted(p.name for p in out.iterdir()) if out.exists() else []
            message = " / ".join(shown)
            for form in (str(tmp).replace("\\", "\\\\"), str(tmp)):  # repr() doubles backslashes
                message = message.replace(form, "<tmp>")
            rows.append({"case": label, "exit": r.returncode, "message": message or "(none)",
                         "files_left": left, "traceback": "Traceback" in r.stderr})
    return rows


def markdown(a7_rows: list[dict], a8_rows: list[dict]) -> str:
    out = ["# Output checks A7 and A8", "",
           "Generated by `python -X utf8 proposal/feasibility/output_check.py`. A7 reads the files in",
           "`proposal/showcase/`; A8 runs `python -m proposal.demo tender-014 --replay` on a temporary",
           "copy of the package with one asset broken each time (the real files are not touched).", "",
           "## A7: output validity (the three showcase decks)", "",
           "| Deck | Kind | Slides (.pptx) | PDF exists | PDF pages | CSV rows | Tender requirements | OK |",
           "|---|---|---|---|---|---|---|---|"]
    for r in a7_rows:
        out.append(f"| `{r['deck']}` | {r['kind'].replace('_', '-')} | {r['slides']} | "
                   f"{'yes' if r['pdf'] else 'no'} | {r['pdf_pages']} | {r['csv_rows']} | "
                   f"{r['requirements']} | {'yes' if r['ok'] else '**no**'} |")
    out += ["", "A proposal has 9 slides and a no-bid deck 3; the PDF must have as many pages as the deck",
            "has slides, and the CSV one row per tender requirement (shown on the slide or not).", "",
            "## A8: missing or broken template assets", "",
            "| Case | Message shown | Exit code | Files left in the output folder |",
            "|---|---|---|---|"]
    for r in a8_rows:
        if "skipped" in r:
            out.append(f"| {r['case']} | skipped: {r['skipped']} | | |")
            continue
        files = ", ".join(f"`{f}`" for f in r["files_left"]) or "none"
        message = r["message"].replace("|", "\\|")
        out.append(f"| {r['case']} | {message} | {r['exit']} | {files} |")
    out += ["", "No case leaves a partial file: a deck is rendered and checked in a temporary folder and",
            "moved into the output folder only when complete (`proposal/build.py`). Two cases were",
            "fixed for this check: with no font installed the demo used to stop with a Python",
            "traceback, and with Montserrat and Inter missing it measured text with Arial and said",
            "nothing. Both now behave as above, pinned by `proposal/tests/test_assets.py`."]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else PKG / "feasibility" / "results" / "output_check.md"
    a7_rows, a8_rows = a7(), a8()
    path.write_text(markdown(a7_rows, a8_rows), encoding="utf-8")
    print(path.read_text(encoding="utf-8"))
    bad = [r for r in a7_rows if not r["ok"]] + [r for r in a8_rows if r.get("traceback")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
