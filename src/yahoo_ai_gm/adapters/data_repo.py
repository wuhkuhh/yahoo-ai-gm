import json
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class DataRepo:
    stat_map_path: str
    waiver_pool_baseline_path: str
    rp_pool_baseline_path: str

    def load_stat_map(self) -> Dict[str, Any]:
        with open(self.stat_map_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_waiver_pool_baseline(self) -> List[Dict[str, Any]]:
        with open(self.waiver_pool_baseline_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_rp_pool_baseline(self) -> List[Dict[str, Any]]:
        with open(self.rp_pool_baseline_path, "r", encoding="utf-8") as f:
            return json.load(f)
