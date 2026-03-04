from functools import lru_cache
from yahoo_ai_gm.adapters.data_repo import DataRepo
from yahoo_ai_gm.adapters.yahoo_client import YahooClient


@lru_cache
def get_data_repo() -> DataRepo:
    return DataRepo(
        stat_map_path="data/stat_map.json",
        waiver_pool_baseline_path="data/waiver_pool_baseline_2025.json",
        rp_pool_baseline_path="data/pool_RP_200_baseline_2025.json",
    )


@lru_cache
def get_yahoo_client() -> YahooClient:
    return YahooClient()
