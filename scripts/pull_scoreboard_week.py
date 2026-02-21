from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple
import xml.etree.ElementTree as ET

from yahoo_ai_gm.yahoo_client import YahooClient

NS = {"y": "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"}

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# League stat ids (confirmed)
CATS = {
    "AVG": "3",
    "R": "7",
    "HR": "12",
    "RBI": "13",
    "SB": "16",
    "ERA": "26",
    "WHIP": "27",
    "W": "28",
    "SV": "32",
    "K": "42",
    "IP": "50",  # extra: needed for weekly min pace
}


def t(node: ET.Element, path: str, default: str = "") -> str:
    el = node.find(path, NS)
    return el.text.strip() if el is not None and el.text else default


def find_current_week_from_scoreboard(root: ET.Element) -> Optional[int]:
    """
    Yahoo scoreboard responses typically include one or more matchups with a <week>.
    We’ll take the first matchup week if present.
    """
    m = root.find(".//y:matchup", NS)
    if m is None:
        return None
    wk = t(m, "y:week")
    return int(wk) if wk.isdigit() else None


def parse_team_totals(team_node: ET.Element) -> Dict[str, str]:
    """
    Returns { cat_name: value_str } for our cats.
    Scoreboard uses stats with stat_id and value under team/team_stats/stats/stat
    """
    out: Dict[str, str] = {}

    # Build map stat_id -> value
    sid_to_val: Dict[str, str] = {}
    for s in team_node.findall(".//y:team_stats/y:stats/y:stat", NS):
        sid = t(s, "y:stat_id")
        val = t(s, "y:value")
        if sid:
            sid_to_val[sid] = val

    # Translate to category names
    for cat_name, sid in CATS.items():
        out[cat_name] = sid_to_val.get(sid, "")

    return out


@dataclass
class ScoreboardTeam:
    team_key: str
    name: str
    totals: Dict[str, str]


@dataclass
class ScoreboardMatchup:
    week: int
    status: str
    teams: Dict[str, ScoreboardTeam]  # team_key -> ScoreboardTeam


@dataclass
class ScoreboardWeek:
    league_key: str
    pulled_at: str
    week: int
    matchup: ScoreboardMatchup


def main():
    client = YahooClient.from_local_config()
    league_key = client.settings.league_key
    team_key = client.settings.team_key

    # 1) Pull league scoreboard (best source for matchup totals by stat)
    # We intentionally start without specifying week. If season is live, it usually returns current week.
    xml = client.get(f"league/{league_key}/scoreboard")
    root = ET.fromstring(xml)

    # 2) Determine current week
    week = find_current_week_from_scoreboard(root)
    if week is None:
        print("No matchup/week found in scoreboard response.")
        print("This usually means the season hasn't started, or scoreboard isn't available yet.")
        return

    # 3) Identify the matchup that includes YOUR team
    matchups = root.findall(".//y:matchup", NS)
    target_matchup = None
    for m in matchups:
        teams = m.findall(".//y:teams/y:team", NS)
        team_keys = [t(x, "y:team_key") for x in teams]
        if team_key in team_keys:
            target_matchup = m
            break

    if target_matchup is None:
        # If we're preseason, scoreboard can return a generic matchup without your team.
        # Or if league uses different timing.
        status_guess = t(matchups[0], "y:status") if matchups else ""
        if status_guess == "preevent":
            print(f"Scoreboard is preseason (status=preevent). Week {week} not active yet.")
            return
        print("Could not find your team in the returned scoreboard matchups.")
        print("We can try specifying a week explicitly once you know it is active.")
        return

    status = t(target_matchup, "y:status") or "unknown"
    wk_str = t(target_matchup, "y:week")
    wk = int(wk_str) if wk_str.isdigit() else week

    teams_out: Dict[str, ScoreboardTeam] = {}
    for team in target_matchup.findall(".//y:teams/y:team", NS):
        tk = t(team, "y:team_key")
        name = t(team, "y:name")
        totals = parse_team_totals(team)
        teams_out[tk] = ScoreboardTeam(team_key=tk, name=name, totals=totals)

    matchup = ScoreboardMatchup(week=wk, status=status, teams=teams_out)

    payload = ScoreboardWeek(
        league_key=league_key,
        pulled_at=datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        week=wk,
        matchup=matchup,
    )

    out_path = DATA_DIR / f"scoreboard_week_{wk}.json"
    out_path.write_text(json.dumps(asdict(payload), indent=2, sort_keys=True), encoding="utf-8")

    # Print a friendly summary
    print(f"League: {league_key}")
    print(f"Week: {wk} | status={status}")
    print(f"Saved -> {out_path}\n")

    # Pretty display
    for tk, team in teams_out.items():
        tag = " (YOU)" if tk == team_key else ""
        print(f"== {team.name}{tag} ==")
        for cat in ["R", "HR", "RBI", "SB", "AVG", "W", "K", "SV", "ERA", "WHIP", "IP"]:
            print(f"{cat:>4}: {team.totals.get(cat, '')}")
        print("")

if __name__ == "__main__":
    main()
