#!/usr/bin/env python3
"""
Roster Inspector
- Loads a saved roster JSON (defaults to latest week file)
- Prints quick roster shape + position counts + MLB team counts
- Lists injuries/IL/DTD when available

Run:
  python -m scripts.roster_inspector --week 1
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any, Dict, List

from scripts._io import DATA_DIR, read_json, latest_week_file, find_roster_file


def _ensure_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    raise TypeError(f"Expected dict, got {type(obj).__name__}")


def _coerce_players(roster: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Roster JSONs can come in a few shapes depending on how they were pulled.
    Normalize to: List[Dict] where each dict is the player payload.
    """
    candidates = (
        roster.get("players")
        or roster.get("roster", {}).get("players")
        or roster.get("team", {}).get("roster", {}).get("players")
        or []
    )

    players: List[Dict[str, Any]] = []
    for item in candidates:
        if isinstance(item, dict) and "player" in item and isinstance(item["player"], dict):
            players.append(item["player"])
        elif isinstance(item, dict):
            players.append(item)
        else:
            # ignore non-dicts quietly
            continue
    return players


def _player_name(p: Dict[str, Any]) -> str:
    return (
        p.get("full_name")
        or p.get("name")
        or (p.get("name", {}) or {}).get("full")
        or p.get("player_name")
        or p.get("player_key", "UNKNOWN")
    )


def _player_team(p: Dict[str, Any]) -> str:
    # your simplified roster.json uses "team": "MIA"
    team = p.get("team")
    if isinstance(team, str) and team.strip():
        return team.strip()

    # yahoo raw can have editorial_team_abbr etc.
    team = p.get("editorial_team_abbr") or p.get("team_abbr")
    if isinstance(team, str) and team.strip():
        return team.strip()

    # sometimes nested
    team = (p.get("editorial_team") or {}).get("abbr")
    if isinstance(team, str) and team.strip():
        return team.strip()

    return "—"


def _player_pos(p: Dict[str, Any]) -> str:
    # your simplified roster.json uses "pos": "1B"
    pos = p.get("pos")
    if isinstance(pos, str) and pos.strip():
        return pos.strip()

    # yahoo raw may store as selected_position / display_position
    pos = p.get("selected_position") or p.get("display_position")
    if isinstance(pos, str) and pos.strip():
        return pos.strip()

    # sometimes nested "selected_position": {"position": "1B"}
    sp = p.get("selected_position")
    if isinstance(sp, dict):
        v = sp.get("position")
        if isinstance(v, str) and v.strip():
            return v.strip()

    return "—"


def _player_status(p: Dict[str, Any]) -> str:
    # your simplified roster.json uses "status": "OK"
    status = p.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()

    # yahoo raw
    status = p.get("injury_status") or p.get("status_full")
    if isinstance(status, str) and status.strip():
        return status.strip()

    return "OK"


def _is_flagged(status: str) -> bool:
    s = status.upper()
    return s in {"IL", "DTD", "NA", "O", "IR"} or ("IL" in s) or ("DTD" in s)


def _print_counter(title: str, counter: Counter) -> None:
    print(f"\n{title}:")
    if not counter:
        print("  (none)")
        return
    for k, v in counter.most_common():
        print(f"  - {k}: {v}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None, help="Week number (used to locate week file)")
    ap.add_argument(
        "--file",
        type=str,
        default=None,
        help="Explicit roster json path (overrides --week)",
    )
    args = ap.parse_args()

    # Determine roster file to read
    roster_path = None
    if args.file:
        roster_path = args.file
    elif args.week is not None:
        roster_path = find_roster_file(args.week)
        if roster_path is None:
            # fall back to latest file in data/ if week not present
            roster_path = latest_week_file("roster")
    else:
        roster_path = latest_week_file("roster")

    if roster_path is None:
        raise SystemExit(
            f"No roster files found. Expected something like {DATA_DIR}/roster_week_*.json"
        )

    roster = _ensure_dict(read_json(roster_path))
    players = _coerce_players(roster)

    team_key = roster.get("team_key") or roster.get("team", {}).get("team_key") or "UNKNOWN"
    print("\nYAHOO AI GM — ROSTER INSPECTOR")
    print("=" * 80)
    print(f"File: {roster_path}")
    print(f"Team key: {team_key}")
    print(f"Players: {len(players)}")

    pos_counts = Counter()
    mlb_counts = Counter()
    flagged: List[Dict[str, Any]] = []

    for p in players:
        name = _player_name(p)
        pos = _player_pos(p)
        tm = _player_team(p)
        status = _player_status(p)

        if pos != "—":
            pos_counts[pos] += 1
        if tm != "—":
            mlb_counts[tm] += 1
        if _is_flagged(status):
            flagged.append(
                {
                    "name": name,
                    "pos": pos,
                    "team": tm,
                    "status": status,
                }
            )

    _print_counter("Roster shape", Counter({"hitters-ish": sum(pos_counts.values())}))
    _print_counter("Positions", pos_counts)
    _print_counter("MLB teams", mlb_counts)

    print("\nStatus / injuries:")
    if not flagged:
        print("  - none")
    else:
        for f in flagged:
            print(f"  - {f['name']} ({f['team']} {f['pos']}): {f['status']}")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
