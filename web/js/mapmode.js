/* The 2026 results on the map, in one of three modes: a candidate's share
 * of the votes across the areas of their contest, who got the most votes
 * where in a contest, or a turnout (of the municipal or the regional
 * elections across the country, or of one contest). The map colours the
 * land in STEPS intensities of a colour (draw.js `setResults`) on a scale
 * fitted to the values shown, or for a winner map in a colour per leading
 * candidate (a tie for the lead in stripes of the leaders' colours). A
 * legend with the scale or the candidates and a close button floats on the
 * map.
 *
 * The mode is one for the page, chosen in a candidate's row
 * (`MapButton`), a contest's header (`TurnoutMapButton`,
 * `WinnerMapButton`), the candidate card or the boundaries menu
 * (controls.js), so it lives here rather than being passed down through
 * the panes. The values come from the live results (live.js) and follow
 * them:
 * - a contest: its `areas` (an obec or city district each, or on election
 *   night a regional obvod `obvod:<n>` of the kraj), else its own figures
 *   over its own area (a mayor's obec, a council's obec or council obvod,
 *   a regional obvod, a kraj's obvody);
 * - the municipal turnout: the mayoral (else council) contests of every
 *   municipality and city district;
 * - Bratislava's and Košice's own elections: likewise from theirs;
 * - the regional turnout: each kraj's presidential contest.
 *
 * The units follow the zoom, as the boundary overlays do (draw.js
 * `OVERLAYS`), each as fine as its figures go:
 * - below the obce's zoom, the regional obvody, each its obce summed
 *   (unless the contest is of one obec, which would colour a whole obvod);
 * - from there, every obec by its own figure;
 * - from the council overlay's zoom, the council obvody of the obce split
 *   into several (a council's own figure, any other contest's okrsky
 *   summed, live.js `okrsokCouncils`);
 * - from the okrsky overlay's zoom, every okrsok drawn (geo/index.json
 *   `okrsky.drawn`) with figures of its own in the final results (live.js
 *   `okrsky`).
 * An obec without finer figures keeps its own at every zoom. One scale
 * spans the units of every level, so that a colour means the same at each
 * zoom. Pointing at the map (on a touch screen, tapping it) names the unit
 * there with its figures; in the municipal elections an okrsok also with
 * its 2022 municipal turnout where it is the same okrsok as then. */

import { html, render, useEffect, useLayoutEffect, useMemo, useRef, useState } from '../vendor/preact-htm.module.js';
import {
  areaName,
  contestArea,
  contestOf,
  contests,
  dataIndex,
  displayName,
  getJSON,
  hasCouncilObvody,
  isCity,
  useLoaded,
} from './data.js';
import { formatList, formatNumber, formatPercent, t } from './i18n.js';
import { ArrowIcon, CloseIcon, ExpandIcon, MapResultsIcon, TurnoutIcon } from './icons.js';
import { addRecord, isSingle, NOT_COUNTED, okrsokCouncils, useLive } from './live.js';

/* The intensities of the colour: app.css `--map-result-<n>` for a
 * candidate's votes, a turnout's tone mixed into the land (draw.js
 * `TONE_STEPS`, app.css `.map-legend.toned`). */
export const STEPS = 6;
/* The colours of a winner map, app.css `--map-series-<n>`: one for each of
 * the candidates with the most votes overall, the rest share
 * `--map-series-other`. */
export const SERIES = 8;
const PALETTE = [...Array.from({ length: SERIES }, (_, i) => `series-${i + 1}`), 'series-other'];
// Values beyond these quantiles (where there are enough to tell) take the
// end steps, so that a hamlet of a dozen voters does not stretch the scale.
const TRIM = 0.05;
const TRIM_FROM = 20;

/* What the map shows, one of:
 * - null;
 * - {kind: 'candidate', id, contest, number, name, surname, label, multi}:
 *   a candidacy, its contest's id and label, `multi` for a council;
 * - {kind: 'winner', contest, label, names, multi}: who got the most votes
 *   where, `names` number → [name, surname], `multi` for a council, whose
 *   top candidate is not all it elects;
 * - {kind: 'turnout', election: 'municipal' | 'city' | 'regional'}, 'city'
 *   for Bratislava's and Košice's own elections;
 * - {kind: 'turnout', contest, label}: one contest's (TurnoutMapButton).
 * A contest's mode from a link has `keepView` too (`parseMode`). */
let mode = null;
const listeners = new Set();

/* Shows *next* (a mode, or null) on the map. */
export function setMapMode(next) {
  mode = next;
  for (const listener of listeners) listener();
}

/* The mode, for a component: renders it again when it changes. */
export function useMapMode() {
  const [, setTick] = useState(0);
  useEffect(() => {
    const listener = () => setTick((n) => n + 1);
    listeners.add(listener);
    return () => listeners.delete(listener);
  }, []);
  return mode;
}

/* A button that shows mode *next* on the map, or takes it off while it is
 * shown (*on*). */
function ToggleButton({ cls, next, on, label, style, children }) {
  return html`<button
    type="button"
    class=${cls}
    style=${style}
    aria-pressed=${on ? 'true' : 'false'}
    title=${label}
    aria-label=${label}
    onClick=${() => setMapMode(on ? null : next)}
  >
    ${children}
  </button>`;
}

/* The modes of a contest's results (see `mode`): candidate *c*'s votes,
 * *label* naming the contest; who got the most votes where; its turnout. */
const candidateMode = (c, label) => ({
  kind: 'candidate',
  id: c.id,
  contest: c.contest,
  number: c.number,
  name: displayName(c),
  surname: c.surname,
  label,
  multi: !isSingle(c.contest),
});

const winnerMode = (contest) => ({
  kind: 'winner',
  contest: contest.id,
  label: contest.label,
  names: Object.fromEntries(contest.candidates.map((c) => [c.number, [displayName(c), c.surname]])),
  multi: !isSingle(contest.id),
});

const turnoutMode = (contest) => ({ kind: 'turnout', contest: contest.id, label: contest.label });

const ELECTIONS = ['municipal', 'city', 'regional'];

/* Mode *m* as a link names it (app.js `mr`): 'candidate:<candidacy>',
 * 'winner:<contest>', 'turnout:<contest>' or 'turnout:<election>'; null
 * for none. */
export function formatMode(m) {
  if (!m) return null;
  if (m.kind === 'candidate') return `candidate:${m.id}`;
  return `${m.kind}:${m.contest ?? m.election}`;
}

