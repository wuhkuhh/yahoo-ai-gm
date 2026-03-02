from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import List, Optional, Tuple
import json

from yahoo_ai_gm.domain.models import Snapshot, WaiverReport, WaiverSuggestion, PlayerSnapshot
from yahoo_ai_gm.analysis.roster_inefficiency import roster_inefficiency_report
from yahoo_ai_gm.analysis.pool_scoring import score_candidates, ScoredCandidate

BAD_STATUSES = {"DTD", "IL", "IL10", "IL15", "IL60", "NA", "SUSP"}
SV_MEANINGFUL_THRESHOLD = 5.0  # baseline season SV >= 5 => "real saves add"


def _roster_pos_counts(snapshot: Snapshot) -> Counter:
    c = Counter()
    for p in snapshot.roster.players:
        for pos in (p.eligible_positions or []):
            c[pos] += 1
    return c


def _derive_needs(snapshot: Snapshot) -> List[str]:
    pos_counts = _roster_pos_counts(snapshot)

    needs = []
    # In a 2-RP roster, you're still fragile for SV. Treat <=2 as a need.
    if pos_counts.get("RP", 0) <= 2:
        needs.append("SV")
    if pos_counts.get("SP", 0) >= 7:
        needs.append("K/W (stream) but protect ERA/WHIP")
    if pos_counts.get("1B", 0) >= 3:
        needs.append("Avoid adding 1B")
    if pos_counts.get("OF", 0) >= 6:
        needs.append("Avoid adding OF unless strong fit")
    return needs


def _drop_candidates(snapshot: Snapshot) -> List[PlayerSnapshot]:
    """
    v1 drop candidates: prefer redundancy positions, deprioritize elite starters (we don't know who is elite yet),
    and NEVER treat DTD as automatic drop (they can be benched).
    """
    ineff = roster_inefficiency_report(snapshot)
    flagged_keys = {i.player_key for i in ineff.items if i.player_key}

    players = list(snapshot.roster.players)
    pos_counts = _roster_pos_counts(snapshot)

    def score(p: PlayerSnapshot) -> float:
        s = 0.0

        # DTD => bench candidate, not drop
        if p.status and p.status.upper() == "DTD":
            s -= 5.0

        # if flagged for redundancy etc, more movable
        if p.player_key in flagged_keys:
            s += 5.0

        # redundant positions more movable
        s += sum(pos_counts.get(pos, 0) for pos in (p.eligible_positions or [])) / 10.0

        # keep RPs if SV need
        if "RP" in (p.eligible_positions or []):
            s -= 2.0

        return s

    players.sort(key=score, reverse=True)
    return players


def _bench_candidates(snapshot: Snapshot) -> List[PlayerSnapshot]:
    # DTD guys first
    return [p for p in snapshot.roster.players if (p.status or "").upper().strip() == "DTD"]


def _load_stat_map() -> dict[str, str]:
    p = Path("data/stat_map.json")
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        # common wrapper
        if isinstance(data.get("stat_map"), dict):
            return data.get("stat_map") or {}
        # sometimes the file is already a mapping
        # (keys like "28": "ERA")
        if data and all(isinstance(k, str) for k in data.keys()):
            # keep only string->string items
            return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
    return {}


def _pos_set(pos_str: str) -> set[str]:
    return {p.strip() for p in (pos_str or "").split(",") if p.strip()}


def _sv_market(sv_pool: Optional[List[dict]], stat_map: dict[str, str]) -> dict:
    """
    Determine whether SV is realistically available on waivers.
    Uses baseline stats if present. If not present, falls back to "unknown".
    """
    if not sv_pool:
        return {"sv_market": "unknown", "reason": "No RP pool provided.", "candidates": []}

    ranked = score_candidates(sv_pool, stat_map=stat_map, needs=["SV"])
    # Keep only candidates with baseline SV present (>=0). If no baseline, impacts will be empty or zeros.
    meaningful = [c for c in ranked if c.impacts.get("SV", 0.0) >= SV_MEANINGFUL_THRESHOLD]
    scarce = len(meaningful) == 0

    top = meaningful[:5] if meaningful else ranked[:5]
    return {
        "sv_market": "scarce" if scarce else "available",
        "threshold": SV_MEANINGFUL_THRESHOLD,
        "kept": len(meaningful),
        "candidates": [
            {
                "player_key": c.player_key,
                "name": c.name,
                "pos": c.pos,
                "team": c.team,
                "impacts": {
                    "SV": c.impacts.get("SV", 0.0),
                    "K": c.impacts.get("K", 0.0),
                    "W": c.impacts.get("W", 0.0),
                    "IP": c.impacts.get("IP", 0.0),
                    "ERA": c.impacts.get("ERA", 0.0),
                    "WHIP": c.impacts.get("WHIP", 0.0),
                },
            }
            for c in top
        ],
    }


