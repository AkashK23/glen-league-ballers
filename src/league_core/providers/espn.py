"""ESPN provider, built on https://github.com/cwendt94/espn-api.

Private leagues need the `espn_s2` and `SWID` cookies from a logged-in
browser session (DevTools > Application > Cookies > espn.com).
"""

from __future__ import annotations

from ..models import BoxScore, DraftPick, LineupEntry, Matchup, MatchupKind, Owner, Season, TeamSeason
from .base import LeagueProvider

BOX_SCORES_FROM = 2019  # ESPN has no player-level box scores before this

_KIND_BY_TIER = {
    "NONE": MatchupKind.REGULAR,
    "WINNERS_BRACKET": MatchupKind.PLAYOFF,
}


class EspnProvider(LeagueProvider):
    name = "espn"

    def __init__(self, league_id: int, espn_s2: str | None = None, swid: str | None = None):
        self.league_id = league_id
        self.espn_s2 = espn_s2
        self.swid = swid

    def _league(self, year: int):
        from espn_api.football import League  # imported lazily so other providers don't need it

        return League(league_id=self.league_id, year=year, espn_s2=self.espn_s2, swid=self.swid)

    def fetch_season(self, year: int) -> Season:
        league = self._league(year)
        settings = league.settings

        owners: dict[str, Owner] = {}
        teams: list[TeamSeason] = []
        for t in league.teams:
            owner_ids = []
            for m in t.owners:
                oid = m.get("id", "")
                owner_ids.append(oid)
                name = f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()
                owners[oid] = Owner(id=oid, name=name or m.get("displayName", oid))
            teams.append(
                TeamSeason(
                    team_id=str(t.team_id),
                    owner_ids=owner_ids,
                    name=t.team_name,
                    wins=t.wins,
                    losses=t.losses,
                    ties=t.ties,
                    points_for=round(t.points_for, 2),
                    points_against=round(t.points_against, 2),
                    seed=t.standing or None,
                    final_rank=t.final_standing or None,
                    division=t.division_name or None,
                    logo_url=t.logo_url or None,
                )
            )

        # scoreboard() works for every season and returns one entry per
        # matchup period, so multi-week playoff rounds come back pre-summed.
        matchups: list[Matchup] = []
        for period in range(1, len(settings.matchup_periods) + 1):
            for m in league.scoreboard(period):
                home = getattr(m, "home_team", None)
                away = getattr(m, "away_team", None)
                if home is None:
                    continue
                matchups.append(
                    Matchup(
                        week=period,
                        home_team_id=str(home.team_id),
                        away_team_id=str(away.team_id) if away is not None else None,
                        home_score=round(m.home_score, 2),
                        away_score=round(m.away_score, 2) if away is not None else 0.0,
                        kind=_KIND_BY_TIER.get(m.matchup_type, MatchupKind.CONSOLATION),
                        weeks=len(settings.matchup_periods.get(str(period), [period])),
                    )
                )

        if year >= BOX_SCORES_FROM:
            self._attach_box_scores(league, matchups)

        draft = [
            DraftPick(
                round=p.round_num,
                pick=p.round_pick,
                team_id=str(p.team.team_id),
                player_name=p.playerName,
                bid_amount=p.bid_amount or None,
                keeper=bool(p.keeper_status),
            )
            for p in league.draft
            if p.team is not None
        ]

        return Season(
            year=year,
            league_name=settings.name,
            regular_season_weeks=settings.reg_season_count,
            playoff_team_count=settings.playoff_team_count,
            owners=list(owners.values()),
            teams=teams,
            matchups=matchups,
            draft=draft,
            provider=self.name,
        )

    def _attach_box_scores(self, league, matchups: list[Matchup]) -> None:
        """Add per-NFL-week lineups to each matchup. Missing weeks are skipped."""
        by_key = {(m.week, m.home_team_id, m.away_team_id): m for m in matchups}
        period_of = {
            nfl_week: int(period)
            for period, nfl_weeks in league.settings.matchup_periods.items()
            for nfl_week in nfl_weeks
        }
        cache: dict = {}
        last_week = max((nfl_week for nfl_week in period_of if nfl_week <= league.current_week), default=0)
        for nfl_week in range(1, last_week + 1):
            try:
                boxes = league.box_scores(nfl_week, player_team_cache=cache)
            except Exception as e:  # noqa: BLE001
                print(f"    box scores {league.year} wk {nfl_week}: skipped ({e})")
                continue
            for b in boxes:
                home_id = getattr(b.home_team, "team_id", None)
                away_id = getattr(b.away_team, "team_id", None)
                if home_id is None:
                    continue
                key = (period_of.get(nfl_week), str(home_id), str(away_id) if away_id is not None else None)
                m = by_key.get(key)
                if m is None:
                    continue
                m.box_scores.append(
                    BoxScore(
                        nfl_week=nfl_week,
                        home_lineup=[_lineup_entry(p) for p in b.home_lineup],
                        away_lineup=[_lineup_entry(p) for p in b.away_lineup] if away_id is not None else [],
                    )
                )


def _lineup_entry(p) -> LineupEntry:
    return LineupEntry(
        player_name=p.name,
        position=p.position,
        slot=p.slot_position,
        points=round(p.points or 0, 2),
        projected_points=round(p.projected_points, 2) if p.projected_points else None,
        pro_team=p.proTeam or None,
    )
