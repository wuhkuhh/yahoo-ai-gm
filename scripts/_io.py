from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

DATA_DIR = Path("data")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_week_file(prefix: str) -> Optional[int]:
    if not DATA_DIR.exists():
        return None
    weeks = []
    pat = re.compile(rf"{re.escape(prefix)}_(\d+)\.json$")
    for p in DATA_DIR.glob(f"{prefix}_*.json"):
        m = pat.search(p.name)
        if m:
            weeks.append(int(m.group(1)))
    return max(weeks) if weeks else None


def find_roster_file(week: Optional[int]) -> Optional[Path]:
    """
    Tries common roster filenames.
    """
    candidates = []
    if week is not None:
        candidates += [
            DATA_DIR / f"roster_week_{week}.json",
            DATA_DIR / f"team_roster_week_{week}.json",
        ]
    candidates += [
        DATA_DIR / "roster.json",
        DATA_DIR / "team_roster.json",
        DATA_DIR / "roster_latest.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None
