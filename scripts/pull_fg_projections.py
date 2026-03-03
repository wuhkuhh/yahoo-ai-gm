"""
scripts/pull_fg_projections.py

Fetch 2026 Steamer projections from FanGraphs via __NEXT_DATA__ SSR payload.
Season totals only (IP > 1, PA > 50). No auth required.

Usage:
  python3 scripts/pull_fg_projections.py
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests

FG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

URLS = {
    "bat": "https://www.fangraphs.com/projections?pos=all&stats=bat&type=steamer&lg=all&players=0",
    "pit": "https://www.fangraphs.com/projections?pos=all&stats=pit&type=steamer&lg=all&players=0",
}

MIN_PA_BAT = 50
MIN_IP_PIT = 10

BAT_KEEP = {
    "PlayerName", "Team", "xMLBAMID", "playerids", "Pos",
    "PA", "AB", "H", "HR", "R", "RBI", "BB", "IBB", "SO",
    "SB", "CS", "AVG", "OBP", "SLG", "OPS", "wRC+", "WAR", "ADP",
}

PIT_KEEP = {
    "PlayerName", "Team", "xMLBAMID", "playerids",
    "G", "GS", "IP", "W", "L", "SV", "HLD", "QS",
    "SO", "BB", "H", "HR", "ER",
    "ERA", "WHIP", "K/9", "BB/9", "FIP", "WAR", "ADP",
}


def _fetch_html(url: str, retries: int = 3) -> str:
    session = requests.Session()
    for attempt in range(retries):
        try:
            resp = session.get(url, headers=FG_HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            print(f"  Retry {attempt + 1}/{retries} after error: {e}")
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def _extract_next_data(html: str) -> list[dict]:
    """Extract player array from __NEXT_DATA__ SSR payload."""
    idx = html.find("__NEXT_DATA__")
    if idx < 0:
        raise ValueError("__NEXT_DATA__ not found in page HTML")

    # Find the opening brace
    start = html.find("{", idx)
    if start < 0:
        raise ValueError("Could not find JSON start after __NEXT_DATA__")

    # Find matching close — walk the string tracking depth
    depth = 0
    end = start
    for i, ch in enumerate(html[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    raw_json = html[start:end]
    data = json.loads(raw_json)

    # Navigate: props -> pageProps -> dehydratedState -> queries[0] -> state -> data
    try:
        players = (
            data["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]
        )
        assert isinstance(players, list)
        return players
    except (KeyError, IndexError, AssertionError) as e:
        raise ValueError(f"Unexpected __NEXT_DATA__ structure: {e}")


def _filter_keep(players: list[dict], keep_cols: set[str]) -> list[dict]:
    return [{k: v for k, v in p.items() if k in keep_cols} for p in players]


def _filter_batters(players: list[dict]) -> list[dict]:
    out = []
    for p in players:
        try:
            if float(p.get("PA") or 0) >= MIN_PA_BAT and p.get("PlayerName"):
                out.append(p)
        except (TypeError, ValueError):
            pass
    return out


def _filter_pitchers(players: list[dict]) -> list[dict]:
    out = []
    for p in players:
        try:
            if float(p.get("IP") or 0) >= MIN_IP_PIT and p.get("PlayerName"):
                out.append(p)
        except (TypeError, ValueError):
            pass
    return out


def fetch_and_save(stat_type: str, out_path: Path) -> None:
    assert stat_type in ("bat", "pit")
    url = URLS[stat_type]
    keep = BAT_KEEP if stat_type == "bat" else PIT_KEEP

    print(f"Fetching FanGraphs {stat_type} projections...")
    html = _fetch_html(url)
    print(f"  HTML size: {len(html):,} bytes")

    players = _extract_next_data(html)
    print(f"  Extracted {len(players)} players from __NEXT_DATA__")

    players = _filter_keep(players, keep)

    if stat_type == "bat":
        players = _filter_batters(players)
    else:
        players = _filter_pitchers(players)

    print(f"  After threshold filter: {len(players)} players")

    players.sort(key=lambda p: (p.get("ADP") is None, p.get("ADP") or 999))

    payload = {
        "source": "fangraphs_steamer",
        "season": 2026,
        "stat_type": stat_type,
        "player_count": len(players),
        "players": players,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Wrote -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=["bat", "pit", "both"], default="both")
    ap.add_argument("--bat-out", default="data/fg_proj_bat_2026.json")
    ap.add_argument("--pit-out", default="data/fg_proj_pit_2026.json")
    args = ap.parse_args()

    if args.type in ("bat", "both"):
        fetch_and_save("bat", Path(args.bat_out))
    if args.type in ("pit", "both"):
        fetch_and_save("pit", Path(args.pit_out))


if __name__ == "__main__":
    main()
