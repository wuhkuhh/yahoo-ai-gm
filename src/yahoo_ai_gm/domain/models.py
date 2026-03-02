from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CategoryValue(BaseModel):
    category: str
    value: float | int | str | None = None


class TeamTotals(BaseModel):
    team_key: str
    team_name: str
    totals: Dict[str, float] = Field(default_factory=dict)


class MatchupSnapshot(BaseModel):
    week: int
    my_team: TeamTotals
    opp_team: TeamTotals


class PlayerSnapshot(BaseModel):
    player_key: str
    name: str
    eligible_positions: List[str] = Field(default_factory=list)
    selected_position: Optional[str] = None
    status: Optional[str] = None
    team_abbr: Optional[str] = None


class RosterSnapshot(BaseModel):
    week: int
    team_key: str
    players: List[PlayerSnapshot] = Field(default_factory=list)


class Snapshot(BaseModel):
    snapshot_version: str = "1.0"
    league_key: str
    week: int
    pulled_at: datetime = Field(default_factory=datetime.utcnow)

    matchup: MatchupSnapshot
    roster: RosterSnapshot

    stat_map: Dict[str, Any] = Field(default_factory=dict)
    raw_refs: Dict[str, str] = Field(default_factory=dict)


class CategoryPressure(BaseModel):
    category: str
    my_value: float
    opp_value: float
    diff: float
    posture: str
    note: Optional[str] = None


class PressureReport(BaseModel):
    week: int
    team_key: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    pressures: List[CategoryPressure]


class Inefficiency(BaseModel):
    kind: str
    severity: str
    player_key: Optional[str] = None
    player_name: Optional[str] = None
    note: str


class InefficiencyReport(BaseModel):
    week: int
    team_key: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    items: List[Inefficiency] = Field(default_factory=list)


class WaiverSuggestion(BaseModel):
    add_player_key: str
    add_name: str
    drop_player_key: str
    drop_name: str
    reason: str
    confidence: str = "med"
    category_impacts: Dict[str, float] = Field(default_factory=dict)


class WaiverReport(BaseModel):
    week: int
    team_key: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    suggestions: List[WaiverSuggestion] = Field(default_factory=list)
