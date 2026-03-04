"""
src/yahoo_ai_gm/analysis/adddrop_engine.py

Layer 2 — Pure Analysis. No FastAPI, no I/O, no Yahoo client.

Add/drop simulation engine.

Models up to max_moves sequential add/drop decisions, each time:
  1. Identifying which categories we are losing or tossing vs current opponent
  2. Finding the best available add that improves those categories
  3. Finding the best drop that doesn't create a position hole
  4. Applying the move and recomputing team state

Output: ordered move sequence with per-move and cumulative category impact.
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
    score_team_categories,
    SCORING_CATS,
    LOWER_IS_BETTER,
    _normalize_name,
)
from yahoo_ai_gm.analysis.matchup_engine import (
    project_category_matchup,
    TOSSUP_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Position constraint helpers
# ---------------------------------------------------------------------------

POSITION_GROUPS = {
    "C":  ["C"],
    "1B": ["1B"],
    "2B": ["2B"],
    "3B": ["3B"],
    "SS": ["SS"],
    "OF": ["OF", "LF", "CF", "RF"],
    "SP": ["SP"],
    "RP": ["RP"],
}

# Positions where losing last eligible player is a hard constraint
UNIQUE_POSITIONS = {"C", "2B", "SS"}


def _player_eligible_positions(player_dict: dict) -> list[str]:
    ep = player_dict.get("eligible_positions")
    if isinstance(ep, list):
        return [p.strip() for p in ep if p.strip()]
    dp = player_dict.get("display_position") or player_dict.get("selected_position") or ""
    return [p.strip() for p in dp.replace(",", "/").split("/") if p.strip()]


def _can_drop(player_dict: dict, roster: list[dict]) -> bool:
    """
    Returns True if dropping this player leaves at least one other player
    eligible at each of this player's unique positions.
    """
    positions = _player_eligible_positions(player_dict)
    player_name = player_dict.get("name") or player_dict.get("full_name", "")

    for pos in positions:
        if pos not in UNIQUE_POSITIONS:
            continue
        # Count other roster players eligible at this position
        others = [
            p for p in roster
            if (p.get("name") or p.get("full_name", "")) != player_name
            and pos in _player_eligible_positions(p)
        ]
        if len(others) == 0:
            return False
    return True


def _can_add(pool_player_dict: dict, roster: list[dict]) -> bool:
    """
    Basic check: pool player has at least one eligible position
    that exists on the roster (i.e. we have a slot for them).
    Always True for our purposes — we'll drop to make room.
    """
    return bool(_player_eligible_positions(pool_player_dict))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AddDropMove:
    move_number: int
    add_name: str
    add_player_key: str
    add_type: str               # "batter" | "pitcher"
    drop_name: str
    drop_player_key: str
    drop_type: str
    cats_improved: list[str]
    cats_hurt: list[str]
    cat_deltas: dict[str, float]
    move_score: float
    rationale: str


@dataclass
class AddDropPlan:
    moves: list[AddDropMove]
    cumulative_cats_improved: list[str]
    cumulative_cats_hurt: list[str]
    cumulative_cat_deltas: dict[str, float]
    projected_record_before: dict   # wins/losses/tossups vs opponent
    projected_record_after: dict
    categories_flipped: list[str]   # categories that changed from loss/tossup to win


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

def _compute_record(
    my_team: TeamProjection,
    opp_team: TeamProjection,
    league_averages: dict,
) -> dict:
    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    wins = losses = tossups = 0
    for cat in all_cats:
        _, stdev = league_averages.get(cat, (0.0, 1.0))
        cm = project_category_matchup(cat, my_team.cat_value(cat), opp_team.cat_value(cat), stdev)
        if cm.result == "win":
            wins += 1
        elif cm.result == "loss":
            losses += 1
        else:
            tossups += 1
    return {"wins": wins, "losses": losses, "toss_ups": tossups}


def _score_add_drop(
    add_proj: PlayerProjection,
    drop_dict: dict,
    drop_proj: Optional[PlayerProjection],
    current_team: TeamProjection,
    opp_team: TeamProjection,
    league_averages: dict,
    cat_score_map: dict,
) -> tuple[float, list[str], list[str], dict[str, float]]:
    """Score a single add/drop pair against opponent."""
    # Build new roster projections
    drop_name = drop_dict.get("name") or drop_dict.get("full_name", "")
    remaining = [p for p in current_team.players if p.name != drop_name]
    if drop_proj and drop_proj.name == drop_name:
        remaining = [p for p in current_team.players if p.name != drop_proj.name]

    new_players = remaining + [add_proj]
    new_team = build_team_projection(new_players)

    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    cats_improved = []
    cats_hurt = []
    cat_deltas = {}
    score = 0.0

    for cat in all_cats:
        old_val = current_team.cat_value(cat)
        new_val = new_team.cat_value(cat)
        delta = new_val - old_val
        if cat in LOWER_IS_BETTER:
            delta = -delta

        cat_deltas[cat] = delta

        cs = cat_score_map.get(cat)
        if cs is None:
            continue

        league_stdev = cs.league_stdev if cs.league_stdev > 0 else 1.0
        net_norm = delta / league_stdev

        # Weight by matchup need: losing cats score highest
        opp_val = opp_team.cat_value(cat)
        my_val = current_team.cat_value(cat)
        raw_gap = my_val - opp_val
        if cat in LOWER_IS_BETTER:
            raw_gap = -raw_gap
        gap_norm = raw_gap / league_stdev

        # Bonus for flipping a loss/tossup
        if gap_norm < -TOSSUP_THRESHOLD:
            matchup_weight = 2.5   # losing — high priority to improve
        elif gap_norm < TOSSUP_THRESHOLD:
            matchup_weight = 1.5   # tossup — medium priority
        else:
            matchup_weight = 0.3   # already winning — protect, don't sacrifice

        if net_norm > 0.02:
            cats_improved.append(cat)
            score += net_norm * matchup_weight
        elif net_norm < -0.02:
            cats_hurt.append(cat)
            # Extra penalty for hurting categories we're comfortably winning
            if gap_norm > 0.75:
                score -= abs(net_norm) * matchup_weight * 2.0  # double penalty
            else:
                score -= abs(net_norm) * matchup_weight

    return score, cats_improved, cats_hurt, cat_deltas


def simulate_adddrop(
    my_roster: list[dict],
    opp_roster: list[dict],
    pool_players: list[dict],
    fg_bat_data: dict,
    fg_pit_data: dict,
    max_moves: int = 6,
    n_teams: int = 10,
) -> AddDropPlan:
    """
    Simulate optimal add/drop sequence up to max_moves.

    Args:
        my_roster: list of player dicts from snapshot roster.players
        opp_roster: list of player dicts from league_rosters.json opponent entry
        pool_players: list of player dicts from waiver pool
        fg_bat_data / fg_pit_data: loaded FG projection dicts
        max_moves: max weekly adds allowed
        n_teams: league size
    """
    all_projections = load_projections_from_fg(fg_bat_data, fg_pit_data)
    fg_lookup = build_fg_lookup(all_projections)

    # Match my roster and opponent
    my_matches = match_roster_to_fg(my_roster, fg_lookup)
    my_projs = [p for p in my_matches.values() if p is not None]

    opp_matches = match_roster_to_fg(opp_roster, fg_lookup)
    opp_projs = [p for p in opp_matches.values() if p is not None]
    opp_team = build_team_projection(opp_projs)

    # Match pool players to FG
    pool_matches = match_roster_to_fg(pool_players, fg_lookup)
    pool_projs = {
        name: proj for name, proj in pool_matches.items()
        if proj is not None
    }

    # Build name -> dict lookup for pool
    pool_dict_by_name = {
        (p.get("name") or p.get("full_name", "")): p
        for p in pool_players
    }

    league_averages = compute_league_averages(all_projections, n_teams=n_teams)

    # Track mutable state
    current_roster = list(my_roster)
    current_projs = list(my_projs)
    current_team = build_team_projection(current_projs)

    # Names already on roster (to avoid re-adding)
    rostered_names = {_normalize_name(p.get("name") or p.get("full_name", "")) for p in current_roster}

    # Record before
    cat_scores = score_team_categories(current_team, league_averages)
    cat_score_map = {cs.cat: cs for cs in cat_scores}
    record_before = _compute_record(current_team, opp_team, league_averages)

    moves: list[AddDropMove] = []
    cumulative_deltas: dict[str, float] = {
        cat: 0.0 for cat in SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    }

    for move_num in range(1, max_moves + 1):
        best_score = 0.0
        best_add_proj: Optional[PlayerProjection] = None
        best_add_dict: Optional[dict] = None
        best_drop_dict: Optional[dict] = None
        best_drop_proj: Optional[PlayerProjection] = None
        best_improved: list[str] = []
        best_hurt: list[str] = []
        best_deltas: dict[str, float] = {}

        # Recompute cat scores against current state
        cat_scores = score_team_categories(current_team, league_averages)
        cat_score_map = {cs.cat: cs for cs in cat_scores}

        # Try each pool player
        for pool_name, add_proj in pool_projs.items():
            if _normalize_name(pool_name) in rostered_names:
                continue

            # Try each drop candidate
            for drop_dict in current_roster:
                drop_name = drop_dict.get("name") or drop_dict.get("full_name", "")
                if not _can_drop(drop_dict, current_roster):
                    continue
                # Don't drop players we just added this simulation
                if _normalize_name(drop_name) + "__protected" in rostered_names:
                    continue

                # Find drop projection
                drop_proj = my_matches.get(drop_name)

                score, improved, hurt, deltas = _score_add_drop(
                    add_proj, drop_dict, drop_proj,
                    current_team, opp_team, league_averages, cat_score_map
                )

                if score > best_score:
                    best_score = score
                    best_add_proj = add_proj
                    best_add_dict = pool_dict_by_name.get(pool_name)
                    best_drop_dict = drop_dict
                    best_drop_proj = drop_proj
                    best_improved = improved
                    best_hurt = hurt
                    best_deltas = deltas

        if best_add_proj is None or best_score <= 0:
            break  # No beneficial move found

        # Apply the move
        drop_name = best_drop_dict.get("name") or best_drop_dict.get("full_name", "")
        drop_key = best_drop_dict.get("player_key", "")
        add_key = best_add_dict.get("player_key", "") if best_add_dict else ""

        # Update state
        current_roster = [p for p in current_roster if (p.get("name") or p.get("full_name","")) != drop_name]
        if best_add_dict:
            current_roster.append(best_add_dict)

        current_projs = [p for p in current_projs if p.name != drop_name]
        current_projs.append(best_add_proj)
        current_team = build_team_projection(current_projs)

        rostered_names.discard(_normalize_name(drop_name))
        rostered_names.add(_normalize_name(best_add_proj.name))

        # Remove from pool
        pool_projs = {k: v for k, v in pool_projs.items() if k != best_add_proj.name}
        # Prevent dropping players added this simulation
        rostered_names.add(_normalize_name(best_add_proj.name) + "__protected")

        # Accumulate deltas
        for cat, delta in best_deltas.items():
            cumulative_deltas[cat] = cumulative_deltas.get(cat, 0.0) + delta

        rationale = (
            f"Move {move_num}: Add {best_add_proj.name} ({best_add_proj.player_type}), "
            f"drop {drop_name}. Improves: {', '.join(best_improved)}."
        )
        if best_hurt:
            rationale += f" Costs: {', '.join(best_hurt)}."

        moves.append(AddDropMove(
            move_number=move_num,
            add_name=best_add_proj.name,
            add_player_key=add_key,
            add_type=best_add_proj.player_type,
            drop_name=drop_name,
            drop_player_key=drop_key,
            drop_type=best_drop_proj.player_type if best_drop_proj else "unknown",
            cats_improved=best_improved,
            cats_hurt=best_hurt,
            cat_deltas=best_deltas,
            move_score=round(best_score, 4),
            rationale=rationale,
        ))

    # Record after
    record_after = _compute_record(current_team, opp_team, league_averages)

    # Categories flipped from loss/tossup to win
    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    cats_flipped = []
    for cat in all_cats:
        _, stdev = league_averages.get(cat, (0.0, 1.0))
        before = project_category_matchup(
            cat,
            build_team_projection(my_projs).cat_value(cat),
            opp_team.cat_value(cat),
            stdev,
        )
        after = project_category_matchup(
            cat,
            current_team.cat_value(cat),
            opp_team.cat_value(cat),
            stdev,
        )
        if before.result in ("loss", "toss-up") and after.result == "win":
            cats_flipped.append(cat)

    # Cumulative improved/hurt
    cum_improved = [c for c, d in cumulative_deltas.items() if d > 0.001]
    cum_hurt = [c for c, d in cumulative_deltas.items() if d < -0.001]

    return AddDropPlan(
        moves=moves,
        cumulative_cats_improved=cum_improved,
        cumulative_cats_hurt=cum_hurt,
        cumulative_cat_deltas=cumulative_deltas,
        projected_record_before=record_before,
        projected_record_after=record_after,
        categories_flipped=cats_flipped,
    )


def adddrop_plan_to_dict(plan: AddDropPlan) -> dict:
    return {
        "projected_record_before": plan.projected_record_before,
        "projected_record_after": plan.projected_record_after,
        "categories_flipped": plan.categories_flipped,
        "cumulative_cats_improved": plan.cumulative_cats_improved,
        "cumulative_cats_hurt": plan.cumulative_cats_hurt,
        "move_count": len(plan.moves),
        "moves": [
            {
                "move_number": m.move_number,
                "add": {"name": m.add_name, "key": m.add_player_key, "type": m.add_type},
                "drop": {"name": m.drop_name, "key": m.drop_player_key, "type": m.drop_type},
                "move_score": m.move_score,
                "cats_improved": m.cats_improved,
                "cats_hurt": m.cats_hurt,
                "cat_deltas": {
                    k: round(v, 5 if k in ("AVG","ERA","WHIP") else 2)
                    for k, v in m.cat_deltas.items()
                    if abs(v) > 0.001
                },
                "rationale": m.rationale,
            }
            for m in plan.moves
        ],
    }
