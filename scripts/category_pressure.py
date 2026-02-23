from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Your league cats + IP minimum helper
CATS = ["R", "HR", "RBI", "SB", "AVG", "W", "K", "SV", "ERA", "WHIP"]
LOWER_IS_BETTER = {"ERA", "WHIP"}

MIN_IP = 20.0
WEEK_DAYS = 7

DATA_DIR = Path("data")


def to_float(s: Any) -> Optional[float]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_scoreboard(week: int) -> dict:
    path = DATA_DIR / f"scoreboard_week_{week}.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run: python scripts/pull_scoreboard_week.py")
    return json.loads(path.read_text(encoding="utf-8"))


def walk_find(obj: Any, key: str) -> List[Any]:
    """Find all values for a key anywhere in a nested dict/list structure."""
    out: List[Any] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                out.append(v)
            out.extend(walk_find(v, key))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(walk_find(item, key))
    return out


def first(obj_list: List[Any]) -> Any:
    return obj_list[0] if obj_list else None


@dataclass
class TeamTotals:
    team_key: str
    name: str
    totals: Dict[str, str]  # keep as strings for display


def classify_counting(diff: float, cat: str) -> str:
    """
    diff = you - opp (positive means you're ahead)
    """
    ad = abs(diff)

    close = {
        "R": 6,
        "RBI": 6,
        "HR": 2,
        "SB": 2,
        "W": 1.5,
        "K": 10,
        "SV": 1.5,
    }.get(cat, 5)

    safe = close * 3

    if ad <= close:
        return "EVEN"
    if diff > 0:
        return "PROTECT" if ad <= safe else "IGNORE"
    else:
        return "PUSH" if ad <= safe else "IGNORE"


def classify_ratio(you: float, opp: float, cat: str) -> str:
    close = {"AVG": 0.010, "ERA": 0.40, "WHIP": 0.06}[cat]
    safe = close * 3

    if cat in LOWER_IS_BETTER:
        diff = opp - you  # positive means you are better (lower)
    else:
        diff = you - opp  # positive means you are better (higher)

    ad = abs(diff)
    if ad <= close:
        return "EVEN"
    if diff > 0:
        return "PROTECT" if ad <= safe else "IGNORE"
    else:
        return "PUSH" if ad <= safe else "IGNORE"


def ip_pace(ip_val: Any) -> str:
    ip = to_float(ip_val)
    if ip is None:
        return "IP: — (no data yet)"
    day = min(max(datetime.now().isoweekday(), 1), 7)  # Mon=1..Sun=7
    expected_by_today = (MIN_IP / WEEK_DAYS) * day
    if ip >= MIN_IP:
        return f"IP: {ip:.1f} (✅ met {MIN_IP:.0f})"
    if ip >= expected_by_today:
        return f"IP: {ip:.1f} (on pace for {MIN_IP:.0f})"
    return f"IP: {ip:.1f} (⚠ behind pace; target ~{expected_by_today:.1f} by today)"