/* The mode a link names (`formatMode`), with *keepView*: the link names
 * the view as well, which fitting the map to the contest's area would
 * undo (`MapResults`). Null for none, or for what is not known (a link
 * made by hand, a contest gone). */
export async function parseMode(value, keepView) {
  const at = value?.indexOf(':') ?? -1;
  if (at < 0) return null;
  const kind = value.slice(0, at);
  const id = value.slice(at + 1);
  if (kind === 'turnout' && ELECTIONS.includes(id)) return { kind, election: id };
  const make = {
    candidate: (contest) => {
      const c = contest.candidates.find((x) => x.id === id);
      return c && candidateMode(c, contest.label);
    },
    winner: winnerMode,
    turnout: turnoutMode,
  }[kind];
  if (!make) return null;
  const [contest] = await contests([kind === 'candidate' ? contestOf(id) : id]).catch(() => []);
  const m = contest?.candidates.length ? make(contest) : null;
  return m ? { ...m, keepView } : null;
}

/* The button that shows counted candidate *c*'s votes on the map, across
 * the areas of their contest where it has several, else over its one
 * area; *label* names the contest. At the end of the candidate's row
 * (ballots.js) and by the origins of their votes (candidate.js). */
export function MapButton({ candidate: c, label }) {
  const current = useMapMode();
  const on = current?.kind === 'candidate' && current.id === c.id;
  const next = candidateMode(c, label);
  return html`<${ToggleButton}
    cls="votes-map"
    next=${next}
    on=${on}
    label=${t(on ? 'mapmode.candidate_hide' : 'mapmode.candidate_show')}
  >
    <${MapResultsIcon} />
  <//>`;
}

/* The colour the map shows mode *m* in (draw.js `setResults`): a
 * candidate's votes in the results' green, like the medal; a turnout in
 * the colour its area is drawn in otherwise (app.css `--map-<tone>`), so
 * that nothing changes colour unexpectedly: a municipality's red, a
 * council obvod's orange, Bratislava's and Košice's green, a regional
 * contest's violet. The municipal turnout across the country is the
 * municipalities' colour, the two cities' own elections theirs. A winner
 * map has a colour per candidate instead: null. */
export function toneOf(m, index) {
  if (m.kind === 'candidate') return 'result';
  if (m.kind === 'winner') return null;
  if (!m.contest) return { municipal: 'accent', city: 'city', regional: 'zsk' }[m.election];
  const [kind, area] = m.contest.split(':');
  const code = area.split('/')[0];
  if (kind === 'predseda' || kind === 'zsk') return 'zsk';
  if (isCity(code)) return 'city';
  return kind === 'oz' && index && hasCouncilObvody(index, code) ? 'council' : 'accent';
}

/* The 2026 turnout at the end of a counted contest's header (ballots.js
 * `Turnout`, its meter the *children*) as the button that colours the
 * contest's area by it on the map, in the area's own colour (`toneOf`), and
 * takes that off again: the ballot box of the turnout's menu (controls.js)
 * beside the figure it puts on the map. *figures*: the turnout in words,
 * for the tooltip. */
export function TurnoutMapButton({ contest, figures, children }) {
  const current = useMapMode();
  const [index] = useLoaded(dataIndex, []);
  const on = current?.kind === 'turnout' && current.contest === contest.id;
  const next = turnoutMode(contest);
  const action = t(on ? 'mapmode.contest_turnout_hide' : 'mapmode.contest_turnout_show');
  return html`<${ToggleButton}
    cls="map-chip turnout-map"
    style=${{ '--tone': `var(--map-${toneOf(next, index)})` }}
    next=${next}
    on=${on}
    label=${`${action}\n${figures}`}
  >
    <${TurnoutIcon} />
    ${children}
  <//>`;
}

/* The button before the turnout of a contest's header (ballots.js
 * `Contest`) once its candidates' votes are counted: it colours each unit
 * of the contest's area (as `MapResults` has them at the zoom) by the
 * candidate with the most votes there. In a council that is its top
 * candidate there, not all it elects, as the legend says. */
export function WinnerMapButton({ contest }) {
  const current = useMapMode();
  const on = current?.kind === 'winner' && current.contest === contest.id;
  const next = winnerMode(contest);
  return html`<${ToggleButton}
    cls="map-chip winner-map"
    next=${next}
    on=${on}
    label=${t(on ? 'mapmode.winner_hide' : 'mapmode.winner_show')}
  >
    <${MapResultsIcon} />
  <//>`;
}

/* The names of the area files (data.js `areaName`) that hold the figures
 * of mode *m*: the contest's, or all of the election's that the live
 * results list. */
function areaFiles(m, live, index) {
  if (m.contest) return [areaName(m.contest, index)];
  const prefix = { municipal: 'okres/', city: 'city/', regional: 'kraj/' }[m.election];
  return Object.keys(live.status?.files ?? {}).filter((name) => name.startsWith(prefix));
}

/* Whether obec *code* (data/index.json row *row*) is in the area of mode
 * *m*. */
function inArea(m, code, row) {
  if (!m.contest) return m.election !== 'city' || row[5] !== undefined;
  const [kind, area] = m.contest.split(':');
  const [c, n] = area.split('/');
  if (kind === 'predseda') return row[2] === c;
  if (kind === 'zsk') return row[2] === c && row[3] === Number(n);
  if (isCity(c)) return row[5] === c && (kind !== 'oz' || row[6] === Number(n));
  return code === c;
}

/* The municipal area files whose okrsky group those of mode *m* by council
 * obvod (live.js `okrsokCouncils`): those of the okresy of the obce in its
 * area that are split into several council obvody. */
function councilFiles(m, index) {
  const names = new Set();
  for (const [code, row] of Object.entries(index.obce)) {
    if (row[1] && hasCouncilObvody(index, code) && inArea(m, code, row)) names.add(`okres/${row[1]}`);
  }
  return [...names];
}

/* What the figures of *m* come from, as live.js has it now:
 * - main: the contest's entry, or the contests of each of area files
 *   *names* that has loaded;
 * - okrsky: the figures by okrsok of those;
 * - councils: those of area files *councilNames* (`councilFiles`).
 * Each list holds only what exists and has loaded. Their identities
 * change exactly when the figures may. */
function sourcesOf(m, live, names, councilNames) {
  const main = m.contest
    ? [live.of(m.contest)].filter((entry) => entry && entry !== NOT_COUNTED)
    : names.map((name) => live.contests(name)).filter(Boolean);
  const byOkrsok = (list) => list.map((name) => live.okrsky(name)).filter(Boolean);
  return { main, okrsky: byOkrsok(names), councils: byOkrsok(councilNames) };
}

