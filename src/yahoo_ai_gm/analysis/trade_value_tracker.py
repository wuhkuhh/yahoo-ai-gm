"""
src/yahoo_ai_gm/analysis/trade_value_tracker.py

Layer 2 — Pure Analysis.

Tracks projection delta for each rostered player since acquisition.
Uses projection_snapshots/ to compare current vs acquisition-week projections.

Output per player:
  - Value delta score (positive = risen, negative = fallen)
  - Per-category deltas
  - Signal: SELL_HIGH | HOLD | CUT_BAIT | WATCH
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from yahoo_ai_gm.analysis.trade_engine import (
    SCORING_CATS,
    LOWER_IS_BETTER,
    _normalize_name,
)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

SELL_HIGH_THRESHOLD  =  1.5   # value delta >= this = sell high
CUT_BAIT_THRESHOLD   = -1.5   # value delta <= this = cut bait
WATCH_THRESHOLD      = -0.8   # value delta <= this = watch


# Category weights for value delta score
# Reflects relative fantasy impact
CAT_WEIGHTS = {
    "R":    0.8,  "HR":   1.2,  "RBI":  0.8,  "SB":   1.0,  "AVG":  1.0,
    "W":    1.2,  "SO":   0.8,  "SV":   1.5,  "ERA":  1.0,  "WHIP": 1.0,  "IP": 0.5,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PlayerValueDelta:
    player_key: str
    name: str
    player_type: str         # "batter" | "pitcher"
    week_acquired: int
    week_baseline: int       # which snapshot week used as baseline
    cat_deltas: dict[str, float]   # cat -> delta (positive = improved)
    value_score: float       # weighted composite
    signal: str              # SELL_HIGH | HOLD | CUT_BAIT | WATCH
    primary_change: str      # "HR up +12.3" etc.


# ---------------------------------------------------------------------------
# Snapshot loading
# ---------------------------------------------------------------------------

def _load_snapshot(snapshots_dir: Path, week: int) -> dict:
    """Load projection snapshot for a given week."""
    # Try exact week first
    path = snapshots_dir / f"projections_week_{week:02d}.json"
    if path.exists():
        import json
        return json.loads(path.read_text())

    # Fall back to preseason (week 0)
    path0 = snapshots_dir / "projections_week_00_preseason.json"
    if path0.exists():
        import json
        return json.loads(path0.read_text())

    return {}


def _get_player_proj(snapshot: dict, name: str, player_type: str) -> Optional[dict]:
    """Look up a player's projection in a snapshot."""
    section = "bat" if player_type == "batter" else "pit"
    data = snapshot.get(section, {})

    # Direct lookup
    if name in data:
        return data[name]

    # Normalized lookup
    norm = _normalize_name(name)
    for k, v in data.items():
        if _normalize_name(k) == norm:
            return v

    return None


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------

def _compute_cat_deltas(
    baseline_proj: dict,
    current_proj: dict,
    player_type: str,
) -> dict[str, float]:
    """Compute per-category projection delta."""
    cats = SCORING_CATS["batting"] if player_type == "batter" else SCORING_CATS["pitching"]
    deltas = {}
    for cat in cats:
        baseline_val = baseline_proj.get(cat)
        current_val  = current_proj.get(cat)
        if baseline_val is None or current_val is None:
            continue
        try:
            b = float(baseline_val)
            c = float(current_val)
        except (TypeError, ValueError):
            continue

        delta = c - b
        # For lower-is-better cats, flip so positive = improvement
        if cat in LOWER_IS_BETTER:
            delta = -delta
        deltas[cat] = round(delta, 4)
    return deltas


def _value_score(cat_deltas: dict[str, float]) -> float:
    """Weighted composite value delta score."""
    score = 0.0
    for cat, delta in cat_deltas.items():
        weight = CAT_WEIGHTS.get(cat, 0.7)
        # Normalize by typical season range
        if cat == "AVG":
            norm = delta / 0.020   # 20pts AVG = 1 unit
        elif cat in ("ERA", "WHIP"):
            norm = delta / 0.30    # 0.30 ERA = 1 unit
        elif cat == "IP":
            norm = delta / 30.0
        elif cat in ("R", "RBI", "SO"):
            norm = delta / 15.0
        elif cat in ("HR", "SB", "W"):
            norm = delta / 5.0
        elif cat == "SV":
            norm = delta / 8.0
        else:
            norm = delta / 10.0
        score += norm * weight
    return round(score, 3)


