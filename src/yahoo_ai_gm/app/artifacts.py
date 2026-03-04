from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactStore:
    """
    Single source of truth for artifact filenames + basic JSON read/write.
    """
    root: Path

    def path(self, name: str) -> Path:
        return self.root / name

    def roster_path(self) -> Path:
        return self.path("roster.json")

    def scoreboard_path(self, week: int) -> Path:
        return self.path(f"scoreboard_week_{week}.json")

    def stat_map_path(self) -> Path:
        return self.path("stat_map.json")

    def snapshot_path(self, week: int) -> Path:
        return self.path(f"snapshot_week_{week}.json")

    def pressure_path(self, week: int) -> Path:
        return self.path(f"pressure_week_{week}.json")

    def inefficiency_path(self, week: int) -> Path:
        return self.path(f"inefficiency_week_{week}.json")

    def waiver_report_path(self, week: int) -> Path:
        return self.path(f"waivers_week_{week}.json")

    def read_json(self, p: Path) -> Any:
        return json.loads(p.read_text(encoding="utf-8"))

    def write_json(self, p: Path, obj: Any) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