/* The leaders of an area's *votes* ({number: votes}) of *valid*: [their
 * votes (each), valid, their numbers in the order *order* (a compare
 * function), votes], several on a tie for the lead, which a winner map
 * stripes in all their colours rather than leave the area blank as if it
 * had no votes; null without votes. */
function leader(votes, valid, order) {
  let best = 0;
  let numbers = [];
  for (const [n, v] of Object.entries(votes)) {
    if (v > best) {
      best = v;
      numbers = [Number(n)];
    } else if (v === best && v > 0) numbers.push(Number(n));
  }
  return numbers.length ? [best, valid, numbers.sort(order), votes] : null;
}

// An area's [eligible, voters, …] as a turnout figure, [voters, eligible].
const turnoutOf = ([eligible, voters]) => (eligible && voters != null ? [voters, eligible] : null);

// A contest's live entry (docs/results.md) as an area's record, [eligible,
// voters, valid, {number: votes}].
const recordOf = (e) => [
  e.eligible ?? null,
  e.voters ?? null,
  e.valid ?? null,
  Object.fromEntries((e.candidates ?? []).map(([n, v]) => [n, v])),
];

/* The records [eligible, voters, valid, {number: votes}] of a mode's units
 * as they are gathered from the live results, before `figures` turns them
 * into figures. A unit known only by its parts gets their records summed. */
class Records {
  constructor(index, drawn, councilFiles) {
    this.index = index;
    this.drawn = drawn;
    // Okrsok → its council obvod, of all the files: one lookup per okrsok
    // rather than one per file.
    this.councilOf = new Map();
    for (const file of councilFiles) {
      for (const [key, council] of okrsokCouncils(file, index)) this.councilOf.set(key, council);
    }
    // Obec code → record.
    this.obce = new Map();
    // Regional obvod '<kraj>/<n>' known only as a whole → record.
    this.whole = new Map();
    // Council obvod '<obec>/<k>' → its own record.
    this.councils = new Map();
    // Drawn okrsok '<obec>/<n>' → record, and its 2022 municipal turnout.
    this.okrsky = new Map();
    this.past = new Map();
    // All okrsky summed by council obvod and by obec.
    this.councilSums = new Map();
    this.obecSums = new Map();
    // The cities (BA, KE) whose districts' figures are the `areas` of their
    // contest: a district missing from them is one whose votes are not
    // known (okrsky not told apart), which its known okrsky would belie.
    this.byAreas = new Set();
    this.totals = new Map();
    // Whether the contest is of one obec; whether of one council obvod of
    // an obec split into several; a winner map's candidates by votes.
    this.local = false;
    this.piece = false;
    this.ranking = [];
  }

  addTotal(rec) {
    addRecord(this.totals, 0, rec);
  }

  /* An area of the live results: an obec, or `obvod:<n>` of *kraj*. */
  put(key, kraj, rec) {
    if (key.startsWith('obvod:')) this.whole.set(`${kraj}/${key.slice('obvod:'.length)}`, rec);
    else if (this.index.obce[key]) this.obce.set(key, rec);
  }

  /* Every regional obvod of *kraj* as a whole. */
  wholeKraj(kraj, rec) {
    for (const [, , k, n] of Object.values(this.index.obce)) if (k === kraj) this.whole.set(`${kraj}/${n}`, rec);
  }

  /* The okrsky among *records* ('<obec>/<n>' → record): each drawn one a
   * unit of its own, with its 2022 municipal turnout from *file* if
   * *withPast*; all of them summed by council obvod and by obec. (An
   * okrsok without an area, addressless, is not drawn.) */
  addOkrsky(records, file, withPast) {
    for (const [key, rec] of Object.entries(records ?? {})) {
      if (this.drawn.keys.has(key)) {
        this.okrsky.set(key, rec);
        if (withPast && file.past?.[key]) this.past.set(key, file.past[key]);
      }
      const council = this.councilOf.get(key);
      if (council) addRecord(this.councilSums, council, rec);
      addRecord(this.obecSums, key.split('/')[0], rec);
    }
  }
}

/* One contest's records (mode *m* with a `contest`): its `areas`, else its
 * own figures over its own area; and its okrsky. */
function gatherContest(rs, m, sources) {
  const { index } = rs;
  const [entry] = sources.main;
  const [kind, area] = m.contest.split(':');
  const code = area.split('/')[0];
  const city = isCity(code);
  const areas = Object.entries(entry?.areas ?? {});
  for (const [key, rec] of areas) rs.put(key, code, rec);
  if (city && entry?.areas) rs.byAreas.add(code);
  const total = entry ? recordOf(entry) : null;
  if (total) rs.addTotal(total);
  if (m.kind === 'winner') rs.ranking = [...(entry?.candidates ?? [])].sort((a, b) => b[1] - a[1]).map(([n]) => n);
  rs.local = (kind === 'starosta' || kind === 'oz') && !city && Boolean(index.obce[code]);
  // A council of one obvod of an obec split into several: the obvod is its
  // whole area, and the obec as a whole has no figure of it.
  rs.piece = rs.local && kind === 'oz' && hasCouncilObvody(index, code);
  // Without areas, the contest's own area. A city contest's is its
  // districts (a city council obvod's, those in it), which are obce; the
  // city is not.
  if (!areas.length && total) {
    if (kind === 'predseda') rs.wholeKraj(code, total);
    else if (kind === 'zsk') rs.whole.set(area, total);
    else if (city) {
      const obvod = kind === 'oz' ? Number(area.split('/')[1]) : null;
      for (const [k, row] of Object.entries(index.obce)) {
        if (row[5] === code && (obvod === null || row[6] === obvod)) rs.obce.set(k, total);
      }
    } else if (rs.piece) rs.councils.set(area, total);
    else if (rs.local) rs.obce.set(code, total);
  }
  // `past` is of the 2022 municipal elections: a municipal contest's.
  const withPast = m.kind === 'turnout' && (kind === 'starosta' || kind === 'oz');
  for (const file of sources.okrsky) rs.addOkrsky(file.contests[m.contest], file, withPast);
}

/* The municipal turnout (mode *m*, election 'municipal' or 'city'). A
 * municipality's turnout is its mayor's contest's; where that has none (a
 * contest not held, or without its figures yet), its council obvody's
 * summed; a council obvod's is its council's. Bratislava's and Košice's
 * districts are municipalities here, electing their own. The two cities'
 * own elections (a city mayor and council over all their districts) are
 * on ballots of their own, so a layer of their own ('city', from the city
 * files): by district where the mayor's contest has `areas`, else the
 * whole city alike. Their okrsky likewise. */
