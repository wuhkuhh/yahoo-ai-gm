"""
src/yahoo_ai_gm/analysis/multi_trade_engine.py

Layer 2 — Pure Analysis. No FastAPI, no I/O, no Yahoo client.

Multi-player trade engine supporting 2-for-1, 1-for-2, and 2-for-2 trades.

Scoring:
  1. Net category delta (z-score normalized, need-weighted)
  2. Position fit multiplier (penalize trades that create roster holes)

Combinatorial limits (pre-filtering):
  - Give candidates: my roster players with ADP < 350
  - Receive candidates: top 40 ADP per opposing team
  - 2-for-2 capped at top give/receive pairs by individual score
"""
from __future__ import annotations

import itertools
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
    score_team_categories,
    SCORING_CATS,
    LOWER_IS_BETTER,
    _normalize_name,
)


# ---------------------------------------------------------------------------
# Position fit scoring
# ---------------------------------------------------------------------------

# Positions that are hard to fill (scarce on roster)
SCARCE_POSITIONS = {"C", "SS", "2B", "SP", "RP"}
POSITION_HOLE_PENALTY = 0.7   # multiply score by this if trade creates a hole


def _eligible_positions(player_dict: dict) -> list[str]:
    """Extract eligible positions from either roster format."""
    ep = player_dict.get("eligible_positions")
    if isinstance(ep, list):
        return ep
    dp = player_dict.get("display_position") or player_dict.get("selected_position") or ""
    return [p.strip() for p in dp.replace(",", "/").split("/") if p.strip()]


def _position_fit_multiplier(
    my_roster: list[dict],
    give_players: list[dict],
    receive_players: list[dict],
) -> float:
    """
    Returns a multiplier 0.5–1.0 based on position fit.
    Penalizes trades that leave us with holes at scarce positions.
    """
    # Build position coverage after trade
    remaining = [p for p in my_roster if p not in give_players]
    for p in receive_players:
        remaining.append(p)

    # Count coverage per scarce position
    coverage: dict[str, int] = {pos: 0 for pos in SCARCE_POSITIONS}
    for p in remaining:
        for pos in _eligible_positions(p):
            if pos in coverage:
                coverage[pos] += 1

    # Check what we had before
    original: dict[str, int] = {pos: 0 for pos in SCARCE_POSITIONS}
    for p in my_roster:
        for pos in _eligible_positions(p):
            if pos in original:
                original[pos] += 1

    # Penalize for each scarce position where we lose coverage
    multiplier = 1.0
    for pos in SCARCE_POSITIONS:
        before = original.get(pos, 0)
        after = coverage.get(pos, 0)
        if before > 0 and after < before and after == 0:
            multiplier *= POSITION_HOLE_PENALTY

    return max(0.3, multiplier)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MultiTradeSuggestion:
    give_players: list[PlayerProjection]
    receive_players: list[PlayerProjection]
    give_team: str               # opposing team name
    trade_size: str              # "2for1" | "1for2" | "2for2"
    cat_score: float             # raw category score
    position_multiplier: float   # position fit multiplier
    trade_score: float           # cat_score * position_multiplier
    cats_improved: list[str]
    cats_hurt: list[str]
    cat_impacts: dict[str, float]
    rationale: str


