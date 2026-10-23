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
  web/src/data/*.json       ← what the website reads
          ▼
  web/ (Astro static site)
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
.venv/bin/python -m league_core build              # writes web/src/data/*.json
.venv/bin/pytest
```

After the first sync, look in `data/seasons/*.json` for each owner's id and
add them to `[owners.*]` in `config/league.toml`. That keeps someone's stats
together across team renames and account changes.

## Website

```sh
cd web
npm install
npm run dev        # http://localhost:4321, reloads as you edit
npm run build      # static site in web/dist
```

Pages: home (reigning champ, current standings, halls of champions/shame),
seasons, records, rivalries (featured + full H2H grid), statistics, and a
profile per owner.

Things the API can't know (Player of the Year, recaps, jokes) go in
`web/src/content/seasons/<year>.md`; see `2025.md` for the format.
Featured rivalries and owner nicknames live in `config/league.toml`.

## Deploying

`.github/workflows/update-site.yml` syncs the current season every Tuesday,
commits the new data, and deploys to GitHub Pages. After pushing to GitHub:
add `ESPN_S2` and `ESPN_SWID` as repository secrets, and set
Settings → Pages → Source to "GitHub Actions".
