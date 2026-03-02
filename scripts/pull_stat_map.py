import json
import os
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


def main() -> None:
    settings = Settings.from_local_config()
    session = requests.Session()
    client = YahooClient(settings=settings, session=session)

    league_key = os.getenv("YAHOO_LEAGUE_KEY", "").strip() or f"469.l.{settings.league_id}"

    # League settings includes stat_categories with stat_id + name
    xml_text = client.get(f"league/{league_key}/settings")
    root = _strip_ns(ET.fromstring(xml_text))

    stat_map = {}
    cats = root.findall(".//stat_categories//stat")
    for st in cats:
        stat_id = _text(st, "stat_id")
        name = _text(st, "name")
        if stat_id and name:
            stat_map[stat_id] = name

    out_path = Path("data/stat_map.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"league_key": league_key, "stat_map": stat_map}, indent=2), encoding="utf-8")

    print(f"Wrote {len(stat_map)} stat ids -> {out_path}")


if __name__ == "__main__":
    main()