function gatherMunicipal(rs, m, sources) {
  const { index } = rs;
  const mayors = new Map();
  const councilTurnouts = new Map();
  for (const contests of sources.main) {
    for (const [id, e] of Object.entries(contests)) {
      if (!e.eligible || e.voters == null) continue;
      const [kind, area] = id.split(':');
      const code = area.split('/')[0];
      if (!index.obce[code]) continue;
      if (kind === 'starosta') mayors.set(code, e);
      else if (kind === 'oz') {
        addRecord(councilTurnouts, code, recordOf(e));
        if (m.election === 'municipal' && hasCouncilObvody(index, code)) rs.councils.set(area, recordOf(e));
      }
    }
  }
  const turnouts = new Map(councilTurnouts);
  for (const [code, e] of mayors) turnouts.set(code, recordOf(e));
  for (const [code, rec] of turnouts) {
    rs.addTotal(rec);
    const areas = Object.entries(mayors.get(code)?.areas ?? {});
    if (m.election === 'municipal') rs.obce.set(code, rec);
    else if (areas.length) {
      rs.byAreas.add(code);
      for (const [key, a] of areas) rs.put(key, null, a);
    } else {
      for (const [k, row] of Object.entries(index.obce)) if (row[5] === code) rs.obce.set(k, rec);
    }
  }
  for (const file of sources.okrsky) {
    // The mayor's okrsky, else the council obvody's: each okrsok is in one
    // of them.
    const contests = Object.entries(file.contests);
    const withMayor = new Set(contests.filter(([id]) => id.startsWith('starosta:')).map(([id]) => id.split(':')[1]));
    for (const [id, records] of contests) {
      const [kind, area] = id.split(':');
      if (kind === 'starosta' || (kind === 'oz' && !withMayor.has(area.split('/')[0]))) rs.addOkrsky(records, file, true);
    }
  }
}

/* The regional turnout: each kraj's presidential contest. */
function gatherRegional(rs, sources) {
  for (const contests of sources.main) {
    const [id, e] = Object.entries(contests).find(([key]) => key.startsWith('predseda:')) ?? [];
    if (!e?.eligible || e.voters == null) continue;
    const kraj = id.slice('predseda:'.length);
    rs.addTotal(recordOf(e));
    const areas = Object.entries(e.areas ?? {});
    for (const [key, a] of areas) rs.put(key, kraj, a);
    // Without areas, the kraj as a whole: each of its obvody.
    if (!areas.length) rs.wholeKraj(kraj, recordOf(e));
  }
  for (const file of sources.okrsky) {
    for (const [id, records] of Object.entries(file.contests)) {
      if (id.startsWith('predseda:')) rs.addOkrsky(records, file, false);
    }
  }
}

/* The figures of mode *m* from *sources* (`sourcesOf`) by unit, each
 * [part, whole]: [votes, valid] of a candidate, [voters, eligible] of a
 * turnout, [the leader's votes, valid, the leaders' numbers (several on a
 * tie), votes] of a winner map (`leader`):
 * - obce: by obec code;
 * - councils: by council obvod '<obec>/<k>' of an obec split into several;
 * - okrsky: by okrsok '<obec>/<n>' of those drawn (*drawn* `keys`,
 *   `useDrawnOkrsky`), with `past` an okrsok's 2022 municipal turnout as
 *   [voters, eligible];
 * - regional: by regional obvod '<kraj>/<n>', its obce summed, or as a
 *   whole where only that is known (those in the Set `whole`);
 * - total: of all counted, null if unknown;
 * - local: whether the contest is of one obec;
 * - ranking: a winner map's candidates' numbers, most votes first. */
function figures(m, sources, index, drawn) {
  const rs = new Records(index, drawn, sources.councils);
  if (m.contest) gatherContest(rs, m, sources);
  else if (m.election === 'municipal' || m.election === 'city') gatherMunicipal(rs, m, sources);
  else gatherRegional(rs, sources);

  for (const [key, rec] of rs.councilSums) if (!rs.councils.has(key)) rs.councils.set(key, rec);
  // An obec without a figure of its own: its okrsky summed; but not the
  // obec of a council obvod's contest, whose okrsky are only the obvod's.
  if (!rs.piece) {
    for (const [code, rec] of rs.obecSums) {
      if (!rs.obce.has(code) && index.obce[code] && !rs.byAreas.has(index.obce[code][5])) rs.obce.set(code, rec);
    }
  }
  const regional = new Map();
  if (!rs.local) {
    for (const [code, rec] of rs.obce) {
      const [, , kraj, zsk] = index.obce[code];
      addRecord(regional, `${kraj}/${zsk}`, rec);
    }
  }
  for (const [key, rec] of rs.whole) regional.set(key, rec);
  // A tie's leaders in the order of their colours (`presentWinner`).
  const place = new Map(rs.ranking.map((n, i) => [n, i]));
  const byPlace = (a, b) => (place.get(a) ?? place.size) - (place.get(b) ?? place.size) || a - b;
  const of = {
    candidate: ([, , valid, votes]) => (valid ? [votes[m.number] ?? 0, valid] : null),
    winner: ([, , valid, votes]) => (valid ? leader(votes, valid, byPlace) : null),
    turnout: turnoutOf,
  }[m.kind];
  const figs = (records, as = of) => {
    const out = new Map();
    for (const [key, rec] of records) {
      const fig = as(rec);
      if (fig) out.set(key, fig);
    }
    return out;
  };
  const total = rs.totals.get(0);
  return {
    obce: figs(rs.obce),
    councils: figs(rs.councils),
    okrsky: figs(rs.okrsky),
    regional: figs(regional),
    whole: new Set(rs.whole.keys()),
    past: figs(rs.past, turnoutOf),
    total: total ? of(total) : null,
    local: rs.local,
    ranking: rs.ranking,
  };
}

/* The figures of every unit of *figs* (`figures`), at every level: one
 * scale spans them all, so that a colour means the same at each zoom. */
const allFigures = (figs) => [
  ...figs.okrsky.values(),
  ...figs.councils.values(),
  ...figs.obce.values(),
  ...figs.regional.values(),
];

/* The figures of *figs* (`figures`) of the finest units: the okrsky, the
 * council obvody of the obce without those, the other obce, and the
 * regional obvody known only as a whole. */
