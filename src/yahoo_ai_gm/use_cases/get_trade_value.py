"""
src/yahoo_ai_gm/use_cases/get_trade_value.py

Layer 4 — Orchestration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class TradeValueReport:
    generated_at: datetime
    week: int
    players: list[dict]
    sell_high: list[dict]
    cut_bait: list[dict]
    watch: list[dict]


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_trade_value_report(
    data_dir: Path,
    week: Optional[int] = None,
) -> TradeValueReport:
    from yahoo_ai_gm.analysis.trade_value_tracker import (
        compute_trade_value_deltas,
        value_delta_to_dict,
    )

    fg_bat = _load_json(data_dir / "fg_proj_bat_2026.json")
    fg_pit = _load_json(data_dir / "fg_proj_pit_2026.json")
    acq_log = _load_json(data_dir / "acquisition_log.json")
    snapshots_dir = data_dir / "projection_snapshots"

    if week is None:
        weeks = []
        for f in (data_dir / "snapshots").glob("week_*.snapshot.json"):
            try:
                weeks.append(int(f.name.split("_")[1].split(".")[0]))
            except (IndexError, ValueError):
                continue
        week = max(weeks) if weeks else 1

    snap = _load_json(data_dir / f"snapshots/week_{week}.snapshot.json")
    my_roster = snap.get("roster", {}).get("players", [])

    deltas = compute_trade_value_deltas(
        my_roster=my_roster,
        acquisition_log=acq_log,
        snapshots_dir=snapshots_dir,
        current_week=week,
        fg_bat_data=fg_bat,
        fg_pit_data=fg_pit,
    )

    all_players = [value_delta_to_dict(p) for p in deltas]
    sell_high = [p for p in all_players if p["signal"] == "SELL_HIGH"]
    cut_bait  = [p for p in all_players if p["signal"] == "CUT_BAIT"]
    watch     = [p for p in all_players if p["signal"] == "WATCH"]

    return TradeValueReport(
        generated_at=datetime.now(tz=timezone.utc),
        week=week,
        players=all_players,
        sell_high=sell_high,
        cut_bait=cut_bait,
        watch=watch,
    )
