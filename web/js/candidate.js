/* The candidate card: the official data of one candidacy, every candidacy
 * of the same person (persons are merged by obec, name and age; see
 * candidates.py), and the state of the research on them. */

import { html, useEffect, useRef } from '../vendor/preact-htm.module.js';
import { Contest, FilterBar, notResearched, OfficeResult, OtherCandidacy, researchScope, useRowActions } from './ballots.js';
import {
  areaName,
  dataIndex,
  displayName,
  displayParties,
  findings,
  latestElection,
  officeLabel,
  otherElections,
  person,
  useLoaded,
} from './data.js';
import { election, formatDate, formatNumber, formatPercent, sourcesBase, t } from './i18n.js';
import { BackIcon, DisputeIcon, WarningIcon } from './icons.js';
import { NOT_COUNTED, useLive } from './live.js';
import { MapButton, useDrawnOkrsky } from './mapmode.js';
import { Notice } from './pane.js';

/* The kinds of finding in the card's order: serious controversies first,
 * as a voter must not miss them, then allegations and disputes, then the
 * career. Each kind of controversy has its mark's icon and a note on what
 * it holds. */
const KINDS = ['affair', 'dispute', 'cv'];
const KIND_ICON = { affair: WarningIcon, dispute: DisputeIcon };
const AFFAIRS_ID = 'km-affairs';

/* One finding: the AI's claim and its source at a glance. Behind a
 * disclosure, open for a serious controversy: the quote it rests on in its
 * own language (with a machine translation where that is not the page's),
 * and the cached copy the quote was checked against. */
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
            href=${`${sourcesBase}/cache/${f.cache}.html`}
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

/* The findings of the research on candidate *c*, by kind, loaded when
 * shown: only for a person who has some. */
function Findings({ candidate: c }) {
  const [list, failed] = useLoaded(() => findings(c), [c.id]);
  if (failed) return html`<p class="panel-body error">${t('error.load')}</p>`;
  if (!list) return html`<p class="panel-body muted">${t('panel.loading')}</p>`;
  return KINDS.map((kind) => {
    const group = list.filter((f) => f.kind === kind);
    if (!group.length) return null;
    const Icon = KIND_ICON[kind];
    return html`
      <h4 class=${`finding-kind ${kind}`} id=${kind === 'affair' ? AFFAIRS_ID : undefined}>
        ${Icon ? html`<${Icon} />` : null}${t(`research.kind.${kind}`)}${' '}<span class="count"
          >${formatNumber(group.length)}</span
        >
      </h4>
      ${Icon ? html`<p class="finding-kind-note">${t(`research.kind.${kind}_note`)}</p>` : null}
      <ul class="findings">
        ${group.map((f) => html`<${Finding} key=${f.url + f.quote} finding=${f} />`)}
      </ul>
    `;
  });
}

/* The research on candidate *c*: not done yet (said as such, never as
 * "nothing found"; on an earlier election's page, with why: research is
 * done on the latest election's candidates), or what was searched and the
 * result: nothing found, or the findings. Research reused from the latest
 * election (data.js `decodeResearch`) says so first: when it was done and
 * for which election, that no new research was done for this one, that
 * only findings published before its day are shown and how many undated
 * ones are left out. */
function Research({ candidate: c }) {
  const r = c.research;
  let state;
  if (!r) {
    state = html`<p class="panel-body research-state">
      <strong>${notResearched(c)}</strong> ${t('research.none_note')}
    </p>`;
  } else {
    const scope = t('research.scope', { scope: researchScope(r), date: formatDate(r.date) });
    state = html`<p class="panel-body research-state">
      ${scope}${' '}
      ${
        r.findings
          ? html`<strong>${t('research.found', { n: formatNumber(r.findings) })}</strong>`
          : html`<strong>${t('research.nothing')}</strong> ${t('research.nothing_note')}`
      }
    </p>`;
  }
  return html`
    <h3 class="group">${t('card.research')}</h3>
    <${Notice} summary=${t('research.notice_summary')}>${t('research.notice', { list: t('about.allowlist.title') })}<//>
    ${
      r?.reused
        ? html`<p class="panel-body research-reused">
            ${t('research.reused', { later: latestElection.slug, date: formatDate(r.date), day: formatDate(election) })}
            ${r.undated ? html`${' '}${t('research.reused_undated', { n: formatNumber(r.undated) })}` : null}
          </p>`
        : null
    }
    ${state}
    ${r?.findings ? html`<${Findings} candidate=${c} />` : null}
  `;
}

