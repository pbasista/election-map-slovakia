/* The 2026 results on the map: one candidate's share of the votes across
 * the areas of their contest, who got the most votes where in a contest,
 * or the turnout of the municipal or of the regional elections across the
 * country. The map colours the land by it in STEPS intensities of the
 * results' green (draw.js `setResults`), the scale fitted to the values
 * shown so that their differences show, or the top candidate's in a colour
 * of each candidate's own, and a legend floats on the map with the scale
 * or the candidates and a close button.
 *
 * What is shown (the mode) is one for the page, chosen in a candidate's
 * row (`MapButton`), a contest's header (`ContestMapButton`,
 * `WinnerMapButton`), the candidate card or the boundaries menu
 * (controls.js), so it lives here rather than being passed down through
 * the panes. The values come from the live results (live.js), and follow
 * them: a contest's `areas` (an obec or city district each, or on election
 * night a regional obvod `obvod:<n>` of the kraj), else the contest's own
 * figures over its own area (a mayor's obec, a council's obec or council
 * obvod, a regional obvod, a kraj's obvody); the turnout of the municipal
 * elections from the mayoral (else council) contests of every municipality
 * and city district, that of Bratislava's and Košice's own elections
 * likewise from theirs, that of the regional ones from each kraj's
 * presidential contest.
 *
 * The units follow the zoom, as the boundary overlays do (draw.js
 * `OVERLAYS`), each as fine as its figures go: below the zoom of the obce
 * the regional obvody, each by its obce together (unless the contest is of
 * one obec, which would colour a whole obvod by it); from there every obec
 * by its own figure; from the council overlay's zoom, the council obvody of
 * the obce split into several (a council's own figure, any other
 * contest's okrsky together, live.js `okrsokCouncils`); from the okrsky
 * overlay's zoom, every okrsok drawn (geo/index.json `okrsky.drawn`) with
 * figures of its own in the final results (live.js `okrsky`). An obec
 * without finer figures keeps its own at every zoom. One scale spans the
 * units of every level, so that a colour means the same at each zoom.
 * Pointing at the map names the unit under the pointer with its figures,
 * and in the municipal elections an okrsok's turnout with its 2022 one
 * where it is the same okrsok as then (the 2022 municipal turnout, so not
 * in the regional ones). */

import { html, useEffect, useMemo, useState } from '../vendor/preact-htm.module.js';
import { areaName, contestArea, dataIndex, displayName, getJSON, useLoaded } from './data.js';
import { formatList, formatNumber, formatPercent, t } from './i18n.js';
import { CloseIcon, MapPinIcon, WinnerMapIcon } from './icons.js';
import { addRecord, NOT_COUNTED, okrsokCouncils, useLive } from './live.js';

/* The intensities of the colour: app.css `--map-result-<n>` for a
 * candidate's votes, a turnout's tone mixed into the land (draw.js
 * `TONE_STEPS`, app.css `.map-legend.toned`). */
export const STEPS = 6;
/* The colours of a winner map, app.css `--map-series-<n>`: one for each of
 * the candidates with the most votes overall, the rest `--map-series-other`
 * alike. */
export const SERIES = 8;
const PALETTE = [...Array.from({ length: SERIES }, (_, i) => `series-${i + 1}`), 'series-other'];
// Values beyond these quantiles (where there are enough to tell) take the
// end steps, so that a hamlet of a dozen voters does not stretch the scale.
const TRIM = 0.05;
const TRIM_FROM = 20;

/* What the map shows: null, {kind: 'candidate', id, contest, number, name,
 * label, multi} (a candidacy, its contest's id and label, `multi` a
 * council), {kind: 'winner', contest, label, names, multi} (who got the
 * most votes where, `names` number → [name, surname], `multi` a council,
 * whose top candidate is not all it elects), {kind: 'turnout', election:
 * 'municipal' | 'city' | 'regional'} (the city one Bratislava's and
 * Košice's own elections) or {kind: 'turnout', contest, label}: one
 * contest's (ContestMapButton). */
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

