from collections import Counter, defaultdict

from yahoo_ai_gm.domain.models import Snapshot, InefficiencyReport, Inefficiency


BAD_STATUSES = {"DTD", "IL", "IL10", "IL15", "IL60", "NA", "SUSP"}


def roster_inefficiency_report(snapshot: Snapshot) -> InefficiencyReport:
    roster = snapshot.roster
    players = roster.players

    items = []

    # 1) Injury / availability flags
    for p in players:
        if not p.status:
            continue
        status = p.status.strip().upper()
        if status in BAD_STATUSES:
            sev = "high" if status.startswith("IL") else "med"
            items.append(
                Inefficiency(
                    kind="availability_risk",
                    severity=sev,
                    player_key=p.player_key,
                    player_name=p.name,
                    note=f"Status={status}. Consider bench/IL slot usage and contingency planning.",
                )
            )

    # 2) Positional clustering / redundancies
    pos_counts = Counter()
    pos_to_players = defaultdict(list)

    for p in players:
        for pos in (p.eligible_positions or []):
            pos_counts[pos] += 1
            pos_to_players[pos].append(p.name)

    # Heuristic thresholds (tune later)
    # In a standard lineup, too much depth at one position can mean wasted flexibility.
    for pos, cnt in sorted(pos_counts.items(), key=lambda x: (-x[1], x[0])):
        if pos in {"SP", "RP"}:
            continue  # handled separately
        if cnt >= 3:
            items.append(
                Inefficiency(
                    kind="positional_redundancy",
                    severity="med" if cnt == 3 else "high",
                    note=f"You have {cnt} players eligible at {pos}: {', '.join(pos_to_players[pos][:6])}"
                         + ("..." if len(pos_to_players[pos]) > 6 else ""),
                )
            )

    # 3) Pitching balance
    sp = pos_counts.get("SP", 0)
    rp = pos_counts.get("RP", 0)
    if sp >= 7:
        items.append(
            Inefficiency(
                kind="pitching_density",
                severity="med" if sp == 7 else "high",
                note=f"High SP density ({sp} SP-eligible). This can crowd bats on a weekly basis; "
                     f"good for streaming Ks/W, risky for ERA/WHIP if unmanaged.",
            )
        )
    if rp <= 1:
        items.append(
            Inefficiency(
                kind="save_exposure",
                severity="med",
                note=f"Low RP depth ({rp} RP-eligible). You may struggle to compete in SV without active management.",
            )
        )

    return InefficiencyReport(
        week=snapshot.week,
        team_key=roster.team_key,
        items=items,
    )
