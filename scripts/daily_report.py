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







def _fmt_trade_value(players: list) -> str:
    out = []
    out.append('## Trade Value Tracker\n')
    if not players:
        out.append('_No trade value data available._\n')
        return '\n'.join(out)
    sell_high = [p for p in players if p['signal'] == 'SELL_HIGH']
    cut_bait  = [p for p in players if p['signal'] == 'CUT_BAIT']
    watch     = [p for p in players if p['signal'] == 'WATCH']
    hold      = [p for p in players if p['signal'] == 'HOLD']
    signal_icon = {'SELL_HIGH': '[SELL]', 'CUT_BAIT': '[CUT]', 'WATCH': '[WATCH]', 'HOLD': '[HOLD]'}
    if sell_high:
        out.append('**Sell High:**')
        for p in sell_high:
            out.append(f'- {p["name"]} (score={p["value_score"]:+.2f}) — {p["primary_change"]}')
        out.append('')
    if cut_bait:
        out.append('**Cut Bait:**')
        for p in cut_bait:
            out.append(f'- {p["name"]} (score={p["value_score"]:+.2f}) — {p["primary_change"]}')
        out.append('')
    if watch:
        out.append('**Watch:**')
        for p in watch:
            out.append(f'- {p["name"]} (score={p["value_score"]:+.2f}) — {p["primary_change"]}')
        out.append('')
    if not sell_high and not cut_bait and not watch:
        out.append(f'_All {len(hold)} rostered players holding steady. Signals will appear as projections diverge during the season._\n')
    return '\n'.join(out)

def _fmt_il(current: dict, alerts: list) -> str:
    out = []
    out.append('## Injury Monitor\n')
    injured = {k: v for k, v in current.items() if v.get('status')}
    if not injured:
        out.append('_No current injuries._\n')
    else:
        for p in injured.values():
            sev = '🔴' if p.get('on_il') else '🟡'
            out.append(f'- {sev} **{p["name"]}**: {p.get("status_full") or p.get("status","?")}  ')
    if alerts:
        out.append('\n**Recent changes:**')
        type_label = {'NEW_IL': '🚨 New IL', 'NEW_DTD': '⚠️ New DTD',
                      'RETURNED': '✅ Returned', 'UPGRADED': '📈 Upgraded'}
        for a in alerts[:5]:
            label = type_label.get(a['type'], a['type'])
            out.append(f'- {label}: **{a["player_name"]}** ({a["prev_status"] or "OK"} → {a["curr_status"] or "OK"})')
            if a.get('replacement'):
                r = a['replacement']
                out.append(f'  - Suggested add: {r["name"]} ({r["pos"]}, {r["team"]})')
    out.append('')
    return '\n'.join(out)

def _fmt_standings(trajectory: dict) -> str:
    out = []
    out.append('## Standings Trajectory\n')
    if not trajectory:
        out.append('_No standings data available._\n')
        return '\n'.join(out)
    rec = trajectory.get('my_projected_record', {})
    rank = trajectory.get('my_projected_rank', '?')
    prob = trajectory.get('playoff_probability', 0)
    sos  = trajectory.get('strength_of_schedule', 0)
    out.append(f'_Projected: {rec.get("wins",0)}W-{rec.get("losses",0)}L-{rec.get("tossups",0)}T | Rank: {rank}/10 | Playoff prob: {prob*100:.0f}% | SOS: {sos:.1f}_\n')
    hard = trajectory.get('hardest_weeks', [])
    easy = trajectory.get('easiest_weeks', [])
    if hard:
        out.append(f'**Hardest weeks:** {", ".join(str(w) for w in hard)}')
    if easy:
        out.append(f'**Easiest weeks:** {", ".join(str(w) for w in easy)}\n')
    out.append('| Rank | Team | W | L | Playoff% |')
    out.append('|------|------|---|---|----------|')
    for t in trajectory.get('all_standings', []):
        flag = '🏆 ' if t['rank'] <= 6 else ''
        prob_str = f'{t["playoff_probability"]*100:.0f}%'
        out.append(f'| {t["rank"]} | {flag}{t["team"]} | {t["wins"]} | {t["losses"]} | {prob_str} |')
    out.append('')
    return '\n'.join(out)

