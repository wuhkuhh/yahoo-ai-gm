 # ⬡ Yahoo AI GM

> A production-grade AI-driven fantasy baseball automation system for Yahoo Fantasy.  
> Built for the 2026 season. Fully deployed. Opening Day ready.

---

## What It Does

Yahoo AI GM is a fully automated fantasy baseball intelligence system. It pulls live data from the Yahoo Fantasy API, runs a suite of analysis engines, and delivers daily recommendations via a web dashboard, REST API, and email report.

It does not give generic advice. It models **your roster**, **your matchup**, **your league**, and tells you exactly what to do and why.

---

## Live Features

### 📊 Daily Analysis
- **Category pressure engine** — identifies which stats you're winning/losing this week and by how much
- **Roster inefficiency detector** — flags players wasting roster spots (availability risk, positional redundancy)
- **Matchup projection** — projects your weekly record category-by-category with swing category identification
- **Standings trajectory** — simulates the rest of your season, projects final record and playoff probability

### 🔄 Roster Moves
- **Waiver recommendations** — scores every available player against your category needs, recommends optimal add/drop pairs
- **Add/drop simulation** — simulates up to 6 sequential moves and shows projected record improvement
- **Streaming SP optimizer** — ranks available starting pitchers by quality score, matchup, and opponent weaknesses (switches to live MLB probable starters on Opening Day)
- **Automated execution** — gated add/drop execution via Yahoo API (dry-run safe, requires env flag to enable)

### 💱 Trade Intelligence
- **1-for-1 trade suggestions** — scores every possible trade against your roster needs
- **Multi-player trades** — evaluates 2-for-1, 1-for-2, and 2-for-2 combinations
- **Trade acceptance probability** — models likelihood the opponent manager actually accepts (factors in their rank, needs, motivation, and whether the trade is fair)
- **What-If trade simulator** — enter any trade and get instant analysis: trade score, acceptance probability, category impact, reasoning
- **Trade value tracker** — tracks projection delta for every rostered player since acquisition week, surfaces sell-high and cut-bait signals

### 🧠 League Intelligence
- **Roster construction scoring** — grades every team 0-100 on balance, depth, and weaknesses
- **Opponent profiling** — per-opponent strength/weakness/punt category breakdown with trade motivation modeling
- **IL/injury monitor** — daily status tracking, detects new IL placements, returns, and surfaces waiver replacements
- **Pitcher ratio risk** — flags ERA/WHIP blowup risk with FIP/BB9 analysis and start/avoid recommendations

### 🌐 Web Dashboard
Full browser UI accessible at your Cloudflare domain:
- Live data from all 18 API endpoints
- Dark analytics aesthetic with Space Mono + DM Sans typography
- Category badge system, probability bars, trade cards
- What-If simulator with autocomplete from your live roster
- Responsive sidebar navigation across 9 sections

### 📧 Daily Email Report
Automated morning email (09:00 daily) covering all 13 analysis sections in markdown format, with PDF attachment.

---

## Architecture

Strict 6-layer separation. No business logic in the service layer. No HTTP in the analysis layer.

```
┌─────────────────────────────────────────┐
│  Layer 6 — FastAPI Service              │  service/main.py
│  Layer 5 — Adapters                     │  src/.../adapters/
│  Layer 4 — Use Cases                    │  src/.../use_cases/
│  Layer 3 — Snapshot                     │  src/.../snapshot/
│  Layer 2 — Analysis Engines             │  src/.../analysis/
│  Layer 1 — Domain Models                │  src/.../domain/
└─────────────────────────────────────────┘
```

### Analysis Engines
| Engine | File | Purpose |
|--------|------|---------|
| Category Pressure | `analysis/category_pressure.py` | Live matchup stat gap modeling |
| Roster Inefficiency | `analysis/roster_inefficiency.py` | Availability and redundancy scoring |
| Waiver Engine | `analysis/waiver_engine.py` | Pool scoring with ratio safety and SV scarcity |
| Pool Scoring | `analysis/pool_scoring.py` | FanGraphs projection-based candidate scoring |
| Matchup Engine | `analysis/matchup_engine.py` | Head-to-head projection with swing category detection |
| Add/Drop Engine | `analysis/adddrop_engine.py` | Sequential move simulation |
| Trade Engine | `analysis/trade_engine.py` | 1-for-1 and multi-player trade scoring |
| Multi-Trade Engine | `analysis/multi_trade_engine.py` | 2-for-1, 1-for-2, 2-for-2 combinations |
| Trade Acceptance | `analysis/trade_acceptance.py` | Opponent acceptance probability model |
| Trade Value Tracker | `analysis/trade_value_tracker.py` | Projection delta since acquisition |
| Ratio Risk | `analysis/ratio_risk.py` | ERA/WHIP/FIP blowup probability |
| Standings Trajectory | `analysis/standings_trajectory.py` | Season-long simulation with playoff probability |
| League Intelligence | `analysis/league_intelligence.py` | Roster construction + opponent profiles |
| Streaming SP | `analysis/streaming_sp.py` | Weekly streaming optimizer with MLB API integration |

---

## API Reference

