"""
src/yahoo_ai_gm/analysis/trade_value.py

Layer 2 — Pure Analysis.

Trade value tracker: compares current FG projections against
acquisition-week projections to identify sell-high and cut-bait candidates.

Labels:
  SELL_HIGH  — projection rose significantly since acquisition
  BUY_LOW    — projection fell but player still has upside
  CUT_BAIT   — projection fell, player not worth holding
  HOLD       — stable projection
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from yahoo_ai_gm.analysis.trade_engine import (
    _normalize_name,
    SCORING_CATS,
    LOWER_IS_BETTER,
)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

SELL_HIGH_THRESHOLD  =  0.40   # z-score delta above this = sell high
CUT_BAIT_THRESHOLD   = -0.40   # z-score delta below this = cut bait
BUY_LOW_THRESHOLD    = -0.25   # between this and cut_bait = buy low

# Category weights for rolling up to single score
CAT_WEIGHTS = {
    "R": 1.0, "HR": 1.0, "RBI": 1.0, "SB": 1.0, "AVG": 1.2,
    "W": 1.2, "SO": 1.0, "SV": 1.5, "ERA": 1.2, "WHIP": 1.2, "IP": 0.8,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PlayerValueDelta:
    player_key: str
    name: str
    player_type: str            # "batter" | "pitcher"
    week_acquired: int
    current_week: int

    # Raw projection values
    current_proj: dict[str, float]
    baseline_proj: dict[str, float]

    # Deltas
    cat_deltas: dict[str, float]        # raw delta per cat
    cat_deltas_normalized: dict[str, float]  # z-score normalized delta
    value_delta: float                  # weighted composite score

    label: str                  # SELL_HIGH | BUY_LOW | CUT_BAIT | HOLD
    label_reason: str
    weeks_held: int


# ---------------------------------------------------------------------------
# Projection snapshot loader
# ---------------------------------------------------------------------------

def _load_snapshot(snapshots_dir: Path, week: int) -> dict:
    """Load projection snapshot for a given week. Falls back to week 0."""
    path = snapshots_dir / f"projections_week_{week:02d}.json"
    if not path.exists():
        # Fall back to preseason
        path = snapshots_dir / "projections_week_00_preseason.json"
    if not path.exists():
        return {"bat": {}, "pit": {}}
    import json
    return json.loads(path.read_text())


def _get_player_proj(snapshot: dict, name: str, player_type: str) -> dict:
    """Extract projection dict for a player from snapshot."""
    key = _normalize_name(name)
    bucket = snapshot.get("bat" if player_type == "batter" else "pit", {})
    # Try exact normalized match
    for snap_name, proj in bucket.items():
        if _normalize_name(snap_name) == key:
            return {k: float(v) for k, v in proj.items() if v is not None}
    return {}


def _player_type(positions: list[str]) -> str:
    if any(p in ("SP", "RP", "P") for p in positions):
        return "pitcher"
    return "batter"


# ---------------------------------------------------------------------------
# League stdev estimates (static — from FG population)
# Used to normalize deltas across categories
# ---------------------------------------------------------------------------

LEAGUE_STDEV = {
    "R":    80.0, "HR":   20.0, "RBI":  75.0, "SB":   25.0, "AVG":  0.020,
    "W":    10.0, "SO":  120.0, "SV":   15.0, "ERA":   0.60, "WHIP":  0.12,
    "IP":  150.0,
}


def _compute_value_delta(
    cat_deltas: dict[str, float],
) -> tuple[float, dict[str, float]]:
    """
    Compute weighted composite value delta and per-cat normalized deltas.
    Returns (composite_score, normalized_deltas).
    """
    normalized = {}
    composite = 0.0
    for cat, delta in cat_deltas.items():
        stdev = LEAGUE_STDEV.get(cat, 1.0)
        norm = delta / stdev
        if cat in LOWER_IS_BETTER:
            norm = -norm  # lower ERA = positive
        normalized[cat] = round(norm, 4)
        weight = CAT_WEIGHTS.get(cat, 1.0)
        composite += norm * weight

    total_weight = sum(CAT_WEIGHTS.get(c, 1.0) for c in cat_deltas)
    if total_weight > 0:
        composite /= total_weight

    return round(composite, 4), normalized


def _label(value_delta: float, current_proj: dict, player_type: str) -> tuple[str, str]:
    """Determine label and reason."""
    if value_delta >= SELL_HIGH_THRESHOLD:
        return "SELL_HIGH", f"Projection improved significantly ({value_delta:+.2f} z). Trade from a position of strength."
    elif value_delta <= CUT_BAIT_THRESHOLD:
        # Check if player is still viable
        if player_type == "batter":
            avg = current_proj.get("AVG", 0.250)
            hr  = current_proj.get("HR", 0)
            if avg < 0.230 or hr < 8:
                return "CUT_BAIT", f"Projection fell ({value_delta:+.2f} z) and current output is weak. Consider dropping."
        else:
            era = current_proj.get("ERA", 5.0)
            ip  = current_proj.get("IP", 0)
            if era > 5.0 or ip < 30:
                return "CUT_BAIT", f"Projection fell ({value_delta:+.2f} z) and ERA/IP concerning. Consider dropping."
        return "BUY_LOW", f"Projection dipped ({value_delta:+.2f} z) but player retains value. Buy-low trade target."
    else:
        return "HOLD", f"Projection stable ({value_delta:+.2f} z). No action needed."


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def compute_trade_values(
    my_roster: list[dict],
    acquisition_log: dict,
    snapshots_dir: Path,
    current_week: int,
) -> list[PlayerValueDelta]:
    """
    Compute projection delta for all rostered players.
    Returns list sorted by value_delta descending (sell-high first).
    """
    # Load current snapshot
    current_snap = _load_snapshot(snapshots_dir, current_week)

    results = []

    for player in my_roster:
        key  = player.get("player_key", "")
        name = player.get("name") or player.get("full_name", "")
        positions = player.get("eligible_positions", [])
        if isinstance(positions, str):
            positions = [p.strip() for p in positions.split(",")]

        ptype = _player_type(positions)

        # Get acquisition info
        acq_info = acquisition_log.get(key, {})
        week_acquired = acq_info.get("week_acquired", current_week)
        weeks_held = max(0, current_week - week_acquired)

        # Load baseline snapshot (acquisition week or preseason)
        baseline_snap = _load_snapshot(snapshots_dir, week_acquired)

        # Get projections
        curr_proj     = _get_player_proj(current_snap, name, ptype)
        baseline_proj = _get_player_proj(baseline_snap, name, ptype)

        if not curr_proj or not baseline_proj:
            continue

        # Compute per-category deltas
        all_cats = (
            ["R", "HR", "RBI", "SB", "AVG"] if ptype == "batter"
            else ["W", "SO", "SV", "ERA", "WHIP", "IP"]
        )
        cat_deltas: dict[str, float] = {}
        for cat in all_cats:
            curr_val = curr_proj.get(cat)
            base_val = baseline_proj.get(cat)
            if curr_val is not None and base_val is not None:
                cat_deltas[cat] = float(curr_val) - float(base_val)

        if not cat_deltas:
            continue

        value_delta, normalized = _compute_value_delta(cat_deltas)
        label, reason = _label(value_delta, curr_proj, ptype)

        results.append(PlayerValueDelta(
            player_key=key,
            name=name,
            player_type=ptype,
            week_acquired=week_acquired,
            current_week=current_week,
            current_proj=curr_proj,
            baseline_proj=baseline_proj,
            cat_deltas=cat_deltas,
            cat_deltas_normalized=normalized,
            value_delta=value_delta,
            label=label,
            label_reason=reason,
            weeks_held=weeks_held,
        ))

    results.sort(key=lambda p: p.value_delta, reverse=True)
    return results


def trade_value_to_dict(p: PlayerValueDelta) -> dict:
    return {
        "name": p.name,
        "type": p.player_type,
        "label": p.label,
        "value_delta": p.value_delta,
        "weeks_held": p.weeks_held,
        "week_acquired": p.week_acquired,
        "reason": p.label_reason,
        "cat_deltas": {
            k: round(v, 5 if k in ("AVG", "ERA", "WHIP") else 2)
            for k, v in p.cat_deltas.items()
        },
        "cat_deltas_normalized": p.cat_deltas_normalized,
        "current_proj": {
            k: round(v, 3 if k in ("AVG", "ERA", "WHIP", "FIP") else 1)
            for k, v in p.current_proj.items()
        },
    }
