"""
src/yahoo_ai_gm/use_cases/get_matchup.py

Layer 4 — Orchestration. No HTTP logic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class MatchupReport:
    generated_at: datetime
    week: int
    projection: dict
    error: Optional[str] = None


def _load_json(path: Path) -> dict | list:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_matchup_report(
    data_dir: Path,
    week: Optional[int] = None,
    n_teams: int = 10,
) -> MatchupReport:
    """
    Requires:
      {data_dir}/snapshots/week_{week}.snapshot.json  — has my roster + matchup info
      {data_dir}/league_rosters.json                  — all team rosters
      {data_dir}/fg_proj_bat_2026.json
      {data_dir}/fg_proj_pit_2026.json
    """
    from yahoo_ai_gm.analysis.matchup_engine import project_matchup, matchup_to_dict

    fg_bat = _load_json(data_dir / "fg_proj_bat_2026.json")
    fg_pit = _load_json(data_dir / "fg_proj_pit_2026.json")
    league_rosters = _load_json(data_dir / "league_rosters.json")

    # Find latest snapshot week if not specified
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

    snap_path = data_dir / f"snapshots/week_{week}.snapshot.json"
    snapshot = _load_json(snap_path)

    # Extract my roster and matchup info from snapshot
    my_roster = snapshot.get("roster", {}).get("players", [])
    matchup_info = snapshot.get("matchup", {})
    my_team_key = matchup_info.get("my_team", {}).get("team_key", "")
    my_team_name = matchup_info.get("my_team", {}).get("team_name", "")
    opp_team_key = matchup_info.get("opp_team", {}).get("team_key", "")
    opp_team_name = matchup_info.get("opp_team", {}).get("team_name", "")

    if not opp_team_key:
        raise ValueError("Opponent team key not found in snapshot matchup data.")

    # Find opponent roster from league_rosters.json
    teams = league_rosters.get("teams", [])
    opp_entry = next((t for t in teams if t["team_key"] == opp_team_key), None)
    if opp_entry is None:
        raise ValueError(f"Opponent {opp_team_key} not found in league_rosters.json. Run pull_league_rosters.py.")

    opp_roster = opp_entry["players"]

    projection = project_matchup(
        my_roster=my_roster,
        opp_roster=opp_roster,
        fg_bat_data=fg_bat,
        fg_pit_data=fg_pit,
        my_team_key=my_team_key,
        my_team_name=my_team_name,
        opp_team_key=opp_team_key,
        opp_team_name=opp_team_name,
        week=week,
        n_teams=n_teams,
    )

    return MatchupReport(
        generated_at=datetime.now(tz=timezone.utc),
        week=week,
        projection=matchup_to_dict(projection),
    )
