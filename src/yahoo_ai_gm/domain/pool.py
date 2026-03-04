from pydantic import BaseModel, Field
from typing import List, Optional


class PoolPlayer(BaseModel):
    player_key: str
    name: str
    team_abbr: Optional[str] = None
    eligible_positions: List[str] = Field(default_factory=list)
    status: Optional[str] = None
