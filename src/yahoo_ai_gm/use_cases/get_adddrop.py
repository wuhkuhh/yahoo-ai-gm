"""
src/yahoo_ai_gm/use_cases/get_adddrop.py

Layer 4 — Orchestration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class AddDropReport:
    generated_at: datetime
    week: int
    max_moves: int
    plan: dict
    error: Optional[str] = None


def _load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_adddrop_report(
    data_dir: Path,
    week: Optional[int] = None,
    max_moves: int = 6,
    n_teams: int = 10,
    pool_file: str = "waiver_pool_baseline_2025_300.json",
) -> AddDropReport:
    from yahoo_ai_gm.analysis.adddrop_engine import simulate_adddrop, adddrop_plan_to_dict

    fg_bat = _load_json(data_dir / "fg_proj_bat_2026.json")
    fg_pit = _load_json(data_dir / "fg_proj_pit_2026.json")
    league_data = _load_json(data_dir / "league_rosters.json")

    # Find latest week
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
    my_team_key = snap.get("roster", {}).get("team_key", "")

    matchup = snap.get("matchup", {})
    opp_team_key = matchup.get("opp_team", {}).get("team_key", "")
    if not opp_team_key:
        raise ValueError("Opponent team key not found in snapshot.")

    opp_entry = next(
        (t for t in league_data.get("teams", []) if t["team_key"] == opp_team_key),
        None
    )
    if opp_entry is None:
        raise ValueError(f"Opponent {opp_team_key} not in league_rosters.json.")

    opp_roster = opp_entry["players"]

    # Load pool
    pool_data = _load_json(data_dir / pool_file)
    pool_players = pool_data.get("players", pool_data if isinstance(pool_data, list) else [])

    plan = simulate_adddrop(
        my_roster=my_roster,
        opp_roster=opp_roster,
        pool_players=pool_players,
        fg_bat_data=fg_bat,
        fg_pit_data=fg_pit,
        max_moves=max_moves,
        n_teams=n_teams,
    )

    return AddDropReport(
        generated_at=datetime.now(tz=timezone.utc),
        week=week,
        max_moves=max_moves,
        plan=adddrop_plan_to_dict(plan),
    )
