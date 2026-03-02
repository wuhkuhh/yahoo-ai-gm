import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import requests

from yahoo_ai_gm.yahoo_client import YahooClient
from yahoo_ai_gm.settings import Settings

PAGE_SIZE = 25  # Yahoo commonly caps page size


def _text(node, path, default=""):
    found = node.find(path)
    return found.text.strip() if (found is not None and found.text) else default


def _split_positions(s: str):
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def _to_float(s: str):
    try:
        return float(s)
    except Exception:
        return None


def _parse_players(xml_text: str):
    root = ET.fromstring(xml_text)

    # Strip namespaces to simplify XPath
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    players = []
    for player in root.findall(".//player"):
        player_key = _text(player, "player_key")
        name_full = _text(player, "name/full")
        editorial_team_abbr = _text(player, "editorial_team_abbr")
        status = _text(player, "status")

        positions = [pos.text.strip() for pos in player.findall(".//eligible_positions/position") if pos.text]
        if not positions:
            positions = _split_positions(_text(player, "display_position"))

        # ownership fields vary a bit; try common paths
        percent_owned = (
            _text(player, "percent_owned")
            or _text(player, "ownership/percent_owned")
            or _text(player, "player_owned/percent_owned")
        )
        percent_owned = _to_float(percent_owned) if percent_owned else None

        ownership_type = _text(player, "ownership/ownership_type") or _text(player, "ownership_type") or None

        if player_key and name_full:
            players.append(
                {
                    "player_key": player_key,
                    "name": name_full,
                    "team": editorial_team_abbr or None,
                    "pos": ",".join(positions),
                    "status": status or None,
                    "percent_owned": percent_owned,
                    "ownership_type": ownership_type,
                }
            )
    return players


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--league-key", default=None, help="Yahoo league_key like 469.l.40206")
    p.add_argument("--limit", type=int, default=100, help="Total players to collect (auto-paged).")
    p.add_argument("--start", type=int, default=0, help="Start offset.")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    settings = Settings.from_local_config()
    session = requests.Session()
    yc = YahooClient(settings=settings, session=session)

    league_key = args.league_key or f"469.l.{settings.league_id}"

    out_path = Path(args.out or f"data/waiver_pool_limit_{args.limit}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_players = []
    start = args.start

    while len(all_players) < args.limit:
        count = min(PAGE_SIZE, args.limit - len(all_players))
        endpoint = f"league/{league_key}/players;status=A;start={start};count={count}"
        xml_text = yc.get(endpoint)

        batch = _parse_players(xml_text)
        if not batch:
            break

        all_players.extend(batch)

        if len(batch) < count:
            break

        start += len(batch)

    out_path.write_text(
        json.dumps(
            {
                "league_key": league_key,
                "start": args.start,
                "limit": args.limit,
                "returned": len(all_players),
                "players": all_players,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(all_players)} players -> {out_path}")


if __name__ == "__main__":
    main()