Service runs at `http://127.0.0.1:8000`. Exposed via Cloudflare tunnel.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Service heartbeat |
| GET | `/snapshot` | Latest roster snapshot |
| GET | `/pressure` | Category pressure report |
| GET | `/inefficiency` | Roster inefficiency report |
| GET | `/waivers` | Waiver recommendations |
| GET | `/trades` | 1-for-1 trade suggestions |
| GET | `/trades/multi` | Multi-player trade suggestions |
| GET | `/trades/acceptance` | Trade suggestions with acceptance probability |
| GET | `/matchup` | Head-to-head matchup projection |
| GET | `/adddrop` | Add/drop simulation |
| GET | `/adddrop/execute` | Execute add/drop plan (gated) |
| GET | `/ratio-risk` | Pitcher ratio risk profiles |
| GET | `/standings` | Standings trajectory |
| GET | `/trade-value` | Trade value tracker |
| GET | `/league/construction` | Roster construction scores |
| GET | `/league/opponents` | Opponent profiles |
| GET | `/streaming-sp` | Streaming SP optimizer |
| GET | `/report` | Latest daily markdown report |
| GET | `/ui` | Web dashboard |

---

## Infrastructure

| Component | Detail |
|-----------|--------|
| Host | Proxmox LXC container (Debian) |
| Python | 3.13.5 with virtualenv |
| Service | uvicorn via systemd |
| Tunnel | Cloudflare (yahoo-api.curley.irish) |
| Scheduler | systemd timers |
| Projections | FanGraphs Steamer 2026 |

### Automation Schedule

```
Daily
  07:30  IL monitor
  08:00  Yahoo snapshot (roster + scoreboard)
  09:00  Daily report + email
  18:00  Yahoo snapshot (mid-day update)

Weekly (Mondays)
  07:00  FanGraphs Steamer projections refresh
  07:15  Projection snapshot + acquisition log update
  07:30  League rosters refresh
```

---

## Setup

### Prerequisites
```bash
# Yahoo Fantasy OAuth credentials required
YAHOO_CLIENT_ID=...
YAHOO_CLIENT_SECRET=...
YAHOO_REFRESH_TOKEN=...
YAHOO_LEAGUE_ID=...
YAHOO_TEAM_KEY=...

# Email (for daily report)
REPORT_EMAIL_TO=...
REPORT_EMAIL_FROM=...
SMTP_HOST=...
SMTP_PASSWORD=...
```

### Install
```bash
git clone https://github.com/wuhkuhh/yahoo-ai-gm.git
cd yahoo-ai-gm
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run
```bash
uvicorn service.main:app --host 127.0.0.1 --port 8000
```

### Data bootstrap
```bash
# Pull FanGraphs projections
python scripts/pull_fg_projections.py

# Pull Yahoo roster snapshot
python scripts/pull_roster.py

# Pull waiver pool
python scripts/pull_waiver_pool.py

# Generate initial daily report
python scripts/daily_report.py
```

---

## Project Structure

```
yahoo-ai-gm/
├── service/                    # FastAPI app + static WebUI
│   ├── main.py
│   └── static/index.html
├── src/yahoo_ai_gm/
│   ├── analysis/               # All analysis engines (pure logic)
│   ├── use_cases/              # Orchestration layer
│   ├── snapshot/               # Roster snapshot builder/store
│   ├── adapters/               # Yahoo client + executor
│   └── domain/                 # Core models
├── scripts/                    # CLI scripts + schedulers
├── data/                       # JSON data store
│   ├── projection_snapshots/
│   └── ...
└── deploy/                     # systemd service + timer files
```

---

## Roadmap

**Season 2026 (active)**
- [x] Category pressure engine
- [x] Roster inefficiency detection
- [x] Waiver scoring + add/drop simulation
- [x] Trade analyzer + multi-player trades
- [x] Trade acceptance probability model
- [x] Matchup projection with swing category detection
- [x] Standings trajectory + playoff probability
- [x] Pitcher ratio risk engine
- [x] SV scarcity and market modeling
- [x] League intelligence + opponent profiling
- [x] IL/injury monitor
- [x] Trade value tracker
- [x] Streaming SP optimizer (FG + MLB API)
- [x] Automated daily email report with PDF
- [x] Full web dashboard
- [x] Cloudflare tunnel deployment

**Planned**
- [ ] Weekly recap email (backward-looking performance review)
- [ ] Natural language query interface
- [ ] Playoff bracket simulator
- [ ] Manager report card (monthly move grading)
- [ ] Live in-game stat tracking (intra-week updates)
- [ ] Historical league database

---

## Tech Stack

- **Python 3.13** — FastAPI, Pydantic, httpx, python-dateutil
- **FanGraphs Steamer** — projection source (batting + pitching)
- **Yahoo Fantasy API** — OAuth 2.0, live roster/scoreboard data
- **MLB Stats API** — probable starters (in-season)
- **Vanilla JS** — WebUI (no framework, no build step)
- **systemd** — service management + scheduling
- **Cloudflare Tunnel** — public HTTPS endpoint

---

## License

Private repository. All rights reserved.

---

*Built from scratch. No boilerplate. No shortcuts. Opening Day: March 25, 2026.*
