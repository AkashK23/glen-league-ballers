"""Multi-season view of the league, keyed by *person* rather than team.

Team names change every year and people sometimes switch accounts, so all
cross-season stats go through `owner_of`, which maps a team to a canonical
owner using the `[owners.*]` tables in config/league.toml.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Matchup, Season, TeamSeason


@dataclass
class OwnerInfo:
    key: str
    name: str


class LeagueHistory:
    def __init__(self, seasons: list[Season], owner_config: dict | None = None):
        self.seasons = sorted(seasons, key=lambda s: s.year)
        self._by_provider_id: dict[str, OwnerInfo] = {}
        for key, cfg in (owner_config or {}).items():
            info = OwnerInfo(key=key, name=cfg.get("name", key))
            for pid in cfg.get("ids", []):
                self._by_provider_id[pid] = info
        # Owners not in config fall back to the platform's name for them.
        for s in self.seasons:
            for o in s.owners:
                self._by_provider_id.setdefault(o.id, OwnerInfo(key=o.id, name=o.name))

    def owner_of(self, team: TeamSeason) -> OwnerInfo:
        """Primary (first-listed) owner of a team."""
        if not team.owner_ids:
            return OwnerInfo(key=f"team:{team.team_id}", name=team.name)
        return self._by_provider_id[team.owner_ids[0]]

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
