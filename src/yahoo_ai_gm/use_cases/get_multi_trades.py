"""
src/yahoo_ai_gm/use_cases/get_multi_trades.py

Layer 4 — Orchestration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class MultiTradeReport:
    generated_at: datetime
    roster_size: int
    trade_sizes: dict
    error: Optional[str] = None


def _load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_multi_trade_report(
    data_dir: Path,
    n_suggestions: int = 10,
    n_teams: int = 10,
) -> MultiTradeReport:
    from yahoo_ai_gm.analysis.multi_trade_engine import (
        multi_trade_suggestions,
        multi_trade_suggestion_to_dict,
    )

    roster_snap = _load_json(data_dir / "snapshots" / "week_1.snapshot.json")
    my_roster = roster_snap.get("roster", {}).get("players", [])

    fg_bat = _load_json(data_dir / "fg_proj_bat_2026.json")
    fg_pit = _load_json(data_dir / "fg_proj_pit_2026.json")
    league_data = _load_json(data_dir / "league_rosters.json")

    # Exclude my own team from receive pool
    my_team_key = roster_snap.get("roster", {}).get("team_key", "")
    other_teams = [t for t in league_data.get("teams", []) if t["team_key"] != my_team_key]

    results = multi_trade_suggestions(
        my_roster=my_roster,
        league_rosters=other_teams,
        fg_bat_data=fg_bat,
        fg_pit_data=fg_pit,
        n_suggestions=n_suggestions,
        n_teams=n_teams,
    )

    return MultiTradeReport(
        generated_at=datetime.now(tz=timezone.utc),
        roster_size=len(my_roster),
        trade_sizes={
            size: [multi_trade_suggestion_to_dict(s) for s in suggestions]
            for size, suggestions in results.items()
        },
    )
