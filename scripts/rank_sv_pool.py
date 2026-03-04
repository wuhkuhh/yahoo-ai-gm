from __future__ import annotations

import argparse
import json
from pathlib import Path

from yahoo_ai_gm.snapshot.store import load_snapshot
from yahoo_ai_gm.analysis.pool_scoring import score_candidates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--out", default="data/ranked_sv_pool.json")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--min_sv", type=float, default=5.0, help="minimum baseline SV to be considered a real saves add")
    args = ap.parse_args()

    _ = load_snapshot(args.week)  # ensures snapshot exists; future use for context

    pool = json.loads(Path(args.pool).read_text(encoding="utf-8"))
    players = pool.get("players", [])

    stat_map = json.loads(Path("data/stat_map.json").read_text(encoding="utf-8"))["stat_map"]

    needs = ["SV"]  # hard mode

    ranked = score_candidates(players, stat_map=stat_map, needs=needs)

    # Hard filter: require some meaningful SV baseline
    filtered = [c for c in ranked if c.impacts.get("SV", 0.0) >= args.min_sv]

    out = {
        "week": args.week,
        "mode": "sv",
        "min_sv": args.min_sv,
        "returned": len(players),
        "kept": len(filtered),
        "top": [
            {
                "player_key": c.player_key,
                "name": c.name,
                "team": c.team,
                "pos": c.pos,
                "score": round(c.score, 3),
                "impacts": {k: round(v, 4) for k, v in c.impacts.items() if k in {"SV","K","W","IP","ERA","WHIP"}},
            }
            for c in filtered[: args.top]
        ],
    }

    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote -> {args.out}")
    print(f"returned={out['returned']} kept={out['kept']} (min_sv={args.min_sv})")
    print("Top 10:")
    for r in out["top"][:10]:
        print(r["score"], r["name"], r["pos"], r["impacts"])


if __name__ == "__main__":
    main()
