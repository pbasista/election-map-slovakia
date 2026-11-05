/* The About text, shown in a dialog (pane.js): a short main page with a
 * sentence on the project, what the page of its election offers as a list,
 * links to its sections, the source code and the license, and one section
 * per topic: how it works, the data sources and their licenses, the sources
 * of the candidate research, the disclaimers; on an earlier election's page
 * also what it takes from the latest one.
 * The lists come from data/about.json, which the build renders from config/
 * and the curated research (see build.py `about`). */

import { html, useEffect, useRef } from '../vendor/preact-htm.module.js';
import { getJSON, latestElection, useLoaded } from './data.js';
import {
  election,
  electionName,
  elections,
  formatAsOf,
  formatDate,
  formatList,
  formatNumber,
  previous,
  repository,
  standInSource,
  t,
  version,
} from './i18n.js';
import {
  ArrowIcon,
  BackIcon,
  ChairIcon,
  CloseIcon,
  EyeOffIcon,
  HeartIcon,
  MapResultsIcon,
  SearchIcon,
  TurnoutIcon,
} from './icons.js';
import { electionKind, electionLabel, isByElection, isNational, kindIcon } from './kinds.js';

// What the page's election offers, a line each (`about.feature.<name>`)
// with the icon the app gives it elsewhere, by its kind: where its ballots
// or results are found (a by-election's map shows where it is held), what
// its ballot holds and what its results are (BALLOT), who held the offices
// where that is known, the research and Favourites (not of a referendum,
// which has no candidates), and that the site has no ads and no tracking.
const BALLOT =
  { presidential: 'presidential', referendum: 'referendum', parliament: 'parties', european: 'parties' }[
    electionKind
  ] ?? 'local';
const FEATURES = [
  [isByElection ? 'find_held' : isNational ? 'find_results' : 'find', MapResultsIcon],
  [`ballot_${BALLOT}`, kindIcon(electionLabel)],
  [`results_${BALLOT}`, TurnoutIcon],
  !isNational && previous && ['incumbents', ChairIcon],
  BALLOT !== 'referendum' && ['research', SearchIcon],
  BALLOT !== 'referendum' && ['favourites', HeartIcon],
  ['private', EyeOffIcon],
].filter(Boolean);

// Section → the key of its title, its link on the main page; on an earlier
// election's page, what comes from the latest (`Substitutes`).
const SECTIONS = {
  method: 'about.method.title',
  ...(election === latestElection.day ? {} : { latest: 'about.latest.title' }),
  sources: 'about.sources.title',
  research: 'about.allowlist.title',
  disclaimers: 'about.disclaimer.title',
};
// The section titles name the latest election by its year, as its body
// does (`about.latest.*`).
const LATEST = { latest: latestElection.day.slice(0, 4) };

/* The section a `v` hash value shows: '' for the main page (`about`), a
 * section name for `about-<section>`, null if it is not the About dialog. */
export function aboutSection(view) {
  if (view === 'about') return '';
  const section = view?.startsWith('about-') ? view.slice('about-'.length) : null;
  return section in SECTIONS ? section : null;
}

export const aboutView = (section) => (section ? `about-${section}` : 'about');

// The data sources (data/about.json `inputs`: the election's and those
// shared) by name prefix, each group under its own line; a group without
// any is left out. Where the candidate lists come with the results (ŠÚ
// SR's packages, build `candidates` "susr", "susr-by"), their line says
// so. The inputs of an election of another kind than the regular ones,
// named as its configuration has it, are ŠÚ SR's candidate lists, units
// and results: those no group takes are under the last line.
const INPUT_GROUPS = [
  ['candidates-', 'about.inputs.candidates'],
  ['zbgis-', 'about.inputs.zbgis'],
  ['addresses', 'about.inputs.addresses'],
  ['natural-earth-', 'about.inputs.countries'],
  ['osm-', 'about.inputs.osm'],
  ['zsk-obvody-', 'about.inputs.zsk'],
  ['results-', 'about.inputs.results'],
];
const OTHER_INPUTS = electionKind === 'municipal-regional' ? null : 'about.inputs.statoffice';

