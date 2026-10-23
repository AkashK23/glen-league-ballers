"""League record book. Pure functions over LeagueHistory -> JSON-ready dicts."""

from __future__ import annotations

from collections import defaultdict

from ..history import LeagueHistory, is_completed
from ..models import MatchupKind


def _top(rows: list[dict], key: str, n: int, reverse: bool = True) -> list[dict]:
    return sorted(rows, key=lambda r: r[key], reverse=reverse)[:n]


def _pct(w: int, l: int, t: int = 0) -> float:
    games = w + l + t
    return round((w + 0.5 * t) / games, 4) if games else 0.0


def single_season_records(h: LeagueHistory, n: int = 10) -> dict:
    rows = []
    for s, t, o in h.iter_team_seasons():
        if s.champion is None:  # season still in progress
            continue
        rows.append(
            {
                "owner": o.name,
                "year": s.year,
                "wins": t.wins,
                "losses": t.losses,
                "ties": t.ties,
                "win_pct": _pct(t.wins, t.losses, t.ties),
                "points_for": t.points_for,
                "points_against": t.points_against,
            }
        )

    streaks = _streaks(h)
    return {
        "best_record": _top(rows, "win_pct", n),
        "worst_record": _top(rows, "win_pct", n, reverse=False),
        "most_points_for": _top(rows, "points_for", n),
        "least_points_for": _top(rows, "points_for", n, reverse=False),
        "most_points_against": _top(rows, "points_against", n),
        "least_points_against": _top(rows, "points_against", n, reverse=False),
        "longest_win_streak": _top(streaks, "win_streak", n),
        "longest_losing_streak": _top(streaks, "loss_streak", n),
    }


def _streaks(h: LeagueHistory) -> list[dict]:
    """Longest regular-season W and L streak per owner per season."""
    results: dict[tuple[int, str], list[tuple[int, str]]] = defaultdict(list)
    names: dict[str, str] = {}
    for s, m, home, away in h.iter_matchups():
        if m.kind != MatchupKind.REGULAR or away is None or not is_completed(m):
            continue
        names[home.key], names[away.key] = home.name, away.name
        winner = m.winner_team_id
        for team_id, o in ((m.home_team_id, home), (m.away_team_id, away)):
            outcome = "T" if winner is None else ("W" if winner == team_id else "L")
            results[(s.year, o.key)].append((m.week, outcome))

    rows = []
    for (year, key), games in results.items():
        best = {"W": 0, "L": 0}
        run_type, run_len = None, 0
        for _, outcome in sorted(games):
            run_len = run_len + 1 if outcome == run_type else 1
            run_type = outcome
            if outcome in best:
                best[outcome] = max(best[outcome], run_len)
        rows.append({"owner": names[key], "year": year, "win_streak": best["W"], "loss_streak": best["L"]})
    return rows


def single_game_records(h: LeagueHistory, n: int = 10) -> dict:
    """One-week regular season + championship bracket games (consolation excluded)."""
    scores, games = [], []
    for s, m, home, away in h.iter_matchups():
        if away is None or m.kind == MatchupKind.CONSOLATION or m.weeks != 1 or not is_completed(m):
            continue
        base = {"year": s.year, "week": m.week, "playoff": m.kind == MatchupKind.PLAYOFF}
        scores.append({**base, "owner": home.name, "opponent": away.name, "points": m.home_score})
        scores.append({**base, "owner": away.name, "opponent": home.name, "points": m.away_score})
        (w, ws), (l, ls) = sorted(((home.name, m.home_score), (away.name, m.away_score)), key=lambda x: -x[1])
        games.append(
            {
                **base,
                "winner": w,
                "loser": l,
                "winner_points": ws,
                "loser_points": ls,
                "margin": round(ws - ls, 2),
                "combined": round(ws + ls, 2),
            }
        )
    return {
        "most_points": _top(scores, "points", n),
        "least_points": _top(scores, "points", n, reverse=False),
        "largest_margin": _top(games, "margin", n),
        "most_combined": _top(games, "combined", n),
        "least_combined": _top(games, "combined", n, reverse=False),
    }


