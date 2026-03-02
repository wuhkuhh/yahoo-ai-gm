from yahoo_ai_gm.domain.models import Snapshot, PressureReport, CategoryPressure

LOWER_IS_BETTER = {"ERA", "WHIP"}


def _posture(diff: float, category: str) -> str:
    adj = -diff if category in LOWER_IS_BETTER else diff

    if abs(adj) < 0.15:
        return "even"
    if adj >= 0.75:
        return "protect"
    if adj <= -0.75:
        return "push"
    return "even"


def pressure_report(snapshot: Snapshot) -> PressureReport:
    my = snapshot.matchup.my_team
    opp = snapshot.matchup.opp_team

    pressures = []

    cats = sorted(set(my.totals.keys()) | set(opp.totals.keys()))

    for cat in cats:
        my_val = float(my.totals.get(cat, 0.0))
        opp_val = float(opp.totals.get(cat, 0.0))
        diff = my_val - opp_val

        pressures.append(
            CategoryPressure(
                category=cat,
                my_value=my_val,
                opp_value=opp_val,
                diff=diff,
                posture=_posture(diff, cat),
            )
        )

    return PressureReport(
        week=snapshot.week,
        team_key=snapshot.roster.team_key,
        pressures=pressures,
    )
