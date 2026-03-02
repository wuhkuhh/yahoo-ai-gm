from __future__ import annotations

import argparse
import json
from pathlib import Path
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


def parse_players(xml_text: str) -> list[dict]:
    root = _strip_ns(ET.fromstring(xml_text))
    out = []
    for pl in root.findall(".//players/player"):
        player_key = _text(pl, "player_key")
        name = _text(pl, "name/full")
        # team abbreviation is buried; try editorial_team_abbr first
        team = _text(pl, "editorial_team_abbr")
        pos = _text(pl, "display_position")
        status = _text(pl, "status") or None
        if player_key:
            out.append(
                {
                    "player_key": player_key,
                    "name": name,
                    "team": team,
                    "pos": pos,
                    "status": status,
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league-key", default="", help="e.g. 469.l.40206 (optional if in env)")
    ap.add_argument("--pos", required=True, help="RP, SP, OF, etc")
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    yc = YahooClient.from_local_config()
    league_key = args.league_key.strip() or f"469.l.{yc.settings.league_id}"

    out_path = Path(args.out or f"data/pool_{args.pos}_start_{args.start}_count_{args.count}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    path = f"league/{league_key}/players;status=A;position={args.pos};start={args.start};count={args.count}"
    xml_text = yc.get(path)
    players = parse_players(xml_text)

    payload = {
        "league_key": league_key,
        "position": args.pos,
        "start": args.start,
        "count": args.count,
        "returned": len(players),
        "players": players,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote -> {out_path} (returned={len(players)})")


if __name__ == "__main__":
    main()