/* The mode that shows the votes of candidate *c* (data.js) in contest
 * *contest* on the map. */
export const candidateMode = (c, contest) => ({
  kind: 'candidate',
  id: c.id,
  contest: c.contest,
  number: c.number,
  name: displayName(c),
  label: contest.label,
  multi: !(contest.id.startsWith('starosta:') || contest.id.startsWith('predseda:')),
});

/* The button at the end of counted candidate *c*'s row (ballots.js) that
 * shows their votes on the map, or takes them off it: across the areas of
 * their contest where it has several, else over its one area. */
export function MapButton({ candidate: c }) {
  const current = useMapMode();
  const on = current?.kind === 'candidate' && current.id === c.id;
  const label = t(on ? 'mapmode.candidate_hide' : 'mapmode.candidate_show');
  const next = {
    kind: 'candidate',
    id: c.id,
    contest: c.contest,
    number: c.number,
    name: displayName(c),
    label: c.result.contestLabel,
    multi: c.result.multi,
  };
  return html`<button
    type="button"
    class="votes-map"
    aria-pressed=${on ? 'true' : 'false'}
    title=${label}
    aria-label=${label}
    onClick=${() => setMapMode(on ? null : next)}
  >
    <${MapPinIcon} />
  </button>`;
}

/* The colour the map shows mode *m* in (draw.js `setResults`): a
 * candidate's votes in the results' green, like the medal; a turnout in the
 * colour its area is drawn in otherwise (app.css `--map-<tone>`), so that
 * nothing changes colour unexpectedly: a municipality's red, a council
 * obvod's orange, Bratislava's and Košice's green, a regional contest's
 * violet. The turnout across the country of the municipal elections is
 * the municipalities', that of the two cities' own elections theirs. A
 * winner map has a colour for each candidate instead: null. */
export function toneOf(m, index) {
  if (m.kind === 'candidate') return 'result';
  if (m.kind === 'winner') return null;
  if (!m.contest) return { municipal: 'accent', city: 'city', regional: 'zsk' }[m.election];
  const [kind, area] = m.contest.split(':');
  const code = area.split('/')[0];
  if (kind === 'predseda' || kind === 'zsk') return 'zsk';
  if (code === 'BA' || code === 'KE') return 'city';
  return kind === 'oz' && (index?.obce[code]?.[4] ?? 0) > 1 ? 'council' : 'accent';
}

/* The pin at the end of a contest's header (ballots.js `Contest`). A press
 * shows the contest's area on the map (*map* {label, onClick}); once the
 * contest is counted (*counted*), the next press colours that area by the
 * 2026 turnout, in the area's own colour (`toneOf`), and the one after
 * takes it off again; the pin is filled in that colour meanwhile. While
 * the map shows another of the contest's results, the area is there
 * already: the first press shows its turnout, in the view as it is. */
export function ContestMapButton({ contest, map, counted }) {
  const current = useMapMode();
  const [index] = useLoaded(dataIndex, []);
  const [placed, setPlaced] = useState(false);
  const on = current?.kind === 'turnout' && current.contest === contest.id;
  const turnout = !on && counted && (placed || current?.contest === contest.id);
  const label = on ? t('mapmode.contest_turnout_hide') : turnout ? t('mapmode.contest_turnout_show') : map.label;
  const mode = { kind: 'turnout', contest: contest.id, label: contest.label };
  const press = () => {
    if (on) setMapMode(null);
    else if (turnout) setMapMode(mode);
    else {
      map.onClick();
      setPlaced(true);
    }
  };
  return html`<button
    type="button"
    class="contest-map"
    style=${{ '--tone': `var(--map-${toneOf(mode, index)})` }}
    aria-pressed=${counted ? String(on) : undefined}
    title=${label}
    aria-label=${label}
    onClick=${press}
  >
    <${MapPinIcon} />
  </button>`;
}

