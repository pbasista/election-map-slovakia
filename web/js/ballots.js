/* The ballots of one place: every contest a voter there votes in, each with
 * its candidates in ballot order, or once the 2026 results come in (live.js)
 * by votes. Which contests apply is decided in data.js `ballots`. */

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { ballots, contestArea, dataIndex, displayName, inOffice, officeOf, useLoaded } from './data.js';
import { formatDate, formatList, formatNumber, formatPercent, researchCategories, t } from './i18n.js';
import {
  ChairIcon,
  CloseIcon,
  CrossOutIcon,
  DisputeIcon,
  EyeIcon,
  EyeOffIcon,
  FilterOffIcon,
  InkCircle,
  InkCross,
  MedalIcon,
  MedalOutlineIcon,
  SearchIcon,
  WarningIcon,
} from './icons.js';
import { decodeResults, NOT_COUNTED, resultsVars, useLive } from './live.js';
import { ContestMapButton, MapButton } from './mapmode.js';
import { Notice } from './pane.js';
import { formatPicks, parsePicks, togglePick } from './picks.js';

/* The candidate filter (app.js keeps it across places, and in the URL:
 * filterParams): `parties` chosen ({short, name, logo, mode}, INDEPENDENT
 * among them), each with whether its candidates are shown (`mode` 'only':
 * those of the parties shown are the only ones not muted) or hidden
 * ('hide'); `marks`, mark name (MARKS) → its mode likewise, for each mark
 * added; `crossed`, the candidacies the visitor has crossed out (ids as
 * picks.js), which it mutes one by one. Muted candidates stay on the list,
 * faded and after the others. */
export const NO_FILTER = { parties: [], marks: {}, crossed: [] };

/* The independent candidates: a member of the party filter like a party,
 * named in the page's language where shown. No party's name is empty. */
const INDEPENDENT = { short: '', name: '', logo: null };
const partyName = (p) => p.name || t('candidate.independent');
const partyShort = (p) => (p.name ? p.short : t('candidate.independent_short'));

/* An element id of the component's own: a contest and its candidates may
 * show in the pane and in Favourites beside it at once. */
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
 * whom it covers: elected in 2026 (officially, or called by this site on a
 * partial count: live.js `decodeResults`); research found serious
 * controversies; disputed or lesser ones; research done (whatever it
 * found); holds the office the contest elects (the chair). */
const MARKS = [
  ['elected', (c) => Boolean(c.result?.elected || c.result?.called), MedalIcon],
  ['affairs', (c) => Boolean(c.research?.affairs), WarningIcon],
  ['disputes', (c) => Boolean(c.research?.disputes), DisputeIcon],
  ['researched', (c) => Boolean(c.research), SearchIcon],
  ['office', inOffice, ChairIcon],
];

const mutedBy = (mode, member) => (mode === 'hide' && member) || (mode === 'only' && !member);

/* Whether *filter* mutes candidate *c*: crossed out, of none of the
 * parties shown where some are, of a party hidden, or any mark that does. */
function isMuted(c, filter) {
  const shown = filter.parties.filter((p) => p.mode === 'only');
  return (
    filter.crossed.includes(c.id) ||
    (shown.length > 0 && !shown.some((p) => standsFor(c, p.name))) ||
    filter.parties.some((p) => p.mode === 'hide' && standsFor(c, p.name)) ||
    MARKS.some(([name, covers]) => name in filter.marks && mutedBy(filter.marks[name], covers(c)))
  );
}

/* The filter in the URL hash (app.js), as [key, value] pairs, none for a
 * group not used: `fp` the parties by their short forms (unique, see
 * config.py `load_parties`), "-" the independents, those shown first, then
 * the hidden ones, each after a "!" (so that a list starting with one hides
 * them all, as links did when the parties had one mode for all); `fm` the
 * marks added, each after a "!" when hidden; `x` the candidacies crossed
 * out, written as picks.js writes the circled ones. */
