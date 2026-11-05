/* The election results: the live results on election night, the final
 * results after it.
 *
 * They are files of parts of the site of their own, one directory per
 * election (docs/results.md), in the same format: the final results
 * (config `results`, /results/<day>/), which a release brings from the
 * definitive packages, and the live results of an election's night
 * (config `live`, /live/<day>/, elections.toml `live`), which `ems results
 * poll --deploy` deploys whenever they change. The final results win
 * wherever they are there.
 *
 * status.json is read from the polls' closing and then every minute while
 * the page is in view, for a week (config `liveWindow`, elections.toml
 * `live_days`): the final results' first, and only where there is none yet
 * (404) the live results', so that a page left open switches to the final
 * results once a release brings them. After that, and in a site built
 * without live results (config `live` null: off once the final results
 * are in), the final results' status.json is read once per page load, so
 * that a page left open, or an old copy of the site, stops polling.
 *
 * status.json lists a content hash per area file; each file is fetched
 * once per hash, from the directory of the status.json that lists it, so
 * only what changed is fetched again: the files of the contests shown,
 * and for the map's turnout of an election of many contests (mapmode.js)
 * the turnout file (`turnout`) with the cities' or the kraje's files. The
 * final results also have figures per okrsok (`okrsky/<area>`), fetched
 * only by what shows them: the map, a place's units on the ballots
 * (`placeResults`) and the card's origins of the votes. Every figure of a
 * unit made of finer ones is the results' own (docs/results.md): nothing
 * here or in the views adds figures up.
 *
 * Without results, or while they cannot be read, the page shows none and
 * works as before. */

import { html, useEffect, useLayoutEffect, useState } from '../vendor/preact-htm.module.js';
import { dataIndex } from './data.js';
import { formatNumber, formatPercent, livePath, liveWindow, polls, resultsPath, rounds, t } from './i18n.js';
import { areaName, isCity, isCountry, isRegional, isSingle, parseContest } from './kinds.js';

const POLL_MS = 60_000;
// setTimeout's longest delay (2^31 − 1 ms, about 24.8 days): a longer wait
// for the polls' closing goes in steps.
const MAX_DELAY = 2 ** 31 - 1;

/* A contest's entry while its area has results but it is not counted yet. */
export const NOT_COUNTED = { status: 'pending' };

const listeners = new Set();
// status.json as last read, and the directory it was read from (the final
// or the live results'), which the files it lists are fetched from; null
// until then, and without results.
let status = null;
let source = null;
// Whether status.json has been tried once, read or not: until then nothing
// is known of the results, not even that they are awaited.
let tried = false;
let index = null;
// Area name → {hash, data}: the file of that hash, or the older one's data
// while it loads.
const files = new Map();
let timer = null;

// The files that come within this long of the last telling are told of
// together, at its end: the map's municipal turnout alone fetches some 80
// okrsok files, and each telling renders the page again and works the
// map's figures out anew (mapmode.js), which one by one held the page up
// for seconds.
const NOTIFY_MS = 200;
let notifying = 0;
let notified = -Infinity;

const notify = () => {
  clearTimeout(notifying);
  notifying = 0;
  notified = performance.now();
  for (const listener of listeners) listener();
};

const notifySoon = () => {
  notifying ||= setTimeout(notify, Math.max(0, notified + NOTIFY_MS - performance.now()));
};

// Whether counting has started: status.json read and naming a phase.
const counting = () => Boolean(status) && status.phase !== 'none';

/* status.json of the results in directory *base*: null where there is none
 * (404); throws where it cannot be read. */
async function readStatus(base) {
  const response = await fetch(`${base}/status.json`, { cache: 'no-cache' });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`${base}/status.json: HTTP ${response.status}`);
  return response.json();
}

async function poll() {
  try {
    // The final results once they are there; until then, within the window,
    // the live results.
    let base = resultsPath;
    let next = await readStatus(base);
    if (!next && livePath && windowNow() === 'during') {
      base = livePath;
      next = await readStatus(base);
    }
    if (next) {
      index ??= await dataIndex();
      if (next.version !== status?.version || base !== source) {
        status = next;
        source = base;
        notify();
      }
    }
  } catch (e) {
    // The results shown stay as they were until status.json can be read again.
    console.error(e);
  } finally {
    if (!tried) {
      tried = true;
      notify();
    }
  }
}

