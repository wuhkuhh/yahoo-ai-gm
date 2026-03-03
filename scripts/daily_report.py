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




def _fmt_matchup(matchup: dict) -> str:
    out = []
    out.append('## Matchup Projection\n')
    if not matchup:
        out.append('_No matchup data available._\n')
        return '\n'.join(out)
    my  = matchup.get('my_team', {}).get('name', '?')
    opp = matchup.get('opp_team', {}).get('name', '?')
    rec = matchup.get('projected_record', {})
    w, l, t = rec.get('wins',0), rec.get('losses',0), rec.get('toss_ups',0)
    out.append(f'**{my}** vs **{opp}**')
    out.append(f'_Projected record: {w}W - {l}L - {t}T_\n')
    swing = matchup.get('swing_categories', [])
    if swing:
        out.append(f'**Swing categories** (waiver targets): {", ".join(swing)}\n')
    # Category table header
    out.append('| Cat | Mine | Theirs | Delta | Result |')
    out.append('|-----|------|--------|-------|--------|')
    result_icon = {'win': '✅', 'loss': '❌', 'toss-up': '⚖️'}
    for c in matchup.get('categories', []):
        cat   = c['cat']
        mine  = c['my_value']
        theirs= c['opp_value']
        delta = c['delta']
        res   = c['result']
        icon  = result_icon.get(res, res)
        swing_flag = ' 🎯' if c.get('is_swing') else ''
        # Format floats nicely
        if cat in ('AVG', 'ERA', 'WHIP'):
            fmt = '.3f'
        elif cat == 'IP':
            fmt = '.0f'
        else:
            fmt = '.1f'
        out.append(f'| {cat}{swing_flag} | {mine:{fmt}} | {theirs:{fmt}} | {delta:+.3f} | {icon} {res} |')
    unmatched = matchup.get('my_unmatched_players', [])
    if unmatched:
        out.append(f'\n_Unmatched (no FG projection): {", ".join(unmatched)}_')
    out.append('')
    return '\n'.join(out)


def _fmt_multi_trades(trade_sizes: dict) -> str:
    out = []
    out.append('## Multi-Player Trade Suggestions\n')
    if not trade_sizes or not any(trade_sizes.values()):
        out.append('_No multi-player trade suggestions generated._\n')
        return '\n'.join(out)
    labels = {'2for1': '2-for-1 (Give 2, Receive 1)', '1for2': '1-for-2 (Give 1, Receive 2)', '2for2': '2-for-2'}
    for size, suggs in trade_sizes.items():
        if not suggs:
            continue
        out.append(f'### {labels.get(size, size)}')
        for i, s in enumerate(suggs, 1):
            give_str = ' + '.join(p['name'] for p in s.get('give_players', []))
            recv_str = ' + '.join(p['name'] for p in s.get('receive_players', []))
            out.append(f'**{i}. Give {give_str} / Receive {recv_str}** (from {s.get("give_team","?")})')
            out.append(f'- **Score:** {s.get("trade_score",0):.3f} (cat={s.get("cat_score",0):.3f}, pos={s.get("position_multiplier",1):.2f}x)')
            out.append(f'- **Improves:** {", ".join(s.get("cats_improved", []))}')
            if s.get('cats_hurt'):
                out.append(f'- **Costs:** {", ".join(s.get("cats_hurt", []))}')
            out.append(f'- {s.get("rationale", "")}')
            out.append('')
    return '\n'.join(out)

def _fmt_trades(suggestions: list) -> str:
    out = []
    out.append('## Trade Suggestions\n')
    if not suggestions:
        out.append('_No trade suggestions generated._\n')
        return '\n'.join(out)
    for i, s in enumerate(suggestions, 1):
        give = s.get('give', {})
        receive = s.get('receive', {})
        out.append(f"### {i}. Give {give.get('name','?')} / Receive {receive.get('name','?')}")
        out.append(f"- **Score:** {s.get('trade_score', 0):.3f}")
        out.append(f"- **Improves:** {', '.join(s.get('cats_improved', []))}")
        if s.get('cats_hurt'):
            out.append(f"- **Costs:** {', '.join(s.get('cats_hurt', []))}")
        out.append(f"- **Rationale:** {s.get('rationale', '')}")
        out.append('')
    return '\n'.join(out)

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
    from yahoo_ai_gm.use_cases.get_trades import get_trade_report
    try:
        trade_report = get_trade_report(data_dir=Path('data'), n_suggestions=5)
        trades_suggestions = trade_report.suggestions
    except Exception as e:
        print(f'[daily_report] Trade suggestions failed: {e}')
        trades_suggestions = []
    from yahoo_ai_gm.use_cases.get_matchup import get_matchup_report
    try:
        matchup_report = get_matchup_report(data_dir=Path('data'))
        matchup_data = matchup_report.projection
    except Exception as e:
        print(f'[daily_report] Matchup projection failed: {e}')
        matchup_data = {}
    from yahoo_ai_gm.use_cases.get_multi_trades import get_multi_trade_report
    try:
        import signal
        def _timeout(signum, frame): raise TimeoutError()
        signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(30)
        multi_report = get_multi_trade_report(data_dir=Path('data'), n_suggestions=3)
        multi_trade_sizes = multi_report.trade_sizes
        signal.alarm(0)
    except Exception as e:
        print(f'[daily_report] Multi-trade suggestions failed: {e}')
        multi_trade_sizes = {}

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
    lines.append('')
    lines.append(_fmt_trades(trades_suggestions))
    lines.append('')
    lines.append(_fmt_matchup(matchup_data))
    lines.append('')
    lines.append(_fmt_multi_trades(multi_trade_sizes))

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

    # Generate PDF
    pdf_path = REPORTS_DIR / f'report_{date_slug}_week_{week}.pdf'
    latest_pdf = REPORTS_DIR / 'latest.pdf'
    try:
        import importlib.util as _ilu2
        _spec2 = _ilu2.spec_from_file_location('generate_pdf', 'scripts/generate_pdf_report.py')
        _pdf_mod = _ilu2.module_from_spec(_spec2)
        _spec2.loader.exec_module(_pdf_mod)
        _pdf_mod.markdown_to_pdf(report_text, pdf_path)
        latest_pdf.write_bytes(pdf_path.read_bytes())
        print(f'[daily_report] PDF -> {pdf_path}')
    except Exception as e:
        print(f'[daily_report] PDF generation failed: {e}')

    # Send email
    try:
        import os
        mail_from = os.environ.get('MAIL_FROM', '').strip()
        mail_to   = os.environ.get('MAIL_TO', '').strip()
        mail_pass = os.environ.get('MAIL_APP_PASSWORD', '').strip()
        if mail_from and mail_to and mail_pass and latest_pdf.exists():
            import importlib.util as _ilu3
            _spec3 = _ilu3.spec_from_file_location('send_email', 'scripts/send_report_email.py')
            _mail_mod = _ilu3.module_from_spec(_spec3)
            _spec3.loader.exec_module(_mail_mod)
            _mail_mod.send_report(
                md_path=latest_path,
                pdf_path=latest_pdf,
                mail_from=mail_from,
                mail_to=mail_to,
                app_password=mail_pass,
                week=week,
            )
        else:
            print('[daily_report] Email skipped: MAIL_* env vars not set or PDF missing.')
    except Exception as e:
        print(f'[daily_report] Email failed: {e}')


if __name__ == "__main__":
    main()
