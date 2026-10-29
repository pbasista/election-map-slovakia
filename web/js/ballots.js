/* The ballots of one place: every contest a voter there votes in, each with
 * its candidates in ballot order, or by votes once the 2026 results come
 * in (live.js). data.js `ballots` decides which contests apply. */

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { ballots, candidacyUrl, displayName, inOffice, latestElection, officeOf, ranBefore, useLoaded } from './data.js';
import {
  election,
  formatDate,
  formatList,
  formatNumber,
  formatPercent,
  logoUrl,
  polls,
  previous,
  researchCategories,
  t,
} from './i18n.js';
import {
  ChairIcon,
  CloseIcon,
  CrossOutIcon,
  DisputeIcon,
  EyeIcon,
  EyeOffIcon,
  FilterOffIcon,
  HistoryIcon,
  InkCircle,
  InkCross,
  MedalIcon,
  MedalOutlineIcon,
  SearchIcon,
  WarningIcon,
  WithdrawnIcon,
} from './icons.js';
import {
  decodeResults,
  isSingle,
  NOT_COUNTED,
  PAST,
  pastLabel,
  pastTitle,
  placeResults,
  resultsVars,
  SCOPES,
  useLive,
} from './live.js';
import { MapButton, TurnoutMapButton, WinnerMapButton } from './mapmode.js';
import { Notice } from './pane.js';
import { formatPicks, parsePicks, togglePick } from './picks.js';

/* The candidate filter, which app.js keeps across places and in the URL
 * (filterParams):
 * - parties: those chosen, {short, name, logo, mode}, INDEPENDENT among
 *   them; `mode` 'only' shows only the candidates of such parties, 'hide'
 *   hides the party's;
 * - marks: mark name (MARKS) → its mode likewise, for each mark added;
 * - crossed: the candidacies the visitor has crossed out (ids as in
 *   picks.js), each muted.
 * Muted candidates stay on the list, faded and after the others. */
export const NO_FILTER = { parties: [], marks: {}, crossed: [] };

/* The independent candidates, a member of the party filter like a party,
 * named in the page's language where shown. No party's name is empty. */
const INDEPENDENT = { short: '', name: '', logo: null };
const partyName = (p) => p.name || t('candidate.independent');
const partyShort = (p) => (p.name ? p.short : t('candidate.independent_short'));

/* An element id of the component's own: the same contest may show in the
 * pane and in Favourites beside it at once. */
let serial = 0;
function useOwnId(prefix) {
  const id = useRef(null);
  id.current ??= `${prefix}-${++serial}`;
  return id.current;
}

/* Whether candidate *c* stands for the party named *name* (INDEPENDENT's:
 * for none). A coalition's candidate stands for each of its parties. */
const standsFor = (c, name) =>
  name === INDEPENDENT.name ? !c.parties.length : c.parties.some((p) => p.name === name);

/* The marks of a row that are filters too, in the bar's order, each with
 * whom it covers:
 * - elected: elected at the page's election, officially or called by this
 *   site on a partial count (live.js `decodeResults`);
 * - affairs: research found serious controversies;
 * - disputes: research found disputed or lesser ones;
 * - researched: research done, whatever it found;
 * - office: held the office the contest elects at the time of the
 *   election (the chair); not for an election whose office holders are
 *   not known (i18n.js `previous` null), so no link can filter by it. */
const MARKS = [
  { name: 'elected', covers: (c) => Boolean(c.result?.elected || c.result?.called), Icon: MedalIcon },
  { name: 'affairs', covers: (c) => Boolean(c.research?.affairs), Icon: WarningIcon },
  { name: 'disputes', covers: (c) => Boolean(c.research?.disputes), Icon: DisputeIcon },
  { name: 'researched', covers: (c) => Boolean(c.research), Icon: SearchIcon },
  ...(previous ? [{ name: 'office', covers: inOffice, Icon: ChairIcon }] : []),
];

const mutedBy = (mode, member) => (mode === 'hide' && member) || (mode === 'only' && !member);

/* Whether *filter* mutes candidate *c*: crossed out, of none of the
 * parties shown where some are, of a party hidden, or muted by a mark. */
function isMuted(c, filter) {
  const shown = filter.parties.filter((p) => p.mode === 'only');
  return (
    filter.crossed.includes(c.id) ||
    (shown.length > 0 && !shown.some((p) => standsFor(c, p.name))) ||
    filter.parties.some((p) => p.mode === 'hide' && standsFor(c, p.name)) ||
    MARKS.some(({ name, covers }) => name in filter.marks && mutedBy(filter.marks[name], covers(c)))
  );
}

/* The filter as [key, value] pairs of the URL hash (app.js), none for a
 * group not used:
 * - fp: the parties by their short forms (unique, see config.py
 *   `load_parties`), "-" for the independents; those shown first, then
 *   the hidden ones, each after a "!" (so that a list starting with one
 *   hides them all, as links did when all parties had one mode);
 * - fm: the marks added, each after a "!" when hidden;
 * - x: the candidacies crossed out, written as picks.js writes circles. */
export function filterParams(filter) {
  const params = [];
  const hide = (mode) => (mode === 'hide' ? '!' : '');
  if (filter.parties.length) {
    const parties = [...filter.parties.filter((p) => p.mode === 'only'), ...filter.parties.filter((p) => p.mode === 'hide')];
    params.push(['fp', parties.map((p) => hide(p.mode) + (p.name ? p.short : '-')).join(',')]);
  }
  const marks = MARKS.filter(({ name }) => name in filter.marks).map(({ name }) => hide(filter.marks[name]) + name);
  if (marks.length) params.push(['fm', marks.join(',')]);
  if (filter.crossed.length) params.push(['x', formatPicks(filter.crossed)]);
  return params;
}

/* The filter that hash values *fp*, *fm* and *x* (filterParams) name, the
 * parties looked up by short form in data/index.json's *parties*. What is
 * not known there (a party gone since the link was made) is dropped. */
export function parseFilter({ fp, fm, x }, parties) {
  const known = new Map(
    Object.values(parties).map(([short, name, logo = null]) => [short, { short, name, logo: logo && logoUrl(logo) }]),
  );
  const allHidden = (fp ?? '').startsWith('!');
  const chosen = new Map();
  for (const token of (fp ?? '').split(',')) {
    const short = token.replace(/^!/, '');
    const p = short === '-' ? INDEPENDENT : known.get(short);
    if (p) chosen.set(p.name, { ...p, mode: allHidden || token.startsWith('!') ? 'hide' : 'only' });
  }
  const marks = {};
  for (const token of (fm ?? '').split(',')) {
    const name = token.replace(/^!/, '');
    if (MARKS.some((mark) => mark.name === name)) marks[name] = token.startsWith('!') ? 'hide' : 'only';
  }
  return { parties: [...chosen.values()], marks, crossed: parsePicks(x) };
}

/* What the research on a candidate searched, said before any result: the
 * source categories of its research languages ("Slovak media and official
 * sites"). */
export function researchScope(r) {
  const categories = new Set(r.languages.flatMap((code) => researchCategories[code] ?? []));
  return formatList([...categories].map((c) => t(`research.scope.${c}`)));
}

/* The research.* strings' variables for research *r*, *n* its count. */
const researchVars = (r, n) => ({ scope: researchScope(r), date: formatDate(r.date), n: formatNumber(n) });

/* Why candidate *c* is not researched. Research is done on the latest
 * election's candidates: there, not yet; on an earlier election's page, a
 * person not linked to one of them gets none, nor one whose linked
 * candidate is not researched yet. */
export function notResearched(c) {
  if (election === latestElection.day) return t('research.none');
  const key = c.elsewhere[latestElection.slug] ? 'research.none_later' : 'research.not_linked';
  return t(key, { later: latestElection.slug });
}

/* For research reused from the latest election (data.js `decodeResearch`
 * `reused`), what it counts of it: *label* followed by that, else *label*. */
const withReuse = (r, label) =>
  r.reused ? `${label} ${t('research.reused_badge', { later: latestElection.slug, day: formatDate(election) })}` : label;

/* The note on documents that state no date (data.js `ballots` `origin`
 * `dating`, `okrskyDating`): *lead* followed by what dates them. A capture
 * or posting before the vote bounds them only from above. */
const DATED = {
  archived: 'notice.dated_archived',
  posted: 'notice.dated_posted',
  named: 'notice.dated_named',
};
const dated = (lead, { by, seen }) => `${lead} ${t(DATED[by], { date: seen ? formatDate(seen) : '' })}`;

/* The note on rules a later source fills in (data.js `ballots` `origin`
 * `supplemented`, `okrskySupplemented`): *lead* followed by which source
 * and that the election's state may have differed. */
