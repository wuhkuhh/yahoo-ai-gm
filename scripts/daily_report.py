from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import importlib.util as _ilu, sys as _sys
_spec = _ilu.spec_from_file_location("scripts._io", "scripts/_io.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
latest_week_file = _mod.latest_week_file
from yahoo_ai_gm.snapshot.store import load_snapshot
from yahoo_ai_gm.analysis.category_pressure import pressure_report
from yahoo_ai_gm.analysis.roster_inefficiency import roster_inefficiency_report
from yahoo_ai_gm.analysis.waiver_engine import waiver_recommendations

REPORTS_DIR = Path("data/reports")
POOL_PATH = Path("data/waiver_pool_baseline_2025.json")
SV_POOL_PATH = Path("data/pool_RP_200_baseline_2025.json")


def _latest_week() -> int:
    w = latest_week_file("scoreboard_week")
    if not w:
        raise SystemExit("No scoreboard files found. Run refresh_snapshot.sh first.")
    return w


def _fmt_pressure(report) -> str:
    lines = []
    lines.append("## Category Pressure\n")
    if report.matchup_status:
        lines.append(f"_Matchup status: `{report.matchup_status}`_\n")
    if report.matchup_status == "preevent":
        lines.append("_No live stats yet — all categories even. Report will populate once the week begins._\n")
        return "\n".join(lines)

    headers = ["Category", "Mine", "Opp", "Diff", "Posture"]
    rows = []
    for p in report.pressures:
        rows.append([
            p.category,
            f"{p.my_value:.3f}" if isinstance(p.my_value, float) else str(p.my_value),
            f"{p.opp_value:.3f}" if isinstance(p.opp_value, float) else str(p.opp_value),
            f"{p.diff:+.3f}",
            p.posture,
        ])

    col_widths = [max(len(h), max((len(r[i]) for r in rows), default=0)) for i, h in enumerate(headers)]
    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    header_row = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    lines.append(header_row)
    lines.append(sep)
    for r in rows:
        lines.append("| " + " | ".join(r[i].ljust(col_widths[i]) for i in range(len(headers))) + " |")
    return "\n".join(lines)


def _fmt_inefficiency(report) -> str:
    lines = []
    lines.append("## Roster Inefficiencies\n")
    if not report.items:
        lines.append("_No inefficiencies detected._\n")
        return "\n".join(lines)
    for item in report.items:
        player = f" — {item.player_name}" if item.player_name else ""
        lines.append(f"- **[{item.severity.upper()}]** `{item.kind}`{player}: {item.note}")
    return "\n".join(lines)


def _fmt_waivers(report) -> str:
    lines = []
    lines.append("## Waiver Suggestions\n")
    if not report.suggestions:
        lines.append("_No suggestions generated._\n")
        return "\n".join(lines)
    for i, s in enumerate(report.suggestions, 1):
        lines.append(f"### {i}. Add {s.add_name} / Drop {s.drop_name}")
        lines.append(f"- **Confidence:** {s.confidence}")
        lines.append(f"- **Reason:** {s.reason}")
        if s.category_impacts:
            impacts = ", ".join(
                f"{k}: {v:.1f}" if isinstance(v, float) else f"{k}: {v}"
                for k, v in s.category_impacts.items()
                if v != 0.0
            )
            if impacts:
                lines.append(f"- **Impacts:** {impacts}")
        lines.append("")
    return "\n".join(lines)


def generate_report(week: int) -> str:
    snapshot = load_snapshot(week)

    pressure = pressure_report(snapshot)
    inefficiency = roster_inefficiency_report(snapshot)

    pool = POOL_PATH if POOL_PATH.exists() else None
    sv_pool = SV_POOL_PATH if SV_POOL_PATH.exists() else None

    pool_list = None
    sv_pool_list = None
    if pool:
        import json
        raw = json.loads(pool.read_text(encoding="utf-8"))
        pool_list = raw if isinstance(raw, list) else raw.get("players") or raw.get("pool") or []
    if sv_pool:
        import json
        raw = json.loads(sv_pool.read_text(encoding="utf-8"))
        sv_pool_list = raw if isinstance(raw, list) else raw.get("players") or raw.get("pool") or []

    waivers = waiver_recommendations(snapshot, pool=pool_list, sv_pool=sv_pool_list)

    now = datetime.now(timezone.utc).astimezone()
    ts = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    date_slug = now.strftime("%Y-%m-%d")

    lines = []
    lines.append(f"# Yahoo AI GM — Daily Report")
    lines.append(f"_Team: {snapshot.matchup.my_team.team_name} | Week: {week} | Generated: {ts}_")
    lines.append("")
    lines.append(_fmt_pressure(pressure))
    lines.append("")
    lines.append(_fmt_inefficiency(inefficiency))
    lines.append("")
    lines.append(_fmt_waivers(waivers))

    return "\n".join(lines), date_slug


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    args = ap.parse_args()

    week = args.week or _latest_week()
    print(f"[daily_report] Generating report for week {week}...")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    report_text, date_slug = generate_report(week)

    out_path = REPORTS_DIR / f"report_{date_slug}_week_{week}.md"
    out_path.write_text(report_text, encoding="utf-8")

    # Also write a stable "latest" symlink-equivalent
    latest_path = REPORTS_DIR / "latest.md"
    latest_path.write_text(report_text, encoding="utf-8")

    print(f"[daily_report] Saved -> {out_path}")
    print(f"[daily_report] Saved -> {latest_path}")


if __name__ == "__main__":
    main()
