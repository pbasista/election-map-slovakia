/* The candidate card: the official data of one candidacy, every candidacy
 * of the same person (persons are merged by obec, name and age; see
 * candidates.py), and the state of the research on them. */

import { html, useEffect, useRef } from '../vendor/preact-htm.module.js';
import { Contest, FilterBar, OfficeResult, researchScope, useRowActions } from './ballots.js';
import {
  contestArea,
  dataIndex,
  displayName,
  displayParties,
  findings,
  officeLabel,
  person,
  useLoaded,
} from './data.js';
import { formatDate, formatNumber, t } from './i18n.js';
import { BackIcon, WarningIcon } from './icons.js';
import { Notice } from './pane.js';

// Controversies first: they are what a voter must not miss.
const KINDS = ['affair', 'cv'];
const AFFAIRS_ID = 'km-affairs';

/* One finding: the AI's claim and where it comes from at a glance; the
 * quote it rests on in the page's own language (and a machine translation
 * where that is not the page's) and the cached copy the quote was checked
 * against behind a disclosure, open for a controversy. */
function Finding({ finding: f }) {
  const host = new URL(f.url).hostname.replace(/^www\./, '');
  return html`
    <li class=${`finding ${f.kind}`}>
      <p class="claim">${f.claim}</p>
      <p class="finding-source">
        <a href=${f.url} title=${f.title || f.url} rel="noopener noreferrer" target="_blank">${host}</a>
        ${f.published ? html`<span class="muted"> · ${formatDate(f.published)}</span>` : null}
      </p>
      <details class="evidence" open=${f.kind === 'affair'}>
        <summary>${t('research.quote')}</summary>
        <blockquote lang=${f.language} cite=${f.url}>${f.quote}</blockquote>
        ${
          f.quoteTranslated
            ? html`<p class="translated">
                <span class="mt" title=${t('research.machine_note')}>${t('research.machine')}</span>
                ${' '}${f.quoteTranslated}
              </p>`
            : null
        }
        <p class="evidence-links">
          ${f.title ? html`<span class="page-title">${f.title}</span> · ` : null}<a
            href=${`/cache/${f.cache}.html`}
            title=${t('research.cached_note')}
            rel="noopener noreferrer"
            target="_blank"
            >${t('research.cached')}</a
          >
        </p>
      </details>
    </li>
  `;
}

/* The research on candidate *c*: not done yet (said as such, never as
 * "nothing found"), or what was searched and then the result: nothing
 * found, or its findings by kind, loaded only for a person who has some. */
function Research({ candidate: c }) {
  const r = c.research;
  const [list, failed] = useLoaded(() => (r?.findings ? findings(c) : Promise.resolve([])), [c.id]);

  let body;
  if (!r) {
    body = html`<p class="panel-body research-state">
      <strong>${t('research.none')}</strong> ${t('research.none_note')}
    </p>`;
  } else {
    const scope = t('research.scope', { scope: researchScope(r), date: formatDate(r.date) });
    const state = html`<p class="panel-body research-state">
      ${scope}${' '}
      ${
        r.findings
          ? html`<strong>${t('research.found', { n: formatNumber(r.findings) })}</strong>`
          : html`<strong>${t('research.nothing')}</strong> ${t('research.nothing_note')}`
      }
    </p>`;
    let found = null;
    if (r.findings && failed) found = html`<p class="panel-body error">${t('error.load')}</p>`;
    else if (r.findings && !list) found = html`<p class="panel-body muted">${t('panel.loading')}</p>`;
    else if (r.findings) {
      found = KINDS.map((kind) => {
        const group = list.filter((f) => f.kind === kind);
        return group.length
          ? html`
              <h4 class=${`finding-kind ${kind}`} id=${kind === 'affair' ? AFFAIRS_ID : undefined}>
                ${kind === 'affair' ? html`<${WarningIcon} />` : null}${t(`research.kind.${kind}`)}${' '}<span
                  class="count"
                  >${formatNumber(group.length)}</span
                >
              </h4>
              <ul class="findings">
                ${group.map((f) => html`<${Finding} key=${f.url + f.quote} finding=${f} />`)}
              </ul>
            `
          : null;
      });
    }
    body = html`${state}${found}`;
  }
  return html`
    <h3 class="group">${t('card.research')}</h3>
    <${Notice}>${t('research.notice', { list: t('about.allowlist.title') })}<//>
    ${body}
  `;
}

/* Research found controversies: said at the top of the card, with a jump
 * to them, rather than only far down among the findings. */
