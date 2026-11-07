/* Loading the site's data files and answering questions about them.
 *
 * File layouts are described in src/election_map_slovakia/bundle.py.
 * Everything is fetched on demand and kept in small LRU caches (files.js),
 * so a long session does not accumulate the whole country in memory.
 */

import { useEffect, useState } from '../vendor/preact-htm.module.js';
import { addressFile, Cache, fetchJSON } from './files.js';
import { election, elections, formatShortDate, hasOccupations, lang, logoUrl, rounds, t } from './i18n.js';
import {
  areaName,
  COUNTRY,
  contestOf,
  electionKind,
  electionLabel,
  holds,
  isByElection,
  isCity,
  isCouncil,
  isCountry,
  isList,
  isNational,
  isRegional,
  officeOf,
  parseContest,
} from './kinds.js';

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

/* Whether obec *code* is split into several council obvody
 * (data/index.json *index*). */
export const hasCouncilObvody = (index, code) => (index.obce[code]?.[4] ?? 0) > 1;

/* Whether some obec of data/index.json *index* elects a regional council
 * (`regional`: a zsk obvod), Bratislava's or Košice's council (`city`: a
 * row naming its city) or a municipal council (`municipal`: councils).
 * Before 2022 the municipal elections (with the cities') and the regional
 * ones were held apart, each election holding only its own, so what the
 * map offers of them (map.js `overlaysHere`, mapmode.js `turnoutChoices`)
 * goes by this, not by the kind of election. A by-election's rows say
 * less (a mayor's alone has no council): it goes by `held`. */
const ELECTS = {
  regional: (row) => row[3] > 0,
  city: (row) => row[5] !== undefined,
  municipal: (row) => (row[4] ?? 0) > 0,
};
export const electsAnywhere = (index, election) => Object.values(index.obce).some(ELECTS[election]);

/* The obce where by-election *index* (data/index.json) elects something
 * (`held`), by code, each with the contests held there: an obec's or city
 * district's own, Bratislava's or Košice's for all their districts, a
 * kraj's for all its obce. Null for an election other than a by-election. */
export function heldObce(index) {
  if (!index.held) return null;
  const obce = new Map();
  const add = (code, ids) => obce.set(code, [...(obce.get(code) ?? []), ...ids]);
  for (const [area, ids] of Object.entries(index.held)) {
    if (index.obce[area]) add(area, ids);
    else for (const [code, row] of Object.entries(index.obce)) if (row[2] === area || row[5] === area) add(code, ids);
  }
  return obce;
}

/* Orders contest ids the most local first, as a place's ballots and a
 * candidate's candidacies both list them: a municipality's or city
 * district's own, then Bratislava's or Košice's, then the kraj's; of one
 * area the council before the mayor or president; the country's last,
 * in `countryOrder`. */
function localFirst(a, b) {
  const rank = (id) => {
    if (isCountry(id)) return 6;
    const level = isRegional(id) ? 2 : isCity(parseContest(id).area) ? 1 : 0;
    return 2 * level + (isCouncil(id) ? 0 : 1);
  };
  return rank(a) - rank(b) || (isCountry(a) && isCountry(b) ? countryOrder(a, b) : 0);
}

/* Orders country-wide contest ids as the ballots list them: the latest
 * round of a presidential election first, it being the one that decides;
 * the questions of a referendum in their order; a party's list after its
 * party contest. */