export function filterParams(filter) {
  const params = [];
  const hide = (mode) => (mode === 'hide' ? '!' : '');
  if (filter.parties.length) {
    const parties = [...filter.parties.filter((p) => p.mode === 'only'), ...filter.parties.filter((p) => p.mode === 'hide')];
    params.push(['fp', parties.map((p) => hide(p.mode) + (p.name ? p.short : '-')).join(',')]);
  }
  const marks = MARKS.filter(([name]) => name in filter.marks).map(([name]) => hide(filter.marks[name]) + name);
  if (marks.length) params.push(['fm', marks.join(',')]);
  if (filter.crossed.length) params.push(['x', formatPicks(filter.crossed)]);
  return params;
}

/* The filter that hash values *fp*, *fm* and *x* (filterParams) name, the
 * parties looked up by short form in data/index.json's *parties*; what is
 * not known there is left out (a party gone since the link was made). */
export function parseFilter({ fp, fm, x }, parties) {
  const known = new Map(Object.values(parties).map(([short, name, logo = null]) => [short, { short, name, logo }]));
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
    if (MARKS.some(([mark]) => mark === name)) marks[name] = token.startsWith('!') ? 'hide' : 'only';
  }
  return { parties: [...chosen.values()], marks, crossed: parsePicks(x) };
}

/* What the research on a candidate searched, the scope said before any
 * result: the source categories of its research languages ("Slovak media
 * and official sites"). */
export function researchScope(r) {
  const categories = new Set(r.languages.flatMap((code) => researchCategories[code] ?? []));
  return formatList([...categories].map((c) => t(`research.scope.${c}`)));
}

/* A candidate's occupation; a machine translation names the Slovak
 * original in its tooltip (the card shows it in full). */
export function Occupation({ candidate: c }) {
  return c.occupationSk
    ? html`<span title=${t('candidate.occupation_sk', { text: c.occupationSk })}>${c.occupation}</span>`
    : c.occupation;
}

/* A candidate's nominating parties as their short forms or logos (or the
 * independent tag), the official name in the tooltip (and for screen
 * readers); the candidate card spells them out. With *actions* (the
 * ballots), each is a button: pointing at it or focusing it highlights the
 * party's candidates; pressing it shows only the candidates of the parties
 * so chosen, the alternate press (useRowActions `tap`) hides the party's,
 * and either, pressed again, takes the party out of the filter. */
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
 * through where its candidates are hidden. */
const activeClass = (mode) => (mode === 'hide' ? ' active excluded' : mode ? ' active' : '');

/* A mark after the parties, explained by *label* in its tooltip (and for
 * screen readers). With *actions* (the ballots), a button that adds the
 * mark *name* (MARKS) to the filter as the party tags add a party. */
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
 * council of the voters with a valid ballot), and of all registered voters
 * with how many of them voted. */
const resultCounts = (r) => [
  t(r.multi ? 'result.count_voters' : 'result.count_valid', resultVars(r)),
  t('result.count_eligible', resultVars(r)),
];

const width = (share) => `${(share * 100).toFixed(1)}%`;

/* How an office was won, a meter a line: the share of the valid ballots
 * (for a council: of the voters with a valid ballot) beside the votes and
 * the ballots, and the share of all registered voters, with the turnout
 * shaded behind it, beside their number and the turnout. Narrow as the
 * pane is, the second line leaves the votes to the first. The tooltips say
 * the counts in full. */
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

/* Marks a candidate who holds now the office the contest elects: a chair
 * with the share of the vote that won it, the votes in the tooltip (the
 * card charts them). */
function InOffice({ candidate: c, actions }) {
  const office = c.offices.find((o) => o.body === officeOf(c.contest));
  const r = office.result;
  const label = [t('candidate.in_office_since', { date: formatDate(office.since) }), ...resultCounts(r)].join(' ');
  return html`<${Mark} name="office" cls="in-office" label=${label} actions=${actions}>
    <${ChairIcon} />${formatPercent(r.votes / r.valid, 0)}
  <//>`;
}

