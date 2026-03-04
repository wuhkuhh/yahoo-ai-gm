# yahoo_ai_gm/matchup.py
from typing import Dict

DEFAULT_SWING_BANDS = {
    "R": 6, "HR": 4, "RBI": 6, "SB": 3,
    "W": 2, "SV": 3, "K": 10, "IP": 6,
    "AVG": 0.015, "ERA": 0.40, "WHIP": 0.08,
}

def _mult(delta: float, band: float) -> float:
    # delta > 0: you're ahead. delta < 0: you're behind.
    if abs(delta) <= band:
        return 1.4
    if -2 * band <= delta < -band:
        return 1.2
    if delta < -2 * band:
        return 0.7
    if delta > 2 * band:
        return 0.8
    return 1.0

def derive_dynamic_weights(
    base_weights: Dict[str, float],
    pressure_report: Dict[str, float],
    swing_bands: Dict[str, float] = DEFAULT_SWING_BANDS,
) -> Dict[str, float]:
    w = dict(base_weights)
    for cat, base in base_weights.items():
        if cat not in pressure_report:
            continue
        band = swing_bands.get(cat)
        if band is None:
            continue
        w[cat] = base * _mult(float(pressure_report[cat]), float(band))
    return w
