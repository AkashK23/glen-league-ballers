"""Weekly power rankings, computed from results alone.

Uses ESPN's published formula, so the numbers line up with what people see
in the app, but runs on our own matchup data so it works for any platform:

    power = 0.80 * two-step dominance + 0.15 * avg points + 0.05 * avg margin

Two-step dominance counts your wins, plus the wins of every team you beat,
so beating good teams counts for more than beating bad ones.
"""

from __future__ import annotations

from ..history import is_completed
from ..models import MatchupKind, Season


def power_rankings(season: Season) -> list[dict]:
    """[{week, rankings: [{team_id, rank, power, wins, losses, prev_rank}]}] for each played week."""
    games = [
        m
        for m in season.matchups
        if m.kind == MatchupKind.REGULAR and not m.is_bye and is_completed(m)
    ]
    weeks = sorted({m.week for m in games})
    team_ids = [t.team_id for t in season.teams]
    idx = {tid: i for i, tid in enumerate(team_ids)}
    n = len(team_ids)

    out: list[dict] = []
    prev: dict[str, int] = {}
    for week in weeks:
        played = [m for m in games if m.week <= week]
        beat = [[0] * n for _ in range(n)]  # beat[i][j] = times i beat j
        points = [0.0] * n
        margin = [0.0] * n
        wins = [0] * n
        losses = [0] * n
        count = [0] * n
        for m in played:
            h, a = idx[m.home_team_id], idx[m.away_team_id]
            for me, opp, pf, pa in ((h, a, m.home_score, m.away_score), (a, h, m.away_score, m.home_score)):
                points[me] += pf
                margin[me] += pf - pa
                count[me] += 1
                if pf > pa:
                    beat[me][opp] += 1
                    wins[me] += 1
                elif pf < pa:
                    losses[me] += 1

        # two-step dominance: row sums of (B^2 + B)
        dominance = [
            sum(beat[i][j] + sum(beat[i][k] * beat[k][j] for k in range(n)) for j in range(n))
            for i in range(n)
        ]
        rows = []
        for i, tid in enumerate(team_ids):
            g = count[i] or 1
            power = 0.8 * dominance[i] + 0.15 * points[i] / g + 0.05 * margin[i] / g
            rows.append({"team_id": tid, "power": round(power, 2), "wins": wins[i], "losses": losses[i], "pf": points[i]})
        rows.sort(key=lambda r: (-r["power"], -r["pf"]))
        for rank, r in enumerate(rows, 1):
            r["rank"] = rank
            r["prev_rank"] = prev.get(r["team_id"])
            del r["pf"]
        prev = {r["team_id"]: r["rank"] for r in rows}
        out.append({"week": week, "rankings": rows})
    return out
