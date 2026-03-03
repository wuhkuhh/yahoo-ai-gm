#!/usr/bin/env bash
set -euo pipefail

cd /root/yahoo-ai-gm
source .venv/bin/activate

echo "[refresh_snapshot] Starting at $(date)"

echo "[refresh_snapshot] Pulling scoreboard..."
python3 scripts/pull_scoreboard_week.py

echo "[refresh_snapshot] Pulling roster snapshot..."
python3 scripts/pull_roster_snapshot.py

# Derive week from the most recent scoreboard file
WEEK=$(ls data/scoreboard_week_*.json 2>/dev/null \
  | sed 's/.*scoreboard_week_\([0-9]*\)\.json/\1/' \
  | sort -n | tail -1)

if [ -z "$WEEK" ]; then
  echo "[refresh_snapshot] ERROR: No scoreboard file found, cannot build snapshot."
  exit 1
fi

echo "[refresh_snapshot] Building snapshot for week $WEEK..."
python3 scripts/build_snapshot.py \
  --week "$WEEK" \
  --league-key 469.l.40206 \
  --my-team-key 469.l.40206.t.6 \
  --roster-json data/roster.json \
  --scoreboard-json "data/scoreboard_week_${WEEK}.json"

echo "[refresh_snapshot] Done at $(date)"
