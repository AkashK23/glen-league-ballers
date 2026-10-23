# Fantasy League Archive

League history, records, and rivalries for our fantasy football league,
pulled automatically from the fantasy platform (ESPN today).

## How it fits together

```
 ESPN / Sleeper / Yahoo API
          │
  providers/<platform>.py   ← the ONLY platform-specific code
          │  converts the API response into models.py types
          ▼
  data/seasons/<year>.json  ← normalized, committed to git
          │
  history.py + stats/       ← records, rivalries, H2H (no platform knowledge)
          │
  public/data/*.json        ← what the website reads
          ▼
       website
```

To switch platforms, add `providers/sleeper.py` (or another) that implements
`LeagueProvider.fetch_season(year) -> Season`, register it in
`providers/__init__.py`, and change `provider` in `config/league.toml`. Past
seasons stay in `data/seasons/` and never have to be fetched again, so history
from the old platform carries over.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[espn,dev]'
cp .env.example .env    # add ESPN_S2 / ESPN_SWID cookies for a private league
# set league_id and first_year in config/league.toml
```

## Usage

```sh
.venv/bin/python -m league_core sync               # every season since first_year
.venv/bin/python -m league_core sync --year 2026   # just one season
.venv/bin/python -m league_core build              # writes public/data/*.json
.venv/bin/pytest
```

After the first sync, look in `data/seasons/*.json` for each owner's id and
add them to `[owners.*]` in `config/league.toml`. That keeps someone's stats
together across team renames and account changes.