/* The person's candidacies in the other elections (data.js
 * `decodeElsewhere`), newest election first, each with how it went and a
 * link to its card there; persons are linked across elections by name,
 * age and place, which the note says is no proof. */
function Elsewhere({ candidate: c }) {
  const runs = otherElections.flatMap(({ slug }) => (c.elsewhere[slug] ?? []).map((run) => ({ slug, run })));
  if (!runs.length) return null;
  return html`
    <h3 class="group">${t('card.elsewhere')}</h3>
    <p class="panel-body muted">${t('card.elsewhere_note')}</p>
    <ul class="panel-body elsewhere">
      ${runs.map(({ slug, run }) => html`<li key=${run.id}><${OtherCandidacy} slug=${slug} run=${run} /></li>`)}
    </ul>
  `;
}

/* Research found serious controversies: said at the top of the card, with
 * a jump to them, rather than only far down among the findings. One line
 * in red, like the notices of the ballots, with the whole unfolded. */
function AffairsAlert({ candidate: c }) {
  const jump = () => document.getElementById(AFFAIRS_ID)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const n = formatNumber(c.research.affairs);
  return html`
    <${Notice}
      danger
      summary=${t('research.affairs_summary', { n })}
      jump=${{ label: t('research.affairs_show'), onClick: jump }}
    >${t('research.affairs_alert', { scope: researchScope(c.research), n })}<//>
  `;
}

// How many units the origins of the votes list each way.
const ORIGINS = 5;
// The share of a handful of ballots says little: the highest shares are
// those of the units with at least this many valid ballots (of all units,
// where fewer than two have as many).
const ORIGIN_VALID = 30;

/* Where candidate *c*'s votes in *contest* came from, once its results
 * give them by unit: by okrsok in the final results, else by obec or city
 * district (the contest's `areas`). Lists the units with the most of the
 * candidate's votes and those with the highest shares, beside the button
 * that shows the votes on the map (by the units of the zoom, mapmode.js).
 * Nothing for a contest of one unit. */
function VoteOrigins({ candidate: c, contest, index }) {
  const live = useLive();
  const drawn = useDrawnOkrsky();
  const entry = live.of(contest.id);
  if (!entry || entry === NOT_COUNTED) return null;
  const name = areaName(contest.id, index);
  const okrsky = live.hasOkrsky(name) ? live.okrsky(name)?.contests[contest.id] : null;
  // By okrsok where the map draws them, as it shows them zoomed in.
  const keys = Object.keys(okrsky ?? {});
  const byOkrsky = keys.length > 1 && keys.some((key) => drawn?.keys.has(key));
  // An okrsok key is '<obec>/<n>'; an area key an obec code or, on election
  // night, a regional obvod, which is not one of the contest's units.
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
        <h4>${t(`card.origins_${byOkrsky ? 'okrsky' : 'obce'}`)}</h4>
        <${MapButton} candidate=${c} label=${contest.label} />
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

/* The card of candidacy *id*. *filter* and `onFilter(next)` as for the
 * ballots (ballots.js): the other candidates of each of the person's
 * contests follow it, the person never. *picks* and `onPicks(next)`: the
 * circled candidates (picks.js). */
export function CandidateCard({ id, onCandidate, onClose, filter, onFilter, picks, onPicks }) {
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
      ${candidacies.map(
        (x) => html`<${Contest}
            key=${x.candidate.id}
            contest=${x.contest}
            current=${x.candidate}
            onCandidate=${onCandidate}
            filter=${filter}
            actions=${actions}
          />
          <${VoteOrigins} key=${`${x.candidate.id} origins`} candidate=${x.candidate} contest=${x.contest} index=${index} />`,
      )}
      <${Elsewhere} candidate=${c} />
      <${Research} candidate=${c} />
      <p class="panel-body muted small">${t('card.disclaimer')}</p>
    </section>
  `;
}