/* The button before the pin of a contest's header (ballots.js `Contest`)
 * once its candidates' votes are counted: it colours each unit of the
 * contest's area (as `MapResults` has them at the zoom) by the candidate
 * with the most votes there, or takes that off the map. In a council of
 * several seats that is its top candidate there, not all it elects, which
 * the legend says. */
export function WinnerMapButton({ contest }) {
  const current = useMapMode();
  const on = current?.kind === 'winner' && current.contest === contest.id;
  const label = t(on ? 'mapmode.winner_hide' : 'mapmode.winner_show');
  const next = {
    kind: 'winner',
    contest: contest.id,
    label: contest.label,
    names: Object.fromEntries(contest.candidates.map((c) => [c.number, [displayName(c), c.surname]])),
    multi: !(contest.id.startsWith('starosta:') || contest.id.startsWith('predseda:')),
  };
  return html`<button
    type="button"
    class="winner-map"
    aria-pressed=${on ? 'true' : 'false'}
    title=${label}
    aria-label=${label}
    onClick=${() => setMapMode(on ? null : next)}
  >
    <${WinnerMapIcon} />
  </button>`;
}

/* The names of the area files (data.js `areaName`) that the figures of
 * mode *m* are in: the contest's, or every one of the election's that the
 * live results list. */
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
  if (c === 'BA' || c === 'KE') return row[5] === c && (kind !== 'oz' || row[6] === Number(n));
  return code === c;
}

/* The names of the municipal area files whose okrsky group those of mode
 * *m* by council obvod (live.js `okrsokCouncils`): of the okresy of the
 * obce in its area split into several council obvody. */
function councilFiles(m, index) {
  const names = new Set();
  for (const [code, row] of Object.entries(index.obce)) {
    if (row[1] && (row[4] ?? 0) > 1 && inArea(m, code, row)) names.add(`okres/${row[1]}`);
  }
  return [...names];
}

/* What the figures of *m* are taken from, as live.js has it now: {main}
 * the contest's entry, or the contests of each of area files *names* that
 * has loaded; {okrsky} the figures by okrsok of those, {councils} of area
 * files *councilNames* (`councilFiles`), where there are any and they have
 * loaded. Their identities change exactly when the figures may. */
function sourcesOf(m, live, names, councilNames) {
  const main = m.contest
    ? [live.of(m.contest)].filter((entry) => entry && entry !== NOT_COUNTED)
    : names.map((name) => live.contests(name)).filter(Boolean);
  const byOkrsok = (list) => list.map((name) => live.okrsky(name)).filter(Boolean);
  return { main, okrsky: byOkrsok(names), councils: byOkrsok(councilNames) };
}

/* The leader of an area's *votes* ({number: votes}) of *valid*: [their
 * votes, valid, number, votes]; null without votes, or where two lead
 * alike, which no colour could say. */
