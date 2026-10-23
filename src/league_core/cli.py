"""
  python -m league_core sync [--year 2026 ...]   pull seasons from the platform into data/seasons/
  python -m league_core build                    compute stats into web/src/data/ for the website
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


def main() -> None:
    p = argparse.ArgumentParser(prog="league_core")
    p.add_argument("--config", type=Path, default=ROOT / "config" / "league.toml")
    p.add_argument("--data", type=Path, default=ROOT / "data")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--year", type=int, action="append")
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, default=ROOT / "web" / "src" / "data")
    args = p.parse_args()

    _load_dotenv(ROOT / ".env")
    config = load_config(args.config)
    if args.cmd == "sync":
        cmd_sync(config, args.data, args.year)
    else:
        cmd_build(config, args.data, args.out)


if __name__ == "__main__":
    main()
