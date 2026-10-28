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

/* As election_map_slovakia.candidates.search_key: case, diacritics and
 * punctuation do not matter. */
export function searchKey(text) {
  return text
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
}

/* ---------- places ---------- */

/* Everything about an obec that the ballots need, from its data/index.json
 * row ([name, okres, kraj, zsk, councils, city, cityObvod], the last two
 * only for a city district of Bratislava or Košice). */
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

/* The contest id of candidacy id *candidacyId* (`<contest>#<number>`). */
export const contestOf = (candidacyId) => candidacyId.slice(0, candidacyId.lastIndexOf('#'));

// The regional contests (president and council) are by kraj.
const isRegional = (kind) => kind === 'predseda' || kind === 'zsk';

/* Whether area code *code* is Bratislava or Košice, cities whose districts
 * are municipalities of their own. */
export const isCity = (code) => code === 'BA' || code === 'KE';

/* Whether obec *code* is split into several council obvody
 * (data/index.json *index*). */
export const hasCouncilObvody = (index, code) => (index.obce[code]?.[4] ?? 0) > 1;

/* Orders contest ids the most local first, as a place's ballots and a
 * candidate's candidacies both list them: a municipality's or city
 * district's own, then Bratislava's or Košice's, then the kraj's; of one
 * area the council before the mayor or president. */
function localFirst(a, b) {
  const rank = (id) => {
    const { kind, area } = parseContest(id);
    const level = isRegional(kind) ? 2 : isCity(area) ? 1 : 0;
    return 2 * level + (kind === 'oz' || kind === 'zsk' ? 0 : 1);
  };
  return rank(a) - rank(b);
}

/* What municipal *area* is: 'city' (Bratislava or Košice), 'district' (one
 * of their city districts: an index row naming its city) or 'obec'. */
function placeKind(area, index) {
  if (isCity(area)) return 'city';
  return index.obce[area]?.[5] !== undefined ? 'district' : 'obec';
}

// The labels of the municipal contests and councils by `placeKind`.
const MAYOR_LABEL = { city: 'contest.mayor_city', district: 'contest.mayor_district', obec: 'contest.mayor' };
const COUNCIL_LABEL = { city: 'contest.council_city', district: 'contest.council_district', obec: 'contest.council' };
const COUNCIL_OFFICE = { city: 'office.council_city', district: 'office.council_district', obec: 'office.council' };

/* The area file a contest is in (build.py `area_file`), by name: kraj/<k>,
 * city/<BA|KE> or okres/<code>. The live results (live.js) name theirs
 * alike. */
export function areaName(contest, index) {
  const { kind, area } = parseContest(contest);
  if (isRegional(kind)) return `kraj/${area}`;
  if (isCity(area)) return `city/${area}`;
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

/* How an office was won, from an area file's result row: {votes, valid,
 * voters, eligible, obvod, multi}. `valid` is the valid ballots for the
 * office, for a council (`multi`) the voters with a valid ballot, each of
 * whom could vote for several; `obvod` the obvod number of that election,
 * null for the whole area. */
function decodeResult(body, [votes, valid, voters, eligible, obvod = null]) {
  const { kind } = parseContest(body);
  return { votes, valid, voters, eligible, obvod, multi: kind === 'oz' || kind === 'zsk' };
}

/* A candidate from their row in the contest's *entry* of an area file.
 * `occupation` is in the page's language where translated, the Slovak
 * original then in `occupationSk`; `parties` are {short, name, logo} from
 * the index's party table; `offices` the offices the person holds now,
 * [{body, since, result}]; `research` {date, findings, languages,
 * affairs, disputes} (affairs: how many findings are serious
 * controversies; disputes: how many are disputed or lesser) from the area
 * file's *researched* summaries, null while the person is not researched
 * yet. */
function decodeCandidate(contest, entry, row, translated, index, researched) {
  const [number, titleBefore, firstName, surname, titleAfter, age, occupation, parties, person, residence = null] =
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
    residence,
    offices: (entry.incumbents?.[number] ?? []).map(([body, since, result]) => ({
      body,
      since,
      result: decodeResult(body, result),
    })),
    research: research ? decodeResearch(research) : null,
  };
}

function decodeResearch([date, findings, languages, affairs, disputes]) {
  return { date, findings, languages, affairs, disputes };
}

/* The office a contest elects: its id without the obvod. */
export const officeOf = (contestId) => contestId.split('/')[0];

/* Whether candidate *c* holds now the office their contest elects. */
export const inOffice = (c) => c.offices.some((o) => o.body === officeOf(c.contest));

