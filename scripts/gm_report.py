from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DATA_DIR = Path("data")
SNAPSHOT_JSON = DATA_DIR / "roster_snapshot.json"
REPORT_MD = DATA_DIR / "gm_report.md"

# Your league stat IDs (confirmed from your stat_map output)
HITTER = {"R": "7", "HR": "12", "RBI": "13", "SB": "16", "AVG": "3"}
PITCHER = {"W": "28", "K": "42", "ERA": "26", "WHIP": "27", "SV": "32", "IP": "50"}


def safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def safe_int(x: Any) -> Optional[int]:
    f = safe_float(x)
    if f is None:
        return None
    return int(round(f))


def fmt(x: Optional[float], digits: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:.{digits}f}"


def zscore(x: float, mean: float, std: float) -> float:
    if std <= 0:
        return 0.0
    return (x - mean) / std


@dataclass
class Player:
    player_key: str
    full_name: str
    mlb_team: str
    display_position: str
    eligible_positions: str
    status: str
    lastseason: Dict[str, str]


def load_snapshot() -> List[Player]:
    if not SNAPSHOT_JSON.exists():
        raise FileNotFoundError(
            f"Missing {SNAPSHOT_JSON}. Run: python scripts/pull_roster_snapshot.py"
        )

    raw = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
    players: List[Player] = []
    for row in raw:
        players.append(
            Player(
                player_key=row.get("player_key", ""),
                full_name=row.get("full_name", ""),
                mlb_team=row.get("mlb_team", ""),
                display_position=row.get("display_position", ""),
                eligible_positions=row.get("eligible_positions", ""),
                status=row.get("status", "OK") or "OK",
                lastseason=row.get("lastseason_stats", {}) or {},
            )
        )
    return players


def is_pitcher(p: Player) -> bool:
    dp = (p.display_position or "").upper()
    return ("SP" in dp) or ("RP" in dp) or (dp == "P")


def get_stat(p: Player, stat_id: str) -> Optional[float]:
    return safe_float(p.lastseason.get(stat_id))


def median(xs: List[float]) -> Optional[float]:
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    mid = n // 2
    if n % 2 == 1:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2