const SUPPLEMENTED = {
  election: 'notice.supplemented_election',
  referendum: 'notice.supplemented_referendum',
  document: 'notice.supplemented_document',
};
const supplemented = (lead, { from, day }) => `${lead} ${t(SUPPLEMENTED[from], { later: day.slice(0, 4) })}`;

/* A candidate's occupation; a machine translation names the Slovak
 * original in its tooltip (the card shows it in full). */
export function Occupation({ candidate: c }) {
  return c.occupationSk
    ? html`<span title=${t('candidate.occupation_sk', { text: c.occupationSk })}>${c.occupation}</span>`
    : c.occupation;
}

/* A candidate's nominating parties as their short forms or logos (or the
 * independent tag), the official name in the tooltip and for screen
 * readers; the candidate card spells them out. With *actions* (the
 * ballots), each is a button: pointing at or focusing it highlights the
 * party's candidates; a press shows only the candidates of the parties so
 * chosen, the alternate press (useRowActions `tap`) hides the party's, and
 * either, pressed again, takes the party out of the filter. */
function Parties({ candidate: c, actions }) {
  return (c.parties.length ? c.parties : [INDEPENDENT]).map((p) => {
    const name = partyName(p);
    const cls = p === INDEPENDENT ? 'party independent' : 'party';
    if (!actions) {
      return p.logo
        ? html`<img class="party-logo" src=${p.logo} alt=${name} title=${name} />`
        : html`<span class=${cls} title=${name} aria-label=${name}>${partyShort(p)}</span>`;
    }
    const mode = actions.partyMode(p.name);
    const label = t(`filter.party_${mode ?? 'none'}`, { name });
    return html`<button
      type="button"
      class=${`party-button${activeClass(mode)}`}
      title=${label}
      aria-label=${label}
      ...${actions.hoverProps(p.name)}
      ...${actions.partyTap(p)}
    >
      ${p.logo ? html`<img class="party-logo" src=${p.logo} alt="" />` : html`<span class=${cls}>${partyShort(p)}</span>`}
    </button>`;
  });
}

/* The classes of a badge in the filter in *mode*: ringed, and struck
 * through while its candidates are hidden. */
const activeClass = (mode) => (mode === 'hide' ? ' active excluded' : mode ? ' active' : '');

/* A mark after the parties, explained by *label* in its tooltip and for
 * screen readers. With *actions* (the ballots), a button that adds mark
 * *name* (MARKS) to the filter as the party tags add a party. */
function Mark({ name, cls, label, actions, children }) {
  if (!actions) return html`<span class=${cls} role="img" title=${label} aria-label=${label}>${children}</span>`;
  const mode = actions.markMode(name);
  const full = `${label} ${t(`filter.mark_${mode ?? 'none'}`, { name: t(`filter.${name}`) })}`;
  return html`<button type="button" class=${cls + activeClass(mode)} title=${full} aria-label=${full} ...${actions.markTap(name)}>
    ${children}
  </button>`;
}

/* The numbers of a decoded office result (data.js `decodeResult`) as the
 * result.* strings take them. */
const resultVars = (r) => ({
  votes: formatNumber(r.votes),
  valid: formatNumber(r.valid),
  voters: formatNumber(r.voters),
  eligible: formatNumber(r.eligible),
  turnout: formatPercent(r.voters / r.eligible),
});

/* The votes behind the shares of a result: of the valid ballots (for a
 * council: of the voters with a valid ballot), and of all registered
 * voters with how many of them voted. */
const resultCounts = (r) => [
  t(r.multi ? 'result.count_voters' : 'result.count_valid', resultVars(r)),
  t('result.count_eligible', resultVars(r)),
];

const width = (share) => `${(share * 100).toFixed(1)}%`;

/* How an office was won, one meter per line: the share of the valid
 * ballots (for a council: of the voters with a valid ballot) beside the
 * votes and ballots; then the share of all registered voters, the turnout
 * shaded behind it, beside their number and the turnout. The pane being
 * narrow, the second line leaves the votes to the first. The tooltips
 * give the counts in full. */
export function OfficeResult({ result: r }) {
  const [ofValid, ofAll] = resultCounts(r);
  const vars = resultVars(r);
  const share = r.votes / r.valid;
  const all = r.votes / r.eligible;
  const turnout = r.voters / r.eligible;
  return html`<div class="won">
    <span class="meter" title=${ofValid}>
      <strong>${formatPercent(share)}</strong>
      <span class="bar" aria-hidden="true"><span class="fill" style=${{ width: width(share) }}></span></span>
      <span class="caption">${t(r.multi ? 'result.share_voters' : 'result.share_valid', vars)}</span>
    </span>
    <span class="meter" title=${ofAll}>
      <strong>${formatPercent(all)}</strong>
      <span class="bar" aria-hidden="true">
        <span class="turnout" style=${{ width: width(turnout) }}></span>
        <span class="fill" style=${{ width: width(all) }}></span>
      </span>
      <span class="caption">${t('result.share_eligible', { ...vars, turnout: formatPercent(turnout, 0) })}</span>
    </span>
  </div>`;
}

/* The candidate held the office the contest elects at the time of the
 * election (later changes are not known): a chair with the
 * share of the vote that won it, the votes in the tooltip (the card charts
 * them). */
function InOffice({ candidate: c, actions }) {
  const office = c.offices.find((o) => o.body === officeOf(c.contest));
  const r = office.result;
  const label = [t('candidate.in_office_since', { date: formatDate(office.since) }), ...resultCounts(r)].join(' ');
  return html`<${Mark} name="office" cls="in-office" label=${label} actions=${actions}>
    <${ChairIcon} />${formatPercent(r.votes / r.valid, 0)}
  <//>`;
}

/* How a candidacy in another election went (data.js `decodeElsewhere`
 * *run*, in the election of *slug*): the year and contest, elected or not,
 * the votes with their share of the valid ballots (for a council: of the
 * voters with a valid ballot) and the place among the contest's
 * candidates; a link opens its card on that election's page. */
export function OtherCandidacy({ slug, run }) {
  const outcome =
    run.votes === null
      ? t('ran.no_result')
      : t(run.elected ? 'ran.elected' : run.withdrew ? 'ran.withdrew' : 'ran.not_elected');
  const result =
    run.votes === null
      ? null
      : t(run.multi ? 'ran.result_multi' : 'ran.result', {
          votes: formatNumber(run.votes),
          share: formatPercent(run.votes / run.valid),
          rank: formatNumber(run.rank),
          of: formatNumber(run.of),
        });
  return html`<span class="other-run">
    <span><strong>${slug}</strong> · ${run.label}</span>
    <span class=${run.elected ? 'other-outcome elected-then' : 'other-outcome'}>${outcome}</span>${
      result ? html` · <span>${result}</span>` : null
    }
    <a class="other-open" href=${candidacyUrl(slug, run.id)}>${t('ran.open', { when: slug })}</a>
  </span>`;
}

/* The candidate stood for the same office at the election before (data.js
 * `ranBefore`): a clock turned back beside the chair, in the grey of past
 * figures. Not a filter like the other marks: a press shows how it went
 * then on a line under the name (*detail* the id of that line), pressed
 * again hides it. */
function RanBefore({ run, open, onToggle, detail }) {
  const label = t('ran.label', { when: run.election.slug });
  return html`<button
    type="button"
    class=${open ? 'ran-before active' : 'ran-before'}
    title=${label}
    aria-label=${label}
    aria-expanded=${open ? 'true' : 'false'}
    aria-controls=${detail}
    onClick=${onToggle}
  >
    <${HistoryIcon} />
  </button>`;
}

/* The state of the research on a candidate: the number of findings, a
 * faint magnifier where it found nothing, a dashed one while not done.
 * The tooltip says what was searched before the result; the card shows
 * the findings. */
function Researched({ candidate: c, actions }) {
  const r = c.research;
  if (!r) {
    return html`<${Mark} name="researched" cls="researched not" label=${notResearched(c)} actions=${actions}>
      <${SearchIcon} />
    <//>`;
  }
  const vars = researchVars(r, r.findings);
  return html`<${Mark}
    name="researched"
    cls=${r.findings ? 'researched' : 'researched none'}
    label=${withReuse(r, r.findings ? t('research.badge', vars) : t('research.badge_none', vars))}
    actions=${actions}
    ><${SearchIcon} />${r.findings ? formatNumber(r.findings) : null}<//>`;
}

/* Research found controversies (*name* 'affairs' or 'disputes', MARKS):
 * the mark's icon with their number. The serious ones (a red warning
 * sign) come first among the marks, so that they are not passed over;
 * disputed or lesser ones (allegations not established) follow in amber,
 * without flagging the row. */
