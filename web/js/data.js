/* Loading the site's data files and answering questions about them.
 *
 * File layouts are described in src/election_map_slovakia/build.py (data/).
 * Everything is fetched on demand and kept in small LRU caches (files.js),
 * so a long session does not accumulate the whole country in memory.
 */

import { useEffect, useState } from '../vendor/preact-htm.module.js';
import { addressFile, Cache, fetchJSON } from './files.js';
import { hasOccupations, lang, t } from './i18n.js';

const files = new Cache(24);
export const getJSON = (path) => files.get(path, fetchJSON);

/* For components: what *load()* resolves to, as [value, failed], value
 * undefined while it loads. Loads again when *deps* change; a result that
 * comes after that is dropped. */
export function useLoaded(load, deps) {
  const [state, setState] = useState([undefined, false]);
  useEffect(() => {
    let live = true;
    setState([undefined, false]);
    load().then(
      (value) => live && setState([value, false]),
      (e) => {
        console.error(e);
        if (live) setState([undefined, true]);
      },
    );
    return () => {
      live = false;
    };
  }, deps);
  return state;
}

export const dataIndex = () => getJSON('/data/index.json');

/* Same as election_map_slovakia.candidates.search_key: case, diacritics and punctuation
 * do not matter. */
export function searchKey(text) {
  return text
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
}

/* ---------- places ---------- */

/* Everything about an obec that the ballots need, from data/index.json. */
export async function obecInfo(code) {
  const index = await dataIndex();
  const row = index.obce[code];
  if (!row) return null;
  const [name, okres, kraj, zsk, councils, city, cityObvod] = row;
  return {
    code,
    name,
    okres,
    okresName: index.okresy[okres]?.[0] ?? '',
    kraj,
    krajName: index.kraje[kraj],
    zsk,
    councils,
    city,
    cityObvod,
  };
}

/* ---------- contests and candidates ---------- */

function parseContest(id) {
  const [kind, area] = id.split(':');
  const [code, obvod] = area.split('/');
  return { kind, area: code, obvod: obvod ? Number(obvod) : null };
}

function parseCandidacy(id) {
  const hash = id.lastIndexOf('#');
  return { contest: id.slice(0, hash), number: Number(id.slice(hash + 1)) };
}

/* The area file a contest is in (build.py `area_file`), by name: kraj/<k>,
 * city/<BA|KE> or okres/<code>. The live results (live.js) name theirs
 * alike. */
export function areaName(contest, index) {
  const { kind, area } = parseContest(contest);
  if (kind === 'predseda' || kind === 'zsk') return `kraj/${area}`;
  if (area === 'BA' || area === 'KE') return `city/${area}`;
  return `okres/${index.obce[area][1]}`;
}

const areaPath = (contest, index) => `/data/${areaName(contest, index)}.json`;

/* Slovak occupation → its translation into the page's language, from
 * /i18n/<lang>/occupations.json, fetched once with the first candidates;
 * empty where there is none (Slovak, or nothing translated yet). */
let occupationMap = null;
function occupations() {
  if (!hasOccupations()) return Promise.resolve({});
  occupationMap ??= fetchJSON(`/i18n/${lang}/occupations.json`).catch((e) => {
    occupationMap = null;
    throw e;
  });
  return occupationMap;
}

/* How an office was won (build.py `result`): {votes, valid, voters,
 * eligible, obvod, multi}, `valid` the valid ballots for the office — for a
 * council (`multi`) the voters with a valid ballot, each of whom could vote
 * for several — `obvod` the obvod number of that election or null for the
 * whole area. */
function decodeResult(body, [votes, valid, voters, eligible, obvod = null]) {
  const { kind } = parseContest(body);
  return { votes, valid, voters, eligible, obvod, multi: kind === 'oz' || kind === 'zsk' };
}

