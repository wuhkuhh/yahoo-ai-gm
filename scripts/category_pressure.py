from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scripts._io import DATA_DIR, read_json, latest_week_file

CATS = ["R", "HR", "RBI", "SB", "AVG", "W", "K", "SV", "ERA", "WHIP", "IP"]
LOWER_IS_BETTER = {"ERA", "WHIP"}
RATIO_CATS = {"AVG", "ERA", "WHIP"}
COUNTING_CATS = {"R", "HR", "RBI", "SB", "W", "K", "SV"}

MIN_IP = 20.0
WEEK_DAYS = 7

# Change this if your team id changes
YOUR_TEAM_SUFFIX = ".t.6"


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
        raise FileNotFoundError(f"Missing {path}. Run pull_scoreboard_week.py first.")
    return read_json(path)


def get_two_teams(sb: dict) -> Tuple[dict, dict, str]:
    teams = sb["matchup"]["teams"]
    keys = list(teams.keys())
    if len(keys) != 2:
        raise RuntimeError(f"Expected 2 teams in matchup, found {len(keys)}")

    your_team_key = next((k for k in keys if k.endswith(YOUR_TEAM_SUFFIX)), keys[0])
    opp_key = keys[1] if keys[0] == your_team_key else keys[0]
    return teams[your_team_key], teams[opp_key], your_team_key


def classify_counting(diff: float, cat: str) -> str:
    ad = abs(diff)
    close = {"R": 6, "RBI": 6, "HR": 2, "SB": 2, "W": 1.5, "K": 10, "SV": 1.5}.get(cat, 5)
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


def ip_pace(ip: float) -> str:
    day = min(max(datetime.now().isoweekday(), 1), 7)
    expected_by_today = (MIN_IP / WEEK_DAYS) * day
    if ip >= MIN_IP:
        return f"IP {ip:.1f} ✅ met {MIN_IP:.0f}"
    if ip >= expected_by_today:
        return f"IP {ip:.1f} ✅ on pace for {MIN_IP:.0f}"
    return f"IP {ip:.1f} ⚠ behind pace (target ~{expected_by_today:.1f} by today)"


def compute_pressure(sb: dict) -> dict:
    you, opp, _ = get_two_teams(sb)

    you_totals = you["totals"]
    opp_totals = opp["totals"]

    rows = []
    buckets: Dict[str, List[str]] = {"PUSH": [], "EVEN": [], "PROTECT": [], "IGNORE": [], "INFO": []}

    any_numbers = False
    for cat in CATS:
        if to_float(you_totals.get(cat, "")) is not None or to_float(opp_totals.get(cat, "")) is not None:
            any_numbers = True
            break

    for cat in CATS:
        y_raw = you_totals.get(cat, "")
        o_raw = opp_totals.get(cat, "")
        y = to_float(y_raw)
        o = to_float(o_raw)

        if y is None or o is None:
            label = "—"
        else:
            if cat in RATIO_CATS:
                label = classify_ratio(y, o, cat)
            elif cat in COUNTING_CATS:
                label = classify_counting(y - o, cat)
            elif cat == "IP":
                label = "INFO"
            else:
                label = "—"

        rows.append({"cat": cat, "you": y_raw, "opp": o_raw, "label": label})
        if label in buckets:
            buckets[label].append(cat)

    return {
        "week": sb.get("week"),
        "status": sb["matchup"]["status"],
        "you_name": you["name"],
        "opp_name": opp["name"],
        "rows": rows,
        "buckets": buckets,
        "has_numbers": any_numbers,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON only")
    args = ap.parse_args()

    week = args.week or latest_week_file("scoreboard_week")
    if not week:
        raise SystemExit("No scoreboard files found. Run pull_scoreboard_week.py first.")

    sb = load_scoreboard(week)
    rpt = compute_pressure(sb)

    if args.json:
        print(json.dumps(rpt, indent=2))
        return

    print(f"Week {rpt['week']} | status={rpt['status']}")
    print(f"You: {rpt['you_name']}")
    print(f"Opp: {rpt['opp_name']}\n")

    if not rpt["has_numbers"]:
        print("No stat values yet (preevent / not started). Run again once the week starts.")
        return

    print("Category pressure (YOU vs OPP):")
    print("-" * 78)
    for r in rpt["rows"]:
        if r["cat"] == "IP" and to_float(r["you"]) is not None:
            print(f"{r['cat']:>4} | you={r['you']:>8} | opp={r['opp']:>8} | {ip_pace(float(r['you']))}")
        else:
            print(f"{r['cat']:>4} | you={r['you']:>8} | opp={r['opp']:>8} | {r['label']}")
    print("-" * 78)

    b = rpt["buckets"]
    def fmt(k: str) -> str:
        return f"{k}: " + (", ".join(b[k]) if b[k] else "—")

    print(fmt("PUSH"))
    print(fmt("EVEN"))
    print(fmt("PROTECT"))
    print(fmt("IGNORE"))


if __name__ == "__main__":
    main()
