from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List, Tuple
from collections import defaultdict


CANON = {
    "Runs": "R",
    "Home Runs": "HR",
    "Runs Batted In": "RBI",
    "Stolen Bases": "SB",
    "Batting Average": "AVG",
    "Hits / At Bats": "H/AB",
    "Innings Pitched": "IP",
    "Wins": "W",
    "Saves": "SV",
    "Strikeouts": "K",
    "Earned Run Average": "ERA",
    "(Walks + Hits)/ Innings Pitched": "WHIP",
}

BAD_STATUSES = {"DTD", "IL", "IL10", "IL15", "IL60", "NA", "SUSP"}


def _pos_set(pos_str: str) -> set[str]:
    return {p.strip() for p in (pos_str or "").split(",") if p.strip()}


def _is_pitcher(pos_str: str) -> bool:
    pos = _pos_set(pos_str)
    return bool(pos & {"SP", "RP", "P"})


def _is_reliever(pos_str: str) -> bool:
    pos = _pos_set(pos_str)
    return "RP" in pos or ("P" in pos and "SP" not in pos)


def _parse_num(v: Any) -> float:
    if v is None:
        return 0.0
    s = str(v).strip()
    if s in {"-", ""}:
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def _parse_hits_ab(val: str) -> Tuple[int, int]:
    if not val:
        return 0, 0
    s = str(val).strip()
    if "/" not in s:
        return 0, 0
    a, b = s.split("/", 1)
    try:
        return int(a), int(b)
    except Exception:
        return 0, 0


@dataclass
class ScoredCandidate:
    player_key: str
    name: str
    team: str | None
    pos: str
    status: str | None
    score: float
    impacts: Dict[str, float]


def score_candidates(
    candidates: List[dict],
    stat_map: Dict[str, str],
    needs: List[str],
) -> List[ScoredCandidate]:
    # base weights
    w = defaultdict(float)
    for c in ["R", "HR", "RBI", "SB", "W", "SV", "K"]:
        w[c] = 1.0

    need_sv = "SV" in needs
    protect_ratios = any("protect ERA/WHIP" in n for n in needs)

    # boosts
    if need_sv:
        w["SV"] += 6.0  # make saves dominate when requested
    if any("K/W" in n for n in needs):
        w["K"] += 1.5
        w["W"] += 1.0

    out: List[ScoredCandidate] = []

    for p in candidates:
        status = (p.get("status") or "").upper().strip()
        if status in BAD_STATUSES:
            continue

        stats_by_id = p.get("baseline_stats_by_id") or p.get("stats_by_id") or {}

        impacts: Dict[str, float] = {}
        hits = ab = 0

        for stat_id, raw_val in stats_by_id.items():
            nm = stat_map.get(str(stat_id))
            if not nm:
                continue
            canon = CANON.get(nm)
            if not canon:
                continue
            if canon == "H/AB":
                h, a = _parse_hits_ab(str(raw_val))
                hits += h
                ab += a
            else:
                impacts[canon] = _parse_num(raw_val)

        if ab > 0:
            impacts["AVG"] = hits / ab

        pos = p.get("pos") or ""
        is_p = _is_pitcher(pos)
        is_rp = _is_reliever(pos)

        score = 0.0

        if is_p:
            # core pitching value
            score += w["W"] * impacts.get("W", 0.0)
            score += w["SV"] * impacts.get("SV", 0.0)
            score += w["K"] * impacts.get("K", 0.0)
            score += 0.05 * impacts.get("IP", 0.0)

            # need gating: if we need saves, strongly prefer RP/closer-ish profiles
            if need_sv:
                if is_rp:
                    score += 30.0
                if impacts.get("SV", 0.0) > 0:
                    score += 40.0
                else:
                    # SP with 0 SV shouldn't dominate when you're chasing saves
                    score -= 25.0

            # ---------------------------------------------------------
            # RATIO PROTECTION ENFORCEMENT (HARD FILTER + SOFT PENALTY)
            #
            # When needs include "protect ERA/WHIP", do NOT recommend
            # obvious ratio nukes as streamers.
            # ---------------------------------------------------------
            if protect_ratios:
                era = impacts.get("ERA", 0.0)
                whip = impacts.get("WHIP", 0.0)

                # HARD FILTER: never recommend these as streamers
                if era >= 5.00 or whip >= 1.45:
                    continue

                # Soft penalties start earlier (keeps you from recommending uglies)
                if era >= 4.20:
                    score -= (era - 4.20) * 45.0
                if whip >= 1.30:
                    score -= (whip - 1.30) * 180.0

        else:
            score += w["R"] * impacts.get("R", 0.0)
            score += w["HR"] * impacts.get("HR", 0.0)
            score += w["RBI"] * impacts.get("RBI", 0.0)
            score += w["SB"] * impacts.get("SB", 0.0)
            score += 0.2 * impacts.get("AVG", 0.0)

        out.append(
            ScoredCandidate(
                player_key=p.get("player_key", ""),
                name=p.get("name", ""),
                team=p.get("team"),
                pos=pos,
                status=p.get("status"),
                score=score,
                impacts={k: float(v) for k, v in impacts.items()},
            )
        )

    out.sort(key=lambda x: x.score, reverse=True)
    return out
