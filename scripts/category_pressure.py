from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple, Optional

# Your league cats + IP minimum helper
CATS = ["R", "HR", "RBI", "SB", "AVG", "W", "K", "SV", "ERA", "WHIP"]
LOWER_IS_BETTER = {"ERA", "WHIP"}
HIGHER_IS_BETTER = {"AVG"}  # plus the counting stats

MIN_IP = 20.0
WEEK_DAYS = 7

DATA_DIR = Path("data")


def to_float(s: str) -> Optional[float]:
    s = (s or "").strip()
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


def get_two_teams(sb: dict) -> Tuple[dict, dict, str]:
    """
    Returns (your_team, opp_team, your_team_key)
    """
    your_team_key = None
    # Stored in payload.matchup.teams dict keyed by team_key. One is (YOU) in print, but JSON has no tag.
    # We can infer "you" by matching Settings team_key later; for now, store your key in env or config if desired.
    # BUT your pull script already knows your team_key and wrote both teams. We’ll use the (YOU) key if present in future.
    # Here: pick the first team as "you" if we can't detect. We'll print both names anyway.

    teams = sb["matchup"]["teams"]
    keys = list(teams.keys())
    if len(keys) != 2:
        raise RuntimeError(f"Expected 2 teams in matchup, found {len(keys)}")

    # Heuristic: if a team key ends with ".t.6" (your team id), treat it as you.
    for k in keys:
        if k.endswith(".t.6"):
            your_team_key = k
            break

    if your_team_key is None:
        your_team_key = keys[0]

    opp_key = keys[1] if keys[0] == your_team_key else keys[0]
    return teams[your_team_key], teams[opp_key], your_team_key


def classify_counting(diff: float, cat: str) -> str:
    """
    diff = you - opp (positive means you're ahead)
    """
    ad = abs(diff)

    # Category-specific "close" thresholds (tweak later)
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
        return "PROTECT" if ad <= safe else "IGNORE"  # too far ahead -> ignore
    else:
        return "PUSH" if ad <= safe else "IGNORE"     # too far behind -> ignore


def classify_ratio(you: float, opp: float, cat: str) -> str:
    """
    For AVG: higher is better.
    For ERA/WHIP: lower is better.
    """
    # "closeness" thresholds
    close = {
        "AVG": 0.010,   # 10 points
        "ERA": 0.40,
        "WHIP": 0.06,
    }[cat]
    safe = close * 3

    if cat in LOWER_IS_BETTER:
        # lower wins
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


def ip_pace(ip_str: str) -> str:
    ip = to_float(ip_str)
    if ip is None:
        return "IP: — (no data yet)"
    # crude day-of-week pace. We'll treat today as day 1..7 of matchup week (local time).
    day = min(max(datetime.now().isoweekday(), 1), 7)  # Mon=1..Sun=7
    expected_by_today = (MIN_IP / WEEK_DAYS) * day
    if ip >= MIN_IP:
        return f"IP: {ip:.1f} (✅ met {MIN_IP:.0f})"
    if ip >= expected_by_today:
        return f"IP: {ip:.1f} (on pace for {MIN_IP:.0f})"
    return f"IP: {ip:.1f} (⚠ behind pace; target ~{expected_by_today:.1f} by today)"


def main():
    # Determine week from latest scoreboard file if not provided
    # simplest: use week 1 for now
    week = 1
    sb = load_scoreboard(week)

    you, opp, you_key = get_two_teams(sb)

    you_name = you["name"]
    opp_name = opp["name"]

    you_totals = you["totals"]
    opp_totals = opp["totals"]

    # Preseason / empty detection
    any_numbers = False
    for cat in CATS:
        if to_float(you_totals.get(cat, "")) is not None or to_float(opp_totals.get(cat, "")) is not None:
            any_numbers = True
            break

    print(f"Week {sb['week']} | status={sb['matchup']['status']}")
    print(f"You: {you_name}")
    print(f"Opp: {opp_name}\n")

    if not any_numbers:
        print("No stat values yet (preseason / preevent).")
        print("Run this again once Week 1 starts and the scoreboard populates.\n")
        # Still show IP pacing placeholder
        print(ip_pace(you_totals.get("IP", "")))
        return

    # Output pressure table
    print("Category pressure (YOU vs OPP):")
    print("-" * 72)

    for cat in CATS:
        y = to_float(you_totals.get(cat, ""))
        o = to_float(opp_totals.get(cat, ""))
        y_disp = you_totals.get(cat, "")
        o_disp = opp_totals.get(cat, "")

        if y is None or o is None:
            label = "—"
        else:
            if cat in ("ERA", "WHIP", "AVG"):
                label = classify_ratio(y, o, cat)
            else:
                label = classify_counting(y - o, cat)

        print(f"{cat:>4} | you={y_disp:>8} | opp={o_disp:>8} | {label}")

    print("-" * 72)
    print(ip_pace(you_totals.get("IP", "")))


if __name__ == "__main__":
    main()
