#!/usr/bin/env python3
"""
scripts/check_il.py

IL/injury monitor. Runs daily, detects status changes, surfaces replacements.

Writes:
  data/il_status.json    — current status snapshot
  data/il_alerts.json    — pending alerts (new injuries/returns)

Usage:
  python3 scripts/check_il.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from yahoo_ai_gm.yahoo_client import YahooClient
import xml.etree.ElementTree as ET

LEAGUE_KEY  = "469.l.40206"
MY_TEAM_KEY = "469.l.40206.t.6"
NS          = "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"

IL_STATUS_PATH = Path("data/il_status.json")
IL_ALERTS_PATH = Path("data/il_alerts.json")
POOL_PATH      = Path("data/waiver_pool_baseline_2025_300.json")


SEVERITY = {
    "":      0,   # healthy
    "DTD":   1,   # day-to-day
    "IL10":  2,
    "IL15":  2,
    "IL60":  3,
    "NA":    3,
    "SUSP":  2,
}


def _severity(status: str) -> int:
    return SEVERITY.get(status.strip().upper(), 1)


def fetch_current_statuses(client: YahooClient) -> dict[str, dict]:
    xml = client.get(f"team/{MY_TEAM_KEY}/roster/players")
    root = ET.fromstring(xml)
    ns = NS
    players = {}
    for player in root.iter(f"{{{ns}}}player"):
        key         = player.findtext(f".//{{{ns}}}player_key") or ""
        name        = player.findtext(f".//{{{ns}}}full") or ""
        status      = player.findtext(f".//{{{ns}}}status") or ""
        status_full = player.findtext(f".//{{{ns}}}status_full") or ""
        on_il       = player.findtext(f".//{{{ns}}}on_disabled_list") or "0"
        if key:
            players[key] = {
                "name":        name,
                "status":      status.strip(),
                "status_full": status_full.strip(),
                "on_il":       on_il == "1",
                "checked_at":  datetime.now(tz=timezone.utc).isoformat(),
            }
    return players


def load_previous_statuses() -> dict[str, dict]:
    if IL_STATUS_PATH.exists():
        return json.loads(IL_STATUS_PATH.read_text())
    return {}


def _top_replacement(drop_name: str, pool_players: list[dict]) -> dict | None:
    """Return best available replacement from pool by ADP."""
    eligible = [
        p for p in pool_players
        if p.get("ownership_type") in (None, "freeagent", "waivers")
    ]
    eligible.sort(key=lambda p: float(p.get("percent_owned") or 0), reverse=True)
    return eligible[0] if eligible else None


def detect_changes(
    previous: dict[str, dict],
    current: dict[str, dict],
    pool_players: list[dict],
) -> list[dict]:
    alerts = []
    now = datetime.now(tz=timezone.utc).isoformat()

    for key, curr in current.items():
        prev = previous.get(key)
        name = curr["name"]
        curr_sev = _severity(curr["status"])

        if prev is None:
            # New player on roster — just track, no alert
            continue

        prev_sev = _severity(prev["status"])

        if curr_sev > prev_sev:
            # Worsened: healthy->DTD, DTD->IL, etc.
            alert_type = "NEW_IL" if curr["on_il"] else "NEW_DTD"
            replacement = None
            if curr["on_il"]:
                replacement = _top_replacement(name, pool_players)

            alerts.append({
                "type":        alert_type,
                "player_key":  key,
                "player_name": name,
                "prev_status": prev["status"] or "OK",
                "curr_status": curr["status"] or "OK",
                "status_full": curr["status_full"],
                "detected_at": now,
                "replacement": {
                    "name":    replacement["name"],
                    "pos":     replacement.get("pos", "?"),
                    "team":    replacement.get("team", "?"),
                    "owned":   replacement.get("percent_owned", "?"),
                } if replacement else None,
            })

        elif prev_sev > curr_sev:
            # Improved: IL->DTD or DTD->healthy
            alert_type = "RETURNED" if prev["on_il"] and not curr["on_il"] else "UPGRADED"
            alerts.append({
                "type":        alert_type,
                "player_key":  key,
                "player_name": name,
                "prev_status": prev["status"] or "OK",
                "curr_status": curr["status"] or "OK",
                "status_full": curr["status_full"] or "Active",
                "detected_at": now,
                "replacement": None,
            })

    return alerts


def load_existing_alerts() -> list[dict]:
    if IL_ALERTS_PATH.exists():
        return json.loads(IL_ALERTS_PATH.read_text())
    return []


def main() -> None:
    client = YahooClient.from_local_config()

    print("[check_il] Fetching current roster statuses...")
    current = fetch_current_statuses(client)
    previous = load_previous_statuses()

    # Load pool for replacement suggestions
    pool_players = []
    if POOL_PATH.exists():
        raw = json.loads(POOL_PATH.read_text())
        pool_players = raw.get("players", raw if isinstance(raw, list) else [])

    # Detect changes
    alerts = detect_changes(previous, current, pool_players)

    # Save current as new baseline
    IL_STATUS_PATH.write_text(json.dumps(current, indent=2))
    print(f"[check_il] Status snapshot -> {IL_STATUS_PATH} ({len(current)} players)")

    # Merge alerts (keep last 30 days)
    existing = load_existing_alerts()
    all_alerts = alerts + existing
    # Keep only most recent 50 alerts
    all_alerts = all_alerts[:50]
    IL_ALERTS_PATH.write_text(json.dumps(all_alerts, indent=2))

    if alerts:
        print(f"[check_il] {len(alerts)} new alert(s):")
        for a in alerts:
            print(f"  [{a['type']}] {a['player_name']}: {a['prev_status']} -> {a['curr_status']}")
            if a.get("replacement"):
                r = a["replacement"]
                print(f"    Suggested replacement: {r['name']} ({r['pos']}, {r['team']})")
    else:
        print("[check_il] No status changes detected.")

    # Print current injuries
    injured = [p for p in current.values() if p["status"]]
    if injured:
        print(f"\n[check_il] Current injuries ({len(injured)}):")
        for p in injured:
            print(f"  {p['name']}: {p['status_full'] or p['status']}")


if __name__ == "__main__":
    main()
