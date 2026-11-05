/* The kinds of elections and contests, contest ids and the area file of a
 * contest: src/election_map_slovakia/contests.py, whose module doc describes
 * them, in the app.
 *
 * A contest is `<kind>:<area>[/<sub>]`, a candidacy `<contest>#<number>`,
 * a body (the office) the contest id without `/<sub>`. A party-list contest
 * (`nrsr:SK`) has the parties as its candidates and a list contest per party
 * (`nrsr:SK/12`) of the persons on its list.
 */

import { election, elections } from './i18n.js';
import { KIND_ICON } from './icons.js';

/* single: a voter marks one candidate (not so a party's list);
 * scope: obec, kraj or country; sub: what `/<sub>` is; party: its
 * candidates are parties, each with a list contest. */
export const KINDS = {
  starosta: { single: true, scope: 'obec', sub: null },
  oz: { single: false, scope: 'obec', sub: 'obvod' },
  predseda: { single: true, scope: 'kraj', sub: null },
  zsk: { single: false, scope: 'kraj', sub: 'obvod' },
  prezident: { single: true, scope: 'country', sub: 'round' },
  referendum: { single: true, scope: 'country', sub: 'question' },
  nrsr: { single: true, scope: 'country', sub: 'list', party: true },
  ep: { single: true, scope: 'country', sub: 'list', party: true },
};

/* The area of a country-wide contest. */
export const COUNTRY = 'SK';

/* The election kinds whose contests are all country-wide. */
const NATIONAL = new Set(['presidential', 'referendum', 'parliament', 'european']);

/* The kind of the page's election (config/elections.toml `kind`). */
export const electionKind = elections.find((e) => e.day === election)?.kind;

/* What the strings of the page's election's kind are keyed by
 * (`app.title.<label>`, build.py `elections`): its kind, but `municipal`
 * or `regional` for a regular election of one half (before 2022 the
 * municipal and the regional elections were held on days of their own). */
export const electionLabel = elections.find((e) => e.day === election)?.label;

/* Whether the page's election is country-wide: one ballot for everyone. */
export const isNational = NATIONAL.has(electionKind);

/* Whether the page's election is a by-election, held in some places only. */
export const isByElection = electionKind === 'by-election';

/* The kind an election's `label` belongs to: a regular election of one
 * half, `municipal` or `regional`, is of the municipal and regional kind. */
export const kindOf = (label) => (label === 'municipal' || label === 'regional' ? 'municipal-regional' : label);

/* The icon of the elections of kind (or label) *kind* (icons.js
 * `KIND_ICON`), and the style of what draws in their colour: `--kind`, the
 * kind's token (app.css `--kind-<kind>`), which `.kind-mark`, the
 * switcher's points and headings, read. */
export const kindIcon = (kind) => KIND_ICON[kindOf(kind)];

export const kindStyle = (kind) => ({ '--kind': `var(--kind-${kindOf(kind)})` });

/* What the overview of the page's election shows (overview.js), the same
 * everywhere: the parties' lists (NR SR, EP), 'parties', or a referendum's
 * questions, 'referendum'; null for the elections without one. */
export const overviewKind = { parliament: 'parties', european: 'parties', referendum: 'referendum' }[electionKind] ?? null;

/* Whether an election labelled *label* (`elections` `label`) holds
 * contests like contest *id*: a regular election of one half holds those
 * of its half only (municipal: a mayor's, a council's; regional: a
 * kraj's). */
export function holds(label, id) {
  if (label === 'municipal') return isMunicipal(id);
  if (label === 'regional') return isRegional(id);
  return true;
}

/* Contest id *id* taken apart: {kind, area, sub, spec}, *spec* its KINDS
 * entry. */
export function parseContest(id) {
  const [kind, rest] = id.split(':');
  const [area, sub] = rest.split('/');
  return { kind, area, sub: sub ? Number(sub) : null, spec: KINDS[kind] };
}

/* The contest of candidacy id *candidacyId*. */
export const contestOf = (candidacyId) => candidacyId.slice(0, candidacyId.lastIndexOf('#'));

/* The body (office) contest *id* elects: the id without `/<sub>`. */
export const officeOf = (id) => id.split('/')[0];

/* Whether contest *id* is a party's list (`nrsr:SK/12`). */
export function isList(id) {
  const { spec, sub } = parseContest(id);
  return Boolean(spec?.party) && sub !== null;
}

/* Whether contest *id* has parties for candidates (`nrsr:SK`). */
export function isParties(id) {
  const { spec, sub } = parseContest(id);
  return Boolean(spec?.party) && sub === null;
}

/* Whether a voter marks one of contest *id*'s candidates: a mayor, a
 * president, an answer, a party. */
export function isSingle(id) {
  const { spec } = parseContest(id);
  return Boolean(spec?.single) && !isList(id);
}

/* Whether contest *id* is a council of several seats (`oz`, `zsk`). */
export const isCouncil = (id) => parseContest(id).spec?.sub === 'obvod';

/* Whether contest *id* is a kraj's (president or council). */
export const isRegional = (id) => parseContest(id).spec?.scope === 'kraj';

/* Whether contest *id* is a municipality's (mayor or council). */
export const isMunicipal = (id) => parseContest(id).spec?.scope === 'obec';

/* Whether contest *id* is country-wide. */
export const isCountry = (id) => parseContest(id).spec?.scope === 'country';

/* Whether area code *code* is Bratislava or Košice, cities whose districts
 * are municipalities of their own. */
export const isCity = (code) => code === 'BA' || code === 'KE';

/* The area file a contest is in (contests.py `area_name`), by name:
 * kraj/<k>, city/<BA|KE>, okres/<code>, country or list/<p>. The results
 * name theirs alike. */
export function areaName(id, index) {
  const { area, sub, spec } = parseContest(id);
  if (spec.scope === 'country') return isList(id) ? `list/${sub}` : 'country';
  if (spec.scope === 'kraj') return `kraj/${area}`;
  if (isCity(area)) return `city/${area}`;
  return `okres/${index.obce[area][1]}`;
}
