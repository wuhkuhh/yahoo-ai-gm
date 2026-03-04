"""
src/yahoo_ai_gm/use_cases/get_trade_acceptance.py

Layer 4 — Orchestration.

Enriches trade suggestions (from get_trades or get_multi_trades)
with acceptance probability scores.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class TradeAcceptanceReport:
    generated_at: datetime
    week: int
    suggestions: list[dict]   # trade suggestions enriched with acceptance_probability


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_trade_acceptance_report(
    data_dir: Path,
    week: Optional[int] = None,
    n_suggestions: int = 10,
    n_teams: int = 10,
) -> TradeAcceptanceReport:
    from yahoo_ai_gm.analysis.trade_acceptance import (
        compute_acceptance_probability,
        acceptance_result_to_dict,
    )
    from yahoo_ai_gm.analysis.trade_engine import (
        load_projections_from_fg,
        build_fg_lookup,
        match_roster_to_fg,
        build_team_projection,
        compute_league_averages,
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
    my_roster = snap.get("roster", {}).get("players", [])
    my_team_key = snap.get("roster", {}).get("team_key", "")

    # Build projections
    all_projections = load_projections_from_fg(fg_bat, fg_pit)
    fg_lookup = build_fg_lookup(all_projections)
    league_averages = compute_league_averages(all_projections, n_teams=n_teams)

    my_matches = match_roster_to_fg(my_roster, fg_lookup)
    my_projs = [p for p in my_matches.values() if p is not None]
    my_team = build_team_projection(my_projs)

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

    # Build opponent team projections
    other_teams = {
        t["team_key"]: t
        for t in league_data.get("teams", [])
        if t["team_key"] != my_team_key
    }
    opp_proj_map = {}
    for tkey, team in other_teams.items():
        matches = match_roster_to_fg(team["players"], fg_lookup)
        projs = [p for p in matches.values() if p is not None]
        opp_proj_map[tkey] = build_team_projection(projs)

    # Get 1-for-1 trade suggestions
    from yahoo_ai_gm.use_cases.get_trades import get_trade_report
    trade_report = get_trade_report(
        data_dir=data_dir,
        n_suggestions=n_suggestions,
        n_teams=n_teams,
    )

    suggestions = []
    for s in trade_report.suggestions:
        give_name    = s.get("give", {}).get("name", "")
        receive_name = s.get("receive", {}).get("name", "")
        give_team_name = s.get("receive", {}).get("team", "")

        # Find opposing team key by name
        opp_entry = next(
            (t for t in league_data.get("teams", [])
             if any(_normalize_name(p.get("full_name","")) == _normalize_name(receive_name)
                    for p in t["players"])),
            None
        )
        if opp_entry is None:
            enriched = dict(s)
            enriched["acceptance"] = {"verdict": "UNKNOWN", "acceptance_probability": None}
            suggestions.append(enriched)
            continue

        opp_key = opp_entry["team_key"]
        opp_name = opp_entry["team_name"]
        opp_rank = rank_map.get(opp_key, 5)
        opp_team = opp_proj_map.get(opp_key)
        if opp_team is None:
            enriched = dict(s)
            enriched["acceptance"] = {"verdict": "UNKNOWN", "acceptance_probability": None}
            suggestions.append(enriched)
            continue

        # Get player projections
        give_proj = fg_lookup.get(_normalize_name(give_name))
        recv_proj  = fg_lookup.get(_normalize_name(receive_name))
        if give_proj is None or recv_proj is None:
            enriched = dict(s)
            enriched["acceptance"] = {"verdict": "UNKNOWN", "acceptance_probability": None}
            suggestions.append(enriched)
            continue

        result = compute_acceptance_probability(
            give_projs=[give_proj],
            receive_projs=[recv_proj],
            my_team=my_team,
            opp_team=opp_team,
            opp_roster=opp_entry["players"],
            opp_team_key=opp_key,
            opp_team_name=opp_name,
            opp_rank=opp_rank,
            league_averages=league_averages,
            n_teams=n_teams,
        )

        enriched = dict(s)
        enriched["acceptance"] = acceptance_result_to_dict(result)
        suggestions.append(enriched)

    # Sort by trade_score * acceptance_probability
    def sort_key(s):
        prob = s.get("acceptance", {}).get("acceptance_probability") or 0.0
        score = s.get("trade_score", 0.0)
        return score * prob

    suggestions.sort(key=sort_key, reverse=True)

    return TradeAcceptanceReport(
        generated_at=datetime.now(tz=timezone.utc),
        week=week,
        suggestions=suggestions,
    )


def _normalize_name(name: str) -> str:
    import unicodedata
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    return name.lower().strip()
