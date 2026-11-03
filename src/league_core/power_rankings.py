"""Weekly power rankings: the stats model ranks, Claude writes.

After a regular-season week is final, `python -m league_core rank` runs the
model in power_model.py (power scores, next week's matchup odds, playoff odds)
and hands the results to Claude through the Claude Code CLI (`claude -p`) as
fixed facts, along with that week's box scores, league history and past
write-ups for voice. Claude writes the headlines and blurbs; it never changes
ranks or numbers, and any figure it writes that isn't in the data is sent back
to be fixed. The CLI runs on a Claude subscription login, so there's no API
bill.

The result goes to web/src/content/power-rankings/<year>/ in the TEMPLATE.md
format, so the site renders it exactly like a hand-written ranking.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from .history import LeagueHistory, is_completed
from .models import LineupEntry, MatchupKind, Season
from .power_model import (
    Knobs,
    build_features,
    expected,
    lineup_projection,
    power_scores,
    regular_games,
    simulate_season,
    team_strengths,
    unplayed,
    win_prob,
)

DEFAULT_MODEL = "opus"
DEFAULT_AUTHOR = "The Glen Bot"
VOICE_SAMPLES = 2  # past write-ups shown to the model so it sounds like the league
VOICE_SAMPLE_CHARS = 12000  # a style example only, so a very long one is cut short
ATTEMPTS = 2  # the first draft, plus one pass to fix missing teams or made-up numbers
TIMEOUT = 900  # seconds per CLI call

SYSTEM = """\
You write the weekly power rankings for {league}, a fantasy football league of \
friends that has been running since {first_year}. Your byline is "{author}"; \
everyone knows the rankings are written by a bot, and you can lean into that.

The ranks, power scores and probabilities you receive come from a statistical \
model and are final. Never reorder teams or change any figure; your job is to \
explain and entertain with them. Ground every take in the data: year-to-date \
body of work vs. recent form (trend), all-play record and luck (lucky teams \
have more wins than their scoring deserves), points vs. projection, rank \
movement, next week's odds and playoff odds, plus the box scores and league \
history. Never invent stats, trades, injuries or events: every number you \
write must appear in the data you were given.

Rankings in this league are trash talk first: roast the bad teams, give the \
good ones grudging respect, call out bad lineup decisions, and bring up \
history (titles, droughts, past collapses) when it lands. Keep it PG-13 and \
about fantasy football and the league itself, not anyone's real life beyond \
what the league's own write-ups already joke about.

For each team write a punchy headline and a blurb of one to three short \
paragraphs. Also write a short intro for the week and pick a game of the week \
from next week's matchups. Write plain text with blank lines between \
paragraphs; **bold**, *italic* and [links](https://example.com) are the only \
formatting allowed."""

SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {"type": "string"},
        "game_of_the_week": {
            "type": "object",
            "properties": {"matchup": {"type": "string"}, "take": {"type": "string"}},
            "required": ["matchup", "take"],
            "additionalProperties": False,
        },
        "teams": {
            "type": "array",
            "description": "Every team exactly once.",
            "items": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "headline": {"type": "string"},
                    "blurb": {"type": "string"},
                },
                "required": ["owner", "headline", "blurb"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["intro", "game_of_the_week", "teams"],
    "additionalProperties": False,
}


def latest_final_week(season: Season) -> int | None:
    """The last regular-season week whose games are all final."""
    weeks: dict[int, bool] = {}
    for m in season.matchups:
        if m.kind == MatchupKind.REGULAR and not m.is_bye and m.week <= season.regular_season_weeks:
            weeks[m.week] = weeks.get(m.week, True) and is_completed(m)
    last = None
    for w in sorted(weeks):
        if not weeks[w]:
            break
        last = w
    return last


def ranking_path(content_dir: Path, year: int, week: int) -> Path:
    # Titled for the week ahead, like the league's own: "Week 7" ranks teams through week 6.
    return content_dir / str(year) / f"{week:02d}-week-{week + 1}.md"


