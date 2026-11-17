"""Compile vendor/final/tokens.json into vendor/final/tokens.css.

Follows the Final design system's own compile rules (artifact-type format.md):
colours and shadows per theme, everything else on :root, one class per type style.
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "vendor" / "final"


def css_name(name: str) -> str:
    return name.lstrip("-.").replace(".", "\\.")


def value_of(v: str) -> str:
    m = re.fullmatch(r"\{([A-Za-z0-9_.-]+)\}", v)
    return f"var(--{css_name(m.group(1))})" if m else v


def length(v) -> str:
    return f"{v}px" if isinstance(v, (int, float)) else str(v)


def main() -> None:
    t = json.loads((HERE / "tokens.json").read_text(encoding="utf-8"))
    themes = [th["id"] for th in t["color"]["themes"]]
    first = themes[0]
    themed = {th: [] for th in themes}
    for family in ("color", "shadow"):
        for tok in t.get(family, {}).get("tokens", []):
            val = tok["value"]
            per = val if isinstance(val, dict) else {first: val}
            for th in themes:
                if th in per:
                    themed[th].append(f"  --{css_name(tok['name'])}: {value_of(per[th])};")

    out = [f"/* {t['name']} — generated from tokens.json by scripts/build_tokens.py */"]
    out.append(f':root, [data-theme="{first}"] {{\n' + "\n".join(themed[first]) + "\n}")
    for th in themes[1:]:
        out.append(f'[data-theme="{th}"] {{\n' + "\n".join(themed[th]) + "\n}")

    plain = []
    for family, body in t.items():
        if family in ("color", "shadow", "type") or not isinstance(body, dict) or "tokens" not in body:
            continue
        for tok in body["tokens"]:
            plain.append(f"  --{css_name(tok['name'])}: {tok['value']};")
    for key, stack in t["type"]["families"].items():
        plain.append(f"  --font-{key}: {stack};")
    out.append(":root {\n" + "\n".join(plain) + "\n}")

    for group in t["type"]["groups"]:
        for s in group["styles"]:
            family = s.get("family", group["family"])
            rules = [
                f"font-family: var(--font-{family});",
                f"font-size: {length(s['fontSize'])};",
                f"line-height: {s['lineHeight']};",
                f"font-weight: {s['fontWeight']};",
            ]
            if s.get("letterSpacing") is not None:
                rules.append(f"letter-spacing: {s['letterSpacing']};")
            out.append(f".{css_name(s['name'])} {{ " + " ".join(rules) + " }")

    (HERE / "tokens.css").write_text("\n\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