/* The state of the research on a candidate: the number of findings, a
 * faint magnifier where it found nothing, a dashed one while no research
 * has been done. The tooltip says what was searched before the result; the
 * card shows the findings. */
function Researched({ candidate: c, actions }) {
  const r = c.research;
  if (!r) {
    return html`<${Mark} name="researched" cls="researched not" label=${t('research.none')} actions=${actions}>
      <${SearchIcon} />
    <//>`;
  }
  const vars = { scope: researchScope(r), date: formatDate(r.date), n: formatNumber(r.findings) };
  return html`<${Mark}
    name="researched"
    cls=${r.findings ? 'researched' : 'researched none'}
    label=${r.findings ? t('research.badge', vars) : t('research.badge_none', vars)}
    actions=${actions}
    ><${SearchIcon} />${r.findings ? formatNumber(r.findings) : null}<//>`;
}

/* Research found serious controversies about the candidate: a red warning
 * sign with their number, first of the marks, so that it is not passed
 * over among the findings. */
function Controversies({ candidate: c, actions }) {
  const r = c.research;
  const n = formatNumber(r.affairs);
  const label = t('research.affairs_badge', { scope: researchScope(r), date: formatDate(r.date), n });
  return html`<${Mark} name="affairs" cls="affairs" label=${label} actions=${actions}><${WarningIcon} />${n}<//>`;
}

/* Research found disputed or lesser controversies: allegations not
 * established, in amber, after the serious ones, and without flagging the
 * row. */
function Disputes({ candidate: c, actions }) {
  const r = c.research;
  const n = formatNumber(r.disputes);
  const label = t('research.disputes_badge', { scope: researchScope(r), date: formatDate(r.date), n });
  return html`<${Mark} name="disputes" cls="disputes" label=${label} actions=${actions}><${DisputeIcon} />${n}<//>`;
}

/* Elected in 2026: the medal alone in the results' green, without a ring,
 * unlike every other badge, as only winning earns it; right after the
 * name, before the parties: in these elections a person is elected, not a
 * party. Called by this site on a partial count, not officially yet, it is
 * drawn in outline, and its tooltip says what the call rests on (live.js
 * `GROWTH`). A mark of the filter. A council's substitutes go unmarked:
 * they are all its other candidates with a vote, in the order the list
 * shows already. */
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

/* A candidate's 2026 votes: their share on a bar in the results' green,
 * then the number. */
function Votes({ candidate: c }) {
  const r = c.result;
  if (r.share === null) return null;
  const label = t(r.multi ? 'results.votes_title_multi' : 'results.votes_title', {
    votes: formatNumber(r.votes),
    valid: formatNumber(r.valid),
    share: formatPercent(r.share),
  });
  return html`<span class="votes" title=${label}>
    <span class="votes-bar" aria-hidden="true"><span style=${{ width: width(r.share) }}></span></span>
    <strong>${formatPercent(r.share)}</strong>
    <span>${t('results.votes', { n: formatNumber(r.votes) })}</span>
  </span>`;
}

/* One candidacy: its ballot number is a button that circles it (or takes
 * the circle off), as a voter circles the numbers of their candidates on
 * the ballot, and with the alternate press (useRowActions `tap`) crosses it
 * out instead (or takes the cross off): the filter then mutes it. Its name
 * is the button that opens the card (a click elsewhere on the row does
 * too), then who nominated it, then apart from those its marks: what is
 * known about the candidate. Party tags and marks are buttons of their
 * own. Once counted, at the row's end like the pin of the contest's
 * header, a pin shows the candidate's votes on the map (mapmode.js).
 * *actions*: see useRowActions. *muted*: the filter fades the row. A row
 * of the party pointed at is highlighted by useRowActions. */
