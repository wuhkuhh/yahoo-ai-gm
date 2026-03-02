from fastapi import APIRouter, Depends, Query

from yahoo_ai_gm.app.pipeline import Pipeline
from yahoo_ai_gm_service.deps import get_pipeline


router = APIRouter(tags=["reports"])


@router.get("/snapshot")
def snapshot(week: int = Query(..., ge=1), pipe: Pipeline = Depends(get_pipeline)):
    return pipe.get_snapshot(week)


@router.get("/pressure")
def pressure(week: int = Query(..., ge=1), pipe: Pipeline = Depends(get_pipeline)):
    return pipe.get_pressure(week)


@router.get("/inefficiency")
def inefficiency(week: int = Query(..., ge=1), pipe: Pipeline = Depends(get_pipeline)):
    return pipe.get_inefficiency(week)


@router.get("/waivers")
def waivers(
    week: int = Query(..., ge=1),
    pool: str = Query(...),
    sv_pool: str | None = Query(None),
    pipe: Pipeline = Depends(get_pipeline),
):
    return pipe.get_waivers(
        week=week,
        pool_path=pool,
        sv_pool_path=sv_pool,
    )
