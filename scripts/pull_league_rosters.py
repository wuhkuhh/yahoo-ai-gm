"""
scripts/pull_league_rosters.py

Fetch all team rosters in the league and save to data/league_rosters.json.
Used by matchup projection engine.

Usage:
  python3 scripts/pull_league_rosters.py
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from yahoo_ai_gm.yahoo_client import YahooClient

NS = {"y": "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"}
DATA_DIR = Path("data")


def _t(node: ET.Element, path: str, default: str = "") -> str:
    el = node.find(path, NS)
    return el.text.strip() if el is not None and el.text else default


def fetch_team_keys(client: YahooClient, league_key: str) -> list[dict]:
    """Return [{team_key, team_name}, ...] for all teams in league."""
    xml = client.get(f"league/{league_key}/teams")
    root = ET.fromstring(xml)
    teams = []
    for t in root.findall(".//y:team", NS):
        key = _t(t, "y:team_key")
        name = _t(t, "y:name")
        if key:
            teams.append({"team_key": key, "team_name": name})
    return teams


def fetch_roster(client: YahooClient, team_key: str) -> list[dict]:
    """Return normalized player list for a team."""
    xml = client.get(f"team/{team_key}/roster/players")
    root = ET.fromstring(xml)
    players = []
    for p in root.findall(".//y:player", NS):
        player_key = _t(p, "y:player_key")
        full_name = _t(p, "y:name/y:full")
        if not full_name:
            first = _t(p, "y:name/y:first")
            last = _t(p, "y:name/y:last")
            full_name = (first + " " + last).strip()
        players.append({
            "player_key": player_key,
            "full_name": full_name,
            "mlb_team": _t(p, "y:editorial_team_abbr"),
            "display_position": _t(p, "y:display_position"),
            "status": _t(p, "y:status") or "OK",
        })
    return players


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = YahooClient.from_local_config()
    league_key = client.settings.league_key

    print(f"Fetching teams for league {league_key}...")
    teams = fetch_team_keys(client, league_key)
    print(f"  Found {len(teams)} teams")

    league_rosters = []
    for team in teams:
        tkey = team["team_key"]
        tname = team["team_name"]
        print(f"  Fetching roster: {tname} ({tkey})...")
        players = fetch_roster(client, tkey)
        print(f"    {len(players)} players")
        league_rosters.append({
            "team_key": tkey,
            "team_name": tname,
            "players": players,
        })

    out_path = DATA_DIR / "league_rosters.json"
    out_path.write_text(
        json.dumps({"league_key": league_key, "teams": league_rosters}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote -> {out_path}")
    print(f"Total teams: {len(league_rosters)}")


if __name__ == "__main__":
    main()