// The method, by how the candidate lists are read (about.json
// `candidates`; none for a referendum) and by what the election has: how
// the map is drawn (its constituencies of whole municipalities: of a
// regular election of one half, those of that half only), the council
// obvody where councils are elected, how the office holders were found
// (or for an election whose office holders are not known, i18n.js
// `previous` null, that they are not shown); of a country-wide election,
// how its results are summed by unit.
const CANDIDATES_METHOD = {
  mvsr: 'about.method.candidates',
  susr: 'about.method.candidates_susr',
  'susr-by': 'about.method.candidates_susr',
  volbysr: 'about.method.candidates_country',
  curated: 'about.method.candidates_curated',
};
const MAP_METHOD = {
  'municipal-regional': 'about.method.map',
  municipal: 'about.method.map_municipal',
  regional: 'about.method.map_regional',
};
const methodKeys = (about) =>
  [
    CANDIDATES_METHOD[about.candidates],
    MAP_METHOD[electionLabel] ?? 'about.method.map_country',
    'about.method.addresses',
    ...(isNational
      ? ['about.method.results_country']
      : [
          electionLabel === 'regional' ? null : 'about.method.obvody',
          'about.method.approximate',
          previous ? 'about.method.incumbents' : 'ballots.no_incumbents',
        ]),
  ].filter(Boolean);

const DISCLAIMERS = [
  'disclaimer.indicative',
  'disclaimer.errors',
  'disclaimer.exhaustive',
  'disclaimer.ai',
  'disclaimer.translation',
];

const Link = ({ href, children }) =>
  html`<a href=${href} rel="noopener noreferrer" target="_blank">${children ?? href}</a>`;

// The flag's twelve stars, on a circle of a third of its height around its
// centre, clockwise from the top, to 0.1 of a unit.
const STARS = Array.from({ length: 12 }, (_, i) => {
  const angle = (i * Math.PI) / 6;
  const round = (v) => Math.round(v * 10) / 10;
  return [round(405 + 180 * Math.sin(angle)), round(270 - 180 * Math.cos(angle))];
});

/* The flag of the European Union in its official geometry: the cue for what
 * "EUPL" means even if the acronym says nothing to the reader. */
function EuFlag() {
  return html`<svg class="eu-flag" viewBox="0 0 810 540" width="30" height="20" aria-hidden="true">
    <defs>
      <path
        id="eu-star"
        fill="#ffcc00"
        d="M0.00,-33.33L7.48,-10.30L31.70,-10.30L12.11,3.93L19.59,26.97L0.00,12.73L-19.59,26.97L-12.11,3.93L-31.70,-10.30L-7.48,-10.30Z"
      />
    </defs>
    <rect x="0" y="0" width="810" height="540" fill="#003399" />
    ${STARS.map(([x, y]) => html`<use href="#eu-star" x=${x} y=${y} />`)}
  </svg>`;
}

/* String *key* with its {*name*} placeholder replaced by *node*. */
function fill(key, name, node) {
  const [before, after = ''] = t(key).split(`{${name}}`);
  return html`${before}${node}${after}`;
}

/* The version, linked to its release notes (only a tagged __version__ is
 * deployed, docs/deploy.md, so the release exists); then the repository
 * sentence, its {github} a link reading "GitHub" in the grammatical case
 * the sentence needs (about.github) rather than the long URL. */
function repositoryLine() {
  const release = html`<${Link} href=${`${repository}/releases/tag/v${version}`}>${version}<//>`;
  const github = html`<${Link} href=${repository}>${t('about.github')}<//>`;
  return html`${fill('about.version', 'version', release)}${' · '}${fill('about.repository', 'github', github)}`;
}

// The lead names the year of the oldest election the site shows, as
// build.py `_texts` does in `site.*`; under it, what this page offers.
const SINCE = elections.at(-1).day.slice(0, 4);

