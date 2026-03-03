from pathlib import Path
from fastapi.responses import PlainTextResponse
from fastapi import FastAPI, HTTPException, Query
from service.routes.waivers import router as waivers_router
from yahoo_ai_gm.snapshot.store import load_snapshot
from yahoo_ai_gm.analysis.category_pressure import pressure_report
from yahoo_ai_gm.analysis.roster_inefficiency import roster_inefficiency_report
from yahoo_ai_gm.analysis.waiver_engine import waiver_recommendations
from yahoo_ai_gm.use_cases.get_trades import get_trade_report

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


@app.get("/trades")
def get_trades(
    n: int = Query(default=10, ge=1, le=50, description="Number of suggestions"),
    n_teams: int = Query(default=12, ge=2, le=20, description="League size"),
    max_adp: float = Query(default=300.0, description="Max ADP for receive candidates"),
):
    data_dir = Path("data")
    try:
        report = get_trade_report(
            data_dir=data_dir,
            n_suggestions=n,
            n_teams=n_teams,
            min_receive_adp=max_adp,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "generated_at": report.generated_at.isoformat(),
        "fg_projection_date": report.fg_projection_date,
        "roster_size": report.roster_size,
        "unmatched_players": report.unmatched_players,
        "weak_categories": report.weak_categories,
        "strong_categories": report.strong_categories,
        "suggestion_count": len(report.suggestions),
        "suggestions": report.suggestions,
    }


@app.get("/matchup")
def get_matchup(week: int = Query(None)):
    from yahoo_ai_gm.use_cases.get_matchup import get_matchup_report
    data_dir = Path("data")
    try:
        report = get_matchup_report(data_dir=data_dir, week=week)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {
        "generated_at": report.generated_at.isoformat(),
        "week": report.week,
        **report.projection,
    }


@app.get("/trades/multi")
def get_multi_trades(
    n: int = Query(default=10, ge=1, le=20, description="Suggestions per trade size"),
    n_teams: int = Query(default=10, ge=2, le=20, description="League size"),
):
    from yahoo_ai_gm.use_cases.get_multi_trades import get_multi_trade_report
    data_dir = Path("data")
    try:
        report = get_multi_trade_report(data_dir=data_dir, n_suggestions=n, n_teams=n_teams)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {
        "generated_at": report.generated_at.isoformat(),
        "roster_size": report.roster_size,
        "trade_sizes": report.trade_sizes,
    }


@app.get("/adddrop")
def get_adddrop(
    week: int = Query(None),
    max_moves: int = Query(default=6, ge=1, le=10),
    n_teams: int = Query(default=10, ge=2, le=20),
):
    from yahoo_ai_gm.use_cases.get_adddrop import get_adddrop_report
    data_dir = Path("data")
    try:
        report = get_adddrop_report(
            data_dir=data_dir,
            week=week,
            max_moves=max_moves,
            n_teams=n_teams,
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {
        "generated_at": report.generated_at.isoformat(),
        "week": report.week,
        "max_moves": report.max_moves,
        **report.plan,
    }


@app.get("/ratio-risk")
def get_ratio_risk(week: int = Query(None)):
    from yahoo_ai_gm.use_cases.get_ratio_risk import get_ratio_risk_report
    data_dir = Path("data")
    try:
        report = get_ratio_risk_report(data_dir=data_dir, week=week)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {
        "generated_at": report.generated_at.isoformat(),
        "week": report.week,
        "pitcher_count": report.pitcher_count,
        "profiles": report.profiles,
    }


@app.get("/adddrop/execute")
def execute_adddrop(
    week: int = Query(None),
    max_moves: int = Query(default=6, ge=1, le=10),
    dry_run: bool = Query(default=True, description="Set false only if YAHOO_AUTO_EXECUTE=true"),
):
    from yahoo_ai_gm.use_cases.execute_adddrop import get_execution_report
    import os
    data_dir = Path("data")
    auto_execute = os.environ.get("YAHOO_AUTO_EXECUTE", "false").strip().lower() == "true"
    # API can never override the env var gate
    effective_dry_run = True if not auto_execute else dry_run
    try:
        report = get_execution_report(
            data_dir=data_dir,
            week=week,
            max_moves=max_moves,
            dry_run=effective_dry_run,
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {
        "generated_at": report.generated_at.isoformat(),
        "week": report.week,
        "dry_run": report.dry_run,
        "auto_execute_enabled": report.auto_execute_enabled,
        "moves_planned": report.moves_planned,
        "moves_attempted": report.moves_attempted,
        "moves_succeeded": report.moves_succeeded,
        "results": report.results,
    }


@app.get("/standings")
def get_standings(
    week: int = Query(default=1, ge=1, le=23),
    n_teams: int = Query(default=10, ge=2, le=20),
):
    from yahoo_ai_gm.use_cases.get_standings import get_standings_report
    data_dir = Path("data")
    try:
        report = get_standings_report(
            data_dir=data_dir,
            current_week=week,
            n_teams=n_teams,
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {
        "generated_at": report.generated_at.isoformat(),
        **report.trajectory,
    }


@app.get("/trade-value")
def get_trade_value(week: int = Query(default=1, ge=1, le=23)):
    from yahoo_ai_gm.use_cases.get_trade_value import get_trade_value_report
    data_dir = Path("data")
    try:
        report = get_trade_value_report(data_dir=data_dir, week=week)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {
        "generated_at": report.generated_at.isoformat(),
        "week": report.week,
        "sell_high": report.sell_high,
        "cut_bait": report.cut_bait,

        "players": report.players,
    }


@app.get("/trade-value")
def get_trade_value(week: int = Query(None)):
    from yahoo_ai_gm.use_cases.get_trade_value import get_trade_value_report
    data_dir = Path("data")
    try:
        report = get_trade_value_report(data_dir=data_dir, week=week)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {
        "generated_at": report.generated_at.isoformat(),
        "week": report.week,
        "sell_high": report.sell_high,
        "cut_bait": report.cut_bait,
        "watch": report.watch,
        "all_players": report.players,
    }

