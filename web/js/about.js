/* The About text, shown in a dialog (pane.js): a short main page with the
 * project's purpose, links to its sections, the source code and the
 * license, and one section per topic: how it works, the data sources and
 * their licenses, the sources of the candidate research, the disclaimers.
 * The lists come from data/about.json, which the build renders from config/
 * and the curated research (see build.py `about`). */

import { html, useEffect, useRef } from '../vendor/preact-htm.module.js';
import { getJSON, useLoaded } from './data.js';
import { formatDate, formatNumber, repository, t, version } from './i18n.js';
import { ArrowIcon, BackIcon, CloseIcon } from './icons.js';

// Section → the keys of its title and of its line on the main page.
const SECTIONS = {
  method: ['about.method.title', 'about.method.summary'],
  sources: ['about.sources.title', 'about.sources.summary'],
  research: ['about.allowlist.title', 'about.allowlist.summary'],
  disclaimers: ['about.disclaimer.title', 'about.disclaimer.summary'],
};

/* The section a `v` hash value shows: '' for the main page (`about`), a
 * section name for `about-<section>`, null if it is not the About dialog. */
export function aboutSection(view) {
  if (view === 'about') return '';
  const section = view?.startsWith('about-') ? view.slice('about-'.length) : null;
  return section in SECTIONS ? section : null;
}

export const aboutView = (section) => (section ? `about-${section}` : 'about');

const INPUT_GROUPS = [
  ['candidates-', 'about.inputs.candidates'],
  ['zbgis-', 'about.inputs.zbgis'],
  ['addresses', 'about.inputs.addresses'],
  ['natural-earth-', 'about.inputs.countries'],
  ['zsk-obvody-', 'about.inputs.zsk'],
  ['results-', 'about.inputs.results'],
];

const Link = ({ href, children }) =>
  html`<a href=${href} rel="noopener noreferrer" target="_blank">${children ?? href}</a>`;

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
    <use href="#eu-star" x="405" y="90" />
    <use href="#eu-star" x="495" y="114.1" />
    <use href="#eu-star" x="560.9" y="180" />
    <use href="#eu-star" x="585" y="270" />
    <use href="#eu-star" x="560.9" y="360" />
    <use href="#eu-star" x="495" y="425.9" />
    <use href="#eu-star" x="405" y="450" />
    <use href="#eu-star" x="315" y="425.9" />
    <use href="#eu-star" x="249.1" y="360" />
    <use href="#eu-star" x="225" y="270" />
    <use href="#eu-star" x="249.1" y="180" />
    <use href="#eu-star" x="315" y="114.1" />
  </svg>`;
}

/* The version, its number a link to its release, whose notes say what
 * changed (only a tag of __version__ is deployed, docs/deploy.md, so the
 * release exists); then the repository sentence, its {github} the link:
 * "GitHub" in the case the sentence needs (about.github), never the long
 * URL. */
function repositoryLine() {
  const [versionBefore, versionAfter = ''] = t('about.version').split('{version}');
  const [before, after = ''] = t('about.repository').split('{github}');
  const release = html`<${Link} href=${`${repository}/releases/tag/v${version}`}>${version}<//>`;
  const github = html`<${Link} href=${repository}>${t('about.github')}<//>`;
  return html`${versionBefore}${release}${versionAfter}${' · '}${before}${github}${after}`;
}

function Main({ sectionHash, onSection }) {
  return html`
    <p>${t('about.purpose')}</p>
    <ul class="about-sections">
      ${Object.entries(SECTIONS).map(
        ([name, [title, summary]]) => html`
          <li key=${name}>
            <a
              href=${sectionHash(name)}
              onClick=${(e) => {
                e.preventDefault();
                onSection(name);
              }}
            >
              <span>
                <strong>${t(title)}</strong>
                <span>${t(summary)}</span>
              </span>
              <${ArrowIcon} />
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

function Method() {
  return html`
    <p>${t('about.method.candidates')}</p>
    <p>${t('about.method.map')}</p>
    <p>${t('about.method.addresses')}</p>
    <p>${t('about.method.obvody')}</p>
    <p>${t('about.method.approximate')}</p>
    <p>${t('about.method.incumbents')}</p>
  `;
}

function Disclaimers() {
  return html`
    <ul>
      <li>${t('disclaimer.indicative')}</li>
      <li>${t('disclaimer.errors')}</li>
      <li>${t('disclaimer.exhaustive')}</li>
      <li>${t('disclaimer.ai')}</li>
      <li>${t('disclaimer.translation')}</li>
    </ul>
  `;
}

/* The sections listing what data/about.json says, once it has loaded. */
function Loaded({ render }) {
  const [about, failed] = useLoaded(() => getJSON('/data/about.json'), []);
  if (failed) return html`<p class="error">${t('error.load')}</p>`;
  return about ? render(about) : html`<p>${t('panel.loading')}</p>`;
}

function Inputs({ inputs }) {
  return html`
    <ul>
      ${INPUT_GROUPS.map(([prefix, key]) => {
        const group = inputs.filter((i) => i.name.startsWith(prefix));
        return html`
          <li>
            ${t(key)}
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

function Sources({ about }) {
  return html`
    <${Inputs} inputs=${about.inputs} />
    <p>${t('about.licenses')}</p>
    <h3>${t('about.obvody.title')}</h3>
    <ul class="links">
      ${about.obvody.map(
        (o) => html`<li>
          ${t(`about.obvody.${o.kind}`, { name: o.name })}
          ${' '}(${formatDate(o.date)}): <${Link} href=${o.source} />
        </li>`,
      )}
    </ul>
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
    <h3>${t('about.logos.title')}</h3>
    <ul class="links">
      ${about.logos.map((o) => html`<li>${o.name}: <${Link} href=${o.source}>${o.license}<//></li>`)}
    </ul>
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
      return html`<${Method} />`;
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
          ${section ? t(SECTIONS[section][0]) : t('about.title')}
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
