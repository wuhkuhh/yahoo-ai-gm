from dataclasses import dataclass
from typing import Any, Dict, Optional, List
import subprocess
import sys
import json
from pathlib import Path

from yahoo_ai_gm.snapshot.store import load_snapshot
from yahoo_ai_gm.analysis.waiver_engine import waiver_recommendations


@dataclass(frozen=True)
class WaiverInputs:
    league_key: str
    team_key: str
    week: int
    pool_path: str
    sv_pool_path: Optional[str] = None
    ratio_mode: str = "protect"


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
        )


def _load_json_list(path: Optional[str]) -> Optional[List[dict]]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Pool file not found: {path}")
    data = json.loads(p.read_text(encoding="utf-8"))

    # Common shapes:
    #   - [ {...}, {...} ]
    #   - {"players": [ ... ]}
    #   - {"pool": [ ... ]}
    #   - {"items": [ ... ]}
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("players", "pool", "items", "data", "waiver_pool", "results", "value"):
            v = data.get(key)
            if isinstance(v, list):
                return v
        # As a fallback, return the first list-valued field
        for k, v in data.items():
            if isinstance(v, list):
                return v
        raise ValueError(f"Pool JSON dict at {path} contains no list field. Keys={list(data.keys())[:20]}")

    raise ValueError(f"Pool JSON must be a list or dict at {path}, got {type(data).__name__}")


def get_waivers(inputs: WaiverInputs, yahoo_client, data_repo) -> Dict[str, Any]:
    # 1) Pull live Yahoo data -> files
    _run([sys.executable, "scripts/pull_scoreboard_week.py"])
    _run([sys.executable, "scripts/pull_roster_snapshot.py"])

    # 2) Build snapshot for requested week using query params
    _run([
        sys.executable,
        "scripts/build_snapshot.py",
        "--week", str(inputs.week),
        "--league-key", inputs.league_key,
        "--my-team-key", inputs.team_key,
        "--roster-json", "data/roster.json",
        "--scoreboard-json", f"data/scoreboard_week_{inputs.week}.json",
    ])

    # 3) Load snapshot + pools
    snapshot = load_snapshot(inputs.week)
    pool = _load_json_list(inputs.pool_path)
    sv_pool = _load_json_list(inputs.sv_pool_path)

    # 4) Run engine (expects lists, not paths)
    report = waiver_recommendations(snapshot, pool=pool, sv_pool=sv_pool, ratio_mode=inputs.ratio_mode)
    return report.model_dump() if hasattr(report, "model_dump") else report
