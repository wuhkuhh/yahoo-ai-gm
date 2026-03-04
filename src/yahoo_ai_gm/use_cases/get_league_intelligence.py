"""
src/yahoo_ai_gm/use_cases/get_league_intelligence.py

Layer 4 — Orchestration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class LeagueIntelligenceReport:
    generated_at: datetime
    week: int
    construction_scores: list[dict]
    my_construction: dict
    opponent_profiles: list[dict]


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_league_intelligence_report(
    data_dir: Path,
    week: Optional[int] = None,
    n_teams: int = 10,
) -> LeagueIntelligenceReport:
    from yahoo_ai_gm.analysis.league_intelligence import (
        compute_league_intelligence,
        construction_score_to_dict,
        opponent_profile_to_dict,
    )
    from yahoo_ai_gm.analysis.standings_trajectory import project_standings

    fg_bat = _load_json(data_dir / "fg_proj_bat_2026.json")
    fg_pit = _load_json(data_dir / "fg_proj_pit_2026.json")
    league_data = _load_json(data_dir / "league_rosters.json")
    schedule_data = _load_json(data_dir / "league_schedule.json")

    if week is None:
        weeks = []
        for f in (data_dir / "snapshots").glob("week_*.snapshot.json"):
            try:
                weeks.append(int(f.name.split("_")[1].split(".")[0]))
            except (IndexError, ValueError):
                continue
        week = max(weeks) if weeks else 1

    snap = _load_json(data_dir / f"snapshots/week_{week}.snapshot.json")
    my_team_key = snap.get("roster", {}).get("team_key", "")

    # Get standings for rank info
    trajectory = project_standings(
        my_team_key=my_team_key,
        league_rosters=league_data.get("teams", []),
        schedule=schedule_data.get("schedule", {}),
        fg_bat_data=fg_bat,
        fg_pit_data=fg_pit,
        current_week=week,
        n_teams=n_teams,
    )
    rank_map = {s.team_key: s.projected_rank for s in trajectory.all_standings}

    construction_scores, opponent_profiles = compute_league_intelligence(
        my_team_key=my_team_key,
        league_rosters=league_data.get("teams", []),
        fg_bat_data=fg_bat,
        fg_pit_data=fg_pit,
        rank_map=rank_map,
        n_teams=n_teams,
    )

    cs_dicts = [construction_score_to_dict(cs) for cs in construction_scores]
    # Match by team_key since team_name may be None in snapshot
    my_team_name = next(
        (t["team_name"] for t in league_data.get("teams", []) if t["team_key"] == my_team_key),
        None
    )
    my_cs = next((d for d in cs_dicts if d["team"] == my_team_name), cs_dicts[0] if cs_dicts else {})
    op_dicts = [opponent_profile_to_dict(p) for p in opponent_profiles]

    return LeagueIntelligenceReport(
        generated_at=datetime.now(tz=timezone.utc),
        week=week,
        construction_scores=cs_dicts,
        my_construction=my_cs,
        opponent_profiles=op_dicts,
    )
