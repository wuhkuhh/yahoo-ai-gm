# yahoo_ai_gm/planner.py
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

@dataclass
class Plan:
    mode: str
    notes: List[str]
    ratio_penalty_scale: float = 3.0
    ratio_allow_hard_gated: bool = False

def choose_plan(
    scarcity: Dict[str, Any],
    pressure_report: Optional[Dict[str, float]] = None,
) -> Plan:
    notes: List[str] = []

    if scarcity.get("SV", {}).get("scarce", False):
        notes.append("SV market scarce → do not force SV chasing")

    if pressure_report:
        # If ratios are close, treat as high leverage
        era = float(pressure_report.get("ERA", 0.0))
        whip = float(pressure_report.get("WHIP", 0.0))
        close = (abs(era) <= 0.40) or (abs(whip) <= 0.08)
        if close:
            notes.append("Ratios are high leverage → protect ratios")
            return Plan(mode="PROTECT_RATIOS", notes=notes, ratio_penalty_scale=3.5, ratio_allow_hard_gated=False)

    return Plan(mode="BALANCED", notes=notes, ratio_penalty_scale=3.0, ratio_allow_hard_gated=False)
