# yahoo-ai-gm

AI GM assistant for Yahoo Fantasy Baseball (10-team, H2H categories, 5x5).

## Goals
- Daily lineup recommendations
- Streaming pitcher recommendations
- Waiver adds/drops ranked by weekly category pressure

## Local setup
1) Create OAuth tokens (stored locally, not committed).
2) Set config/local/.env and config/local/oauth.json (gitignored).
3) Run:
   - `python scripts/hello_league.py`

## Security
This repo intentionally ignores `.env` and OAuth token files.
