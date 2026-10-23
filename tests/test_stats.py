"""Stats are tested against hand-built Seasons, so no platform is involved."""

from league_core.history import LeagueHistory
from league_core.models import Matchup, MatchupKind, Owner, Season, TeamSeason
from league_core.stats import record_book, rivalry_report
from league_core.storage import load_seasons, save_season


def _season(year: int) -> Season:
    owners = [Owner("A", "Alice"), Owner("B", "Bob"), Owner("C", "Cara"), Owner("D", "Dev")]
    teams = [
        TeamSeason("1", ["A"], f"Alice {year}", 3, 0, 0, 390.0, 300.0, seed=1, final_rank=1),
        TeamSeason("2", ["B"], f"Bob {year}", 2, 1, 0, 350.0, 320.0, seed=2, final_rank=2),
        TeamSeason("3", ["C"], f"Cara {year}", 1, 2, 0, 310.0, 340.0, seed=3, final_rank=3),
        TeamSeason("4", ["D"], f"Dev {year}", 0, 3, 0, 280.0, 370.0, seed=4, final_rank=4),
    ]
    R, P, C = MatchupKind.REGULAR, MatchupKind.PLAYOFF, MatchupKind.CONSOLATION
    matchups = [
        Matchup(1, "1", "2", 130, 110, R), Matchup(1, "3", "4", 100, 90, R),
        Matchup(2, "1", "3", 120, 105, R), Matchup(2, "2", "4", 125, 95, R),
        Matchup(3, "1", "4", 140, 95, R), Matchup(3, "2", "3", 115, 105, R),
        Matchup(4, "1", "2", 250, 200, P, weeks=2), Matchup(4, "3", "4", 80, 70, C, weeks=2),
    ]
    return Season(year, "Test League", 3, 2, owners, teams, matchups)


def _history(years=(2024, 2025)) -> LeagueHistory:
    return LeagueHistory([_season(y) for y in years], {"alice": {"name": "Alice", "ids": ["A"]}})


def test_single_game_and_season_records():
    book = record_book(_history())
    # the 2-week playoff matchup (250) is not a single game
    assert book["single_game"]["most_points"][0]["points"] == 140
    assert book["single_game"]["largest_margin"][0]["margin"] == 45
    assert book["playoffs"]["most_points_in_2_week_playoff_matchup"][0]["points"] == 250
    # consolation 70-point game is excluded from single-game records
    assert book["single_game"]["least_points"][0]["points"] == 90
    assert book["single_season"]["best_record"][0]["owner"] == "Alice"
    assert book["single_season"]["longest_win_streak"][0]["win_streak"] == 3
    assert book["single_season"]["longest_losing_streak"][0]["loss_streak"] == 3


def test_playoffs_and_career():
    in_progress = _season(2026)
    for t in in_progress.teams:
        t.final_rank = None
    in_progress.matchups = [m for m in in_progress.matchups if m.kind == MatchupKind.REGULAR]
    h = _history()
    h = LeagueHistory(h.seasons + [in_progress], {"alice": {"name": "Alice", "ids": ["A"]}})
    book = record_book(h)
    assert book["playoffs"]["most_appearances"][0]["appearances"] == 2  # 2026 not counted yet
    champs = book["playoffs"]["most_championships"][0]
    assert (champs["owner"], champs["championships"], champs["wins"]) == ("Alice", 2, 2)
    career = {r["owner"]: r for r in book["all_time"]["career"]}
    assert career["Alice"]["scoring_titles"] == 2
    assert career["Bob"]["winning_seasons"] == 2
    assert career["Dev"]["wins"] == 0


def test_rivalry_report_respects_order_and_freeze():
    h = _history()
    [r] = rivalry_report(h, [{"owners": ["B", "alice"]}])
    assert r["owners"] == ["Bob", "Alice"]
    assert r["wins"] == [0, 4]  # each season: 1 regular-season + 1 playoff win
    assert r["championships"] == [0, 2]
    [frozen] = rivalry_report(h, [{"owners": ["alice", "B"], "frozen_after": 2024}])
    assert frozen["wins"] == [2, 0]
    assert frozen["championships"] == [1, 0]


def test_owner_identity_survives_team_renames():
    h = _history()
    assert {o.name for o in h.owners()} == {"Alice", "Bob", "Cara", "Dev"}


def test_storage_round_trip(tmp_path):
    save_season(_season(2025), tmp_path)
    [loaded] = load_seasons(tmp_path)
    assert loaded == _season(2025)
