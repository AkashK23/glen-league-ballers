"""The stats model behind the power rankings, ported from model_training/powerrank.

- Power score: z-scored year-to-date metrics (all-play %, PPG, win %) blended
  with recent form (last-N average, last week's all-play, trend). 50 = average.
- Team strength: recency-weighted scoring average and spread, shrunk toward
  the league early in the season. Drives matchup odds (normal scores) and a
  Monte Carlo of the rest of the regular season for playoff odds.

Works on regular-season games only, straight from the normalized Seasons, so
it runs on every synced year and the backtest can use all of them.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import fmean, pstdev, stdev

from .history import is_completed
from .models import Matchup, MatchupKind, Season

# Metric weights inside each block (each block sums to 1).
YTD_METRICS = {"allplay_pct": 0.5, "pf_avg": 0.3, "win_pct": 0.2}
RECENT_METRICS = {"recent_avg": 0.5, "last_allplay": 0.3, "trend": 0.2}


@dataclass
class Knobs:
    ytd_weight: float = 0.6  # share of the power score from year-to-date metrics (rest is recent form)
    recent_weeks: int = 3  # window for "recent" metrics
    half_life: float = 3.0  # weeks; recency decay for the scoring-strength estimate
    prior_games: float = 2.0  # pseudo-games of league-average scoring to shrink early-season estimates
    proj_weight: float = 0.5  # how much to trust platform projections for next week's matchups (0-1)
    n_sims: int = 10000

    @classmethod
    def from_config(cls, cfg: dict) -> Knobs:
        return cls(**{k: type(getattr(cls(), k))(cfg[k]) for k in cls.__dataclass_fields__ if k in cfg})


@dataclass
class Game:
    """One team's side of one completed game."""

    week: int
    team_id: str
    opp_id: str
    score: float
    opp_score: float
    proj: float | None  # the lineup's projected points, when the platform has box scores

    @property
    def result(self) -> float:
        return 1.0 if self.score > self.opp_score else 0.5 if self.score == self.opp_score else 0.0


@dataclass
class Strength:
    mu: float  # expected weekly score
    sd: float


@dataclass
class TeamModel:
    team_id: str
    games: int
    wins: int
    losses: int
    ties: int
    win_pct: float
    pf: float
    pa: float
    pf_avg: float
    allplay_pct: float
    allplay_w: float
    allplay_l: float
    exp_wins: float
    luck: float  # wins above what the team's scoring deserved
    recent_avg: float
    last_score: float
    last_allplay: float
    trend: float  # recent average minus season average
    vs_proj: float  # average points above projection
    power: float = 50.0
    rank: int = 0


def lineup_projection(m: Matchup, home: bool) -> float | None:
    if not m.box_scores:
        return None
    total = sum(
        e.projected_points or 0
        for b in m.box_scores
        for e in (b.home_lineup if home else b.away_lineup)
        if e.is_starter
    )
    return total or None


def regular_games(s: Season, through_week: int | None = None) -> list[Game]:
    out = []
    for m in s.matchups:
        if m.kind != MatchupKind.REGULAR or m.is_bye or not is_completed(m):
            continue
        if through_week is not None and m.week > through_week:
            continue
        out.append(Game(m.week, m.home_team_id, m.away_team_id, m.home_score, m.away_score, lineup_projection(m, True)))
        out.append(Game(m.week, m.away_team_id, m.home_team_id, m.away_score, m.home_score, lineup_projection(m, False)))
    return out


def unplayed(s: Season, after_week: int) -> list[Matchup]:
    """Regular-season games after `after_week`, i.e. the rest of the schedule."""
    return [
        m for m in s.matchups
        if m.kind == MatchupKind.REGULAR and not m.is_bye and after_week < m.week <= s.regular_season_weeks
    ]


def _allplay(games: list[Game]) -> dict[int, tuple[float, float]]:
    """id(game) -> (teams beaten that week, teams it lost to), ties counting half."""
    by_week: dict[int, list[Game]] = {}
    for g in games:
        by_week.setdefault(g.week, []).append(g)
    out = {}
    for wk in by_week.values():
        n = len(wk)
        for g in wk:
            below = sum(o.score < g.score for o in wk) + 0.5 * (sum(o.score == g.score for o in wk) - 1)
            out[id(g)] = (below, (n - 1) - below)
    return out


