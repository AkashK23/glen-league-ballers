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



def test_co_owner_credit_goes_to_the_main_owner():
    s = _season(2022)
    s.owners.append(Owner("M", "Mayur"))
    s.teams[3].owner_ids = ["M", "D"]  # Mayur listed first on Dev's team
    owners = {"mayur": {"name": "Mayur", "ids": ["M"], "defer_to_co_owner": True}}
    assert LeagueHistory([s], owners).owner_of(s.teams[3]).name == "Dev"
    assert LeagueHistory([s]).owner_of(s.teams[3]).name == "Mayur"  # default: first listed


def test_play_in_games_do_not_count_toward_playoff_stats():
    s = _season(2019)
    # make week 4 a play-in (3 vs 4) and week 5 the real final (1 vs 3)
    s.matchups[-2] = Matchup(4, "3", "4", 90, 80, MatchupKind.PLAYOFF)
    s.matchups.append(Matchup(5, "1", "3", 120, 100, MatchupKind.PLAYOFF))
    s.playoff_team_count = 4
    with_rule = record_book(LeagueHistory([s], play_in_seasons=[2019]))["playoffs"]
    rows = {r["owner"]: r for r in with_rule["most_championships"]}
    assert (rows["Cara"]["wins"], rows["Cara"]["losses"]) == (0, 1)  # play-in win ignored
    assert "Dev" not in rows  # lost the play-in: no playoff appearance or games
    assert rows["Alice"]["wins"] == 1  # the final
    without = {r["owner"]: r for r in record_book(LeagueHistory([s]))["playoffs"]["most_championships"]}
    assert without["Cara"]["wins"] == 1 and without["Dev"]["appearances"] == 1


def test_power_ranking_week_and_markdown():
    from datetime import date

    from league_core.power_model import Knobs
    from league_core.power_rankings import compute, latest_final_week, to_markdown

    s = _season(2026)
    assert latest_final_week(s) == 3
    s.matchups[3] = Matchup(2, "2", "4", 0, 0, MatchupKind.REGULAR)  # week 2 not played yet
    assert latest_final_week(s) == 1

    s = _season(2026)
    h = LeagueHistory([s])
    ctx = compute(h, s, 2, Knobs(n_sims=500), {"Alice": 2})
    assert [t["owner"] for t in ctx["teams"]] == ["Alice", "Bob", "Cara", "Dev"]
    alice = ctx["teams"][0]
    assert (alice["record"], alice["allplay_record"], alice["prev_rank"]) == ("2-0", "5-1", 2)  # Bob's 125 beat her 120 in week 2
    by_owner = {t["owner"]: t for t in ctx["teams"]}
    assert by_owner["Alice"]["next_win_pct"] + by_owner["Dev"]["next_win_pct"] == 100  # week 3: Alice vs Dev
    assert sum(t["playoff_pct"] for t in ctx["teams"]) == 200  # 2 playoff spots

    narration = {
        "intro": "Hi.",
        "game_of_the_week": {"matchup": "Bob vs. Cara", "take": "Coin flip."},
        "teams": {t["owner"]: {"headline": "Head", "blurb": "One.\n\nTwo: \"quoted\""} for t in ctx["teams"]},
    }
    md = to_markdown(ctx, narration, author="Bot", today=date(2026, 10, 1))
    assert 'title: "Week 3"\nweek: 2\n' in md
    assert '  - owner: "Alice"\n    extras:\n      "Power score": ' in md
    assert '    blurb: |\n      **Head**\n\n      One.\n\n      Two: "quoted"\n' in md
    assert "---\n\nHi.\n\n**Game of the week: Bob vs. Cara.** Coin flip.\n" in md


def test_power_ranking_number_check():
    from league_core.power_rankings import unsupported_numbers

    prompt = "Alice 120.5 - Bob 98 (margin 22.5), playoff_pct 64, record 52-25"
    narration = {
        "intro": "Week 6 and 2 teams matter.",
        "game_of_the_week": {"matchup": "Alice vs. Bob", "take": "64% says Alice."},
        "teams": [
            {"owner": "Alice", "headline": "Won by 22.5", "blurb": "120.5 points, 52-25 all-play."},
            {"owner": "Bob", "headline": "Lost by 23.4", "blurb": "Scored 98.0, or 1,234 in spirit."},
        ],
    }
    assert unsupported_numbers(narration, prompt) == {"Bob": ["23.4", "1,234"]}


def test_power_model_backtest_runs():
    from league_core.power_model import backtest

    result = backtest([_season(2025), _season(2026)], start=2)
    assert result["ytd_weight"][0.6]["games"] == 8  # weeks 2-3, two games a week, two seasons
    assert 0 <= result["half_life"][3]["accuracy"] <= 1
