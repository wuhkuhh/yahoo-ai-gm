import argparse
import json
from pathlib import Path

from yahoo_ai_gm.snapshot.store import load_snapshot
from yahoo_ai_gm.analysis.waiver_engine import waiver_recommendations


def _load_players(path_str: str | None):
    if not path_str:
        return None
    p = Path(path_str)
    if not p.exists():
        raise FileNotFoundError(f"Pool file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8")).get("players", [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--pool", required=True, help="General waiver pool JSON with {players:[...]}")
    parser.add_argument("--sv-pool", required=False, help="Targeted RP pool JSON with {players:[...]} for SV scarcity detection")
    args = parser.parse_args()

    snapshot = load_snapshot(week=args.week)

    pool = _load_players(args.pool)
    sv_pool = _load_players(args.sv_pool) if args.sv_pool else None

    report = waiver_recommendations(
        snapshot=snapshot,
        pool=pool,
        sv_pool=sv_pool,
    )

    # WaiverReport is a pydantic/dataclass-ish model in your codebase.
    # Try best-effort JSON output:
    try:
        print(report.model_dump_json(indent=2))  # pydantic v2
    except Exception:
        try:
            print(json.dumps(report.__dict__, indent=2, default=str))
        except Exception:
            print(report)


if __name__ == "__main__":
    main()