function AffairsAlert({ candidate: c }) {
  const jump = () => document.getElementById(AFFAIRS_ID)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return html`
    <div class="affairs-alert" role="note">
      <${WarningIcon} />
      <p>${t('research.affairs_alert', { scope: researchScope(c.research), n: formatNumber(c.research.affairs) })}</p>
      <button type="button" class="link" onClick=${jump}>${t('research.affairs_show')}</button>
    </div>
  `;
}

/* *filter* and `onFilter(next)` as for the ballots (ballots.js): the other
 * candidates of each of the person's contests follow it; the person never.
 * *picks* and `onPicks(next)` the circled candidates (picks.js). */
export function CandidateCard({ id, onCandidate, onPlace, onClose, filter, onFilter, picks, onPicks }) {
  // Null for a candidacy that does not exist.
  const [result, failed] = useLoaded(
    () => Promise.all([person(id), dataIndex()]).then(([p, index]) => p && { ...p, index }),
    [id],
  );
  const heading = useRef(null);
  const section = useRef(null);
  const actions = useRowActions(
    section,
    new Map((result?.candidacies ?? []).flatMap((x) => x.contest.candidates.map((c) => [c.id, c]))),
    filter,
    onFilter,
    picks,
    onPicks,
  );

  useEffect(() => {
    heading.current?.focus();
  }, [result]);

  // An icon in the corner of the header, beside the name: no line of its own.
  const back = html`<button type="button" class="back" aria-label=${t('card.back')} title=${t('card.back')} onClick=${onClose}>
    <${BackIcon} />
  </button>`;
  if (failed || result === null) {
    return html`<section class="card">
      <header class="panel-head has-back">${back}<p class="error">${t('card.missing')}</p></header>
    </section>`;
  }
  if (!result) {
    return html`<section class="card">
      <header class="panel-head has-back">${back}<p class="muted loading">${t('panel.loading')}</p></header>
    </section>`;
  }

  const { candidate: c, candidacies, index } = result;
  const residence = c.residence ? index.obce[c.residence]?.[0] : null;
  return html`
    <section class="card" aria-labelledby="km-card-name" ref=${section}>
      <header class="panel-head has-back">
        ${back}
        <div>
          <h2 id="km-card-name" tabindex="-1" ref=${heading}>${displayName(c)}</h2>
          <p class="muted">${t('candidate.age', { n: c.age })} · ${c.occupation}</p>
          ${
            c.occupationSk
              ? html`<p class="muted small">${t('candidate.occupation_sk', { text: c.occupationSk })}</p>`
              : null
          }
        </div>
      </header>
      ${c.research?.affairs ? html`<${AffairsAlert} candidate=${c} />` : null}
      <${FilterBar} filter=${filter} onFilter=${onFilter} actions=${actions} />
      <dl class="facts panel-body">
        <dt>${t('card.parties')}</dt>
        <dd>${displayParties(c)}</dd>
        ${residence ? html`<dt>${t('card.residence')}</dt><dd>${residence}</dd>` : null}
        ${
          c.offices.length
            ? html`<dt class="wide">${t('card.offices')}</dt>
                <dd class="wide">
                  <ul class="offices">
                    ${c.offices.map((o) => {
                      const since = t('card.office_since', { date: formatDate(o.since) });
                      const unit = o.result.obvod === null ? null : t('card.result_obvod', { n: o.result.obvod });
                      return html`<li key=${o.body}>
                        ${officeLabel(o.body, index)}
                        <span class="muted small"> (${unit ? `${since}, ${unit}` : since})</span>
                        <${OfficeResult} result=${o.result} />
                      </li>`;
                    })}
                  </ul>
                </dd>`
            : null
        }
      </dl>
      <h3 class="group">${t('card.candidacies')}</h3>
      ${candidacies.length > 1 ? html`<p class="panel-body muted">${t('card.merged')}</p>` : null}
      ${candidacies.map((x) => {
        const target = contestArea(x.contest.id, index);
        return html`<${Contest}
          key=${x.candidate.id}
          contest=${x.contest}
          current=${x.candidate}
          onCandidate=${onCandidate}
          filter=${filter}
          actions=${actions}
          map=${{ label: t(`card.map_${target.what}`), onClick: () => onPlace(target) }}
        />`;
      })}
      <${Research} candidate=${c} />
      <p class="panel-body muted small">${t('card.disclaimer')}</p>
    </section>
  `;
}