def build_features(games: list[Game], recent_weeks: int = 3) -> dict[str, TeamModel]:
    ap = _allplay(games)
    last_week = max(g.week for g in games)
    by_team: dict[str, list[Game]] = {}
    for g in sorted(games, key=lambda g: g.week):
        by_team.setdefault(g.team_id, []).append(g)

    out = {}
    for tid, gs in by_team.items():
        share = [ap[id(g)][0] / max(sum(ap[id(g)]), 1) for g in gs]
        scores = [g.score for g in gs]
        wins = sum(g.result == 1 for g in gs)
        ties = sum(g.result == 0.5 for g in gs)
        pf_avg = fmean(scores)
        recent = [g.score for g in gs if g.week > last_week - recent_weeks] or scores
        projected = [g.score - g.proj for g in gs if g.proj]
        out[tid] = TeamModel(
            team_id=tid,
            games=len(gs),
            wins=wins,
            losses=sum(g.result == 0 for g in gs),
            ties=ties,
            win_pct=fmean(g.result for g in gs),
            pf=sum(scores),
            pa=sum(g.opp_score for g in gs),
            pf_avg=pf_avg,
            allplay_pct=fmean(share),
            allplay_w=sum(ap[id(g)][0] for g in gs),
            allplay_l=sum(ap[id(g)][1] for g in gs),
            exp_wins=sum(share),
            luck=wins + 0.5 * ties - sum(share),
            recent_avg=fmean(recent),
            last_score=gs[-1].score,
            last_allplay=share[-1],
            trend=fmean(recent) - pf_avg,
            vs_proj=fmean(projected) if projected else 0.0,
        )
    return out


def _z(values: dict[str, float]) -> dict[str, float]:
    mean, sd = fmean(values.values()), pstdev(values.values())
    return {k: (v - mean) / sd if sd > 0 else 0.0 for k, v in values.items()}


def power_scores(feat: dict[str, TeamModel], ytd_weight: float) -> list[TeamModel]:
    """Blend z-scored YTD and recent metrics into a 0-100ish power score (50 = league average); best first."""

    def block(metrics: dict[str, float]) -> dict[str, float]:
        zs = {m: _z({t: getattr(f, m) for t, f in feat.items()}) for m in metrics}
        return {t: sum(w * zs[m][t] for m, w in metrics.items()) for t in feat}

    ytd, recent = block(YTD_METRICS), block(RECENT_METRICS)
    for t, f in feat.items():
        f.power = 50 + 10 * (ytd_weight * ytd[t] + (1 - ytd_weight) * recent[t])
    ranked = sorted(feat.values(), key=lambda f: -f.power)
    for i, f in enumerate(ranked, 1):
        f.rank = i
    return ranked


def team_strengths(games: list[Game], half_life: float, prior_games: float) -> dict[str, Strength]:
    """Expected weekly score (mu) and spread (sd) per team.

    mu is a recency-weighted mean shrunk toward the league mean; sd is the team's spread
    shrunk toward the typical within-team spread. Both shrinkages fade as games accumulate.
    """
    last = max(g.week for g in games)
    league_mean = fmean(g.score for g in games)
    by_team: dict[str, list[Game]] = {}
    for g in games:
        by_team.setdefault(g.team_id, []).append(g)
    spreads = [stdev(g.score for g in gs) for gs in by_team.values() if len(gs) > 1]
    league_sd = fmean(spreads) if spreads else 0.0
    if not league_sd > 0:
        league_sd = pstdev(g.score for g in games) or 20.0

    out = {}
    for tid, gs in by_team.items():
        w = [0.5 ** ((last - g.week) / half_life) for g in gs]
        n = len(gs)
        mu_raw = sum(wi * g.score for wi, g in zip(w, gs)) / sum(w)
        mu = (n * mu_raw + prior_games * league_mean) / (n + prior_games)
        var = stdev(g.score for g in gs) ** 2 if n > 1 else league_sd**2
        sd = math.sqrt(((n - 1) * var + prior_games * league_sd**2) / ((n - 1) + prior_games))
        out[tid] = Strength(mu, sd)
    return out


def win_prob(a: Strength, b: Strength) -> float:
    z = (a.mu - b.mu) / math.sqrt(a.sd**2 + b.sd**2)
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def expected(s: Strength, proj: float | None, proj_weight: float) -> Strength:
    """A team's strength for one game, blended with its lineup projection when there is one."""
    if proj and proj_weight > 0:
        return Strength((1 - proj_weight) * s.mu + proj_weight * proj, s.sd)
    return s