function Controversies({ candidate: c, name, actions }) {
  const r = c.research;
  const { Icon } = MARKS.find((mark) => mark.name === name);
  const vars = researchVars(r, r[name]);
  return html`<${Mark} name=${name} cls=${name} label=${withReuse(r, t(`research.${name}_badge`, vars))} actions=${actions}>
    <${Icon} />${vars.n}
  <//>`;
}

/* Elected in 2026: the medal alone in the results' green, without the
 * ring every other badge has, as only winning earns it; right after the
 * name, before the parties, as in these elections a person is elected,
 * not a party. Called by this site on a partial count, not officially yet,
 * it is drawn in outline, and its tooltip says what the call rests on
 * (live.js `GROWTH`). A council's substitutes go unmarked: they are all
 * its other candidates with a vote, in the order the list shows already. */
function Elected({ candidate: c, actions }) {
  const r = c.result;
  if (!r.elected && !r.called) return null;
  let label = t('results.elected');
  if (!r.elected) {
    label =
      r.call.bound === null
        ? t('results.called_complete')
        : t('results.called', {
            remaining: formatNumber(r.call.remaining),
            bound: formatNumber(r.call.bound),
            election: pastElection(r.past),
            eligible: formatNumber(r.eligible),
          });
  }
  return html`<${Mark} name="elected" cls=${r.elected ? 'elected' : 'elected called'} label=${label} actions=${actions}>
    ${r.elected ? html`<${MedalIcon} />` : html`<${MedalOutlineIcon} />`}
  <//>`;
}

/* Withdrew from the election yet stayed on the ballot: a grey door with an
 * arrow, right after the name where the medal would be, as such a
 * candidate cannot be elected. Not a filter mark. */
function Withdrawn() {
  return html`<${Mark} cls="withdrawn-mark" label=${t('results.withdrawn_title')}><${WithdrawnIcon} /><//>`;
}

/* A candidate's 2026 votes: their share on a bar in the results' green,
 * then the number. A candidate who withdrew yet stayed on the ballot,
 * whose votes count, in grey and tagged so. */
function Votes({ candidate: c }) {
  const r = c.result;
  if (r.share === null) return null;
  const label = t(r.multi ? 'results.votes_title_multi' : 'results.votes_title', {
    votes: formatNumber(r.votes),
    valid: formatNumber(r.valid),
    share: formatPercent(r.share),
  });
  return html`<span class=${r.withdrawn ? 'votes withdrawn-votes' : 'votes'} title=${label}>
    <span class="votes-bar" aria-hidden="true"><span style=${{ width: width(r.share) }}></span></span>
    <strong>${formatPercent(r.share)}</strong>
    <span>${t('results.votes', { n: formatNumber(r.votes) })}</span>
    ${r.withdrawn ? html`<span class="withdrawn" title=${t('results.withdrawn_title')}>${t('results.withdrawn')}</span>` : null}
  </span>`;
}

/* One candidacy.
 * - The ballot number is a button that circles it, as a voter circles
 *   numbers on the ballot; the alternate press (useRowActions `tap`)
 *   crosses it out instead, and the filter then mutes it. Pressed again,
 *   either is undone.
 * - The name is the button that opens the card (as does a click anywhere
 *   else on the row), followed by the parties and, apart from those, the
 *   marks: what is known about the candidate. Party tags and marks are
 *   buttons of their own.
 * - Once counted, a button at the row's end, with the folded map of the
 *   winner map's in the header, shows the candidate's votes on the map
 *   (mapmode.js `MapButton`).
 * - Where the candidate stood for the same office at the election before,
 *   a mark beside the chair unfolds how that went on a line of the row's
 *   own (RanBefore, OtherCandidacy).
 * *actions*: see useRowActions; the row of the party pointed at is
 * highlighted there. *muted*: the filter fades the row. *seat* ({place,
 * seats, end}, `seatPlaces`): on a partial count of a council, a place
 * that would win a seat so far, its number in the results' green and said
 * to screen readers; `end`, the last of them before a row that is not,
 * draws a labelled dashed line under it. */
export function CandidateRow({ candidate, onCandidate, current = false, actions, muted = false, seat = null }) {
  const c = candidate;
  const flagged = Boolean(c.research?.affairs);
  const picked = actions.isPicked(c.id);
  const crossed = !picked && actions.isCrossed(c.id);
  const metaId = useOwnId('km-meta');
  const before = ranBefore(c);
  const beforeId = useOwnId('km-before');
  const [showBefore, setShowBefore] = useState(false);
  const classes = [
    'cand',
    current && 'current',
    flagged && 'flagged',
    crossed && 'crossed',
    muted && 'dimmed',
    seat && 'in-seats',
    seat?.end && 'seats-end',
  ];
  const state = crossed ? t('pick.crossed_state') : muted ? t('filter.muted') : null;
  return html`
    <div
      class=${classes.filter(Boolean).join(' ')}
      onClick=${(e) => {
        // The row's own buttons and links do what they say, and the line of
        // the election before is read; the rest opens the card.
        if (!e.target.closest('button, a, .ran-detail')) onCandidate(c.id);
      }}
    >
      <button
        type="button"
        class="num"
        aria-pressed=${picked ? 'true' : 'false'}
        aria-label=${t('pick.label', { n: c.number })}
        title=${t(picked ? 'pick.remove' : crossed ? 'pick.uncross' : 'pick.add', { n: c.number })}
        ...${actions.pickTap(c.id)}
      >
        ${c.number}<${InkCircle} /><${InkCross} />
      </button>
      <span class="who">
        <span class="name-line">
          <button
            type="button"
            class="cand-open"
            aria-current=${current ? 'true' : undefined}
            aria-describedby=${metaId}
            data-candidate=${c.id}
            onClick=${() => onCandidate(c.id)}
          >
            <span class="sr-only">${t('candidate.number', { n: c.number })} </span>
            <span class="name">${displayName(c)}</span>
            ${state ? html`<span class="sr-only"> (${state})</span>` : null}
          </button>
          ${' '}${c.result ? html`<${Elected} candidate=${c} actions=${actions} />` : null}
          ${c.result?.withdrawn ? html`<${Withdrawn} />` : null}
          <${Parties} candidate=${c} actions=${actions} />
          <span class="marks">
            ${flagged ? html`<${Controversies} candidate=${c} name="affairs" actions=${actions} />` : null}
            ${c.research?.disputes ? html`<${Controversies} candidate=${c} name="disputes" actions=${actions} />` : null}
            ${inOffice(c) ? html`<${InOffice} candidate=${c} actions=${actions} />` : null}
            ${
              before
                ? html`<${RanBefore}
                    run=${before}
                    open=${showBefore}
                    onToggle=${() => setShowBefore(!showBefore)}
                    detail=${beforeId}
                  />`
                : null
            }
            <${Researched} candidate=${c} actions=${actions} />
          </span>
        </span>
        ${c.result ? html`<${Votes} candidate=${c} />` : null}
        ${seat ? html`<span class="sr-only">${t('results.in_seats', { place: seat.place, n: formatNumber(seat.seats) })}</span>` : null}
        <span class="meta" id=${metaId}>${t('candidate.age', { n: c.age })} · <${Occupation} candidate=${c} /></span>
        ${
          before && showBefore
            ? html`<span class="ran-detail" id=${beforeId}><${OtherCandidacy} slug=${before.election.slug} run=${before} /></span>`
            : null
        }
      </span>
      ${c.result && c.result.share !== null ? html`<${MapButton} candidate=${c} label=${c.result.contestLabel} />` : null}
      ${
        seat?.end
          ? html`<span class="seats-line" title=${t('results.seats_line_title', { n: formatNumber(seat.seats) })} aria-hidden="true">
              ${t('results.seats_line', { n: formatNumber(seat.seats) })}
            </span>`
          : null
      }
    </div>
  `;
}

/* The kinds of contest the visitor has closed. They stay closed on the
 * ballots of every other place, so that one can go through, say, council
 * candidates without the mayoral ones listed first. Bratislava's and
 * Košice's city contests are kinds of their own. */
const closedKinds = new Set();

function contestKind(id) {
  const [kind, area] = id.split(':');
  return /^(BA|KE)\b/.test(area) ? `${kind}:city` : kind;
}

