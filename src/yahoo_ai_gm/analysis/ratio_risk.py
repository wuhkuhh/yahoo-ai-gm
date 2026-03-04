"""
src/yahoo_ai_gm/analysis/ratio_risk.py

Layer 2 — Pure Analysis. No FastAPI, no I/O, no Yahoo client.

Ratio risk engine: models ERA/WHIP blowup probability for rostered pitchers
using FanGraphs 2026 Steamer projections.

Risk factors:
  1. FIP-ERA gap (positive = ERA lucky, will regress upward)
  2. BB/9 (walk rate -> WHIP inflation)
  3. HR/9 (home run rate -> ERA spikes)
  4. IP projection (low IP = high per-start variance)
  5. K/9 (high K rate partially offsets other risks)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from yahoo_ai_gm.analysis.trade_engine import (
    load_projections_from_fg,
    build_fg_lookup,
    match_roster_to_fg,
    _normalize_name,
)


# ---------------------------------------------------------------------------
# League average baselines (2026 Steamer population estimates)
# ---------------------------------------------------------------------------

LEAGUE_AVG_ERA   = 4.20
LEAGUE_AVG_WHIP  = 1.28
LEAGUE_AVG_BB9   = 3.20
LEAGUE_AVG_HR9   = 1.25
LEAGUE_AVG_K9    = 8.80
LEAGUE_AVG_FIP   = 4.25

# Risk thresholds
RISK_CRITICAL = 7.0
RISK_HIGH     = 5.0
RISK_MEDIUM   = 3.0

# FIP-ERA gap thresholds
FIP_GAP_CRITICAL = 0.75   # ERA more than 0.75 below FIP = very lucky
FIP_GAP_HIGH     = 0.40
FIP_GAP_MEDIUM   = 0.20

# Weights for risk components
W_FIP_GAP = 0.35
W_BB9     = 0.30
W_HR9     = 0.20
W_IP_VAR  = 0.10
W_K9_SAVE = 0.05   # K9 offsets risk


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PitcherRiskProfile:
    name: str
    team: str
    role: str              # "SP" | "RP"

    # Projection stats
    era: float
    whip: float
    fip: float
    k9: float
    bb9: float
    hr9: float
    ip: float

    # Risk components (0-10 each)
    fip_gap_score: float
    bb9_score: float
    hr9_score: float
    ip_var_score: float
    k9_save_score: float   # negative contribution (reduces risk)

    # Composite
    raw_risk: float
    risk_score: float      # 0-10 normalized
    risk_label: str        # LOW | MEDIUM | HIGH | CRITICAL
    primary_driver: str    # what's causing the risk
    recommendation: str    # START | STREAM_CAUTION | AVOID | STASH

    # Projected ranges
    era_upside: float      # best case (FIP - 0.3)
    era_downside: float    # worst case (FIP + regression)
    whip_upside: float
    whip_downside: float


# ---------------------------------------------------------------------------
# Risk computation
# ---------------------------------------------------------------------------

def _fip_gap_score(era: float, fip: float) -> float:
    """
    Positive FIP-ERA gap means ERA is below FIP (lucky) -> regression risk.
    Returns 0-10.
    """
    gap = fip - era  # positive = ERA lucky
    if gap <= 0:
        return 0.0   # ERA >= FIP, no regression risk
    # Scale: gap of 1.0 = score of 10
    return min(10.0, gap * 10.0)


def _bb9_score(bb9: float) -> float:
    """High BB/9 -> WHIP risk. Returns 0-10."""
    # 2.0 = very good (score 0), 5.0 = very bad (score 10)
    normalized = (bb9 - 2.0) / 3.0
    return max(0.0, min(10.0, normalized * 10.0))


def _hr9_score(hr9: float) -> float:
    """High HR/9 -> ERA spike risk. Returns 0-10."""
    # 0.8 = good (score 0), 2.0 = bad (score 10)
    normalized = (hr9 - 0.8) / 1.2
    return max(0.0, min(10.0, normalized * 10.0))


def _ip_variance_score(ip: float, role: str) -> float:
    """
    Low IP = high per-start variance. Returns 0-10.
    SP below 150 IP = elevated risk. RP below 50 IP = elevated risk.
    """
    if role == "SP":
        baseline = 170.0
    else:
        baseline = 60.0
    if ip >= baseline:
        return 0.0
    normalized = (baseline - ip) / baseline
    return min(10.0, normalized * 8.0)


def _k9_save_score(k9: float) -> float:
    """
    High K/9 reduces risk (fewer balls in play, fewer BABIP-driven blowups).
    Returns 0-5 (subtracted from risk).
    """
    # 10+ K/9 = max save score of 5
    normalized = max(0.0, (k9 - LEAGUE_AVG_K9) / 3.0)
    return min(5.0, normalized * 5.0)


def _risk_label(score: float) -> str:
    if score >= RISK_CRITICAL:
        return "CRITICAL"
    elif score >= RISK_HIGH:
        return "HIGH"
    elif score >= RISK_MEDIUM:
        return "MEDIUM"
    return "LOW"


def _primary_driver(
    fip_gap: float,
    bb9: float,
    hr9: float,
    ip: float,
    role: str,
) -> str:
    drivers = []
    if fip_gap >= FIP_GAP_HIGH:
        drivers.append(("FIP-ERA regression risk", fip_gap * W_FIP_GAP))
    if bb9 >= 3.8:
        drivers.append(("elevated walk rate", (bb9 - 2.0) / 3.0 * W_BB9))
    if hr9 >= 1.4:
        drivers.append(("high HR/9 rate", (hr9 - 0.8) / 1.2 * W_HR9))
    ip_baseline = 170.0 if role == "SP" else 60.0
    if ip < ip_baseline * 0.7:
        drivers.append(("low IP projection", W_IP_VAR))

    if not drivers:
        return "no significant risk factors"
    drivers.sort(key=lambda x: x[1], reverse=True)
    return drivers[0][0]


def _recommendation(risk_score: float, role: str, ip: float) -> str:
    if risk_score >= RISK_CRITICAL:
        return "AVOID" if role == "SP" else "STASH"
    elif risk_score >= RISK_HIGH:
        return "STREAM_CAUTION"
    elif risk_score >= RISK_MEDIUM:
        return "START" if ip >= 100 else "STREAM_CAUTION"
    return "START"


def _era_range(era: float, fip: float, bb9: float) -> tuple[float, float]:
    """Estimate best/worst case ERA over a season."""
    # Upside: ERA improves toward FIP if lucky, or stays if already good
    upside = min(era, fip) - 0.15
    # Downside: regress to FIP + BB risk premium
    bb_premium = max(0.0, (bb9 - LEAGUE_AVG_BB9) * 0.12)
    downside = max(era, fip) + bb_premium + 0.20
    return round(max(1.5, upside), 2), round(downside, 2)


def _whip_range(whip: float, bb9: float, k9: float) -> tuple[float, float]:
    """Estimate best/worst case WHIP."""
    k_factor = max(0.0, (k9 - LEAGUE_AVG_K9) * 0.01)
    upside = whip - 0.05 - k_factor
    bb_factor = max(0.0, (bb9 - LEAGUE_AVG_BB9) * 0.04)
    downside = whip + bb_factor + 0.08
    return round(max(0.80, upside), 3), round(downside, 3)


def compute_pitcher_risk(
    name: str,
    team: str,
    role: str,
    era: float,
    whip: float,
    fip: float,
    k9: float,
    bb9: float,
    ip: float,
    hr: float,
) -> PitcherRiskProfile:
    hr9 = (hr / ip * 9.0) if ip > 0 else LEAGUE_AVG_HR9

    fip_gap_s = _fip_gap_score(era, fip)
    bb9_s     = _bb9_score(bb9)
    hr9_s     = _hr9_score(hr9)
    ip_var_s  = _ip_variance_score(ip, role)
    k9_save   = _k9_save_score(k9)

    raw = (
        fip_gap_s  * W_FIP_GAP +
        bb9_s      * W_BB9 +
        hr9_s      * W_HR9 +
        ip_var_s   * W_IP_VAR -
        k9_save    * W_K9_SAVE
    )
    risk_score = max(0.0, min(10.0, raw))

    fip_gap = fip - era
    driver = _primary_driver(fip_gap, bb9, hr9, ip, role)
    label = _risk_label(risk_score)
    rec = _recommendation(risk_score, role, ip)

    era_up, era_dn = _era_range(era, fip, bb9)
    whip_up, whip_dn = _whip_range(whip, bb9, k9)

    return PitcherRiskProfile(
        name=name,
        team=team,
        role=role,
        era=round(era, 3),
        whip=round(whip, 3),
        fip=round(fip, 3),
        k9=round(k9, 2),
        bb9=round(bb9, 2),
        hr9=round(hr9, 2),
        ip=round(ip, 1),
        fip_gap_score=round(fip_gap_s, 2),
        bb9_score=round(bb9_s, 2),
        hr9_score=round(hr9_s, 2),
        ip_var_score=round(ip_var_s, 2),
        k9_save_score=round(k9_save, 2),
        raw_risk=round(raw, 3),
        risk_score=round(risk_score, 2),
        risk_label=label,
        primary_driver=driver,
        recommendation=rec,
        era_upside=era_up,
        era_downside=era_dn,
        whip_upside=whip_up,
        whip_downside=whip_dn,
    )


# ---------------------------------------------------------------------------
# Roster risk report
# ---------------------------------------------------------------------------

def roster_ratio_risk(
    my_roster: list[dict],
    fg_pit_data: dict,
) -> list[PitcherRiskProfile]:
    """
    Compute ratio risk profiles for all rostered pitchers.
    Returns list sorted by risk_score descending.
    """
    fg_lookup_pit: dict[str, dict] = {}
    for p in fg_pit_data.get("players", []):
        key = _normalize_name(p.get("PlayerName", ""))
        if key:
            fg_lookup_pit[key] = p

    profiles = []
    for player in my_roster:
        name = player.get("name") or player.get("full_name", "")
        positions = player.get("eligible_positions", [])
        if isinstance(positions, str):
            positions = [p.strip() for p in positions.split(",")]

        is_pitcher = any(pos in ("SP", "RP", "P") for pos in positions)
        if not is_pitcher:
            continue

        role = "RP" if "RP" in positions and "SP" not in positions else "SP"

        fg = fg_lookup_pit.get(_normalize_name(name))
        if fg is None:
            continue

        era  = float(fg.get("ERA") or 99.0)
        whip = float(fg.get("WHIP") or 9.9)
        fip  = float(fg.get("FIP") or era)
        k9   = float(fg.get("K/9") or 0.0)
        bb9  = float(fg.get("BB/9") or 0.0)
        ip   = float(fg.get("IP") or 0.0)
        hr   = float(fg.get("HR") or 0.0)

        if ip < 5.0:
            continue  # not enough projection to evaluate

        profile = compute_pitcher_risk(
            name=name,
            team=player.get("team_abbr") or fg.get("Team", ""),
            role=role,
            era=era,
            whip=whip,
            fip=fip,
            k9=k9,
            bb9=bb9,
            ip=ip,
            hr=hr,
        )
        profiles.append(profile)

    profiles.sort(key=lambda p: p.risk_score, reverse=True)
    return profiles


def risk_profile_to_dict(p: PitcherRiskProfile) -> dict:
    return {
        "name": p.name,
        "team": p.team,
        "role": p.role,
        "risk_score": p.risk_score,
        "risk_label": p.risk_label,
        "recommendation": p.recommendation,
        "primary_driver": p.primary_driver,
        "projections": {
            "ERA": p.era, "WHIP": p.whip, "FIP": p.fip,
            "K/9": p.k9, "BB/9": p.bb9, "HR/9": p.hr9, "IP": p.ip,
        },
        "risk_components": {
            "fip_gap": p.fip_gap_score,
            "bb9": p.bb9_score,
            "hr9": p.hr9_score,
            "ip_variance": p.ip_var_score,
            "k9_save": p.k9_save_score,
        },
        "projected_ranges": {
            "ERA": {"upside": p.era_upside, "downside": p.era_downside},
            "WHIP": {"upside": p.whip_upside, "downside": p.whip_downside},
        },
    }
