"""
src/yahoo_ai_gm/analysis/matchup_engine.py

Layer 2 — Pure Analysis. No FastAPI, no I/O, no Yahoo client.

Matchup projection engine using FanGraphs 2026 Steamer projections.

Algorithm:
1. Build TeamProjection for my team and opponent from FG lookup
2. Compute per-category projected values for both teams
3. For each of 11 scoring categories: project win / loss / toss-up
4. Compute projected record and confidence per category
5. Identify swing categories (close enough to flip the matchup)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from yahoo_ai_gm.analysis.trade_engine import (
    PlayerProjection,
    TeamProjection,
    build_team_projection,
    build_fg_lookup,
    load_projections_from_fg,
    match_roster_to_fg,
    compute_league_averages,
    SCORING_CATS,
    LOWER_IS_BETTER,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CategoryMatchup:
    cat: str
    my_value: float
    opp_value: float
    delta: float            # my - opp (flipped for lower-is-better)
    delta_normalized: float # delta / league_stdev
    result: str             # "win" | "loss" | "toss-up"
    confidence: str         # "high" | "medium" | "low"
    is_swing: bool          # close enough that roster moves could flip it


@dataclass
class MatchupProjection:
    my_team_key: str
    my_team_name: str
    opp_team_key: str
    opp_team_name: str
    week: int

    categories: list[CategoryMatchup]

    projected_wins: int
    projected_losses: int
    projected_tossups: int

    swing_categories: list[str]      # categories we could flip with targeted adds
    my_unmatched: list[str]          # roster players missing from FG
    opp_unmatched: list[str]


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Normalized delta thresholds (delta / league_stdev)
TOSSUP_THRESHOLD = 0.15    # within 0.15 stdev = toss-up
SWING_THRESHOLD = 0.40     # within 0.40 stdev = swing category (waiver target opportunity)

CONFIDENCE_HIGH = 0.75
CONFIDENCE_MEDIUM = 0.30


# ---------------------------------------------------------------------------
# Core projection
# ---------------------------------------------------------------------------

def project_category_matchup(
    cat: str,
    my_val: float,
    opp_val: float,
    league_stdev: float,
) -> CategoryMatchup:
    raw_delta = my_val - opp_val
    if cat in LOWER_IS_BETTER:
        raw_delta = -raw_delta  # flip so positive = I win

    norm = raw_delta / league_stdev if league_stdev > 0 else 0.0

    if abs(norm) <= TOSSUP_THRESHOLD:
        result = "toss-up"
    elif norm > 0:
        result = "win"
    else:
        result = "loss"

    abs_norm = abs(norm)
    if abs_norm >= CONFIDENCE_HIGH:
        confidence = "high"
    elif abs_norm >= CONFIDENCE_MEDIUM:
        confidence = "medium"
    else:
        confidence = "low"

    is_swing = abs(norm) <= SWING_THRESHOLD

    return CategoryMatchup(
        cat=cat,
        my_value=round(my_val, 4),
        opp_value=round(opp_val, 4),
        delta=round(raw_delta, 4),
        delta_normalized=round(norm, 4),
        result=result,
        confidence=confidence,
        is_swing=is_swing,
    )


def project_matchup(
    my_roster: list[dict],
    opp_roster: list[dict],
    fg_bat_data: dict,
    fg_pit_data: dict,
    my_team_key: str,
    my_team_name: str,
    opp_team_key: str,
    opp_team_name: str,
    week: int,
    n_teams: int = 10,
) -> MatchupProjection:
    """
    Project head-to-head category matchup between my team and opponent.

    Args:
        my_roster: list of player dicts from roster_snapshot.json
        opp_roster: list of player dicts from league_rosters.json (opponent entry)
        fg_bat_data: loaded fg_proj_bat_2026.json
        fg_pit_data: loaded fg_proj_pit_2026.json
        my_team_key / opp_team_key: Yahoo team keys
        week: current matchup week
        n_teams: league size for league average computation
    """
    all_projections = load_projections_from_fg(fg_bat_data, fg_pit_data)
    fg_lookup = build_fg_lookup(all_projections)

    # Match both rosters
    my_matches = match_roster_to_fg(my_roster, fg_lookup)
    opp_matches = match_roster_to_fg(opp_roster, fg_lookup)

    my_proj = [p for p in my_matches.values() if p is not None]
    opp_proj = [p for p in opp_matches.values() if p is not None]

    my_unmatched = [n for n, p in my_matches.items() if p is None]
    opp_unmatched = [n for n, p in opp_matches.items() if p is None]

    my_team = build_team_projection(my_proj)
    opp_team = build_team_projection(opp_proj)

    league_avgs = compute_league_averages(all_projections, n_teams=n_teams)

    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    # Use K instead of SO in display (Yahoo uses K)
    cat_matchups = []
    wins = losses = tossups = 0
    swing_cats = []

    for cat in all_cats:
        my_val = my_team.cat_value(cat)
        opp_val = opp_team.cat_value(cat)
        _, stdev = league_avgs.get(cat, (0.0, 1.0))

        cm = project_category_matchup(cat, my_val, opp_val, stdev)
        cat_matchups.append(cm)

        if cm.result == "win":
            wins += 1
        elif cm.result == "loss":
            losses += 1
        else:
            tossups += 1

        if cm.is_swing:
            swing_cats.append(cat)

    return MatchupProjection(
        my_team_key=my_team_key,
        my_team_name=my_team_name,
        opp_team_key=opp_team_key,
        opp_team_name=opp_team_name,
        week=week,
        categories=cat_matchups,
        projected_wins=wins,
        projected_losses=losses,
        projected_tossups=tossups,
        swing_categories=swing_cats,
        my_unmatched=my_unmatched,
        opp_unmatched=opp_unmatched,
    )


def matchup_to_dict(mp: MatchupProjection) -> dict:
    return {
        "my_team": {"key": mp.my_team_key, "name": mp.my_team_name},
        "opp_team": {"key": mp.opp_team_key, "name": mp.opp_team_name},
        "week": mp.week,
        "projected_record": {
            "wins": mp.projected_wins,
            "losses": mp.projected_losses,
            "toss_ups": mp.projected_tossups,
        },
        "swing_categories": mp.swing_categories,
        "my_unmatched_players": mp.my_unmatched,
        "opp_unmatched_players": mp.opp_unmatched,
        "categories": [
            {
                "cat": cm.cat,
                "my_value": cm.my_value,
                "opp_value": cm.opp_value,
                "delta": cm.delta,
                "result": cm.result,
                "confidence": cm.confidence,
                "is_swing": cm.is_swing,
            }
            for cm in mp.categories
        ],
    }
