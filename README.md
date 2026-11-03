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
.venv/bin/python -m league_core rank               # model ranks the latest week, a local LLM writes it up
.venv/bin/python -m league_core backtest           # check the model against every past season
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

Every game links to a box score page (`/seasons/<year>/week/<n>`) with both
lineups, slot by slot, plus bench and projections. ESPN only has player-level
box scores from 2019 on; earlier weeks show final scores only.

Hand-written content:
- `web/src/content/seasons/<year>.md`: recap and `player_of_the_year` (see `2025.md`)
- `web/src/content/power-rankings/<year>/<name>.md`: written power rankings.
  Copy `web/src/content/power-rankings/TEMPLATE.md`; list teams in order with a
  blurb each. Records, PPG, titles and week-to-week movement are filled in
  automatically. The newest one also shows on the home page.
  The 2017–2025 rankings were imported from the old Weebly site as cleaned
  HTML (images in `web/public/power-rankings/`); they render as free-form
  write-ups.
- Power rankings bot: `python -m league_core rank` ranks the latest final
  regular-season week with the stats model in `src/league_core/power_model.py`
  (ported from `model_training/`), then a free local model writes the
  commentary. See "Power rankings bot" below.
- `web/src/content/season-extras/<year>/*.md`: extra season sections (rules,
  draft and playoff notes, teams and players, articles, media, punishments...).
  `section:` groups them on the season page; `title:` and `order:` set the bar
  label and position. Imported from the old site, images in `web/public/archive/`.
- `web/src/content/articles/*.md`: standalone articles (the First Era Recap),
  listed on `/articles` along with every season's articles.
- `web/src/assets/hero/<key>.jpg`: banner photos. Keys: `home`, `season`,
  `records`, `rivalries`, `stats`, `owner`, and `default` as the fallback.
  Without photos, a drawn striped background is used.

Featured rivalries, owner nicknames and site branding live in `config/league.toml`.

## Power rankings bot

- **Power score**: z-scored year-to-date metrics (all-play %, PPG, win %)
  blended with recent form (last-3 average, last week's all-play, trend).
  50 is league average.
- **Matchup odds**: each team's expected score is a recency-weighted average,
  shrunk toward the league mean early on, blended with lineup projections.
  Win probability assumes normally distributed scores.
- **Playoff odds**: 10,000 simulations of the rest of the regular season.
- **Commentary**: Claude, through the Claude Code CLI (`claude -p`), gets
  those numbers as fixed facts, plus the box scores, league history and past
  write-ups for voice, and writes the headlines, blurbs, intro and game of the
  week. It never changes ranks or odds. Any number in the write-up that isn't
  in the data goes back to Claude to fix once; anything left is printed as a
  warning. The CLI runs on a Claude Pro/Max login, so there's no API bill.

The Tuesday workflow writes the ranking right after the sync and deploys it
with the new stats. One-time setup: install the CLI
(`npm install -g @anthropic-ai/claude-code`), run `claude setup-token`, and
save the token as the `CLAUDE_CODE_OAUTH_TOKEN` repository secret. Without
that secret the workflow just skips the ranking. Set the byline, `model` and
the model knobs in `[power_rankings]` in `config/league.toml`.

To write one locally instead (logged in to `claude`):

```sh
.venv/bin/python -m league_core rank      # a couple of minutes
git add web/src/content/power-rankings && git commit -m "Week N power rankings" && git push
```

Pushing redeploys the site. Weeks that already have a file are skipped;
`--week 6 --force` redoes one, and `--no-ai` just prints the model's ranking.
The file is a normal ranking, so edit or delete it like a hand-written one.
`python -m league_core backtest` replays every synced season to show how each
knob setting would have predicted games.

## Deploying

`.github/workflows/update-site.yml` syncs the current season every Tuesday,
writes that week's power rankings, commits both, and deploys to GitHub Pages.
After pushing to GitHub: add `ESPN_S2` and `ESPN_SWID` as repository secrets
(plus `CLAUDE_CODE_OAUTH_TOKEN` for the power rankings), and set
Settings → Pages → Source to "GitHub Actions".
