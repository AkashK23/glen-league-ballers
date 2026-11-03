"""
  python -m league_core sync [--year 2026 ...]   pull seasons from the platform into data/seasons/
  python -m league_core build                    compute stats into web/src/data/ for the website
  python -m league_core rank [--week 6] [--no-ai] rank the latest week with the stats model; Claude writes it up
  python -m league_core backtest                 check the model's predictions against every past season
"""

from __future__ import annotations

import argparse
import json
import tomllib
from datetime import date
from pathlib import Path

from .export import build_site_data
from .history import LeagueHistory
from .providers import get_provider
from .storage import load_seasons, save_season

ROOT = Path(__file__).resolve().parents[2]


def load_config(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def _load_dotenv(path: Path) -> None:
    import os

    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def cmd_sync(config: dict, data_dir: Path, years: list[int] | None) -> None:
    league = config["league"]
    provider = get_provider(league)
    if not years:
        years = list(range(league["first_year"], date.today().year + 1))
    for year in years:
        try:
            season = provider.fetch_season(year)
        except Exception as e:  # noqa: BLE001 - keep going so one bad year doesn't block the rest
            print(f"  {year}: skipped ({e})")
            continue
        print(f"  {year}: {len(season.teams)} teams, {len(season.matchups)} matchups -> {save_season(season, data_dir)}")


def cmd_build(config: dict, data_dir: Path, out_dir: Path) -> None:
    history = LeagueHistory(load_seasons(data_dir), config.get("owners"), config.get("league", {}).get("play_in_seasons"))
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in build_site_data(history, config).items():
        path = out_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"Built {len(history.seasons)} seasons -> {out_dir}")


def cmd_rank(config: dict, data_dir: Path, content_dir: Path, year: int | None, week: int | None, force: bool, no_ai: bool) -> None:
    from . import power_rankings as pr
    from .power_model import Knobs

    history = LeagueHistory(load_seasons(data_dir), config.get("owners"), config.get("league", {}).get("play_in_seasons"))
    year = year or date.today().year
    season = next((s for s in history.seasons if s.year == year), None)
    if season is None:
        print(f"No {year} season in {data_dir}; run sync first")
        return
    week = week or pr.latest_final_week(season)
    if not week:
        print(f"No final {year} regular-season week yet; nothing to rank")
        return
    rank_cfg = config.get("power_rankings", {})
    context = pr.compute(history, season, week, Knobs.from_config(rank_cfg), pr.previous_ranks(content_dir, year, week))
    print(pr.table(context))
    if no_ai:
        return
    path = pr.ranking_path(content_dir, year, week)
    if path.exists() and not force:
        print(f"Already ranked: {path}")
        return
    author = rank_cfg.get("author", pr.DEFAULT_AUTHOR)
    model = rank_cfg.get("model", pr.DEFAULT_MODEL)
    print(f"Writing commentary with Claude ({model})...")
    narration = pr.narrate(history, season, context, content_dir, config.get("site", {}), author, model=model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pr.to_markdown(context, narration, author, date.today()), encoding="utf-8")
    print(f"Ranked {year} week {week} -> {path}")


def cmd_backtest(data_dir: Path, start: int) -> None:
    from .power_model import backtest

    result = backtest(load_seasons(data_dir), start)
    knobs = result["knobs"]

    def show(title: str, key: str, current, brier: bool = True) -> None:
        print(title)
        print(f"{key:>12} {'accuracy':>9}" + (f" {'brier':>7}" if brier else ""))
        for k, r in result[key].items():
            if not r["games"]:
                continue
            mark = "  <- current" if k == current else ""
            print(f"{k:>12} {r['accuracy']:>9.1%}" + (f" {r['brier']:>7.3f}" if brier else "") + mark)
        print(f"({max(r['games'] for r in result[key].values())} games)\n")

    print(f"Every regular-season week from week {start} on, all synced seasons. Brier: lower is better, coin flip = 0.25\n")
    show("Win probability by half-life (weeks)", "half_life", knobs.half_life)
    show("Win probability by projection weight (seasons with box scores)", "proj_weight", knobs.proj_weight)
    show("Power-ranking picks (higher power score wins) by YTD weight", "ytd_weight", knobs.ytd_weight, brier=False)


def main() -> None:
    p = argparse.ArgumentParser(prog="league_core")
    p.add_argument("--config", type=Path, default=ROOT / "config" / "league.toml")
    p.add_argument("--data", type=Path, default=ROOT / "data")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--year", type=int, action="append")
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, default=ROOT / "web" / "src" / "data")
    r = sub.add_parser("rank")
    r.add_argument("--year", type=int)
    r.add_argument("--week", type=int, help="rank through this week (default: latest final week)")
    r.add_argument("--force", action="store_true", help="rewrite a ranking that already exists")
    r.add_argument("--no-ai", action="store_true", help="print the model's ranking without writing anything")
    r.add_argument("--content", type=Path, default=ROOT / "web" / "src" / "content" / "power-rankings")
    bt = sub.add_parser("backtest")
    bt.add_argument("--start", type=int, default=3, help="first week of each season to predict")
    args = p.parse_args()

    _load_dotenv(ROOT / ".env")
    config = load_config(args.config)
    if args.cmd == "sync":
        cmd_sync(config, args.data, args.year)
    elif args.cmd == "rank":
        cmd_rank(config, args.data, args.content, args.year, args.week, args.force, args.no_ai)
    elif args.cmd == "backtest":
        cmd_backtest(args.data, args.start)
    else:
        cmd_build(config, args.data, args.out)


if __name__ == "__main__":
    main()