function finestFigures(figs) {
  const obecOf = (key) => key.split('/')[0];
  const byOkrsky = new Set([...figs.okrsky.keys()].map(obecOf));
  const byCouncils = new Set([...figs.councils.keys()].map(obecOf));
  return [
    ...figs.okrsky.values(),
    ...[...figs.councils].filter(([key]) => !byOkrsky.has(obecOf(key))).map(([, fig]) => fig),
    ...[...figs.obce].filter(([key]) => !byOkrsky.has(key) && !byCouncils.has(key)).map(([, fig]) => fig),
    ...[...figs.regional].filter(([key]) => figs.whole.has(key)).map(([, fig]) => fig),
  ];
}

/* The cells draw.js `setResults` takes of *figs* (`figures`), each unit's
 * *cell(fig)*; a regional obvod known only as a whole marked so. */
function cellsOf(figs, cell) {
  const cells = (map) => Object.fromEntries([...map].map(([key, fig]) => [key, cell(fig)]));
  const zsk = cells(figs.regional);
  for (const key of figs.whole) zsk[key]?.push(1);
  return { obce: cells(figs.obce), zsk, councils: cells(figs.councils), okrsky: cells(figs.okrsky) };
}

/* What the map and the legend show of *figs* (`figures`); null with no
 * values:
 * - shown: as draw.js `setResults` takes it;
 * - scale: [low, high], the shares of the lowest and the highest step;
 * - below, above: whether values lie beyond them;
 * - digits: of the percentages.
 * The scale spans the values of the units of every level (`allFigures`),
 * not from zero: areas not counted yet have no value and stay uncoloured,
 * so they do not widen it. */
function present(figs) {
  const share = ([part, all]) => part / all;
  const values = allFigures(figs)
    .map(share)
    .sort((a, b) => a - b);
  if (!values.length) return null;
  const trim = values.length >= TRIM_FROM ? TRIM : 0;
  const quantile = (q) => values[Math.min(values.length - 1, Math.floor(q * values.length))];
  // Whole percentage points, so that the ends read plainly.
  let low = Math.floor(quantile(trim) * 100 + 1e-9) / 100;
  let high = Math.ceil(quantile(1 - trim) * 100 - 1e-9) / 100;
  if (high <= low) {
    if (low >= 1) low = 0.99;
    else high = low + 0.01;
  }
  const digits = high < 0.1 ? 1 : 0;
  // All values alike (a single area, say): nothing to tell apart, so the
  // strongest step, for the area to show.
  const alike = values[0] === values.at(-1);
  const step = (v) =>
    alike ? STEPS - 1 : Math.min(STEPS - 1, Math.max(0, Math.floor(((v - low) / (high - low)) * STEPS)));
  return {
    shown: { steps: STEPS, ...cellsOf(figs, (fig) => [step(share(fig)), formatPercent(share(fig), digits)]) },
    scale: [low, high],
    below: values[0] < low,
    above: values.at(-1) > high,
    digits,
  };
}

/* The names of the candidates *numbers* of winner map *m*: their full
 * names (*which* 0) or their surnames (1), or their numbers where unknown. */
const namesOf = (m, numbers, which) => numbers.map((n) => m.names[n]?.[which] ?? String(n));

// Those tied for the lead by surname, in the order of their stripes: a
// label on the map, where a list in words would rarely fit.
const surnames = (m, numbers) => namesOf(m, numbers, 1).join(' / ');

/* The same for a winner map (mode *m*): each unit in the colour of its
 * leader (`PALETTE`, by the candidates' votes overall) with the leader's
 * surname; a tie for the lead in stripes of the leaders' colours (a
 * palette entry of several, draw.js `stepFill`) with their surnames. The
 * legend's:
 * - leaders: [number, units led, colour, of those tied] of every candidate
 *   who leads one of the finest units (`finestFigures`), in the order of
 *   the colours; a tie counts for each of those tied, whose colours its
 *   stripes are;
 * - tie: {count, colours} where the map has stripes: the finest units
 *   tied, and the colours striped anywhere, else null.
 * Null with no values. */
function presentWinner(figs, m) {
  if (!allFigures(figs).length) return null;
  const colour = new Map(figs.ranking.map((n, i) => [n, Math.min(i, SERIES)]));
  const colourOf = (n) => colour.get(n) ?? SERIES;
  // A tie's palette entry by its colours, once each (those beyond SERIES
  // share one), in order as its leaders are; and all the colours striped.
  const palette = [...PALETTE];
  const striped = new Map();
  const stripedColours = new Set();
  const step = (numbers) => {
    const colours = [...new Set(numbers.map(colourOf))];
    if (colours.length === 1) return colours[0];
    const key = colours.join();
    if (!striped.has(key)) {
      striped.set(key, palette.length);
      palette.push(colours.map((c) => PALETTE[c]));
      for (const c of colours) stripedColours.add(c);
    }
    return striped.get(key);
  };
  const cells = cellsOf(figs, (fig) => [step(fig[2]), surnames(m, fig[2])]);
  const led = new Map();
  const tiedIn = new Map();
  let tied = 0;
  for (const [, , numbers] of finestFigures(figs)) {
    for (const n of numbers) led.set(n, (led.get(n) ?? 0) + 1);
    if (numbers.length === 1) continue;
    tied++;
    for (const n of numbers) tiedIn.set(n, (tiedIn.get(n) ?? 0) + 1);
  }
  const leaders = [...led]
    .map(([n, count]) => [n, count, colourOf(n), tiedIn.get(n) ?? 0])
    .sort((a, b) => a[2] - b[2] || b[1] - a[1]);
  return {
    shown: { steps: palette.length, palette, ...cells },
    leaders,
    tie: stripedColours.size ? { count: tied, colours: [...stripedColours].sort((a, b) => a - b) } : null,
    digits: 0,
  };
}

/* The kinds of unit that *figs* (`figures`) have figures of, coarsest
 * first, as the legend names them. */
const levelsOf = (figs) =>
  [
    ['zsk', figs.regional],
    ['obce', figs.obce],
    ['councils', figs.councils],
    ['okrsky', figs.okrsky],
  ]
    .filter(([, units]) => units.size)
    .map(([level]) => t(`mapmode.level_${level}`));

/* The tooltip's lines for the unit at the pointer, *hit* {kind, key}
 * (draw.js `unitAt`: the unit whose fill is drawn there), by figures *figs*
 * (`figures`) of mode *m*: the unit's name, its figures, and an okrsok's
 * 2022 turnout where known; null where it has none. */