/* What stands under a contest's name:
 * - how many are elected: one mayor or president; a council's seats where
 *   known (from the decisions on the obvody, else from the 2026 results
 *   once they give them), otherwise the 2022 number, labelled so;
 * - how many stand, and how many of them the filter leaves shown
 *   (*unmuted*) where it mutes some;
 * - how many the visitor has circled (*picked*), if any. With more
 *   circled than are elected, which would make a real ballot invalid,
 *   both numbers carry a warning. Circling more is still allowed: the
 *   visitor may circle a shortlist to choose from later.
 * Once the count reaches the contest, a line says how far it has got
 * (ResultsLine); a contest without a final result (data.js `noResult`)
 * says so instead. *id*: the element's, which the header's button refers
 * to. */
function ContestFacts({ id, contest, unmuted, picked, results, pending }) {
  const n = contest.candidates.length;
  const single = isSingle(contest.id);
  const seats = contest.seats ?? results?.reportedSeats ?? null;
  const elected = single
    ? t('contest.single')
    : seats
      ? t('contest.seats', { n: formatNumber(seats) })
      : contest.seats2022
        ? t('contest.seats_previous', { n: formatNumber(contest.seats2022) })
        : null;
  const candidates =
    unmuted < n
      ? t('contest.candidates_filtered', { shown: formatNumber(unmuted), n: formatNumber(n) })
      : t('contest.candidates', { n: formatNumber(n) });
  const limit = single ? 1 : (seats ?? contest.seats2022);
  const over = limit !== null && picked > limit;
  const warning = over ? t('contest.too_many', { picked: formatNumber(picked), n: formatNumber(limit) }) : null;
  // Each fact a piece of its own, so that a line breaks between them only.
  const fact = (cls, text) =>
    over && cls
      ? html`<span class=${`fact ${cls} over`} title=${warning}><${WarningIcon} />${text}</span>`
      : html`<span class="fact">${text}</span>`;
  return html`<span class="contest-text" id=${id}>
    <span class="contest-meta">
      ${elected ? html`${fact('seats', elected)} · ` : null}${fact(null, candidates)}
      ${picked ? html` · ${fact('picked', t('contest.picked', { n: formatNumber(picked) }))}` : null}
    </span>
    ${over ? html`<span class="sr-only">${warning}</span>` : null}
    ${
      contest.noResult
        ? html`<span class="contest-results pending">${t('results.no_result')}</span>`
        : results || pending
          ? html`<${ResultsLine} results=${results} single=${single} />`
          : null
    }
  </span>`;
}

/* How far the 2026 count of a contest has got, in the results' green:
 * - not counted yet;
 * - counting: the share counted (of its registered voters, live.js
 *   `countShare`; its okrsky in the tooltip) and the valid votes counted,
 *   which tell how much a lead may still change;
 * - counted with only the winners so far (municipal contests on election
 *   night);
 * - final: the valid votes alone, as final goes without saying once the
 *   elections are over. */
function ResultsLine({ results: r, single }) {
  if (!r) return html`<span class="contest-results pending">${t('results.pending')}</span>`;
  if (r.status === 'final' && !r.valid) return null;
  const vars = resultsVars(r);
  let text;
  let title = null;
  if (r.status === 'partial') {
    text = t(r.counted ? 'results.counting' : 'results.counting_votes', vars);
    if (r.counted) title = t(r.registered === null ? 'results.counting_units' : 'results.counting_title', vars);
  } else if (r.status === 'winner') {
    text = t(single || r.filled === null ? 'results.counted_mayor' : 'results.counted_council', vars);
    title = t('results.counted_title');
  } else text = t('results.valid_votes', vars);
  return html`<span class=${`contest-results ${r.status}`} title=${title}>
    ${r.status === 'partial' ? html`<span class="live-dot" aria-hidden="true"></span>` : null}${text}
  </span>`;
}

/* The mayor or president in office who does not stand again. */
function Holder({ contest }) {
  const h = contest.holder;
  if (!h || h.number !== null) return null;
  return html`<div class="holder">
    <p>
      ${t('contest.holder_not_standing', { name: h.name })}
      <span class="muted"> (${t('card.office_since', { date: formatDate(h.since) })})</span>
    </p>
    <${OfficeResult} result=${h.result} />
  </div>`;
}

/* The election *past* (data.js `contest`) is of, named with its day: the
 * regular municipal or regional ones before (results named oso<year>,
 * osk<year>), or a municipal by-election held since (oso<year><month>). */
function pastElection(past) {
  const regular = /^os[ok]\d{4}$/.test(past.election);
  const kind = regular ? (past.election.startsWith('osk') ? 'regional' : 'municipal') : 'by';
  return t(`turnout.election_${kind}`, { date: formatDate(past.date) });
}

/* The turnout at the header's end, a short horizontal meter like the
 * votes' bars, its share above its start and the year at its end: the
 * last election's in grey (*past*); once counted, 2026's in the results'
 * green (*live*) over the same track, with the last election's as a grey
 * tick and its share and year under it, so that the two compare at a
 * glance. Each is {share, year, label, approx}, the label (the numbers)
 * in the tooltip, `approx` where the last election's figures are not
 * exactly of this area (live.js `PAST`): its share then reads "≈". Once
 * counted, the meter is the button that puts *contest*'s 2026 turnout on
 * the map (mapmode.js `TurnoutMapButton`). */
function Turnout({ contest, past, live }) {
  const main = live ?? past;
  const tick = live && past;
  const label = [past?.label, live?.label].filter(Boolean).join(' ');
  // No space after the mark: the narrow meter would break the line there.
  const percent = (x) => `${x.approx ? '≈' : ''}${formatPercent(x.share, 0)}`;
  const lines = html`
    <span class="gauge-line"><strong>${percent(main)}</strong>${main.year}</span>
    <span class="gauge-bar">
      <span class="gauge-fill" style=${{ width: width(main.share) }}></span>
      ${tick ? html`<span class="gauge-tick" style=${{ left: width(past.share) }}></span>` : null}
    </span>
    ${tick ? html`<span class="gauge-line past"><span>${percent(past)}</span>${past.year}</span>` : null}
  `;
  if (!live) return html`<span class="gauge" role="img" aria-label=${label} title=${label}>${lines}</span>`;
  return html`<${TurnoutMapButton} contest=${contest} figures=${label}>
    <span class="gauge live" aria-hidden="true">${lines}</span>
  <//>`;
}

/* The turnout of the last election in a contest's area, for whoever
 * wonders how many vote there, labelled with that election. A council now
 * split into several obvody: that of the okrsky its obvod is made of, with
 * how they were found (live.js `pastLabel`, `pastTitle`); else, where one
 * of those is not known, that of the whole municipality. */
function pastTurnout(contest) {
  const p = contest.past;
  const share = p.voters / p.eligible;
  const text = t('turnout.detail', {
    election: pastElection(p),
    voters: formatNumber(p.voters),
    eligible: formatNumber(p.eligible),
    turnout: formatPercent(share),
  });
  let note = null;
  if (p.whole) note = t(contestKind(contest.id) === 'oz:city' ? 'turnout.whole_city' : 'turnout.whole');
  else if (p.method !== null) note = `${t('turnout.obvod', { method: pastLabel(p.method) })} ${pastTitle(p.method)}`;
  return {
    share,
    year: p.date.slice(0, 4),
    label: note ? `${text} ${note}` : text,
    approx: p.method !== null && p.method !== PAST.same,
  };
}

/* *numbers* in order, as ranges: [7, 1, 2, 3] → "1–3, 7". */
function numberRanges(numbers) {
  const sorted = [...numbers].sort((a, b) => a - b);
  const out = [];
  for (let i = 0; i < sorted.length; ) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++;
    out.push(j > i ? `${sorted[i]}–${sorted[j]}` : `${sorted[i]}`);
    i = j + 1;
  }
  return out.join(', ');
}

/* The 2026 turnout so far (of the districts counted, while counting goes
 * on); with *unit* named, of that unit of the contest's area (`inUnit`). */
const liveTurnout = (r, unit = null) => ({
  share: r.voters / r.eligible,
  year: election.slice(0, 4),
  label: unit
    ? t('results.turnout_unit', { ...resultsVars(r), unit })
    : t(r.status === 'partial' ? 'results.turnout_partial' : 'results.turnout', resultsVars(r)),
});

/* An okrsok's turnout in the election before (live.js `pastOf`: {day,
 * method, record}), labelled with how its figures were found; where they
 * are not known, null. */
const okrsokPast = ({ day, method, record }) => {
  if (!record) return null;
  const [eligible, voters] = record;
  const text = t('turnout.okrsok', {
    voters: formatNumber(Math.round(voters)),
    eligible: formatNumber(Math.round(eligible)),
    turnout: formatPercent(voters / eligible),
    method: pastLabel(method),
  });
  return {
    share: voters / eligible,
    year: day.slice(0, 4),
    label: method === PAST.same ? text : `${text} ${pastTitle(method)}`,
    approx: method !== PAST.same,
  };
};