function Main({ sectionHash, onSection }) {
  return html`
    <p class="about-lead">${t('about.lead', { since: SINCE })}</p>
    <h3>${electionName(election)}</h3>
    <ul class="about-features">
      ${FEATURES.map(
        ([name, Icon]) => html`<li key=${name}><${Icon} /><span>${t(`about.feature.${name}`)}</span></li>`,
      )}
    </ul>
    <ul class="about-sections">
      ${Object.entries(SECTIONS).map(
        ([name, title]) => html`
          <li key=${name}>
            <a
              href=${sectionHash(name)}
              onClick=${(e) => {
                e.preventDefault();
                onSection(name);
              }}
            >
              ${t(title, LATEST)}<${ArrowIcon} />
            </a>
          </li>
        `,
      )}
    </ul>
    <p>${repositoryLine()}</p>
    <footer class="license">
      <${EuFlag} />
      <${Link} href=${`${repository}/blob/main/LICENSE`}>${t('about.license')}<//>
    </footer>
  `;
}

/* The method, then the obce whose units another vote's borders stand in
 * for (data/about.json `stand_ins`), by that vote. */
function Method({ about }) {
  const standIns = ['obvody', 'okrsky'].flatMap((units) =>
    about.stand_ins[units].map(([day, names]) =>
      t(`about.method.${units}_adopted`, {
        source: standInSource(day),
        n: formatNumber(names.length),
        list: formatList(names),
      }),
    ),
  );
  return html`
    ${methodKeys(about).map((key) => html`<p>${t(key)}</p>`)}
    ${standIns.length ? html`<ul>${standIns.map((item) => html`<li>${item}</li>`)}</ul>` : null}
  `;
}

const Disclaimers = () => html`<ul>${DISCLAIMERS.map((key) => html`<li>${t(key)}</li>`)}</ul>`;

/* The sections listing what data/about.json says, once it has loaded. */
function Loaded({ render }) {
  const [about, failed] = useLoaded(() => getJSON('/data/about.json'), []);
  if (failed) return html`<p class="error">${t('error.load')}</p>`;
  return about ? render(about) : html`<p>${t('panel.loading')}</p>`;
}

function Inputs({ inputs, lists }) {
  const grouped = INPUT_GROUPS.map(([prefix, key]) => [key, inputs.filter((i) => i.name.startsWith(prefix))]);
  const rest = inputs.filter((i) => !INPUT_GROUPS.some(([prefix]) => i.name.startsWith(prefix)));
  const groups = OTHER_INPUTS ? [...grouped, [OTHER_INPUTS, rest]] : grouped;
  return html`
    <ul>
      ${groups.map(([key, group]) => {
        if (!group.length) return null;
        const withLists = key === 'about.inputs.results' && (lists === 'susr' || lists === 'susr-by');
        return html`
          <li>
            ${t(withLists ? 'about.inputs.results_lists' : key)}
            <ul class="links">
              ${group.map(
                (i) => html`<li>
                  <${Link} href=${i.url} />
                  ${i.retrieved ? ` (${t('about.retrieved', { date: formatDate(i.retrieved) })})` : ''}
                </li>`,
              )}
            </ul>
          </li>
        `;
      })}
    </ul>
  `;
}

/* On an earlier election's page, each datum taken from the latest election
 * and each one missing, with counts (data/about.json `substitutes`, build.py
 * `substitutes`); the ballots and the map say so at each place too. */