/* Where now is relative to the polling window: 'before' the polls close,
 * 'during' the days after, 'after' those. Always 'during' without a window
 * (a test server), always 'after' in a site without live results. */
function windowNow() {
  if (!livePath) return 'after';
  if (!liveWindow) return 'during';
  const now = Date.now();
  if (now < liveWindow[0]) return 'before';
  return now < liveWindow[1] ? 'during' : 'after';
}

/* Schedules the next read: in a minute, or at the polls' closing; none past
 * the window, nor while the page is out of view. */
function schedule() {
  clearTimeout(timer);
  if (document.visibilityState !== 'visible') return;
  const when = windowNow();
  if (when === 'before') timer = setTimeout(update, Math.min(liveWindow[0] - Date.now(), MAX_DELAY));
  else if (when === 'during') timer = setTimeout(update, POLL_MS);
}

/* Reads status.json if within the window, then schedules the next read. */
function update() {
  if (windowNow() === 'during') poll().then(schedule);
  else schedule();
}

let started = false;
function start() {
  if (started) return;
  started = true;
  // Past the window, once: the final results.
  if (windowNow() === 'after') poll();
  else update();
  // A page in a background tab does not poll; back in view, it catches up.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') update();
    else clearTimeout(timer);
  });
}

function load(name, hash) {
  const file = files.get(name);
  if (file?.hash === hash) return file;
  const next = { hash, data: file?.data ?? null };
  files.set(name, next);
  fetch(`${source}/${name}.json?v=${hash}`)
    .then((response) => {
      if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      if (files.get(name) !== next) return;
      next.data = data;
      notifySoon();
    })
    // Tried again with the next hash; the older data stays shown meanwhile.
    .catch((e) => console.error(e));
  return next;
}

/* The results as read so far. "Not known" (undefined) means before
 * counting starts, without results, or while the file loads. */
const live = {
  /* status.json (docs/results.md): {phase, updated, source, …}; null
   * without results. */
  get status() {
    return status;
  },
  /* Whether status.json has been tried yet, so that a null `status` means
   * no results rather than not read yet. */
  get tried() {
    return tried;
  },
  /* The live entry of contest *id*: NOT_COUNTED in an area not counted
   * yet; undefined where not known, or where it was held nowhere, no
   * candidate having registered (data/index.json `uncontested`): nothing
   * is to be counted. */
  of(id) {
    if (!counting() || !index || index.uncontested.includes(id)) return undefined;
    const name = areaName(id, index);
    const hash = status.files?.[name];
    if (!hash) return NOT_COUNTED;
    const file = load(name, hash);
    return file.data ? (file.data.contests[id] ?? NOT_COUNTED) : undefined;
  },
  /* The contests of area file *name* (kinds.js `areaName`, a key of
   * `status.files`), id → live entry, for the map (mapmode.js): {} where
   * the file is absent (nothing counted in its area yet); undefined where
   * not known. */
  contests(name) {
    if (!counting()) return undefined;
    const hash = status.files?.[name];
    if (!hash) return {};
    return load(name, hash).data?.contests;
  },
  /* The figures by okrsok of area file *name* (`okrsky/<name>` in
   * `status.files`, docs/results.md), only in the final results:
   * {contests: {id: {'<obec>/<n>': [eligible, voters, valid, {number:
   * votes}]}}, units, past}, `units` the units made of the okrsky
   * (`placeResults`), `past` the election before's on the same okrsky
   * (`pastOf`). Null where there are none; undefined where not known. */
  okrsky(name) {
    if (!counting()) return undefined;
    const hash = status.files?.[`okrsky/${name}`];
    if (!hash) return null;
    return load(`okrsky/${name}`, hash).data ?? undefined;
  },
  /* Whether area file *name* has figures by okrsok, without fetching
   * them. */
  hasOkrsky(name) {
    return Boolean(status?.files?.[`okrsky/${name}`]);
  },
  /* The turnout of the elections of many contests (`turnout` in
   * `status.files`, docs/results.md), for the map (mapmode.js): {municipal,
   * city, regional}, each {total, …} of [eligible, voters]; null where
   * there is none; undefined where not known. */
  turnout() {
    if (!counting()) return undefined;
    const hash = status.files?.turnout;
    if (!hash) return null;
    return load('turnout', hash).data ?? undefined;
  },
};

