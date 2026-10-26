/* The election results: partial on election night, final after it.
 * They are part of the site, under the election's own directory (config
 * `results`, /results/<day>/, docs/results.md): on election night `ems
 * results` writes them and deploys the site with them whenever they change,
 * and after it a release carries the final results. Their status.json is
 * read from the polls' closing, again every minute while the page is in
 * view, for a week (config `liveWindow`, site.toml `live_days`); after that
 * only once per page load, so that a page left open, or an old copy of the
 * site, stops polling. A site built not to poll (config `live`, site.toml
 * `live`: off once the final results are in it) reads it once per page
 * load at any time. An area file of results is fetched once for each
 * content hash status.json lists, so that only what changed is fetched
 * again: those of the contests shown, and for the map's turnout
 * (mapmode.js) all of them. The final results also have the figures of
 * every okrsok, in files of their own (`okrsky/<area>`), fetched only by
 * what shows them: the map's results, the units of a place on the ballots
 * (`placeResults`), the candidate card's origins of the votes.
 * Without results, or while they cannot be read, the page shows none and
 * works as before. */

import { html, useEffect, useState } from '../vendor/preact-htm.module.js';
import { areaName, dataIndex } from './data.js';
import { formatNumber, formatPercent, liveWindow, live as polling, polls, resultsPath, t } from './i18n.js';

const POLL_MS = 60_000;
// setTimeout's longest delay (2^31 − 1 ms, about 24.8 days): a longer wait
// for the polls' closing goes in steps.
const MAX_DELAY = 2 ** 31 - 1;

/* A contest's entry while its area has results but it is not counted yet. */
export const NOT_COUNTED = { status: 'pending' };

const listeners = new Set();
// status.json as last read; null until then, and without results.
let status = null;
// Whether status.json has been tried once, read or not: until then nothing
// is known of the results, not even that they are awaited.
let tried = false;
let index = null;
// Area name → {hash, data}: the file of that hash, or the older one's data
// while it loads.
const files = new Map();
let timer = null;

const notify = () => {
  for (const listener of listeners) listener();
};