def _fmt(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _record(w: float, l: float, t: float = 0) -> str:
    return f"{round(w)}-{round(l)}" + (f"-{round(t)}" if t else "")


def _previous(content_dir: Path, year: int, week: int) -> Path | None:
    earlier = sorted(p for p in (content_dir / str(year)).glob("*.md") if p.name < ranking_path(content_dir, year, week).name)
    return earlier[-1] if earlier else None


def previous_ranks(content_dir: Path, year: int, week: int) -> dict[str, int]:
    """Owner -> rank in the season's previous ranking (written or generated)."""
    prev = _previous(content_dir, year, week)
    if prev is None:
        return {}
    owners = re.findall(r'^\s*- owner:\s*"?([^"\n]+?)"?\s*$', prev.read_text(encoding="utf-8"), re.M)
    return {o: i for i, o in enumerate(owners, 1)}


def compute(h: LeagueHistory, s: Season, week: int, knobs: Knobs, prev_ranks: dict[str, int]) -> dict:
    """Run the model through `week` and shape the results by owner name."""
    owner = {t.team_id: h.owner_of(t).name for t in s.teams}
    games = regular_games(s, week)
    ranked = power_scores(build_features(games, knobs.recent_weeks), knobs.ytd_weight)
    strengths = team_strengths(games, knobs.half_life, knobs.prior_games)
    feat = {f.team_id: f for f in ranked}
    remaining = unplayed(s, week)
    sim = simulate_season(feat, strengths, remaining, s.playoff_team_count, knobs.n_sims) if remaining else {}

    next_games = []
    for m in remaining:
        if m.week != week + 1:
            continue
        a = expected(strengths[m.home_team_id], lineup_projection(m, True), knobs.proj_weight)
        b = expected(strengths[m.away_team_id], lineup_projection(m, False), knobs.proj_weight)
        next_games.append((m.home_team_id, m.away_team_id, a.mu, b.mu, win_prob(a, b)))
    opp_of = {}
    for ta, tb, mu_a, mu_b, p in next_games:
        opp_of[ta] = (tb, p, mu_a)
        opp_of[tb] = (ta, 1 - p, mu_b)

    teams = []
    for f in ranked:
        name = owner[f.team_id]
        opp = opp_of.get(f.team_id)
        t = {
            "rank": f.rank,
            "prev_rank": prev_ranks.get(name),
            "owner": name,
            "team_name": s.team(f.team_id).name,
            "record": _record(f.wins, f.losses, f.ties),
            "allplay_record": _record(f.allplay_w, f.allplay_l),
            "power": round(f.power, 1),
            "pf_avg": round(f.pf_avg, 1),
            "recent_avg": round(f.recent_avg, 1),
            "last_score": round(f.last_score, 1),
            "trend": round(f.trend, 1),
            "luck": round(f.luck, 1),
            "vs_proj": round(f.vs_proj, 1),
            "next_opp": owner[opp[0]] if opp else None,
            "next_win_pct": round(100 * opp[1]) if opp else None,
            "next_proj": round(opp[2], 1) if opp else None,
        }
        if f.team_id in sim:
            t["proj_wins"] = round(sim[f.team_id]["proj_wins"], 1)
            t["playoff_pct"] = round(100 * sim[f.team_id]["playoff_pct"])
            t["top_seed_pct"] = round(100 * sim[f.team_id]["top_seed_pct"])
        teams.append(t)

    matchups = []
    for ta, tb, mu_a, mu_b, p in sorted(next_games, key=lambda g: abs(g[4] - 0.5)):  # closest games first
        fav, pct = (ta, p) if p >= 0.5 else (tb, 1 - p)
        matchups.append({
            "team_a": owner[ta], "team_b": owner[tb],
            "proj_a": round(mu_a, 1), "proj_b": round(mu_b, 1),
            "favorite": owner[fav], "favorite_pct": round(100 * pct),
        })

    return {
        "year": s.year,
        "week": week,
        "regular_season_weeks": s.regular_season_weeks,
        "playoff_teams": s.playoff_team_count,
        "recent_weeks": knobs.recent_weeks,
        "teams": teams,
        "next_week_matchups": matchups,
    }


def _lineup_notes(lineup: list[LineupEntry]) -> str:
    starters = sorted((e for e in lineup if e.is_starter), key=lambda e: -e.points)
    bench = sorted((e for e in lineup if not e.is_starter), key=lambda e: -e.points)

    def player(e: LineupEntry) -> str:
        proj = f", proj {_fmt(e.projected_points)}" if e.projected_points is not None else ""
        return f"{e.player_name} ({e.slot}) {_fmt(e.points)}{proj}"

    notes = [f"starters: {'; '.join(player(e) for e in starters)}"]
    if bench:
        notes.append(f"best bench: {'; '.join(player(e) for e in bench[:3])}")
    return " | ".join(notes)


def _week_results(h: LeagueHistory, s: Season, week: int) -> str:
    out = []
    for m in s.matchups:
        if m.week != week or m.kind != MatchupKind.REGULAR or m.is_bye:
            continue
        home, away = h.owner_of(s.team(m.home_team_id)).name, h.owner_of(s.team(m.away_team_id)).name
        out.append(f"### {home} {_fmt(m.home_score)} - {away} {_fmt(m.away_score)} (margin {_fmt(abs(m.home_score - m.away_score))})")
        for box in m.box_scores:
            out.append(f"- {home}: {_lineup_notes(box.home_lineup)}")
            out.append(f"- {away}: {_lineup_notes(box.away_lineup)}")
    return "\n".join(out)


def _history_notes(h: LeagueHistory, year: int, owners: list[str]) -> str:
    lines = []
    for owner in owners:
        titles = [s.year for s in h.seasons if s.year < year and s.champion and h.owner_of(s.champion).name == owner]
        lasts = [
            s.year for s in h.seasons
            if s.year < year and s.champion and h.owner_of(max(s.teams, key=lambda t: t.final_rank or 0)).name == owner
        ]
        first = min(s.year for s in h.seasons if any(h.owner_of(t).name == owner for t in s.teams))
        lines.append(f"- {owner}: own team since {first}; titles {titles or 'none'}; last-place finishes {lasts or 'none'}")
    return "\n".join(lines)


def _plain(md: str) -> str:
    """A past ranking as readable text (the imported ones are HTML)."""
    text = re.sub(r"<br\s*/?>|</p>", "\n", md)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _voice_samples(content_dir: Path, author: str) -> list[str]:
    files = sorted(
        (p for p in content_dir.glob("*/*.md") if p.name != "TEMPLATE.md" and author not in p.read_text(encoding="utf-8")[:500]),
        key=lambda p: (p.parent.name, p.name),
    )
    samples = []
    for p in reversed(files):
        text = _plain(p.read_text(encoding="utf-8"))
        if len(text) > 3000:  # skip placeholders like "will be uploaded"
            samples.append(text[:VOICE_SAMPLE_CHARS])
        if len(samples) == VOICE_SAMPLES:
            break
    return samples


def build_prompt(h: LeagueHistory, s: Season, context: dict, content_dir: Path, author: str) -> str:
    week = context["week"]
    owners = [t["owner"] for t in context["teams"]]
    parts = []
    for i, sample in enumerate(_voice_samples(content_dir, author), 1):
        parts.append(f'<past_ranking index="{i}">\n{sample}\n</past_ranking>')
    parts.append(f"<league_history>\n{_history_notes(h, s.year, sorted(owners))}\n</league_history>")
    parts.append(f"<model_output>\n{json.dumps(context, indent=1, ensure_ascii=False)}\n</model_output>")
    parts.append(f"<week_{week}_box_scores>\n{_week_results(h, s, week)}\n</week_{week}_box_scores>")
    parts.append(
        f"Write the {s.year} power rankings after week {week} of {s.regular_season_weeks}. "
        f"The teams in model_output are already in rank order. Write about all {len(owners)}, "
        f"using exactly these owner names: {', '.join(owners)}."
    )
    return "\n\n".join(parts)


def _claude(system: str, prompt: str, model: str) -> dict:
    """One `claude -p` call that returns JSON matching SCHEMA."""
    cmd = [
        os.environ.get("CLAUDE_CLI", "claude"), "-p",
        "--model", model,
        "--system-prompt", system,
        "--json-schema", json.dumps(SCHEMA),
        "--output-format", "json",
        "--tools", "",  # everything it needs is in the prompt
        "--no-session-persistence",
    ]
    # Run from an empty folder so the repo's own files and settings stay out of it.
    with tempfile.TemporaryDirectory() as cwd:
        try:
            done = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=cwd, timeout=TIMEOUT)
        except FileNotFoundError as e:
            raise RuntimeError("Claude Code CLI not found: `npm install -g @anthropic-ai/claude-code`, or set CLAUDE_CLI") from e
    try:
        reply = json.loads(done.stdout)
    except json.JSONDecodeError:
        reply = {}
    if done.returncode or reply.get("is_error"):
        detail = reply.get("result") or done.stderr.strip() or done.stdout.strip()
        raise RuntimeError(f"claude -p failed: {detail} (logged in? `claude setup-token` makes a token for CI)")
    if reply.get("structured_output"):
        return reply["structured_output"]
    text = reply.get("result", "")
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    return {float(n.replace(",", "")) for n in _NUMBER.findall(text)}