/* The live results, for a component: renders it again whenever they
 * change. It listens from a layout effect, which runs as the render is
 * committed, before anything else can: a file its first render asked for
 * (`load`) may come before a plain effect's turn after the paint (a small
 * one, or one the browser has kept), and its telling would then be missed,
 * the component showing the file as still loading until something else
 * renders it again. */
export function useLive() {
  const [, setTick] = useState(0);
  useLayoutEffect(() => {
    const listener = () => setTick((n) => n + 1);
    listeners.add(listener);
    start();
    return () => listeners.delete(listener);
  }, []);
  return live;
}

/* How the figures of the election before were found for an okrsok
 * (docs/results.md `past`): the same area (by the addresses, or the obec's
 * one okrsok), the same number with about as many registered voters, an
 * estimate from the okrsky its addresses were in then, or not at all. */
export const PAST = { unknown: 0, same: 1, identity: 2, approximate: 3 };

/* The election before in okrsok *key* of contest *id*, from okrsok file
 * *file* (`live.okrsky`): {day, method (`PAST`), record}, `record` [eligible,
 * voters, valid, {number: votes}] (the votes of the contest's candidates
 * who stood for the same office then, by their numbers now), null where
 * the method is unknown. An okrsok of an obec of one okrsok then and now
 * is that obec. Null where nothing is known of it: no election before, or
 * no figures there. */
export function pastOf(file, id, key) {
  const past = file?.past;
  if (!past?.day) return null;
  const figures = past.contests[id] ?? {};
  const method = past.okrsky[key] ?? PAST.same;
  if (method === PAST.unknown) return { day: past.day, method, record: null };
  const record = figures[key] ?? (key in past.okrsky ? null : figures[key.split('/')[0]]);
  return record ? { day: past.day, method, record } : null;
}

/* What the figures of the election before are, by *method* (`PAST`): of the
 * same area, of the okrsok of the same number and about as many voters,
 * estimated, or not known; and (`pastTitle`) how they were found, against
 * the election of day *day* where given (a referendum's is the vote before
 * of whatever kind, which the page's `previous` does not name). */
export const pastLabel = (method) => t(`past.${pastName(method)}`);

export const pastTitle = (method, day = null) =>
  t(`past.how_${pastName(method)}`, day ? { previous: day.slice(0, 4) } : {});

const pastName = (method) => Object.keys(PAST).find((name) => PAST[name] === method) ?? 'unknown';

/* The election before of contest *id* in a unit of okrsok file *file*
 * made of its okrsky, as the file's `past.units` has it (summed by `ems
 * results`, docs/results.md): *level* 'obec', 'okres', 'kraj', 'zsk' or
 * 'obvod' and the unit's *code* ('<obec>/<k>' of a council obvod, the
 * number of a regional one), or 'all' and 'obce', the whole contest by
 * its okrsky or by its obce. {day, method, record}, the method the least
 * certain of its parts'; null where not known (a part not known, or
 * nothing then). An obec with figures of its own in `past.contests` has no
 * entry: `pastObec`. */
function pastUnit(file, id, level, code = null) {
  const past = file?.past;
  const units = past?.day ? past.units[id]?.[level] : undefined;
  const unit = level === 'all' || level === 'obce' ? units : units?.[code];
  return unit ? { day: past.day, method: unit[0], record: unit[1] } : null;
}

/* The election before of contest *id* in obec *code*, from okrsok file
 * *file*: its own figures then (the same area), else its okrsky's then
 * summed (`pastUnit`). */
function pastObec(file, id, code) {
  const own = file?.past?.day ? file.past.contests[id]?.[code] : undefined;
  return own ? { day: file.past.day, method: PAST.same, record: own } : pastUnit(file, id, 'obec', code);
}

/* The whole of contest *id* at the election before, as the okrsok file of
 * *place* ({obec}; see `placeResults`) has it ({day, method, record}): the
 * same contest's then, for one that is its own counterpart (a country-wide
 * one, a mayor's), else (a council obvod's, whose file is all of it) its
 * obce's then summed where each has its own (a regional or a city council
 * obvod's: the same area, as the 2022 regional constituencies over 2017's
 * figures), else its okrsky's (`pastUnit`); null where unknown or the file
 * has not come. */
