import json
import re
from pathlib import Path
from typing import Optional

CONTENT_LIMIT = 300
START_TOOL = "research_run_start"

# Params is JSON that may itself contain " | " (logged search queries), so the
# line is anchored on the fixed shape: params end at the 64-hex hash field.
_LINE = re.compile(
    r"^(\S+) \| INFO \| (.*?) \| (\{.*?\}) \| ([0-9a-f]{64}) \| (.*)$"
)


def _parse(line: str) -> Optional[dict]:
    match = _LINE.match(line.rstrip("\r\n"))
    if match is None:
        return None
    timestamp, tool, raw_params, digest, content = match.groups()
    try:
        params = json.loads(raw_params)
    except ValueError:
        return None
    if not isinstance(params, dict):
        return None
    return {
        "timestamp": timestamp,
        "tool": tool,
        "params": params,
        "hash": digest,
        "content": content[:CONTENT_LIMIT],
    }


def _log_files(log_path: Path) -> list[Path]:
    rotated = sorted(log_path.parent.glob(f"{log_path.name}.*"), reverse=True)
    return [p for p in [log_path, *rotated] if p.is_file()]


def _lines(path: Path):
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line
    except OSError:
        return


def _last_start(path: Path, tender_id: str) -> Optional[tuple[int, str]]:
    """Line number and run_id of the file's newest start for the tender, parsing only start lines."""
    found = None
    for number, line in enumerate(_lines(path)):
        if f" | {START_TOOL} | " not in line:
            continue
        entry = _parse(line)
        if entry and entry["tool"] == START_TOOL and entry["params"].get("tender_id") == tender_id:
            found = (number, entry["params"].get("run_id"))
    return found


def _run_entries(path: Path, run_id: str, first_line: int) -> list[dict]:
    needle = json.dumps(run_id)
    entries = []
    for number, line in enumerate(_lines(path)):
        if number < first_line or needle not in line:
            continue
        entry = _parse(line)
        if entry and entry["params"].get("run_id") == run_id:
            entries.append(entry)
    return entries


def read_run(log_path: Path, tender_id: str, limit: int = 200) -> list[dict]:
    """Entries of the newest research run for the tender, oldest first."""
    files = _log_files(Path(log_path))
    for index, path in enumerate(files):
        found = _last_start(path, tender_id)
        if found is None:
            continue
        first_line, run_id = found
        entries = _run_entries(path, run_id, first_line)
        for newer in reversed(files[:index]):
            entries += _run_entries(newer, run_id, 0)
        return entries[:limit]
    return []
