import argparse

from yahoo_ai_gm.snapshot.store import load_snapshot
from yahoo_ai_gm.analysis.category_pressure import pressure_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()

    snap = load_snapshot(args.week)
    report = pressure_report(snap)

    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