def _primary_change(cat_deltas: dict[str, float]) -> str:
    """Return the most significant category change as a string."""
    if not cat_deltas:
        return "no change"
    # Find largest absolute normalized delta
    best_cat = max(cat_deltas, key=lambda c: abs(cat_deltas[c]) * CAT_WEIGHTS.get(c, 0.7))
    delta = cat_deltas[best_cat]
    direction = "up" if delta > 0 else "down"
    return f"{best_cat} {direction} {delta:+.2f}"


def _signal(score: float) -> str:
    if score >= SELL_HIGH_THRESHOLD:
        return "SELL_HIGH"
    elif score <= CUT_BAIT_THRESHOLD:
        return "CUT_BAIT"
    elif score <= WATCH_THRESHOLD:
        return "WATCH"
    return "HOLD"


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def compute_trade_value_deltas(
    my_roster: list[dict],
    acquisition_log: dict,
    snapshots_dir: Path,
    current_week: int,
    fg_bat_data: dict,
    fg_pit_data: dict,
) -> list[PlayerValueDelta]:
    """
    Compute projection delta for all rostered players since acquisition.

    Returns list sorted by value_score descending (sell-high candidates first).
    """
    # Build current projection lookup from FG data
    current_bat = {
        _normalize_name(p["PlayerName"]): {
            "R": p.get("R"), "HR": p.get("HR"), "RBI": p.get("RBI"),
            "SB": p.get("SB"), "AVG": p.get("AVG"),
        }
        for p in fg_bat_data.get("players", []) if p.get("PlayerName")
    }
    current_pit = {
        _normalize_name(p["PlayerName"]): {
            "W": p.get("W"), "SO": p.get("SO"), "SV": p.get("SV"),
            "ERA": p.get("ERA"), "WHIP": p.get("WHIP"), "IP": p.get("IP"),
        }
        for p in fg_pit_data.get("players", []) if p.get("PlayerName")
    }

    results = []

    for player in my_roster:
        key  = player.get("player_key", "")
        name = player.get("name") or player.get("full_name", "")
        positions = player.get("eligible_positions", [])
        if isinstance(positions, str):
            positions = [p.strip() for p in positions.split(",")]

        is_pitcher = any(pos in ("SP", "RP", "P") for pos in positions)
        player_type = "pitcher" if is_pitcher else "batter"

        # Get acquisition week
        acq_entry = acquisition_log.get(key, {})
        week_acquired = acq_entry.get("week_acquired", 1)
        baseline_week = max(0, week_acquired - 1)

        # Load baseline snapshot
        baseline_snap = _load_snapshot(snapshots_dir, baseline_week)

        # Get baseline projection
        baseline_proj = _get_player_proj(baseline_snap, name, player_type)
        if baseline_proj is None:
            continue

        # Get current projection
        norm_name = _normalize_name(name)
        current_proj = (current_bat if player_type == "batter" else current_pit).get(norm_name)
        if current_proj is None:
            continue

        cat_deltas = _compute_cat_deltas(baseline_proj, current_proj, player_type)
        if not cat_deltas:
            continue

        score = _value_score(cat_deltas)
        signal = _signal(score)
        primary = _primary_change(cat_deltas)

        results.append(PlayerValueDelta(
            player_key=key,
            name=name,
            player_type=player_type,
            week_acquired=week_acquired,
            week_baseline=baseline_week,
            cat_deltas=cat_deltas,
            value_score=score,
            signal=signal,
            primary_change=primary,
        ))

    results.sort(key=lambda p: p.value_score, reverse=True)
    return results


def value_delta_to_dict(p: PlayerValueDelta) -> dict:
    return {
        "name": p.name,
        "type": p.player_type,
        "week_acquired": p.week_acquired,
        "value_score": p.value_score,
        "signal": p.signal,
        "primary_change": p.primary_change,
        "cat_deltas": p.cat_deltas,
    }
