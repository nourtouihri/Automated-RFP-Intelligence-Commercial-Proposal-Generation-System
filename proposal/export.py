"""PDF export through LibreOffice headless (decision F1)."""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

WINDOWS_DEFAULT = r"C:\Program Files\LibreOffice\program\soffice.exe"


def soffice_path() -> str:
    """SOFFICE_PATH when set, else soffice on PATH, else the default Windows install."""
    configured = os.environ.get("SOFFICE_PATH")
    if configured:
        if not Path(configured).is_file():
            raise FileNotFoundError(f"SOFFICE_PATH points to a missing file: {configured}")
        return configured
    found = shutil.which("soffice") or (WINDOWS_DEFAULT if Path(WINDOWS_DEFAULT).is_file() else None)
    if found is None:
        raise FileNotFoundError("LibreOffice not found: put soffice on PATH or set SOFFICE_PATH")
    return found


def to_pdf(pptx: str | Path, outdir: str | Path | None = None, timeout: int = 180) -> Path:
    pptx = Path(pptx)
    outdir = Path(outdir) if outdir else pptx.parent
    pdf = outdir / f"{pptx.stem}.pdf"
    pdf.unlink(missing_ok=True)
    # Own profile: headless soffice exits without converting while another
    # LibreOffice instance holds the default one.
    profile = Path(tempfile.gettempdir()) / "proposal-soffice-profile"
    subprocess.run([soffice_path(), f"-env:UserInstallation={profile.as_uri()}", "--headless",
                    "--convert-to", "pdf", "--outdir", str(outdir), str(pptx)],
                   check=True, capture_output=True, timeout=timeout)
    if not pdf.is_file():
        raise RuntimeError(f"LibreOffice exited without writing {pdf}")
    return pdf


def matrix_csv(deck, path: str | Path) -> Path:
    """Every requirement with its fit, score and evidence, shown on the slide or not.
    utf-8 with a BOM, so Excel reads the accents."""
    path = Path(path)
    shown = {r.requirement for r in deck.requirements}
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        out = csv.writer(f)
        out.writerow(["requirement", "fit", "score", "evidence_id", "evidence", "shown"])
        for r in deck.all_requirements or deck.requirements:
            out.writerow([r.requirement, r.fit, f"{r.score:.2f}", r.evidence_id or "", r.evidence,
                          "yes" if r.requirement in shown else "no"])
    return path
