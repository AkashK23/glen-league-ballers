// Typed access to the JSON produced by `python -m league_core build`.
import leagueJson from "../data/league.json";
import recordsJson from "../data/records.json";
import rivalriesJson from "../data/rivalries.json";
import h2hJson from "../data/h2h.json";
import seasonsJson from "../data/seasons.json";

export interface TeamRow {
  owner: string;
  team_name: string;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  seed: number | null;
  final_rank: number | null;
  division: string | null;
  logo_url: string | null;
}

export interface Side {
  owner: string;
  team_name: string;
  score: number;
}

export interface MatchupRow {
  week: number;
  weeks: number;
  kind: "regular" | "playoff" | "consolation";
  completed: boolean;
  home: Side;
  away: Side | null;
}

export interface PickRow {
  round: number;
  pick: number;
  owner: string;
  player: string;
  bid_amount: number | null;
  keeper: boolean;
}

export interface SeasonData {
  year: number;
  league_name: string;
  complete: boolean;
  champion: string | null;
  runner_up: string | null;
  last_place: string | null;
  regular_season_weeks: number;
  playoff_team_count: number;
  standings: TeamRow[];
  matchups: MatchupRow[];
  draft: PickRow[];
}

export interface Rivalry {
  owners: [string, string];
  championships: [number, number];
  wins: [number, number];
  ties: number;
  points: [number, number];
  frozen_after: number | null;
  note: string | null;
}

export interface H2HRow {
  owner_a: string;
  owner_b: string;
  wins_a: number;
  wins_b: number;
  ties: number;
  points_a: number;
  points_b: number;
  playoff_games: number;
}

export const league = leagueJson as {
  name: string;
  tagline: string;
  first_year: number;
  latest_year: number;
  owners: string[];
};
export const records = recordsJson as Record<string, Record<string, any[]>>;
export const rivalries = rivalriesJson as Rivalry[];
export const h2h = h2hJson as H2HRow[];
export const seasons = (seasonsJson as SeasonData[]).slice().sort((a, b) => b.year - a.year);
export const completedSeasons = seasons.filter((s) => s.complete);
export const currentSeason = seasons.find((s) => !s.complete) ?? null;

// ---------- helpers ----------

export const url = (path: string) => `${import.meta.env.BASE_URL.replace(/\/$/, "")}${path}`;

export const slug = (owner: string) => owner.toLowerCase().replace(/[^a-z0-9]+/g, "-");

export const pts = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const pct = (n: number) => n.toFixed(3).replace(/^0/, "");

export const record = (w: number, l: number, t = 0) => (t ? `${w}-${l}-${t}` : `${w}-${l}`);

export const ordinal = (n: number) => {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
};

/** Head-to-head from `owner`'s point of view against `opponent`. */
export function versus(owner: string, opponent: string) {
  const row = h2h.find(
    (r) => (r.owner_a === owner && r.owner_b === opponent) || (r.owner_a === opponent && r.owner_b === owner),
  );
  if (!row) return null;
  const mine = row.owner_a === owner;
  return {
    wins: mine ? row.wins_a : row.wins_b,
    losses: mine ? row.wins_b : row.wins_a,
    ties: row.ties,
    points_for: mine ? row.points_a : row.points_b,
    points_against: mine ? row.points_b : row.points_a,
    playoff_games: row.playoff_games,
  };
}

/** Labels for ESPN-style playoff rounds, counting back from the final. */
export function playoffRoundName(week: number, playoffWeeks: number[]) {
  const fromEnd = playoffWeeks.length - 1 - playoffWeeks.indexOf(week);
  return ["Championship", "Semifinals", "Quarterfinals", "Wild Card"][fromEnd] ?? `Round ${week}`;
}

// Optional hand-written season notes: web/src/content/seasons/<year>.md
const notes = import.meta.glob<{ frontmatter: Record<string, any>; Content: any }>(
  "../content/seasons/*.md",
  { eager: true },
);
export function seasonNotes(year: number) {
  return notes[`../content/seasons/${year}.md`] ?? null;
}
