from __future__ import annotations

import os

from .base import LeagueProvider


def get_provider(config: dict) -> LeagueProvider:
    """Build the provider named in config/league.toml. Secrets come from env."""
    name = config["provider"]
    if name == "espn":
        from .espn import EspnProvider

        return EspnProvider(
            league_id=int(config["league_id"]),
            espn_s2=os.environ.get("ESPN_S2"),
            swid=os.environ.get("ESPN_SWID"),
        )
    # elif name == "sleeper": return SleeperProvider(...)
    raise ValueError(f"Unknown provider: {name!r}")


__all__ = ["LeagueProvider", "get_provider"]