function leader(votes, valid) {
  let best = null;
  let tie = false;
  for (const [n, v] of Object.entries(votes)) {
    if (!best || v > best[0]) {
      best = [v, valid, Number(n), votes];
      tie = false;
    } else if (v === best[0]) tie = true;
  }
  return best && best[0] > 0 && !tie ? best : null;
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

/* The figures of mode *m* from *sources* (`sourcesOf`) by unit, each
 * [part, whole]: [votes, valid] of a candidate, [voters, eligible] of a
 * turnout, [the leader's votes, valid, the leader's number, votes] of a
 * winner map. By obec code (`obce`); by council obvod '<obec>/<k>' of an
 * obec split into several (`councils`); by okrsok '<obec>/<n>' of those
 * drawn (*drawn* `keys`, `useDrawnOkrsky`; `okrsky`), with an okrsok's
 * 2022 municipal turnout as [voters, eligible] (`past`); by regional
 * obvod '<kraj>/<n>' (`regional`), its obce together, or as a whole where
 * only that is known (those in the Set `whole`); and of all counted
 * (`total`, null if unknown). `local` where the contest is of one obec;
 * `ranking` the numbers of a winner map's candidates, most votes first. */
function figures(m, sources, index, drawn) {
  // Records [eligible, voters, valid, votes] first, each made a figure at
  // the end: a unit known by its parts is their records summed.
  const obce = new Map();
  const whole = new Map();
  const councils = new Map();
  const okrsky = new Map();
  const past = new Map();
  const councilSums = new Map();
  const obecSums = new Map();
  // The cities (BA, KE) whose districts' figures are the `areas` of their
  // contest: a district missing from them is one whose votes are not known
  // (okrsky not told apart), which its okrsky that are known would belie.
  const byAreas = new Set();
  const totals = new Map();
  let local = false;
  let piece = false;
  let ranking = [];
  // An area of the live results: an obec, or `obvod:<n>` of *kraj*.
  const put = (key, kraj, rec) => {
    if (key.startsWith('obvod:')) whole.set(`${kraj}/${key.slice('obvod:'.length)}`, rec);
    else if (index.obce[key]) obce.set(key, rec);
  };
  // Every regional obvod of *kraj* as a whole.
  const wholeKraj = (kraj, rec) => {
    for (const [, , k, n] of Object.values(index.obce)) if (k === kraj) whole.set(`${kraj}/${n}`, rec);
  };
  const councilMaps = sources.councils.map((file) => okrsokCouncils(file, index));
  const councilOf = (key) => {
    for (const map of councilMaps) {
      const council = map.get(key);
      if (council) return council;
    }
    return undefined;
  };
  // The okrsky among *records* ('<obec>/<n>' → record): each drawn one a
  // unit of its own, with its 2022 municipal turnout from *file* where
  // *withPast* (one without an area, addressless, is none); all of them
  // summed by council obvod and by obec.
  const byOkrsok = (records, file, withPast) => {
    for (const [key, rec] of Object.entries(records ?? {})) {
      if (drawn.keys.has(key)) {
        okrsky.set(key, rec);
        if (withPast && file.past?.[key]) past.set(key, file.past[key]);
      }
      const council = councilOf(key);
      if (council) addRecord(councilSums, council, rec);
      addRecord(obecSums, key.split('/')[0], rec);
    }
  };
  if (m.contest) {
    const [entry] = sources.main;
    const [kind, area] = m.contest.split(':');
    const code = area.split('/')[0];
    const city = code === 'BA' || code === 'KE';
    const areas = Object.entries(entry?.areas ?? {});
    for (const [key, rec] of areas) put(key, code, rec);
    if (city && entry?.areas) byAreas.add(code);
    const total = entry ? recordOf(entry) : null;
    if (total) addRecord(totals, 0, total);
    if (m.kind === 'winner') ranking = [...(entry?.candidates ?? [])].sort((a, b) => b[1] - a[1]).map(([n]) => n);
    local = (kind === 'starosta' || kind === 'oz') && !city && Boolean(index.obce[code]);
    // A council of one obvod of an obec split into several: the obvod is
    // its whole area, and the obec as a whole has no figure of it.
    piece = local && kind === 'oz' && (index.obce[code][4] ?? 0) > 1;
    // Without areas, the contest's own area: a city's contest its districts
    // (a city council obvod's those in it), which are obce, the city not.
    if (!areas.length && total) {
      if (kind === 'predseda') wholeKraj(code, total);
      else if (kind === 'zsk') whole.set(area, total);
      else if (city) {
        const obvod = kind === 'oz' ? Number(area.split('/')[1]) : null;
        for (const [k, row] of Object.entries(index.obce)) {
          if (row[5] === code && (obvod === null || row[6] === obvod)) obce.set(k, total);
        }
      } else if (piece) councils.set(area, total);
      else if (local) obce.set(code, total);
    }
    // `past` is of the 2022 municipal elections: a municipal contest's.
    const withPast = m.kind === 'turnout' && (kind === 'starosta' || kind === 'oz');
    for (const file of sources.okrsky) byOkrsok(file.contests[m.contest], file, withPast);
  } else if (m.election === 'municipal' || m.election === 'city') {
    // A municipality's turnout is its mayor's contest's; where that has
    // none (a contest not held, or without its figures yet), its council
    // obvody's together; a council obvod's its council's. Bratislava's and
    // Košice's districts are municipalities here, electing their own. The
    // two cities' own elections, of a city mayor and council over all their
    // districts, are on ballots of their own, so a layer of their own
    // ('city', from the city files): by district where the mayor's contest
    // has `areas`, else the whole city alike. Their okrsky likewise.
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
          if (m.election === 'municipal' && (index.obce[code][4] ?? 0) > 1) councils.set(area, recordOf(e));
        }
      }
    }
    const turnouts = new Map(councilTurnouts);
    for (const [code, e] of mayors) turnouts.set(code, recordOf(e));
    for (const [code, rec] of turnouts) {
      addRecord(totals, 0, rec);
      const areas = Object.entries(mayors.get(code)?.areas ?? {});
      if (m.election === 'municipal') obce.set(code, rec);
      else if (areas.length) {
        byAreas.add(code);
        for (const [key, a] of areas) put(key, null, a);
      } else {
        for (const [k, row] of Object.entries(index.obce)) if (row[5] === code) obce.set(k, rec);
      }
    }
    for (const file of sources.okrsky) {
      // The mayor's okrsky, else the council obvody's: each okrsok is in
      // one of them.
      const contests = Object.entries(file.contests);
      const withMayor = new Set(contests.filter(([id]) => id.startsWith('starosta:')).map(([id]) => id.split(':')[1]));
      for (const [id, records] of contests) {
        const [kind, area] = id.split(':');
        if (kind === 'starosta' || (kind === 'oz' && !withMayor.has(area.split('/')[0]))) byOkrsok(records, file, true);
      }
    }
  } else {
    for (const contests of sources.main) {
      const [id, e] = Object.entries(contests).find(([key]) => key.startsWith('predseda:')) ?? [];
      if (!e?.eligible || e.voters == null) continue;
      const kraj = id.slice('predseda:'.length);
      addRecord(totals, 0, recordOf(e));
      const areas = Object.entries(e.areas ?? {});
      for (const [key, a] of areas) put(key, kraj, a);
      // Without areas, the kraj as a whole: each of its obvody.
      if (!areas.length) wholeKraj(kraj, recordOf(e));
    }
    for (const file of sources.okrsky) {
      for (const [id, records] of Object.entries(file.contests)) {
        if (id.startsWith('predseda:')) byOkrsok(records, file, false);
      }
    }
  }
  for (const [key, rec] of councilSums) if (!councils.has(key)) councils.set(key, rec);
  // An obec without a figure of its own: its okrsky together; but not the
  // obec of a council obvod's contest, whose okrsky are only the obvod's.
  if (!piece) {
    for (const [code, rec] of obecSums) {
      if (!obce.has(code) && index.obce[code] && !byAreas.has(index.obce[code][5])) obce.set(code, rec);
    }
  }
  const regional = new Map();
  if (!local) {
    for (const [code, rec] of obce) {
      const [, , kraj, zsk] = index.obce[code];
      addRecord(regional, `${kraj}/${zsk}`, rec);
    }
  }
  for (const [key, rec] of whole) regional.set(key, rec);
  const of = {
    candidate: ([, , valid, votes]) => (valid ? [votes[m.number] ?? 0, valid] : null),
    winner: ([, , valid, votes]) => (valid ? leader(votes, valid) : null),
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
  const total = totals.get(0);
  return {
    obce: figs(obce),
    councils: figs(councils),
    okrsky: figs(okrsky),
    regional: figs(regional),
    whole: new Set(whole.keys()),
    past: figs(past, turnoutOf),
    total: total ? of(total) : null,
    local,
    ranking,
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

/* What the map and the legend show of *figs* (`figures`): {shown} as
 * draw.js `setResults` takes it, {scale} [low, high] the shares of the
 * lowest and highest step, `below`/`above` whether values lie beyond
 * them, `digits` of the percentages; null with no values. The scale spans
 * the values of the units of every level (`allFigures`), not from zero:
 * areas not counted yet have none and are left uncoloured, so they do not
 * widen it. */
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
  // All values alike (a single area, say), there is nothing to tell apart:
  // the strongest step, so that the area shows.
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

/* The same for a winner map (mode *m*): each unit in the colour of its
 * leader (`PALETTE`, by the candidates' votes overall) with the leader's
 * surname; {leaders} [number, units led, colour] of every candidate who
 * leads one of the finest units (`finestFigures`), in the order of the
 * colours; null with no values. */
function presentWinner(figs, m) {
  if (!allFigures(figs).length) return null;
  const colour = new Map(figs.ranking.map((n, i) => [n, Math.min(i, SERIES)]));
  const led = new Map();
  for (const fig of finestFigures(figs)) led.set(fig[2], (led.get(fig[2]) ?? 0) + 1);
  const leaders = [...led]
    .map(([n, count]) => [n, count, colour.get(n) ?? SERIES])
    .sort((a, b) => a[2] - b[2] || b[1] - a[1]);
  return {
    shown: {
      steps: PALETTE.length,
      palette: PALETTE,
      ...cellsOf(figs, (fig) => [colour.get(fig[2]) ?? SERIES, m.names[fig[2]]?.[1] ?? String(fig[2])]),
    },
    leaders,
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
    value = t('mapmode.tip_winner', { name: m.names[fig[2]]?.[0] ?? fig[2], share });
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

/* The candidates of a winner map who lead somewhere, each in their colour,
 * with how many of the units shown they lead. */
function Leaders({ m, leaders }) {
  return html`<ul class="map-legend-leaders">
    ${leaders.map(
      ([n, count, colour]) => html`<li key=${n}>
        <span class="map-legend-swatch" style=${{ background: `var(--map-${PALETTE[colour]})` }}></span>
        <span class="map-legend-name">${m.names[n]?.[0] ?? n}</span>
        <span class="map-legend-count" title=${t('mapmode.winner_count', { n: formatNumber(count) })}
          >${formatNumber(count)}</span
        >
      </li>`,
    )}
  </ul>`;
}

/* Where the tooltip of the pointer at *tip* {x, y} goes: below and right
 * of it, or left of it near the right edge of the page, where it would not
 * fit. */
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

/* Shows the mode on *map* (map.js) and its legend: what is shown, by
 * which units, the scale (or the leaders) and the share or turnout of all
 * counted; while the pointer is over the map, a tooltip of the unit under
 * it. The map is fitted to a contest's area when the results shown become
 * that contest's, not as they change between its modes or the zoom
 * changes their units. *legendRef* gets the legend's element (app.js
 * `insets`). */
export function MapResults({ map, legendRef }) {
  const m = useMapMode();
  const live = useLive();
  const [index] = useLoaded(dataIndex, []);
  const [tip, setTip] = useState(null);
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

  useEffect(() => {
    map?.setResults(shown?.shown ?? null);
  }, [map, shown]);

  // Fitted to a contest's area only when the contest shown changes (or
  // comes after none): another of its modes (a candidate, its turnout, who
  // got the most votes) keeps the view the visitor has zoomed to.
  const contest = m?.contest ?? null;
  useEffect(() => {
    if (map && index && contest) map.fitArea(contestArea(contest, index));
  }, [map, index, contest]);

  useEffect(() => {
    if (!map || !m) return undefined;
    map.setHover(setTip);
    return () => {
      map.setHover(null);
      setTip(null);
    };
  }, [map, m]);

  if (!m) return null;
  const percent = (share) => formatPercent(share, shown?.digits ?? 0);
  let title;
  let subtitle;
  let summary = null;
  if (m.kind === 'candidate') {
    title = m.name;
    subtitle = `${m.label} · ${t(m.multi ? 'mapmode.share_voters' : 'mapmode.share_valid')}`;
    if (total) summary = `${formatPercent(total[0] / total[1])} · ${t('results.votes', { n: formatNumber(total[0]) })}`;
  } else if (m.kind === 'winner') {
    title = t('mapmode.winner_title');
    subtitle = `${m.label} · ${t(m.multi ? 'mapmode.winner_of_council' : 'mapmode.winner_of')}`;
    if (total) {
      summary = t('mapmode.winner_total', { name: m.names[total[2]]?.[0] ?? total[2], share: formatPercent(total[0] / total[1]) });
    }
  } else if (m.contest) {
    title = t('mapmode.turnout_title');
    subtitle = `${m.label} · ${t('mapmode.turnout_of')}`;
    if (total?.[1]) summary = t('mapmode.turnout_total', { turnout: formatPercent(total[0] / total[1]) });
  } else {
    title = t(`mapmode.turnout_${m.election}`);
    subtitle = t('mapmode.turnout_by');
    if (total?.[1]) summary = t('mapmode.turnout_total', { turnout: formatPercent(total[0] / total[1]) });
  }
  const scale = shown?.scale;
  let body;
  if (shown && m.kind === 'winner') {
    body = html`
      <${Leaders} m=${m} leaders=${shown.leaders} />
      ${summary ? html`<p class="map-legend-ends"><span class="map-legend-total">${summary}</span></p>` : null}
    `;
  } else if (scale) {
    body = html`
      <div class="map-legend-scale" aria-hidden="true">
        ${Array.from({ length: STEPS }, (_, i) => html`<span class=${`step-${i + 1}`}></span>`)}
      </div>
      <p class="map-legend-ends">
        <span>${shown.below ? `≤ ${percent(scale[0])}` : percent(scale[0])}</span>
        ${summary ? html`<span class="map-legend-total">${summary}</span>` : null}
        <span>${shown.above ? `≥ ${percent(scale[1])}` : percent(scale[1])}</span>
      </p>
    `;
  } else {
    body = html`<p class="map-legend-none">${t('mapmode.none')}</p>`;
  }
  const classes = ['map-legend', 'float', tone && tone !== 'result' && 'toned', m.kind === 'winner' && 'winner'];
  const lines = tip && shown && index ? tipLines(tip.unit, result.figs, m, index) : null;
  const levels = shown ? levelsOf(result.figs) : [];
  return html`
    <section
      class=${classes.filter(Boolean).join(' ')}
      style=${tone ? { '--tone': `var(--map-${tone})` } : undefined}
      ref=${legendRef}
      aria-label=${t('mapmode.legend')}
    >
      <div class="map-legend-head">
        <p class="map-legend-title"><strong>${title}</strong><span>${subtitle}</span></p>
        <button
          type="button"
          class="map-legend-close"
          title=${t('mapmode.close')}
          aria-label=${t('mapmode.close')}
          onClick=${() => setMapMode(null)}
        >
          <${CloseIcon} />
        </button>
      </div>
      ${levels.length ? html`<p class="map-legend-levels">${t(levels.length > 1 ? 'mapmode.levels' : 'mapmode.levels_one', { units: formatList(levels) })}</p>` : null}
      ${body}
    </section>
    ${
      lines
        ? html`<div class="map-tip" role="tooltip" style=${tipStyle(tip)}>
            ${lines.map((line, i) => (i ? html`<span key=${i}>${line}</span>` : html`<strong key=${i}>${line}</strong>`))}
          </div>`
        : null
    }
  `;
}
