from functools import lru_cache

from yahoo_ai_gm.app.pipeline import Pipeline


@lru_cache(maxsize=1)
def get_pipeline() -> Pipeline:
    return Pipeline()
