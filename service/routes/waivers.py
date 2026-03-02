from fastapi import APIRouter, Depends, Query, HTTPException

from service.deps import get_data_repo, get_yahoo_client
from yahoo_ai_gm.use_cases.get_waivers import WaiverInputs, get_waivers

router = APIRouter()

@router.get("/live/waivers")
def waivers(
    league_key: str = Query(...),
    team_key: str = Query(...),
    week: int = Query(..., ge=1, le=30),
    pool: str = Query("data/waiver_pool_baseline_2025.json"),
    sv_pool: str = Query("data/pool_RP_200_baseline_2025.json"),
    ratio_mode: str = Query("protect", pattern="^(protect|push)$"),
    yahoo_client=Depends(get_yahoo_client),
    data_repo=Depends(get_data_repo),
):
    inputs = WaiverInputs(
        league_key=league_key,
        team_key=team_key,
        week=week,
        pool_path=pool,
        sv_pool_path=sv_pool,
        ratio_mode=ratio_mode,
    )
    try:
        return get_waivers(inputs, yahoo_client=yahoo_client, data_repo=data_repo)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
