"""
src/yahoo_ai_gm/use_cases/get_standings.py

Layer 4 — Orchestration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class StandingsReport:
    generated_at: datetime
    trajectory: dict


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_standings_report(
    data_dir: Path,
    current_week: int = 1,
    n_teams: int = 10,
) -> StandingsReport:
    from yahoo_ai_gm.analysis.standings_trajectory import (
        project_standings,
        standings_trajectory_to_dict,
    )

    fg_bat = _load_json(data_dir / "fg_proj_bat_2026.json")
    fg_pit = _load_json(data_dir / "fg_proj_pit_2026.json")
    league_data = _load_json(data_dir / "league_rosters.json")
    schedule_data = _load_json(data_dir / "league_schedule.json")

    snap_path = data_dir / f"snapshots/week_{current_week}.snapshot.json"
    if not snap_path.exists():
        # Fall back to latest
        weeks = []
        for f in (data_dir / "snapshots").glob("week_*.snapshot.json"):
            try:
                weeks.append(int(f.name.split("_")[1].split(".")[0]))
            except (IndexError, ValueError):
                continue
        current_week = max(weeks) if weeks else 1

    snap = _load_json(data_dir / f"snapshots/week_{current_week}.snapshot.json")
    my_team_key = snap.get("roster", {}).get("team_key", "")

    trajectory = project_standings(
        my_team_key=my_team_key,
        league_rosters=league_data.get("teams", []),
        schedule=schedule_data.get("schedule", {}),
        fg_bat_data=fg_bat,
        fg_pit_data=fg_pit,
        current_week=current_week,
        n_teams=n_teams,
    )

    return StandingsReport(
        generated_at=datetime.now(tz=timezone.utc),
        trajectory=standings_trajectory_to_dict(trajectory),
    )