export function CandidateRow({ candidate, onCandidate, current = false, actions, muted = false }) {
  const c = candidate;
  const flagged = Boolean(c.research?.affairs);
  const picked = actions.isPicked(c.id);
  const crossed = !picked && actions.isCrossed(c.id);
  const metaId = useOwnId('km-meta');
  const classes = ['cand', current && 'current', flagged && 'flagged', crossed && 'crossed', muted && 'dimmed'];
  const state = crossed ? t('pick.crossed_state') : muted ? t('filter.muted') : null;
  return html`
    <div
      class=${classes.filter(Boolean).join(' ')}
      onClick=${(e) => {
        // The row's own buttons do what they say; the rest opens the card.
        if (!e.target.closest('button')) onCandidate(c.id);
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
          <${Parties} candidate=${c} actions=${actions} />
          <span class="marks">
            ${flagged ? html`<${Controversies} candidate=${c} actions=${actions} />` : null}
            ${c.research?.disputes ? html`<${Disputes} candidate=${c} actions=${actions} />` : null}
            ${inOffice(c) ? html`<${InOffice} candidate=${c} actions=${actions} />` : null}
            <${Researched} candidate=${c} actions=${actions} />
          </span>
        </span>
        ${c.result ? html`<${Votes} candidate=${c} />` : null}
        <span class="meta" id=${metaId}>${t('candidate.age', { n: c.age })} · <${Occupation} candidate=${c} /></span>
      </span>
      ${c.result && c.result.share !== null ? html`<${MapButton} candidate=${c} />` : null}
    </div>
  `;
}

/* The kinds of contest the visitor has closed: they stay closed on the
 * ballots of every other place, so that one can go through, say, council
 * candidates without the mayoral ones listed first. Bratislava's and
 * Košice's city contests are kinds of their own. */
const closedKinds = new Set();

function contestKind(id) {
  const [kind, area] = id.split(':');
  return /^(BA|KE)\b/.test(area) ? `${kind}:city` : kind;
}

/* What stands under a contest's name: how many are elected (one mayor or
 * president; a council's seats where known, from the decisions on the
 * obvody or else from the 2026 results once they give them, otherwise the
 * 2022 number, labelled so) and how many stand, with how many of them the
 * filter leaves shown (*unmuted*) where it mutes some; and how many of them
 * the visitor has circled (*picked*), if any. More circled than are
 * elected, both numbers are highlighted with a warning: on the ballot
 * itself that would make it invalid. Circling more is still allowed: the
 * visitor may circle whom they like best, to choose among them later. Once
 * the 2026 count reaches the contest, a line of its own says how far it has
 * got (ResultsLine). */
function ContestHead({ contest, unmuted, picked, results, pending }) {
  const n = contest.candidates.length;
  const kind = contestKind(contest.id);
  const single = kind.startsWith('starosta') || kind === 'predseda';
  const seats = contest.seats ?? results?.reportedSeats ?? null;
  const elected = single
    ? t('contest.single')
    : seats
      ? t('contest.seats', { n: formatNumber(seats) })
      : contest.seats2022
        ? t('contest.seats_2022', { n: formatNumber(contest.seats2022) })
        : null;
  const candidates =
    unmuted < n
      ? t('contest.candidates_filtered', { shown: formatNumber(unmuted), n: formatNumber(n) })
      : t('contest.candidates', { n: formatNumber(n) });
  const limit = single ? 1 : (seats ?? contest.seats2022);
  const over = limit !== null && picked > limit;
  const warning = over ? t('contest.too_many', { picked: formatNumber(picked), n: formatNumber(limit) }) : null;
  const flag = (cls, text) =>
    over ? html`<span class=${`${cls} over`} title=${warning}><${WarningIcon} />${text}</span>` : text;
  return html`
    <span class="contest-title">${contest.label}</span>
    <span class="contest-meta">
      ${elected ? html`${flag('seats', elected)} · ` : null}${candidates}
      ${picked ? html` · ${flag('picked', t('contest.picked', { n: formatNumber(picked) }))}` : null}
    </span>
    ${over ? html`<span class="sr-only">${warning}</span>` : null}
    ${results || pending ? html`<${ResultsLine} results=${results} single=${single} />` : null}
  `;
}

/* How far the 2026 count of a contest has got, in the results' green: not
 * counted yet; counting, with the share counted (of its registered voters,
 * live.js `countShare`; its okrsky in the tooltip) and the valid votes
 * counted, which tells how much a lead may still change; counted, with the
 * winners only so far (municipal contests on election night); final. */