function Substitutes({ about }) {
  const s = about.substitutes;
  const latest = s.latest;
  const n = formatNumber;
  const { obvody: o, okrsky: k, research: r } = s;
  const items = [
    s.boundaries &&
      t('about.latest.boundaries', {
        zbgis: s.boundaries.zbgis,
        date: formatDate(s.boundaries.day),
        n: n(s.boundaries.obce.length),
        list: formatList(s.boundaries.obce),
      }),
    o.several && t('about.latest.obvody', { several: n(o.several), own: n(o.own) }),
    o.approximate && t('about.latest.obvody_dated', { n: n(o.approximate) }),
    o.supplemented && t('about.latest.obvody_supplemented', { n: n(o.supplemented) }),
    o.reused.length && t('about.latest.obvody_reused', { latest, n: n(o.reused.length), list: formatList(o.reused) }),
    o.unknown &&
      t(o.unknown === o.not_found ? 'about.latest.obvody_unknown' : 'about.latest.obvody_unknown_partly', {
        n: n(o.unknown),
        not_found: n(o.not_found),
      }),
    t('about.latest.okrsky', { several: n(k.several), drawn: n(k.several - k.unknown), unknown: n(k.unknown) }),
    k.reused &&
      (isNational
        ? t('about.latest.okrsky_copied', { n: n(k.reused), years: formatList(k.reused_from) })
        : t('about.latest.okrsky_reused', { latest, n: n(k.reused) })),
    k.referendum && t('about.latest.okrsky_referendum', { n: n(k.referendum) }),
    k.approximate && t('about.latest.okrsky_dated', { n: n(k.approximate) }),
    k.supplemented && t('about.latest.okrsky_supplemented', { n: n(k.supplemented) }),
    t('about.latest.persons', { latest, linked: n(s.persons[0]), total: n(s.persons[1]) }),
    s.research_own
      ? t('about.latest.research_own', {
          date: formatDate(election),
          persons: n(r[0]),
          found: n(r[1]),
          findings: n(r[2]),
        })
      : t('about.latest.research', {
          latest,
          date: formatDate(election),
          persons: n(r[0]),
          found: n(r[1]),
          findings: n(r[2]),
          undated: n(r[3]),
        }),
    t('about.latest.base', { latest, date: formatAsOf(s.osm) }),
    t('about.latest.addresses', { latest, date: formatAsOf(s.addresses) }),
    t('about.latest.own', { latest }),
  ].filter(Boolean);
  return html`
    <p>${t('about.latest.intro', { latest })}</p>
    <ul>${items.map((item) => html`<li>${item}</li>`)}</ul>
  `;
}

function Sources({ about }) {
  return html`
    <${Inputs} inputs=${about.inputs} lists=${about.candidates} />
    <p>${t('about.licenses')}</p>
    ${
      about.obvody.length
        ? html`
            <h3>${t('about.obvody.title')}</h3>
            <ul class="links">
              ${about.obvody.map(
                (o) => html`<li>
                  ${t(`about.obvody.${o.kind}`, { name: o.name })}
                  ${' '}(${formatDate(o.date)}): <${Link} href=${o.source} />
                </li>`,
              )}
            </ul>
          `
        : null
    }
    ${
      about.council.length
        ? html`
            <h3>${t('about.council.title')}</h3>
            <ul class="links">
              ${about.council.map(
                (o) => html`<li>
                  ${o.name}${o.date ? ` (${formatDate(o.date)})` : ''}:
                  ${o.sources.map((url, i) => html`${i ? ', ' : ' '}<${Link} href=${url} />`)}
                </li>`,
              )}
            </ul>
          `
        : null
    }
    ${
      about.logos.length
        ? html`
            <h3>${t('about.logos.title')}</h3>
            <ul class="links">
              ${about.logos.map((o) => html`<li>${o.name}: <${Link} href=${o.source}>${o.license}<//></li>`)}
            </ul>
          `
        : null
    }
    <h3>${t('about.software.title')}</h3>
    <p>${t('about.software')}</p>
  `;
}

