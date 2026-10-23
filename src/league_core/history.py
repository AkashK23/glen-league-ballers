"""Multi-season view of the league, keyed by *person* rather than team.

Team names change every year and people sometimes switch accounts, so all
cross-season stats go through `owner_of`, which maps a team to a canonical
owner using the `[owners.*]` tables in config/league.toml.

League conventions that change what counts also live here, so every stat
applies them the same way: who gets credit for a co-owned team, and which
playoff games were play-ins that don't count toward playoff stats.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Matchup, MatchupKind, Season, TeamSeason


@dataclass
class OwnerInfo:
    key: str
    name: str
    defers: bool = False  # never credited for a team they co-own with someone else


class LeagueHistory:
    def __init__(self, seasons: list[Season], owner_config: dict | None = None, play_in_seasons: list[int] | None = None):
        self.seasons = sorted(seasons, key=lambda s: s.year)
        self._play_in_weeks = {
            s.year: min((m.week for m in s.matchups if m.kind == MatchupKind.PLAYOFF), default=None)
            for s in self.seasons
            if s.year in set(play_in_seasons or [])
        }
        self._by_provider_id: dict[str, OwnerInfo] = {}
        for key, cfg in (owner_config or {}).items():
            info = OwnerInfo(key=key, name=cfg.get("name", key), defers=bool(cfg.get("defer_to_co_owner", False)))
            for pid in cfg.get("ids", []):
                self._by_provider_id[pid] = info
        # Owners not in config fall back to the platform's name for them.
        for s in self.seasons:
            for o in s.owners:
                self._by_provider_id.setdefault(o.id, OwnerInfo(key=o.id, name=o.name))

    def owner_of(self, team: TeamSeason) -> OwnerInfo:
        """The owner credited with a team: the first-listed owner, skipping
        anyone marked `defer_to_co_owner` while they share the team."""
        if not team.owner_ids:
            return OwnerInfo(key=f"team:{team.team_id}", name=team.name)
        owners = [self._by_provider_id[i] for i in team.owner_ids]
        return next((o for o in owners if not o.defers), owners[0])

    def is_play_in(self, season: Season, m: Matchup) -> bool:
        """First-round play-in game (e.g. 4 vs 5 seed), which doesn't count as a playoff game."""
        return m.kind == MatchupKind.PLAYOFF and self._play_in_weeks.get(season.year) == m.week

    def play_in_losers(self, season: Season) -> set[str]:
        """Team ids that lost a play-in, and so didn't really make the playoffs."""
        out = set()
        for m in season.matchups:
            if self.is_play_in(season, m) and m.winner_team_id is not None:
                out.add(m.away_team_id if m.winner_team_id == m.home_team_id else m.home_team_id)
        return out

    def owner_name(self, key: str) -> str:
        return next((o.name for o in self._by_provider_id.values() if o.key == key), key)

    def owners(self) -> list[OwnerInfo]:
        seen: dict[str, OwnerInfo] = {}
        for s in self.seasons:
            for t in s.teams:
                o = self.owner_of(t)
                seen.setdefault(o.key, o)
        return list(seen.values())

    def iter_matchups(self):
        """Yield (season, matchup, home_owner, away_owner|None) for every game."""
        for s in self.seasons:
            for m in s.matchups:
                home = self.owner_of(s.team(m.home_team_id))
                away = None if m.is_bye else self.owner_of(s.team(m.away_team_id))
                yield s, m, home, away

    def iter_team_seasons(self):
        for s in self.seasons:
            for t in s.teams:
                yield s, t, self.owner_of(t)


def is_completed(m: Matchup) -> bool:
    """Unplayed future games come back from most APIs as 0-0."""
    return m.home_score > 0 or m.away_score > 0
