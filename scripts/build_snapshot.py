from __future__ import annotations

import argparse
from pathlib import Path

from yahoo_ai_gm.snapshot.build import build_snapshot_from_files
from yahoo_ai_gm.snapshot.store import save_snapshot


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--week", type=int, required=True)

    # You can omit these if you prefer to hardcode later in settings.
    p.add_argument("--league-key", default="469.l.40206")
    p.add_argument("--my-team-key", default="469.l.40206.t.6")

    p.add_argument("--roster-json", default="data/roster.json")
    p.add_argument("--scoreboard-json", default=None)

    args = p.parse_args()
    scoreboard = args.scoreboard_json or f"data/scoreboard_week_{args.week}.json"

    snap = build_snapshot_from_files(
        league_key=args.league_key,
        week=args.week,
        my_team_key=args.my_team_key,
        roster_json_path=Path(args.roster_json),
        scoreboard_json_path=Path(scoreboard),
    )

    path = save_snapshot(snap)
    print(f"Saved snapshot -> {path}")


if __name__ == "__main__":
    main()
