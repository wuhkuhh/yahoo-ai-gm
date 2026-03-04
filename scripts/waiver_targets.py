from __future__ import annotations

import argparse
from typing import Dict, List, Optional

from scripts._io import latest_week_file, read_json, DATA_DIR, find_roster_file
from scripts.category_pressure import compute_pressure, to_float


def load_scoreboard(week: int) -> dict:
    path = DATA_DIR / f"scoreboard_week_{week}.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run pull_scoreboard_week.py first.")
    return read_json(path)


def extract_players(roster_payload: dict) -> List[dict]:
    if isinstance(roster_payload, list):
        return roster_payload
    for path in (
        ("players",),
        ("roster", "players"),
        ("team", "roster", "players"),
        ("data", "players"),
    ):
        cur = roster_payload
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and isinstance(cur, list):
            return cur
    if "players" in roster_payload and isinstance(roster_payload["players"], dict):
        return list(roster_payload["players"].values())
    return []


def get_pos(p: dict) -> str:
    return str(p.get("display_position") or p.get("positions") or p.get("position") or "")


def roster_shape(players: List[dict]) -> Dict[str, int]:
    hitters = 0
    pitchers = 0
    sp = 0
    rp = 0
    for p in players:
        pos = get_pos(p)
        poss = [x.strip() for x in pos.split(",") if x.strip()]
        if any(x in {"SP", "RP", "P"} for x in poss):
            pitchers += 1
        if any(x in {"C", "1B", "2B", "3B", "SS", "OF"} for x in poss):
            hitters += 1
        if "SP" in poss:
            sp += 1
        if "RP" in poss:
            rp += 1
    return {"hitters": hitters, "pitchers": pitchers, "sp": sp, "rp": rp}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    args = ap.parse_args()

    week = args.week or latest_week_file("scoreboard_week")
    if not week:
        raise SystemExit("No scoreboard files found. Run pull_scoreboard_week.py first.")

    sb = load_scoreboard(week)
    pressure = compute_pressure(sb)

    roster_path = find_roster_file(week)
    roster_players: List[dict] = []
    if roster_path and roster_path.exists():
        roster_players = extract_players(read_json(roster_path))

    shape = roster_shape(roster_players) if roster_players else {"hitters": 0, "pitchers": 0, "sp": 0, "rp": 0}

    print(f"Week {pressure['week']} | status={pressure['status']}")
    print(f"You: {pressure['you_name']} vs {pressure['opp_name']}")
    if roster_path:
        print(f"Roster: {roster_path}")
    print(f"Roster shape: hitters={shape['hitters']} pitchers={shape['pitchers']} (SP={shape['sp']} RP={shape['rp']})\n")

    if not pressure["has_numbers"]:
        print("No stats yet (preevent). This will be way better once the week starts.\n")

    b = pressure["buckets"]
    push = set(b.get("PUSH", []))
    protect = set(b.get("PROTECT", []))

    # --- basic heuristics -> action plan ---
    actions: List[str] = []
    avoid: List[str] = []

    # Pitching plan
    if "SV" in push:
        actions.append("CHASE SAVES: add a closer/spec-closer RP; prioritize teams with shaky 9th inning.")
    if "K" in push or "W" in push:
        actions.append("STREAM STARTERS: add 1–2 SP with good matchups to chase Ks/W.")
    if "ERA" in protect or "WHIP" in protect:
        actions.append("PROTECT RATIOS: avoid risky streamers; prefer high-K relievers and safe matchups.")
    if "ERA" in push or "WHIP" in push:
        actions.append("RATIOS LOSING: consider volume if far behind; otherwise target elite relievers to stabilize.")

    # Hitting plan
    if "SB" in push:
        actions.append("CHASE SPEED: add a SB specialist (leadoff type) and prioritize daily lineup steals chances.")
    if "HR" in push or "RBI" in push:
        actions.append("CHASE POWER: add a power bat with good park/matchups; target middle-of-order hitters.")
    if "AVG" in protect:
        actions.append("PROTECT AVG: bench low-AVG sluggers unless you must chase HR/RBI.")
    if "AVG" in push:
        actions.append("AVG LOSING: prefer high-contact bats; reduce low-contact boom/bust starts.")

    # Avoid chasing ignored categories
    ignore = set(b.get("IGNORE", []))
    if ignore:
        avoid.append("DON’T OVER-INVEST in: " + ", ".join(sorted(ignore)))

    # IP pace hint (if present)
    ip_row = next((r for r in pressure["rows"] if r["cat"] == "IP"), None)
    if ip_row and to_float(ip_row.get("you", "")) is not None:
        ip = float(ip_row["you"])
        if ip < 8:
            actions.append("IP LOW: you’re early-week light — streaming may be needed if chasing W/K.")
        elif ip > 20:
            actions.append("IP MET: you can pivot to ratio-protection and avoid extra SP risk.")

    # Output
    print("Waiver / lineup gameplan:")
    print("-" * 72)
    if actions:
        for a in actions:
            print(f"- {a}")
    else:
        print("- No obvious pushes yet. Once stats populate, this will get sharper.")

    if avoid:
        print("\nAvoid:")
        for a in avoid:
            print(f"- {a}")

    print("\nNext upgrade (when you’re ready):")
    print("- Plug in Yahoo 'players' search endpoint to actually list names for targets.")
    print("- Add a simple streamer filter: probable starters + opponent + park factor + K-rate proxy.")


if __name__ == "__main__":
    main()