export function placePast(id, place) {
  const entry = live.of(id);
  if (!entry || entry === NOT_COUNTED || !place?.obec) return null;
  const name = okrsokFile(id, place.obec);
  const file = live.hasOkrsky(name) ? live.okrsky(name) : null;
  const record = file?.past?.totals?.[id];
  if (record) return { day: file.past.day, method: PAST.same, record };
  return pastUnit(file, id, 'obce') ?? pastUnit(file, id, 'all');
}

/* The scopes a contest's results can be narrowed to, coarsest first: the
 * kraj and okres only of a country-wide contest, the regional obvod
 * ('zsk') only of a regional president's. */
export const SCOPES = ['all', 'kraj', 'okres', 'zsk', 'obec', 'obvod', 'okrsok'];

/* The finest of *units* (`placeResults`) not finer than *level* (one of
 * SCOPES), or null: the unit the ballots show at the level, and the one a
 * map mode made there is of (mapmode.js). */
export const unitWithin = (units, level) =>
  units.filter((u) => SCOPES.indexOf(u.scope) <= SCOPES.indexOf(level)).at(-1) ?? null;

/* The okrsok file of contest *id* for obec *obec* (`live.okrsky`): its
 * area file's, or of a country-wide contest (a party's list too) its
 * kraj's, `country/<kraj>` or `list/<p>/<kraj>`. */
const okrsokFile = (id, obec) => (isCountry(id) ? `${areaName(id, index)}/${index.obce[obec][2]}` : areaName(id, index));

/* The figures of counted contest *id* in the units of *place* ({obec,
 * obvod, okrsok}: its obec or city district code, and its council obvod
 * and okrsok where known), coarsest first, each unit only where it has
 * figures of its own that differ from the whole contest's and from the
 * coarser units': [{scope, record, past}], `scope` one of SCOPES, `record`
 * as in the okrsok files, `past` the unit's in the election before
 * ({day, method, record}, as `pastOf` gives an okrsok's) where anything is
 * known of it. The units, each as the results have it (summed by `ems
 * results`, docs/results.md), never summed here:
 * - kraj and okres: of a country-wide contest (its record's `units`); the
 *   past, `pastUnit`;
 * - zsk: the regional obvod of a regional president (its record's
 *   `units`); the past, `pastUnit`;
 * - obec: of a regional, a city or a country-wide contest (its `areas`
 *   entry, else the okrsok file's `units`); the past, the whole obec's
 *   then (`pastObec`);
 * - obvod: the council obvod of an obec split into several, for any
 *   contest but that obvod's own council (the okrsok file's `units`); the
 *   past, `pastUnit`;
 * - okrsok.
 * The okrsok files load as needed (only the final results have them): []
 * without them, or while they load. Made once per entry, place and file:
 * the ballots ask it for every party's list on every render, and the
 * units then keep their identity (ballots.js `inUnit`, `preferenceRank`). */
const placed = new WeakMap();
export function placeResults(id, place) {
  const entry = live.of(id);
  if (!entry || entry === NOT_COUNTED || !place?.obec) return [];
  const name = okrsokFile(id, place.obec);
  const file = live.hasOkrsky(name) ? live.okrsky(name) : null;
  const key = `${place.obec}/${place.obvod ?? ''}/${place.okrsok ?? ''}`;
  const kept = placed.get(entry);
  if (kept?.key === key && kept.file === file) return kept.units;
  const units = unitsOf(id, entry, place, file);
  placed.set(entry, { key, file, units });
  return units;
}