export function officeLabel(body, index) {
  const { kind, area } = parseContest(body);
  if (kind === 'starosta' || kind === 'predseda') return contestLabel(body, index);
  if (kind === 'zsk') return t('office.regional_council', { kraj: index.kraje[area] });
  return t(COUNCIL_OFFICE[placeKind(area, index)], { name: index.obce[area]?.[0] });
}

export function displayName(c) {
  const name = [c.titleBefore, c.firstName, c.surname].filter(Boolean).join(' ');
  return c.titleAfter ? `${name}, ${c.titleAfter}` : name;
}

export const displayParties = (c) =>
  c.parties.length ? c.parties.map((p) => p.name).join(', ') : t('candidate.independent');

export function contestLabel(id, index) {
  const { kind, area, obvod } = parseContest(id);
  const name = index.obce[area]?.[0];
  const kraj = index.kraje[area];
  switch (kind) {
    case 'starosta':
      return t(MAYOR_LABEL[placeKind(area, index)], { name });
    case 'oz':
      return t(COUNCIL_LABEL[placeKind(area, index)], { name, n: obvod });
    case 'predseda':
      return t('contest.president', { kraj });
    default:
      return t('contest.regional_council', { kraj, n: obvod });
  }
}

/* The mayor or president in office, from the entry's `holder`: {name,
 * since, number, result}, `number` their ballot number, null when not
 * standing. */
function decodeHolder(office, [name, since, number, result]) {
  return { name, since, number, result: decodeResult(office, result) };
}

/* The turnout of the last election of the contest's body, from the entry's
 * `past`: {election, date, eligible, voters, whole, okrsky}, `election` the
 * results name (oso2022, osk2022, oso202303, …), `whole` set when the
 * figures are of the whole municipality or city rather than this council
 * obvod, `okrsky` the numbers of the okrsky they are summed over where they
 * are this obvod's (else null). */
function decodePast([election, date, eligible, voters, scope]) {
  return { election, date, eligible, voters, whole: scope === 1, okrsky: Array.isArray(scope) ? scope : null };
}

/* Contest *id* from its area file; `holder` and `past` (see above) are null
 * where not known. */
async function contest(id, index) {
  const [file, translated] = await Promise.all([getJSON(areaPath(id, index)), occupations()]);
  const entry = file.contests[id] ?? { candidates: [] };
  return {
    id,
    label: contestLabel(id, index),
    seats: entry.seats ?? null,
    seats2022: entry.seats_2022 ?? null,
    sources: entry.sources ?? [],
    holder: entry.holder ? decodeHolder(officeOf(id), entry.holder) : null,
    past: entry.past ? decodePast(entry.past) : null,
    candidates: entry.candidates.map((row) => decodeCandidate(id, entry, row, translated, index, file.research)),
  };
}

/* The contests *ids* (as in `ballots`), leaving out an id whose area is not
 * known (from a link made by hand, say). */
export async function contests(ids) {
  const index = await dataIndex();
  const known = ids.filter((id) => {
    const { kind, area } = parseContest(id);
    return isRegional(kind) ? area in index.kraje : area in index.obce;
  });
  return Promise.all(known.map((id) => contest(id, index)));
}

/* The council contests on the ballots of *obec* and how they were chosen
 * (`council`, see `ballots`): its one council, obvod *obvod*'s, or every
 * obvod's. */
function councilContests(obec, obvod, byAddress) {
  const id = (n) => `oz:${obec.code}/${n}`;
  if (obec.councils === 1) return { council: 'single', ids: [id(1)] };
  if (obvod) return { council: 'address', ids: [id(obvod)] };
  if (obec.councils > 1) {
    const ids = Array.from({ length: obec.councils }, (_, i) => id(i + 1));
    return { council: byAddress ? 'choose' : 'pending', ids };
  }
  return { council: 'none', ids: [] };
}

/* Every contest a voter in obec *code* votes in, the most local first
 * (`localFirst`), so that what heads the list changes with the place
 * clicked: municipal council, mayor, in Bratislava and Košice the city
 * council and mayor, then regional council and president. *where* narrows
 * the council where the obec has several obvody: {obvod} of an address or a
 * point, or {street, part} chosen in the search, whose houses may all be in
 * one.
 *
 * Null for an unknown obec, else {obec, council, obvod, estimated,
 * contests, group}:
 * - `contests`: as `contests` gives them, the council ones with `council`;
 * - `council`: 'single' (one obvod), 'address' (several, the place's known:
 *   `obvod`), 'choose' (several, known by address, but no address chosen),
 *   'pending' (several, not known by address yet) or 'none'; without an
 *   obvod every council obvod is listed;
 * - `estimated`: the obec has not published which addresses are in which
 *   obvod, so they are a guess;
 * - `group`: the council obvody and okrsky of the houses of the street or
 *   part chosen (`groupUnits`). */
