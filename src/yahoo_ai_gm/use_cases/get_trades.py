"""
src/yahoo_ai_gm/use_cases/get_trades.py

Layer 4 — Use Case. Orchestrates snapshot, FG projections, and trade engine.
No HTTP logic here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class TradeReport:
    generated_at: datetime
    roster_size: int
    unmatched_players: list[str]
    weak_categories: list[str]
    strong_categories: list[str]
    suggestions: list[dict]
    fg_projection_date: str
    error: Optional[str] = None


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_trade_report(
    data_dir: Path,
    n_suggestions: int = 10,
    n_teams: int = 12,
    min_receive_adp: float = 300.0,
    max_give_adp: float = 400.0,
) -> TradeReport:
    """
    Orchestrate trade suggestion generation.

    Requires:
      {data_dir}/roster_snapshot.json
      {data_dir}/fg_proj_bat_2026.json
      {data_dir}/fg_proj_pit_2026.json
    """
    from yahoo_ai_gm.analysis.trade_engine import (
        trade_suggestions,
        score_team_categories,
        build_team_projection,
        compute_league_averages,
        load_projections_from_fg,
        build_fg_lookup,
        match_roster_to_fg,
        suggestion_to_dict,
        SCORING_CATS,
    )

    # Load data
    roster = _load_json(data_dir / "roster_snapshot.json")
    fg_bat = _load_json(data_dir / "fg_proj_bat_2026.json")
    fg_pit = _load_json(data_dir / "fg_proj_pit_2026.json")

    fg_date = f"{fg_bat.get('season', 2026)} Steamer"

    # Run engine
    suggestions = trade_suggestions(
        roster=roster,
        fg_bat_data=fg_bat,
        fg_pit_data=fg_pit,
        n_suggestions=n_suggestions,
        n_teams=n_teams,
        min_receive_adp=min_receive_adp,
        max_give_adp=max_give_adp,
    )

    # Compute category summary for the report
    all_projections = load_projections_from_fg(fg_bat, fg_pit)
    fg_lookup = build_fg_lookup(all_projections)
    roster_matches = match_roster_to_fg(roster, fg_lookup)
    my_projections = [p for p in roster_matches.values() if p is not None]
    unmatched = [name for name, proj in roster_matches.items() if proj is None]

    my_team = build_team_projection(my_projections)
    league_averages = compute_league_averages(all_projections, n_teams=n_teams)
    cat_scores = score_team_categories(my_team, league_averages)

    weak_cats = [cs.cat for cs in cat_scores if cs.rank_label == "weakness"]
    strong_cats = [cs.cat for cs in cat_scores if cs.rank_label == "strength"]

    return TradeReport(
        generated_at=datetime.now(tz=timezone.utc),
        roster_size=len(roster),
        unmatched_players=unmatched,
        weak_categories=weak_cats,
        strong_categories=strong_cats,
        suggestions=[suggestion_to_dict(s) for s in suggestions],
        fg_projection_date=fg_date,
    )
