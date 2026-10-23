"""Normalized seasons are cached as data/seasons/<year>.json and committed.

Finished seasons never need to be fetched again, and a season from a platform
we no longer use (or typed in by hand) is just another JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Season


def save_season(season: Season, data_dir: Path) -> Path:
    path = data_dir / "seasons" / f"{season.year}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(season.to_dict(), indent=2, default=str) + "\n")
    return path


def load_seasons(data_dir: Path) -> list[Season]:
    return [
        Season.from_dict(json.loads(p.read_text()))
        for p in sorted((data_dir / "seasons").glob("*.json"))
    ]
