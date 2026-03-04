from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--ranked-sv", default="")
    args = ap.parse_args()

    p = Path(args.ranked_sv or f"data/ranked_sv_week_{args.week}.json")
    if not p.exists():
        raise FileNotFoundError(p)

    d = json.loads(p.read_text(encoding="utf-8"))
    scarce = d.get("kept", 0) == 0 and float(d.get("min_sv", 0)) >= 5.0
    out = {
        "week": args.week,
        "sv_scarce": scarce,
        "min_sv": d.get("min_sv"),
        "kept": d.get("kept"),
        "top": d.get("top", [])[:5],
    }
    out_path = Path(f"data/sv_market_week_{args.week}.json")
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Wrote ->", out_path)

if __name__ == "__main__":
    main()
