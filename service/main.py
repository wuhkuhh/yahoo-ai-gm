from fastapi import FastAPI, HTTPException
from service.routes.waivers import router as waivers_router
from yahoo_ai_gm_service.routers.reports import router as reports_router
from yahoo_ai_gm.snapshot.store import load_snapshot
from yahoo_ai_gm.analysis.category_pressure import pressure_report
from yahoo_ai_gm.analysis.roster_inefficiency import roster_inefficiency_report
from yahoo_ai_gm.analysis.waiver_engine import waiver_recommendations

app = FastAPI(title="Yahoo AI GM Service")
app.include_router(reports_router)
app.include_router(waivers_router)

@app.get("/health")
def health():
    return {"ok": True}


def _get_snapshot_or_404(week: int):
    try:
        return load_snapshot(week)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/analysis/{week}/pressure")
def get_pressure(week: int):
    snap = _get_snapshot_or_404(week)
    return pressure_report(snap).model_dump()


@app.get("/analysis/{week}/inefficiency")
def get_inefficiency(week: int):
    snap = _get_snapshot_or_404(week)
    return roster_inefficiency_report(snap).model_dump()


@app.get("/analysis/{week}/waivers")
def get_waivers(week: int):
    snap = _get_snapshot_or_404(week)
    return waiver_recommendations(snap).model_dump()
