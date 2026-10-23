"""Platform-agnostic league data model.

Every provider (ESPN, Sleeper, Yahoo, ...) converts its API responses into
these classes. Everything downstream (stats, storage, the website) only ever
sees these types, so switching platforms means writing a new provider and
nothing else.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MatchupKind(str, Enum):
    REGULAR = "regular"
    PLAYOFF = "playoff"  # championship bracket
    CONSOLATION = "consolation"  # losers bracket / toilet bowl


@dataclass
class Owner:
    """A person in the league. Stable across seasons (team names are not)."""

    id: str  # provider's member id, or a canonical id from config
    name: str


@dataclass
class TeamSeason:
    """One owner's team for one season."""

    team_id: str
    owner_ids: list[str]
    name: str
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    seed: int | None = None  # regular season finish / playoff seed
    final_rank: int | None = None  # 1 = champion
    division: str | None = None
    logo_url: str | None = None


@dataclass
class LineupEntry:
    """One player on a fantasy roster for one NFL week."""

    player_name: str
    position: str  # the player's position: QB, RB, WR, TE, K, D/ST
    slot: str  # where they were played: QB, RB, FLEX, ..., BE (bench), IR
    points: float
    projected_points: float | None = None
    pro_team: str | None = None

    @property
    def is_starter(self) -> bool:
        return self.slot not in ("BE", "IR")


@dataclass
class BoxScore:
    """Both lineups for one NFL week of a matchup (2-week rounds have two)."""

    nfl_week: int
    home_lineup: list[LineupEntry]
    away_lineup: list[LineupEntry]


@dataclass
class Matchup:
    week: int  # matchup period (a 2-week playoff round counts as one)
    home_team_id: str
    away_team_id: str | None  # None = bye
    home_score: float
    away_score: float
    kind: MatchupKind = MatchupKind.REGULAR
    weeks: int = 1  # NFL weeks this matchup spans (some leagues use 2-week playoff rounds)
    box_scores: list[BoxScore] = field(default_factory=list)  # empty if the platform has none

    @property
    def is_bye(self) -> bool:
        return self.away_team_id is None

    @property
    def winner_team_id(self) -> str | None:
        if self.is_bye or self.home_score == self.away_score:
            return None
        return self.home_team_id if self.home_score > self.away_score else self.away_team_id


@dataclass
class DraftPick:
    round: int
    pick: int
    team_id: str
    player_name: str
    bid_amount: float | None = None  # auction leagues
    keeper: bool = False


@dataclass
class Season:
    year: int
    league_name: str
    regular_season_weeks: int
    playoff_team_count: int
    owners: list[Owner]
    teams: list[TeamSeason]
    matchups: list[Matchup]
    draft: list[DraftPick] = field(default_factory=list)
    provider: str = ""

    def team(self, team_id: str) -> TeamSeason:
        return next(t for t in self.teams if t.team_id == team_id)

    @property
    def champion(self) -> TeamSeason | None:
        return next((t for t in self.teams if t.final_rank == 1), None)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Season:
        return cls(
            year=d["year"],
            league_name=d["league_name"],
            regular_season_weeks=d["regular_season_weeks"],
            playoff_team_count=d["playoff_team_count"],
            owners=[Owner(**o) for o in d["owners"]],
            teams=[TeamSeason(**t) for t in d["teams"]],
            matchups=[_matchup_from_dict(m) for m in d["matchups"]],
            draft=[DraftPick(**p) for p in d.get("draft", [])],
            provider=d.get("provider", ""),
        )


def _matchup_from_dict(m: dict[str, Any]) -> Matchup:
    boxes = [
        BoxScore(
            nfl_week=b["nfl_week"],
            home_lineup=[LineupEntry(**e) for e in b["home_lineup"]],
            away_lineup=[LineupEntry(**e) for e in b["away_lineup"]],
        )
        for b in m.get("box_scores", [])
    ]
    return Matchup(**{**m, "kind": MatchupKind(m["kind"]), "box_scores": boxes})
