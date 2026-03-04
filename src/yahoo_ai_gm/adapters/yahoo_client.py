from typing import Any, Dict, List


class YahooClient:
    """
    Thin wrapper: implement these by delegating to your existing Yahoo pull code.
    Keep this as the ONLY place that touches network/auth.
    """

    def get_roster(self, team_key: str) -> Dict[str, Any]:
        raise NotImplementedError("Wire to existing roster pull")

    def get_scoreboard(self, league_key: str, week: int) -> Dict[str, Any]:
        raise NotImplementedError("Wire to existing scoreboard pull")

    def get_waiver_pool(self, league_key: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("Wire to existing waiver pool pull")
