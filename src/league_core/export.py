"""Shapes LeagueHistory into the JSON files the website reads.

The website never sees provider ids or team ids, only owner display names,
so it stays as platform-agnostic as the stats.
"""

from __future__ import annotations

from .history import LeagueHistory, is_completed
from .models import Season, TeamSeason
from .stats import h2h_matrix, record_book, rivalry_report


def _team_row(h: LeagueHistory, t: TeamSeason) -> dict:
    return {
        "owner": h.owner_of(t).name,
        "team_name": t.name,
        "wins": t.wins,
        "losses": t.losses,
        "ties": t.ties,
        "points_for": t.points_for,
        "points_against": t.points_against,
        "seed": t.seed,
        "final_rank": t.final_rank,
        "division": t.division,
        "logo_url": t.logo_url,
    }


def _side(h: LeagueHistory, s: Season, team_id: str | None, score: float) -> dict | None:
    if team_id is None:
        return None
    t = s.team(team_id)
    return {"owner": h.owner_of(t).name, "team_name": t.name, "score": score}


def season_detail(h: LeagueHistory, s: Season) -> dict:
    complete = s.champion is not None
    by_finish = sorted(s.teams, key=lambda t: (t.final_rank or 99, t.seed or 99))
    by_seed = sorted(s.teams, key=lambda t: (t.seed or 99))
    last = max(s.teams, key=lambda t: t.final_rank or 0) if complete else None
    runner_up = next((t for t in s.teams if t.final_rank == 2), None)
    return {
        "year": s.year,
        "league_name": s.league_name,
        "complete": complete,
        "champion": h.owner_of(s.champion).name if complete else None,
        "runner_up": h.owner_of(runner_up).name if runner_up else None,
        "last_place": h.owner_of(last).name if last else None,
        "regular_season_weeks": s.regular_season_weeks,
        "playoff_team_count": s.playoff_team_count,
        "standings": [_team_row(h, t) for t in (by_finish if complete else by_seed)],
        "has_box_scores": any(m.box_scores for m in s.matchups),
        "matchups": [
            {
                "id": f"{m.week}-{m.home_team_id}-{m.away_team_id or 'bye'}",
                "week": m.week,
                "weeks": m.weeks,
                "kind": m.kind.value,
                "completed": is_completed(m),
                "home": _side(h, s, m.home_team_id, m.home_score),
                "away": _side(h, s, m.away_team_id, m.away_score),
            }
            for m in s.matchups
        ],
        "draft": [
            {
                "round": p.round,
                "pick": p.pick,
                "owner": h.owner_of(s.team(p.team_id)).name,
                "player": p.player_name,
                "bid_amount": p.bid_amount,
                "keeper": p.keeper,
            }
            for p in s.draft
        ],
    }


def _lineup(entries) -> list[dict]:
    order = ["QB", "RB", "WR", "TE", "RB/WR/TE", "WR/TE", "OP", "D/ST", "K", "BE", "IR"]
    rank = {slot: i for i, slot in enumerate(order)}
    return [
        {"player": e.player_name, "pos": e.position, "slot": e.slot, "pts": e.points,
         "proj": e.projected_points, "team": e.pro_team}
        for e in sorted(entries, key=lambda e: rank.get(e.slot, 50))
    ]


def season_box_scores(s: Season) -> dict:
    """{matchup id: [{nfl_week, home, away}]}"""
    return {
        f"{m.week}-{m.home_team_id}-{m.away_team_id or 'bye'}": [
            {"nfl_week": b.nfl_week, "home": _lineup(b.home_lineup), "away": _lineup(b.away_lineup)}
            for b in sorted(m.box_scores, key=lambda b: b.nfl_week)
        ]
        for m in s.matchups
        if m.box_scores
    }


def build_site_data(h: LeagueHistory, config: dict) -> dict[str, object]:
    """{filename: payload} for everything the site needs."""
    seasons = [season_detail(h, s) for s in h.seasons]
    latest = h.seasons[-1] if h.seasons else None
    return {
        "league.json": {
            "name": config.get("site", {}).get("name") or (latest.league_name if latest else ""),
            "tagline": config.get("site", {}).get("tagline", ""),
            "short_name": config.get("site", {}).get("short_name", ""),
            "wordmark": config.get("site", {}).get("wordmark", ""),
            "hero_title": config.get("site", {}).get("hero_title", ""),
            "first_year": h.seasons[0].year if h.seasons else None,
            "latest_year": latest.year if latest else None,
            "owners": sorted(o.name for o in h.owners()),
        },
        "records.json": record_book(h),
        "rivalries.json": rivalry_report(h, config.get("rivalries", [])),
        "h2h.json": h2h_matrix(h),
        "seasons.json": seasons,
        **{f"boxscores/{s.year}.json": season_box_scores(s) for s in h.seasons if any(m.box_scores for m in s.matchups)},
    }