def unsupported_numbers(narration: dict, prompt: str) -> dict[str, list[str]]:
    """Figures in the write-up that appear nowhere in the data it was given.

    Small whole numbers (counts, weeks, ranks) pass, since they're usually
    "two titles" or "week 6" rather than stats.
    """
    known = _numbers(prompt)
    pieces = {"intro": narration["intro"], "game of the week": narration["game_of_the_week"]["take"]}
    pieces.update({t["owner"]: f"{t['headline']} {t['blurb']}" for t in narration["teams"]})
    bad = {}
    for where, text in pieces.items():
        odd = [n for n in _NUMBER.findall(text) if float(n.replace(",", "")) not in known and not (n.isdigit() and int(n) <= 20)]
        if odd:
            bad[where] = sorted(set(odd), key=odd.index)
    return bad


def narrate(h: LeagueHistory, s: Season, context: dict, content_dir: Path, site: dict, author: str,
            model: str = DEFAULT_MODEL) -> dict:
    """Claude's intro, game of the week and per-owner headline and blurb."""
    system = SYSTEM.format(league=site.get("name", s.league_name), first_year=h.seasons[0].year, author=author)
    prompt = build_prompt(h, s, context, content_dir, author)
    owners = {t["owner"].casefold(): t["owner"] for t in context["teams"]}
    request = prompt
    for attempt in range(1, ATTEMPTS + 1):
        data = _claude(system, request, model)
        named = {owners.get(t["owner"].strip().casefold()): t for t in data["teams"]}
        named.pop(None, None)
        missing = sorted(set(owners.values()) - set(named))
        bad = unsupported_numbers(data, prompt)
        if not missing and (not bad or attempt == ATTEMPTS):
            for where, nums in bad.items():
                print(f"  warning: {where} still cites {', '.join(nums)}, which isn't in the data")
            data["teams"] = {o: dict(t, owner=o) for o, t in named.items()}
            return data
        problems = [f"- Missing teams: {', '.join(missing)}"] if missing else []
        problems += [f"- {where}: {', '.join(nums)}" for where, nums in bad.items()]
        print(f"  attempt {attempt}: fixing\n" + "\n".join(problems))
        request = (
            f"{prompt}\n\n<draft>\n{json.dumps(data, indent=1, ensure_ascii=False)}\n</draft>\n\n"
            "Revise the draft above. Every number must come straight from the data (scores, margins, "
            "projections, model_output); these don't, so replace each with the real figure or rephrase "
            "without it, and write about every team:\n" + "\n".join(problems) +
            "\nKeep everything else as it is."
        )
    raise RuntimeError("Claude didn't write about every team; no ranking written")