def extract_matchup_teams_totals(payload: dict) -> Tuple[dict, TeamTotals, TeamTotals]:
    """
    Supports two formats:
      A) normalized: payload has keys like week/status/matchup/teams with totals
      B) raw Yahoo: deep nested fantasy_content->league->scoreboard->matchups->matchup->teams->team...

    Returns (meta, teamA, teamB) where meta contains week/status if found.
    """
    meta = {
        "week": first(walk_find(payload, "week")),
        "status": first(walk_find(payload, "status")),
    }

    # --- Format A: your simplified shape ---
    if isinstance(payload.get("matchup"), dict) and isinstance(payload["matchup"].get("teams"), dict):
        teams_dict = payload["matchup"]["teams"]
        keys = list(teams_dict.keys())
        if len(keys) == 2:
            t1 = teams_dict[keys[0]]
            t2 = teams_dict[keys[1]]
            team1 = TeamTotals(team_key=keys[0], name=t1.get("name", "Unknown"), totals=t1.get("totals", {}))
            team2 = TeamTotals(team_key=keys[1], name=t2.get("name", "Unknown"), totals=t2.get("totals", {}))
            # week/status override if present in top-level
            if "week" in payload:
                meta["week"] = payload["week"]
            if isinstance(payload.get("matchup"), dict) and "status" in payload["matchup"]:
                meta["status"] = payload["matchup"]["status"]
            return meta, team1, team2

    # --- Format B: raw Yahoo ---
    # Find a "matchup" object that actually contains two teams
    matchups = walk_find(payload, "matchup")
    matchup_obj = None
    for m in matchups:
        if isinstance(m, dict):
            # try to see if it has teams underneath
            teams = first(walk_find(m, "team"))
            if isinstance(teams, list) and len(teams) >= 2:
                matchup_obj = m
                break
    if matchup_obj is None:
        raise RuntimeError("Could not locate a matchup with two teams in this JSON snapshot.")

    # Extract the two team dicts
    team_list = first(walk_find(matchup_obj, "team"))
    if not isinstance(team_list, list) or len(team_list) < 2:
        raise RuntimeError("Matchup found, but couldn't extract two teams.")

    def team_key(team: dict) -> str:
        k = team.get("team_key")
        if isinstance(k, str) and k.strip():
            return k.strip()
        k2 = first(walk_find(team, "team_key"))
        return k2.strip() if isinstance(k2, str) else "unknown"

    def team_name(team: dict) -> str:
        n = team.get("name")
        if isinstance(n, str) and n.strip():
            return n.strip()
        n2 = first(walk_find(team, "name"))
        return n2.strip() if isinstance(n2, str) else "Unknown"

    # Totals are not always present; sometimes you only have "team_stats" with stat_id/value.
    # Your pull_scoreboard_week.py appears to print category lines, so totals likely exist in snapshot.
    def totals_dict(team: dict) -> Dict[str, str]:
        # Try direct totals
        t = team.get("totals")
        if isinstance(t, dict):
            return {k: str(v) for k, v in t.items()}

        # Try matchup->teams->team->team_stats->stats->stat list with stat_id/value
        # We'll map only the categories we care about if we can find "display_name" or pre-mapped names.
        # If not found, return {} and script will show blanks.
        return {}

    t1_raw, t2_raw = team_list[0], team_list[1]
    team1 = TeamTotals(team_key=team_key(t1_raw), name=team_name(t1_raw), totals=totals_dict(t1_raw))
    team2 = TeamTotals(team_key=team_key(t2_raw), name=team_name(t2_raw), totals=totals_dict(t2_raw))

    return meta, team1, team2


def pick_you_vs_opp(team1: TeamTotals, team2: TeamTotals, team_suffix: str) -> Tuple[TeamTotals, TeamTotals]:
    """
    team_suffix: something like ".t.6" so we can identify your team_key.
    Falls back to team1 as 'you' if not found.
    """
    if team1.team_key.endswith(team_suffix):
        return team1, team2
    if team2.team_key.endswith(team_suffix):
        return team2, team1
    return team1, team2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=1)
    ap.add_argument("--team-suffix", type=str, default=".t.6", help="Used to identify your team_key, e.g. .t.6")
    args = ap.parse_args()

    sb = load_scoreboard(args.week)
    meta, t1, t2 = extract_matchup_teams_totals(sb)
    you, opp = pick_you_vs_opp(t1, t2, args.team_suffix)

    week = meta.get("week", args.week)
    status = meta.get("status", "unknown")

    print(f"Week {week} | status={status}")
    print(f"You: {you.name} [{you.team_key}]")
    print(f"Opp: {opp.name} [{opp.team_key}]\n")

    you_totals = you.totals or {}
    opp_totals = opp.totals or {}

    any_numbers = False
    for cat in CATS + ["IP"]:
        if to_float(you_totals.get(cat)) is not None or to_float(opp_totals.get(cat)) is not None:
            any_numbers = True
            break

    if not any_numbers:
        print("No stat values yet (preseason / preevent).")
        print("Run this again once matchups start and the scoreboard populates.\n")
        print(ip_pace(you_totals.get("IP")))
        return

    print("Category pressure (YOU vs OPP):")
    print("-" * 72)

    for cat in CATS:
        y = to_float(you_totals.get(cat))
        o = to_float(opp_totals.get(cat))
        y_disp = str(you_totals.get(cat, ""))
        o_disp = str(opp_totals.get(cat, ""))

        if y is None or o is None:
            label = "—"
        else:
            if cat in ("ERA", "WHIP", "AVG"):
                label = classify_ratio(y, o, cat)
            else:
                label = classify_counting(y - o, cat)

        print(f"{cat:>4} | you={y_disp:>8} | opp={o_disp:>8} | {label}")

    print("-" * 72)
    print(ip_pace(you_totals.get("IP")))


if __name__ == "__main__":
    main()