function ResultsLine({ results: r, single }) {
  if (!r) return html`<span class="contest-results pending">${t('results.pending')}</span>`;
  const vars = resultsVars(r);
  let text;
  let title = null;
  if (r.status === 'partial') {
    text = t(r.counted ? 'results.counting' : 'results.counting_votes', vars);
    if (r.counted) title = t(r.registered === null ? 'results.counting_units' : 'results.counting_title', vars);
  } else if (r.status === 'winner') {
    text = t(single || r.filled === null ? 'results.counted_mayor' : 'results.counted_council', vars);
    title = t('results.counted_title');
  } else text = t(r.valid ? 'results.final' : 'results.final_plain', vars);
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

/* The election that *past* (data.js `contest`) is of, named with its day:
 * the regular ones of 2022, or a municipal by-election held since. */
function pastElection(past) {
  const kind = { oso2022: 'municipal', osk2022: 'regional' }[past.election] ?? 'by';
  return t(`turnout.election_${kind}`, { date: formatDate(past.date) });
}

/* The turnout at the header's end, a short horizontal meter like the
 * votes' bars, its share above it at the start and the year at the end:
 * the last election's in grey (*past*); once counted, 2026's in the
 * results' green (*live*) over the same track, the last election's left
 * on it as a grey tick, its share and year under it, so that the two
 * compare at a glance. Each is `{share, year, label}`, the label (the
 * numbers) in the tooltip. It sits inside the header, so that a press
 * there still opens or closes the contest, and takes no height of its
 * own. */
function Turnout({ past, live }) {
  const main = live ?? past;
  const tick = live && past;
  const label = [past?.label, live?.label].filter(Boolean).join(' ');
  return html`<span class=${live ? 'gauge live' : 'gauge'} role="img" aria-label=${label} title=${label}>
    <span class="gauge-line" aria-hidden="true"><strong>${formatPercent(main.share, 0)}</strong>${main.year}</span>
    <span class="gauge-bar" aria-hidden="true">
      <span class="gauge-fill" style=${{ width: width(main.share) }}></span>
      ${tick ? html`<span class="gauge-tick" style=${{ left: width(past.share) }}></span>` : null}
    </span>
    ${
      tick
        ? html`<span class="gauge-line past" aria-hidden="true"><span>${formatPercent(past.share, 0)}</span>${past.year}</span>`
        : null
    }
  </span>`;
}

/* The turnout of the last election in a contest's area, for whoever
 * wonders how many vote there, and which election that was, not this
 * year's. A council's is of the whole municipality where it has several
 * constituencies now: those of the last election were drawn otherwise. */
function pastTurnout(contest) {
  const p = contest.past;
  const share = p.voters / p.eligible;
  const text = t('turnout.detail', {
    election: pastElection(p),
    voters: formatNumber(p.voters),
    eligible: formatNumber(p.eligible),
    turnout: formatPercent(share),
  });
  const whole = p.whole ? t(contestKind(contest.id) === 'oz:city' ? 'turnout.whole_city' : 'turnout.whole') : null;
  return { share, year: p.date.slice(0, 4), label: whole ? `${text} ${whole}` : text };
}

/* The 2026 turnout so far: of the districts counted while counting goes
 * on. */
const liveTurnout = (r) => ({
  share: r.voters / r.eligible,
  year: '2026',
  label: t(r.status === 'partial' ? 'results.turnout_partial' : 'results.turnout', resultsVars(r)),
});

/* *candidates* in list order: those the *filter* leaves shown, then those it
 * mutes, each group in ballot order or, *ranked* (the 2026 results are in),
 * by votes, those without any after the rest; and which are muted. The
 * circled ones (*actions* `isPicked`) never are. */
function byFilter(candidates, filter, actions, ranked) {
  const sorted = ranked ? [...candidates].sort((a, b) => (b.result?.votes ?? -1) - (a.result?.votes ?? -1)) : candidates;
  const muted = new Map(sorted.map((c) => [c, !actions.isPicked(c.id) && isMuted(c, filter)]));
  const order = [...sorted.filter((c) => !muted.get(c)), ...sorted.filter((c) => muted.get(c))];
  return { order, muted, unmuted: order.length - [...muted.values()].filter(Boolean).length };
}

/* The candidates of *contest* with their 2026 results (*results*, live.js
 * `decodeResults`) as `result`: what a row shows and the filter's
 * `elected` mark reads, with what explains a call. */
function withResults(contest, results) {
  if (!results) return contest.candidates;
  const multi = !(contest.id.startsWith('starosta:') || contest.id.startsWith('predseda:'));
  const extra = {
    call: results.call,
    past: contest.past,
    valid: results.valid,
    eligible: results.eligible,
    multi,
    contestLabel: contest.label,
  };
  return contest.candidates.map((c) => {
    const r = results.byNumber.get(c.number);
    return r ? { ...c, result: { ...r, ...extra } } : c;
  });
}

/* A contest: its header, which opens and closes the list of its candidates
 * and shows whether it is open: open, it stands out from the candidates
 * under it; closed, it is muted, and a bar at its side marks it as one
 * that opens to more candidates; its tooltip says what a press does.
 *
 * Open or closed, it lists first *current* (the candidate of a card,
 * highlighted), then the candidates circled while it is shown, so that a
 * circle taken off by mistake can be put back where it was. Open, it lists
 * the others too, those the filter mutes after the rest. With *pin* (My
 * candidates) the circled ones stay first when it opens; otherwise they
 * take their places among the others, in ballot order.
 *
 * *initiallyOpen*, and `onOpen(open)` when the visitor opens or closes it.
 * *map* ({label, onClick}), where the contest has a place on the map, is a
 * pin at the header's end that shows it there, and once counted its 2026
 * turnout (mapmode.js `ContestMapButton`). In the header, the turnout of
 * the last election there and, once counted, of 2026 (Turnout). */
export function Contest({ contest, current = null, pin = false, initiallyOpen = false, onOpen, onCandidate, filter, actions, map }) {
  const [open, setOpen] = useState(initiallyOpen);
  const live = useLive();
  const entry = live.of(contest.id);
  const results = entry && entry !== NOT_COUNTED ? decodeResults(contest, entry) : null;
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
  const past = contest.past ? pastTurnout(contest) : null;
  const now = results?.eligible && results.voters !== null ? liveTurnout(results) : null;
  const head = html`<span class="contest-text">
      <${ContestHead}
        contest=${contest}
        unmuted=${unmuted + (current ? 1 : 0)}
        picked=${picked}
        results=${results}
        pending=${entry === NOT_COUNTED}
      />
    </span>
    ${past || now ? html`<${Turnout} past=${past} live=${now} />` : null}`;
  const list = useOwnId('km-list');
  const toggle = () => {
    setOpen(!open);
    onOpen?.(!open);
  };
  const row = (c, props) => html`<li key=${c.id}>
    <${CandidateRow} candidate=${c} onCandidate=${onCandidate} actions=${actions} ...${props} />
  </li>`;
  return html`
    <section class=${open || !opens ? 'contest open' : 'contest'}>
      <div class=${opens ? 'contest-bar opens' : 'contest-bar'}>
        ${
          opens
            ? html`<button
                type="button"
                class="contest-head"
                title=${tooltip}
                aria-expanded=${open ? 'true' : 'false'}
                aria-controls=${list}
                onClick=${toggle}
              >
                ${head}
              </button>`
            : html`<div class="contest-head">${head}</div>`
        }
        ${map ? html`<${ContestMapButton} contest=${contest} map=${map} counted=${Boolean(now)} />` : null}
      </div>
      ${open || !contest.candidates.length ? html`<${Holder} contest=${contest} />` : null}
      ${
        contest.candidates.length
          ? html`<ol class="cands" id=${list}>
              ${shown ? row(shown, { current: true }) : null}
              ${listed.map((c) => row(c, { muted: muted.get(c) }))}
            </ol>`
          : html`<p class="muted">${t('contest.no_candidates')}</p>`
      }
    </section>
  `;
}

/* A contest on the ballots, open unless the visitor has closed one of its
 * kind. *listed*: one of all the council obvody of an obec, listed at
 * once: closed, and how the visitor leaves it says nothing about the
 * kind. */
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

/* The visitor's work that the buttons on the rows change, as one value
 * {filter, picks}: crossing a candidate out takes off its circle, and
 * circling one takes off its cross. Each change is a function of it. */
const without = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : list);

