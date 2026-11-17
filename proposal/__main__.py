"""python -m proposal <data.json> <out.pptx> [--allow-issues] [--font NAME] [--head-font NAME]
[--theme website|sample]

Renders a Proposal (or NoBid) JSON and runs the validator. With validator issues it
exits 1 and writes no deck; a missing font or logo exits 2 and writes nothing; --allow-issues writes it and prints the issues."""

import argparse
import json
import sys

from . import render
from .build import DeckRejected, build
from .measure import FontNotFound
from .schemas import NoBid, Proposal

ap = argparse.ArgumentParser(prog="proposal")
ap.add_argument("data")
ap.add_argument("out")
ap.add_argument("--font", default=render.FONT)
ap.add_argument("--head-font", default=render.HEAD_FONT)
ap.add_argument("--theme", default="website", choices=sorted(render.THEMES))
ap.add_argument("--allow-issues", action="store_true",
                help="write the deck even if the validator reports issues")
a = ap.parse_args()
render.apply_theme(a.theme)
with open(a.data, encoding="utf-8") as f:
    raw = json.load(f)
deck = (NoBid if "recommendation" in raw else Proposal).model_validate(raw)
try:
    built = build(deck, a.out, allow_issues=a.allow_issues, font=a.font, head_font=a.head_font)
except (render.LogoError, FontNotFound) as e:
    print(f"no deck written: {e}", file=sys.stderr)
    sys.exit(2)
except DeckRejected as e:
    print(f"no deck written: {e}", file=sys.stderr)
    for issue in e.issues:
        print(f"  {issue}", file=sys.stderr)
    sys.exit(1)
print(built.path)
for warning in built.warnings:
    print(f"warning: {warning}")