function unitsOf(id, entry, place, file) {
  const { kind, area } = parseContest(id);
  const records = file?.contests[id] ?? {};
  const sums = file?.units[id] ?? {};
  const same = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  const whole = [entry.eligible, entry.voters, entry.valid];
  const out = [];
  const push = (scope, record, past = null) => {
    if (record && !same(record, whole) && !out.some((u) => same(u.record, record))) out.push({ scope, record, past });
  };
  const [, okres, kraj, zsk] = index.obce[place.obec];
  if (isCountry(id) && entry.units) {
    // Bratislava and Košice as wholes are in no okres.
    push('kraj', entry.units.kraj[kraj], pastUnit(file, id, 'kraj', kraj));
    if (okres) push('okres', entry.units.okres[okres], pastUnit(file, id, 'okres', okres));
  }
  if (kind === 'predseda' && entry.units && zsk) {
    push('zsk', entry.units.zsk[zsk], pastUnit(file, id, 'zsk', zsk));
  }
  if (isRegional(id) || isCountry(id) || isCity(area)) {
    // Where the contest has `areas`, an obec missing from them is one whose
    // votes are not known (okrsky of the cities not told apart): none shown.
    push('obec', entry.areas ? entry.areas[place.obec] : sums.obec?.[place.obec], pastObec(file, id, place.obec));
  }
  if (place.obvod) {
    // Only an obec split into several has them, and not for its councils.
    const target = `${place.obec}/${place.obvod}`;
    push('obvod', sums.obvod?.[target], pastUnit(file, id, 'obvod', target));
  }
  if (place.okrsok) {
    const key = `${place.obec}/${place.okrsok}`;
    push('okrsok', records[key], pastOf(file, id, key));
  }
  return out;
}

/* Whether the figures by okrsok of contest *id* for obec *obec* are still
 * loading: `placeResults` then has none of the units made of them yet,
 * which are not to be taken for missing. */
export function okrskyLoading(id, obec) {
  const name = okrsokFile(id, obec);
  return live.hasOkrsky(name) && live.okrsky(name) === undefined;
}

/* How much the registered voters may have grown since the contest's last
 * election. With this margin on their number then, the voters not counted
 * yet are bounded, and a winner is called only when no likely number of
 * them could change who wins. */
export const GROWTH = 1.1;

/* At most how many votes a contest has left to count, one per registered
 * voter of the districts not counted yet: {remaining, bound}, where
 * `bound` is the registered voters at the last election times GROWTH (or
 * those counted, if more). Nothing remains once every district is counted
 * (`bound` null then); null where either figure is unknown, and then
 * nothing is called. */
function uncounted(contest, r) {
  if (r.counted && r.counted[0] >= r.counted[1]) return { remaining: 0, bound: null };
  if (!contest.past || r.eligible == null) return null;
  const bound = Math.ceil(Math.max(contest.past.eligible * GROWTH, r.eligible));
  return { remaining: bound - r.eligible, bound };
}

/* The ballot numbers sure of one of *seats* seats among *votes* ([number,
 * votes] pairs): those whom fewer than *seats* others could reach (a tie
 * counts as reached) even if every one of the *remaining* votes went to
 * them, as each voter gives a candidate one vote at most. */
function sure(votes, seats, remaining) {
  const called = new Set();
  for (const [n, v] of votes) {
    const rivals = votes.filter(([m, w]) => m !== n && w + remaining >= v).length;
    if (rivals < seats) called.add(n);
  }
  return called;
}

/* How far a count has got: the share of an area's registered voters
 * (*voters* [of the okrsky counted, of all]) whose okrsky are counted. An
 * okrsok counts whole once it is in, however many voted, so that okrsky
 * weigh by size. Under 100 % until every okrsok (*units* [counted, all])
 * is in, as the area's voters are an estimate until then. Without the
 * voters, the okrsky's share; null without either. */
export function countShare(voters, units) {
  if (units?.[1] && units[0] >= units[1]) return 1;
  if (voters?.[1]) return Math.min(0.99, voters[0] / voters[1]);
  return units?.[1] ? units[0] / units[1] : null;
}

/* A count's progress (`countShare`) as a percentage: whole points, but
 * tenths below 10 % and never 0 % once anything is counted. The small
 * places come in first, so a count well under way can still be a fraction
 * of a per cent of the voters. */
export function formatProgress(share) {
  if (share > 0 && share < 0.0005) return `< ${formatPercent(0.001, 1)}`;
  return formatPercent(share, share > 0 && share < 0.1 ? 1 : 0);
}

/* The flags of the results (docs/results.md): elected (a party: won
 * seats; an answer: won), a substitute on a party's list, through to a
 * presidential election's round 2, withdrew yet stayed on the ballot
 * (whose votes count). */
const ELECTED = 1;
const SUBSTITUTE = 0;
const ADVANCED = 2;
const WITHDRAWN = -1;

