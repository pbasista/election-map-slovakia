/* The candidate card: the official data of one candidacy, every candidacy
 * of the same person (persons are merged by obec, name and age; see
 * candidates.py), and the state of the research on them. */

import { html, useEffect, useRef } from '../vendor/preact-htm.module.js';
import { Contest, FilterBar, OfficeResult, researchScope, useRowActions } from './ballots.js';
import {
  areaName,
  contestArea,
  dataIndex,
  displayName,
  displayParties,
  findings,
  officeLabel,
  person,
  useLoaded,
} from './data.js';
import { formatDate, formatNumber, formatPercent, t } from './i18n.js';
import { BackIcon, DisputeIcon, MapPinIcon, WarningIcon } from './icons.js';
import { NOT_COUNTED, useLive } from './live.js';
import { candidateMode, setMapMode, useDrawnOkrsky, useMapMode } from './mapmode.js';
import { Notice } from './pane.js';

/* Serious controversies first: they are what a voter must not miss; then
 * allegations and disputes, then the career. Each controversy kind with
 * its mark's icon and a line on what it holds. */
const KINDS = ['affair', 'dispute', 'cv'];
const KIND_ICON = { affair: WarningIcon, dispute: DisputeIcon };
const AFFAIRS_ID = 'km-affairs';

/* One finding: the AI's claim and where it comes from at a glance; the
 * quote it rests on in the page's own language (and a machine translation
 * where that is not the page's) and the cached copy the quote was checked
 * against behind a disclosure, open for a serious controversy. */
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
        const Icon = KIND_ICON[kind];
        return group.length
          ? html`
              <h4 class=${`finding-kind ${kind}`} id=${kind === 'affair' ? AFFAIRS_ID : undefined}>
                ${Icon ? html`<${Icon} />` : null}${t(`research.kind.${kind}`)}${' '}<span class="count"
                  >${formatNumber(group.length)}</span
                >
              </h4>
              ${Icon ? html`<p class="finding-kind-note">${t(`research.kind.${kind}_note`)}</p>` : null}
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

// How many units the origins of the votes list each way.
const ORIGINS = 5;
// The share of a handful of ballots says little: the highest shares are
// those of the units with at least this many valid ballots (of all, where
// fewer than two have as many).
const ORIGIN_VALID = 30;

/* Where candidate *c*'s votes in *contest* came from, once its results
 * give them by unit: by okrsok in the final results, else by obec or city
 * district (the contest's `areas`). The units with the most of the
 * candidate's votes and those where the candidate had the highest share,
 * and a pin that shows the candidate's votes on the map (by the units of
 * the zoom, mapmode.js). Nothing for a contest of one unit. */
function VoteOrigins({ candidate: c, contest, index }) {
  const live = useLive();
  const current = useMapMode();
  const drawn = useDrawnOkrsky();
  const entry = live.of(contest.id);
  if (!entry || entry === NOT_COUNTED) return null;
  const name = areaName(contest.id, index);
  const okrsky = live.hasOkrsky(name) ? live.okrsky(name)?.contests[contest.id] : null;
  // By okrsok where the map draws them, as it shows them zoomed in.
  const keys = Object.keys(okrsky ?? {});
  const byOkrsky = keys.length > 1 && keys.some((key) => drawn?.keys.has(key));
  // An okrsok key is '<obec>/<n>'; an area an obec code, or on election
  // night a regional obvod, which is not one of the contest's units.
  const records = byOkrsky ? Object.entries(okrsky) : Object.entries(entry.areas ?? {}).filter(([key]) => index.obce[key]);
  const rows = records
    .filter(([, [, , valid]]) => valid)
    .map(([key, [, , valid, votes]]) => ({ key, votes: votes[c.number] ?? 0, valid }));
  if (rows.length < 2) return null;
  const obce = new Set(rows.map((r) => r.key.split('/')[0]));
  const unitName = (key) => {
    if (!byOkrsky) return index.obce[key]?.[0] ?? key;
    const [code, n] = key.split('/');
    const obec = index.obce[code]?.[0] ?? code;
    return obce.size > 1 ? t('card.origins_okrsok_in', { n, name: obec }) : t('card.origins_okrsok', { n });
  };
  const most = [...rows].sort((a, b) => b.votes - a.votes).slice(0, ORIGINS);
  const sizeable = rows.filter((r) => r.valid >= ORIGIN_VALID);
  const highest = [...(sizeable.length > 1 ? sizeable : rows)]
    .sort((a, b) => b.votes / b.valid - a.votes / a.valid)
    .slice(0, ORIGINS);
  const by = byOkrsky ? 'okrsky' : 'obce';
  const on = current?.kind === 'candidate' && current.id === c.id;
  const label = t(on ? 'mapmode.candidate_hide' : 'mapmode.candidate_show');
  const list = (items) => html`<ol class="origins-list">
    ${items.map(
      (r) => html`<li key=${r.key}>
        <span class="origins-unit">${unitName(r.key)}</span>
        <span class="origins-figures">${formatNumber(r.votes)} · ${formatPercent(r.votes / r.valid)}</span>
      </li>`,
    )}
  </ol>`;
  return html`
    <div class="origins panel-body">
      <div class="origins-head">
        <h4>${t(`card.origins_${by}`)}</h4>
        <button
          type="button"
          class="votes-map"
          aria-pressed=${on ? 'true' : 'false'}
          title=${label}
          aria-label=${label}
          onClick=${() => setMapMode(on ? null : candidateMode(c, contest))}
        >
          <${MapPinIcon} />
        </button>
      </div>
      <div class="origins-columns">
        <section>
          <h5>${t('card.origins_most')}</h5>
          ${list(most)}
        </section>
        <section>
          <h5>${t('card.origins_highest')}</h5>
          ${list(highest)}
        </section>
      </div>
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
          />
          <${VoteOrigins} key=${`${x.candidate.id} origins`} candidate=${x.candidate} contest=${x.contest} index=${index} />`;
      })}
      <${Research} candidate=${c} />
      <p class="panel-body muted small">${t('card.disclaimer')}</p>
    </section>
  `;
}