def playoff_records(h: LeagueHistory, n: int = 10) -> dict:
    agg: dict[str, dict] = defaultdict(lambda: {"championships": 0, "appearances": 0, "wins": 0, "losses": 0})
    names: dict[str, str] = {}

    for s, t, o in h.iter_team_seasons():
        names[o.key] = o.name
        if t.final_rank == 1:
            agg[o.key]["championships"] += 1
        if (
            s.champion is not None
            and t.seed is not None
            and t.seed <= s.playoff_team_count
            and t.team_id not in h.play_in_losers(s)
        ):
            agg[o.key]["appearances"] += 1

    games = []
    for s, m, home, away in h.iter_matchups():
        if m.kind != MatchupKind.PLAYOFF or away is None or not is_completed(m) or h.is_play_in(s, m):
            continue
        winner = m.winner_team_id
        for team_id, o, pts, opp, opp_pts in (
            (m.home_team_id, home, m.home_score, away, m.away_score),
            (m.away_team_id, away, m.away_score, home, m.home_score),
        ):
            if winner == team_id:
                agg[o.key]["wins"] += 1
            elif winner is not None:
                agg[o.key]["losses"] += 1
            games.append(
                {
                    "owner": o.name,
                    "opponent": opp.name,
                    "year": s.year,
                    "week": m.week,
                    "weeks": m.weeks,
                    "points": pts,
                    "margin": round(pts - opp_pts, 2),
                }
            )

    table = [
        {"owner": names[k], **v, "win_pct": _pct(v["wins"], v["losses"])}
        for k, v in agg.items()
    ]
    return {
        "most_championships": _top(table, "championships", n),
        "most_appearances": _top(table, "appearances", n),
        "most_playoff_wins": _top(table, "wins", n),
        "best_playoff_win_pct": _top([r for r in table if r["wins"] + r["losses"]], "win_pct", n),
        "most_points_in_1_week_playoff_game": _top([g for g in games if g["weeks"] == 1], "points", n),
        "most_points_in_2_week_playoff_matchup": _top([g for g in games if g["weeks"] == 2], "points", n),
        "largest_playoff_margin": _top(games, "margin", n),
    }


def all_time_leaders(h: LeagueHistory) -> dict:
    career: dict[str, dict] = defaultdict(
        lambda: {
            "seasons": 0, "wins": 0, "losses": 0, "ties": 0,
            "points_for": 0.0, "points_against": 0.0,
            "scoring_titles": 0, "schedule_difficulty_titles": 0, "winning_seasons": 0,
        }
    )
    names: dict[str, str] = {}
    for s in h.seasons:
        if s.champion is None:
            continue
        pf_leader = max(s.teams, key=lambda t: t.points_for)
        pa_leader = max(s.teams, key=lambda t: t.points_against)
        for t in s.teams:
            o = h.owner_of(t)
            names[o.key] = o.name
            c = career[o.key]
            c["seasons"] += 1
            c["wins"] += t.wins
            c["losses"] += t.losses
            c["ties"] += t.ties
            c["points_for"] = round(c["points_for"] + t.points_for, 2)
            c["points_against"] = round(c["points_against"] + t.points_against, 2)
            c["scoring_titles"] += t is pf_leader
            c["schedule_difficulty_titles"] += t is pa_leader
            c["winning_seasons"] += t.wins > t.losses
    rows = [
        {"owner": names[k], **v, "win_pct": _pct(v["wins"], v["losses"], v["ties"])}
        for k, v in career.items()
    ]
    return {"career": sorted(rows, key=lambda r: -r["win_pct"])}


def record_book(h: LeagueHistory) -> dict:
    return {
        "single_season": single_season_records(h),
        "single_game": single_game_records(h),
        "playoffs": playoff_records(h),
        "all_time": all_time_leaders(h),
    }