/* `occupation` is in the page's language where translated, the Slovak
 * original then in `occupationSk`; `parties` are {short, name, logo} from
 * the index's party table; `offices` the offices the person holds now,
 * [{body, since, result}], from the *entry* of the contest in its area file;
 * `research` {date, findings, languages, affairs, disputes} (how many of
 * the findings are serious controversies, how many disputed or lesser
 * ones) from the area file's *researched* summaries, null while the
 * person is not researched yet. */
function decodeCandidate(contest, entry, row, translated, index, researched) {
  const [number, titleBefore, firstName, surname, titleAfter, age, occupation, parties, person] =
    row;
  const known = Object.hasOwn(translated, occupation);
  const research = researched?.[person];
  return {
    id: `${contest}#${number}`,
    contest,
    number,
    titleBefore,
    firstName,
    surname,
    titleAfter,
    age,
    occupation: known ? translated[occupation] : occupation,
    occupationSk: known ? occupation : null,
    parties: parties.map((p) => {
      const [short, name, logo = null] = index.parties[p];
      return { short, name, logo };
    }),
    person,
    residence: row[9] ?? null,
    offices: (entry.incumbents?.[number] ?? []).map(([body, since, result]) => ({
      body,
      since,
      result: decodeResult(body, result),
    })),
    research: research
      ? {
          date: research[0],
          findings: research[1],
          languages: research[2],
          affairs: research[3],
          disputes: research[4],
        }
      : null,
  };
}

/* The office a contest elects: its id without the obvod. */
export const officeOf = (contestId) => contestId.split('/')[0];

/* Whether candidate *c* holds now the office their contest elects. */
export const inOffice = (c) => c.offices.some((o) => o.body === officeOf(c.contest));

export function officeLabel(body, index) {
  const { kind, area } = parseContest(body);
  if (kind === 'starosta' || kind === 'predseda') return contestLabel(body, index);
  if (kind === 'zsk') return t('office.regional_council', { kraj: index.kraje[area] });
  const obec = index.obce[area];
  const key =
    area === 'BA' || area === 'KE' ? 'office.council_city' : obec?.[5] !== undefined ? 'office.council_district' : 'office.council';
  return t(key, { name: obec?.[0] });
}

export function displayName(c) {
  const name = [c.titleBefore, c.firstName, c.surname].filter(Boolean).join(' ');
  return c.titleAfter ? `${name}, ${c.titleAfter}` : name;
}

export const displayParties = (c) =>
  c.parties.length ? c.parties.map((p) => p.name).join(', ') : t('candidate.independent');

export function contestLabel(id, index) {
  const { kind, area, obvod } = parseContest(id);
  const obec = index.obce[area];
  const name = obec?.[0];
  const district = obec?.[5] !== undefined;
  const city = area === 'BA' || area === 'KE';
  const kraj = index.kraje[area];
  switch (kind) {
    case 'starosta':
      return t(
        city ? 'contest.mayor_city' : district ? 'contest.mayor_district' : 'contest.mayor',
        { name },
      );
    case 'oz':
      return t(
        city ? 'contest.council_city' : district ? 'contest.council_district' : 'contest.council',
        { name, n: obvod },
      );
    case 'predseda':
      return t('contest.president', { kraj });
    default:
      return t('contest.regional_council', { kraj, n: obvod });
  }
}

/* `past` is the turnout of the last election of the contest's body (build.py
 * `past`): {election, date, eligible, voters, whole}, `election` the results
 * name (oso2022, osk2022, oso202303, …), `whole` set when the figures are of
 * the whole municipality or city rather than this council obvod; null when
 * not known. */
async function contest(id, index) {
  const [file, translated] = await Promise.all([getJSON(areaPath(id, index)), occupations()]);
  const entry = file.contests[id] ?? { candidates: [] };
  const holder = entry.holder
    ? {
        name: entry.holder[0],
        since: entry.holder[1],
        number: entry.holder[2],
        result: decodeResult(officeOf(id), entry.holder[3]),
      }
    : null;
  return {
    id,
    label: contestLabel(id, index),
    seats: entry.seats ?? null,
    seats2022: entry.seats_2022 ?? null,
    sources: entry.sources ?? [],
    holder,
    past: entry.past
      ? {
          election: entry.past[0],
          date: entry.past[1],
          eligible: entry.past[2],
          voters: entry.past[3],
          whole: entry.past[4] === 1,
        }
      : null,
    candidates: entry.candidates.map((row) => decodeCandidate(id, entry, row, translated, index, file.research)),
  };
}

