"""
src/yahoo_ai_gm/use_cases/get_streaming_sp.py

Layer 4 — Orchestration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class StreamingSpReport:
    generated_at: datetime
    week: int
    week_start: str
    week_end: str
    data_source: str
    opp_weaknesses: list[str]
    candidates: list[dict]


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_streaming_sp_report(
    data_dir: Path,
    week: Optional[int] = None,
    max_owned_pct: float = 60.0,
    top_n: int = 10,
) -> StreamingSpReport:
    from yahoo_ai_gm.analysis.streaming_sp import (
        rank_streaming_candidates,
        streaming_candidate_to_dict,
    )

    fg_pit = _load_json(data_dir / "fg_proj_pit_2026.json")
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

    # Get week dates from schedule
    week_matchups = schedule_data.get("schedule", {}).get(str(week), [])
    week_start = "2026-03-25"
    week_end   = "2026-03-29"
    if week_matchups:
        # Pull from scoreboard if available
        scoreboard = snap.get("scoreboard", {})
        week_start = scoreboard.get("week_start", week_start)
        week_end   = scoreboard.get("week_end",   week_end)

    # Get opponent weaknesses for this week
    opp_weaknesses: list[str] = []
    try:
        from yahoo_ai_gm.use_cases.get_league_intelligence import get_league_intelligence_report
        from yahoo_ai_gm.analysis.standings_trajectory import project_standings
        league_data = _load_json(data_dir / "league_rosters.json")
        fg_bat = _load_json(data_dir / "fg_proj_bat_2026.json")
        trajectory = project_standings(
            my_team_key=my_team_key,
            league_rosters=league_data.get("teams", []),
            schedule=schedule_data.get("schedule", {}),
            fg_bat_data=fg_bat,
            fg_pit_data=fg_pit,
            current_week=week,
        )
        # Find this week's opponent
        my_week = next(
            (w for w in trajectory.remaining_schedule if w.week == week), None
        )
        if my_week:
            from yahoo_ai_gm.use_cases.get_league_intelligence import get_league_intelligence_report
            li = get_league_intelligence_report(data_dir=data_dir, week=week)
            opp_profile = next(
                (o for o in li.opponent_profiles
                 if o.get("team") and my_week.opp_team_name and
                 o["team"] == my_week.opp_team_name),
                None
            )
            if opp_profile:
                opp_weaknesses = opp_profile.get("consistent_weaknesses", [])
    except Exception:
        pass

    # Load waiver pool
    pool_path = data_dir / "waiver_pool_baseline_2025_300.json"
    raw = _load_json(pool_path)
    pool_players = raw.get("players", raw if isinstance(raw, list) else [])

    candidates = rank_streaming_candidates(
        pool_players=pool_players,
        fg_pit_data=fg_pit,
        opp_weaknesses=opp_weaknesses,
        week_start=week_start,
        week_end=week_end,
        max_owned_pct=max_owned_pct,
        top_n=top_n,
    )

    source = candidates[0].source if candidates else "fg_projection"

    return StreamingSpReport(
        generated_at=datetime.now(tz=timezone.utc),
        week=week,
        week_start=week_start,
        week_end=week_end,
        data_source=source,
        opp_weaknesses=opp_weaknesses,
        candidates=[streaming_candidate_to_dict(c) for c in candidates],
    )
