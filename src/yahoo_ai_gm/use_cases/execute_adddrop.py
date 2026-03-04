"""
src/yahoo_ai_gm/use_cases/execute_adddrop.py

Layer 4 — Orchestration for add/drop execution.

This use case:
  1. Runs the add/drop simulation
  2. Passes the plan to the executor
  3. Returns execution results

GATED: will only live-execute if YAHOO_AUTO_EXECUTE=true in environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ExecutionReport:
    generated_at: datetime
    week: int
    dry_run: bool
    auto_execute_enabled: bool
    moves_planned: int
    moves_attempted: int
    moves_succeeded: int
    results: list[dict]


def get_execution_report(
    data_dir: Path,
    week: Optional[int] = None,
    max_moves: int = 6,
    n_teams: int = 10,
    dry_run: Optional[bool] = None,
) -> ExecutionReport:
    from yahoo_ai_gm.use_cases.get_adddrop import get_adddrop_report
    from yahoo_ai_gm.adapters.yahoo_executor import execute_adddrop_plan
    import json

    auto_execute = os.environ.get("YAHOO_AUTO_EXECUTE", "false").strip().lower() == "true"

    # If dry_run not explicitly set, infer from env
    if dry_run is None:
        dry_run = not auto_execute

    # Load league config for keys
    league_data = json.loads((data_dir / "league_rosters.json").read_text())
    league_key = league_data.get("league_key", "")

    snap_path = None
    if week is None:
        snapshots_dir = data_dir / "snapshots"
        weeks = []
        for f in snapshots_dir.glob("week_*.snapshot.json"):
            try:
                weeks.append(int(f.name.split("_")[1].split(".")[0]))
            except (IndexError, ValueError):
                continue
        if not weeks:
            raise FileNotFoundError("No snapshot files found.")
        week = max(weeks)

    snap = json.loads((data_dir / f"snapshots/week_{week}.snapshot.json").read_text())
    my_team_key = snap.get("roster", {}).get("team_key", "")

    if not league_key or not my_team_key:
        raise ValueError(f"Missing league_key={league_key!r} or my_team_key={my_team_key!r}")

    # Run simulation
    adddrop_report = get_adddrop_report(
        data_dir=data_dir,
        week=week,
        max_moves=max_moves,
        n_teams=n_teams,
    )
    moves = adddrop_report.plan.get("moves", [])

    # Execute (or dry-run)
    results = execute_adddrop_plan(
        moves=moves,
        league_key=league_key,
        my_team_key=my_team_key,
        dry_run=dry_run,
    )

    succeeded = sum(1 for r in results if r.success)

    return ExecutionReport(
        generated_at=datetime.now(tz=timezone.utc),
        week=week,
        dry_run=dry_run,
        auto_execute_enabled=auto_execute,
        moves_planned=len(moves),
        moves_attempted=len(results),
        moves_succeeded=succeeded,
        results=[
            {
                "move_number": r.move_number,
                "add": r.add_name,
                "drop": r.drop_name,
                "dry_run": r.dry_run,
                "success": r.success,
                "error": r.error,
            }
            for r in results
        ],
    )