export async function ballots(code, where = {}) {
  const index = await dataIndex();
  const obec = await obecInfo(code);
  if (!obec) return null;
  const byAddress = index.by_address.includes(obec.code);
  const group = await groupUnits(code, where);
  const one = group.obvody.length === 1 ? group.obvody[0] : null;
  const obvod = obec.councils > 1 && byAddress ? (where.obvod ?? one) : null;
  const { council, ids: councilIds } = councilContests(obec, obvod, byAddress);
  const ids = [...councilIds, `starosta:${obec.code}`];
  if (obec.city) ids.push(`oz:${obec.city}/${obec.cityObvod}`, `starosta:${obec.city}`);
  ids.push(`zsk:${obec.kraj}/${obec.zsk}`, `predseda:${obec.kraj}`);
  const contests = await Promise.all(ids.map((id) => contest(id, index)));
  for (const c of contests) if (councilIds.includes(c.id)) c.council = council;
  return { obec, council, obvod, estimated: index.estimated.includes(obec.code), contests, group };
}

/* The council obvody and the okrsky of the houses of the street or part
 * *where* names in obec *code*, as the address file gives them (files.js
 * `addressFile`), each in order: {obvody, okrsky}, empty where it gives
 * none or none is named. */
async function groupUnits(code, { street, part }) {
  const name = street ?? part;
  if (!name) return { obvody: [], okrsky: [] };
  const kind = street ? 'streets' : 'parts';
  const group = (await addressFile(code)).groups.find((g) => g.kind === kind && g.name === name);
  const numbers = (values) =>
    [...new Set((values ?? []).filter((v) => v != null).map(Number))].sort((a, b) => a - b);
  return { obvody: numbers(group?.obvody), okrsky: numbers(group?.okrsky) };
}

/* A candidacy and every candidacy of the same person, the most local first
 * (`localFirst`), each with its whole contest (as in `ballots`):
 * {candidate, candidacies: [{candidate, contest}]}, `candidate` there one of
 * `contest.candidates`. */
export async function person(candidacyId) {
  const index = await dataIndex();
  const contestId = contestOf(candidacyId);
  const [file, translated] = await Promise.all([getJSON(areaPath(contestId, index)), occupations()]);
  const entry = file.contests[contestId];
  const row = entry?.candidates.find((r) => `${contestId}#${r[0]}` === candidacyId);
  if (!row) return null;
  const candidate = decodeCandidate(contestId, entry, row, translated, index, file.research);
  const ids = [...(file.persons[candidate.person] ?? [candidacyId])].sort((a, b) => localFirst(contestOf(a), contestOf(b)));
  const candidacies = await Promise.all(
    ids.map(async (id) => {
      const whole = await contest(contestOf(id), index);
      return { candidate: whole.candidates.find((x) => x.id === id), contest: whole };
    }),
  );
  return { candidate, candidacies };
}

/* What research found on candidate *c*, from data/research/<lang>/<area>.json
 * beside the candidate's area file: [{kind ('cv', 'affair' or 'dispute'),
 * claim (in the page's language, else English), quote (as written, in
 * `language`), quoteTranslated (machine translation into the page's
 * language, or null), url, title, published (or ''), cache (the sha256 of
 * the cached copy), category, language}]. The file lists only persons with
 * findings and exists only where there are some. */
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

/* Where a contest is voted, for fitting the map to it (map.js `fitArea`):
 * {obec, obvod} for a municipal contest (`obvod` the council obvod where
 * the obec has several), else {area}: for a Bratislava or Košice city
 * contest 'BA' the city, 'BA/3' a city council obvod; for a regional one
 * 'kraj:1' the kraj (its president), 'kraj:1/3' its regional council
 * obvod. */
export function contestArea(id, index) {
  const { kind, area, obvod } = parseContest(id);
  if (kind === 'predseda') return { area: `kraj:${area}` };
  if (kind === 'zsk') return { area: `kraj:${area}/${obvod}` };
  if (isCity(area)) return { area: kind === 'oz' ? `${area}/${obvod}` : area };
  return { obec: area, obvod: kind === 'oz' && hasCouncilObvody(index, area) ? obvod : null };
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
    const prefix = w.slice(0, 2);
    const size = index.names[prefix];
    if (size === undefined) return [];
    if (best === null || size < index.names[best]) best = prefix;
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
