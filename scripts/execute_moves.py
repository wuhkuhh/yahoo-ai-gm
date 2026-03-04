#!/usr/bin/env python3
"""
scripts/execute_moves.py

CLI entry point for add/drop execution.

Usage:
  # Dry run (always safe — logs what would happen)
  python3 scripts/execute_moves.py

  # Live execution (requires YAHOO_AUTO_EXECUTE=true in environment)
  YAHOO_AUTO_EXECUTE=true python3 scripts/execute_moves.py

  # Limit moves
  python3 scripts/execute_moves.py --max-moves 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week",       type=int, default=None)
    ap.add_argument("--max-moves",  type=int, default=6)
    ap.add_argument("--n-teams",    type=int, default=10)
    ap.add_argument("--dry-run",    action="store_true", default=None,
                    help="Force dry run regardless of YAHOO_AUTO_EXECUTE")
    args = ap.parse_args()

    auto_execute = os.environ.get("YAHOO_AUTO_EXECUTE", "false").strip().lower() == "true"
    dry_run = True if args.dry_run else (not auto_execute)

    print(f"[execute_moves] YAHOO_AUTO_EXECUTE={auto_execute}")
    print(f"[execute_moves] dry_run={dry_run}")
    if not auto_execute:
        print("[execute_moves] ⚠️  Running in DRY RUN mode. Set YAHOO_AUTO_EXECUTE=true to execute live.")

    from yahoo_ai_gm.use_cases.execute_adddrop import get_execution_report

    report = get_execution_report(
        data_dir=Path("data"),
        week=args.week,
        max_moves=args.max_moves,
        n_teams=args.n_teams,
        dry_run=dry_run,
    )

    print(f"\n[execute_moves] Week {report.week} | Planned: {report.moves_planned} | Succeeded: {report.moves_succeeded}")
    print(f"[execute_moves] Auto-execute enabled: {report.auto_execute_enabled}")
    print()
    for r in report.results:
        status = "✅" if r["success"] else "❌"
        mode   = "[DRY]" if r["dry_run"] else "[LIVE]"
        print(f"  {status} {mode} Move {r["move_number"]}: Add {r["add"]} / Drop {r["drop"]}")
        if r.get("error"):
            print(f"       Error: {r["error"]}")

    print(f"\n[execute_moves] Log: data/execution_log.jsonl")


if __name__ == "__main__":
    main()