def _filter_by_avoid_needs(pool: List[dict], needs: List[str]) -> List[dict]:
    if not pool:
        return pool

    avoid_1b = "Avoid adding 1B" in needs
    avoid_of = any(n.startswith("Avoid adding OF") for n in needs)

    if not (avoid_1b or avoid_of):
        return pool

    kept: List[dict] = []
    for p in pool:
        pos = _pos_set(p.get("pos") or "")
        if avoid_1b and "1B" in pos:
            continue
        if avoid_of and "OF" in pos:
            continue
        kept.append(p)
    return kept


def _top_adds(
    snapshot: Snapshot,
    pool: Optional[List[dict]],
    stat_map: dict[str, str],
    needs: List[str],
    top_n: int = 10,
    ratio_mode: str = "protect",
) -> List[ScoredCandidate]:
    if not pool:
        return []
    pool2 = _filter_by_avoid_needs(pool, needs)
    pool2 = _filter_ratio_risk(pool2, needs, stat_map, ratio_mode)
    ranked = score_candidates(pool2, stat_map=stat_map, needs=needs)
    return ranked[:top_n]


def _impacts_for_add(add: ScoredCandidate) -> dict:
    # Only include the stuff we care about for now
    impacts = {}
    for k in ["R", "HR", "RBI", "SB", "AVG", "W", "SV", "K", "IP", "ERA", "WHIP"]:
        if k in add.impacts:
            impacts[k] = add.impacts[k]
    return impacts


