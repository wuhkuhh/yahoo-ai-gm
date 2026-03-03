"""
src/yahoo_ai_gm/analysis/standings_trajectory.py

Layer 2 — Pure Analysis.

Projects final standings for all 10 teams based on:
  - Current FG Steamer projections for all rostered players
  - Full remaining schedule from league_schedule.json
  - Per-week matchup simulation using project_matchup()

Output:
  - Projected W/L/T record for all 10 teams
  - Projected standings rank
  - Playoff probability (top 6 of 10)
  - Remaining schedule difficulty for my team
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from yahoo_ai_gm.analysis.trade_engine import (
    build_team_projection,
    build_fg_lookup,
    load_projections_from_fg,
    match_roster_to_fg,
    compute_league_averages,
    SCORING_CATS,
    LOWER_IS_BETTER,
    _normalize_name,
)
from yahoo_ai_gm.analysis.matchup_engine import project_category_matchup, TOSSUP_THRESHOLD


PLAYOFF_TEAMS = 6
REGULAR_SEASON_WEEKS = 23


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TeamStanding:
    team_key: str
    team_name: str
    projected_wins: int
    projected_losses: int
    projected_tossups: int
    projected_rank: int
    playoff_probability: float    # 0.0 - 1.0
    weeks_simulated: int
    category_win_rates: dict[str, float]   # cat -> fraction of weeks won
    strength_of_schedule: float   # avg opponent projected win total


@dataclass
class WeeklyMatchupResult:
    week: int
    my_team_key: str
    opp_team_key: str
    opp_team_name: str
    projected_wins: int
    projected_losses: int
    projected_tossups: int
    swing_categories: list[str]


@dataclass
class StandingsTrajectory:
    my_team_key: str
    my_team_name: str
    current_week: int
    my_standing: TeamStanding
    all_standings: list[TeamStanding]
    remaining_schedule: list[WeeklyMatchupResult]
    hardest_weeks: list[int]       # weeks with toughest projected opponents
    easiest_weeks: list[int]       # weeks with weakest projected opponents
    playoff_contenders: list[str]  # team names projected to make playoffs


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

def _project_week_matchup(
    team_a_proj,
    team_b_proj,
    league_averages: dict,
) -> tuple[int, int, int]:
    """Returns (a_wins, a_losses, a_tossups) for one matchup."""
    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    a_wins = a_losses = a_tossups = 0
    for cat in all_cats:
        _, stdev = league_averages.get(cat, (0.0, 1.0))
        cm = project_category_matchup(
            cat,
            team_a_proj.cat_value(cat),
            team_b_proj.cat_value(cat),
            stdev,
        )
        if cm.result == "win":
            a_wins += 1
        elif cm.result == "loss":
            a_losses += 1
        else:
            a_tossups += 1
    return a_wins, a_losses, a_tossups


def project_standings(
    my_team_key: str,
    league_rosters: list[dict],
    schedule: dict,         # week_str -> list of matchup dicts
    fg_bat_data: dict,
    fg_pit_data: dict,
    current_week: int = 1,
    n_teams: int = 10,
) -> StandingsTrajectory:
    """
    Project final standings for all teams.

    Args:
        my_team_key: e.g. "469.l.40206.t.6"
        league_rosters: from league_rosters.json teams list
        schedule: from league_schedule.json schedule dict
        fg_bat_data / fg_pit_data: loaded FG projection dicts
        current_week: first week to simulate from
        n_teams: league size
    """
    # Build projections for all teams
    all_projections = load_projections_from_fg(fg_bat_data, fg_pit_data)
    fg_lookup = build_fg_lookup(all_projections)
    league_averages = compute_league_averages(all_projections, n_teams=n_teams)

    team_proj_map: dict[str, object] = {}  # team_key -> TeamProjection
    team_name_map: dict[str, str] = {}

    for team in league_rosters:
        tkey = team["team_key"]
        tname = team["team_name"]
        team_name_map[tkey] = tname
        matches = match_roster_to_fg(team["players"], fg_lookup)
        projs = [p for p in matches.values() if p is not None]
        team_proj_map[tkey] = build_team_projection(projs)

    # Initialize record accumulators
    records: dict[str, dict] = {
        tkey: {"wins": 0, "losses": 0, "tossups": 0,
               "cat_wins": {c: 0 for c in SCORING_CATS["batting"] + SCORING_CATS["pitching"]},
               "weeks": 0}
        for tkey in team_proj_map
    }

    my_weekly_results: list[WeeklyMatchupResult] = []

    # Simulate each remaining week
    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    for week in range(current_week, REGULAR_SEASON_WEEKS + 1):
        week_matchups = schedule.get(str(week), [])
        for matchup in week_matchups:
            a_key = matchup["team_a"]["key"]
            b_key = matchup["team_b"]["key"]
            a_name = matchup["team_a"]["name"]
            b_name = matchup["team_b"]["name"]

            proj_a = team_proj_map.get(a_key)
            proj_b = team_proj_map.get(b_key)
            if proj_a is None or proj_b is None:
                continue

            a_wins, a_losses, a_tossups = _project_week_matchup(
                proj_a, proj_b, league_averages
            )

            # Accumulate for team A
            if a_key in records:
                records[a_key]["wins"]   += a_wins
                records[a_key]["losses"] += a_losses
                records[a_key]["tossups"]+= a_tossups
                records[a_key]["weeks"]  += 1
                for cat in all_cats:
                    _, stdev = league_averages.get(cat, (0.0, 1.0))
                    cm = project_category_matchup(
                        cat, proj_a.cat_value(cat), proj_b.cat_value(cat), stdev
                    )
                    if cm.result == "win":
                        records[a_key]["cat_wins"][cat] += 1

            # Accumulate for team B (inverse)
            if b_key in records:
                records[b_key]["wins"]   += a_losses
                records[b_key]["losses"] += a_wins
                records[b_key]["tossups"]+= a_tossups
                records[b_key]["weeks"]  += 1
                for cat in all_cats:
                    _, stdev = league_averages.get(cat, (0.0, 1.0))
                    cm = project_category_matchup(
                        cat, proj_b.cat_value(cat), proj_a.cat_value(cat), stdev
                    )
                    if cm.result == "win":
                        records[b_key]["cat_wins"][cat] += 1

            # Track my weekly results
            if a_key == my_team_key or b_key == my_team_key:
                is_a = a_key == my_team_key
                opp_key = b_key if is_a else a_key
                opp_name = b_name if is_a else a_name
                my_w = a_wins if is_a else a_losses
                my_l = a_losses if is_a else a_wins

                # Swing cats for my matchup
                swing_cats = []
                for cat in all_cats:
                    _, stdev = league_averages.get(cat, (0.0, 1.0))
                    if stdev == 0:
                        continue
                    my_val = (proj_a if is_a else proj_b).cat_value(cat)
                    opp_val = (proj_b if is_a else proj_a).cat_value(cat)
                    gap = abs(my_val - opp_val) / stdev
                    if gap < 0.40:
                        swing_cats.append(cat)

                my_weekly_results.append(WeeklyMatchupResult(
                    week=week,
                    my_team_key=my_team_key,
                    opp_team_key=opp_key,
                    opp_team_name=opp_name,
                    projected_wins=my_w,
                    projected_losses=my_l,
                    projected_tossups=a_tossups,
                    swing_categories=swing_cats,
                ))

    # Build standings
    standings_list = []
    for tkey, rec in records.items():
        weeks = max(rec["weeks"], 1)
        cat_win_rates = {
            cat: rec["cat_wins"][cat] / weeks
            for cat in all_cats
        }
        standings_list.append({
            "team_key": tkey,
            "team_name": team_name_map.get(tkey, tkey),
            "wins": rec["wins"],
            "losses": rec["losses"],
            "tossups": rec["tossups"],
            "weeks": weeks,
            "cat_win_rates": cat_win_rates,
        })

    # Sort by wins desc, losses asc
    standings_list.sort(key=lambda t: (-t["wins"], t["losses"]))

    # Compute strength of schedule for my team
    my_opp_wins = []
    for wr in my_weekly_results:
        opp_rec = records.get(wr.opp_team_key, {})
        my_opp_wins.append(opp_rec.get("wins", 0))
    sos = sum(my_opp_wins) / len(my_opp_wins) if my_opp_wins else 0.0

    # Build TeamStanding objects
    all_standings = []
    for rank, t in enumerate(standings_list, 1):
        weeks = max(t["weeks"], 1)
        playoff_prob = 1.0 if rank <= PLAYOFF_TEAMS else 0.0
        # For teams on the bubble (rank 5-7), use wins margin
        if rank in (5, 6, 7):
            boundary_wins = standings_list[PLAYOFF_TEAMS - 1]["wins"]
            my_wins = t["wins"]
            margin = my_wins - boundary_wins
            if margin == 0:
                playoff_prob = 0.5
            elif margin > 0:
                playoff_prob = min(1.0, 0.5 + margin / 20.0)
            else:
                playoff_prob = max(0.0, 0.5 + margin / 20.0)

        all_standings.append(TeamStanding(
            team_key=t["team_key"],
            team_name=t["team_name"],
            projected_wins=t["wins"],
            projected_losses=t["losses"],
            projected_tossups=t["tossups"],
            projected_rank=rank,
            playoff_probability=round(playoff_prob, 3),
            weeks_simulated=t["weeks"],
            category_win_rates=t["cat_win_rates"],
            strength_of_schedule=round(sos, 1) if t["team_key"] == my_team_key else 0.0,
        ))

    my_standing = next(s for s in all_standings if s.team_key == my_team_key)
    my_name = team_name_map.get(my_team_key, my_team_key)

    # Hardest/easiest weeks for my team
    sorted_by_opp = sorted(
        my_weekly_results,
        key=lambda w: records.get(w.opp_team_key, {}).get("wins", 0),
        reverse=True,
    )
    hardest_weeks = [w.week for w in sorted_by_opp[:3]]
    easiest_weeks = [w.week for w in sorted_by_opp[-3:]]

    playoff_contenders = [
        s.team_name for s in all_standings if s.projected_rank <= PLAYOFF_TEAMS
    ]

    return StandingsTrajectory(
        my_team_key=my_team_key,
        my_team_name=my_name,
        current_week=current_week,
        my_standing=my_standing,
        all_standings=all_standings,
        remaining_schedule=my_weekly_results,
        hardest_weeks=hardest_weeks,
        easiest_weeks=easiest_weeks,
        playoff_contenders=playoff_contenders,
    )


def standings_trajectory_to_dict(t: StandingsTrajectory) -> dict:
    return {
        "my_team": t.my_team_name,
        "current_week": t.current_week,
        "my_projected_record": {
            "wins": t.my_standing.projected_wins,
            "losses": t.my_standing.projected_losses,
            "tossups": t.my_standing.projected_tossups,
        },
        "my_projected_rank": t.my_standing.projected_rank,
        "playoff_probability": t.my_standing.playoff_probability,
        "strength_of_schedule": t.my_standing.strength_of_schedule,
        "hardest_weeks": t.hardest_weeks,
        "easiest_weeks": t.easiest_weeks,
        "playoff_contenders": t.playoff_contenders,
        "all_standings": [
            {
                "rank": s.projected_rank,
                "team": s.team_name,
                "wins": s.projected_wins,
                "losses": s.projected_losses,
                "tossups": s.projected_tossups,
                "playoff_probability": s.playoff_probability,
                "category_win_rates": {
                    k: round(v, 3) for k, v in s.category_win_rates.items()
                },
            }
            for s in t.all_standings
        ],
        "remaining_schedule": [
            {
                "week": w.week,
                "opponent": w.opp_team_name,
                "projected": f"{w.projected_wins}-{w.projected_losses}-{w.projected_tossups}",
                "swing_categories": w.swing_categories,
            }
            for w in t.remaining_schedule
        ],
    }
