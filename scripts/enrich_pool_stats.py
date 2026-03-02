import argparse
import json
import time
from pathlib import Path
import xml.etree.ElementTree as ET
import requests

from yahoo_ai_gm.yahoo_client import YahooClient
from yahoo_ai_gm.settings import Settings


def _strip_ns(root):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _text(node, path, default=""):
    found = node.find(path)
    return found.text.strip() if (found is not None and found.text) else default


def fetch_player_stats_xml(yc: YahooClient, player_key: str) -> str:
    # Common pattern: player/{player_key}/stats
    endpoint = f"player/{player_key}/stats"
    return yc.get(endpoint)


def parse_player_stats(xml_text: str) -> dict:
    """
    Returns a dict like:
      {"stat_map": {"R": 10, "HR": 2, ...}} if Yahoo provides stat_id-based output.
    We’ll keep raw stat_id/value pairs first; later we map stat_ids -> category names.
    """
    root = _strip_ns(ET.fromstring(xml_text))

    # Yahoo stats often look like: player/stats/stat -> stat_id, value
    stats = {}
    for stat in root.findall(".//stats//stat"):
        stat_id = _text(stat, "stat_id")
        value = _text(stat, "value")
        if stat_id:
            stats[stat_id] = value

    return {"stats_by_id": stats}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="data/waiver_pool_limit_100.json")
    ap.add_argument("--out", default="data/waiver_pool_enriched_100.json")
    ap.add_argument("--sleep", type=float, default=0.2, help="Sleep between requests (seconds).")
    ap.add_argument("--limit", type=int, default=None, help="Only enrich first N players (debug).")
    args = ap.parse_args()

    settings = Settings.from_local_config()
    session = requests.Session()
    yc = YahooClient(settings=settings, session=session)

    pool = json.loads(Path(args.pool).read_text(encoding="utf-8"))
    players = pool.get("players", [])

    if args.limit is not None:
        players = players[: args.limit]

    enriched = []
    for i, p in enumerate(players, start=1):
        pk = p["player_key"]
        try:
            xml_text = fetch_player_stats_xml(yc, pk)
            parsed = parse_player_stats(xml_text)
            p2 = dict(p)
            p2.update(parsed)
            enriched.append(p2)
            print(f"[{i}/{len(players)}] ok {p['name']}")
        except Exception as e:
            print(f"[{i}/{len(players)}] FAIL {p.get('name')} {pk}: {e}")
            p2 = dict(p)
            p2["stats_by_id"] = {}
            p2["stats_error"] = str(e)
            enriched.append(p2)

        time.sleep(args.sleep)

    out = dict(pool)
    out["players"] = enriched
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote -> {args.out}")


if __name__ == "__main__":
    main()