def waiver_recommendations(
    snapshot: Snapshot,
    pool: Optional[List[dict]] = None,
    sv_pool: Optional[List[dict]] = None,
    ratio_mode: str = "protect",
) -> WaiverReport:
    stat_map = _load_stat_map()

    needs = _derive_needs(snapshot)

    # SV scarcity awareness
    sv_meta = _sv_market(sv_pool, stat_map=stat_map) if "SV" in needs else {"sv_market": "n/a", "candidates": []}
    if "SV" in needs and sv_meta.get("sv_market") == "scarce":
        # remove SV from needs to avoid "chasing ghosts"
        needs = [n for n in needs if n != "SV"]

    adds = _top_adds(snapshot, pool, stat_map=stat_map, needs=needs, top_n=10, ratio_mode=ratio_mode)

    bench = _bench_candidates(snapshot)
    drops = _drop_candidates(snapshot)
    real_drop_pool = [p for p in drops if (p.status or "").upper().strip() != "DTD"]

    suggestions: List[WaiverSuggestion] = []

    # A) If DTD exists: recommend BENCH + ADD (do not “drop”)
    for injured in bench[:2]:
        for add in adds[:3] if adds else []:
            reason_prefix = ""
            if sv_meta.get("sv_market") == "scarce":
                reason_prefix = (
                    "SV market is scarce (no meaningful saves adds available). "
                    "Don't burn moves chasing saves; prioritize K/W streaming + ratio safety. "
                )
            suggestions.append(
                WaiverSuggestion(
                    add_player_key=add.player_key or "(unknown)",
                    add_name=add.name or "(unknown)",
                    drop_player_key=injured.player_key,
                    drop_name=injured.name,
                    reason=(
                        f"{reason_prefix}ACTION: BENCH (not drop). {injured.name} is DTD. "
                        f"Add {add.name} as a healthy contingency. Needs: {', '.join(needs) or 'none'}."
                    ),
                    confidence="med",
                    category_impacts=_impacts_for_add(add),
                )
            )
        if not adds:
            suggestions.append(
                WaiverSuggestion(
                    add_player_key="(pool-needed)",
                    add_name="(pool-needed)",
                    drop_player_key=injured.player_key,
                    drop_name=injured.name,
                    reason=(
                        f"ACTION: BENCH (not drop). {injured.name} is DTD. "
                        f"Add best healthy player aligned to needs: {', '.join(needs) or 'best available'}."
                    ),
                    confidence="low",
                    category_impacts={},
                )
            )

    # B) Real add/drop: pair top adds with top drop candidates
    for add in adds[:5]:
        if not real_drop_pool:
            break
        drop = real_drop_pool[0]
        reason_prefix = ""
        if sv_meta.get("sv_market") == "scarce":
            reason_prefix = (
                "SV market is scarce (no meaningful saves adds available). "
                "Recommendation assumes you won't gain much SV from waivers. "
            )

        suggestions.append(
            WaiverSuggestion(
                add_player_key=add.player_key or "(unknown)",
                add_name=add.name or "(unknown)",
                drop_player_key=drop.player_key,
                drop_name=drop.name,
                reason=(
                    f"{reason_prefix}ACTION: DROP/TRADE candidate. Add {add.name} to address needs "
                    f"({', '.join(needs) or 'best available'}). Drop candidate chosen by redundancy/structure heuristics."
                ),
                confidence="low",
                category_impacts=_impacts_for_add(add),
            )
        )

    # Always include SV meta note if relevant
    if "SV" in _derive_needs(snapshot) and sv_meta.get("sv_market") == "scarce":
        suggestions.insert(
            0,
            WaiverSuggestion(
                add_player_key="(meta)",
                add_name="(SV scarce)",
                drop_player_key="(meta)",
                drop_name="(no-op)",
                reason=(
                    f"SV market is scarce (baseline SV >= {SV_MEANINGFUL_THRESHOLD} not available in waiver RP pool). "
                    "Don't chase saves via waivers unless matchup pressure says SV is within reach; "
                    "focus on K/W streaming with ratio safety or pursue a trade for a closer."
                ),
                confidence="high",
                category_impacts={},
            ),
        )

    return WaiverReport(
        week=snapshot.week,
        team_key=snapshot.roster.team_key,
        generated_at=None,
        suggestions=suggestions,
    )


def _filter_ratio_risk(pool: List[dict], needs: List[str], stat_map: dict[str, str], ratio_mode: str = "protect") -> List[dict]:
    """
    v1 ratio safety:
      - If needs includes 'protect ERA/WHIP', filter out pitchers with clearly bad baseline ratios.
      - Pool uses baseline_stats_by_id (Yahoo stat ids); stat_map translates ids -> names.
    """
    if not pool:
        return pool

    protect = any("protect ERA/WHIP" in n for n in needs)
    if not protect:
        return pool

    # Find the Yahoo stat-id keys that correspond to ERA/WHIP (strings)
    era_ids = {sid for sid, name in (stat_map or {}).items() if "EARNED RUN AVERAGE" in str(name).upper()}
    whip_ids = {sid for sid, name in (stat_map or {}).items() if ("WALKS" in str(name).upper() and "HITS" in str(name).upper() and "INNINGS" in str(name).upper())}

    def _stat_float(stats: dict, ids: set[str]) -> Optional[float]:
        for sid in ids:
            if sid in stats:
                try:
                    s = str(stats[sid]).strip()
                    if s == "":
                        continue
                    return float(s)
                except Exception:
                    continue
        return None

    kept: List[dict] = []
    for p in pool:
        pos = str(p.get("pos") or "")
        is_pitcher = ("SP" in pos) or ("RP" in pos) or ("P" in pos)
        if is_pitcher:
            stats = p.get("baseline_stats_by_id") or {}
            if not isinstance(stats, dict):
                stats = {}

            era_f = _stat_float(stats, era_ids)
            whip_f = _stat_float(stats, whip_ids)

            # Hard guardrails (tunable)
            if era_f is not None and era_f > 4.40:
                continue
            if whip_f is not None and whip_f > 1.35:
                continue

        kept.append(p)

    return kept
