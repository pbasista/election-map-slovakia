/* UI strings and the language switch.
 *
 * The page's language is the <html lang> the build stamped into this shell
 * (/sk/, /en/, ...); its strings come from /i18n/<lang>.json. The build fills
 * every enabled language completely, so there is no runtime fallback: a
 * string not translated yet comes in English, and `_pending` tells the app
 * to say that the translation is incomplete.
 */

import { setDataSource, setStringsVersion, sharedUrl } from './files.js';

const config = JSON.parse(document.querySelector('meta[name="km-config"]').content);
const dates = (isos) => isos?.map((iso) => new Date(iso)) ?? null;

export const lang = document.documentElement.lang;
export const languages = config.languages;
export const election = config.election;
// Every election the site shows, [{day, slug}] newest first; each has its
// pages at /<lang>/<slug>/ (search.js `Elections`).
export const elections = config.elections;
// When the polls open and close, as Dates (config/elections.toml).
export const polls = dates(config.polls);
// Research language → the source categories its research searches.
export const researchCategories = config.research;
// The project's source code repository, linked from the About dialog.
export const repository = config.repository;
// The site's version (__version__), named in the About dialog.
export const version = config.version;
// A presidential election's rounds, [[day, open, close]] (ISO), round 1
// first; null for any other kind.
export const rounds = config.rounds ?? null;
// Where the page's election's files are, and their versions (files.js
// `setDataSource`): its map bundle (/map/<slug> served by `ems serve`,
// deployed at an address of its own: geo/, addr/), its data bundle
// (likewise: data/, i18n/) and its extract's base map (/base/<extract>:
// base/). Set here, before anything is fetched.
export const dataSource = {
  data: config.data,
  dataVersion: config.dataVersion,
  map: config.map,
  mapVersion: config.mapVersion,
  base: config.base,
  baseVersion: config.baseVersion,
};
setDataSource(dataSource);
// Asked for with the UI strings (files.js `sharedUrl`), which every
// election's page shares.
setStringsVersion(config.stringsVersion);
// Day of the regular elections before the page's, of which the office
// holders and the past turnouts are; null where they are not known.
export const previous = config.previous;
// On an earlier election's page, what the map's credits name: {boundaries:
// [slug, n] where it is drawn on a later election's boundaries (n obce then
// differed) or null, osm and addresses the date (YYYY-MM-DD or YYYY-MM)
// their data are of}; null on the latest's.
export const credits = config.credits;
// Where the election's final results are (/results/<day> served by `ems
// serve`, deployed on a domain of their own), named even before there are
// any.
export const resultsPath = config.results;
// Where the cached copies of the pages research cites are, below cache/
// (empty: this site's own origin). A copy, cache/<sha256>.html, is linked
// as cache/<sha256>: Pages answers the .html URL with a redirect to that.
export const sourcesBase = config.sources;
// The URL of a party logo, which data/index.json names by file.
export const logoUrl = (file) => `${config.logos}/${file}`;
// Where the live results of the election's night are (/live/<day>, deployed
// on a domain of their own), which the app reads where the final results
// are not there yet; null where it reads the final results alone, once per
// page load (config/elections.toml live).
export const livePath = config.live;
// The window, as Dates, in which the app reads the results every minute
// (config/elections.toml live_days); null: any time (a build with
// EMS_RESULTS_ANYTIME=1, for testing).
export const liveWindow = dates(config.liveWindow);

let strings = {};
// The language the strings are in: the page's, or for a language with no
// string translated yet the one its strings were taken from.
let locale = lang;

export async function loadStrings() {
  const response = await fetch(sharedUrl(`/i18n/${lang}.json`));
  if (!response.ok) throw new Error(`/i18n/${lang}.json: HTTP ${response.status}`);
  strings = await response.json();
  if (strings._locale) {
    locale = strings._locale;
    document.documentElement.lang = locale;
  }
}

// A language other than Slovak, in which the occupations are written, has
// them translated in the election's bundle (i18n/<lang>.json), all but
// config.occupations[lang] of them.
export const translationPending = () => Boolean(strings._pending) || config.occupations[lang] > 0;

/* Whether the election's bundle has occupations in this language. */
export const hasOccupations = () => lang in config.occupations;

// Placeholders every string may use: {year}, the page's election's, and
// {previous}, that of the elections before it (none where `previous` is
// null, and no string with it is shown then).
const pageVars = { year: election.slice(0, 4), previous: previous?.slice(0, 4) };

/* `t('contest.council', {name, n})`: {name} placeholders are replaced, and
 * {year} and {previous} (`pageVars`) unless *vars* has them; a missing key
 * shows as itself, which is easier to spot than a blank. */
export function t(key, vars) {
  const all = { ...pageVars, ...vars };
  return (strings[key] ?? key).replace(/\{(\w+)\}/g, (m, k) => (all[k] != null ? String(all[k]) : m));
}