def _extras(t: dict, recent_weeks: int) -> list[tuple[str, str]]:
    out = [
        ("Power score", f"{t['power']} (all-play {t['allplay_record']}, luck {t['luck']:+.1f} wins)"),
        ("Form", f"{t['recent_avg']} PPG over the last {recent_weeks} weeks, {t['pf_avg']} for the season"),
    ]
    if t["next_opp"]:
        out.append(("Next week", f"vs. {t['next_opp']}, {t['next_win_pct']}% to win"))
    if "playoff_pct" in t:
        out.append(("Playoff odds", f"{t['playoff_pct']}% (projected {t['proj_wins']} wins)"))
    return out


def to_markdown(context: dict, narration: dict, author: str, today: date) -> str:
    def q(text: str) -> str:  # a JSON string is a valid YAML scalar
        return json.dumps(text, ensure_ascii=False)

    week = context["week"]
    lines = [
        "---",
        f"title: {q(f'Week {week + 1}')}",
        f"week: {week}",
        f"order: {week}",
        f"author: {q(author)}",
        f"date: {today.isoformat()}",
        "",
        "rankings:",
    ]
    for t in context["teams"]:
        n = narration["teams"][t["owner"]]
        lines.append(f"  - owner: {q(t['owner'])}")
        lines.append("    extras:")
        lines += [f"      {q(k)}: {q(v)}" for k, v in _extras(t, context['recent_weeks'])]
        lines.append("    blurb: |")
        blurb = f"**{n['headline'].strip()}**\n\n{n['blurb'].strip()}"
        lines += [f"      {line}".rstrip() for line in blurb.splitlines()]
        lines.append("")
    lines += ["---", "", narration["intro"].strip(), ""]

    gotw = narration["game_of_the_week"]
    lines += [f"**Game of the week: {gotw['matchup'].strip()}.** {gotw['take'].strip()}", ""]
    if context["next_week_matchups"]:
        lines += [f"Week {week + 1} odds:", "", "| Matchup | Projected | Favorite |", "|---|---|---|"]
        for m in context["next_week_matchups"]:
            lines.append(
                f"| {m['team_a']} vs. {m['team_b']} | {m['proj_a']:.1f}-{m['proj_b']:.1f} "
                f"| {m['favorite']} ({m['favorite_pct']}%) |"
            )
        lines.append("")
    return "\n".join(lines)


def table(context: dict) -> str:
    """The model's ranking as plain text, for `rank --no-ai`."""
    rows = [f"{context['year']} power rankings through week {context['week']}"]
    for t in context["teams"]:
        playoffs = f"  playoffs {t['playoff_pct']:>3}%" if "playoff_pct" in t else ""
        nxt = f"  next: {t['next_win_pct']:>3}% vs {t['next_opp']}" if t["next_opp"] else ""
        rows.append(
            f"{t['rank']:>2}. {t['owner']:<8} {t['record']:<6} power {t['power']:>5}  "
            f"all-play {t['allplay_record']:<6} luck {t['luck']:+5.1f}{playoffs}{nxt}"
        )
    return "\n".join(rows)
