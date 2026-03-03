"""
src/yahoo_ai_gm/analysis/trade_acceptance.py

Layer 2 — Pure Analysis.

Models likelihood that an opponent manager would accept a proposed trade.

Factors:
  1. Need score — does our give player address their category weaknesses?
  2. Redundancy score — is our receive player redundant on their roster?
  3. Playoff motivation — bubble teams more willing to deal
  4. Trade balance — is the trade fair enough they won't feel exploited?
  5. Desperation — out-of-contention teams more likely to shake things up

Output: acceptance_probability (0.0-1.0) + reasoning
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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
from yahoo_ai_gm.analysis.matchup_engine import project_category_matchup


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLAYOFF_TEAMS = 6

# How much each factor contributes to acceptance probability
W_NEED         = 0.35   # does our give player help them?
W_REDUNDANCY   = 0.20   # is their give player redundant?
W_MOTIVATION   = 0.20   # how motivated are they to trade?
W_BALANCE      = 0.15   # is the trade fair?
W_DESPERATION  = 0.10   # are they out of contention?


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeAcceptanceResult:
    opp_team_key: str
    opp_team_name: str
    opp_rank: int
    give_players: list[str]      # names we give
    receive_players: list[str]   # names we receive
    acceptance_probability: float
    need_score: float
    redundancy_score: float
    motivation_score: float
    balance_score: float
    desperation_score: float
    reasoning: list[str]
    verdict: str   # "LIKELY" | "POSSIBLE" | "UNLIKELY" | "VERY_UNLIKELY"


# ---------------------------------------------------------------------------
# Factor computation
# ---------------------------------------------------------------------------

def _need_score(
    give_projs: list[PlayerProjection],
    opp_team: TeamProjection,
    league_averages: dict,
    n_teams: int,
) -> tuple[float, list[str]]:
    """
    How much do our give players address the opponent's weaknesses?
    Returns (score 0-1, list of categories addressed)
    """
    from yahoo_ai_gm.analysis.trade_engine import score_team_categories
    opp_cat_scores = score_team_categories(opp_team, league_averages)
    opp_needs = {cs.cat: cs.z_score for cs in opp_cat_scores if cs.z_score < -0.3}

    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    cats_addressed = []
    total_need = sum(abs(v) for v in opp_needs.values()) or 1.0
    need_met = 0.0

    for give in give_projs:
        # Simulate adding give player to opponent
        new_players = opp_team.players + [give]
        new_team = build_team_projection(new_players)
        for cat, z in opp_needs.items():
            old_val = opp_team.cat_value(cat)
            new_val = new_team.cat_value(cat)
            delta = new_val - old_val
            if cat in LOWER_IS_BETTER:
                delta = -delta
            _, stdev = league_averages.get(cat, (0.0, 1.0))
            if stdev > 0 and delta / stdev > 0.1:
                need_met += abs(z)
                if cat not in cats_addressed:
                    cats_addressed.append(cat)

    score = min(1.0, need_met / total_need)
    return round(score, 3), cats_addressed


def _redundancy_score(
    receive_projs: list[PlayerProjection],
    opp_roster: list[dict],
) -> tuple[float, list[str]]:
    """
    How redundant are our receive players on their roster?
    Returns (score 0-1, list of redundant positions)
    """
    from yahoo_ai_gm.analysis.adddrop_engine import _player_eligible_positions

    redundant_positions = []
    score = 0.0

    for recv in receive_projs:
        recv_type = recv.player_type  # "batter" or "pitcher"
        # Count how many of same type on their roster
        same_type = [
            p for p in opp_roster
            if (recv_type == "pitcher" and any(
                pos in ("SP", "RP", "P")
                for pos in _player_eligible_positions(p)
            )) or (recv_type == "batter" and not any(
                pos in ("SP", "RP", "P")
                for pos in _player_eligible_positions(p)
            ))
        ]
        # If they have more than 12 of same type, likely redundant
        if recv_type == "batter" and len(same_type) > 11:
            score += 0.4
            redundant_positions.append(f"excess {recv_type}s")
        elif recv_type == "pitcher" and len(same_type) > 9:
            score += 0.4
            redundant_positions.append(f"excess {recv_type}s")

        # Check ADP — low ADP players are less valuable, easier to give up
        if recv.adp > 250:
            score += 0.3
            redundant_positions.append(f"{recv.name} low ADP ({recv.adp:.0f})")

    return round(min(1.0, score / max(len(receive_projs), 1)), 3), redundant_positions


def _motivation_score(opp_rank: int, n_teams: int) -> tuple[float, str]:
    """
    Playoff motivation. Bubble teams trade most aggressively.
    Returns (score 0-1, description)
    """
    if opp_rank <= 2:
        return 0.2, "dominant team, cautious about trades"
    elif opp_rank <= 4:
        return 0.4, "safely in playoffs, selective"
    elif opp_rank <= 6:
        return 0.8, "on the playoff bubble, motivated to deal"
    elif opp_rank <= 8:
        return 0.6, "out of contention, open to shaking things up"
    else:
        return 0.4, "far out of contention, may not engage"


def _balance_score(
    give_projs: list[PlayerProjection],
    receive_projs: list[PlayerProjection],
    my_team: TeamProjection,
    opp_team: TeamProjection,
    league_averages: dict,
) -> tuple[float, str]:
    """
    Is the trade fair? Score how balanced it is from opponent's perspective.
    Returns (score 0-1, description)
    """
    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]

    # My team after trade
    my_give_names = {g.name for g in give_projs}
    my_new = build_team_projection(
        [p for p in my_team.players if p.name not in my_give_names] + receive_projs
    )

    # Their team after trade
    opp_recv_names = {r.name for r in receive_projs}
    opp_new = build_team_projection(
        [p for p in opp_team.players if p.name not in opp_recv_names] + give_projs
    )

    # Count wins for each team in head-to-head after trade
    my_wins = 0
    for cat in all_cats:
        _, stdev = league_averages.get(cat, (0.0, 1.0))
        cm = project_category_matchup(
            cat, my_new.cat_value(cat), opp_new.cat_value(cat), stdev
        )
        if cm.result == "win":
            my_wins += 1

    # If I win 8+ of 11 cats after trade, it's probably too lopsided
    balance = my_wins / len(all_cats)
    if balance <= 0.45:
        return 0.9, "trade favors them slightly"
    elif balance <= 0.55:
        return 0.7, "roughly balanced trade"
    elif balance <= 0.65:
        return 0.4, "trade favors us somewhat"
    else:
        return 0.1, "trade heavily favors us — they likely reject"


def _desperation_score(opp_rank: int, n_teams: int) -> tuple[float, str]:
    """Teams far out of contention may accept almost anything to change their situation."""
    if opp_rank >= n_teams - 1:
        return 0.7, "last place, desperate for change"
    elif opp_rank >= n_teams - 3:
        return 0.5, "out of contention"
    return 0.1, "not desperate"


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def compute_acceptance_probability(
    give_projs: list[PlayerProjection],
    receive_projs: list[PlayerProjection],
    my_team: TeamProjection,
    opp_team: TeamProjection,
    opp_roster: list[dict],
    opp_team_key: str,
    opp_team_name: str,
    opp_rank: int,
    league_averages: dict,
    n_teams: int = 10,
) -> TradeAcceptanceResult:

    need_s, cats_addressed = _need_score(give_projs, opp_team, league_averages, n_teams)
    redund_s, redund_pos   = _redundancy_score(receive_projs, opp_roster)
    motiv_s, motiv_desc    = _motivation_score(opp_rank, n_teams)
    balance_s, balance_desc = _balance_score(
        give_projs, receive_projs, my_team, opp_team, league_averages
    )
    desp_s, desp_desc      = _desperation_score(opp_rank, n_teams)

    prob = (
        need_s    * W_NEED +
        redund_s  * W_REDUNDANCY +
        motiv_s   * W_MOTIVATION +
        balance_s * W_BALANCE +
        desp_s    * W_DESPERATION
    )
    prob = round(min(1.0, max(0.0, prob)), 3)

    if prob >= 0.65:
        verdict = "LIKELY"
    elif prob >= 0.45:
        verdict = "POSSIBLE"
    elif prob >= 0.25:
        verdict = "UNLIKELY"
    else:
        verdict = "VERY_UNLIKELY"

    reasoning = []
    if cats_addressed:
        reasoning.append(f"Addresses their needs in: {', '.join(cats_addressed)}")
    if redund_pos:
        reasoning.append(f"Redundancy on their roster: {', '.join(redund_pos)}")
    reasoning.append(f"Motivation: {motiv_desc}")
    reasoning.append(f"Balance: {balance_desc}")
    if desp_s > 0.3:
        reasoning.append(f"Desperation factor: {desp_desc}")

    return TradeAcceptanceResult(
        opp_team_key=opp_team_key,
        opp_team_name=opp_team_name,
        opp_rank=opp_rank,
        give_players=[p.name for p in give_projs],
        receive_players=[p.name for p in receive_projs],
        acceptance_probability=prob,
        need_score=need_s,
        redundancy_score=redund_s,
        motivation_score=motiv_s,
        balance_score=balance_s,
        desperation_score=desp_s,
        reasoning=reasoning,
        verdict=verdict,
    )


def acceptance_result_to_dict(r: TradeAcceptanceResult) -> dict:
    return {
        "opponent": r.opp_team_name,
        "opponent_rank": r.opp_rank,
        "give": r.give_players,
        "receive": r.receive_players,
        "acceptance_probability": r.acceptance_probability,
        "verdict": r.verdict,
        "factors": {
            "need_score": r.need_score,
            "redundancy_score": r.redundancy_score,
            "motivation_score": r.motivation_score,
            "balance_score": r.balance_score,
            "desperation_score": r.desperation_score,
        },
        "reasoning": r.reasoning,
    }