def multi_trade_suggestion_to_dict(s: MultiTradeSuggestion) -> dict:
    return {
        "trade_size": s.trade_size,
        "give_team": s.give_team,
        "give_players": [
            {"name": p.name, "team": p.team, "type": p.player_type, "adp": round(p.adp, 1)}
            for p in s.give_players
        ],
        "receive_players": [
            {"name": p.name, "team": p.team, "type": p.player_type, "adp": round(p.adp, 1)}
            for p in s.receive_players
        ],
        "trade_score": round(s.trade_score, 3),
        "cat_score": round(s.cat_score, 3),
        "position_multiplier": round(s.position_multiplier, 3),
        "cats_improved": s.cats_improved,
        "cats_hurt": s.cats_hurt,
        "cat_impacts": {k: round(v, 5 if k in ("AVG", "ERA", "WHIP") else 3) for k, v in s.cat_impacts.items()},
        "rationale": s.rationale,
    }


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def _score_trade(
    give_projs: list[PlayerProjection],
    receive_projs: list[PlayerProjection],
    my_team: TeamProjection,
    cat_score_map: dict,
    league_averages: dict,
) -> tuple[float, list[str], list[str], dict[str, float]]:
    """
    Score a give/receive group. Returns (score, cats_improved, cats_hurt, cat_impacts).
    """
    # Simulate team after trade
    remaining = [p for p in my_team.players if p.name not in {g.name for g in give_projs}]
    new_players = remaining + receive_projs
    new_team = build_team_projection(new_players)

    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    cats_improved = []
    cats_hurt = []
    cat_impacts = {}
    score = 0.0

    for cat in all_cats:
        old_val = my_team.cat_value(cat)
        new_val = new_team.cat_value(cat)
        delta = new_val - old_val
        if cat in LOWER_IS_BETTER:
            delta = -delta

        cat_impacts[cat] = delta

        cs = cat_score_map.get(cat)
        if cs is None:
            continue

        league_stdev = cs.league_stdev if cs.league_stdev > 0 else 1.0
        net_normalized = delta / league_stdev
        need_weight = max(0.0, -cs.z_score)
        surplus_weight = max(0.0, cs.z_score)

        if net_normalized > 0.02:
            cats_improved.append(cat)
            score += net_normalized * (1.0 + need_weight)
        elif net_normalized < -0.02:
            cats_hurt.append(cat)
            score -= abs(net_normalized) * (1.0 + surplus_weight)

    return score, cats_improved, cats_hurt, cat_impacts


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