function tipLines(hit, figs, m, index) {
  const { kind, key } = hit;
  const fig = (kind === 'zsk' ? figs.regional : figs[kind]).get(key);
  if (!fig) return null;
  const [code, n] = key.split('/');
  const name = index.obce[code]?.[0];
  const unit = {
    okrsky: () => t('mapmode.tip_okrsok', { n, name }),
    councils: () => t('mapmode.tip_obvod', { n, name }),
    obce: () => name,
    zsk: () => t('mapmode.tip_zsk', { n, kraj: index.kraje[code] }),
  }[kind]();
  const share = formatPercent(fig[0] / fig[1]);
  let value;
  if (m.kind === 'candidate') {
    value = t('mapmode.tip_votes', { share, votes: formatNumber(fig[0]), valid: formatNumber(fig[1]) });
  } else if (m.kind === 'winner') {
    value = leadText(m, fig[2], share, 'mapmode.tip_winner', 'mapmode.tip_tie');
  } else {
    value = t('mapmode.tip_turnout', { turnout: share, voters: formatNumber(fig[0]), eligible: formatNumber(fig[1]) });
  }
  const past = kind === 'okrsky' ? figs.past.get(key) : null;
  const then = past
    ? t('mapmode.tip_past', {
        turnout: formatPercent(past[0] / past[1]),
        voters: formatNumber(past[0]),
        eligible: formatNumber(past[1]),
      })
    : null;
  return [unit, value, then].filter(Boolean);
}

/* What winner map *m* says of the leaders *numbers* (a figure's, `leader`)
 * with *share* each: by message *one* the leader's full name, or by *tie*
 * those tied for the lead in a list. */
const leadText = (m, numbers, share, one, tie) =>
  numbers.length === 1
    ? t(one, { name: namesOf(m, numbers, 0)[0], share })
    : t(tie, { names: formatList(namesOf(m, numbers, 0)), share });

/* *lines* (`tipLines`) as a tooltip's or a card's content: the unit's name
 * in bold, then its figures. */
const tipContent = (lines) =>
  lines.map((line, i) => (i ? html`<span key=${i}>${line}</span>` : html`<strong key=${i}>${line}</strong>`));

// Pixels of each colour across a legend's stripes.
const SWATCH_STRIPE = 3;

/* The style of a legend's swatch of *colours* (indexes of PALETTE): one
 * plain, several in stripes as the map draws a tie (draw.js `stepFill`). */
function swatchStyle(colours) {
  const vars = colours.map((c) => `var(--map-${PALETTE[c]})`);
  if (vars.length === 1) return { background: vars[0] };
  const stops = vars.map((v, i) => `${v} ${i * SWATCH_STRIPE}px ${(i + 1) * SWATCH_STRIPE}px`);
  return { background: `repeating-linear-gradient(45deg, ${stops.join(', ')})` };
}

// The title of a winner map's *count* of units led, *ties* of them tied.
const ledTitle = (count, ties) =>
  ties
    ? t('mapmode.winner_count_ties', { n: formatNumber(count), ties: formatNumber(ties) })
    : t('mapmode.winner_count', { n: formatNumber(count) });

// The title of the finest units tied, *tie* as `presentWinner` has it.
const tieTitle = (tie) => (tie.count ? t('mapmode.tie_count', { n: formatNumber(tie.count) }) : undefined);

/* The candidates of a winner map who lead somewhere, each in their colour,
 * with how many of the units shown they lead (ties included, as their
 * colour is in the stripes); then, where any unit is striped, the stripes
 * of a tie (`presentWinner` *tie*) with the finest units tied. */
function Leaders({ m, leaders, tie }) {
  return html`<ul class="map-legend-leaders">
    ${leaders.map(
      ([n, count, colour, ties]) => html`<li key=${n}>
        <span class="map-legend-swatch" style=${swatchStyle([colour])}></span>
        <span class="map-legend-name">${m.names[n]?.[0] ?? n}</span>
        <span class="map-legend-count" title=${ledTitle(count, ties)}>${formatNumber(count)}</span>
      </li>`,
    )}
    ${
      tie &&
      html`<li key="tie">
        <span class="map-legend-swatch" style=${swatchStyle(tie.colours)}></span>
        <span class="map-legend-name">${t('mapmode.tie')}</span>
        <span class="map-legend-count" title=${tieTitle(tie)}>${tie.count ? formatNumber(tie.count) : ''}</span>
      </li>`
    }
  </ul>`;
}

/* The same as a row of chips, by surname as the map names them, scrolled
 * sideways where wider than the screen: the legend in a phone's sheet. */
function Chips({ m, leaders, tie }) {
  return html`<ul class="map-legend-chips">
    ${leaders.map(
      ([n, count, colour, ties]) => html`<li key=${n} title=${ledTitle(count, ties)}>
        <span class="map-legend-swatch" style=${swatchStyle([colour])}></span>
        <span class="map-legend-name">${m.names[n]?.[1] ?? n}</span>
        <span class="map-legend-count">${formatNumber(count)}</span>
      </li>`,
    )}
    ${
      tie &&
      html`<li key="tie" title=${tieTitle(tie)}>
        <span class="map-legend-swatch" style=${swatchStyle(tie.colours)}></span>
        <span class="map-legend-name">${t('mapmode.tie')}</span>
        ${tie.count ? html`<span class="map-legend-count">${formatNumber(tie.count)}</span>` : null}
      </li>`
    }
  </ul>`;
}

/* The figure of all counted in mode *m* (*total* as `figures` has it) in
 * short: the turnout, or the share of the candidate shown or of the one
 * with the most votes (each of those tied for them) after their surname.
 * Beside the legend's title (*titled*), which names the turnout or the
 * candidate, without that. Null where unknown. */
function keyFigure(m, total, titled = false) {
  if (!total?.[1]) return null;
  const share = formatPercent(total[0] / total[1]);
  if (m.kind === 'turnout') return t(titled ? 'mapmode.turnout_total' : 'mapmode.key_turnout', { turnout: share });
  if (m.kind === 'candidate' && titled) return share;
  return `${m.kind === 'winner' ? surnames(m, total[2]) : (m.surname ?? m.name)} ${share}`;
}

/* The legend's title, subtitle and summary (the figure of all counted,
 * *total* as `figures` has it, null where unknown) for mode *m*. */
