"""
src/yahoo_ai_gm/analysis/streaming_sp.py

Layer 2 — Pure Analysis.

Streaming SP optimizer: ranks available SPs for weekly streaming.

Two-phase approach:
  Phase 1 (pre-season / no probable pitchers): rank by FG projected quality
  Phase 2 (in-season): augment with actual probable starts from MLB Stats API

Scoring factors:
  1. Projected quality: ERA, WHIP, K/9, FIP
  2. Starts this week: from MLB API probable pitchers (if available)
  3. Matchup opponent weakness: targets opponent's weak pitching categories
  4. Ownership %: lower owned = more available
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from yahoo_ai_gm.analysis.ratio_risk import _normalize_name
from yahoo_ai_gm.analysis.trade_engine import SCORING_CATS, LOWER_IS_BETTER


LEAGUE_AVG_ERA  = 4.20
LEAGUE_AVG_WHIP = 1.28
LEAGUE_AVG_K9   = 8.80
LEAGUE_AVG_FIP  = 4.25


@dataclass
class StreamingCandidate:
    name: str
    team: str
    player_key: str
    percent_owned: float
    projected_starts: int         # from MLB API or estimated from GS projection
    era: float
    whip: float
    k9: float
    fip: float
    ip_proj: float
    quality_score: float          # 0-10 composite
    streaming_score: float        # final ranking score
    cats_addressed: list[str]     # which opponent weaknesses this helps
    source: str                   # "mlb_api" | "fg_projection"


def _fetch_probable_starters(start_date: str, end_date: str) -> dict[str, int]:
    """
    Fetch probable starters from MLB Stats API.
    Returns {pitcher_name: start_count} for the date range.
    Falls back to empty dict if API unavailable.
    """
    import urllib.request, json
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&startDate={start_date}&endDate={end_date}"
        f"&hydrate=probablePitcher"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
    except Exception:
        return {}

    starts: dict[str, int] = {}
    for date in data.get("dates", []):
        for game in date.get("games", []):
            for side in ("away", "home"):
                pitcher = game.get("teams", {}).get(side, {}).get("probablePitcher", {})
                name = pitcher.get("fullName", "")
                if name and name != "TBD":
                    starts[name] = starts.get(name, 0) + 1
    return starts


def _estimate_weekly_starts(gs_proj: float, ip_proj: float) -> int:
    """
    Estimate starts in a typical 7-day week from season projections.
    Season = ~26 weeks of starts.
    """
    if gs_proj and gs_proj > 0:
        weekly = gs_proj / 26.0
        return max(1, round(weekly))
    elif ip_proj and ip_proj > 0:
        # ~6 IP per start -> estimate GS
        est_gs = ip_proj / 6.0
        return max(1, round(est_gs / 26.0))
    return 1


def _quality_score(era: float, whip: float, k9: float, fip: float) -> float:
    """
    Composite quality score 0-10.
    Higher = better streaming option.
    """
    era_score  = max(0.0, (LEAGUE_AVG_ERA  - era)  / 1.0 * 3.0 + 5.0)
    whip_score = max(0.0, (LEAGUE_AVG_WHIP - whip) / 0.2 * 3.0 + 5.0)
    k9_score   = max(0.0, (k9 - LEAGUE_AVG_K9)     / 2.0 * 2.0 + 5.0)
    fip_score  = max(0.0, (LEAGUE_AVG_FIP  - fip)  / 1.0 * 2.0 + 5.0)

    composite = (era_score * 0.30 + whip_score * 0.30 + k9_score * 0.25 + fip_score * 0.15)
    return round(min(10.0, max(0.0, composite)), 2)


def _cats_addressed(
    era: float, whip: float, k9: float,
    opp_weaknesses: list[str],
) -> list[str]:
    cats = []
    if "ERA"  in opp_weaknesses and era  < LEAGUE_AVG_ERA:   cats.append("ERA")
    if "WHIP" in opp_weaknesses and whip < LEAGUE_AVG_WHIP:  cats.append("WHIP")
    if "SO"   in opp_weaknesses and k9   > LEAGUE_AVG_K9:    cats.append("SO")
    if "W"    in opp_weaknesses:                             cats.append("W")
    if "IP"   in opp_weaknesses:                             cats.append("IP")
    return cats


def rank_streaming_candidates(
    pool_players: list[dict],
    fg_pit_data: dict,
    opp_weaknesses: list[str],
    week_start: str,
    week_end: str,
    max_owned_pct: float = 60.0,
    top_n: int = 10,
) -> list[StreamingCandidate]:
    """
    Rank available SP streamers for the current week.

    Args:
        pool_players: waiver pool players (dicts with name, player_key, percent_owned)
        fg_pit_data: FanGraphs pitcher projections
        opp_weaknesses: opponent weak categories (from opponent profile)
        week_start / week_end: ISO date strings for current week
        max_owned_pct: exclude players owned above this threshold
        top_n: number of candidates to return
    """
    # Build FG lookup
    fg_lookup: dict[str, dict] = {}
    for p in fg_pit_data.get("players", []):
        key = _normalize_name(p.get("PlayerName", ""))
        if key:
            fg_lookup[key] = p

    # Try MLB API for probable starters
    probable_starts = _fetch_probable_starters(week_start, week_end)
    has_live_starts = len(probable_starts) >= 10  # need meaningful coverage to trust API data

    candidates = []
    for player in pool_players:
        name      = player.get("name") or player.get("full_name", "")
        pkey      = player.get("player_key", "")
        owned_pct = float(player.get("percent_owned") or 0.0)
        positions = player.get("eligible_positions") or player.get("pos", "")
        if isinstance(positions, str):
            positions = [p.strip() for p in positions.split(",")]

        is_sp = "SP" in positions
        if not is_sp:
            continue
        if owned_pct > max_owned_pct:
            continue

        fg = fg_lookup.get(_normalize_name(name))
        if fg is None:
            continue

        era  = float(fg.get("ERA")  or LEAGUE_AVG_ERA)
        whip = float(fg.get("WHIP") or LEAGUE_AVG_WHIP)
        k9   = float(fg.get("K/9")  or LEAGUE_AVG_K9)
        fip  = float(fg.get("FIP")  or era)
        ip   = float(fg.get("IP")   or 0.0)
        gs   = float(fg.get("GS")   or 0.0)

        if ip < 10.0:
            continue  # not enough projection

        # Determine starts this week
        if has_live_starts:
            starts = probable_starts.get(name, 0)
            source = "mlb_api"
        else:
            starts = _estimate_weekly_starts(gs, ip)
            source = "fg_projection"

        if starts == 0 and not has_live_starts:
            starts = 1  # assume at least 1 start if projectable

        quality = _quality_score(era, whip, k9, fip)
        cats    = _cats_addressed(era, whip, k9, opp_weaknesses)

        # Final streaming score:
        # quality * starts * matchup bonus
        matchup_bonus = 1.0 + len(cats) * 0.15
        ownership_discount = max(0.3, 1.0 - owned_pct / 100.0)
        streaming_score = quality * starts * matchup_bonus * ownership_discount

        candidates.append(StreamingCandidate(
            name=name,
            team=fg.get("Team", ""),
            player_key=pkey,
            percent_owned=owned_pct,
            projected_starts=starts,
            era=round(era, 3),
            whip=round(whip, 3),
            k9=round(k9, 2),
            fip=round(fip, 3),
            ip_proj=round(ip, 1),
            quality_score=quality,
            streaming_score=round(streaming_score, 3),
            cats_addressed=cats,
            source=source,
        ))

    candidates.sort(key=lambda c: c.streaming_score, reverse=True)
    return candidates[:top_n]


def streaming_candidate_to_dict(c: StreamingCandidate) -> dict:
    return {
        "name": c.name,
        "team": c.team,
        "player_key": c.player_key,
        "percent_owned": c.percent_owned,
        "projected_starts": c.projected_starts,
        "quality_score": c.quality_score,
        "streaming_score": c.streaming_score,
        "cats_addressed": c.cats_addressed,
        "projections": {
            "ERA": c.era, "WHIP": c.whip,
            "K/9": c.k9, "FIP": c.fip, "IP": c.ip_proj,
        },
        "data_source": c.source,
    }