/* Results *r* (live.js `decodeResults`) narrowed to a unit of the contest's
 * area, *record* [eligible, voters, valid, {number: votes}] (live.js
 * `placeResults`): the unit's votes, shares and turnout. Who is elected
 * and the state of the count stay the contest's. */
function inUnit(r, [eligible, voters, valid, votes]) {
  const byNumber = new Map(
    [...r.byNumber].map(([n, x]) => {
      const v = votes[n] ?? 0;
      return [n, { ...x, votes: x.votes === null ? null : v, share: x.share === null || !valid ? null : v / valid }];
    }),
  );
  return { ...r, eligible, voters, valid, byNumber };
}

/* The results of *contest* from its live *entry*, as shown with *place*
 * (as `Contest` takes it) and *level* (one of SCOPES):
 * - whole: the whole contest's (live.js `decodeResults`), null until
 *   counted;
 * - units: the units of *place* with figures of their own (live.js
 *   `placeResults`);
 * - unit: the finest of them not finer than *level*, or null;
 * - results: the whole narrowed to that unit (`inUnit`). */
function scopedResults(contest, entry, place, level) {
  const whole = entry && entry !== NOT_COUNTED ? decodeResults(contest, entry) : null;
  const units = whole && place ? placeResults(contest.id, place) : [];
  const unit = units.filter((u) => SCOPES.indexOf(u.scope) <= SCOPES.indexOf(level)).at(-1) ?? null;
  return { whole, units, unit, results: unit ? inUnit(whole, unit.record) : whole };
}

/* The name of *scope* (one of SCOPES) of *place* (as `Contest` takes
 * it). */
function scopeName(scope, place) {
  if (scope === 'all') return t('scope.all');
  if (scope === 'obec') return place.name;
  return t(`scope.${scope}`, { n: place[scope] });
}

/* The choice of scope for a contest's results, where the place shown lies
 * in units of its area with figures of their own (*units*, live.js
 * `placeResults`): the whole contest or one of those units, *shown* (one
 * of SCOPES) pressed. A press sets the scope for every contest on the
 * ballots (`onLevel`). *place*: as `Contest` takes it. */
function ScopeChoice({ units, shown, place, onLevel }) {
  return html`<div class="contest-scope" role="group" aria-label=${t('scope.label')}>
    ${['all', ...units.map((u) => u.scope)].map(
      (scope) => html`<button
        type="button"
        key=${scope}
        aria-pressed=${scope === shown ? 'true' : 'false'}
        onClick=${() => onLevel(scope)}
      >
        ${scopeName(scope, place)}
      </button>`,
    )}
  </div>`;
}

/* *list* with the items that satisfy *test* moved to its end, each part in
 * its order. */
const lastWhere = (list, test) => [...list.filter((x) => !test(x)), ...list.filter(test)];

/* *candidates* in list order and which of them are muted: those the
 * *filter* leaves shown, then those it mutes (never the circled ones,
 * *actions* `isPicked`). Each group is in ballot order or, *ranked* (the
 * 2026 results are in), by votes, those without any last; within it,
 * those who withdrew come last, to be seen apart. */
function byFilter(candidates, filter, actions, ranked) {
  const byVotes = ranked ? [...candidates].sort((a, b) => (b.result?.votes ?? -1) - (a.result?.votes ?? -1)) : candidates;
  const sorted = lastWhere(byVotes, (c) => c.result?.withdrawn);
  const muted = new Map(sorted.map((c) => [c, !actions.isPicked(c.id) && isMuted(c, filter)]));
  const order = lastWhere(sorted, (c) => muted.get(c));
  return { order, muted, unmuted: order.length - [...muted.values()].filter(Boolean).length };
}

/* The candidates of *contest* with their 2026 results (*results*, live.js
 * `decodeResults`) as `result`: what a row shows and the filter's
 * `elected` mark reads, with what explains a call. */
function withResults(contest, results) {
  if (!results) return contest.candidates;
  const extra = {
    call: results.call,
    past: contest.past,
    valid: results.valid,
    eligible: results.eligible,
    multi: !isSingle(contest.id),
    contestLabel: contest.label,
  };
  return contest.candidates.map((c) => {
    const r = results.byNumber.get(c.number);
    return r ? { ...c, result: { ...r, ...extra } } : c;
  });
}

/* On a partial count of a contest of several seats (a municipal or
 * regional council obvod; *r* the whole contest's, live.js
 * `decodeResults`), the places that would win them so far: ballot number
 * → place, for the first `seats` candidates by votes (with any, and not
 * withdrawn), while nobody is elected yet; null otherwise. Always the whole
 * contest's, whatever unit the list shows. */
function seatPlaces(contest, r) {
  if (r?.status !== 'partial' || !r.seats || isSingle(contest.id)) return null;
  const all = [...r.byNumber];
  if (all.some(([, x]) => x.elected)) return null;
  const ranked = all.filter(([, x]) => x.votes > 0 && !x.withdrawn).sort((a, b) => b[1].votes - a[1].votes);
  return new Map(ranked.slice(0, r.seats).map(([n], i) => [n, i + 1]));
}

/* What a contest counted on election night does not have yet (*r* the
 * whole contest's, live.js `decodeResults`), said where its rows would
 * otherwise stand puzzlingly without votes: counting, but no candidate's
 * votes yet; or counted with the turnout and at most the winners (status
 * `winner`), naming them where known, as the candidates' votes are not
 * published until the final results. Null where the votes are there. */
function nightNote(contest, r) {
  if (!r || r.status === 'final') return null;
  const all = [...r.byNumber.values()];
  if (r.status === 'partial') return all.some((x) => x.votes !== null) ? null : t('results.note_partial');
  const elected = all.filter((x) => x.elected).length;
  if (elected && elected >= contest.candidates.length) return t('results.note_all_elected');
  if (elected) return t('results.note_winner');
  return t(r.eligible === null ? 'results.note_counted' : 'results.note_turnout');
}

/* A contest: a header that opens and closes the list of its candidates.
 * Open, the header stands out from the candidates under it; closed, it is
 * muted, with a bar at its side where it opens to more candidates. Its
 * tooltip says what a press does. The contest's name is the button and
 * takes the header's whole width, as a long name broken over lines would
 * make the list ragged; a press anywhere else in the header but its other
 * buttons does the same, as on a candidate's row.
 *
 * Open or closed, it lists first *current* (the candidate of a card,
 * highlighted), then the candidates circled while it is shown, so that a
 * circle taken off by mistake can be put back where it was. Open, it
 * lists the others too, those the filter mutes last. With *pin* (My
 * candidates) the circled stay first when it opens; otherwise they take
 * their places among the others.
 *
 * *initiallyOpen*; `onOpen(open)` when the visitor opens or closes it.
 * Under the name, beside the facts (`ContestFacts`), the header ends in
 * the turnout of the last election there (Turnout); once counted, that of
 * 2026, which is then the button that puts it on the map, and before it,
 * once the candidates' votes are in, a button that shows who got the most
 * votes where (mapmode.js `WinnerMapButton`).
 *
 * *place* ({obec, name, obvod, okrsok}: the obec or city district of the
 * ballots, named, and its council obvod and okrsok where known): once
 * counted, where it lies in units of the contest's area with figures of
 * their own (live.js `placeResults`), a choice of the results' scope
 * (`ScopeChoice`). The candidates' votes and the 2026 turnout are then
 * those of the finest unit not finer than *level* (one of SCOPES, one
 * choice for all the ballots' contests, changed by `onLevel(next)`), with
 * an okrsok's 2022 turnout where known. */