/* The results of *contest* (data.js `contest`) from its live entry *r*
 * (docs/results.md):
 * - status: 'partial', 'winner' or 'final';
 * - counted, eligible, voters, valid, filled: as in the entry, null where
 *   absent;
 * - preferences: of a party's list, its persons' preference votes (summed
 *   by `ems results`), else null;
 * - seats: the seats elected; reportedSeats those the results give, null
 *   where they give none;
 * - registered: while counting, the area's registered voters as far as
 *   known (those of its last election, or those counted if more);
 * - progress: how far the count has got (`countShare`);
 * - byNumber: ballot number → {votes, share, elected, called, withdrawn,
 *   substitute, advanced, won}, `share` of the valid ballots (for a
 *   council: of the voters with a valid ballot; for a party's list: of
 *   the party's votes), `called` decided by this site on a partial count,
 *   not yet officially, `substitute` of a party's list, `advanced` to a
 *   presidential round 2, `won` a party's seats (where the results give
 *   them);
 * - call: {remaining, bound} (`uncounted`), what a call rests on.
 * A contest counted with as many seats filled as it has candidates has
 * them all elected, `votes` and `share` null, until ŠÚ SR publishes their
 * votes (on the night of 2026 it published no council's). A candidate who
 * withdrew but stayed on the list cannot be elected, so fewer seats are
 * filled; where the results flag them (`withdrawn`), their votes count
 * among the valid ones and in the shares, but they are never called, nor
 * in the way of a call. Decoded once per entry and contest: the ballots
 * decode every party's list on every render, and an entry stays as long as
 * its file. */
const decoded = new WeakMap();
export function decodeResults(contest, r) {
  const kept = decoded.get(r);
  if (kept?.contest === contest) return kept.results;
  const results = decode(contest, r);
  decoded.set(r, { contest, results });
  return results;
}

function decode(contest, r) {
  const seats = r.seats ?? (isSingle(contest.id) ? 1 : (contest.seats ?? contest.seats2022));
  const votes = r.candidates.filter(([, , flag]) => flag !== WITHDRAWN).map(([n, v]) => [n, v]);
  const call = r.status === 'partial' && seats ? uncounted(contest, r) : null;
  const called = call ? sure(votes, seats, call.remaining) : new Set();
  const byNumber = new Map(
    r.candidates.map(([n, v, flag]) => [
      n,
      {
        votes: v,
        share: r.valid ? v / r.valid : null,
        elected: flag === ELECTED,
        called: called.has(n),
        withdrawn: flag === WITHDRAWN,
        substitute: flag === SUBSTITUTE,
        advanced: flag === ADVANCED,
        won: r.won?.[n] ?? null,
      },
    ]),
  );
  if (!r.candidates.length && r.filled && r.filled === contest.candidates.length) {
    for (const c of contest.candidates) {
      byNumber.set(c.number, { votes: null, share: null, elected: true, called: false, withdrawn: false });
    }
  }
  const registered = contest.past && r.eligible != null ? Math.max(contest.past.eligible, r.eligible) : null;
  return {
    status: r.status,
    counted: r.counted ?? null,
    eligible: r.eligible ?? null,
    voters: r.voters ?? null,
    valid: r.valid ?? null,
    seats,
    reportedSeats: r.seats ?? null,
    filled: r.filled ?? null,
    preferences: r.preferences ?? null,
    registered,
    progress: countShare(registered === null ? null : [r.eligible, registered], r.counted),
    byNumber,
    call,
  };
}

/* A time of day in Slovak time on the 24-hour clock, as the polls and the
 * count are announced there, wherever the page is read. */
const slovakTime = (date) =>
  date.toLocaleTimeString(document.documentElement.lang, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: 'Europe/Bratislava',
  });

/* The time the results were last got from ŠÚ SR (the latest of
 * the sources', else status.json's `updated`). */
function sourceTime(s) {
  const times = Object.values(s.source ?? {})
    .map((x) => x?.time)
    .filter(Boolean)
    .map((time) => new Date(time))
    .sort((a, b) => a - b);
  const latest = times.at(-1) ?? (s.updated ? new Date(s.updated) : null);
  return latest ? slovakTime(latest) : '';
}

/* The polls' opening and closing that now falls in or after: a presidential
 * election's round 2 is voted two weeks after round 1, at the same hours,
 * so its day has the voting line too. */
function pollsOf(now) {
  const windows = rounds ? rounds.map(([, open, close]) => [new Date(open), new Date(close)]) : [polls];
  return windows.findLast(([open]) => now >= open) ?? windows[0];
}

