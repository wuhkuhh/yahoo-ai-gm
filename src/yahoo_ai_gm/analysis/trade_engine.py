"""
src/yahoo_ai_gm/analysis/trade_engine.py

Layer 2 — Pure Analysis. No FastAPI, no I/O, no Yahoo client.

Trade suggestion engine using FanGraphs 2026 Steamer projections.

Algorithm:
1. Build PlayerProjection from FG data for all players
2. Match rostered players to FG projections by name
3. Compute MyTeamProjection: aggregate counting stats, weighted ratio stats
4. Compute LeagueAverages from full FG population
5. Compute z-scores per category: where does my team rank?
6. Identify weakest categories (need) and strongest (surplus)
7. For each roster player:
   - Compute team stats WITHOUT that player (give simulation)
   - Find pool candidates that fill the need gaps
   - Score trade by: gain in weak cats - loss in strong cats
8. Return ranked TradeSuggestion list
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Stat category config — must match stat_map IDs
# ---------------------------------------------------------------------------

# Maps FG column name -> Yahoo stat_id
FG_TO_YAHOO_STAT_ID: dict[str, str] = {
    # Batting
    "R": "7",
    "HR": "12",
    "RBI": "13",
    "SB": "16",
    "AVG": "3",
    # Pitching
    "W": "28",
    "SO": "42",
    "SV": "32",
    "ERA": "26",
    "WHIP": "27",
    "IP": "50",
}

# Scoring categories used in this league (from stat_map)
SCORING_CATS = {
    "batting": ["R", "HR", "RBI", "SB", "AVG"],
    "pitching": ["W", "SO", "SV", "ERA", "WHIP", "IP"],
}

# Lower is better for these (ratio stats)
LOWER_IS_BETTER = {"ERA", "WHIP"}

# AVG is a weighted ratio — needs AB weighting
RATIO_CATS = {"AVG"}

# Minimum IP required to contribute to ERA/WHIP weighting
MIN_IP_WEIGHT = 1.0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PlayerProjection:
    name: str
    team: str
    player_type: str          # "batter" or "pitcher"
    fg_playerids: str         # FG playerids string
    mlb_id: Optional[int]     # xMLBAMID

    # Batting
    pa: float = 0.0
    ab: float = 0.0
    r: float = 0.0
    hr: float = 0.0
    rbi: float = 0.0
    sb: float = 0.0
    avg: float = 0.0
    bb_bat: float = 0.0

    # Pitching
    ip: float = 0.0
    w: float = 0.0
    so: float = 0.0
    sv: float = 0.0
    era: float = 0.0
    whip: float = 0.0
    hld: float = 0.0

    # Meta
    adp: float = 999.0
    war: float = 0.0


@dataclass
class TeamProjection:
    """Aggregated projection for a set of players."""
    players: list[PlayerProjection] = field(default_factory=list)

    # Counting stats (sum)
    r: float = 0.0
    hr: float = 0.0
    rbi: float = 0.0
    sb: float = 0.0
    w: float = 0.0
    so: float = 0.0
    sv: float = 0.0
    total_ab: float = 0.0
    total_hits: float = 0.0
    total_ip: float = 0.0
    total_er: float = 0.0
    total_baserunners: float = 0.0  # H + BB for WHIP

    @property
    def avg(self) -> float:
        return self.total_hits / self.total_ab if self.total_ab > 0 else 0.0

    @property
    def era(self) -> float:
        return (self.total_er * 9.0) / self.total_ip if self.total_ip > 0 else 99.0

    @property
    def whip(self) -> float:
        return self.total_baserunners / self.total_ip if self.total_ip > 0 else 99.0

    def cat_value(self, cat: str) -> float:
        mapping = {
            "R": self.r, "HR": self.hr, "RBI": self.rbi, "SB": self.sb,
            "AVG": self.avg, "W": self.w, "SO": self.so, "SV": self.sv,
            "ERA": self.era, "WHIP": self.whip, "IP": self.total_ip,
        }
        return mapping.get(cat, 0.0)


@dataclass
class CategoryScore:
    cat: str
    my_value: float
    league_mean: float
    league_stdev: float
    z_score: float           # positive = above average
    rank_label: str          # "strength" | "neutral" | "weakness"


@dataclass
class TradeSuggestion:
    give_player: PlayerProjection
    receive_player: PlayerProjection
    trade_score: float               # higher = better trade for us
    cats_improved: list[str]
    cats_hurt: list[str]
    give_impact: dict[str, float]    # cat -> delta if we remove give_player
    receive_impact: dict[str, float] # cat -> delta if we add receive_player
    rationale: str


# ---------------------------------------------------------------------------
# FG projection loader
# ---------------------------------------------------------------------------

def load_projections_from_fg(
    bat_data: dict,
    pit_data: dict,
) -> list[PlayerProjection]:
    """
    Parse loaded FG JSON dicts into PlayerProjection objects.
    bat_data / pit_data: contents of fg_proj_bat_2026.json / fg_proj_pit_2026.json
    """
    projections: list[PlayerProjection] = []

    def _f(val, default: float = 0.0) -> float:
        try:
            v = float(val)
            return v if v == v else default  # NaN check
        except (TypeError, ValueError):
            return default

    for p in bat_data.get("players", []):
        name = p.get("PlayerName", "")
        if not name:
            continue
        ab = _f(p.get("AB"))
        hits = _f(p.get("H"))
        avg = _f(p.get("AVG")) if _f(p.get("AB")) > 0 else (hits / ab if ab > 0 else 0.0)
        proj = PlayerProjection(
            name=name,
            team=p.get("Team") or "",
            player_type="batter",
            fg_playerids=str(p.get("playerids") or ""),
            mlb_id=int(p["xMLBAMID"]) if p.get("xMLBAMID") else None,
            pa=_f(p.get("PA")),
            ab=ab,
            r=_f(p.get("R")),
            hr=_f(p.get("HR")),
            rbi=_f(p.get("RBI")),
            sb=_f(p.get("SB")),
            avg=avg,
            bb_bat=_f(p.get("BB")),
            adp=_f(p.get("ADP"), default=999.0),
            war=_f(p.get("WAR")),
        )
        projections.append(proj)

    for p in pit_data.get("players", []):
        name = p.get("PlayerName", "")
        if not name:
            continue
        ip = _f(p.get("IP"))
        era = _f(p.get("ERA"), default=99.0)
        whip = _f(p.get("WHIP"), default=99.0)
        # Reconstruct ER and baserunners from ERA/WHIP/IP for aggregation
        er = (era * ip) / 9.0 if ip > 0 else 0.0
        baserunners = whip * ip if ip > 0 else 0.0
        proj = PlayerProjection(
            name=name,
            team=p.get("Team") or "",
            player_type="pitcher",
            fg_playerids=str(p.get("playerids") or ""),
            mlb_id=int(p["xMLBAMID"]) if p.get("xMLBAMID") else None,
            ip=ip,
            w=_f(p.get("W")),
            so=_f(p.get("SO")),
            sv=_f(p.get("SV")),
            era=era,
            whip=whip,
            hld=_f(p.get("HLD")),
            adp=_f(p.get("ADP"), default=999.0),
            war=_f(p.get("WAR")),
        )
        # Store ER and baserunners for aggregation
        proj._er = er
        proj._baserunners = baserunners
        projections.append(proj)

    return projections


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Lowercase, strip accents (rough), remove punctuation."""
    name = name.lower().strip()
    # Basic accent normalization
    replacements = {
        "á": "a", "à": "a", "ä": "a", "â": "a",
        "é": "e", "è": "e", "ë": "e", "ê": "e",
        "í": "i", "ì": "i", "ï": "i", "î": "i",
        "ó": "o", "ò": "o", "ö": "o", "ô": "o",
        "ú": "u", "ù": "u", "ü": "u", "û": "u",
        "ñ": "n", "ç": "c",
    }
    for accented, plain in replacements.items():
        name = name.replace(accented, plain)
    name = re.sub(r"[^a-z0-9 ]", "", name)
    return name