export function Contest({
  contest,
  current = null,
  pin = false,
  initiallyOpen = false,
  onOpen,
  onCandidate,
  filter,
  actions,
  place = null,
  level = 'all',
  onLevel,
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const live = useLive();
  const entry = live.of(contest.id);
  const { whole, units, unit, results } = scopedResults(contest, entry, place, level);
  const candidates = withResults(contest, results);
  const shown = current && (candidates.find((c) => c.id === current.id) ?? current);
  const kept = useRef(new Set());
  for (const c of contest.candidates) if (actions.isPicked(c.id)) kept.current.add(c.id);
  const rest = candidates.filter((c) => c.id !== current?.id);
  const keptRest = rest.filter((c) => kept.current.has(c.id));
  const { order, muted, unmuted } = byFilter(rest, filter, actions, Boolean(results));
  let listed = keptRest;
  if (open) listed = pin ? [...keptRest, ...order.filter((c) => !kept.current.has(c.id))] : order;
  const opens = rest.length > 0;
  // Whether some candidates show while it is closed: then it opens to the others.
  const some = Boolean(current) || keptRest.length > 0;
  const tooltip = some
    ? t(open ? 'contest.hide_others' : 'contest.show_all')
    : t(open ? 'contest.hide_candidates' : 'contest.show_candidates');
  const picked = contest.candidates.filter((c) => actions.isPicked(c.id)).length;
  // A unit's own turnout then only: the contest's is of its whole area. An
  // okrsok whose figures then are not known says so beside 2026's.
  const past = unit ? (unit.past ? okrsokPast(unit.past) : null) : contest.past ? pastTurnout(contest) : null;
  const unknown = unit?.past && !unit.past.record ? ` ${pastTitle(PAST.unknown)}` : '';
  const turnout = results?.eligible && results.voters !== null ? liveTurnout(results, unit && scopeName(unit.scope, place)) : null;
  const now = turnout && { ...turnout, label: turnout.label + unknown };
  // Who got the most votes where, once the candidates' votes are in: on
  // election night a municipality's give the winners only.
  const winnerMap = Boolean(whole?.valid) && whole.status !== 'winner' && [...whole.byNumber.values()].some((r) => r.votes);
  const facts = useOwnId('km-facts');
  const list = useOwnId('km-list');
  const toggle = () => {
    setOpen(!open);
    onOpen?.(!open);
  };
  const places = seatPlaces(contest, whole);
  const note = open || some ? nightNote(contest, whole) : null;
  const rows = [...(shown ? [shown] : []), ...listed];
  const row = (c, i) => {
    const place = places?.get(c.number);
    const seat = place && {
      place,
      seats: whole.seats,
      end: place === whole.seats && i + 1 < rows.length && !places.has(rows[i + 1].number),
    };
    return html`<li key=${c.id}>
      <${CandidateRow}
        candidate=${c}
        onCandidate=${onCandidate}
        actions=${actions}
        current=${c === shown}
        muted=${c !== shown && muted.get(c)}
        seat=${seat}
      />
    </li>`;
  };
  return html`
    <section class=${open || !opens ? 'contest open' : 'contest'}>
      <div
        class=${opens ? 'contest-bar opens' : 'contest-bar'}
        title=${opens ? tooltip : undefined}
        onClick=${(e) => {
          // The header's own buttons do what they say; the rest opens or closes it.
          if (opens && !e.target.closest('button')) toggle();
        }}
      >
        ${
          opens
            ? html`<button
                type="button"
                class="contest-head"
                aria-expanded=${open ? 'true' : 'false'}
                aria-controls=${list}
                aria-describedby=${facts}
                onClick=${toggle}
              >
                ${contest.label}
              </button>`
            : html`<span class="contest-head">${contest.label}</span>`
        }
        <${ContestFacts}
          id=${facts}
          contest=${contest}
          unmuted=${unmuted + (current ? 1 : 0)}
          picked=${picked}
          results=${whole}
          pending=${entry === NOT_COUNTED}
        />
        ${
          past || now
            ? html`<span class="contest-tools">
                ${winnerMap ? html`<${WinnerMapButton} contest=${contest} />` : null}
                <${Turnout} contest=${contest} past=${past} live=${now} />
              </span>`
            : null
        }
      </div>
      ${units.length ? html`<${ScopeChoice} units=${units} shown=${unit?.scope ?? 'all'} place=${place} onLevel=${onLevel} />` : null}
      ${open || !contest.candidates.length ? html`<${Holder} contest=${contest} />` : null}
      ${note ? html`<p class="results-note">${note}</p>` : null}
      ${
        contest.candidates.length
          ? html`<ol class="cands" id=${list}>
              ${rows.map(row)}
            </ol>`
          : html`<p class="muted">${t('contest.no_candidates')}</p>`
      }
    </section>
  `;
}

/* A contest on the ballots, open unless the visitor has closed one of its
 * kind. *listed*: one of all the council obvody of an obec, listed at
 * once; it starts closed, and opening or closing it says nothing about
 * the kind. */
function BallotContest({ contest, listed = false, ...props }) {
  const kind = contestKind(contest.id);
  const onOpen = (open) => {
    if (listed) return;
    if (open) closedKinds.delete(kind);
    else closedKinds.add(kind);
  };
  return html`<${Contest}
    contest=${contest}
    initiallyOpen=${!listed && !closedKinds.has(kind)}
    onOpen=${onOpen}
    ...${props}
  />`;
}

/* The changes the row buttons make to the visitor's work, {filter, picks}:
 * each a function of it. Crossing a candidate out takes off its circle,
 * and circling one takes off its cross. */
const without = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : list);

const pick = (id) => (s) => ({
  picks: togglePick(s.picks, id),
  filter: s.filter.crossed.includes(id) ? { ...s.filter, crossed: without(s.filter.crossed, id) } : s.filter,
});

const cross = (id) => (s) =>
  s.filter.crossed.includes(id)
    ? { picks: s.picks, filter: { ...s.filter, crossed: without(s.filter.crossed, id) } }
    : { picks: without(s.picks, id), filter: { ...s.filter, crossed: [...s.filter.crossed, id] } };

/* Party *p*, or mark *name*, put in the filter in *mode*; if already there
 * in that mode, taken out. */
const setParty = (p, mode) => (s) => {
  const current = s.filter.parties.find((f) => f.name === p.name);
  const rest = s.filter.parties.filter((f) => f !== current);
  return { ...s, filter: { ...s.filter, parties: current?.mode === mode ? rest : [...rest, { ...p, mode }] } };
};

const setMark = (name, mode) => (s) => {
  const { [name]: current, ...rest } = s.filter.marks;
  return { ...s, filter: { ...s.filter, marks: current === mode ? rest : { ...rest, [name]: mode } } };
};

/* How soon and how near a second click or tap must follow the first to
 * make a double one: about what systems allow for a double-click, and
 * less than a row's height, so that quick taps down a list of numbers
 * each count. */
const DOUBLE_MS = 400;
const DOUBLE_PX = 24;

/* The handlers of the buttons on candidate rows (CandidateRow *actions*),
 * for the rows inside *section* (a ref) of *candidates* (id → candidate):
 * the filter's (*filter*, `onFilter(next)`) and the circles' (*picks*,
 * `onPicks(next)`, picks.js).
 *
 * Every such button has a press and an alternate one: a number circles,
 * the alternate crosses out; a party tag or a mark shows only its
 * candidates, the alternate hides them; each, repeated, undoes itself.
 * The alternate press is a Shift+click, or a double click or tap, the only
 * one a phone has. A double press's first press has done the plain change
 * by then, which the second undoes before making its own. That first
 * press may have moved the row (circling a muted candidate lists it with
 * the others), so the second counts wherever it lands near the first.
 *
 * The party pointed at or focused has its candidates highlighted by a
 * class on their rows rather than by rendering again: with a few hundred
 * candidates that takes tens of milliseconds, and a pointer crossing the
 * pane (dragging the map, say) passes many party tags. */