function legendText(m, total) {
  const share = total?.[1] ? formatPercent(total[0] / total[1]) : null;
  if (m.kind === 'candidate') {
    return {
      title: m.name,
      subtitle: `${m.label} · ${t(m.multi ? 'mapmode.share_voters' : 'mapmode.share_valid')}`,
      summary: total ? `${formatPercent(total[0] / total[1])} · ${t('results.votes', { n: formatNumber(total[0]) })}` : null,
    };
  }
  if (m.kind === 'winner') {
    return {
      title: t('mapmode.winner_title'),
      subtitle: `${m.label} · ${t(m.multi ? 'mapmode.winner_of_council' : 'mapmode.winner_of')}`,
      summary: total
        ? leadText(m, total[2], formatPercent(total[0] / total[1]), 'mapmode.winner_total', 'mapmode.winner_total_tie')
        : null,
    };
  }
  return {
    title: m.contest ? t('mapmode.turnout_title') : t(`mapmode.turnout_${m.election}`),
    subtitle: m.contest ? `${m.label} · ${t('mapmode.turnout_of')}` : t('mapmode.turnout_by'),
    summary: share && t('mapmode.turnout_total', { turnout: share }),
  };
}

/* Renders *children* into element *into*, a root of its own: the legend in
 * the sheet (pane.js), as this Preact has no portals. */
function Portal({ into, children }) {
  useLayoutEffect(() => {
    render(children, into);
  });
  useLayoutEffect(() => () => render(null, into), [into]);
  return null;
}

// Pixels between the tapped point, or the edges of the map left uncovered,
// and the card of the unit tapped.
const CARD_GAP = 12;

/* The unit tapped on a touch screen (map.js `setInspect`), *at* {x, y,
 * pick}: its figures, *lines* (`tipLines`), in a card by the tap, kept
 * within the part of the map left uncovered (*insets*, app.js), with a
 * button that picks the place there as the tap would have. Esc or a press
 * outside the map closes it (`onClose`); on the map, map.js and MapResults
 * see to that. */
function TapCard({ lines, at, insets, onClose }) {
  const card = useRef(null);

  useLayoutEffect(() => {
    const el = card.current;
    const i = insets();
    const right = innerWidth - i.right - el.offsetWidth - CARD_GAP;
    const bottom = innerHeight - i.bottom - el.offsetHeight - CARD_GAP;
    // Below the tap, or above it where there is no room below.
    const below = at.y + CARD_GAP;
    const top = below <= bottom ? below : at.y - el.offsetHeight - CARD_GAP;
    el.style.left = `${Math.max(i.left + CARD_GAP, Math.min(right, at.x - el.offsetWidth / 2))}px`;
    el.style.top = `${Math.max(i.top + CARD_GAP, Math.min(bottom, top))}px`;
  });

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      // Handled: app.js would close the pane as well.
      e.preventDefault();
      onClose();
    };
    const outside = (e) => {
      if (!card.current.contains(e.target) && !e.target.closest('.leaflet-container')) onClose();
    };
    // Before app.js's Esc and any press's own handling.
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('pointerdown', outside, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('pointerdown', outside, true);
    };
  }, []);

  return html`<div class="map-tip map-card" ref=${card} role="dialog" aria-label=${lines[0]}>
    ${tipContent(lines)}
    <button
      type="button"
      class="map-card-ballots"
      onClick=${() => {
        onClose();
        at.pick();
      }}
    >
      ${t('mapmode.show_ballots')}<${ArrowIcon} />
    </button>
  </div>`;
}

/* Where the tooltip of the pointer at *tip* {x, y} goes: below and right
 * of it, or left of it near the right edge of the page, where it would
 * not fit. */
const tipStyle = ({ x, y }) => ({
  left: `${x}px`,
  top: `${y}px`,
  transform: x > innerWidth - 300 ? 'translate(calc(-100% - 14px), 14px)' : 'translate(14px, 14px)',
});

/* The okrsky the map draws (geo/index.json `okrsky.drawn`, obec → the
 * numbers of its okrsky that have an area), for a component: {keys: Set of
 * '<obec>/<n>'}; null while it loads. */
export function useDrawnOkrsky() {
  const [geo] = useLoaded(() => getJSON('/geo/index.json'), []);
  return useMemo(() => {
    if (!geo) return null;
    const entries = Object.entries(geo.okrsky.drawn);
    return { keys: new Set(entries.flatMap(([obec, numbers]) => numbers.map((n) => `${obec}/${n}`))) };
  }, [geo]);
}

/* Shows the mode on *map* (map.js) with its legend: what is shown, by
 * which units, the scale (or the leaders) and the share or turnout of all
 * counted. While the pointer is over the map, a tooltip names the unit
 * under it; on a touch screen a card shows the unit tapped (`TapCard`).
 * The map is fitted to a contest's area when the results shown become
 * that contest's, not as they switch between its modes or the zoom
 * changes their units. *legendRef* gets the legend's element over the map
 * (app.js `insets`, which *insets* is).
 *
 * On a *phone* the legend over the map is a pill under the search card
 * with the figure of all counted (`keyFigure`), which unfolds into the
 * whole legend. With the sheet open, it is a bar at the top of the sheet,
 * rendered into element *sheet* (pane.js): the title, the figure, the
 * scale or the leaders' chips, the rest unfolded on demand. */
