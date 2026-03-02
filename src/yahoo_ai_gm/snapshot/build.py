from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from yahoo_ai_gm.domain.models import (
    Snapshot,
    MatchupSnapshot,
    TeamTotals,
    RosterSnapshot,
    PlayerSnapshot,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0
    return 0.0


def build_snapshot_from_files(
    *,
    league_key: str,
    week: int,
    my_team_key: str,
    roster_json_path: Path,
    scoreboard_json_path: Path,
) -> Snapshot:
    roster_raw = _load_json(roster_json_path)
    scoreboard_raw = _load_json(scoreboard_json_path)

    roster = _parse_roster(week=week, roster_raw=roster_raw)
    matchup = _parse_matchup(week=week, my_team_key=my_team_key, scoreboard_raw=scoreboard_raw)

    league_key_final = str(scoreboard_raw.get("league_key") or league_key)

    return Snapshot(
        league_key=league_key_final,
        week=week,
        roster=roster,
        matchup=matchup,
        raw_refs={
            "roster_json": str(roster_json_path),
            "scoreboard_json": str(scoreboard_json_path),
        },
    )


def _parse_roster(*, week: int, roster_raw: Any) -> RosterSnapshot:
    team_key = str(roster_raw.get("team_key"))
    players_raw = roster_raw.get("players", []) or []

    players: list[PlayerSnapshot] = []
    for p in players_raw:
        pos_str = (p.get("pos") or "").strip()
        eligible_positions = [x.strip() for x in pos_str.split(",") if x.strip()]

        players.append(
            PlayerSnapshot(
                player_key=str(p.get("player_key")),
                name=str(p.get("full_name") or ""),
                team_abbr=str(p.get("team") or "") or None,
                eligible_positions=eligible_positions,
                selected_position=eligible_positions[0] if eligible_positions else None,
                status=str(p.get("status") or "") or None,
            )
        )

    return RosterSnapshot(week=week, team_key=team_key, players=players)


def _parse_matchup(*, week: int, my_team_key: str, scoreboard_raw: Any) -> MatchupSnapshot:
    matchup = scoreboard_raw.get("matchup") or {}
    teams = matchup.get("teams") or {}

    if not isinstance(teams, dict) or len(teams) < 2:
        raise ValueError("scoreboard file missing matchup.teams dict with 2 teams")

    if my_team_key not in teams:
        for k, t in teams.items():
            if str(t.get("team_key")) == my_team_key:
                my_team_key = k
                break

    if my_team_key not in teams:
        raise ValueError(f"my_team_key {my_team_key} not found in matchup.teams")

    my_team_raw = teams[my_team_key]
    opp_key = next(k for k in teams.keys() if k != my_team_key)
    opp_team_raw = teams[opp_key]

    def parse_team(team_raw: Dict[str, Any]) -> TeamTotals:
        totals_raw = team_raw.get("totals") or {}
        totals: Dict[str, float] = {}
        for cat, val in totals_raw.items():
            totals[str(cat)] = _to_float(val)

        return TeamTotals(
            team_key=str(team_raw.get("team_key")),
            team_name=str(team_raw.get("name") or ""),
            totals=totals,
        )

    my = parse_team(my_team_raw)
    opp = parse_team(opp_team_raw)

    return MatchupSnapshot(week=week, my_team=my, opp_team=opp)