export function useRowActions(section, candidates, filter, onFilter, picks, onPicks) {
  const hovered = useRef(null);
  const highlight = () => {
    const name = hovered.current;
    for (const row of section.current?.querySelectorAll('.cand') ?? []) {
      const c = candidates.get(row.querySelector('[data-candidate]').dataset.candidate);
      row.classList.toggle('highlighted', name !== null && Boolean(c) && standsFor(c, name));
    }
  };
  // A row rendered again with another class has lost it.
  useLayoutEffect(highlight);
  const point = (value) => () => {
    hovered.current = value;
    highlight();
  };

  const work = { filter, picks };
  const apply = (next) => {
    if (next.filter !== filter) onFilter(next.filter);
    if (next.picks !== picks) onPicks(next.picks);
  };
  // The first press of what may become a double one: when and where, the
  // work before it, and the alternate change.
  const first = useRef(null);
  const latest = useRef(apply);
  latest.current = apply;
  useEffect(() => {
    // Captured before any button sees it, so that a second press on another
    // button (or on the row, which would open the card) makes only the
    // alternate change.
    const onClick = (e) => {
      const f = first.current;
      if (!f || e.detail === 0 || !section.current?.contains(e.target)) return;
      first.current = null;
      if (e.timeStamp - f.time > DOUBLE_MS || Math.hypot(e.clientX - f.x, e.clientY - f.y) > DOUBLE_PX) return;
      e.stopPropagation();
      latest.current(f.alternate(f.before));
    };
    document.addEventListener('click', onClick, true);
    // While Shift is held, a button under the pointer previews its
    // alternate press (app.css `.shift`). Pointer events catch a Shift
    // pressed while the window was in the background; blur, one released
    // there.
    const root = document.documentElement;
    const onShift = (e) => root.classList.toggle('shift', e.shiftKey);
    const onBlur = () => root.classList.remove('shift');
    const shiftEvents = ['keydown', 'keyup', 'pointermove', 'pointerdown'];
    for (const type of shiftEvents) document.addEventListener(type, onShift);
    window.addEventListener('blur', onBlur);
    return () => {
      document.removeEventListener('click', onClick, true);
      for (const type of shiftEvents) document.removeEventListener(type, onShift);
      window.removeEventListener('blur', onBlur);
      onBlur();
    };
  }, []);
  const tap = (change, alternate) => ({
    // No text selected by a Shift+click or a double click.
    onMouseDown: (e) => {
      if (e.shiftKey || e.detail > 1) e.preventDefault();
    },
    onClick: (e) => {
      if (e.shiftKey) {
        apply(alternate(work));
        return;
      }
      // Pressed from the keyboard (no detail), a button has no double press.
      first.current = e.detail ? { time: e.timeStamp, x: e.clientX, y: e.clientY, before: work, alternate } : null;
      apply(change(work));
    },
  });

  const picked = new Set(picks);
  return {
    hoverProps: (name) => ({ onMouseEnter: point(name), onMouseLeave: point(null), onFocus: point(name), onBlur: point(null) }),
    partyMode: (name) => filter.parties.find((f) => f.name === name)?.mode,
    markMode: (name) => filter.marks[name],
    partyTap: (p) => tap(setParty(p, 'only'), setParty(p, 'hide')),
    markTap: (name) => tap(setMark(name, 'only'), setMark(name, 'hide')),
    isPicked: (id) => picked.has(id),
    isCrossed: (id) => filter.crossed.includes(id),
    pickTap: (id) => tap(pick(id), cross(id)),
    removeParty: (name) => onFilter({ ...filter, parties: filter.parties.filter((f) => f.name !== name) }),
    removeMark: (name) => {
      const { [name]: _, ...rest } = filter.marks;
      onFilter({ ...filter, marks: rest });
    },
    clearCrossed: () => onFilter({ ...filter, crossed: [] }),
  };
}

/* The official documents that set a council's obvody: their links stay
 * with the ballots rather than in About's list of every municipality. One
 * line after the contests, so that the next contest follows close: a
 * document's title, cut short, or several documents numbered; each one's
 * full title in its tooltip and for screen readers. */
function Sources({ sources }) {
  const numbered = sources.length > 1;
  return html`<p class=${numbered ? 'sources numbered' : 'sources'}>
    ${t('contest.sources')}
    ${sources.map(
      ([title, url], i) => html`<a
        key=${url}
        href=${url}
        title=${title}
        aria-label=${numbered ? title : undefined}
        rel="noopener noreferrer"
        target="_blank"
      >
        ${numbered ? formatNumber(i + 1) : title}
      </a>`,
    )}
  </p>`;
}

/* A filter group's mode as one button that switches it: an open eye while
 * only the group's candidates are shown, struck through while they are
 * hidden; the tooltip says which, and what a press does. */
function ModeToggle({ mode, onMode }) {
  const only = mode === 'only';
  const label = t(only ? 'filter.mode_only' : 'filter.mode_hide');
  return html`<button
    type="button"
    class="filter-mode"
    title=${label}
    aria-label=${label}
    onClick=${() => onMode(only ? 'hide' : 'only')}
  >
    ${only ? html`<${EyeIcon} />` : html`<${EyeOffIcon} />`}
  </button>`;
}

/* The filter, under the place's name, in as few lines as fit:
 * - each group (the parties shown, those hidden, each mark added) with
 *   its mode and its chips, each removable; a party's chip highlights its
 *   candidates as a party tag on a row does (*actions* as for
 *   CandidateRow);
 * - the candidates crossed out, counted, removable all at once;
 * - a button that clears it all.
 * Stuck to the top while the lists scroll, it is ruled off from the
 * pane's close button beside it, which must not pass for the clear
 * button. */