export function MapResults({ map, legendRef, phone, sheet, insets }) {
  const m = useMapMode();
  const live = useLive();
  const [index] = useLoaded(dataIndex, []);
  const [tip, setTip] = useState(null);
  // The unit tapped (map.js `setInspect`), and whether the legend is
  // unfolded on a phone.
  const [tapped, setTapped] = useState(null);
  const [unfolded, setUnfolded] = useState(false);
  const drawn = useDrawnOkrsky();
  const ready = Boolean(m && index && drawn);
  const sources = ready
    ? sourcesOf(m, live, areaFiles(m, live, index), councilFiles(m, index))
    : { main: [], okrsky: [], councils: [] };
  const tone = m ? toneOf(m, index) : null;
  const result = useMemo(() => {
    if (!ready) return null;
    const figs = figures(m, sources, index, drawn);
    const p = m.kind === 'winner' ? presentWinner(figs, m) : present(figs);
    return { figs, p: p && { ...p, shown: { ...p.shown, tone } } };
  }, [m, index, drawn, ...sources.main, ...sources.okrsky, ...sources.councils]);
  const shown = result?.p ?? null;
  const total = result?.figs.total ?? null;
  // For the tap handler, which is set once per mode.
  const latest = useRef(null);
  latest.current = { m, index, figs: shown ? result.figs : null, tapped };

  useEffect(() => {
    map?.setResults(shown?.shown ?? null);
  }, [map, shown]);

  // Fitted to a contest's area only when the contest shown changes (or
  // comes after none): another of its modes (a candidate, its turnout, who
  // got the most votes) keeps the view the visitor has zoomed to, as does
  // one from a link that names its view (`keepView`).
  const contest = m?.contest ?? null;
  const keepView = useRef(false);
  keepView.current = Boolean(m?.keepView);
  useEffect(() => {
    if (map && index && contest && !keepView.current) map.fitArea(contestArea(contest, index));
  }, [map, index, contest]);

  useEffect(() => {
    if (!map || !m) return undefined;
    map.setHover(setTip);
    // A tap on a unit with figures shows them; one beside the card closes
    // it; elsewhere the tap picks the place.
    map.setInspect((hit) => {
      const now = latest.current;
      const lines = hit?.unit && now.figs ? tipLines(hit.unit, now.figs, now.m, now.index) : null;
      setTapped(lines ? hit : null);
      return Boolean(lines || now.tapped);
    });
    return () => {
      map.setHover(null);
      map.setInspect(null);
      setTip(null);
      setTapped(null);
    };
  }, [map, m]);

  // Each mode's legend starts folded.
  useEffect(() => setUnfolded(false), [m]);
  // The legend unfolded or folded covers more or less of the map.
  useEffect(() => {
    map?.redraw();
  }, [unfolded]);

  if (!m) return null;
  const percent = (share) => formatPercent(share, shown?.digits ?? 0);
  const { title, subtitle, summary } = legendText(m, total);
  const scale = shown?.scale;
  const steps = (extra = '') => html`<div class=${`map-legend-scale${extra}`} aria-hidden="true">
    ${Array.from({ length: STEPS }, (_, i) => html`<span class=${`step-${i + 1}`}></span>`)}
  </div>`;
  const low = scale && (shown.below ? `≤ ${percent(scale[0])}` : percent(scale[0]));
  const high = scale && (shown.above ? `≥ ${percent(scale[1])}` : percent(scale[1]));
  let body;
  if (shown && m.kind === 'winner') {
    body = html`
      <${Leaders} m=${m} leaders=${shown.leaders} tie=${shown.tie} />
      ${summary ? html`<p class="map-legend-ends"><span class="map-legend-total">${summary}</span></p>` : null}
    `;
  } else if (scale) {
    body = html`
      ${steps()}
      <p class="map-legend-ends">
        <span>${low}</span>
        ${summary ? html`<span class="map-legend-total">${summary}</span>` : null}
        <span>${high}</span>
      </p>
    `;
  } else {
    body = html`<p class="map-legend-none">${t('mapmode.none')}</p>`;
  }
  const classes = ['map-legend', tone && tone !== 'result' && 'toned', m.kind === 'winner' && 'winner'];
  const style = tone ? { '--tone': `var(--map-${tone})` } : undefined;
  const lines = tip && shown && index ? tipLines(tip.unit, result.figs, m, index) : null;
  const tappedLines = tapped && shown && index ? tipLines(tapped.unit, result.figs, m, index) : null;
  const levels = shown ? levelsOf(result.figs) : [];
  const levelsLine = levels.length
    ? html`<p class="map-legend-levels">${t(levels.length > 1 ? 'mapmode.levels' : 'mapmode.levels_one', { units: formatList(levels) })}</p>`
    : null;
  const key = keyFigure(m, total, Boolean(sheet));
  const close = html`<button
    type="button"
    class="map-legend-close"
    title=${t('mapmode.close')}
    aria-label=${t('mapmode.close')}
    onClick=${() => setMapMode(null)}
  >
    <${CloseIcon} />
  </button>`;
  const fold = html`<button
    type="button"
    class="map-legend-fold"
    title=${t(unfolded ? 'mapmode.legend_less' : 'mapmode.legend_more')}
    aria-label=${t(unfolded ? 'mapmode.legend_less' : 'mapmode.legend_more')}
    aria-expanded=${unfolded ? 'true' : 'false'}
    onClick=${() => setUnfolded(!unfolded)}
  >
    <${ExpandIcon} />
  </button>`;

  let legend;
  if (sheet) {
    let row;
    if (shown && m.kind === 'winner') row = html`<${Chips} m=${m} leaders=${shown.leaders} tie=${shown.tie} />`;
    else if (scale) row = html`<div class="map-legend-row"><span>${low}</span>${steps()}<span>${high}</span></div>`;
    else row = html`<p class="map-legend-none">${t('mapmode.none')}</p>`;
    legend = html`<${Portal} into=${sheet}>
      <section class=${[...classes, 'bar'].filter(Boolean).join(' ')} style=${style} aria-label=${t('mapmode.legend')}>
        <div class="map-legend-head">
          <p class="map-legend-title"><strong>${title}</strong></p>
          ${key ? html`<span class="map-legend-key">${key}</span>` : null}
          ${fold}${close}
        </div>
        ${unfolded ? html`<p class="map-legend-sub">${subtitle}</p>${levelsLine}` : null}
        ${row}
      </section>
    <//>`;
  } else if (phone && !unfolded) {
    // The leader overall in their colour, the first (`presentWinner`);
    // those tied for the lead overall in stripes of the first colours.
    const mark =
      m.kind === 'winner'
        ? html`<span
            class="map-legend-swatch"
            style=${swatchStyle(total ? total[2].map((_, i) => Math.min(i, SERIES)) : [0])}
          ></span>`
        : steps(' mini');
    legend = html`<section
      class=${[...classes, 'float', 'pill'].filter(Boolean).join(' ')}
      style=${style}
      ref=${legendRef}
      aria-label=${t('mapmode.legend')}
    >
      <button
        type="button"
        class="map-legend-unfold"
        title=${t('mapmode.legend_more')}
        aria-expanded="false"
        onClick=${() => setUnfolded(true)}
      >
        ${shown ? mark : null}
        <strong>${key ?? title}</strong>
      </button>
      ${close}
    </section>`;
  } else {
    legend = html`<section
      class=${[...classes, 'float'].filter(Boolean).join(' ')}
      style=${style}
      ref=${legendRef}
      aria-label=${t('mapmode.legend')}
    >
      <div class="map-legend-head">
        <p class="map-legend-title"><strong>${title}</strong><span>${subtitle}</span></p>
        ${phone ? fold : null}${close}
      </div>
      ${levelsLine}
      ${body}
    </section>`;
  }
  return html`
    ${legend}
    ${lines ? html`<div class="map-tip" role="tooltip" style=${tipStyle(tip)}>${tipContent(lines)}</div>` : null}
    ${tappedLines ? html`<${TapCard} lines=${tappedLines} at=${tapped} insets=${insets} onClose=${() => setTapped(null)} />` : null}
  `;
}