/* The strings whose keys start with *prefix*, by the rest of the key. */
export const stringsUnder = (prefix) =>
  Object.fromEntries(
    Object.entries(strings)
      .filter(([key]) => key.startsWith(prefix))
      .map(([key, s]) => [key.slice(prefix.length), s]),
  );

// Intl formatters are slow to make, and a pane formats hundreds of numbers
// and dates on every render: each is made once, by locale and options.
const formatters = new Map();
function formatter(key, make) {
  const id = `${locale} ${key}`;
  if (!formatters.has(id)) formatters.set(id, make());
  return formatters.get(id);
}

export const formatNumber = (n) => formatter('number', () => new Intl.NumberFormat(locale)).format(n);

/* A share (0.412) as a percentage with *digits* decimals ("41.2%",
 * "41,2 %"). */
export const formatPercent = (share, digits = 1) =>
  formatter(
    `percent ${digits}`,
    () =>
      new Intl.NumberFormat(locale, {
        style: 'percent',
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }),
  ).format(share);

/* Date *iso* (YYYY-MM-DD) written out ("24. októbra 2026"). */
export function formatDate(iso) {
  const date = new Date(`${iso}T00:00:00Z`);
  // Browsers have no calendar data for some languages (rue, rmc) and would
  // write the date in English; their month names come with the strings.
  const known = formatter('date', () =>
    Intl.DateTimeFormat.supportedLocalesOf([locale]).length
      ? new Intl.DateTimeFormat(locale, { dateStyle: 'long', timeZone: 'UTC' })
      : null,
  );
  if (known) return known.format(date);
  return t('date.long', {
    day: date.getUTCDate(),
    month: t('date.months').split('|')[date.getUTCMonth()],
    year: date.getUTCFullYear(),
  });
}

/* The vote of day *iso* by its name and date, as `[part, text]` pairs in
 * the language's order (`elections.item`, "{name} {date}"): *part* is
 * 'name' (`elections.name.<label>`), 'date' (written out) or null for the
 * template's own words, so that the title bar can set the date apart from
 * the name. A day of no election the site shows by its date alone. */
export function electionParts(iso) {
  const label = elections.find((e) => e.day === iso)?.label;
  const date = formatDate(iso);
  if (!label) return [['date', date]];
  const parts = { name: t(`elections.name.${label}`), date };
  return t('elections.item')
    .split(/\{(name|date)\}/)
    .map((text, i) => (i % 2 ? [text, parts[text]] : [null, text]))
    .filter(([, text]) => text);
}

/* The vote of day *iso* by its name and date, as one string
 * (`electionParts`): as the title bar names the page's election. */
export const electionName = (iso) =>
  electionParts(iso)
    .map(([, text]) => text)
    .join('');

/* The vote of day *iso* whose borders stand in for this election's, named
 * by its kind and year (a by-election by its date: several a year) as the
 * notes say "borders of …" (`stand_in.source.<label>`, the label of the
 * election list's `elections.kind.<label>`). */
export function standInSource(iso) {
  const label = elections.find((e) => e.day === iso)?.label;
  return t(`stand_in.source.${label}`, { year: iso.slice(0, 4), date: formatDate(iso) });
}

/* Date *iso* (YYYY-MM-DD) short, for a label that names it in passing
 * ("23. 3. 2024", "Mar 23, 2024"); in the strings' form where the browser
 * does not know the language (formatDate). */
export function formatShortDate(iso) {
  const date = new Date(`${iso}T00:00:00Z`);
  const known = formatter('date-short', () =>
    Intl.DateTimeFormat.supportedLocalesOf([locale]).length
      ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' })
      : null,
  );
  if (known) return known.format(date);
  return t('date.short', { day: date.getUTCDate(), month: date.getUTCMonth() + 1, year: date.getUTCFullYear() });
}

/* A date of data, *asOf* YYYY-MM-DD (written out) or YYYY-MM (MM/YYYY). */
export function formatAsOf(asOf) {
  const [year, month, day] = asOf.split('-');
  return day ? formatDate(asOf) : `${month}/${year}`;
}

/* "a, b and c" in the page's language; plain commas where the browser does
 * not know the language (formatDate). */
export function formatList(items) {
  const known = formatter('list', () =>
    Intl.ListFormat.supportedLocalesOf([locale]).length ? new Intl.ListFormat(locale, { type: 'conjunction' }) : null,
  );
  return known ? known.format(items) : items.join(', ');
}

/* The page in language *code* of the page's election: /<code>/ for the
 * latest, which that path serves, else /<code>/<slug>/. */
export function languagePage(code) {
  const slug = election === elections[0].day ? '' : `${elections.find((e) => e.day === election).slug}/`;
  return `/${code}/${slug}`;
}

/* The root page (/) sends visitors to the language they chose last time,
 * else to the first of navigator.languages that the site has. */
export function switchLanguage(code) {
  try {
    localStorage.setItem(config.storage, code);
  } catch {
    // Private mode or storage disabled: the switch still works for this visit.
  }
  location.assign(`${languagePage(code)}${location.hash}`);
}