const pick = (id) => (s) => ({
  picks: togglePick(s.picks, id),
  filter: s.filter.crossed.includes(id) ? { ...s.filter, crossed: without(s.filter.crossed, id) } : s.filter,
});

const cross = (id) => (s) =>
  s.filter.crossed.includes(id)
    ? { picks: s.picks, filter: { ...s.filter, crossed: without(s.filter.crossed, id) } }
    : { picks: without(s.picks, id), filter: { ...s.filter, crossed: [...s.filter.crossed, id] } };

/* Party *p*, or mark *name*, put in the filter in *mode*; already there
 * in it, taken out. */
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
 * make the two a double one: about what systems allow for a double-click,
 * and less than the height of a row, so that quick taps down a list of
 * numbers each count. */
const DOUBLE_MS = 400;
const DOUBLE_PX = 24;

/* The handlers that the buttons on candidate rows use (*actions* of
 * CandidateRow), for the rows inside *section* (a ref) of *candidates*
 * (id → candidate): the filter's (*filter*, `onFilter(next)`) and the
 * circles' (*picks*, `onPicks(next)`, picks.js).
 *
 * Each of those buttons has a press and an alternate one, the same on
 * every button: a number circles, the alternate crosses out; a party tag
 * or a mark shows only its candidates, the alternate hides them; each,
 * repeated, undoes itself. The alternate press is a Shift+click, or a
 * double click or tap, the only one a phone has: its first press has
 * done the other thing by then, which the second undoes before doing its
 * own. That first press may have moved the row (circling a muted
 * candidate lists it with the others), so the second counts wherever it
 * lands near the first.
 *
 * The party pointed at or focused has its candidates highlighted by a
 * class on their rows, not by rendering them again, which with a few
 * hundred candidates takes tens of milliseconds, while a pointer on its
 * way across the pane (dragging the map, say) passes many party tags. */
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
    // Before any button sees it, so that a second press on another (or on
    // the row, which would open the card) does only the alternate change.
    const onClick = (e) => {
      const f = first.current;
      if (!f || e.detail === 0 || !section.current?.contains(e.target)) return;
      first.current = null;
      if (e.timeStamp - f.time > DOUBLE_MS || Math.hypot(e.clientX - f.x, e.clientY - f.y) > DOUBLE_PX) return;
      e.stopPropagation();
      latest.current(f.alternate(f.before));
    };
    document.addEventListener('click', onClick, true);
    // Shift held, a button under the pointer previews its alternate press
    // (app.css `.shift`). The pointer's events catch a Shift pressed while
    // the window was in the background, a blur one released there.
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