def build_fg_lookup(projections: list[PlayerProjection]) -> dict[str, PlayerProjection]:
    """Build name -> projection lookup with normalized keys."""
    lookup: dict[str, PlayerProjection] = {}
    for proj in projections:
        key = _normalize_name(proj.name)
        lookup[key] = proj
    return lookup


def match_roster_to_fg(
    roster: list[dict],
    fg_lookup: dict[str, PlayerProjection],
) -> dict[str, Optional[PlayerProjection]]:
    """
    Match roster player dicts to FG projections.
    Returns {full_name: PlayerProjection | None}
    """
    result: dict[str, Optional[PlayerProjection]] = {}
    for player in roster:
        name = player.get("full_name") or player.get("name") or ""
        key = _normalize_name(name)
        match = fg_lookup.get(key)
        if match is None:
            # Try last-name-only fallback for common truncations
            parts = key.split()
            if len(parts) >= 2:
                last = parts[-1]
                candidates = [v for k, v in fg_lookup.items() if k.endswith(last)]
                if len(candidates) == 1:
                    match = candidates[0]
        result[name] = match
    return result


# ---------------------------------------------------------------------------
# Team projection builder
# ---------------------------------------------------------------------------

def build_team_projection(projections: list[PlayerProjection]) -> TeamProjection:
    tp = TeamProjection(players=list(projections))
    for p in projections:
        if p.player_type == "batter":
            tp.r += p.r
            tp.hr += p.hr
            tp.rbi += p.rbi
            tp.sb += p.sb
            tp.total_ab += p.ab
            tp.total_hits += p.avg * p.ab if p.ab > 0 else 0.0
        else:
            tp.w += p.w
            tp.so += p.so
            tp.sv += p.sv
            tp.total_ip += p.ip
            er = getattr(p, "_er", (p.era * p.ip / 9.0) if p.ip > 0 else 0.0)
            br = getattr(p, "_baserunners", p.whip * p.ip if p.ip > 0 else 0.0)
            tp.total_er += er
            tp.total_baserunners += br
    return tp


