# yahoo_ai_gm/risk.py
from dataclasses import dataclass
from typing import Any, Dict, Tuple

def _f(d: Dict[str, Any], k: str, default: float = 0.0) -> float:
    try:
        v = d.get(k, default)
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default

@dataclass(frozen=True)
class RatioRiskConfig:
    era_hard: float = 5.00
    whip_hard: float = 1.45
    era_soft: float = 4.30
    whip_soft: float = 1.32
    penalty_scale: float = 3.0
    allow_hard_gated: bool = False

def pitcher_ratio_risk(baseline: Dict[str, Any], cfg: RatioRiskConfig) -> Tuple[bool, float, Dict[str, Any]]:
    """
    Returns:
      allowed: bool (False means filter out)
      penalty: float (>=0, higher is worse)
      debug: dict
    """
    era = _f(baseline, "ERA", 0.0)
    whip = _f(baseline, "WHIP", 0.0)

    hard_gated = (era >= cfg.era_hard) or (whip >= cfg.whip_hard)
    if hard_gated and not cfg.allow_hard_gated:
        return False, float("inf"), {"hard_gated": True, "ERA": era, "WHIP": whip}

    # Soft penalty ramps up quickly as you approach hard thresholds
    penalty = 0.0
    if era > cfg.era_soft and cfg.era_hard > cfg.era_soft:
        penalty += ((era - cfg.era_soft) / (cfg.era_hard - cfg.era_soft)) ** 2
    if whip > cfg.whip_soft and cfg.whip_hard > cfg.whip_soft:
        penalty += ((whip - cfg.whip_soft) / (cfg.whip_hard - cfg.whip_soft)) ** 2

    return True, cfg.penalty_scale * penalty, {
        "hard_gated": hard_gated,
        "ERA": era,
        "WHIP": whip,
        "penalty": cfg.penalty_scale * penalty,
    }

def is_pitcher(candidate: Dict[str, Any]) -> bool:
    # Works with typical shapes: ["SP","RP"], or "position_type": "P"
    pos = candidate.get("eligible_positions") or candidate.get("positions") or []
    if isinstance(pos, str):
        pos = [pos]
    if any(p in {"SP", "RP", "P"} for p in pos):
        return True
    pt = (candidate.get("position_type") or candidate.get("pos_type") or "").upper()
    return pt == "P"
