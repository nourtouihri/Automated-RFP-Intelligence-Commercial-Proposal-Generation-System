"""Render a deck, check it, and write it only if the checks pass.

A missing font or logo stops it before anything is written. The validator (F4)
gates every deck: with issues, no final file is written and
DeckRejected carries them, unless allow_issues is set, in which case the deck is
written and each issue is added to the bid warnings.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import render
from .compose import Trace, bid_warnings
from .config import DEFAULT, Config
from .export import matrix_csv
from .measure import font_gaps
from .schemas import NoBid, Proposal
from .validate import Issue, validate


class DeckRejected(RuntimeError):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__(f"{len(issues)} validator issue(s): " + "; ".join(map(str, issues[:3]))
                         + (" ..." if len(issues) > 3 else ""))


@dataclass
class Built:
    path: Path
    csv: Path
    issues: list[Issue]
    warnings: list[str]


def build(deck: Proposal | NoBid, path: str | Path, *, retrieved: set[str] | None = None,
          allow_issues: bool = False, trace: Trace | None = None, config: Config = DEFAULT,
          font: str = render.FONT, head_font: str = render.HEAD_FONT) -> Built:
    """retrieved is the set of record ids the retrieval returned, for the citation check."""
    path = Path(path)
    # Both raise before anything is written: no font at all, or a missing or broken logo.
    fonts = [f"font not installed: {g}; the PDF may use a substitute"
             for g in font_gaps((font, head_font))]
    render.check_logos(config)
    draw = render.render_no_bid if isinstance(deck, NoBid) else render.render
    with tempfile.TemporaryDirectory() as tmp:
        draft = Path(tmp) / path.name
        draw(deck, str(draft), font, head_font, config)
        issues = validate(str(draft), None if isinstance(deck, NoBid) else deck, retrieved)
        if issues and not allow_issues:
            raise DeckRejected(issues)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(draft), path)
    csv_path = matrix_csv(deck, path.with_name(path.stem + ".matrix.csv"))
    return Built(path, csv_path, issues,
                 bid_warnings(deck, trace) + fonts + [f"validator: {i}" for i in issues])