def multi_trade_suggestions(
    my_roster: list[dict],
    league_rosters: list[dict],
    fg_bat_data: dict,
    fg_pit_data: dict,
    n_suggestions: int = 10,
    n_teams: int = 10,
    max_give_adp: float = 350.0,
    max_receive_adp: float = 300.0,
    top_receive_per_team: int = 40,
) -> dict[str, list[MultiTradeSuggestion]]:
    """
    Generate multi-player trade suggestions.

    Returns dict keyed by trade size: {"2for1": [...], "1for2": [...], "2for2": [...]}
    """
    # Load projections
    all_projections = load_projections_from_fg(fg_bat_data, fg_pit_data)
    fg_lookup = build_fg_lookup(all_projections)

    # Match my roster
    my_matches = match_roster_to_fg(my_roster, fg_lookup)
    my_projs = [p for p in my_matches.values() if p is not None]
    my_team = build_team_projection(my_projs)

    # League averages and category scores
    league_averages = compute_league_averages(all_projections, n_teams=n_teams)
    cat_scores = score_team_categories(my_team, league_averages)
    cat_score_map = {cs.cat: cs for cs in cat_scores}

    # My give candidates
    give_candidates = [p for p in my_projs if p.adp <= max_give_adp]

    # Build receive pool from all other teams
    # {team_name: [PlayerProjection, ...]}
    my_name_set = {_normalize_name(p.name) for p in my_projs}
    team_receive_pools: list[tuple[str, list[PlayerProjection]]] = []

    for team in league_rosters:
        tname = team["team_name"]
        tplayers = team["players"]
        matches = match_roster_to_fg(tplayers, fg_lookup)
        projs = [p for p in matches.values() if p is not None
                 and _normalize_name(p.name) not in my_name_set
                 and p.adp <= max_receive_adp]
        projs.sort(key=lambda p: p.adp)
        projs = projs[:top_receive_per_team]
        if projs:
            team_receive_pools.append((tname, projs))

    # Flatten receive pool with team attribution
    all_receive: list[tuple[str, PlayerProjection]] = []
    for tname, projs in team_receive_pools:
        for p in projs:
            all_receive.append((tname, p))

    results: dict[str, list[MultiTradeSuggestion]] = {
        "2for1": [], "1for2": [], "2for2": []
    }

    # ── 2-for-1 ──────────────────────────────────────────────────────────
    for give_pair in itertools.combinations(give_candidates, 2):
        for tname, receive in all_receive:
            # Skip if receive player is same as one being given
            if receive.name in {g.name for g in give_pair}:
                continue

            score, improved, hurt, impacts = _score_trade(
                list(give_pair), [receive], my_team, cat_score_map, league_averages
            )
            if score <= 0:
                continue

            pos_mult = _position_fit_multiplier(
                my_roster,
                [p for p in my_roster if any(
                    _normalize_name(p.get("name") or p.get("full_name","")) == _normalize_name(g.name)
                    for g in give_pair
                )],
                [],
            )
            final_score = score * pos_mult

            give_names = " + ".join(g.name for g in give_pair)
            rationale = (f"Give {give_names}, receive {receive.name} from {tname}. "
                        f"Improves: {', '.join(improved)}.")
            if hurt:
                rationale += f" Costs: {', '.join(hurt)}."

            results["2for1"].append(MultiTradeSuggestion(
                give_players=list(give_pair),
                receive_players=[receive],
                give_team=tname,
                trade_size="2for1",
                cat_score=score,
                position_multiplier=pos_mult,
                trade_score=final_score,
                cats_improved=improved,
                cats_hurt=hurt,
                cat_impacts=impacts,
                rationale=rationale,
            ))

    # ── 1-for-2 ──────────────────────────────────────────────────────────
    # Group receive by team for 1-for-2 (both receive from same team)
    for tname, team_projs in team_receive_pools:
        for give in give_candidates:
            for receive_pair in itertools.combinations(team_projs, 2):
                if give.name in {r.name for r in receive_pair}:
                    continue

                score, improved, hurt, impacts = _score_trade(
                    [give], list(receive_pair), my_team, cat_score_map, league_averages
                )
                if score <= 0:
                    continue

                pos_mult = _position_fit_multiplier(
                    my_roster,
                    [p for p in my_roster if _normalize_name(
                        p.get("name") or p.get("full_name","")) == _normalize_name(give.name)],
                    [],
                )
                final_score = score * pos_mult

                recv_names = " + ".join(r.name for r in receive_pair)
                rationale = (f"Give {give.name}, receive {recv_names} from {tname}. "
                            f"Improves: {', '.join(improved)}.")
                if hurt:
                    rationale += f" Costs: {', '.join(hurt)}."

                results["1for2"].append(MultiTradeSuggestion(
                    give_players=[give],
                    receive_players=list(receive_pair),
                    give_team=tname,
                    trade_size="1for2",
                    cat_score=score,
                    position_multiplier=pos_mult,
                    trade_score=final_score,
                    cats_improved=improved,
                    cats_hurt=hurt,
                    cat_impacts=impacts,
                    rationale=rationale,
                ))

    # ── 2-for-2 ──────────────────────────────────────────────────────────
    # Pre-filter: only top 10 give pairs and top 10 receive pairs per team
    # to keep combinatorics manageable
    top_give_pairs = sorted(
        itertools.combinations(give_candidates, 2),
        key=lambda pair: pair[0].adp + pair[1].adp
    )[:15]

    for tname, team_projs in team_receive_pools:
        top_recv_pairs = list(itertools.combinations(team_projs[:12], 2))
        for give_pair in top_give_pairs:
            for receive_pair in top_recv_pairs:
                give_names_set = {g.name for g in give_pair}
                if any(r.name in give_names_set for r in receive_pair):
                    continue

                score, improved, hurt, impacts = _score_trade(
                    list(give_pair), list(receive_pair),
                    my_team, cat_score_map, league_averages
                )
                if score <= 0:
                    continue

                pos_mult = _position_fit_multiplier(my_roster, [], [])
                final_score = score * pos_mult

                give_str = " + ".join(g.name for g in give_pair)
                recv_str = " + ".join(r.name for r in receive_pair)
                rationale = (f"Give {give_str}, receive {recv_str} from {tname}. "
                            f"Improves: {', '.join(improved)}.")
                if hurt:
                    rationale += f" Costs: {', '.join(hurt)}."

                results["2for2"].append(MultiTradeSuggestion(
                    give_players=list(give_pair),
                    receive_players=list(receive_pair),
                    give_team=tname,
                    trade_size="2for2",
                    cat_score=score,
                    position_multiplier=pos_mult,
                    trade_score=final_score,
                    cats_improved=improved,
                    cats_hurt=hurt,
                    cat_impacts=impacts,
                    rationale=rationale,
                ))

    # Sort and cap each bucket
    for size in results:
        results[size].sort(key=lambda s: s.trade_score, reverse=True)
        # Deduplicate: max 2 suggestions per give player set
        seen: dict[str, int] = {}
        deduped = []
        for s in results[size]:
            key = "+".join(sorted(p.name for p in s.give_players))
            if seen.get(key, 0) < 2:
                deduped.append(s)
                seen[key] = seen.get(key, 0) + 1
            if len(deduped) >= n_suggestions:
                break
        results[size] = deduped

    return results
