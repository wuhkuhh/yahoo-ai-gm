#!/usr/bin/env python3
"""
scripts/snapshot_projections.py

Weekly projection snapshot — stores current FG projections keyed by week.
Run after pull_fg_projections.py (Mon 07:00) so projections are fresh.

Also tracks roster acquisition dates: first week a player appears = acquisition week.

Usage:
  python3 scripts/snapshot_projections.py --week 1
  python3 scripts/snapshot_projections.py  # auto-detects current week
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

PROJ_SNAPSHOTS_DIR = Path("data/projection_snapshots")
ACQUISITION_LOG    = Path("data/acquisition_log.json")


def _latest_week() -> int:
    import importlib.util as _ilu, sys as _sys
    _spec = _ilu.spec_from_file_location("scripts._io", "scripts/_io.py")
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    w = _mod.latest_week_file("scoreboard_week")
    return w or 1


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_projections(week: int) -> None:
    fg_bat = _load_json(Path("data/fg_proj_bat_2026.json"))
    fg_pit = _load_json(Path("data/fg_proj_pit_2026.json"))

    snapshot = {
        "captured_at": datetime.now(tz=timezone.utc).isoformat(),
        "week": week,
        "bat_player_count": len(fg_bat.get("players", [])),
        "pit_player_count": len(fg_pit.get("players", [])),
        "bat": {
            p["PlayerName"]: {
                "R": p.get("R"), "HR": p.get("HR"), "RBI": p.get("RBI"),
                "SB": p.get("SB"), "AVG": p.get("AVG"), "ADP": p.get("ADP"),
            }
            for p in fg_bat.get("players", []) if p.get("PlayerName")
        },
        "pit": {
            p["PlayerName"]: {
                "W": p.get("W"), "SO": p.get("SO"), "SV": p.get("SV"),
                "ERA": p.get("ERA"), "WHIP": p.get("WHIP"), "IP": p.get("IP"),
                "FIP": p.get("FIP"), "ADP": p.get("ADP"),
            }
            for p in fg_pit.get("players", []) if p.get("PlayerName")
        },
    }

    PROJ_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROJ_SNAPSHOTS_DIR / f"projections_week_{week:02d}.json"
    out_path.write_text(json.dumps(snapshot, indent=2))
    print(f"[snapshot_projections] Wrote {out_path}")
    print(f"  Batters: {snapshot['bat_player_count']}  Pitchers: {snapshot['pit_player_count']}")


def update_acquisition_log(week: int) -> None:
    """
    Track first week each rostered player appears.
    acquisition_log.json: {player_key: {name, week_acquired, week_last_seen}}
    """
    snap_path = Path(f"data/snapshots/week_{week}.snapshot.json")
    if not snap_path.exists():
        print(f"[acquisition_log] No snapshot for week {week}, skipping.")
        return

    snap = _load_json(snap_path)
    players = snap.get("roster", {}).get("players", [])

    log: dict = {}
    if ACQUISITION_LOG.exists():
        log = json.loads(ACQUISITION_LOG.read_text())

    for p in players:
        key = p.get("player_key", "")
        name = p.get("name", "")
        if not key:
            continue
        if key not in log:
            log[key] = {
                "name": name,
                "week_acquired": week,
                "week_last_seen": week,
            }
            print(f"  [new] {name} — acquired week {week}")
        else:
            log[key]["week_last_seen"] = week

    ACQUISITION_LOG.write_text(json.dumps(log, indent=2))
    print(f"[acquisition_log] Tracking {len(log)} players -> {ACQUISITION_LOG}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    args = ap.parse_args()

    week = args.week or _latest_week()
    print(f"[snapshot_projections] Week {week}")

    snapshot_projections(week)
    update_acquisition_log(week)


if __name__ == "__main__":
    main()