def main() -> None:
    players = load_snapshot()
    hitters = [p for p in players if not is_pitcher(p)]
    pitchers = [p for p in players if is_pitcher(p)]

    # Health
    flagged = [p for p in players if (p.status or "").upper() not in ("OK", "")]
    dtd = [p for p in flagged if (p.status or "").upper() == "DTD"]
    il = [p for p in flagged if "IL" in (p.status or "").upper()]

    # Position coverage
    pos_counts: Dict[str, int] = {}
    for p in players:
        elig = (p.eligible_positions or "").split(",") if p.eligible_positions else []
        for pos in elig:
            pos = pos.strip()
            if not pos:
                continue
            pos_counts[pos] = pos_counts.get(pos, 0) + 1

    # Hitter profile (lastseason)
    h_hr = [get_stat(p, HITTER["HR"]) for p in hitters]
    h_sb = [get_stat(p, HITTER["SB"]) for p in hitters]
    h_avg = [get_stat(p, HITTER["AVG"]) for p in hitters]
    # Filter Nones
    hr_vals = [x for x in h_hr if x is not None]
    sb_vals = [x for x in h_sb if x is not None]
    avg_vals = [x for x in h_avg if x is not None]

    total_hr = sum(hr_vals) if hr_vals else None
    total_sb = sum(sb_vals) if sb_vals else None
    med_avg = median(avg_vals)

    # Pitcher profile
    p_ip = [get_stat(p, PITCHER["IP"]) for p in pitchers]
    p_k = [get_stat(p, PITCHER["K"]) for p in pitchers]
    p_w = [get_stat(p, PITCHER["W"]) for p in pitchers]
    p_sv = [get_stat(p, PITCHER["SV"]) for p in pitchers]
    p_era = [get_stat(p, PITCHER["ERA"]) for p in pitchers]
    p_whip = [get_stat(p, PITCHER["WHIP"]) for p in pitchers]

    ip_vals = [x for x in p_ip if x is not None]
    k_vals = [x for x in p_k if x is not None]
    w_vals = [x for x in p_w if x is not None]
    sv_vals = [x for x in p_sv if x is not None]
    era_vals = [x for x in p_era if x is not None]
    whip_vals = [x for x in p_whip if x is not None]

    total_ip = sum(ip_vals) if ip_vals else None
    total_k = sum(k_vals) if k_vals else None
    total_w = sum(w_vals) if w_vals else None
    total_sv = sum(sv_vals) if sv_vals else None
    med_era = median(era_vals)
    med_whip = median(whip_vals)

    # K per IP (rough “strikeout juice”)
    k_per_ip = (total_k / total_ip) if (total_k is not None and total_ip and total_ip > 0) else None

    # Quick heuristics for “team shape” (purely internal, not league-relative yet)
    hitter_notes = []
    if total_hr is not None and total_sb is not None:
        if total_hr >= 220 and total_sb < 80:
            hitter_notes.append("Power-leaning roster (HR-heavy). Consider one more speed specialist.")
        elif total_sb >= 120 and total_hr < 180:
            hitter_notes.append("Speed-leaning roster (SB-heavy). Consider one more reliable power bat.")
        else:
            hitter_notes.append("Balanced power/speed profile (good for weekly category flexibility).")
    if med_avg is not None:
        if med_avg < 0.245:
            hitter_notes.append("Batting average risk: several low-AVG profiles. Be careful streaming cold bats.")
        elif med_avg > 0.270:
            hitter_notes.append("Strong batting average foundation: you can take some power-only risks in waivers.")
        else:
            hitter_notes.append("Average looks workable; matchup-dependent optimization will matter more than roster shape.")

    pitcher_notes = []
    if total_sv is not None:
        if total_sv < 20:
            pitcher_notes.append("Saves look thin on paper. Plan for early season SV speculation adds.")
        elif total_sv >= 50:
            pitcher_notes.append("Saves strength. You can pivot waiver adds toward SP streaming or ratio stabilizers.")
        else:
            pitcher_notes.append("Saves are mid-pack; don’t ignore SV, but don’t overpay in waivers either.")
    if k_per_ip is not None:
        if k_per_ip >= 1.05:
            pitcher_notes.append("High strikeout density (K/IP). You’ll be able to hit weekly K targets without desperation streams.")
        elif k_per_ip <= 0.85:
            pitcher_notes.append("Lower strikeout density (K/IP). You may need more streamer volume to win Ks.")
        else:
            pitcher_notes.append("Average strikeout density. Weekly K plan should be opponent-dependent.")
    if med_era is not None and med_whip is not None:
        pitcher_notes.append(f"Median pitcher ratios (last season): ERA {fmt(med_era,2)}, WHIP {fmt(med_whip,2)} (medians, not weighted).")

    # Action items (preseason)
    actions = []
    if dtd:
        actions.append(f"Monitor DTD: " + ", ".join([p.full_name for p in dtd]))
    if il:
        actions.append(f"Monitor IL: " + ", ".join([p.full_name for p in il]))
    actions.append("Preseason: prioritize building a watchlist of (1) probable SP streamers, (2) speculative closers, (3) top-50 call-ups.")
    actions.append("Week 1: track IP pace daily to avoid scrambling for the 20 IP minimum.")
    actions.append("Before opening week: confirm your RP slots aren’t filled by SP-only arms (keep SV flexibility).")

    # Build report
    now = datetime.now(timezone.utc).astimezone()
    lines: List[str] = []
    lines.append(f"# Yahoo AI GM Report — Get a WHIFF of THIS!")
    lines.append(f"_Generated: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}_")
    lines.append("")
    lines.append("## Snapshot")
    lines.append(f"- Roster size: **{len(players)}** (Hitters: **{len(hitters)}**, Pitchers: **{len(pitchers)}**)")
    lines.append(f"- Flagged statuses: **{len(flagged)}** (DTD: **{len(dtd)}**, IL: **{len(il)}**)")
    lines.append("")
    if flagged:
        lines.append("### Status watch")
        for p in flagged:
            lines.append(f"- **{p.full_name}** — {p.status}")
        lines.append("")

    lines.append("## Roster construction")
    # Show key position coverage
    wanted = ["C", "1B", "2B", "3B", "SS", "OF", "UTIL", "SP", "RP", "P"]
    cov = []
    for pos in wanted:
        if pos in pos_counts:
            cov.append(f"{pos}:{pos_counts[pos]}")
    lines.append("- Eligible position coverage (count of players eligible): " + (", ".join(cov) if cov else "—"))
    lines.append("")

    lines.append("## Hitting profile (last season stats where available)")
    lines.append(f"- Total HR (sum): **{safe_int(total_hr)}**" if total_hr is not None else "- Total HR (sum): —")
    lines.append(f"- Total SB (sum): **{safe_int(total_sb)}**" if total_sb is not None else "- Total SB (sum): —")
    lines.append(f"- Median AVG: **{fmt(med_avg, 3)}**" if med_avg is not None else "- Median AVG: —")
    for n in hitter_notes:
        lines.append(f"- {n}")
    lines.append("")

    lines.append("## Pitching profile (last season stats where available)")
    lines.append(f"- Total IP (sum): **{fmt(total_ip, 1)}**" if total_ip is not None else "- Total IP (sum): —")
    lines.append(f"- Total K (sum): **{safe_int(total_k)}**" if total_k is not None else "- Total K (sum): —")
    lines.append(f"- K per IP: **{fmt(k_per_ip, 3)}**" if k_per_ip is not None else "- K per IP: —")
    lines.append(f"- Total W (sum): **{safe_int(total_w)}**" if total_w is not None else "- Total W (sum): —")
    lines.append(f"- Total SV (sum): **{safe_int(total_sv)}**" if total_sv is not None else "- Total SV (sum): —")
    for n in pitcher_notes:
        lines.append(f"- {n}")
    lines.append("")

    lines.append("## Preseason action items")
    for a in actions:
        lines.append(f"- {a}")
    lines.append("")

    lines.append("## Notes / next unlocks")
    lines.append("- Once Week 1 begins, we’ll switch from last-season stats to **live weekly scoreboard** and run category-pressure logic.")
    lines.append("- Next scripts to add:")
    lines.append("  - `pull_scoreboard_week.py` (your matchup totals by stat)")
    lines.append("  - `daily_lineup_reco.py` (start/sit based on who is playing + category needs)")
    lines.append("  - `streamers.py` (probable SP evaluation + ratio risk gating)")
    lines.append("")

    report = "\n".join(lines)
    REPORT_MD.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nSaved report -> {REPORT_MD}")


if __name__ == "__main__":
    main()
