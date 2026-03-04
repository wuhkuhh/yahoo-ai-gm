"""
src/yahoo_ai_gm/use_cases/get_ratio_risk.py

Layer 4 — Orchestration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class RatioRiskReport:
    generated_at: datetime
    week: int
    pitcher_count: int
    profiles: list[dict]


def _load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_ratio_risk_report(
    data_dir: Path,
    week: Optional[int] = None,
) -> RatioRiskReport:
    from yahoo_ai_gm.analysis.ratio_risk import roster_ratio_risk, risk_profile_to_dict

    fg_pit = _load_json(data_dir / "fg_proj_pit_2026.json")

    if week is None:
        snapshots_dir = data_dir / "snapshots"
        weeks = []
        for f in snapshots_dir.glob("week_*.snapshot.json"):
            try:
                weeks.append(int(f.name.split("_")[1].split(".")[0]))
            except (IndexError, ValueError):
                continue
        if not weeks:
            raise FileNotFoundError("No snapshot files found.")
        week = max(weeks)

    snap = _load_json(data_dir / f"snapshots/week_{week}.snapshot.json")
    my_roster = snap.get("roster", {}).get("players", [])

    profiles = roster_ratio_risk(my_roster, fg_pit)

    return RatioRiskReport(
        generated_at=datetime.now(tz=timezone.utc),
        week=week,
        pitcher_count=len(profiles),
        profiles=[risk_profile_to_dict(p) for p in profiles],
    )
