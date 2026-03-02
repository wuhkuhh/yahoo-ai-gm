from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

from yahoo_ai_gm.yahoo_client import YahooClient

DATA_DIR = Path("data")

NS = {
    "y": "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"
}

def _maybe_json(s: str) -> Optional[dict]:
    s2 = s.strip()
    if not s2:
        return None
    if s2.startswith("{") or s2.startswith("["):
        try:
            return json.loads(s2)
        except Exception:
            return None
    return None

def _parse_roster_xml(xml_text: str) -> List[Dict[str, str]]:
    """
    Parse Yahoo fantasy XML and return a normalized list of players.
    We avoid fancy dependencies and just pull the common fields.
    """
    root = ET.fromstring(xml_text)

    players_out: List[Dict[str, str]] = []

    # Every player is under <player> ... </player> in Yahoo's namespace
    for p in root.findall(".//y:player", NS):
        player_key = (p.findtext("y:player_key", default="", namespaces=NS) or "").strip()
        status = (p.findtext("y:status", default="OK", namespaces=NS) or "OK").strip()

        # name/full can be missing in some payloads; fall back to name/first+last
        full = (p.findtext("y:name/y:full", default="", namespaces=NS) or "").strip()
        if not full:
            first = (p.findtext("y:name/y:first", default="", namespaces=NS) or "").strip()
            last = (p.findtext("y:name/y:last", default="", namespaces=NS) or "").strip()
            full = (first + " " + last).strip()

        team = (p.findtext("y:editorial_team_abbr", default="", namespaces=NS) or "").strip()
        pos = (p.findtext("y:display_position", default="", namespaces=NS) or "").strip()

        players_out.append(
            {
                "player_key": player_key,
                "full_name": full,
                "team": team,
                "pos": pos,
                "status": status,
            }
        )

    return players_out

def _call_roster(client: YahooClient, team_key: str) -> Any:
    # This is the Yahoo fantasy endpoint for team roster (players currently on roster)
    path = f"/team/{team_key}/roster/players"
    return client.get(path)

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    client = YahooClient.from_local_config()
    team_key = client.settings.team_key  # already a string

    raw = _call_roster(client, team_key=team_key)

    # Normalize raw -> players list
    players: List[Dict[str, str]] = []

    if isinstance(raw, dict):
        # If in the future client.get returns dict
        players = raw.get("players") or raw.get("roster", {}).get("players") or []
    elif isinstance(raw, str):
        # Try JSON first, then XML
        as_json = _maybe_json(raw)
        if as_json is not None:
            players = as_json.get("players") or as_json.get("roster", {}).get("players") or []
        else:
            players = _parse_roster_xml(raw)
    else:
        raise TypeError(f"Unexpected roster payload type: {type(raw)}")

    # Save a normalized JSON report
    out_path = DATA_DIR / "roster.json"
    out = {"team_key": team_key, "count": len(players), "players": players}
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"Found {len(players)} players on roster")
    print(f"Saved -> {out_path}")

    for p in players:
        name = p.get("full_name") or p.get("name") or "?"
        team = p.get("team") or "?"
        pos = p.get("pos") or p.get("position") or "?"
        status = p.get("status") or "OK"
        pkey = p.get("player_key") or p.get("key") or ""
        print(f"- {name} ({team}) | {pos} | status={status} | {pkey}")

if __name__ == "__main__":
    main()