function Allowlist({ sources }) {
  return html`
    <p>${t('about.allowlist.intro')}</p>
    <dl class="allowlist">
      ${sources.categories.map(
        ([name, hosts]) => html`
          <dt>${t(`about.category.${name}`)}</dt>
          <dd>${hosts.join(', ')}</dd>
        `,
      )}
    </dl>
    <p>${t('about.allowlist.rule')}</p>
    <ul class="links">
      ${sources.references.map((url) => html`<li><${Link} href=${url} /></li>`)}
    </ul>
    <p>
      ${t('about.allowlist.exclude', {
        hosts: sources.exclude.host_labels.join(', '),
        paths: sources.exclude.path_segments.join(', '),
      })}
    </p>
    <p>
      ${t('about.allowlist.blocklist', {
        date: formatDate(sources.blocklist.date),
        n: formatNumber(sources.blocklist.hosts),
      })}
      ${' '}<${Link} href="https://www.konspiratori.sk/zoznam-stranok" />
    </p>
  `;
}

/* Per research language: the categories of the allowlist searched, and how
 * many candidates are researched in all of them and have findings. */
function Coverage({ research }) {
  return html`
    <table class="coverage">
      <thead>
        <tr>
          <th scope="col">${t('about.research.language')}</th>
          <th scope="col">${t('about.research.categories')}</th>
          <th scope="col" class="num">${t('about.research.researched')}</th>
          <th scope="col" class="num">${t('about.research.found')}</th>
        </tr>
      </thead>
      <tbody>
        ${research.map(
          ([code, categories, researched, found]) => html`
            <tr key=${code}>
              <th scope="row">${t(`research.lang.${code}`)}</th>
              <td>${categories.map((c) => t(`about.category.${c}`)).join(', ')}</td>
              <td class="num">${formatNumber(researched)}</td>
              <td class="num">${formatNumber(found)}</td>
            </tr>
          `,
        )}
      </tbody>
    </table>
  `;
}

function Research({ about }) {
  return html`
    <p>${t('about.method.research')}</p>
    <p>${t('about.method.research_check')}</p>
    <h3>${t('about.allowlist.sites')}</h3>
    <${Allowlist} sources=${about.sources} />
    <h3>${t('about.research.title')}</h3>
    <${Coverage} research=${about.research} />
    <p>${t('about.research.unresearched')}</p>
  `;
}

function Body({ section, sectionHash, onSection }) {
  switch (section) {
    case 'method':
      return html`<${Loaded} render=${(about) => html`<${Method} about=${about} />`} />`;
    case 'latest':
      return html`<${Loaded} render=${(about) => html`<${Substitutes} about=${about} />`} />`;
    case 'disclaimers':
      return html`<${Disclaimers} />`;
    case 'sources':
      return html`<${Loaded} render=${(about) => html`<${Sources} about=${about} />`} />`;
    case 'research':
      return html`<${Loaded} render=${(about) => html`<${Research} about=${about} />`} />`;
    default:
      return html`<${Main} sectionHash=${sectionHash} onSection=${onSection} />`;
  }
}

/* *section*: '' for the main page; *sectionHash(section)* the link to one,
 * *onSection(section)* opens it. */
export function About({ section, sectionHash, onSection, onClose }) {
  const heading = useRef(null);
  const shown = useRef(section);

  // A new section starts at its top, and its heading takes the focus that
  // the link or button which opened it had, so a screen reader reads it.
  useEffect(() => {
    if (shown.current === section) return;
    shown.current = section;
    heading.current.closest('dialog').scrollTop = 0;
    heading.current.focus();
  }, [section]);

  return html`
    <article class="about">
      <header class="about-head">
        ${
          section
            ? html`<button
                type="button"
                class="back"
                aria-label=${t('card.back')}
                title=${t('card.back')}
                onClick=${() => onSection('')}
              >
                <${BackIcon} />
              </button>`
            : null
        }
        <h2 id="km-about" tabindex="-1" ref=${heading}>
          ${section ? t(SECTIONS[section], LATEST) : t('about.title')}
        </h2>
        <button
          type="button"
          class="close"
          aria-label=${t('panel.close')}
          title=${t('panel.close')}
          onClick=${onClose}
        >
          <${CloseIcon} />
        </button>
      </header>
      <${Body} section=${section} sectionHash=${sectionHash} onSection=${onSection} />
    </article>
  `;
}