export function FilterBar({ filter, onFilter, actions }) {
  const { parties, marks, crossed } = filter;
  const added = MARKS.filter(({ name }) => name in marks);
  const shown = parties.length > 0 || added.length > 0 || crossed.length > 0;
  const bar = useRef(null);
  const [stuck, setStuck] = useState(false);

  useEffect(() => {
    const element = bar.current;
    if (!element) return;
    // Sticky at top 0 of a root shrunk by a pixel, the bar is cut by it.
    const observer = new IntersectionObserver(
      ([entry]) => setStuck(entry.intersectionRatio < 1 && entry.boundingClientRect.top < entry.rootBounds.top),
      { root: element.closest('.pane-body'), rootMargin: '-1px 0px 0px 0px', threshold: 1 },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [shown]);

  if (!shown) return null;
  const remove = (label, onClick) => html`<button
    type="button"
    class="chip-remove"
    aria-label=${t('filter.remove', { name: label })}
    title=${t('filter.remove', { name: label })}
    onClick=${onClick}
  >
    <${CloseIcon} />
  </button>`;
  const group = (key, label, mode, onMode, chips) => html`
    <div key=${key} class=${`filter-group ${mode}`} role="group" aria-label=${label}>
      <${ModeToggle} mode=${mode} onMode=${onMode} />
      <ul class="chips">${chips}</ul>
    </div>
  `;
  // Switching a party group's mode joins its parties to the other group.
  const partyGroup = (mode) => {
    const members = parties.filter((p) => p.mode === mode);
    if (!members.length) return null;
    return group(
      `parties-${mode}`,
      t('filter.parties'),
      mode,
      (next) => onFilter({ ...filter, parties: parties.map((p) => (p.mode === mode ? { ...p, mode: next } : p)) }),
      members.map((p) => {
        const name = partyName(p);
        return html`<li key=${p.name} class="chip" title=${name} ...${actions.hoverProps(p.name)}>
          ${p.logo ? html`<img class="party-logo" src=${p.logo} alt="" />` : null}
          <span>${partyShort(p)}</span>
          ${remove(name, () => actions.removeParty(p.name))}
        </li>`;
      }),
    );
  };
  return html`
    <div ref=${bar} class=${stuck ? 'filter-bar stuck' : 'filter-bar'} role="group" aria-label=${t('filter.label')}>
      ${partyGroup('only')} ${partyGroup('hide')}
      ${added.map(({ name, Icon }) => {
        const label = t(`filter.${name}`);
        return group(
          name,
          label,
          marks[name],
          (mode) => onFilter({ ...filter, marks: { ...marks, [name]: mode } }),
          html`<li class=${`chip ${name}-chip`}>
            <${Icon} />
            <span>${label}</span>
            ${remove(label, () => actions.removeMark(name))}
          </li>`,
        );
      })}
      ${
        crossed.length
          ? html`<div class="filter-group hide crossed" role="group" aria-label=${t('filter.crossed')}>
              <ul class="chips">
                <li class="chip crossed-chip">
                  <${CrossOutIcon} />
                  <span>${t('filter.crossed_n', { n: formatNumber(crossed.length) })}</span>
                  ${remove(t('filter.crossed'), actions.clearCrossed)}
                </li>
              </ul>
            </div>`
          : null
      }
      <button type="button" class="filter-clear" onClick=${() => onFilter(NO_FILTER)}>
        <${FilterOffIcon} />${t('filter.clear')}
      </button>
    </div>
  `;
}

const MUNICIPAL = new Set(['starosta', 'oz']);

/* Whether contest *id* is of the municipal elections (mayor, council)
 * rather than the regional ones. */
export const isMunicipal = (id) => MUNICIPAL.has(id.split(':')[0]);

/* The scope of the results on the ballots (live.js SCOPES) the visitor
 * chose last. It carries over from place to place, each with its own
 * units, as one looks through the okrsky of a town, say. */
let keptLevel = 'all';

/* The ballots of obec *code*.
 * - label: names the address, street or part chosen in it, if any.
 * - scope ({obvod, street, part}): narrows its council obvod (data.js
 *   `ballots`); `approximate`: the obvod was taken from the map's
 *   approximate boundary at a clicked point.
 * - okrsok: the place's okrsok (polling district) where known,
 *   `okrsokApproximate` likewise. A street's or part's is its houses'
 *   okrsok where they share one; else their okrsky and council obvody are
 *   named (data.js `ballots` `group`).
 * - focus: the candidacy whose card was just left; its row takes the
 *   focus.
 * - filter (see NO_FILTER) and `onFilter(next)`: the candidate filter;
 *   picks and `onPicks(next)`: the circled candidates (picks.js).
 * The counted contests' results all show one scope (`Contest` *level*):
 * the whole contest, or the place's obec, council obvod or okrsok. */
export function Ballots({
  code,
  label,
  scope = {},
  approximate = false,
  okrsok = null,
  okrsokApproximate = false,
  focus,
  onCandidate,
  filter,
  onFilter,
  picks,
  onPicks,
}) {
  const { obvod = null, street = null, part = null } = scope;
  const [result, failed] = useLoaded(
    () => ballots(code, { obvod, street, part }),
    [code, obvod, street, part],
  );
  const [level, setLevel] = useState(keptLevel);
  const onLevel = (next) => {
    keptLevel = next;
    setLevel(next);
  };
  const section = useRef(null);
  const actions = useRowActions(
    section,
    new Map((result?.contests ?? []).flatMap((c) => c.candidates.map((x) => [x.id, x]))),
    filter,
    onFilter,
    picks,
    onPicks,
  );

  useEffect(() => {
    if (!result || !focus) return;
    const row = section.current.querySelector(`[data-candidate="${CSS.escape(focus)}"]`);
    row?.focus();
    // In a closed contest, or not on these ballots: the place's name.
    if (document.activeElement !== row) section.current.querySelector('#km-place').focus();
  }, [result]);

  if (failed) return html`<p class="panel-body error">${t('error.load')}</p>`;
  if (result === null) return html`<p class="panel-body error">${t('place.missing')}</p>`;
  if (!result) return html`<p class="panel-body muted loading">${t('panel.loading')}</p>`;
  const { obec, council, obvod: placeObvod, estimated, origin, contests, group } = result;
  const municipal = contests.filter((c) => isMunicipal(c.id));
  const regional = contests.filter((c) => !isMunicipal(c.id));
  const firstCouncil = municipal.findIndex((c) => c.council);
  // A street's or part's okrsok where all its houses are in one; where they
  // are in several, which (and likewise its council obvody).
  const placeOkrsok = okrsok ?? (group.okrsky.length === 1 ? group.okrsky[0] : null);
  const where = [
    label ? obec.name : null,
    placeObvod
      ? t('place.obvod', { n: placeObvod })
      : group.obvody.length > 1
        ? t('place.obvody', { n: numberRanges(group.obvody) })
        : null,
    placeOkrsok
      ? t(okrsokApproximate ? 'place.okrsok_approximate' : 'place.okrsok', { n: placeOkrsok })
      : group.okrsky.length > 1
        ? t('place.okrsky', { n: numberRanges(group.okrsky) })
        : null,
    obec.okresName ? t('place.okres', { name: obec.okresName }) : null,
    t('place.kraj', { name: obec.krajName }),
  ].filter(Boolean);

  // Each a one-line summary and the whole note. Where the obvody are the
  // later election's without proof that they match, that matters most, then
  // where they are a guess, more than how the obvod was found; where
  // another election's rules stand in, that comes next, then documents
  // dated only approximately or filled in from a later source: every one
  // that applies is said, the first summarises.
  // Once the polls have closed the notes speak of the election as past.
  const past = Date.now() > polls[1];
  const n = obec.councils;
  const name = obec.name;
  const other = origin.reused?.slice(0, 4);
  const adopted = origin.adopted?.slice(0, 4);
  const caveats = [
    adopted && [t('council.summary_adopted', { later: adopted }), t('council.adopted', { name, later: adopted })],
    estimated && [t('council.summary_estimated'), t('council.estimated', { name })],
    other && [t('council.summary_reused', { other }), t('council.reused', { name, other })],
    origin.dating && [t('council.summary_dated'), dated(t('council.dated', { name }), origin.dating)],
    origin.supplemented && [
      t('council.summary_supplemented'),
      supplemented(t('council.supplemented', { name }), origin.supplemented),
    ],
  ].filter(Boolean);
  const caveat = caveats.length ? [caveats[0][0], caveats.map((c) => c[1]).join(' ')] : null;
  // An estimate is approximate anyway.
  const approximateNote = approximate && !estimated ? t('council.approximate') : null;
  const notes = {
    pending: () =>
      origin.notFound
        ? [t('council.summary_not_found', { n }), t('council.not_found', { n, name })]
        : past
          ? [t('council.summary_pending_past', { n }), t('council.pending_past', { n, name })]
          : [t('council.summary_pending', { n }), t('council.pending', { n, name })],
    choose: () => [
      caveat ? caveat[0] : t(past ? 'council.summary_choose_past' : 'council.summary_choose', { n }),
      [t(past ? 'council.choose_past' : 'council.choose', { n, name }), caveat?.[1]].filter(Boolean).join(' '),
    ],
    address: () =>
      caveat
        ? [caveat[0], [caveat[1], approximateNote].filter(Boolean).join(' ')]
        : approximateNote
          ? [t('council.summary_approximate'), approximateNote]
          : null,
  };
  const note = notes[council]?.();
  const councilNote = note ? html`<${Notice} summary=${note[0]}>${note[1]}<//>` : null;
  // What the map draws of the obec when it is not this election's own:
  // its boundary, its okrsky (the polling districts its results are by).
  const boundary = origin.boundary;
  const okrskyFrom = origin.okrskyReused ?? origin.okrskyReferendum;
  const placeNotes = [
    boundary && [
      t('notice.summary_boundary', { on: boundary.on }),
      boundary.obce.length
        ? t('notice.boundary', { name, on: boundary.on, date: formatDate(boundary.day), others: formatList(boundary.obce) })
        : t('notice.boundary_state', { name, on: boundary.on, date: formatDate(boundary.day) }),
    ],
    origin.okrskyReused && [
      t('notice.summary_okrsky_reused', { other: okrskyFrom.slice(0, 4) }),
      t('notice.okrsky_reused', { name, other: okrskyFrom.slice(0, 4) }),
    ],
    origin.okrskyAdopted && [
      t('notice.summary_okrsky_adopted', { later: origin.okrskyAdopted.slice(0, 4) }),
      t('notice.okrsky_adopted', { name, later: origin.okrskyAdopted.slice(0, 4) }),
    ],
    origin.okrskyReferendum && [
      t('notice.summary_okrsky_referendum', { date: formatDate(okrskyFrom) }),
      t('notice.okrsky_referendum', { name, date: formatDate(okrskyFrom) }),
    ],
    origin.okrskyDating && [
      t('notice.summary_okrsky_dated'),
      dated(t('notice.okrsky_dated', { name }), origin.okrskyDating),
    ],
    origin.okrskySupplemented && [
      t('notice.summary_okrsky_supplemented'),
      supplemented(t('notice.okrsky_supplemented', { name }), origin.okrskySupplemented),
    ],
    origin.okrskyUnknown && [t('notice.summary_okrsky_unknown'), t('notice.okrsky_unknown', { name })],
  ].filter(Boolean);
  const place = { obec: obec.code, name: obec.name, obvod: placeObvod, okrsok: placeOkrsok };

  // The sources of a council's obvody follow the last of its contests.
  const withSources = (list, c, i) => {
    const last = i + 1 === list.length || officeOf(list[i + 1].id) !== officeOf(c.id);
    return html`
      <${BallotContest}
        key=${c.id}
        contest=${c}
        listed=${c.council === 'pending' || c.council === 'choose'}
        onCandidate=${onCandidate}
        filter=${filter}
        actions=${actions}
        place=${place}
        level=${level}
        onLevel=${onLevel}
      />
      ${c.sources.length && last ? html`<${Sources} sources=${c.sources} />` : null}
    `;
  };

  return html`
    <section class="ballots" aria-labelledby="km-place" ref=${section}>
      <header class="panel-head">
        <h2 id="km-place" tabindex="-1">${label ?? obec.name}</h2>
        <p class="muted">${where.join(' · ')}</p>
      </header>
      <${FilterBar} filter=${filter} onFilter=${onFilter} actions=${actions} />
      ${previous ? null : html`<p class="panel-body intro">${t('ballots.no_incumbents')}</p>`}
      <p class="panel-body intro">${t('ballots.intro')}</p>
      ${placeNotes.map(([summary, text]) => html`<${Notice} summary=${summary}>${text}<//>`)}
      <h3 class="group">${t('ballots.municipal')}</h3>
      ${municipal.map(
        (c, i) => html`
          ${i === firstCouncil ? councilNote : null}
          ${withSources(municipal, c, i)}
        `,
      )}
      ${council === 'none' ? html`<${Notice}>${t('council.none')}<//>` : null}
      <h3 class="group">${t('ballots.regional')}</h3>
      ${regional.map((c, i) => withSources(regional, c, i))}
    </section>
  `;
}