# ---------------------------------------------------------------------------
# League average computation
# ---------------------------------------------------------------------------

def compute_league_averages(
    all_projections: list[PlayerProjection],
    n_teams: int = 12,
    roster_size: int = 23,
) -> dict[str, tuple[float, float]]:
    """
    Estimate league average category values by simulating N teams
    using top ADP players. Returns {cat: (mean, stdev)}.
    """
    # Take top ADP players as proxy for rostered players
    rostered_count = n_teams * roster_size
    batters = sorted(
        [p for p in all_projections if p.player_type == "batter"],
        key=lambda p: p.adp
    )[:rostered_count // 2]
    pitchers = sorted(
        [p for p in all_projections if p.player_type == "pitcher"],
        key=lambda p: p.adp
    )[:rostered_count // 2]

    team_size_bat = len(batters) // n_teams
    team_size_pit = len(pitchers) // n_teams

    team_values: dict[str, list[float]] = {cat: [] for cat in
        SCORING_CATS["batting"] + SCORING_CATS["pitching"]}

    for i in range(n_teams):
        team_bat = batters[i * team_size_bat:(i + 1) * team_size_bat]
        team_pit = pitchers[i * team_size_pit:(i + 1) * team_size_pit]
        tp = build_team_projection(team_bat + team_pit)
        for cat in SCORING_CATS["batting"] + SCORING_CATS["pitching"]:
            team_values[cat].append(tp.cat_value(cat))

    averages: dict[str, tuple[float, float]] = {}
    for cat, vals in team_values.items():
        if len(vals) < 2:
            averages[cat] = (vals[0] if vals else 0.0, 1.0)
        else:
            averages[cat] = (statistics.mean(vals), statistics.stdev(vals) or 1.0)

    return averages


# ---------------------------------------------------------------------------
# Category scoring
# ---------------------------------------------------------------------------

def score_team_categories(
    my_team: TeamProjection,
    league_averages: dict[str, tuple[float, float]],
) -> list[CategoryScore]:
    scores = []
    all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
    for cat in all_cats:
        my_val = my_team.cat_value(cat)
        mean, stdev = league_averages.get(cat, (0.0, 1.0))
        z = (my_val - mean) / stdev
        if cat in LOWER_IS_BETTER:
            z = -z  # flip so positive = good
        if z >= 0.5:
            label = "strength"
        elif z <= -0.5:
            label = "weakness"
        else:
            label = "neutral"
        scores.append(CategoryScore(
            cat=cat,
            my_value=my_val,
            league_mean=mean,
            league_stdev=stdev,
            z_score=z,
            rank_label=label,
        ))
    return scores


# ---------------------------------------------------------------------------
# Impact computation
# ---------------------------------------------------------------------------

def compute_player_impact(
    player: PlayerProjection,
    current_team: TeamProjection,
    action: str,  # "remove" or "add"
) -> dict[str, float]:
    """
    Compute category delta if player is added or removed from team.
    Returns {cat: delta} where positive = improvement.
    """
    sign = -1.0 if action == "remove" else 1.0

    # Simulate new team
    new_players = list(current_team.players)
    if action == "remove":
        new_players = [p for p in new_players if p.name != player.name]
    else:
        new_players = new_players + [player]

    new_tp = build_team_projection(new_players)
    deltas: dict[str, float] = {}

    for cat in SCORING_CATS["batting"] + SCORING_CATS["pitching"]:
        old_val = current_team.cat_value(cat)
        new_val = new_tp.cat_value(cat)
        delta = new_val - old_val
        if cat in LOWER_IS_BETTER:
            delta = -delta  # flip so positive = improvement
        deltas[cat] = delta

    return deltas


# ---------------------------------------------------------------------------
# Main trade engine
# ---------------------------------------------------------------------------

def trade_suggestions(
    roster: list[dict],
    fg_bat_data: dict,
    fg_pit_data: dict,
    n_suggestions: int = 10,
    n_teams: int = 12,
    min_receive_adp: float = 300.0,
    max_give_adp: float = 400.0,
) -> list[TradeSuggestion]:
    """
    Main entry point. Returns ranked TradeSuggestion list.

    Args:
        roster: list of player dicts from roster_snapshot.json
        fg_bat_data: loaded fg_proj_bat_2026.json dict
        fg_pit_data: loaded fg_proj_pit_2026.json dict
        n_suggestions: max suggestions to return
        n_teams: league size for average computation
        min_receive_adp: only suggest receiving players with ADP < this
        max_give_adp: only suggest giving players with ADP < this (valuable enough to trade)
    """
    # 1. Load all FG projections
    all_projections = load_projections_from_fg(fg_bat_data, fg_pit_data)
    fg_lookup = build_fg_lookup(all_projections)

    # 2. Match roster to FG
    roster_matches = match_roster_to_fg(roster, fg_lookup)
    my_projections = [p for p in roster_matches.values() if p is not None]

    unmatched = [name for name, proj in roster_matches.items() if proj is None]
    if unmatched:
        pass  # Caller can log these

    # 3. Build my team projection
    my_team = build_team_projection(my_projections)

    # 4. Compute league averages
    league_averages = compute_league_averages(all_projections, n_teams=n_teams)

    # 5. Score categories
    cat_scores = score_team_categories(my_team, league_averages)
    cat_score_map = {cs.cat: cs for cs in cat_scores}

    weaknesses = [cs for cs in cat_scores if cs.rank_label == "weakness"]
    strengths = [cs for cs in cat_scores if cs.rank_label == "strength"]

    # 6. Build receive candidate pool (not on my roster, reasonable ADP)
    my_names = {_normalize_name(p.name) for p in my_projections}
    receive_pool = [
        p for p in all_projections
        if _normalize_name(p.name) not in my_names
        and p.adp <= min_receive_adp
    ]

    # 7. Build give candidates (my roster, not too irreplaceable)
    give_candidates = [
        p for p in my_projections
        if p.adp <= max_give_adp
    ]

    # 8. Score all give/receive pairs
    suggestions: list[TradeSuggestion] = []

    for give in give_candidates:
        give_impact = compute_player_impact(give, my_team, "remove")

        for receive in receive_pool:
            # Skip same position type mismatches in extreme cases
            # (e.g., don't give only closer for only batter if SV is a strength)

            receive_impact = compute_player_impact(receive, my_team, "add")

            # Net delta per category
            cats_improved = []
            cats_hurt = []
            score = 0.0

            all_cats = SCORING_CATS["batting"] + SCORING_CATS["pitching"]
            for cat in all_cats:
                cs = cat_score_map.get(cat)
                net = give_impact.get(cat, 0.0) + receive_impact.get(cat, 0.0)

                if cs is None:
                    continue

                # Weight the net delta by how much we need improvement in this cat
                # Weak categories count more, strong categories penalize losses more
                need_weight = max(0.0, -cs.z_score)   # higher = we need it more
                surplus_weight = max(0.0, cs.z_score)  # higher = we have surplus

                if net > 0.01:
                    cats_improved.append(cat)
                    score += net * (1.0 + need_weight)
                elif net < -0.01:
                    cats_hurt.append(cat)
                    score -= abs(net) * (1.0 + surplus_weight)

            if score <= 0:
                continue

            # Build rationale string
            improved_str = ", ".join(f"{c}(+{give_impact.get(c,0)+receive_impact.get(c,0):.2f})" for c in cats_improved)
            hurt_str = ", ".join(f"{c}({give_impact.get(c,0)+receive_impact.get(c,0):+.2f})" for c in cats_hurt)
            rationale = f"Give {give.name}, receive {receive.name}."
            if cats_improved:
                rationale += f" Improves: {improved_str}."
            if cats_hurt:
                rationale += f" Costs: {hurt_str}."

            suggestions.append(TradeSuggestion(
                give_player=give,
                receive_player=receive,
                trade_score=score,
                cats_improved=cats_improved,
                cats_hurt=cats_hurt,
                give_impact=give_impact,
                receive_impact=receive_impact,
                rationale=rationale,
            ))

    # Sort by trade score descending
    suggestions.sort(key=lambda s: s.trade_score, reverse=True)

    # Deduplicate: limit to 2 suggestions per give player
    give_counts: dict[str, int] = {}
    deduped: list[TradeSuggestion] = []
    for s in suggestions:
        gname = s.give_player.name
        if give_counts.get(gname, 0) < 2:
            deduped.append(s)
            give_counts[gname] = give_counts.get(gname, 0) + 1
        if len(deduped) >= n_suggestions:
            break

    return deduped


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def suggestion_to_dict(s: TradeSuggestion) -> dict:
    return {
        "give": {
            "name": s.give_player.name,
            "team": s.give_player.team,
            "type": s.give_player.player_type,
            "adp": s.give_player.adp,
        },
        "receive": {
            "name": s.receive_player.name,
            "team": s.receive_player.team,
            "type": s.receive_player.player_type,
            "adp": s.receive_player.adp,
        },
        "trade_score": round(s.trade_score, 3),
        "cats_improved": s.cats_improved,
        "cats_hurt": s.cats_hurt,
        "rationale": s.rationale,
        "cat_impacts": {
            cat: round(s.give_impact.get(cat, 0) + s.receive_impact.get(cat, 0), 3)
            for cat in SCORING_CATS["batting"] + SCORING_CATS["pitching"]
        },
    }