function countryOrder(a, b) {
  const x = parseContest(a);
  const y = parseContest(b);
  if (x.kind === 'prezident' && y.kind === 'prezident') return y.sub - x.sub;
  return (x.sub ?? 0) - (y.sub ?? 0);
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

const areaPath = (contest, index) => `/data/${areaName(contest, index)}.json`;

/* Slovak occupation → its translation into the page's language, from the
 * election's bundle, i18n/<lang>.json, fetched once with the first
 * candidates; empty where there is none (Slovak). */
let occupationMap = null;
function occupations() {
  if (!hasOccupations()) return Promise.resolve({});
  occupationMap ??= fetchJSON(`/i18n/${lang}.json`).then(
    (file) => file.occupations,
    (e) => {
      occupationMap = null;
      throw e;
    },
  );
  return occupationMap;
}

/* How an office was won, from an area file's result row: {votes, valid,
 * voters, eligible, obvod, multi}. `valid` is the valid ballots for the
 * office, for a council (`multi`) the voters with a valid ballot, each of
 * whom could vote for several; `obvod` the obvod number of that election,
 * null for the whole area. */
function decodeResult(body, [votes, valid, voters, eligible, obvod = null]) {
  return { votes, valid, voters, eligible, obvod, multi: isCouncil(body) };
}

/* Party *key* (config/parties.toml) as the index's party table gives it:
 * {key, short, name, logo}. */
function partyOf(key, index) {
  const [short, name, logo = null] = index.parties[key];
  return { key, short, name, logo: logo && logoUrl(logo) };
}

/* A person standing in a contest, from their row in the contest's *entry*
 * of area file *file*: `type` 'person'.
 * `age` is null and `occupation` empty where the lists do not give them;
 * `occupation` is in the page's language where translated, the Slovak
 * original then in `occupationSk`; `parties` are {key, short, name, logo}
 * from the index's party table (a list person's: the list's party, a
 * presidential candidate's none); `residence` the obec code of a regional
 * or country-wide candidate's residence where known, `residenceName` its
 * name (or the name as written, where it names no one obec); `offices` the
 * offices the person held at the time of the election,
 * [{body, since, result}]; `research` {date, findings, languages,
 * affairs, disputes, reused, undated} (affairs: how many findings are
 * serious controversies; disputes: how many are disputed or lesser;
 * reused: the research of the latest election's person linked to them, cut
 * to the findings published before this election's day, undated then how
 * many were left out for want of a date) from the file's summaries, null
 * while the person is not researched yet; `elsewhere` the person's
 * candidacies in other elections, by slug (`decodeElsewhere`). */
function decodeCandidate(contest, entry, row, translated, index, file) {
  const [number, titleBefore, firstName, surname, titleAfter, age, occupation, parties, person, residence = null] =
    row;
  const known = Object.hasOwn(translated, occupation);
  const research = file.research?.[person];
  const code = residence && index.obce[residence] ? residence : null;
  return {
    id: `${contest}#${number}`,
    contest,
    number,
    type: 'person',
    titleBefore,
    firstName,
    surname,
    titleAfter,
    age,
    occupation: known ? translated[occupation] : occupation,
    occupationSk: known ? occupation : null,
    parties: parties.map((p) => partyOf(p, index)),
    person,
    residence: code,
    residenceName: code ? index.obce[code][0] : residence,
    offices: (entry.incumbents?.[number] ?? []).map(([body, since, result]) => ({
      body,
      since,
      result: decodeResult(body, result),
    })),
    research: research ? decodeResearch(research) : null,
    elsewhere: decodeElsewhere(file.elsewhere?.[person] ?? {}, index),
  };
}

function decodeResearch([date, findings, languages, affairs, disputes, undated]) {
  return { date, findings, languages, affairs, disputes, reused: undated !== undefined, undated: undated ?? 0 };
}

/* What every candidate has, for one that is no person: no office, no
 * research, no other candidacy. */
const NOT_A_PERSON = { offices: [], research: null, elsewhere: {} };

/* A party on a party-list ballot (`nrsr:SK`), from its row of the entry's
 * `subjects`: `type` 'party', its ballot `number`, `party` (as `partyOf`),
 * `size` (the candidates on its list), `threshold` (the share of the valid
 * votes in % it needs for seats) and `withdrawn`; `parties` itself, so that
 * the party filter takes it like a candidate. `listResearch` is the entry's
 * precomputed `research` totals over its list's candidates, `{researched,
 * findings, affairs, disputes}`, or null where none is researched; not
 * `research`, which the research filters and cards read as a person's. */
function decodeSubject(contest, [number, key, size, threshold, withdrawn = 0], index, totals) {
  const party = partyOf(key, index);
  const r = totals?.[number];
  return {
    ...NOT_A_PERSON,
    id: `${contest}#${number}`,
    contest,
    number,
    type: 'party',
    party,
    parties: [party],
    size,
    threshold,
    withdrawn: Boolean(withdrawn),
    listResearch: r ? { researched: r[0], findings: r[1], affairs: r[2], disputes: r[3] } : null,
  };
}

/* The answers to a referendum question, its candidates: `type` 'answer',
 * number 1 `yes`, 2 `no` (`answer`). */
const answers = (contest) =>
  ['yes', 'no'].map((answer, i) => ({
    ...NOT_A_PERSON,
    id: `${contest}#${i + 1}`,
    contest,
    number: i + 1,
    type: 'answer',
    answer,
    parties: [],
  }));

/* What a row names candidate *c* by: a person's name, a party's short
 * form, an answer's word. */
export function candidateName(c) {
  if (c.type === 'party') return c.party.short;
  if (c.type === 'answer') return t(`referendum.${c.answer}`);
  return displayName(c);
}

/* The candidacies of a person in other elections, from the area file's
 * `elsewhere` entry: slug → [{id, contest, label, votes, valid, rank, of,
 * elected, withdrew, multi}], the numbers null where that election's
 * results are not final or the contest has none; `votes` and `rank` alone
 * where they are not published (a by-election of 2019–2022 published the
 * elected councillors' only). `label` names the contest
 * as this election's index does (the municipalities and kraje are the same
 * then), without what only this election's files know (a round's day, a
 * list's party). */
function decodeElsewhere(bySlug, index) {
  return Object.fromEntries(
    Object.entries(bySlug).map(([slug, rows]) => [
      slug,
      rows.map(([id, votes = null, valid = null, rank = null, of = null, flag = null]) => {
        const contest = contestOf(id);
        return {
          id,
          contest,
          label: contestLabel(contest, index, { day: null }),
          votes,
          valid,
          rank,
          of,
          elected: flag === 1,
          withdrew: flag === -1,
          multi: isCouncil(contest),
        };
      }),
    ]),
  );
}

/* Every election other than the page's, newest first, as {day, slug}. */
export const otherElections = elections.filter((e) => e.day !== election);

/* The newest regular election, whose candidates the research is done on;
 * an earlier one's are given that of the person linked to them
 * (`reused`). */
export const latestElection = elections.find((e) => e.kind === 'municipal-regional');

/* The election before the page's for contest *id*: the next older the site
 * shows of the same kind that holds contests like it (kinds.js `holds`),
 * or null. */
export const electionBefore = (id) =>
  elections
    .slice(elections.findIndex((e) => e.day === election) + 1)
    .find((e) => e.kind === electionKind && holds(e.label, id)) ?? null;

/* The page of candidacy *id* in the election of *slug*, opening its card. */
export const candidacyUrl = (slug, id) => `/${lang}/${slug}/#c=${id.replace('#', '%23')}`;

/* The candidacy of candidate *c*'s person in the election of *slug* that
 * stands for theirs: the one for the same office (body) if there is one,
 * else their first there; null where the person is not linked to anyone
 * there. */
export function linkedCandidacy(c, slug) {
  const there = c.elsewhere[slug];
  if (!there) return null;
  return there.find((x) => officeOf(x.contest) === officeOf(c.contest)) ?? there[0];
}

/* How candidate *c* fared for the same office at the election before
 * (`electionBefore` of their contest): their candidacy there
 * (`decodeElsewhere`) with `election` {day, slug}; null where they did not
 * stand for it then (as far as the persons are linked). */
export function ranBefore(c) {
  const before = electionBefore(c.contest);
  if (!before) return null;
  const there = linkedCandidacy(c, before.slug);
  return there && officeOf(there.contest) === officeOf(c.contest) ? { ...there, election: before } : null;
}

/* Whether candidate *c* held the office their contest elects at the time
 * of the election. */
export const inOffice = (c) => c.offices.some((o) => o.body === officeOf(c.contest));

export function officeLabel(body, index) {
  const { kind, area } = parseContest(body);
  if (kind === 'zsk') return t('office.regional_council', { kraj: index.kraje[area] });
  if (kind === 'oz') return t(COUNCIL_OFFICE[placeKind(area, index)], { name: index.obce[area]?.[0] });
  return contestLabel(body, index);
}

export function displayName(c) {
  const name = [c.titleBefore, c.firstName, c.surname].filter(Boolean).join(' ');
  return c.titleAfter ? `${name}, ${c.titleAfter}` : name;
}

export const displayParties = (c) =>
  c.parties.length ? c.parties.map((p) => p.name).join(', ') : t('candidate.independent');

/* The day of round *n* of the page's presidential election, or null. */
const roundDay = (n) => rounds?.[n - 1]?.[0] ?? null;

/* The name of contest *id*: of a municipality, city district, city or kraj
 * as data/index.json *index* names them; a presidential round with its
 * *day* (by default the page's election's), a referendum question by its
 * number, a party-list ballot by its body, a party's list by its *party*
 * (as `partyOf` gives it) where known, else by its ballot number. */
export function contestLabel(id, index, { day = undefined, party = null } = {}) {
  const { kind, area, sub } = parseContest(id);
  const name = index.obce[area]?.[0];
  const kraj = index.kraje[area];
  switch (kind) {
    case 'starosta':
      return t(MAYOR_LABEL[placeKind(area, index)], { name });
    case 'oz':
      return t(COUNCIL_LABEL[placeKind(area, index)], { name, n: sub });
    case 'predseda':
      return t('contest.president', { kraj });
    case 'zsk':
      return t('contest.regional_council', { kraj, n: sub });
    case 'prezident': {
      const date = day === undefined ? roundDay(sub) : day;
      return date
        ? t('contest.president_round', { round: sub, date: formatShortDate(date) })
        : t('contest.president_round_undated', { round: sub });
    }
    case 'referendum':
      return t('contest.question', { n: sub });
    default:
      if (sub === null) return t(`contest.parties.${kind}`);
      return party ? t('contest.list', { party: party.name }) : t('contest.list_number', { n: sub });
  }
}

/* The party whose list contest *id* (`nrsr:SK/12`) is, as `partyOf` gives
 * it with its ballot `number`, from the party contest's subjects; null
 * where there is no such party. */
export async function listParty(id, index) {
  const subjects = (await getJSON('/data/country.json')).contests[officeOf(id)]?.subjects ?? [];
  const { sub } = parseContest(id);
  const row = subjects.find(([number]) => number === sub);
  return row ? { ...partyOf(row[1], index), number: sub } : null;
}

/* The mayor or president in office at the time of the election, from the
 * entry's `holder`: {name,
 * since, number, result}, `number` their ballot number, null when not
 * standing. */
function decodeHolder(office, [name, since, number, result]) {
  return { name, since, number, result: decodeResult(office, result) };
}

/* The turnout of the last election of the contest's body, from the entry's
 * `past`: {election, date, eligible, voters, whole, method}, `election`
 * the results name (oso2022, osk2022, oso202303, …), `whole` set when the
 * figures are of the whole municipality or city rather than this council
 * obvod; for an obvod of a council of several now whose figures are its
 * own okrsky's then, `method` the least certain way they were found
 * (live.js `PAST`; else null). */
function decodePast([election, date, eligible, voters, scope]) {
  const method = Array.isArray(scope) ? scope[0] : null;
  return { election, date, eligible, voters, whole: scope === 1, method };
}

/* Contest *id* from its area file; `holder` and `past` (see above) are null
 * where not known; `noResult` set for a contest that had candidates but has
 * no final result (the vote could not be completed), `electedOnly` for a
 * council contest whose candidates are its elected only, the others not
 * published, `uncontested` {title, url} for one called but held nowhere,
 * no candidate having registered (what says so). Where they apply:
 * `round` and `day` of a presidential round, `question` (the wording) of
 * a referendum question; of a party-list ballot `seats` (the body's),
 * `threshold` (the % of the valid votes a party needs for seats),
 * `coalitions` ([[parties, %]], what a coalition of at least that many
 * parties needs instead, by ascending parties; none where it needs what a
 * party does), `preferences` (how many of a list's candidates a voter may
 * circle) and `quota` (the % of its party's votes a candidate's
 * preference votes must reach to move up the list), the last two of a
 * party's list too, and its `party` (`listParty`). `candidates` are the
 * persons, the parties of a party-list ballot (`decodeSubject`) or a
 * question's answers. */
async function contest(id, index) {
  const [file, translated] = await Promise.all([getJSON(areaPath(id, index)), occupations()]);
  const entry = file.contests[id] ?? { candidates: [] };
  const list = isList(id);
  const party = list ? await listParty(id, index) : null;
  const ballot = list ? ((await getJSON('/data/country.json')).contests[officeOf(id)] ?? {}) : entry;
  const { kind } = parseContest(id);
  let candidates;
  if (kind === 'referendum') candidates = answers(id);
  else if (entry.subjects) candidates = entry.subjects.map((row) => decodeSubject(id, row, index, entry.research));
  else candidates = entry.candidates.map((row) => decodeCandidate(id, entry, row, translated, index, file));
  return {
    id,
    label: contestLabel(id, index, { day: entry.day ?? undefined, party }),
    seats: entry.seats ?? null,
    seats2022: entry.seats_2022 ?? null,
    sources: entry.sources ?? [],
    holder: entry.holder ? decodeHolder(officeOf(id), entry.holder) : null,
    past: entry.past ? decodePast(entry.past) : null,
    noResult: Boolean(entry.no_result),
    electedOnly: Boolean(entry.elected_only),
    uncontested: entry.uncontested ? { title: entry.uncontested[0], url: entry.uncontested[1] } : null,
    round: entry.round ?? null,
    day: entry.day ?? null,
    question: entry.question ?? null,
    preferences: ballot.preferences ?? null,
    threshold: entry.threshold ?? null,
    coalitions: entry.coalitions ?? [],
    quota: ballot.quota ?? null,
    party,
    candidates,
  };
}

/* The contests *ids* (as in `ballots`), leaving out an id whose area is not
 * known (from a link made by hand, say), or a list of no party. */
export async function contests(ids) {
  const index = await dataIndex();
  const known = await Promise.all(
    ids.map(async (id) => {
      const { area, spec } = parseContest(id);
      if (!spec) return false;
      if (spec.scope === 'country') return area === COUNTRY && (!isList(id) || (await listParty(id, index)) !== null);
      return spec.scope === 'kraj' ? area in index.kraje : area in index.obce;
    }),
  );
  return Promise.all(ids.filter((_, i) => known[i]).map((id) => contest(id, index)));
}

/* The ids of the country-wide contests of the page's election, as the
 * ballots list them (`countryOrder`): the party lists not among them,
 * which open from their parties. */
async function countryIds() {
  const file = await getJSON('/data/country.json');
  return Object.keys(file.contests)
    .filter((id) => !isList(id))
    .sort(countryOrder);
}

/* The country-wide contests of the page's election (`countryIds`), as
 * `contests` gives them: the ballots of every voter. */
export async function countryBallots() {
  const index = await dataIndex();
  return Promise.all((await countryIds()).map((id) => contest(id, index)));
}

/* The places of a by-election where something is elected
 * (data/index.json `held`), each {code, kraj, name, detail, contests}: an
 * obec (or Bratislava, Košice), `detail` its okres and kraj, or a kraj
 * (`kraj` set), with what is elected there, `contests` short names of
 * them (`byelection.<kind>`: a council's obvod where it has several);
 * obce by name, after them the kraje. */
export async function heldPlaces() {
  const index = await dataIndex();
  const collator = new Intl.Collator(lang);
  const short = (id) => {
    const { kind, area, sub } = parseContest(id);
    const obvod = kind === 'zsk' || (kind === 'oz' && hasCouncilObvody(index, area));
    return t(`byelection.${kind}${obvod ? '_obvod' : ''}`, { n: sub });
  };
  const places = Object.entries(index.held ?? {}).map(([code, ids]) => {
    const contests = ids.map(short);
    if (code in index.kraje) return { code, kraj: true, name: t('place.kraj', { name: index.kraje[code] }), contests };
    const [name, okres, kraj] = index.obce[code];
    const detail = [okres && t('place.okres', { name: index.okresy[okres][0] }), t('place.kraj', { name: index.kraje[kraj] })];
    return { code, kraj: false, name, detail: detail.filter(Boolean).join(' · '), contests };
  });
  return places.sort((a, b) => Number(a.kraj) - Number(b.kraj) || collator.compare(a.name, b.name));
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
 * council and mayor, then regional council and president; of a by-election
 * only those held there (data/index.json `held`) or called there but held
 * nowhere (`uncontested`); of a regular election of
 * one half only its half's (kinds.js `holds`); of a country-wide
 * election the country's (`countryIds`). *where* narrows
 * the council where the obec has several obvody: {obvod} of an address or a
 * point, or {street, part} chosen in the search, whose houses may all be in
 * one.
 *
 * Null for an unknown obec, else {obec, council, obvod, estimated,
 * origin, contests, group}:
 * - `contests`: as `contests` gives them, the council ones with `council`;
 * - `council`: 'single' (one obvod), 'address' (several, the place's known:
 *   `obvod`), 'choose' (several, known by address, but no address chosen),
 *   'pending' (several, not known by address yet) or 'none'; without an
 *   obvod every council obvod is listed;
 * - `estimated`: the obec has not published which addresses are in which
 *   obvod, so they are a guess;
 * - `origin`: where its units come from when not from this election's own
 *   documents, from data/index.json: `reused` the day of the election whose
 *   council obvod rules stand in, `adopted` that of the vote, earlier or
 *   later, whose rules stand in though the layout is not proven to match
 *   (the borders indicative only), `dating` {by, seen} where the documents
 *   of its obvody state no date and are dated approximately ('archived'
 *   or 'posted' on the day `seen`, or 'named': they name the election),
 *   `supplemented` {from, day} where those documents do not place every
 *   address and rules from a later source ('election', 'referendum' or
 *   'document' of the day `day`) fill them in,
 *   `notFound` whether no document setting its obvody was found,
 *   `okrskyReused`, `okrskyAdopted` and `okrskyReferendum` the day of the
 *   election or referendum whose okrsky are drawn, `okrskyDating` and
 *   `okrskySupplemented` as `dating` and `supplemented` of the okrsky's
 *   document, `okrskyUnknown`
 *   whether it voted in several okrsky that are not drawn, `special` its
 *   okrsky without territory that voted (data/index.json `special`: okrsok
 *   → {kind, voters, title, url, okresy | facility}, never drawn),
 *   `boundary` {day, on, obce} where its boundary on `day` differed from
 *   that of the election `on` drawn (`obce` the names of the neighbours
 *   the land moved between, none for the state border), each null or
 *   false where not;
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
  let ids = isNational ? await countryIds() : [...councilIds, `starosta:${obec.code}`];
  if (!isNational) {
    if (obec.city) ids.push(`oz:${obec.city}/${obec.cityObvod}`, `starosta:${obec.city}`);
    ids.push(`zsk:${obec.kraj}/${obec.zsk}`, `predseda:${obec.kraj}`);
  }
  if (isByElection) {
    // Those called but held nowhere too: the ballot box says so.
    const areas = [obec.code, obec.city, obec.kraj];
    const held = new Set(areas.flatMap((area) => index.held[area] ?? []));
    for (const id of index.uncontested) if (areas.includes(parseContest(id).area)) held.add(id);
    ids = ids.filter((id) => held.has(id));
  }
  ids = ids.filter((id) => holds(electionLabel, id));
  const contests = await Promise.all(ids.map((id) => contest(id, index)));
  for (const c of contests) if (councilIds.includes(c.id)) c.council = council;
  const own = index.boundaries?.obce[obec.code];
  const origin = {
    reused: index.reused[obec.code] ?? null,
    adopted: index.adopted[obec.code] ?? null,
    dating: index.date_approximate[obec.code] ?? null,
    supplemented: index.supplemented[obec.code] ?? null,
    notFound: index.not_found.includes(obec.code),
    okrskyReused: index.okrsky_reused[obec.code] ?? null,
    okrskyAdopted: index.okrsky_adopted[obec.code] ?? null,
    okrskyOutliers: index.okrsky_outliers[obec.code] ?? null,
    okrskyReferendum: index.okrsky_referendum[obec.code] ?? null,
    okrskyDating: index.okrsky_date_approximate[obec.code] ?? null,
    okrskySupplemented: index.okrsky_supplemented[obec.code] ?? null,
    okrskyUnknown: index.okrsky_unknown.includes(obec.code),
    special: index.special[obec.code] ?? null,
    boundary: own
      ? { day: index.boundaries.day, on: index.boundaries.on, obce: own.map((c) => index.obce[c][0]) }
      : null,
  };
  return { obec, council, obvod, estimated: index.estimated.includes(obec.code), origin, contests, group };
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
  const candidate = decodeCandidate(contestId, entry, row, translated, index, file);
  const ids = [...(file.persons[candidate.person] ?? [candidacyId])].sort((a, b) => localFirst(contestOf(a), contestOf(b)));
  const candidacies = await Promise.all(
    ids.map(async (id) => {
      const whole = await contest(contestOf(id), index);
      return { candidate: whole.candidates.find((x) => x.id === id), contest: whole };
    }),
  );
  return { candidate, candidacies };
}

/* For candidacy *candidacyId*, the candidacy that stands for it in each
 * other election (`linkedCandidacy`): slug → candidacy id, none where the
 * person is not linked there; empty for a candidacy not found. The card of
 * the candidacy is open, so its file is loaded already. */
export async function candidacyLinks(candidacyId) {
  const found = await person(candidacyId).catch(() => null);
  if (!found) return {};
  return Object.fromEntries(
    otherElections.flatMap(({ slug }) => {
      const there = linkedCandidacy(found.candidate, slug);
      return there ? [[slug, there.id]] : [];
    }),
  );
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
  const { kind, area, sub } = parseContest(id);
  if (kind === 'predseda') return { area: `kraj:${area}` };
  if (kind === 'zsk') return { area: `kraj:${area}/${sub}` };
  if (isCity(area)) return { area: kind === 'oz' ? `${area}/${sub}` : area };
  return { obec: area, obvod: kind === 'oz' && hasCouncilObvody(index, area) ? sub : null };
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
