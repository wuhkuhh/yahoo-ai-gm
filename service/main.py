from pathlib import Path
from fastapi.responses import PlainTextResponse
from fastapi import FastAPI, HTTPException, Query
from service.routes.waivers import router as waivers_router
from yahoo_ai_gm.snapshot.store import load_snapshot
from yahoo_ai_gm.analysis.category_pressure import pressure_report
from yahoo_ai_gm.analysis.roster_inefficiency import roster_inefficiency_report
from yahoo_ai_gm.analysis.waiver_engine import waiver_recommendations

app = FastAPI(title="Yahoo AI GM Service")
app.include_router(waivers_router)


def _get_snapshot_or_404(week: int):
    try:
        return load_snapshot(week)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _latest_week() -> int:
    snapshots_dir = Path("data/snapshots")
    if not snapshots_dir.exists():
        raise HTTPException(status_code=404, detail="No snapshots directory found.")
    weeks = []
    for f in snapshots_dir.glob("week_*.snapshot.json"):
        try:
            weeks.append(int(f.name.split("_")[1].split(".")[0]))
        except (IndexError, ValueError):
            continue
    if not weeks:
        raise HTTPException(status_code=404, detail="No snapshot files found in data/snapshots/.")
    return max(weeks)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/analysis/{week}/pressure")
def get_pressure(week: int):
    snap = _get_snapshot_or_404(week)
    return pressure_report(snap).model_dump()


@app.get("/analysis/{week}/inefficiency")
def get_inefficiency(week: int):
    snap = _get_snapshot_or_404(week)
    return roster_inefficiency_report(snap).model_dump()


@app.get("/analysis/{week}/waivers")
def get_waivers_by_week(week: int):
    snap = _get_snapshot_or_404(week)
    return waiver_recommendations(snap).model_dump()


@app.get("/snapshot")
def get_snapshot(week: int = Query(None)):
    w = week if week is not None else _latest_week()
    snap = _get_snapshot_or_404(w)
    return snap.model_dump()


@app.get("/pressure")
def get_pressure_latest(week: int = Query(None)):
    w = week if week is not None else _latest_week()
    snap = _get_snapshot_or_404(w)
    return pressure_report(snap).model_dump()


@app.get("/inefficiency")
def get_inefficiency_latest(week: int = Query(None)):
    w = week if week is not None else _latest_week()
    snap = _get_snapshot_or_404(w)
    return roster_inefficiency_report(snap).model_dump()


@app.get("/waivers")
def get_waivers_latest(week: int = Query(None)):
    w = week if week is not None else _latest_week()
    snap = _get_snapshot_or_404(w)
    return waiver_recommendations(snap).model_dump()

@app.get("/report", response_class=PlainTextResponse)
def get_report():
    p = Path("data/reports/latest.md")
    if not p.exists():
        raise HTTPException(status_code=404, detail="No report generated yet. Run daily_report.py first.")
    return p.read_text(encoding="utf-8")
