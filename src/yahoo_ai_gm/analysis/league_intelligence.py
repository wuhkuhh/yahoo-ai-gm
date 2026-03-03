"""
src/yahoo_ai_gm/analysis/league_intelligence.py

Layer 2 — Pure Analysis.

Two related engines sharing all-teams projection infrastructure:

1. Roster Construction Score (0-100)
   Measures how well-balanced each team is across all 11 categories.
   Penalizes category black holes, rewards depth and balance.

2. Opponent Modeling
   Per-opponent profile: consistent strengths, weaknesses, category tendencies.
   Used to inform trade strategy and matchup preparation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from yahoo_ai_gm.analysis.trade_engine import (
    PlayerProjection,
    TeamProjection,
    build_team_projection,
    build_fg_lookup,
    load_projections_from_fg,
    match_roster_to_fg,
    compute_league_averages,
    score_team_categories,
    SCORING_CATS,
    LOWER_IS_BETTER,
    _normalize_name,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RosterConstructionScore:
    team_key: str
    team_name: str
    score: float            # 0-100
    grade: str              # A / B / C / D / F
    category_z_scores: dict[str, float]   # cat -> z-score vs league
    strengths: list[str]    # cats where z > 0.5
    weaknesses: list[str]   # cats where z < -0.5
    black_holes: list[str]  # cats where z < -1.5
    balance_penalty: float  # how much variance across cats hurts score
    depth_bonus: float      # bonus for having multiple contributors


@dataclass
class OpponentProfile:
    team_key: str
    team_name: str
    projected_rank: int
    category_z_scores: dict[str, float]
    consistent_strengths: list[str]   # z > 0.4
    consistent_weaknesses: list[str]  # z < -0.4
    punt_categories: list[str]        # z < -1.2 — likely punting
    elite_categories: list[str]       # z > 1.2 — dominant
    trade_motivations: list[str]      # what they need
    construction_score: float
    construction_grade: str


# ---------------------------------------------------------------------------
# Roster construction scoring
# ---------------------------------------------------------------------------

def _grade(score: float) -> str:
    if score >= 85:  return "A"
    elif score >= 70: return "B"
    elif score >= 55: return "C"
    elif score >= 40: return "D"
    return "F"


def compute_construction_score(
    team_key: str,
    team_name: str,
    team_proj: TeamProjection,
    league_averages: dict,
) -> RosterConstructionScore:
    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    cat_scores = score_team_categories(team_proj, league_averages)
    z_map = {cs.cat: cs.z_score for cs in cat_scores}

    strengths   = [c for c, z in z_map.items() if z >  0.5]
    weaknesses  = [c for c, z in z_map.items() if z < -0.5]
    black_holes = [c for c, z in z_map.items() if z < -1.5]

    # Base score: mean z-score normalized to 0-100
    mean_z = sum(z_map.values()) / len(z_map) if z_map else 0.0
    base = 50.0 + mean_z * 15.0

    # Balance penalty: std dev of z-scores (high variance = unbalanced)
    z_vals = list(z_map.values())
    variance = sum((z - mean_z) ** 2 for z in z_vals) / len(z_vals) if z_vals else 0.0
    std_dev = math.sqrt(variance)
    balance_penalty = std_dev * 5.0

    # Black hole penalty
    black_hole_penalty = len(black_holes) * 4.0

    # Depth bonus: number of categories above +0.5
    depth_bonus = len(strengths) * 1.5

    score = base + depth_bonus - balance_penalty - black_hole_penalty
    score = round(max(0.0, min(100.0, score)), 1)

    return RosterConstructionScore(
        team_key=team_key,
        team_name=team_name,
        score=score,
        grade=_grade(score),
        category_z_scores={c: round(z, 3) for c, z in z_map.items()},
        strengths=strengths,
        weaknesses=weaknesses,
        black_holes=black_holes,
        balance_penalty=round(balance_penalty, 2),
        depth_bonus=round(depth_bonus, 2),
    )


# ---------------------------------------------------------------------------
# Opponent modeling
# ---------------------------------------------------------------------------

def build_opponent_profile(
    team_key: str,
    team_name: str,
    projected_rank: int,
    team_proj: TeamProjection,
    league_averages: dict,
) -> OpponentProfile:
    construction = compute_construction_score(
        team_key, team_name, team_proj, league_averages
    )
    z_map = construction.category_z_scores

    consistent_strengths  = [c for c, z in z_map.items() if z >  0.4]
    consistent_weaknesses = [c for c, z in z_map.items() if z < -0.4]
    punt_cats  = [c for c, z in z_map.items() if z < -1.2]
    elite_cats = [c for c, z in z_map.items() if z >  1.2]

    # Trade motivations: categories they're weakest in that aren't punts
    trade_motivations = [
        c for c, z in sorted(z_map.items(), key=lambda x: x[1])
        if -1.2 < z < -0.3
    ][:3]

    return OpponentProfile(
        team_key=team_key,
        team_name=team_name,
        projected_rank=projected_rank,
        category_z_scores=z_map,
        consistent_strengths=consistent_strengths,
        consistent_weaknesses=consistent_weaknesses,
        punt_categories=punt_cats,
        elite_categories=elite_cats,
        trade_motivations=trade_motivations,
        construction_score=construction.score,
        construction_grade=construction.grade,
    )


# ---------------------------------------------------------------------------
# League-wide analysis
# ---------------------------------------------------------------------------

def compute_league_intelligence(
    my_team_key: str,
    league_rosters: list[dict],
    fg_bat_data: dict,
    fg_pit_data: dict,
    rank_map: dict[str, int],
    n_teams: int = 10,
) -> tuple[list[RosterConstructionScore], list[OpponentProfile]]:
    """
    Compute roster construction scores and opponent profiles for all teams.

    Returns:
        (construction_scores sorted by score desc,
         opponent_profiles sorted by rank asc)
    """
    all_projections = load_projections_from_fg(fg_bat_data, fg_pit_data)
    fg_lookup = build_fg_lookup(all_projections)
    league_averages = compute_league_averages(all_projections, n_teams=n_teams)

    construction_scores = []
    opponent_profiles = []

    for team in league_rosters:
        tkey  = team["team_key"]
        tname = team["team_name"]
        rank  = rank_map.get(tkey, 5)

        matches = match_roster_to_fg(team["players"], fg_lookup)
        projs   = [p for p in matches.values() if p is not None]
        tproj   = build_team_projection(projs)

        cs = compute_construction_score(tkey, tname, tproj, league_averages)
        construction_scores.append(cs)

        if tkey != my_team_key:
            profile = build_opponent_profile(tkey, tname, rank, tproj, league_averages)
            opponent_profiles.append(profile)

    construction_scores.sort(key=lambda s: s.score, reverse=True)
    opponent_profiles.sort(key=lambda p: p.projected_rank)

    return construction_scores, opponent_profiles


def construction_score_to_dict(cs: RosterConstructionScore) -> dict:
    return {
        "team": cs.team_name,
        "score": cs.score,
        "grade": cs.grade,
        "strengths": cs.strengths,
        "weaknesses": cs.weaknesses,
        "black_holes": cs.black_holes,
        "category_z_scores": cs.category_z_scores,
    }


def opponent_profile_to_dict(p: OpponentProfile) -> dict:
    return {
        "team": p.team_name,
        "rank": p.projected_rank,
        "construction_score": p.construction_score,
        "construction_grade": p.construction_grade,
        "elite_categories": p.elite_categories,
        "consistent_strengths": p.consistent_strengths,
        "consistent_weaknesses": p.consistent_weaknesses,
        "punt_categories": p.punt_categories,
        "trade_motivations": p.trade_motivations,
        "category_z_scores": p.category_z_scores,
    }