def simulate_season(feat: dict[str, TeamModel], strengths: dict[str, Strength], remaining: list[Matchup],
                    playoff_teams: int, n_sims: int = 10000, seed: int = 0) -> dict[str, dict]:
    """Monte Carlo the rest of the regular season. Seeding is by wins, then points for."""
    rng = random.Random(seed)
    ids = list(strengths)
    base_w = {t: feat[t].wins + 0.5 * feat[t].ties for t in ids}
    base_pf = {t: feat[t].pf for t in ids}
    total_w = dict.fromkeys(ids, 0.0)
    playoffs = dict.fromkeys(ids, 0)
    top_seed = dict.fromkeys(ids, 0)
    for _ in range(n_sims):
        wins, pf = dict(base_w), dict(base_pf)
        for m in remaining:
            a, b = m.home_team_id, m.away_team_id
            sa = rng.gauss(strengths[a].mu, strengths[a].sd)
            sb = rng.gauss(strengths[b].mu, strengths[b].sd)
            wins[a] += sa > sb
            wins[b] += sb > sa
            pf[a] += sa
            pf[b] += sb
        order = sorted(ids, key=lambda t: (-wins[t], -pf[t]))
        top_seed[order[0]] += 1
        for t in order[:playoff_teams]:
            playoffs[t] += 1
        for t in ids:
            total_w[t] += wins[t]
    return {
        t: {"proj_wins": total_w[t] / n_sims, "playoff_pct": playoffs[t] / n_sims, "top_seed_pct": top_seed[t] / n_sims}
        for t in ids
    }


def backtest(seasons: list[Season], start: int = 3) -> dict:
    """Replay every week from `start` on, in every season, using only earlier weeks.

    Returns accuracy and Brier score of the win-probability model for a grid of
    half-lives and projection weights, and how often the higher power score wins
    for a grid of YTD weights.
    """
    knobs = Knobs()
    half_lives = (1, 2, 3, 5, math.inf)
    proj_weights = (0.0, 0.25, 0.5, 0.75, 1.0)
    ytd_weights = (0.0, 0.25, 0.5, 0.6, 0.75, 1.0)
    strength_hits = {hl: [] for hl in half_lives}
    strength_brier = {hl: [] for hl in half_lives}
    proj_hits = {pw: [] for pw in proj_weights}
    proj_brier = {pw: [] for pw in proj_weights}
    power_hits = {wt: [] for wt in ytd_weights}

    for s in seasons:
        games = regular_games(s)
        if not games:
            continue
        for w in range(start, max(g.week for g in games) + 1):
            past = [g for g in games if g.week < w]
            now = [g for g in games if g.week == w and g.team_id < g.opp_id and g.result != 0.5]
            if not past or not now:
                continue
            for hl in half_lives:
                st = team_strengths(past, hl, knobs.prior_games)
                for g in now:
                    p = win_prob(st[g.team_id], st[g.opp_id])
                    strength_hits[hl].append((p > 0.5) == (g.result == 1))
                    strength_brier[hl].append((p - g.result) ** 2)
            st = team_strengths(past, knobs.half_life, knobs.prior_games)
            opp_proj = {(g.week, g.team_id): g.proj for g in games}
            for pw in proj_weights:
                for g in now:
                    if not g.proj:
                        continue
                    p = win_prob(expected(st[g.team_id], g.proj, pw), expected(st[g.opp_id], opp_proj[(w, g.opp_id)], pw))
                    proj_hits[pw].append((p > 0.5) == (g.result == 1))
                    proj_brier[pw].append((p - g.result) ** 2)
            feat = build_features(past, knobs.recent_weeks)
            for wt in ytd_weights:
                power_scores(feat, wt)
                for g in now:
                    power_hits[wt].append((feat[g.team_id].power > feat[g.opp_id].power) == (g.result == 1))

    def summary(hits, briers=None):
        return {
            k: {"accuracy": fmean(v) if v else None, "brier": fmean(briers[k]) if briers and v else None, "games": len(v)}
            for k, v in hits.items()
        }

    return {
        "knobs": knobs,
        "half_life": summary(strength_hits, strength_brier),
        "proj_weight": summary(proj_hits, proj_brier),
        "ytd_weight": summary(power_hits),
    }