/* The contests *ids* (as in `ballots`), leaving out an id whose area is not
 * known (from a link made by hand, say). */
export async function contests(ids) {
  const index = await dataIndex();
  const known = ids.filter((id) => {
    const { kind, area } = parseContest(id);
    return kind === 'predseda' || kind === 'zsk' ? area in index.kraje : area in index.obce;
  });
  return Promise.all(known.map((id) => contest(id, index)));
}

/* Every contest a voter in obec *code* votes in, the most local first, so
 * that clicking around the map what heads the list changes with the place:
 * municipal council, mayor, then in Bratislava and Košice city council and
 * mayor of the city, then regional council and regional president. *where*
 * narrows the
 * council where the obec has several obvody: {obvod} of an address or a
 * point, or {street, part} chosen in the search, whose houses may all be in
 * one obvod.
 *
 * Returns {obec, contests: [{id, label, seats, seats2022, sources, holder, past, candidates,
 * council?}], council, obvod, estimated}: `holder` the mayor or president in office
 * ({name, since, number, won}, `number` null when not standing in the contest);
 * `council` 'single' (one obvod), 'address' (several, and
 * the place's is known: `obvod`), 'choose' (several, known by address, but
 * no address chosen), 'pending' (several, not known by address yet) or
 * 'none'. Without an obvod every council obvod is listed, with `council`
 * set. `estimated`: the obec has not published which addresses are in which
 * obvod, so they are a guess. */
export async function ballots(code, where = {}) {
  const index = await dataIndex();
  const obec = await obecInfo(code);
  if (!obec) return null;
  let council = 'none';
  const councilIds = [];
  const byAddress = index.by_address.includes(obec.code);
  const obvod = obec.councils > 1 && byAddress ? (where.obvod ?? (await groupObvod(code, where))) : null;
  if (obec.councils === 1) {
    council = 'single';
    councilIds.push(`oz:${obec.code}/1`);
  } else if (obvod) {
    council = 'address';
    councilIds.push(`oz:${obec.code}/${obvod}`);
  } else if (obec.councils > 1) {
    council = byAddress ? 'choose' : 'pending';
    for (let n = 1; n <= obec.councils; n++) councilIds.push(`oz:${obec.code}/${n}`);
  }
  const ids = [...councilIds, `starosta:${obec.code}`];
  if (obec.city) ids.push(`oz:${obec.city}/${obec.cityObvod}`, `starosta:${obec.city}`);
  ids.push(`zsk:${obec.kraj}/${obec.zsk}`, `predseda:${obec.kraj}`);
  const contests = await Promise.all(ids.map((id) => contest(id, index)));
  for (const c of contests) if (councilIds.includes(c.id)) c.council = council;
  return { obec, council, obvod, estimated: index.estimated.includes(obec.code), contests };
}

/* The council obvod of all the houses of the street or part *where* names
 * in obec *code*, or null if they are in several (or none is named). */
async function groupObvod(code, { street, part }) {
  const name = street ?? part;
  if (!name) return null;
  const kind = street ? 'streets' : 'parts';
  const group = (await addressFile(code)).groups.find((g) => g.kind === kind && g.name === name);
  const obvody = new Set(group?.obvody ?? []);
  return obvody.size === 1 ? [...obvody][0] : null;
}

/* A candidacy and every candidacy of the same person, each with its whole
 * contest (as in `ballots`): {candidate, candidacies: [{candidate,
 * contest}]}, `candidate` there one of `contest.candidates`. */
