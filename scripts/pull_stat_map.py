from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from yahoo_ai_gm.yahoo_client import YahooClient

NS = {"y": "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"}

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def t(node: ET.Element, path: str, default: str = "") -> str:
    el = node.find(path, NS)
    return el.text.strip() if el is not None and el.text else default

def main():
    client = YahooClient.from_local_config()
    league_key = client.settings.league_key  # e.g. 469.l.40206

    xml = client.get(f"league/{league_key}/settings")
    root = ET.fromstring(xml)

    # Yahoo's stat categories are under league/settings/stat_categories
    stats = root.findall(".//y:stat_categories/y:stats/y:stat", NS)
    if not stats:
        # some responses nest differently, fallback
        stats = root.findall(".//y:stat", NS)

    stat_map = {}
    for s in stats:
        stat_id = t(s, "y:stat_id")
        name = t(s, "y:name")
        display_name = t(s, "y:display_name") or name
        group = t(s, "y:stat_group")  # often 'batting' or 'pitching'
        # Some leagues include these:
        position_type = t(s, "y:position_type")  # B or P
        sort_order = t(s, "y:sort_order")
        is_only_display = t(s, "y:is_only_display_stat")

        if stat_id:
            stat_map[stat_id] = {
                "name": name,
                "display_name": display_name,
                "group": group,
                "position_type": position_type,
                "sort_order": sort_order,
                "is_only_display_stat": is_only_display,
            }

    out_path = DATA_DIR / "stat_map.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(stat_map, f, indent=2, sort_keys=True)

    print(f"Saved {len(stat_map)} stat definitions -> {out_path}")

    # Print the most relevant stuff to screen for quick sanity
    print("\n--- Stat IDs (id -> display_name) ---")
    for sid in sorted(stat_map.keys(), key=lambda x: int(x) if x.isdigit() else 9999):
        print(f"{sid:>4} -> {stat_map[sid]['display_name']}")

if __name__ == "__main__":
    main()
