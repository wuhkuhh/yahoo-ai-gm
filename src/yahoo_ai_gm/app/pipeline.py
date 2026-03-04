from __future__ import annotations

from typing import Any, Optional


class Pipeline:
    """
    Orchestration boundary:
      - keep imports lazy so FastAPI startup is fast and never blocks
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir

    def get_snapshot(self, week: int) -> dict[str, Any]:
        from yahoo_ai_gm.snapshot.store import load_snapshot

        snapshot = load_snapshot(week=week)
        return snapshot.model_dump() if hasattr(snapshot, "model_dump") else snapshot

    def get_pressure(self, week: int) -> dict[str, Any]:
        from yahoo_ai_gm.snapshot.store import load_snapshot
        from yahoo_ai_gm.analysis.category_pressure import pressure_report

        snapshot = load_snapshot(week=week)
        report = pressure_report(snapshot)
        return report.model_dump() if hasattr(report, "model_dump") else report

    def get_inefficiency(self, week: int) -> dict[str, Any]:
        from yahoo_ai_gm.snapshot.store import load_snapshot
        from yahoo_ai_gm.analysis.roster_inefficiency import inefficiency_report

        snapshot = load_snapshot(week=week)
        report = inefficiency_report(snapshot)
        return report.model_dump() if hasattr(report, "model_dump") else report

    def get_waivers(
        self,
        week: int,
        pool_path: str,
        sv_pool_path: Optional[str] = None,
    ) -> dict[str, Any]:
        from yahoo_ai_gm.snapshot.store import load_snapshot
        from yahoo_ai_gm.analysis.waiver_engine import waiver_recommendations

        snapshot = load_snapshot(week=week)
        report = waiver_recommendations(snapshot, pool_path=pool_path, sv_pool_path=sv_pool_path)
        return report.model_dump() if hasattr(report, "model_dump") else report
