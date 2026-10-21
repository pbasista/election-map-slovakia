/* UI strings and the language switch.
 *
 * The page's language is the <html lang> the build stamped into this shell
 * (/sk/, /en/, ...); its strings come from /i18n/<lang>.json. The build fills
 * every enabled language completely, so there is no runtime fallback: a
 * string not translated yet comes in English, and `_pending` tells the app
 * to say that the translation is incomplete.
 */

const config = JSON.parse(document.querySelector('meta[name="km-config"]').content);

export const lang = document.documentElement.lang;
export const languages = config.languages;
export const election = config.election;
// Research language → the source categories its research searches.
export const researchCategories = config.research;
// The project's source code repository, linked from the About dialog.
export const repository = config.repository;

let strings = {};
// The language the strings are in: the page's, or for a language with no
// string translated yet the one its strings were taken from.
let locale = lang;

export async function loadStrings() {
  const response = await fetch(`/i18n/${lang}.json`);
  if (!response.ok) throw new Error(`/i18n/${lang}.json: HTTP ${response.status}`);
  strings = await response.json();
  if (strings._locale) {
    locale = strings._locale;
    document.documentElement.lang = locale;
  }
}

export const translationPending = () => Boolean(strings._pending);

/* Whether /i18n/<lang>/occupations.json has occupations in this language. */
export const hasOccupations = () => Boolean(strings._occupations);

/* `t('contest.council', {name, n})`: {name} placeholders are replaced; a
 * missing key shows as itself, which is easier to spot than a blank. */
export function t(key, vars) {
  const s = strings[key] ?? key;
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
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

/* "a, b and c" in the page's language; plain commas where the browser does
 * not know the language (formatDate). */
export function formatList(items) {
  const known = formatter('list', () =>
    Intl.ListFormat.supportedLocalesOf([locale]).length ? new Intl.ListFormat(locale, { type: 'conjunction' }) : null,
  );
  return known ? known.format(items) : items.join(', ');
}

/* The root page (/) sends visitors to the language they chose last time,
 * else to the first of navigator.languages that the site has. */
export function switchLanguage(code) {
  try {
    localStorage.setItem(config.storage, code);
  } catch {
    // Private mode or storage disabled: the switch still works for this visit.
  }
  location.assign(`/${code}/${location.hash}`);
}
