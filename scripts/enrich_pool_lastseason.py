from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from yahoo_ai_gm.yahoo_client import YahooClient


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _text(node: ET.Element, path: str, default: str = "") -> str:
    found = node.find(path)
    return found.text.strip() if (found is not None and found.text) else default


def parse_player_stats_by_id(xml_text: str) -> dict[str, str]:
    root = _strip_ns(ET.fromstring(xml_text))
    out: dict[str, str] = {}
    for stat in root.findall(".//stats//stat"):
        stat_id = _text(stat, "stat_id")
        value = _text(stat, "value")
        if stat_id:
            out[str(stat_id)] = value
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--limit", type=int, default=0, help="0=all, else first N players")
    args = ap.parse_args()

    yc = YahooClient.from_local_config()

    pool = json.loads(Path(args.pool).read_text(encoding="utf-8"))
    players = pool.get("players", [])
    if args.limit and args.limit > 0:
        players = players[: args.limit]

    enriched: list[dict[str, Any]] = []
    total = len(players)

    for i, p in enumerate(players, start=1):
        pk = p["player_key"]
        name = p.get("name", pk)

        path = f"player/{pk}/stats;type=season;season={args.season}"
        xml_text = yc.get(path)

        baseline_stats_by_id = parse_player_stats_by_id(xml_text)

        p2 = dict(p)
        p2["baseline_season"] = args.season
        p2["baseline_stats_by_id"] = baseline_stats_by_id
        enriched.append(p2)

        print(f"[{i}/{total}] ok {name}")
        time.sleep(args.sleep)

    out = dict(pool)
    out["baseline_season"] = args.season
    out["players"] = enriched

    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote -> {args.out}")


if __name__ == "__main__":
    main()