def _fmt_ratio_risk(profiles: list) -> str:
    out = []
    out.append('## Pitcher Ratio Risk\n')
    if not profiles:
        out.append('_No pitcher risk profiles available._\n')
        return '\n'.join(out)
    label_icon = {'LOW': '🟢', 'MEDIUM': '🟡', 'HIGH': '🟠', 'CRITICAL': '🔴'}
    rec_map = {'START': 'Start', 'STREAM_CAUTION': 'Stream w/ caution', 'AVOID': 'Avoid', 'STASH': 'Stash'}
    out.append('| Pitcher | Role | Risk | Score | ERA | FIP | BB/9 | K/9 | Driver |')
    out.append('|---------|------|------|-------|-----|-----|------|-----|--------|')
    for p in profiles:
        icon = label_icon.get(p['risk_label'], '')
        proj = p.get('projections', {})
        out.append(
            f'| {p["name"]} | {p["role"]} | {icon} {p["risk_label"]} | {p["risk_score"]:.1f} |'
            f' {proj.get("ERA","?"):.3f} | {proj.get("FIP","?"):.3f} |'
            f' {proj.get("BB/9","?"):.2f} | {proj.get("K/9","?"):.2f} |'
            f' {p["primary_driver"]} |'
        )
    # Add recommendations for non-START pitchers
    flagged = [p for p in profiles if p['recommendation'] != 'START']
    if flagged:
        out.append('')
        out.append('**Action items:**')
        for p in flagged:
            rec = rec_map.get(p['recommendation'], p['recommendation'])
            ranges = p.get('projected_ranges', {})
            era_range = ranges.get('ERA', {})
            out.append(f'- {p["name"]}: {rec} — ERA range {era_range.get("upside","?")}-{era_range.get("downside","?")}, driver: {p["primary_driver"]}')
    out.append('')
    return '\n'.join(out)

def _fmt_adddrop(plan: dict) -> str:
    out = []
    out.append('## Add/Drop Simulation\n')
    if not plan or not plan.get('moves'):
        out.append('_No add/drop moves suggested._\n')
        return '\n'.join(out)
    before = plan.get('projected_record_before', {})
    after  = plan.get('projected_record_after', {})
    flipped = plan.get('categories_flipped', [])
    out.append(f'_Projected record: {before.get("wins",0)}-{before.get("losses",0)}-{before.get("toss_ups",0)} → {after.get("wins",0)}-{after.get("losses",0)}-{after.get("toss_ups",0)}_')
    if flipped:
        out.append(f'**Categories flipped to win:** {", ".join(flipped)}\n')
    for m in plan.get('moves', []):
        out.append(f'**Move {m["move_number"]}:** Add {m["add"]["name"]} / Drop {m["drop"]["name"]}')
        out.append(f'- Improves: {", ".join(m.get("cats_improved", []))}')
        if m.get('cats_hurt'):
            out.append(f'- Costs: {", ".join(m.get("cats_hurt", []))}')
        out.append(f'- {m.get("rationale", "")}')
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
    from yahoo_ai_gm.use_cases.get_adddrop import get_adddrop_report
    try:
        adddrop_report = get_adddrop_report(data_dir=Path('data'))
        adddrop_plan = adddrop_report.plan
    except Exception as e:
        print(f'[daily_report] Add/drop simulation failed: {e}')
        adddrop_plan = {}
    from yahoo_ai_gm.use_cases.get_ratio_risk import get_ratio_risk_report
    try:
        ratio_report = get_ratio_risk_report(data_dir=Path('data'))
        ratio_profiles = ratio_report.profiles
    except Exception as e:
        print(f'[daily_report] Ratio risk failed: {e}')
        ratio_profiles = []
    from yahoo_ai_gm.use_cases.get_standings import get_standings_report
    try:
        standings_report = get_standings_report(data_dir=Path('data'), current_week=week)
        standings_data = standings_report.trajectory
    except Exception as e:
        print(f'[daily_report] Standings trajectory failed: {e}')
        standings_data = {}
    import json as _json
    try:
        _il_status = _json.loads(Path('data/il_status.json').read_text()) if Path('data/il_status.json').exists() else {}
        _il_alerts = _json.loads(Path('data/il_alerts.json').read_text()) if Path('data/il_alerts.json').exists() else []
    except Exception as e:
        print(f'[daily_report] IL monitor load failed: {e}')
        _il_status, _il_alerts = {}, []
    from yahoo_ai_gm.use_cases.get_trade_value import get_trade_value_report
    try:
        tv_report = get_trade_value_report(data_dir=Path('data'))
        trade_value_players = tv_report.players
    except Exception as e:
        print(f'[daily_report] Trade value tracker failed: {e}')
        trade_value_players = []
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
    lines.append('')
    lines.append(_fmt_adddrop(adddrop_plan))
    lines.append('')
    lines.append(_fmt_ratio_risk(ratio_profiles))
    lines.append('')
    lines.append(_fmt_standings(standings_data))
    lines.append('')
    lines.append(_fmt_il(_il_status, _il_alerts))
    lines.append('')
    lines.append(_fmt_trade_value(trade_value_players))

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
