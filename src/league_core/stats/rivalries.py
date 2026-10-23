"""Head-to-head history between every pair of owners."""

from __future__ import annotations

from collections import defaultdict

from ..history import LeagueHistory, is_completed
from ..models import MatchupKind


def head_to_head(h: LeagueHistory, through_year: int | None = None) -> dict[tuple[str, str], dict]:
    """{(owner_a, owner_b): stats} with owner_a < owner_b. Consolation games excluded."""
    table: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"wins_a": 0, "wins_b": 0, "ties": 0, "points_a": 0.0, "points_b": 0.0, "playoff_games": 0}
    )
    for s, m, home, away in h.iter_matchups():
        if away is None or m.kind == MatchupKind.CONSOLATION or not is_completed(m):
            continue
        if through_year is not None and s.year > through_year:
            continue
        (a, a_team, a_pts), (b, b_team, b_pts) = sorted(
            ((home.key, m.home_team_id, m.home_score), (away.key, m.away_team_id, m.away_score))
        )
        row = table[(a, b)]
        row["points_a"] = round(row["points_a"] + a_pts, 2)
        row["points_b"] = round(row["points_b"] + b_pts, 2)
        row["playoff_games"] += m.kind == MatchupKind.PLAYOFF
        winner = m.winner_team_id
        if winner is None:
            row["ties"] += 1
        elif winner == a_team:
            row["wins_a"] += 1
        else:
            row["wins_b"] += 1
    return dict(table)


def championships(h: LeagueHistory) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for _, t, o in h.iter_team_seasons():
        if t.final_rank == 1:
            out[o.key] += 1
    return dict(out)


def rivalry_report(h: LeagueHistory, rivalries: list[dict]) -> list[dict]:
    """Featured rivalries from config, e.g. {owners = ["brian", "girish"], frozen_after = 2016}."""
    titles = championships(h)
    report = []
    for r in rivalries:
        x, y = r["owners"]
        a, b = sorted((x, y))
        stats = head_to_head(h, through_year=r.get("frozen_after")).get((a, b))
        if stats is None:
            stats = {"wins_a": 0, "wins_b": 0, "ties": 0, "points_a": 0.0, "points_b": 0.0, "playoff_games": 0}
        flip = a != x  # present in the order the config listed them
        report.append(
            {
                "owners": [h.owner_name(x), h.owner_name(y)],
                "championships": [titles.get(x, 0), titles.get(y, 0)],
                "wins": [stats["wins_b"], stats["wins_a"]] if flip else [stats["wins_a"], stats["wins_b"]],
                "ties": stats["ties"],
                "points": [stats["points_b"], stats["points_a"]] if flip else [stats["points_a"], stats["points_b"]],
                "frozen_after": r.get("frozen_after"),
                "note": r.get("note"),
            }
        )
    return report


def h2h_matrix(h: LeagueHistory) -> list[dict]:
    """Flat list for an all-pairs grid on the site."""
    return [
        {
            "owner_a": h.owner_name(a),
            "owner_b": h.owner_name(b),
            **stats,
        }
        for (a, b), stats in sorted(head_to_head(h).items())
    ]
