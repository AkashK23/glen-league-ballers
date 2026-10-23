from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Season


class LeagueProvider(ABC):
    """The only interface that touches a fantasy platform.

    To support a new platform, subclass this, implement `fetch_season`, and
    register it in `providers/__init__.py`.
    """

    name: str

    @abstractmethod
    def fetch_season(self, year: int) -> Season:
        """Return a fully normalized Season for `year`."""

    def available_years(self) -> list[int] | None:
        """Seasons this league has on the platform, if the platform can tell us."""
        return None