/* The voting under way, under the title, from the polls' opening to
 * their closing (config `polls`), while there are no results yet: a bar
 * of how much of the voting day has passed and when the polls close. It
 * neither moves nor blinks, as nothing on the site changes meanwhile; it is
 * redrawn every minute, so that the bar fills and the line comes and goes
 * with the polls.
 * After the closing, a line says that results are awaited while
 * status.json, once *tried*, has nothing counted (or cannot be read) and
 * is still polled; not before it is tried, so that a page loaded with the
 * results in does not flash it. */
function VotingStatus({ tried }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!polls) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);
  if (!polls) return null;
  const [open, close] = pollsOf(now);
  if (now < open) return null;
  if (now >= close) {
    if (!tried || windowNow() === 'after') return null;
    return html`<p class="live-status awaiting" role="status" title=${t('results.awaiting_title', { close: slovakTime(close) })}>
      <span class="live-dot" aria-hidden="true"></span>${t('results.awaiting')}
    </p>`;
  }
  const share = (now - open) / (close - open);
  const title = t('voting.title', { open: slovakTime(open), close: slovakTime(close) });
  return html`<p class="live-status voting" title=${title}>
    <span class="voting-bar" aria-hidden="true"><span style=${{ width: `${(share * 100).toFixed(1)}%` }}></span></span>
    ${t('voting.status', { time: slovakTime(close) })}
  </p>`;
}

/* The results' sources (status.json `source`, contests.py `source_of`) in
 * the order the status line names them: [key, the strings that name it
 * (`results.status_<name>` there, `results.units_<name>` in the tooltip's
 * count of units), their variables]. The regional elections first, as
 * they are counted by okrsok and come in sooner; a presidential
 * election's rounds by number; a country-wide election's one source as
 * the country. */
const SOURCES = [
  ['osk', 'regional', {}],
  ['oso', 'municipal', {}],
  ['prez1', 'round', { round: 1 }],
  ['prez2', 'round', { round: 2 }],
  ['ref', 'country', {}],
  ['nrsr', 'country', {}],
  ['ep', 'country', {}],
];

/* The state of the results under the title, on one line where it
 * fits. While counting: how far each of the election's sources has got
 * (`countShare`; the units counted in the tooltip) and the time of the
 * results. Nothing once final, which goes without saying after the
 * elections. Before counting starts, or without results: VotingStatus. */
export function LiveStatus() {
  const results = useLive();
  const s = results.status;
  if (!s || s.phase === 'none') return html`<${VotingStatus} tried=${results.tried} />`;
  if (s.phase === 'final') return null;
  const sources = SOURCES.filter(([key]) => s.source?.[key]).map(([key, name, vars]) => ({ x: s.source[key], name, vars }));
  const parts = sources.flatMap(({ x, name, vars }) => {
    const share = countShare(x.voters, x.counted);
    return share === null ? [] : [t(`results.status_${name}`, { ...vars, share: formatProgress(share) })];
  });
  const text = [t('results.status_counting'), ...parts, sourceTime(s)].filter(Boolean).join(' · ');
  const units = sources.map(({ x, name, vars }) =>
    t(`results.units_${name}`, {
      ...vars,
      n: x.counted ? `${formatNumber(x.counted[0])}/${formatNumber(x.counted[1])}` : '–',
    }),
  );
  const title = `${t('results.status_source')} ${t('results.status_units', { list: units.join(', ') })}`;
  return html`<p class="live-status" role="status" title=${title}>
    <span class="live-dot" aria-hidden="true"></span>${text}
  </p>`;
}

/* The numbers of results *res* as the results.* strings take them. */
export const resultsVars = (res) => ({
  valid: formatNumber(res.valid ?? 0),
  voters: formatNumber(res.voters ?? 0),
  eligible: formatNumber(res.eligible ?? 0),
  registered: formatNumber(res.registered ?? 0),
  turnout: res.eligible ? formatPercent(res.voters / res.eligible) : '',
  counted: res.progress != null ? formatProgress(res.progress) : '',
  districts: formatNumber(res.counted?.[0] ?? 0),
  districts_all: formatNumber(res.counted?.[1] ?? 0),
  seats: formatNumber(res.seats ?? 0),
  filled: formatNumber(res.filled ?? 0),
});
