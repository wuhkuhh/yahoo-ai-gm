from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from yahoo_ai_gm.yahoo_client import YahooClient

NS = {"y": "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"}

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

STAT_MAP_PATH = DATA_DIR / "stat_map.json"

# Your league’s key categories (from data/stat_map.json)
HITTER_CATS = {"R": "7", "HR": "12", "RBI": "13", "SB": "16", "AVG": "3"}
PITCHER_CATS = {"W": "28", "K": "42", "ERA": "26", "WHIP": "27", "SV": "32"}
EXTRAS = {"IP": "50"}  # useful for your weekly minimum



def t(node: ET.Element, path: str, default: str = "") -> str:
    el = node.find(path, NS)
    return el.text.strip() if el is not None and el.text else default


def parse_player_stats_map(root: ET.Element) -> Dict[str, Dict[str, str]]:
    """
    Returns:
      { player_key: { stat_id: value, ... }, ... }
    """
    out: Dict[str, Dict[str, str]] = {}
    for p in root.findall(".//y:player", NS):
        pkey = t(p, "y:player_key")
        if not pkey:
            continue
        stats: Dict[str, str] = {}
        for s in p.findall(".//y:stats/y:stat", NS):
            stat_id = t(s, "y:stat_id")
            value = t(s, "y:value")
            if stat_id:
                stats[stat_id] = value
        out[pkey] = stats
    return out


@dataclass
class PlayerSnapshot:
    player_key: str
    full_name: str
    mlb_team: str
    display_position: str
    eligible_positions: str
    status: str

    # stats maps by type
    lastseason_stats: Dict[str, str]
    season_stats: Dict[str, str]


def chunked(xs: List[str], n: int) -> List[List[str]]:
    return [xs[i:i+n] for i in range(0, len(xs), n)]


def fetch_players_xml(client: YahooClient, player_keys: List[str]) -> ET.Element:
    # players;player_keys=... returns player metadata
    path = "players;player_keys=" + ",".join(player_keys)
    xml = client.get(path)
    return ET.fromstring(xml)


def fetch_stats_xml(client: YahooClient, player_keys: List[str], stats_type: str, season: Optional[str] = None) -> ET.Element:
    # players;player_keys=.../stats;type=...
    # Common: type=lastseason OR type=season;season=YYYY
    base = "players;player_keys=" + ",".join(player_keys) + f"/stats;type={stats_type}"
    if season:
        base += f";season={season}"
    xml = client.get(base)
    return ET.fromstring(xml)


def main():
    client = YahooClient.from_local_config()
    team_key = client.settings.team_key

    # 1) Pull roster -> get player keys
    roster_xml = client.get(f"team/{team_key}/roster")
    roster_root = ET.fromstring(roster_xml)
    roster_players = roster_root.findall(".//y:player", NS)

    roster_player_keys = [t(p, "y:player_key") for p in roster_players if t(p, "y:player_key")]
    if not roster_player_keys:
        raise SystemExit("No player_keys found on roster response.")

    # 2) Batch fetch player metadata and stats
    snapshots: List[PlayerSnapshot] = []

    # Yahoo can be finicky with very long URLs. 25–50 keys per call is usually safe.
    for keys in chunked(roster_player_keys, 25):
        players_root = fetch_players_xml(client, keys)

        # Try lastseason stats (should exist even preseason)
        try:
            lastseason_root = fetch_stats_xml(client, keys, "lastseason")
            lastseason_map = parse_player_stats_map(lastseason_root)
        except Exception:
            lastseason_map = {}

        # Try current season stats (may be empty preseason)
        # We'll use the game_key-derived season if you ever want it; for now, just call type=season without year.
        try:
            season_root = fetch_stats_xml(client, keys, "season")
            season_map = parse_player_stats_map(season_root)
        except Exception:
            season_map = {}

        # Build snapshot from metadata
        for p in players_root.findall(".//y:player", NS):
            pkey = t(p, "y:player_key")
            if not pkey:
                continue

            full_name = t(p, "y:name/y:full")
            mlb_team = t(p, "y:editorial_team_abbr")
            display_pos = t(p, "y:display_position")
            status = t(p, "y:status") or "OK"

            elig_positions = []
            for pos in p.findall(".//y:eligible_positions/y:position", NS):
                if pos.text:
                    elig_positions.append(pos.text.strip())
            eligible_positions = ",".join(elig_positions)

            snapshots.append(
                PlayerSnapshot(
                    player_key=pkey,
                    full_name=full_name,
                    mlb_team=mlb_team,
                    display_position=display_pos,
                    eligible_positions=eligible_positions,
                    status=status,
                    lastseason_stats=lastseason_map.get(pkey, {}),
                    season_stats=season_map.get(pkey, {}),
                )
            )

    # 3) Save JSON (full fidelity)
    json_path = DATA_DIR / "roster_snapshot.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in snapshots], f, indent=2, sort_keys=True)

        # 4) Save CSV (flattened + labeled columns)
    csv_path = DATA_DIR / "roster_snapshot.csv"

    hitter_cols = list(HITTER_CATS.keys())
    pitcher_cols = list(PITCHER_CATS.keys())
    extra_cols = list(EXTRAS.keys())

    fieldnames = [
        "player_key",
        "full_name",
        "mlb_team",
        "display_position",
        "eligible_positions",
        "status",
        "type_guess",
        *[f"lastseason_{c}" for c in (hitter_cols + pitcher_cols + extra_cols)],
        *[f"season_{c}" for c in (hitter_cols + pitcher_cols + extra_cols)],
    ]

    def guess_type(display_position: str) -> str:
        # crude but works well enough for organizing CSV
        if "SP" in display_position or "RP" in display_position or "P" == display_position:
            return "P"
        return "B"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()

        for s in snapshots:
            row = {
                "player_key": s.player_key,
                "full_name": s.full_name,
                "mlb_team": s.mlb_team,
                "display_position": s.display_position,
                "eligible_positions": s.eligible_positions,
                "status": s.status,
                "type_guess": guess_type(s.display_position),
            }

            def get_stat(stats: dict, cat: str) -> str:
                # cat -> stat_id
                if cat in HITTER_CATS:
                    return stats.get(HITTER_CATS[cat], "")
                if cat in PITCHER_CATS:
                    return stats.get(PITCHER_CATS[cat], "")
                if cat in EXTRAS:
                    return stats.get(EXTRAS[cat], "")
                return ""

            for cat in (hitter_cols + pitcher_cols + extra_cols):
                row[f"lastseason_{cat}"] = get_stat(s.lastseason_stats, cat)
                row[f"season_{cat}"] = get_stat(s.season_stats, cat)

            w.writerow(row)

    print(f"Saved:\n- {json_path}\n- {csv_path}\n")
    print(f"Players: {len(snapshots)}")


if __name__ == "__main__":
    main()