export async function person(candidacyId) {
  const index = await dataIndex();
  const { contest: contestId } = parseCandidacy(candidacyId);
  const [file, translated] = await Promise.all([getJSON(areaPath(contestId, index)), occupations()]);
  const entry = file.contests[contestId];
  const row = entry?.candidates.find((r) => `${contestId}#${r[0]}` === candidacyId);
  if (!row) return null;
  const candidate = decodeCandidate(contestId, entry, row, translated, index, file.research);
  const ids = file.persons[candidate.person] ?? [candidacyId];
  const candidacies = await Promise.all(
    ids.map(async (id) => {
      const whole = await contest(parseCandidacy(id).contest, index);
      return { candidate: whole.candidates.find((x) => x.id === id), contest: whole };
    }),
  );
  return { candidate, candidacies };
}

/* What research found on candidate *c*, from data/research/<lang>/<area>.json
 * beside the candidate's area file: [{kind ('cv', 'affair' or 'dispute'),
 * claim (in the page's language, else English), quote (as written in the
 * page's `language`), quoteTranslated (machine translation into the page's
 * language, or null), url, title, published (or ''), cache (the sha256 of
 * the cached copy), category}]. The file lists only persons with findings
 * and exists only where there are some. */
export async function findings(c) {
  const index = await dataIndex();
  const path = areaPath(c.contest, index).replace('/data/', `/data/research/${lang}/`);
  const file = await files.get(path, (p) => fetchJSON(p, {}));
  return (file[c.person] ?? []).map(
    ([kind, claim, quote, quoteTranslated, url, title, published, cache, category, language]) => ({
      kind,
      claim,
      quote,
      quoteTranslated,
      url,
      title,
      published,
      cache,
      category,
      language,
    }),
  );
}

/* Where a contest is voted, for showing it on the map, with what it is
 * (the key of its card.map_* string): {obec, obvod} for a municipal contest
 * (`obvod` the council obvod where the obec has several), else {area}
 * (app.js `r`): for a Bratislava or Košice city contest 'BA' the city,
 * 'BA/3' a city council obvod; for a regional one 'kraj:1' the kraj (its
 * president), 'kraj:1/3' its regional council obvod. */
export function contestArea(id, index) {
  const { kind, area, obvod } = parseContest(id);
  if (kind === 'predseda') return { area: `kraj:${area}`, what: 'kraj' };
  if (kind === 'zsk') return { area: `kraj:${area}/${obvod}`, what: 'obvod' };
  if (area === 'BA' || area === 'KE') {
    return kind === 'oz' ? { area: `${area}/${obvod}`, what: 'obvod' } : { area, what: 'city' };
  }
  const row = index.obce[area];
  const several = kind === 'oz' && (row?.[4] ?? 0) > 1;
  return {
    obec: area,
    obvod: several ? obvod : null,
    what: several ? 'obvod' : row?.[5] !== undefined ? 'district' : 'obec',
  };
}

/* ---------- candidate-name search ---------- */

const shards = new Cache(6);

/* Persons whose name words start with every word of *key*, at most *limit*.
 * Loads the smallest name shard among the query's two-letter prefixes. */
export async function findPersons(key, limit) {
  const words = key.split(' ').filter(Boolean);
  const index = await dataIndex();
  let best = null;
  for (const w of words) {
    if (w.length < 2) continue;
    const n = index.names[w.slice(0, 2)];
    if (n === undefined) return [];
    if (best === null || n < index.names[best]) best = w.slice(0, 2);
  }
  if (best === null) return [];
  const rows = await shards.get(best, (p) =>
    fetchJSON(`/data/names/${p}.json`).then((list) =>
      list.map(([name, age, candidacies]) => ({
        words: searchKey(name).split(' '),
        name,
        age,
        candidacies,
      })),
    ),
  );
  const out = [];
  for (const row of rows) {
    if (words.every((w) => row.words.some((p) => p.startsWith(w)))) {
      out.push(row);
      if (out.length >= limit) break;
    }
  }
  return out;
}
