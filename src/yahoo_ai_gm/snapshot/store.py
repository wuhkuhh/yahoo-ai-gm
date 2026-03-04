from __future__ import annotations

from pathlib import Path
from yahoo_ai_gm.domain.models import Snapshot

SNAPSHOT_DIR = Path("data/snapshots")


def snapshot_path(week: int) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SNAPSHOT_DIR / f"week_{week}.snapshot.json"


def save_snapshot(snapshot: Snapshot) -> Path:
    path = snapshot_path(snapshot.week)
    # Pydantic v2: model_dump_json supports indent but not sort_keys in your version.
    path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_snapshot(week: int) -> Snapshot:
    path = snapshot_path(week)
    if not path.exists():
        raise FileNotFoundError(f"No snapshot found at {path}. Run refresh first.")
    return Snapshot.model_validate_json(path.read_text(encoding="utf-8"))