async function poll() {
  try {
    const response = await fetch(`${resultsPath}/status.json`, { cache: 'no-cache' });
    if (!response.ok) throw new Error(`status.json: HTTP ${response.status}`);
    const next = await response.json();
    index ??= await dataIndex();
    if (next.version !== status?.version) {
      status = next;
      notify();
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

/* Where the page is in the window it polls in: 'before' the polls close,
 * 'during' the days after, 'after' those; always 'during' without a
 * window (a test server), always 'after' in a site that does not poll. */
function windowNow() {
  if (!polling) return 'after';
  if (!liveWindow) return 'during';
  const now = Date.now();
  if (now < liveWindow[0]) return 'before';
  return now < liveWindow[1] ? 'during' : 'after';
}

/* The next read: in a minute, or at the polls' closing; none past the
 * window, nor while the page is out of view. */
function schedule() {
  clearTimeout(timer);
  if (document.visibilityState !== 'visible') return;
  const when = windowNow();
  if (when === 'before') timer = setTimeout(update, Math.min(liveWindow[0] - Date.now(), MAX_DELAY));
  else if (when === 'during') timer = setTimeout(update, POLL_MS);
}

/* Reads status.json if the window has begun and not ended, then schedules
 * the next read. */
function update() {
  if (windowNow() === 'during') poll().then(schedule);
  else schedule();
}

let started = false;
function start() {
  if (started) return;
  started = true;
  // Past the window, once: the results as they were left.
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
  fetch(`${resultsPath}/${name}.json?v=${hash}`)
    .then((response) => {
      if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      if (files.get(name) !== next) return;
      next.data = data;
      notify();
    })
    // Tried again with the next hash; the older data stays shown meanwhile.
    .catch((e) => console.error(e));
  return next;
}

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
   * yet; undefined before counting starts, without results, or while its
   * file loads. */
  of(id) {
    if (!status || status.phase === 'none' || !index) return undefined;
    const name = areaName(id, index);
    const hash = status.files?.[name];
    if (!hash) return NOT_COUNTED;
    const file = load(name, hash);
    return file.data ? (file.data.contests[id] ?? NOT_COUNTED) : undefined;
  },
  /* The contests of area file *name* (data.js `areaName`), id → live
   * entry, for what needs a whole file or all of them (the map's results,
   * mapmode.js): {} where the file is not there, as with nothing counted
   * in its area yet; undefined before counting starts, without results, or
   * while it loads. The names are the keys of `status.files`. */
  contests(name) {
    if (!status || status.phase === 'none') return undefined;
    const hash = status.files?.[name];
    if (!hash) return {};
    return load(name, hash).data?.contests;
  },
  /* The figures by okrsok of area file *name* (`okrsky/<name>` in
   * `status.files`, docs/results.md), only in the final results:
   * {contests: {id: {'<obec>/<n>': [eligible, voters, valid, {number:
   * votes}]}}, past: {'<obec>/<n>': [eligible, voters]}}, `past` the 2022
   * turnout where the okrsok is the same as then. Null where there are
   * none; undefined before counting starts, without results, or while it
   * loads. */
  okrsky(name) {
    if (!status || status.phase === 'none') return undefined;
    const hash = status.files?.[`okrsky/${name}`];
    if (!hash) return null;
    return load(`okrsky/${name}`, hash).data ?? undefined;
  },
  /* Whether area file *name* has figures by okrsok, without fetching
   * them. */
  hasOkrsky(name) {
    return Boolean(status?.files?.[`okrsky/${name}`]);
  },
};

/* The live results, for a component: renders it again whenever they
 * change. */
export function useLive() {
  const [, setTick] = useState(0);
  useEffect(() => {
    const listener = () => setTick((n) => n + 1);
    listeners.add(listener);
    start();
    return () => listeners.delete(listener);
  }, []);
  return live;
}

/* Adds *record* [eligible, voters, valid, {number: votes}] (an area's or
 * an okrsok's, docs/results.md) to the sum under *key* in *sums*. */
export function addRecord(sums, key, [eligible, voters, valid, votes]) {
  const sum = sums.get(key);
  if (!sum) {
    sums.set(key, [eligible, voters, valid, { ...votes }]);
    return;
  }
  sum[0] += eligible;
  sum[1] += voters;
  sum[2] += valid;
  for (const [n, v] of Object.entries(votes)) sum[3][n] = (sum[3][n] ?? 0) + v;
}

/* The council obvod '<obec>/<k>' of every okrsok '<obec>/<n>' of the obce
 * split into several (data/index.json *index*), from *file*, the okrsky of
 * an okres's municipal contests (`live.okrsky('okres/<code>')`): each
 * council obvod's contest has the okrsky it is made of. An obec's okrsky
 * are the same polling districts with the same numbers in every contest,
 * so this groups those of a mayor's, a city's or a regional contest too.
 * Made once per file. */
const councilMaps = new WeakMap();
export function okrsokCouncils(file, index) {
  let councils = councilMaps.get(file);
  if (councils) return councils;
  councils = new Map();
  for (const [id, records] of Object.entries(file.contests)) {
    const [kind, area] = id.split(':');
    const [code, k] = area.split('/');
    if (kind !== 'oz' || !k || !((index.obce[code]?.[4] ?? 0) > 1)) continue;
    for (const key of Object.keys(records)) councils.set(key, area);
  }
  councilMaps.set(file, councils);
  return councils;
}

/* The scopes of a place that a contest's results can be narrowed to, from
 * the coarsest. */
export const SCOPES = ['all', 'obec', 'obvod', 'okrsok'];

/* The figures of counted contest *id* in the units of *place* ({obec,
 * obvod, okrsok}: its obec or city district code, and its council obvod
 * and okrsok where known) that have figures of their own and differ from
 * the contest's whole and from each other, coarsest first: [{scope,
 * record, past}], `scope` one of SCOPES, `record` as in the okrsok files,
 * `past` an okrsok's 2022 municipal turnout [eligible, voters] in a
 * municipal contest where known. The obec of a regional or a city contest
 * (its `areas` entry, else its okrsky together); the council obvod of an
 * obec split into several, of any contest but that obvod's own council
 * (its okrsky together, grouped by `okrsokCouncils`); the okrsok. The
 * okrsok files load as needed (only the final results have them): []
 * without them, or while they load. */
export function placeResults(id, place) {
  const entry = live.of(id);
  if (!entry || entry === NOT_COUNTED || !place?.obec) return [];
  const [kind, area] = id.split(':');
  const code = area.split('/')[0];
  const name = areaName(id, index);
  const file = live.hasOkrsky(name) ? live.okrsky(name) : null;
  const records = file?.contests[id] ?? {};
  const same = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  const whole = [entry.eligible, entry.voters, entry.valid];
  const out = [];
  const push = (scope, record, past = null) => {
    if (record && !same(record, whole) && !out.some((u) => same(u.record, record))) out.push({ scope, record, past });
  };
  const sumOf = (keys) => {
    const sums = new Map();
    for (const key of keys) addRecord(sums, 0, records[key]);
    return sums.get(0);
  };
  const keys = Object.keys(records);
  if (kind === 'predseda' || kind === 'zsk' || code === 'BA' || code === 'KE') {
    // Where the contest has `areas`, an obec missing from them is one whose
    // votes are not known (okrsky of the cities not told apart): none shown.
    push('obec', entry.areas ? entry.areas[place.obec] : sumOf(keys.filter((key) => key.startsWith(`${place.obec}/`))));
  }
  const row = index.obce[place.obec];
  if (place.obvod && (row?.[4] ?? 0) > 1 && !(kind === 'oz' && code === place.obec)) {
    const municipal = `okres/${row[1]}`;
    const councils = live.hasOkrsky(municipal) ? live.okrsky(municipal) : null;
    if (councils) {
      const of = okrsokCouncils(councils, index);
      const target = `${place.obec}/${place.obvod}`;
      push('obvod', sumOf(keys.filter((key) => of.get(key) === target)));
    }
  }
  if (place.okrsok) {
    const key = `${place.obec}/${place.okrsok}`;
    const municipal = kind === 'starosta' || kind === 'oz';
    push('okrsok', records[key], municipal ? (file?.past?.[key] ?? null) : null);
  }
  return out;
}

/* How much the registered voters may have grown since the contest's last
 * election: with that margin on their number then, the voters not counted
 * yet are bounded, and a winner is called only when no number of them that
 * is at all likely could change who wins. */
export const GROWTH = 1.1;

/* The votes not counted yet in a contest at most, one per registered
 * voter of the districts not counted yet: none once every district is
 * counted, else the registered voters at the last election with GROWTH (or
 * those counted, if more) less those of the districts counted; null where
 * either is not known, and then nothing is called. */
function uncounted(contest, r) {
  if (r.counted && r.counted[0] >= r.counted[1]) return { remaining: 0, bound: null };
  if (!contest.past || r.eligible == null) return null;
  const bound = Math.ceil(Math.max(contest.past.eligible * GROWTH, r.eligible));
  return { remaining: bound - r.eligible, bound };
}

/* The ballot numbers sure of one of *seats* seats among *votes* ([number,
 * votes] pairs): those whom fewer than *seats* others could reach (a tie
 * counts as reached) even if every one of the *remaining* votes went to
 * them, as each voter can give each candidate one at most. */
function sure(votes, seats, remaining) {
  const called = new Set();
  for (const [n, v] of votes) {
    const rivals = votes.filter(([m, w]) => m !== n && w + remaining >= v).length;
    if (rivals < seats) called.add(n);
  }
  return called;
}

const SINGLE = new Set(['starosta', 'predseda']);

/* How far a count has got: the share of an area's registered voters
 * (*voters* [of the okrsky counted, of all]) whose okrsky are counted, an
 * okrsok counting whole once it is in, however many of them voted, so that
 * okrsky of every size weigh as they should; under 100 % until every one of
 * them (*units* [counted, all]) is in, the area's voters being an estimate
 * until then. Without the voters, the okrsky's share; null without either. */
export function countShare(voters, units) {
  if (units?.[1] && units[0] >= units[1]) return 1;
  if (voters?.[1]) return Math.min(0.99, voters[0] / voters[1]);
  return units?.[1] ? units[0] / units[1] : null;
}

/* A count's progress (`countShare`) as a percentage: whole points, but
 * tenths below 10 % and never 0 % once anything is counted, since the
 * small places come in first and a count well under way can still be a
 * fraction of a per cent of the voters. */
export function formatProgress(share) {
  if (share > 0 && share < 0.0005) return `< ${formatPercent(0.001, 1)}`;
  return formatPercent(share, share > 0 && share < 0.1 ? 1 : 0);
}

/* The flag of a candidate who withdrew yet stayed on the ballot, whose
 * votes count (docs/results.md). */
const WITHDRAWN = -1;

/* The results of *contest* (data.js `contest`) from its live entry *r*
 * (docs/results.md): {status ('partial', 'winner' or 'final'), counted,
 * eligible, voters, valid, seats, reportedSeats, filled, registered,
 * progress, byNumber: number → {votes, share, elected, called, withdrawn},
 * call}. `reportedSeats`: those the results give, null where they give
 * none. `registered`: the area's registered voters as far as known
 * while counting (those of its last election, or counted if more);
 * `progress` how far the count has got (`countShare`). `called`: decided by
 * this site on a partial count, not yet officially (`call` {remaining,
 * bound} says on what); `share` of the valid ballots, for a council of the
 * voters with a valid ballot. A contest counted with as many seats filled
 * as it has candidates has them all elected (`votes` and `share` null),
 * before ŠÚ SR publishes their votes (on the night of 2026 it published no
 * council's). A candidate who withdrew but is still on the list cannot be
 * elected, so fewer seats are filled and nothing is marked; where the
 * results flag them (`withdrawn`), their votes count among the valid ones
 * and in the shares, but they are never called, nor in the way of a call. */
export function decodeResults(contest, r) {
  const seats = r.seats ?? (SINGLE.has(contest.id.split(':')[0]) ? 1 : (contest.seats ?? contest.seats2022));
  const votes = r.candidates.filter(([, , flag]) => flag !== WITHDRAWN).map(([n, v]) => [n, v]);
  const call = r.status === 'partial' && seats ? uncounted(contest, r) : null;
  const called = call ? sure(votes, seats, call.remaining) : new Set();
  const byNumber = new Map(
    r.candidates.map(([n, v, flag]) => [
      n,
      {
        votes: v,
        share: r.valid ? v / r.valid : null,
        elected: flag === 1,
        called: called.has(n),
        withdrawn: flag === WITHDRAWN,
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
    registered,
    progress: countShare(registered === null ? null : [r.eligible, registered], r.counted),
    byNumber,
    call,
  };
}

/* A time of day in Slovak time on the 24-hour clock, as the count and
 * the polls are announced there, wherever the page is read. */
const slovakTime = (date) =>
  date.toLocaleTimeString(document.documentElement.lang, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: 'Europe/Bratislava',
  });

/* The time of the results as `ems results` last got them from ŠÚ SR (the
 * shorter for the 24-hour clock, so that the status keeps to a line). */
function sourceTime(s) {
  const times = Object.values(s.source ?? {})
    .map((x) => x?.time)
    .filter(Boolean)
    .map((time) => new Date(time))
    .sort((a, b) => a - b);
  const latest = times.at(-1) ?? (s.updated ? new Date(s.updated) : null);
  return latest ? slovakTime(latest) : '';
}

/* The voting under way, under the site's name, from the polls' opening to
 * their closing (config `polls`) and while there are no results yet: a bar
 * of how much of the voting day has gone by, full when the polls close,
 * and when that is. Nothing on it moves or blinks, as nothing on the site
 * changes meanwhile; it is drawn again every minute, so that the bar fills
 * and the line comes when the polls open and goes when they close. From
 * then, once status.json has been *tried* and has nothing counted yet (or
 * cannot be read) and is still polled, a line says that the results are
 * awaited, so that a visitor knows more is coming; not before it is
 * tried, so that a page loaded with the results in does not flash it. */
function VotingStatus({ tried }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!polls) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);
  if (!polls) return null;
  const [open, close] = polls;
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

/* The state of the results under the site's name, in a line where it
 * fits: counting, how far each election has got (of the registered voters
 * whose okrsky are counted, `countShare`; the okrsky and municipalities
 * counted in the tooltip) and the time of the results; nothing once they
 * are final, which goes without saying after the elections. Before
 * counting starts, or without results, the voting while it is under way
 * and the results awaited after it (VotingStatus). */
export function LiveStatus() {
  const results = useLive();
  const s = results.status;
  if (!s || s.phase === 'none') return html`<${VotingStatus} tried=${results.tried} />`;
  if (s.phase === 'final') return null;
  const share = (x) => {
    const value = countShare(x?.voters, x?.counted);
    return value === null ? null : formatProgress(value);
  };
  const parts = [
    share(s.source?.osk) && t('results.status_regional', { share: share(s.source.osk) }),
    share(s.source?.oso) && t('results.status_municipal', { share: share(s.source.oso) }),
  ].filter(Boolean);
  const text = [t('results.status_counting'), ...parts, sourceTime(s)].filter(Boolean).join(' · ');
  const units = (x) => (x?.counted ? `${formatNumber(x.counted[0])}/${formatNumber(x.counted[1])}` : '–');
  const title = `${t('results.status_source')} ${t('results.status_units', { regional: units(s.source?.osk), municipal: units(s.source?.oso) })}`;
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