/* The official documents that set the obvody of a council: its links stay
 * with the ballots rather than in About's list of every municipality. One
 * line each, the full title in the tooltip. */
function Sources({ sources }) {
  return html`
    <div class="sources">
      <p>${t('contest.sources')}</p>
      <ul>
        ${sources.map(([title, url]) => {
          const text = title || t('contest.source_document');
          return html`<li key=${url}>
            <a href=${url} title=${text} rel="noopener noreferrer" target="_blank">${text}</a>
          </li>`;
        })}
      </ul>
    </div>
  `;
}

/* The mode of a filter group as one button that switches it: an open eye
 * while only the group's candidates are shown, struck through while they
 * are hidden; the tooltip says which, and what a press does. */
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

/* The filter, under the place's name, in as few lines as fit: each group
 * (the parties shown, those hidden, each mark added) its mode and its
 * chips, a party's highlighting its candidates like a party in the list,
 * each removable (*actions* as for CandidateRow); the candidates crossed
 * out, counted, all removable at once; and a button that clears them all.
 * Stuck to the top while the lists scroll, it is ruled off from the pane's
 * close button beside it, which must not pass for the clear button. */
export function FilterBar({ filter, onFilter, actions }) {
  const { parties, marks, crossed } = filter;
  const added = MARKS.filter(([name]) => name in marks);
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
  // A party group's mode switched joins its parties to the other group.
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
      ${added.map(([name, , Icon]) => {
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

/* The ballots of obec *code*; *label* names the address, street or part
 * chosen in it, if any. *scope* ({obvod, street, part}) narrows its council
 * obvod (data.js `ballots`); `approximate`: the obvod was taken from the
 * map's approximate boundary at a clicked point. *focus*: the candidacy
 * whose card was just left, whose row then takes the focus. *filter* (see
 * NO_FILTER) and `onFilter(next)` the candidate filter; *picks* and
 * `onPicks(next)` the circled candidates (picks.js). `onArea(target)` fits
 * the map to a contest's area (data.js `contestArea`), the pin in its
 * header, leaving the place and these ballots as they are. */
export function Ballots({
  code,
  label,
  scope = {},
  approximate = false,
  focus,
  onCandidate,
  filter,
  onFilter,
  picks,
  onPicks,
  onArea,
}) {
  const { obvod = null, street = null, part = null } = scope;
  const [result, failed] = useLoaded(
    () => ballots(code, { obvod, street, part }),
    [code, obvod, street, part],
  );
  const [index] = useLoaded(dataIndex, []);
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
  const { obec, council, obvod: placeObvod, estimated, contests } = result;
  const municipal = contests.filter((c) => isMunicipal(c.id));
  const regional = contests.filter((c) => !isMunicipal(c.id));
  const firstCouncil = municipal.findIndex((c) => c.council);
  const where = [
    label ? obec.name : null,
    placeObvod ? t('place.obvod', { n: placeObvod }) : null,
    obec.okresName ? t('place.okres', { name: obec.okresName }) : null,
    t('place.kraj', { name: obec.krajName }),
  ].filter(Boolean);

  // Where the obvody are a guess, that matters more than how the obvod was found.
  const estimate = estimated ? t('council.estimated', { name: obec.name }) : null;
  const notes = {
    pending: () => t('council.pending', { n: obec.councils, name: obec.name }),
    choose: () => [t('council.choose', { n: obec.councils, name: obec.name }), estimate].filter(Boolean).join(' '),
    address: () => estimate ?? (approximate ? t('council.approximate') : null),
  };
  const note = notes[council]?.();
  const councilNote = note ? html`<${Notice}>${note}<//>` : null;

  // The sources of a council's obvody follow the last of its contests.
  const area = (c) => c?.id.split('/')[0];
  const pin = (c) => {
    if (!index || !onArea) return null;
    const target = contestArea(c.id, index);
    return { label: t(`card.map_${target.what}`), onClick: () => onArea(target) };
  };
  const withSources = (list, c, i) => html`
    <${BallotContest}
      key=${c.id}
      contest=${c}
      listed=${c.council === 'pending' || c.council === 'choose'}
      onCandidate=${onCandidate}
      filter=${filter}
      actions=${actions}
      map=${pin(c)}
    />
    ${c.sources.length && area(list[i + 1]) !== area(c) ? html`<${Sources} sources=${c.sources} />` : null}
  `;

  return html`
    <section class="ballots" aria-labelledby="km-place" ref=${section}>
      <header class="panel-head">
        <h2 id="km-place" tabindex="-1">${label ?? obec.name}</h2>
        <p class="muted">${where.join(' · ')}</p>
      </header>
      <${FilterBar} filter=${filter} onFilter=${onFilter} actions=${actions} />
      <p class="panel-body intro">${t('ballots.intro')}</p>
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
