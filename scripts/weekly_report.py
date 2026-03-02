from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts._io import latest_week_file


def run_py(module_path: str, args: list[str]) -> None:
    module = module_path.replace("/", ".").replace(".py", "")
    cmd = [sys.executable, "-m", module] + args
    print(f"\n$ {' '.join(cmd)}")
    subprocess.run(cmd, check=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    args = ap.parse_args()

    week = args.week or latest_week_file("scoreboard_week")
    if not week:
        raise SystemExit("No scoreboard files found. Run pull_scoreboard_week.py first.")

    print("=" * 80)
    print(f"YAHOO AI GM — WEEK {week} REPORT")
    print("=" * 80)

    run_py("scripts/roster_inspector.py", ["--week", str(week)])
    run_py("scripts/category_pressure.py", ["--week", str(week)])
    run_py("scripts/waiver_targets.py", ["--week", str(week)])

    print("\nDone.")


if __name__ == "__main__":
    main()
