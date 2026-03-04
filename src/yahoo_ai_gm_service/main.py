from __future__ import annotations

import os
from fastapi import FastAPI, Header, HTTPException
from yahoo_ai_gm.yahoo_client import YahooClient

app = FastAPI(title="Yahoo AI GM Service", version="0.1.0")

API_KEY = os.getenv("YAHOO_AI_GM_API_KEY", "").strip()


def require_key(x_api_key: str | None):
    if not API_KEY:
        raise RuntimeError("YAHOO_AI_GM_API_KEY is not set on the server.")
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/league")
def league(x_api_key: str | None = Header(default=None)):
    require_key(x_api_key)
    client = YahooClient.from_local_config()
    xml = client.get(f"league/{client.settings.league_key}")
    return {"league_key": client.settings.league_key, "xml": xml}


@app.get("/team/roster")
def team_roster(x_api_key: str | None = Header(default=None)):
    require_key(x_api_key)
    client = YahooClient.from_local_config()
    xml = client.get(f"team/{client.settings.team_key}/roster")
    return {"team_key": client.settings.team_key, "xml": xml}


@app.get("/league/scoreboard")
def league_scoreboard(x_api_key: str | None = Header(default=None)):
    require_key(x_api_key)
    client = YahooClient.from_local_config()
    xml = client.get(f"league/{client.settings.league_key}/scoreboard")
    return {"league_key": client.settings.league_key, "xml": xml}
