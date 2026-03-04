import argparse
import json
from pathlib import Path

from yahoo_ai_gm.snapshot.store import load_snapshot
from yahoo_ai_gm.analysis.pool_scoring import score_candidates


def derive_needs_from_roster(snapshot) -> list[str]:
    # mirror your waiver_engine heuristic needs for preseason usefulness
    pos_counts = {}
    for p in snapshot.roster.players:
        for pos in (p.eligible_positions or []):
            pos_counts[pos] = pos_counts.get(pos, 0) + 1

    needs = []
    if pos_counts.get("RP", 0) <= 2:
        needs.append("SV")
    if pos_counts.get("SP", 0) >= 7:
        needs.append("K/W (stream) but protect ERA/WHIP")
    if pos_counts.get("1B", 0) >= 3:
        needs.append("Avoid adding 1B")
    if pos_counts.get("OF", 0) >= 6:
        needs.append("Avoid adding OF unless strong fit")
    return needs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--out", default="data/ranked_pool.json")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    snap = load_snapshot(args.week)

    needs = derive_needs_from_roster(snap)

    pool = json.loads(Path(args.pool).read_text(encoding="utf-8"))
    players = pool.get("players", [])

    stat_map = json.loads(Path("data/stat_map.json").read_text(encoding="utf-8"))["stat_map"]

    ranked = score_candidates(players, stat_map=stat_map, needs=needs)

    out = {
        "week": args.week,
        "needs": needs,
        "top": [
            {
                "player_key": c.player_key,
                "name": c.name,
                "team": c.team,
                "pos": c.pos,
                "score": round(c.score, 3),
                "impacts": {k: round(v, 4) for k, v in c.impacts.items() if k in {"R","HR","RBI","SB","AVG","W","SV","K","IP","ERA","WHIP"}},
            }
            for c in ranked[: args.top]
        ],
    }

    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote -> {args.out}")
    print("Needs:", needs)
    print("Top 10:")
    for r in out["top"][:10]:
        print(r["score"], r["name"], r["pos"], r["impacts"])


if __name__ == "__main__":
    main()
