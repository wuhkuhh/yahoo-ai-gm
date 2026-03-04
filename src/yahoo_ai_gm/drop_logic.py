# yahoo_ai_gm/drop_logic.py
from dataclasses import dataclass
from typing import Any, Dict, List

def _f(stats: Dict[str, Any], k: str, default: float = 0.0) -> float:
    try:
        v = stats.get(k, default)
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default

@dataclass
class DropCandidate:
    player_id: str
    name: str
    drop_cost: float  # higher = more painful to drop
    reasons: List[str]

def _get_player_id(p: Dict[str, Any]) -> str:
    return str(p.get("player_id") or p.get("playerId") or p.get("id") or p.get("player_key") or "")

def _get_name(p: Dict[str, Any]) -> str:
    # tolerate several shapes
    if isinstance(p.get("name"), dict):
        return p["name"].get("full") or p["name"].get("full_name") or "unknown"
    return p.get("name") or p.get("full_name") or "unknown"

def _positions(p: Dict[str, Any]) -> List[str]:
    pos = p.get("eligible_positions") or p.get("positions") or []
    if isinstance(pos, str):
        return [pos]
    return list(pos)

def suggest_drops(
    roster_players: List[Dict[str, Any]],
    baseline_stats_by_id: Dict[str, Dict[str, Any]],
    max_suggestions: int = 8,
) -> List[DropCandidate]:
    # Count position redundancy to prefer dropping redundant players
    pos_counts: Dict[str, int] = {}
    for rp in roster_players:
        for pos in _positions(rp):
            pos_counts[pos] = pos_counts.get(pos, 0) + 1

    scored: List[DropCandidate] = []

    for rp in roster_players:
        pid = _get_player_id(rp)
        name = _get_name(rp)
        b = baseline_stats_by_id.get(pid, {})
        pos = _positions(rp)
        status = (rp.get("status") or rp.get("injury_status") or "").upper()

        is_p = any(p in {"SP", "RP", "P"} for p in pos) or (rp.get("position_type") == "P")
        reasons: List[str] = []

        if is_p:
            k = _f(b, "K"); ip = _f(b, "IP"); sv = _f(b, "SV")
            era = _f(b, "ERA"); whip = _f(b, "WHIP")
            # Contribution proxy: reward Ks/IP/SV
            contrib = 0.60 * (k ** 0.5) + 0.45 * (ip ** 0.5) + 0.90 * (sv ** 0.5)
            # Liability makes dropping less costly (ratio nukes are easier drops)
            liability = 0.0
            if era >= 4.50: liability += 1.0
            if whip >= 1.35: liability += 1.0
            drop_cost = max(0.0, contrib - 1.25 * liability)
            if liability > 0:
                reasons.append(f"ratio liability (ERA {era:.2f}, WHIP {whip:.2f})")
        else:
            r = _f(b, "R"); hr = _f(b, "HR"); rbi = _f(b, "RBI"); sb = _f(b, "SB"); avg = _f(b, "AVG")
            # Contribution proxy: reward power/speed, modestly reward avg
            contrib = (r ** 0.5) + 1.15 * (hr ** 0.5) + 1.10 * (rbi ** 0.5) + 1.30 * (sb ** 0.5) + 8.0 * avg
            drop_cost = max(0.0, contrib)

        # Status: more droppable if IL/NA/etc
        if status in {"IL", "DL", "NA", "INJ"}:
            drop_cost *= 0.65
            reasons.append(f"status={status}")

        # Redundancy: if you have lots at a position, dropping hurts less
        for p in pos:
            if p in {"OF", "SP", "RP"} and pos_counts.get(p, 0) >= 4:
                drop_cost *= 0.85
                reasons.append(f"redundant at {p}")
                break

        scored.append(DropCandidate(player_id=pid, name=name, drop_cost=drop_cost, reasons=reasons))

    # Sort: lowest drop_cost first = best drops
    scored.sort(key=lambda x: x.drop_cost)
    return scored[:max_suggestions]
