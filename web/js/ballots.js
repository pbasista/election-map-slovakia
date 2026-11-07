/* The ballots of one place: every contest a voter there votes in, each with
 * its candidates in ballot order, or by votes once the 2026 results come
 * in (live.js). data.js `ballots` decides which contests apply. */

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import {
  ballots,
  candidacyUrl,
  contests,
  countryBallots,
  displayName,
  heldPlaces,
  inOffice,
  latestElection,
  ranBefore,
  useLoaded,
} from './data.js';
import {
  election,
  electionName,
  formatDate,
  formatList,
  formatNumber,
  formatPercent,
  logoUrl,
  polls,
  previous,
  researchCategories,
  standInSource,
  t,
} from './i18n.js';
import {
  AdvancedIcon,
  ChairIcon,
  CloseIcon,
  ColumnsIcon,
  CovidIcon,
  CrossOutIcon,
  DisputeIcon,
  ExpandIcon,
  EyeIcon,
  EyeOffIcon,
  FilterOffIcon,
  HistoryIcon,
  InkCircle,
  InkCross,
  LAYER_ICON,
  MedalIcon,
  MedalOutlineIcon,
  NoSeatsIcon,
  PersonIcon,
  PreferredIcon,
  PrisonIcon,
  SearchIcon,
  SubstituteIcon,
  WarningIcon,
  WithdrawnIcon,
} from './icons.js';
import {
  isByElection,
  isCity,
  isCountry,
  isList,
  isMunicipal,
  isNational,
  isParties,
  isSingle,
  officeOf,
  overviewKind,
  parseContest,
} from './kinds.js';
import {
  decodeResults,
  NOT_COUNTED,
  obecOkrsky,
  okrskyLoading,
  PAST,
  pastLabel,
  pastTitle,
  placePast,
  placeResults,
  resultsVars,
  unitWithin,
  useLive,
} from './live.js';
import { followLevel, MapButton, TurnoutMapButton, useDrawnOkrsky, useLevel, WinnerMapButton } from './mapmode.js';
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

/* Of a party's list: elected thanks to the preference votes, from a place
 * below the party's seats, overtaking those above on them; a substitute,
 * who takes a seat its party's member leaves. */
const isPreferred = (c) => {
  const r = c.result;
  return Boolean(r?.elected) && isList(c.contest) && r.seats !== null && c.number > r.seats;
};
const isSubstitute = (c) => Boolean(c.result?.substitute) && isList(c.contest);

/* The marks of a row that are filters too, in the bar's order, each with
 * whom it covers:
 * - elected: elected at the page's election, officially or called by this
 *   site on a partial count (live.js `decodeResults`);
 * - preferred, substitute: of a party's list (`isPreferred`,
 *   `isSubstitute`, ResultTags);
 * - affairs: research found serious controversies;
 * - disputes: research found disputed or lesser ones;
 * - researched: research done, whatever it found;
 * - office: held the office the contest elects at the time of the
 *   election (the chair); not for an election whose office holders are
 *   not known (i18n.js `previous` null), so no link can filter by it. */
const MARKS = [
  { name: 'elected', covers: (c) => Boolean(c.result?.elected || c.result?.called), Icon: MedalIcon },
  { name: 'preferred', covers: isPreferred, Icon: PreferredIcon },
  { name: 'substitute', covers: isSubstitute, Icon: SubstituteIcon },
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
  return t(key, { later: electionName(latestElection.day) });
}

/* For research reused from the latest election (data.js `decodeResearch`
 * `reused`), what it counts of it: *label* followed by that, else *label*. */
const withReuse = (r, label) =>
  r.reused
    ? `${label} ${t('research.reused_badge', { later: electionName(latestElection.day), day: formatDate(election) })}`
    : label;

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
 * (a vote by its name, a document by its date) and that the election's
 * state may have differed. */
const SUPPLEMENTED = {
  election: 'notice.supplemented_election',
  referendum: 'notice.supplemented_referendum',
  document: 'notice.supplemented_document',
};
const supplemented = (lead, { from, day }) =>
  `${lead} ${t(SUPPLEMENTED[from], { later: from === 'document' ? formatDate(day) : electionName(day) })}`;

/* A candidate's occupation; a machine translation names the Slovak
 * original in its tooltip (the card shows it in full). */
export function Occupation({ candidate: c }) {
  return c.occupationSk
    ? html`<span title=${t('candidate.occupation_sk', { text: c.occupationSk })}>${c.occupation}</span>`
    : c.occupation;
}

/* What is known of a candidate besides the name, on one line: the age and
 * the occupation (which ŠÚ SR's by-election packages of 2019–2022 do not
 * give) and, with *residence*, where a country-wide candidate lives. */
function about(c, residence) {
  const parts = [
    c.age !== null && t('candidate.age', { n: c.age }),
    c.occupation && html`<${Occupation} candidate=${c} />`,
    residence && c.residenceName,
  ].filter(Boolean);
  return parts.flatMap((part, i) => (i ? [' · ', part] : [part]));
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
 * *name* (MARKS) to the filter as the party tags add a party, pressed
 * while in the filter in either mode. */
function Mark({ name, cls, label, actions, children }) {
  if (!actions) return html`<span class=${cls} role="img" title=${label} aria-label=${label}>${children}</span>`;
  const mode = actions.markMode(name);
  const full = `${label} ${t(`filter.mark_${mode ?? 'none'}`, { name: t(`filter.${name}`) })}`;
  return html`<button
    type="button"
    class=${cls + activeClass(mode)}
    title=${full}
    aria-label=${full}
    aria-pressed=${mode ? 'true' : 'false'}
    ...${actions.markTap(name)}
  >
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
 * *run*, in election *election*, an entry of i18n.js `elections`): the
 * election by its full name and the contest, elected or not, the votes
 * with their share of the valid ballots (for a council: of the voters
 * with a valid ballot) and the place among the contest's candidates, where
 * published; a link opens its card on that election's page. */
export function OtherCandidacy({ election: e, run }) {
  const outcome =
    run.of === null
      ? t('ran.no_result')
      : t(run.elected ? 'ran.elected' : run.withdrew ? 'ran.withdrew' : 'ran.not_elected');
  const result =
    run.votes === null || !run.valid
      ? null
      : t(run.multi ? 'ran.result_multi' : 'ran.result', {
          votes: formatNumber(run.votes),
          share: formatPercent(run.votes / run.valid),
          rank: formatNumber(run.rank),
          of: formatNumber(run.of),
        });
  return html`<span class="other-run">
    <span><strong>${electionName(e.day)}</strong> · ${run.label}</span>
    <span class=${run.elected ? 'other-outcome elected-then' : 'other-outcome'}>${outcome}</span>${
      result ? html` · <span>${result}</span>` : null
    }
    <a class="other-open" href=${candidacyUrl(e.slug, run.id)}>${t('ran.open')}</a>
  </span>`;
}

/* The candidate stood for the same office at the election before (data.js
 * `ranBefore`): a clock turned back beside the chair, in the grey of past
 * figures. Not a filter like the other marks: a press shows how it went
 * then on a line under the name (*detail* the id of that line), pressed
 * again hides it. */
function RanBefore({ run, open, onToggle, detail }) {
  const label = t('ran.label', { when: electionName(run.election.day) });
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

/* The research marks of party *c* on a party-list ballot: those of its
 * list's candidates totalled (data.js `listResearch`, precomputed by the
 * build), in the order and look of a candidate's. Plain marks, not filter
 * buttons: the filters pick candidates, not parties. */
export function ListResearch({ candidate: c }) {
  const r = c.listResearch;
  const vars = (n) => ({ n: formatNumber(n), researched: formatNumber(r.researched), size: formatNumber(c.size) });
  const mark = (name, n) => {
    const { Icon } = MARKS.find((m) => m.name === name);
    return html`<${Mark} cls=${name} label=${t(`party.research_${name}`, vars(n))}><${Icon} />${formatNumber(n)}<//>`;
  };
  return html`<span class="marks">
    ${r.affairs ? mark('affairs', r.affairs) : null}
    ${r.disputes ? mark('disputes', r.disputes) : null}
    ${
      r.findings
        ? html`<${Mark} cls="researched" label=${t('party.research_findings', vars(r.findings))}>
            <${SearchIcon} />${formatNumber(r.findings)}
          <//>`
        : html`<${Mark} cls="researched none" label=${t('party.research_findings_none', vars(0))}><${SearchIcon} /><//>`
    }
  </span>`;
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

/* What the results say of a candidate beyond being elected, after the
 * name, an icon in a capsule each, its tooltip and accessible label
 * saying it in full: through to a presidential round 2 (an arrow into a
 * 2) and, on a party's list, elected thanks to the preference votes (an
 * arrow up beside a list), both in the results' green, or a substitute (a
 * person beside the arrows of a swap, in a quiet dashed capsule: not
 * elected, though in line for a seat). The last two are filter marks
 * (MARKS), buttons like the research's. */
function ResultTags({ candidate: c, actions }) {
  const r = c.result;
  const seats = { seats: formatNumber(r.seats ?? 0) };
  const mark = (name, Icon) =>
    html`<${Mark} name=${name} cls=${`result-tag ${name}`} label=${t(`party.${name}_title`, seats)} actions=${actions}>
      <${Icon} />
    <//>`;
  return [
    r.advanced &&
      html`<span class="result-tag advanced" role="img" title=${t('president.advanced_title')} aria-label=${t('president.advanced')}>
        <${AdvancedIcon} />
      </span>`,
    isSubstitute(c) && mark('substitute', SubstituteIcon),
    isPreferred(c) && mark('preferred', PreferredIcon),
  ];
}

/* A candidate's 2026 votes: their share on a bar in the results' green,
 * then the number; a list person's preference votes, their share of the
 * party's votes. A candidate who withdrew yet stayed on the ballot,
 * whose votes count, in grey and tagged so. */
export function Votes({ candidate: c }) {
  const r = c.result;
  if (r.share === null) return null;
  const list = isList(c.contest);
  const vars = { votes: formatNumber(r.votes), valid: formatNumber(r.valid), share: formatPercent(r.share) };
  const label = t(list ? 'party.votes_title' : r.multi ? 'results.votes_title_multi' : 'results.votes_title', vars);
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
  // A presidential candidate stands for no party, a list person for the
  // party of the list they are on: where they live says more. Research is
  // done on the candidates of the regular elections only.
  const country = isCountry(c.contest);
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
          ${c.result ? html`<${ResultTags} candidate=${c} actions=${actions} />` : null}
          ${country ? null : html`<${Parties} candidate=${c} actions=${actions} />`}
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
            ${country && !c.research ? null : html`<${Researched} candidate=${c} actions=${actions} />`}
          </span>
        </span>
        ${c.result ? html`<${Votes} candidate=${c} />` : null}
        ${seat ? html`<span class="sr-only">${t('results.in_seats', { place: seat.place, n: formatNumber(seat.seats) })}</span>` : null}
        <span class="meta" id=${metaId}>
          ${about(c, country)}
        </span>
        ${
          before && showBefore
            ? html`<span class="ran-detail" id=${beforeId}><${OtherCandidacy} election=${before.election} run=${before} /></span>`
            : null
        }
      </span>
      ${c.result && c.result.share !== null ? html`<${MapButton} candidate=${c} label=${c.result.contestLabel} at=${c.result.at} />` : null}
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
  const { kind, area } = parseContest(id);
  return isCity(area) ? `${kind}:city` : kind;
}

/* A percentage of the config (a party's threshold, 5.0) as the page
 * writes it: "5 %", "5,5 %". */
const formatThreshold = (percent) => formatPercent(percent / 100, Number.isInteger(percent) ? 0 : 1);

/* The rules of a contest that its header leaves to a note (`ContestFacts`),
 * as sentences: of a party-list ballot, what a party needs for seats, what
 * coalitions need by how many parties they are of, where that differs, and
 * how many preference votes a voter may give on a party's list; of a
 * referendum question, when the referendum is valid and an answer wins,
 * and how the turnout's bar marks that (`Turnout`); of a presidential
 * round, what decides it (round 1 is won by more than half of the votes
 * of all registered voters, else the two best go to round 2, which the
 * one with more votes wins). Null for the other contests. */
function contestRules(contest, parties, referendum) {
  if (referendum) return [t('referendum.rules'), t('referendum.rules_bar')];
  if (parseContest(contest.id).kind === 'prezident') return [t(`president.rule_${contest.round}`)];
  if (!parties) return null;
  const rules = [t('contest.rules_threshold', { share: formatThreshold(contest.threshold) })];
  if (contest.coalitions.length) {
    const ranges = contest.coalitions.map(([from, share], i) => {
      const next = contest.coalitions[i + 1];
      const vars = { from: formatNumber(from), share: formatThreshold(share) };
      if (!next) return t('contest.rules_coalitions_from', vars);
      if (next[0] - 1 === from) return t('contest.rules_coalitions_exactly', vars);
      return t('contest.rules_coalitions_range', { ...vars, to: formatNumber(next[0] - 1) });
    });
    rules.push(t('contest.rules_coalitions', { list: ranges.join(', ') }));
  }
  if (contest.preferences) rules.push(t('contest.rules_preferences', { n: formatNumber(contest.preferences) }));
  return rules;
}

/* What stands under a contest's name, short:
 * - how many are elected: one mayor or president; a council's seats where
 *   known (from the decisions on the obvody, else from the 2026 results
 *   once they give them), otherwise the 2022 number, labelled so; a
 *   party-list body's seats; that a referendum question is answered yes
 *   or no;
 * - how many stand (persons or parties), and how many of them the filter
 *   leaves shown (*unmuted*) where it mutes some; where only the elected
 *   are known (data.js `electedOnly`), that the others are not published;
 * - how many the visitor has circled (*picked*), if any. With more
 *   circled than are elected (one party), which would make a real ballot
 *   invalid, both numbers carry a warning. Circling more is still allowed:
 *   the visitor may circle a shortlist to choose from later;
 * - of a party-list ballot or a referendum question, a button that unfolds
 *   its rules under the line (`contestRules`; a list's own facts are its
 *   party's row's tooltip, `listFacts`), folded at first.
 * Once the count reaches the contest, a line says how far it has got
 * (ResultsLine), with the valid votes of the unit its results show at
 * (*results*, `scopedResults`); a contest without a final result (data.js
 * `noResult`) says so instead. *id*: the element's, which the header's
 * button refers to. */
export function ContestFacts({ id, contest, unmuted, picked, results, pending }) {
  const [rulesOpen, setRulesOpen] = useState(false);
  const rulesId = useOwnId('km-rules');
  const n = contest.candidates.length;
  const single = isSingle(contest.id);
  const parties = isParties(contest.id);
  const referendum = parseContest(contest.id).kind === 'referendum';
  const seats = contest.seats ?? results?.reportedSeats ?? null;
  let elected = null;
  if (referendum) elected = t('referendum.facts');
  else if (parties) elected = t('contest.seats', { n: formatNumber(seats) });
  else if (single) elected = t('contest.single');
  else if (seats) elected = t('contest.seats', { n: formatNumber(seats) });
  else if (contest.seats2022) elected = t('contest.seats_previous', { n: formatNumber(contest.seats2022) });
  const count = (key) =>
    unmuted < n
      ? t(`${key}_filtered`, { shown: formatNumber(unmuted), n: formatNumber(n) })
      : t(key, { n: formatNumber(n) });
  const candidates = referendum ? null : count(parties ? 'contest.party_count' : 'contest.candidates');
  const limit = single ? 1 : (seats ?? contest.seats2022);
  const over = limit !== null && picked > limit;
  const tooMany = parties ? 'contest.too_many_parties' : 'contest.too_many';
  const warning = over ? t(tooMany, { picked: formatNumber(picked), n: formatNumber(limit) }) : null;
  const rules = contestRules(contest, parties, referendum);
  // Each fact a piece of its own, so that a line breaks between them only;
  // the one that states the limit is marked with the circled when over it.
  const fact = (cls, text) =>
    over && cls
      ? html`<span class=${`fact ${cls} over`} title=${warning}><${WarningIcon} />${text}</span>`
      : html`<span class="fact">${text}</span>`;
  const facts = [
    elected && fact(referendum || parties ? null : 'seats', elected),
    candidates && fact(null, candidates),
    contest.electedOnly && fact(null, t('contest.elected_only')),
    picked && fact('picked', t('contest.picked', { n: formatNumber(picked) })),
    rules &&
      html`<button
        type="button"
        class="rules-toggle"
        aria-expanded=${rulesOpen ? 'true' : 'false'}
        aria-controls=${rulesId}
        onClick=${() => setRulesOpen(!rulesOpen)}
      >
        ${t('contest.rules')}<${ExpandIcon} />
      </button>`,
  ].filter(Boolean);
  return html`<span class="contest-text" id=${id}>
    <span class="contest-meta">${facts.flatMap((f, i) => (i ? ['\u00a0· ', f] : [f]))}</span>
    ${
      rules
        ? // A press in the note is the note's, not the header's that it is in
          // and that a press opens or closes (`Contest`).
          html`<span class="contest-rules" id=${rulesId} hidden=${!rulesOpen} onClick=${(e) => e.stopPropagation()}>
            ${rules.map((rule) => html`<span>${rule}</span>`)}
          </span>`
        : null
    }
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

/* How far the 2026 count of a contest has got, in the results' green
 * (`resultsText`), or that it has not started. */
function ResultsLine({ results: r, single }) {
  if (!r) return html`<span class="contest-results pending">${t('results.pending')}</span>`;
  const said = resultsText(r, single);
  if (!said) return null;
  return html`<span class=${`contest-results ${r.status}`} title=${said.title}>
    ${r.status === 'partial' ? html`<span class="live-dot" aria-hidden="true"></span>` : null}${said.text}
  </span>`;
}

/* How far the 2026 count of results *r* (live.js `decodeResults`) has got,
 * {text, title} (a tooltip or null), of a single-winner contest
 * (*single*) or a party's *list*:
 * - counting: the share counted (of its registered voters, live.js
 *   `countShare`; its okrsky in the tooltip) and the valid votes counted,
 *   which tell how much a lead may still change;
 * - counted with only the winners so far (municipal contests on election
 *   night);
 * - final: the valid votes alone (of a party's list: the party's), as
 *   final goes without saying once the elections are over; null without
 *   them. */
function resultsText(r, single, list = false) {
  if (r.status === 'final' && !r.valid) return null;
  // A party's list counts the party's votes and its candidates' preference
  // votes (summed by `ems results`), not valid ballots of its own.
  const vars = { ...resultsVars(r), preferences: formatNumber(r.preferences ?? 0) };
  const key = (name) => (list ? `party.list_${name}` : `results.${name}`);
  if (r.status === 'partial') {
    return {
      text: t(r.counted ? key('counting') : key('counting_votes'), vars),
      title: r.counted ? t(r.registered === null ? 'results.counting_units' : 'results.counting_title', vars) : null,
    };
  }
  if (r.status === 'winner') {
    return {
      text: t(single || r.filled === null ? 'results.counted_mayor' : 'results.counted_council', vars),
      title: t('results.counted_title'),
    };
  }
  return { text: t(key('valid_votes'), vars), title: null };
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
 * the map (mapmode.js `TurnoutMapButton`). A referendum's marks the
 * turnout it needs to be valid, *quorum* (a share), with a dashed line
 * across the track, the last referendum's tick staying solid; the tooltip
 * names both. *at*: the level the contest's results show at
 * (`levelAt`). */
function Turnout({ contest, past, live, quorum = null, at = null }) {
  const main = live ?? past;
  const tick = live && past;
  // No space after the mark: the narrow meter would break the line there.
  const percent = (x) => `${x.approx ? '≈' : ''}${formatPercent(x.share, 0)}`;
  const marks = quorum
    ? [
        t('referendum.quorum', { share: formatPercent(quorum, 0) }),
        tick && t('referendum.past_tick', { year: past.year, share: percent(past) }),
      ]
    : [];
  const label = [past?.label, live?.label, ...marks].filter(Boolean).join(' ');
  const lines = html`
    <span class="gauge-line"><strong>${percent(main)}</strong>${main.year}</span>
    <span class="gauge-bar">
      <span class="gauge-fill" style=${{ width: width(main.share) }}></span>
      ${tick ? html`<span class="gauge-tick" style=${{ left: width(past.share) }}></span>` : null}
      ${quorum ? html`<span class="gauge-quorum" style=${{ left: width(quorum) }}></span>` : null}
    </span>
    ${tick ? html`<span class="gauge-line past"><span>${percent(past)}</span>${past.year}</span>` : null}
  `;
  if (!live) return html`<span class="gauge" role="img" aria-label=${label} title=${label}>${lines}</span>`;
  return html`<${TurnoutMapButton} contest=${contest} figures=${label} at=${at}>
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
  else if (p.method !== null) note = `${t('turnout.obvod', { method: pastLabel(p.method) })} ${pastTitle(p.method, p.date)}`;
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

/* A unit's turnout in the election before (live.js `pastOf`,
 * `placeResults`: {day, method, record}), labelled with the unit (*unit*,
 * its name; none for an okrsok, which the sentence names) and how its
 * figures were found; where they are not known, null. */
const unitPast = ({ day, method, record }, unit = null) => {
  if (!record) return null;
  const [eligible, voters] = record;
  const text = t(unit ? 'turnout.unit' : 'turnout.okrsok', {
    unit,
    previous: day.slice(0, 4),
    voters: formatNumber(Math.round(voters)),
    eligible: formatNumber(Math.round(eligible)),
    turnout: formatPercent(voters / eligible),
    method: pastLabel(method),
  });
  return {
    share: voters / eligible,
    year: day.slice(0, 4),
    label: method === PAST.same ? text : `${text} ${pastTitle(method, day)}`,
    approx: method !== PAST.same,
  };
};

/* Results *r* (live.js `decodeResults`) narrowed to a unit of the contest's
 * area, *record* [eligible, voters, valid, {number: votes}] (live.js
 * `placeResults`; a party's list's with its preference votes, summed by
 * `ems results`, fifth): the unit's votes, shares and turnout. Who is
 * elected and the state of the count stay the contest's. Made once per
 * record and results (the results' own objects, decoded once), as the
 * ballots narrow every party's list on every render. */
const narrowed = new WeakMap();
function inUnit(r, record) {
  const kept = narrowed.get(record);
  if (kept?.r === r) return kept.results;
  const [eligible, voters, valid, votes, preferences = null] = record;
  const byNumber = new Map(
    [...r.byNumber].map(([n, x]) => {
      const v = votes[n] ?? 0;
      return [n, { ...x, votes: x.votes === null ? null : v, share: x.share === null || !valid ? null : v / valid }];
    }),
  );
  const results = { ...r, eligible, voters, valid, preferences, byNumber };
  narrowed.set(record, { r, results });
  return results;
}

/* Results *r* (live.js `decodeResults`) in a unit whose votes are not
 * known: who is elected and the state of the count, no votes. */
function withoutVotes(r) {
  const byNumber = new Map([...r.byNumber].map(([n, x]) => [n, { ...x, votes: null, share: null }]));
  return { ...r, eligible: null, voters: null, valid: null, byNumber };
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
  const unit = unitWithin(units, level);
  return { whole, units, unit, results: unit ? inUnit(whole, unit.record) : whole };
}

/* The level results of a contest show at, as the buttons that put them
 * on the map take it (mapmode.js `MapButton`, `WinnerMapButton`,
 * `TurnoutMapButton` *at*): the scope of *unit* (`scopedResults`, null
 * for the whole) and *place* (as `Contest` takes it). */
const levelAt = (unit, place) => ({ level: unit?.scope ?? 'all', place });

/* The name of *scope* (one of SCOPES) of *place* (as `Contest` takes
 * it) in contest *id*: the whole of a country-wide one is the country. */
function scopeName(scope, place, id) {
  if (scope === 'all') return t(isCountry(id) ? 'scope.country' : 'scope.all');
  if (scope === 'obec') return place.name;
  if (scope === 'kraj') return t('scope.kraj', { name: place.krajName });
  if (scope === 'okres') return t('scope.okres', { name: place.okresName });
  return t(`scope.${scope}`, { n: place[scope] });
}

/* The choice of scope for a contest's results, where the place shown lies
 * in units of its area with figures of their own (*units*, live.js
 * `placeResults`): the whole contest or one of those units, *shown* (one
 * of live.js SCOPES) pressed. A press sets the scope for every contest on
 * the ballots (`onLevel(scope, place, id)`). *place*: as `Contest` takes
 * it; *id* the contest's. */
function ScopeChoice({ units, shown, place, id, onLevel }) {
  return html`<div class="contest-scope" role="group" aria-label=${t('scope.label')}>
    ${['all', ...units.map((u) => u.scope)].map(
      (scope) => html`<button
        type="button"
        key=${scope}
        aria-pressed=${scope === shown ? 'true' : 'false'}
        onClick=${() => onLevel(scope, place, id)}
      >
        ${scopeName(scope, place, id)}
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
export function byFilter(candidates, filter, actions, ranked) {
  const byVotes = ranked ? [...candidates].sort((a, b) => (b.result?.votes ?? -1) - (a.result?.votes ?? -1)) : candidates;
  const sorted = lastWhere(byVotes, (c) => c.result?.withdrawn);
  const muted = new Map(sorted.map((c) => [c, !actions.isPicked(c.id) && isMuted(c, filter)]));
  const order = lastWhere(sorted, (c) => muted.get(c));
  return { order, muted, unmuted: order.length - [...muted.values()].filter(Boolean).length };
}

/* The candidates of *contest* with their 2026 results (*results*, live.js
 * `decodeResults`) as `result`: what a row shows and the filter's
 * `elected` mark reads, with what explains a call, and the seats (of a
 * party's list: the party's); *at* (`levelAt`) the level they show at,
 * for the row's map button. */
export function withResults(contest, results, at = null) {
  if (!results) return contest.candidates;
  const extra = {
    call: results.call,
    past: contest.past,
    valid: results.valid,
    eligible: results.eligible,
    seats: results.seats,
    multi: !isSingle(contest.id),
    contestLabel: contest.label,
    at,
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

/* What a contest's results do not have (*r* the whole contest's, live.js
 * `decodeResults`), said where its rows would otherwise stand puzzlingly
 * without votes: counting on election night, but no candidate's votes
 * yet; or counted with the turnout and at most the winners (status
 * `winner`), naming them where known, as the candidates' votes are not
 * published until the final results; or final with the votes of the
 * elected only (the by-elections of 2019–2022). Null where the votes are
 * there. A withdrawn candidate may have none: ŠÚ SR leaves out a party that
 * withdrew from a party-list ballot (EP 2024, Piráti), whose votes are
 * invalid. */
function resultsNote(contest, r) {
  if (!r) return null;
  if (r.status === 'final') {
    const unpublished = contest.candidates.some((c) => !c.withdrawn && !r.byNumber.has(c.number));
    return r.byNumber.size && unpublished ? t('results.note_elected_only') : null;
  }
  const all = [...r.byNumber.values()];
  if (r.status === 'partial') return all.some((x) => x.votes !== null) ? null : t('results.note_partial');
  const elected = all.filter((x) => x.elected).length;
  if (elected && elected >= contest.candidates.length) return t('results.note_all_elected');
  if (elected) return t('results.note_winner');
  return t(r.eligible === null ? 'results.note_counted' : 'results.note_turnout');
}

/* Whether a referendum question was decided, once its results are final
 * (*r* the whole question's, live.js `decodeResults`): valid only where
 * more than half of the registered voters took part and an answer has
 * more than half of the valid votes (its flag). */
function Verdict({ contest, results: r }) {
  if (r?.status !== 'final' || !r.eligible) return null;
  const turnout = r.voters / r.eligible;
  const won = contest.candidates.find((c) => r.byNumber.get(c.number)?.elected);
  let text;
  if (turnout <= QUORUM) text = t('referendum.invalid_turnout', { turnout: formatPercent(turnout) });
  else if (!won) text = t('referendum.no_majority');
  else {
    const share = formatPercent(r.byNumber.get(won.number).share);
    text = t('referendum.valid', { answer: t(`referendum.${won.answer}`), share });
  }
  return html`<p class=${won ? 'verdict valid' : 'verdict'}>${text}</p>`;
}

/* The share of the registered voters a referendum needs to take part. */
const QUORUM = 0.5;

/* The choice to show a referendum question's whole wording, by contest
 * id: kept for the visit, as the same question shows at every place. */
const questionsOpen = new Map();
const QUESTION_LINES = 5;

/* A referendum question's wording, quoted under its contest's header. One
 * longer than QUESTION_LINES lines is cut to them (app.css
 * `.question-text.clamped`), so that the answers' figures stay in view
 * from place to place, with a button that shows it all and cuts it again;
 * screen readers have it whole either way, the cut being only drawn.
 * Whether it is that long is measured when it mounts and when its width
 * changes, not on every render: the whole wording's height, which the cut
 * does not change (scrollHeight), against the lines'. */
function Question({ id, text }) {
  const ref = useRef(null);
  const textId = useOwnId('km-question');
  const [long, setLong] = useState(false);
  const [open, setOpen] = useState(() => questionsOpen.get(id) ?? false);
  useLayoutEffect(() => {
    const el = ref.current;
    let width = null;
    const measure = () => {
      if (el.clientWidth === width) return;
      width = el.clientWidth;
      setLong(el.scrollHeight > Number.parseFloat(getComputedStyle(el).lineHeight) * QUESTION_LINES + 1);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text]);
  const toggle = () => {
    questionsOpen.set(id, !open);
    setOpen(!open);
  };
  return html`<div class="question">
    <blockquote ref=${ref} id=${textId} class=${long && !open ? 'question-text clamped' : 'question-text'}>
      ${t('referendum.quote', { text })}
    </blockquote>
    ${
      long
        ? html`<button type="button" class="question-toggle" aria-expanded=${open ? 'true' : 'false'} aria-controls=${textId} onClick=${toggle}>
            ${t(open ? 'referendum.question_less' : 'referendum.question_more')}<${ExpandIcon} />
          </button>`
        : null
    }
  </div>`;
}

/* An answer to a referendum question: "Yes" or "No", with its votes once
 * counted and a medal where it won. Not circled: the site shows the
 * question, it does not take part in it. */
function AnswerRow({ candidate: c }) {
  const r = c.result;
  return html`<div class="cand answer">
    <span class="who">
      <span class="name-line">
        <span class="name" data-candidate=${c.id}>${t(`referendum.${c.answer}`)}</span>
        ${r?.elected ? html`${' '}<${Mark} cls="elected" label=${t('referendum.won')}><${MedalIcon} /><//>` : null}
      </span>
      ${r ? html`<${Votes} candidate=${c} />` : null}
    </span>
    ${r && r.share !== null ? html`<${MapButton} candidate=${c} label=${r.contestLabel} at=${r.at} />` : null}
  </div>`;
}

/* How many persons of a party's list show before "show all". */
const LIST_FIRST = 20;

/* The contest of party *party*'s list (the party contest's candidate),
 * loaded once for the page: the party's row reads it for its facts and
 * map button (`listFacts`), the list under it for its persons. A failure
 * is not kept, so that the list tries again when opened again. */
const listContests = new Map();
function loadList(party) {
  const id = `${party.contest}/${party.number}`;
  if (!listContests.has(id)) {
    const loading = contests([id]).then(([c]) => c ?? null);
    loading.catch(() => listContests.delete(id));
    listContests.set(id, loading);
  }
  return listContests.get(id);
}

/* What a party's list *list* (`loadList`) has, said on its party's row
 * (`PartyRow`) rather than over the list, which then starts with its
 * persons; as `ContestFacts` says a contest's, a line each: its
 * candidates (and how many the filter leaves shown), how many preference
 * votes a voter may give, how far the count has got in the row's unit
 * (*place*, *scope*: the party's votes and the preference votes there;
 * none where the list has no figures of that unit, `PartyList`), and how
 * many the visitor has circled on it, with a warning (*warning*) where
 * more than the preference votes, which would make them all void on a
 * real ballot. *at*: where the results give the list's preference votes
 * by obec (`areas`), which the whole country's figures alone would not,
 * the level (`levelAt`) of the row's unit for the button that shows who
 * got the most of them where; else null. */
function listFacts(list, entry, { place, scope, filter, actions }) {
  const { whole, unit, results } = scopedResults(list, entry, place, scope);
  const n = list.candidates.length;
  const { unmuted } = byFilter(withResults(list, whole), filter, actions, false);
  const picked = list.candidates.filter((c) => actions.isPicked(c.id)).length;
  const limit = list.preferences;
  const warning =
    limit !== null && picked > limit
      ? t('contest.too_many_preferences', { picked: formatNumber(picked), n: formatNumber(limit) })
      : null;
  let count = null;
  if (list.noResult) count = t('results.no_result');
  else if (whole && !unitMissing(whole, unit, scope)) count = resultsText(results, isSingle(list.id), true)?.text;
  else if (entry === NOT_COUNTED) count = t('results.pending');
  const lines = [
    unmuted < n
      ? t('contest.candidates_filtered', { shown: formatNumber(unmuted), n: formatNumber(n) })
      : t('contest.candidates', { n: formatNumber(n) }),
    limit && t('contest.preferences', { n: formatNumber(limit) }),
    count,
    picked && t('contest.picked', { n: formatNumber(picked) }),
    warning,
  ];
  const winnerMap = Boolean(whole?.valid && entry.areas) && [...whole.byNumber.values()].some((r) => r.votes);
  return { text: lines.filter(Boolean).join('\n'), picked, warning, at: winnerMap ? levelAt(unit, place) : null };
}

/* Where a party's list shows the results of unit *scope* (one of live.js
 * SCOPES; *whole*, *unit* as `scopedResults` gives them), whether it has
 * no figures of that unit: the list's preference votes are published for
 * fewer units than the party's votes, and those of a coarser unit do not
 * stand in for them. */
const unitMissing = (whole, unit, scope) => Boolean(whole) && scope !== 'all' && unit?.scope !== scope;

/* The places of the persons of a party's list in the order the law gives
 * them seats (Act No. 180/2014 Coll. § 68 ods. 5, § 94 ods. 5; results.py
 * `preference_order`, which the results are checked against): ballot
 * number → place of those whose preference votes reach *quota* % of the
 * party's votes, first, by their votes (a tie by list position); the rest
 * follow them by list position. *source* is the list's live entry (the
 * whole country's: the official order) or a unit's record [eligible,
 * voters, valid, {number: votes}] (live.js `placeResults`), whose votes
 * rank the list there. Made once per source: the results' own objects stay
 * as long as their file, so a render sorts only the few that reach it. */
const preferenceRanks = new WeakMap();
function preferenceRank(quota, source) {
  let ranks = preferenceRanks.get(source);
  if (ranks) return ranks;
  const [valid, votes] = Array.isArray(source)
    ? [source[2], Object.entries(source[3]).map(([n, v]) => [Number(n), v])]
    : [source.valid, source.candidates];
  const least = ((quota ?? 0) * (valid ?? 0)) / 100;
  const ahead = votes.filter(([, v]) => v >= least).sort((a, b) => b[1] - a[1] || a[0] - b[0]);
  ranks = new Map(ahead.map(([n], i) => [n, i]));
  preferenceRanks.set(source, ranks);
  return ranks;
}

/* *candidates* of a party's list (`withResults`) in the order of
 * `preferenceRank`. */
function byPreference(candidates, quota, source) {
  const ranks = preferenceRank(quota, source);
  const place = (c) => ranks.get(c.number) ?? ranks.size + c.number;
  return [...candidates].sort((a, b) => place(a) - place(b));
}

/* A party's list (*party* the party contest's candidate), loaded when
 * opened (`loadList`; its facts are its row's, `listFacts`): what a voter
 * may circle on it, its persons; counted, with their preference votes
 * (`Votes`) in the unit of the party's row (*place*, *scope*: one of
 * live.js SCOPES, the unit whose votes the row shows), in the order the
 * preference rule gives them there (`byPreference`: of the whole list, the
 * elected first as they got their seats), else in list order. Where the
 * list has no figures of that unit (`unitMissing`), none of a coarser one
 * stand in for them: its persons show no votes, in the whole list's
 * order, under a note that the unit's are not published. Under its row on
 * the ballots, the first LIST_FIRST and those circled until "show all",
 * and with `onOverview(number)` a button that opens it in the overview of
 * the lists (overview.js); there (*full*), all of them at once, in as many
 * columns as fit (app.css). *id*: the element's. *focus*: a candidacy on
 * it whose row takes the focus once the list is in (the card just left). */
export function PartyList({
  id,
  party,
  onCandidate,
  filter,
  actions,
  place = null,
  scope = 'all',
  full = false,
  onOverview,
  focus = null,
}) {
  const [contest, failed] = useLoaded(() => loadList(party), [party.id]);
  const [all, setAll] = useState(false);
  const live = useLive();
  useEffect(() => {
    if (contest && focus) document.getElementById(id)?.querySelector(`[data-candidate="${CSS.escape(focus)}"]`)?.focus();
  }, [contest, focus]);
  if (failed) return html`<p class="party-list error" id=${id}>${t('error.load')}</p>`;
  if (contest === undefined) return html`<p class="party-list muted loading" id=${id}>${t('panel.loading')}</p>`;
  if (!contest) return null;
  const entry = live.of(contest.id);
  const { whole, unit, results } = scopedResults(contest, entry, place, scope);
  // The unit's figures may yet come with its okrsok file; until then, none.
  const missing = unitMissing(whole, unit, scope);
  const unpublished = missing && !okrskyLoading(contest.id, place.obec);
  const candidates = withResults(contest, missing ? withoutVotes(whole) : results, levelAt(unit, place));
  const { order, muted } = byFilter(
    whole ? byPreference(candidates, contest.quota, unit && !missing ? unit.record : entry) : candidates,
    filter,
    actions,
    false,
  );
  const shown = all || full ? order : order.filter((c, i) => i < LIST_FIRST || actions.isPicked(c.id));
  const more = !full && order.length > LIST_FIRST;
  return html`<div class="party-list" id=${id}>
    ${unpublished ? html`<p class="results-note">${t('party.list_unpublished', { unit: scopeName(scope, place, contest.id) })}</p>` : null}
    <ol class="cands">
      ${shown.map(
        (c) => html`<li key=${c.id}>
          <${CandidateRow} candidate=${c} onCandidate=${onCandidate} actions=${actions} muted=${muted.get(c)} />
        </li>`,
      )}
    </ol>
    ${
      more || onOverview
        ? html`<div class="list-buttons">
            ${
              more
                ? html`<button type="button" class="list-more" aria-expanded=${all ? 'true' : 'false'} onClick=${() => setAll(!all)}>
                    ${t(all ? 'party.show_first' : 'party.show_all', { n: formatNumber(all ? LIST_FIRST : order.length) })}
                  </button>`
                : null
            }
            ${
              onOverview
                ? html`<button type="button" class="list-more" onClick=${() => onOverview(party.number)}>
                    <${ColumnsIcon} />${t('overview.open_party')}
                  </button>`
                : null
            }
          </div>`
        : null
    }
  </div>`;
}

/* The seats a party won (*result* its row's): a green badge with a person
 * and their number; the label says it in words. */
export function SeatsWon({ result: r }) {
  return html`<span class="seats-won" title=${t('party.won_title', { n: formatNumber(r.won), seats: formatNumber(r.seats) })}>
    <${PersonIcon} /><span aria-hidden="true">${formatNumber(r.won)}</span>
    <span class="sr-only">${t('party.won', { n: formatNumber(r.won) })}</span>
  </span>`;
}

/* Why party *c* won no seats, once the whole country's results *whole*
 * (live.js `decodeResults`) are final, whatever unit its row shows: its
 * share of the valid votes below its own threshold, a coalition's where
 * that is above the parties' own (*threshold*). Null for a party with
 * seats, one that withdrew, and while the count goes on, when a share
 * below the threshold may still rise. */
export function noSeatsReason(c, whole, threshold) {
  if (whole?.status !== 'final') return null;
  const r = whole.byNumber.get(c.number);
  if (!r || r.withdrawn || r.won || r.share === null || r.share * 100 >= c.threshold) return null;
  return t(c.threshold > threshold ? 'party.no_seats_coalition' : 'party.no_seats_single', {
    share: formatPercent(r.share),
    threshold: formatThreshold(c.threshold),
  });
}

/* A party that won no seats (*why*, `noSeatsReason`): the seats' person
 * struck through after its name, where one that won has the person and
 * their number (`SeatsWon`); the tooltip and label say why. */
export function NoSeats({ why }) {
  const mask = useOwnId('km-no-seats');
  return html`<span class="no-seats" title=${why}>
    <${NoSeatsIcon} id=${mask} /><span class="sr-only">${why}</span>
  </span>`;
}

/* A party on a party-list ballot: its ballot number, which circles it as
 * a voter circles the party on the ballot (the alternate press crosses it
 * out, as on a candidate's row), its logo, name and short form (which a
 * logo need not spell out; its tooltip says what it is), its list's
 * research marks (`ListResearch`), and how many stand on its list (with a
 * coalition's threshold where it differs),
 * with the list's facts (`listFacts`) in the tooltip of that line and of
 * the name, and how many are circled on it where any are, warned where
 * too many. Counted, its votes (in the unit *scope* of *place*, as its
 * contest shows them) and the seats it won, or once final without any,
 * greyed with why (*noSeats*, `noSeatsReason`: the whole country's result,
 * which no unit's share changes). At its end, the buttons that put on
 * the map who got the most preference votes on its list where (mapmode.js
 * `WinnerMapButton`, where the list has them by obec) and its votes
 * (`MapButton`), as a contest's header has the winner's beside its
 * turnout. A press on the row opens its list under it (`PartyList`, with
 * *onOverview*, in the same unit). *threshold*: the parties' own, beside
 * which its line names a coalition's.
 *
 * With `onSelect(number)`, it is one of the parties of the overview of the
 * lists (overview.js), named by its short form: a press selects it, whose
 * list the overview shows beside (*selected*), instead. */
export function PartyRow({
  candidate: c,
  onCandidate,
  actions,
  muted,
  noSeats = null,
  threshold,
  filter,
  place = null,
  scope = 'all',
  onOverview,
  selected = false,
  onSelect = null,
}) {
  const [open, setOpen] = useState(false);
  const listId = useOwnId('km-party-list');
  const [list] = useLoaded(() => loadList(c), [c.id]);
  const live = useLive();
  const facts = list ? listFacts(list, live.of(list.id), { place, scope, filter, actions }) : null;
  // The list's facts after what a hover over the name says it does.
  const titled = (title) => (facts ? `${title}\n\n${facts.text}` : title);
  const picked = actions.isPicked(c.id);
  const crossed = !picked && actions.isCrossed(c.id);
  const r = c.result;
  const p = c.party;
  const tab = onSelect !== null;
  const classes = [
    'cand',
    'party-row',
    crossed && 'crossed',
    muted && 'dimmed',
    noSeats && 'unseated',
    tab && selected && 'selected',
  ];
  const state = crossed ? t('pick.crossed_state') : muted ? t('filter.muted') : null;
  const coalition = c.threshold > threshold;
  const toggle = tab ? () => onSelect(c.number) : () => setOpen(!open);
  return html`
    <div
      class=${classes.filter(Boolean).join(' ')}
      onClick=${(e) => {
        if (!e.target.closest('button, a')) toggle();
      }}
    >
      <button
        type="button"
        class="num"
        aria-pressed=${picked ? 'true' : 'false'}
        aria-label=${t('party.pick_label', { n: c.number })}
        title=${t(picked ? 'party.pick_remove' : crossed ? 'party.uncross' : 'party.pick_add', { n: c.number })}
        ...${actions.pickTap(c.id)}
      >
        ${c.number}<${InkCircle} /><${InkCross} />
      </button>
      <span class="who">
        <span class="name-line">
          ${
            tab
              ? html`<button
                  type="button"
                  class="cand-open"
                  aria-pressed=${selected ? 'true' : 'false'}
                  data-candidate=${c.id}
                  title=${titled(p.name)}
                  onClick=${toggle}
                >
                  ${p.logo ? html`<img class="party-logo" src=${p.logo} alt="" />` : null}
                  <span class="name">${p.short}</span>
                  <span class="sr-only">${p.short !== p.name ? ` (${p.name})` : ''}${state ? ` (${state})` : ''}</span>
                </button>`
              : html`<button
                  type="button"
                  class="cand-open"
                  aria-expanded=${open ? 'true' : 'false'}
                  aria-controls=${listId}
                  data-candidate=${c.id}
                  title=${titled(t(open ? 'party.hide_list' : 'party.show_list'))}
                  onClick=${toggle}
                >
                  ${p.logo ? html`<img class="party-logo" src=${p.logo} alt="" />` : null}
                  <span class="name">${p.name}</span>
                  ${state ? html`<span class="sr-only"> (${state})</span>` : null}
                </button>
                ${' '}${p.short !== p.name ? html`<span class="party" title=${t('party.short_title', { name: p.name })}>${p.short}</span>` : null}`
          }
          ${r?.won ? html`<${SeatsWon} result=${r} />` : null}
          ${noSeats ? html`<${NoSeats} why=${noSeats} />` : null}
          ${c.withdrawn || r?.withdrawn ? html`<${Withdrawn} />` : null}
          ${c.listResearch ? html`<${ListResearch} candidate=${c} />` : null}
        </span>
        ${r ? html`<${Votes} candidate=${c} />` : null}
        <span class="meta" title=${facts?.text}>
          ${t('party.size', { n: formatNumber(c.size) })}${coalition ? ` · ${t('party.coalition', { share: formatThreshold(c.threshold) })}` : null}
          ${
            facts?.picked
              ? html` · <span class=${facts.warning ? 'over' : null} title=${facts.warning}>
                  ${facts.warning ? html`<${WarningIcon} />` : null}${t('contest.picked', { n: formatNumber(facts.picked) })}
                </span>`
              : null
          }
        </span>
      </span>
      ${facts?.at ? html`<${WinnerMapButton} contest=${list} at=${facts.at} />` : null}
      ${r && r.share !== null ? html`<${MapButton} candidate=${c} label=${r.contestLabel} at=${r.at} />` : null}
    </div>
    ${
      open && !tab
        ? html`<${PartyList}
            id=${listId}
            party=${c}
            onCandidate=${onCandidate}
            filter=${filter}
            actions=${actions}
            place=${place}
            scope=${scope}
            onOverview=${onOverview}
          />`
        : null
    }
  `;
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
 * *place* ({obec, name, obvod, okrsok, zsk}: the obec or city district of
 * the ballots, named, its council obvod and okrsok where known and its
 * regional obvod): once counted, where it lies in units of the contest's
 * area with figures of their own (live.js `placeResults`), a choice of the
 * results' scope (`ScopeChoice`). The candidates' votes, the valid votes
 * and the 2026 turnout are then those of the finest unit not finer than
 * *level* (one of live.js SCOPES, one choice for all the ballots'
 * contests, changed by `onLevel(next, place, id)`, mapmode.js
 * `followLevel`), with an okrsok's 2022 turnout
 * where known. The buttons that put the results on the map carry that
 * unit's level (`levelAt`), whose unit the map is fitted to. A
 * party-list ballot's lists, with `onOverview(number)`, have a button
 * that opens the overview of the lists at theirs (`PartyList`). */
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
  onOverview,
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const live = useLive();
  const entry = live.of(contest.id);
  const { whole, units, unit, results } = scopedResults(contest, entry, place, level);
  const at = levelAt(unit, place);
  const candidates = withResults(contest, results, at);
  const shown = current && (candidates.find((c) => c.id === current.id) ?? current);
  const kept = useRef(new Set());
  for (const c of contest.candidates) if (actions.isPicked(c.id)) kept.current.add(c.id);
  const rest = candidates.filter((c) => c.id !== current?.id);
  const keptRest = rest.filter((c) => kept.current.has(c.id));
  const { kind } = parseContest(contest.id);
  // A referendum's answers and a party's list keep their order: yes before
  // no, the list as the party ranked it.
  const ranked = Boolean(results) && kind !== 'referendum' && !isList(contest.id);
  const { order, muted, unmuted } = byFilter(rest, filter, actions, ranked);
  let listed = keptRest;
  if (open) listed = pin ? [...keptRest, ...order.filter((c) => !kept.current.has(c.id))] : order;
  const opens = rest.length > 0;
  // Whether some candidates show while it is closed: then it opens to the others.
  const some = Boolean(current) || keptRest.length > 0;
  // Named as what its rows are: parties, a referendum's answers (never
  // circled, so never some shown while closed), else candidates.
  const noun = isParties(contest.id) ? 'parties' : kind === 'referendum' ? 'answers' : 'candidates';
  const tooltip = some
    ? t(`${open ? 'contest.hide_others' : 'contest.show_all'}${noun === 'parties' ? '_parties' : ''}`)
    : t(`contest.${open ? 'hide' : 'show'}_${noun}`);
  const picked = contest.candidates.filter((c) => actions.isPicked(c.id)).length;
  // A unit's own turnout then only, else the contest's, of its whole area:
  // from the candidates' data, or where they give none (a country-wide
  // contest) from the okrsok file of the place. An okrsok whose figures
  // then are not known says so beside 2026's.
  const name = (scope) => (scope === 'okrsok' ? null : scopeName(scope, place, contest.id));
  let past = null;
  if (unit) past = unit.past ? unitPast(unit.past, name(unit.scope)) : null;
  else if (contest.past) past = pastTurnout(contest);
  else {
    const then = placePast(contest.id, place);
    past = then && unitPast(then, name('all'));
  }
  const unknown = unit?.past && !unit.past.record ? ` ${pastTitle(PAST.unknown, unit.past.day)}` : '';
  const turnout =
    results?.eligible && results.voters !== null ? liveTurnout(results, unit && scopeName(unit.scope, place, contest.id)) : null;
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
  const note = open || some ? resultsNote(contest, whole) : null;
  const rows = [...(shown ? [shown] : []), ...listed];
  // A party-list ballot's parties' own threshold, beside which a
  // coalition's is named.
  const threshold = isParties(contest.id) ? contest.threshold : null;
  const row = (c, i) => {
    if (c.type === 'answer') return html`<li key=${c.id}><${AnswerRow} candidate=${c} /></li>`;
    if (c.type === 'party') {
      return html`<li key=${c.id}>
        <${PartyRow}
          candidate=${c}
          onCandidate=${onCandidate}
          actions=${actions}
          muted=${muted.get(c)}
          noSeats=${noSeatsReason(c, whole, threshold)}
          threshold=${threshold}
          filter=${filter}
          place=${place}
          scope=${unit?.scope ?? 'all'}
          onOverview=${onOverview}
        />
      </li>`;
    }
    const rank = places?.get(c.number);
    const seat = rank && {
      place: rank,
      seats: whole.seats,
      end: rank === whole.seats && i + 1 < rows.length && !places.has(rows[i + 1].number),
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
          results=${results}
          pending=${entry === NOT_COUNTED}
        />
        ${
          past || now
            ? html`<span class="contest-tools">
                ${winnerMap ? html`<${WinnerMapButton} contest=${contest} at=${at} />` : null}
                <${Turnout} contest=${contest} past=${past} live=${now} quorum=${kind === 'referendum' ? QUORUM : null} at=${at} />
              </span>`
            : null
        }
      </div>
      ${contest.question ? html`<${Question} id=${contest.id} text=${contest.question} />` : null}
      ${kind === 'referendum' ? html`<${Verdict} contest=${contest} results=${whole} />` : null}
      ${units.length ? html`<${ScopeChoice} units=${units} shown=${unit?.scope ?? 'all'} place=${place} id=${contest.id} onLevel=${onLevel} />` : null}
      ${open || !contest.candidates.length ? html`<${Holder} contest=${contest} />` : null}
      ${note ? html`<p class="results-note">${note}</p>` : null}
      ${
        contest.candidates.length
          ? html`<ol class="cands" id=${list}>
              ${rows.map(row)}
            </ol>`
          : html`<p class="muted">${t(isByElection && contest.uncontested ? 'contest.not_held' : 'contest.no_candidates')}</p>`
      }
      ${contest.uncontested ? html`<${Uncontested} why=${contest.uncontested} />` : null}
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

/* What says that a contest was called but held nowhere, no candidate
 * having registered (`contest.uncontested` {title, url}): one line, as
 * `Sources` has its documents, the title cut short, whole in its tooltip. */
function Uncontested({ why }) {
  return html`<p class="sources">
    ${t('contest.uncontested_source')}
    <a href=${why.url} title=${why.title} rel="noopener noreferrer" target="_blank">${why.title}</a>
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

/* The okrsky of obec *obec* (as data.js `ballots` gives it) that have
 * figures of their own but are not on the map (live.js `obecOkrsky`, of
 * the ballots' contests *ids*): all of an obec whose okrsky are not drawn,
 * one without an area (addressless) of an obec whose others are, and the
 * okrsky without territory (*special*, data/index.json `special`), never
 * drawn. An obec of one okrsok with territory is drawn as that okrsok, so
 * only its special ones are listed. Each a button that picks the okrsok, with
 * its council obvod where the obec has several (that whose council counted
 * it), as a click on the map picks a drawn one, and shows the ballots at
 * its level (`onUnit(place, level, contest)`, app.js `openUnit`, as the
 * candidate card's units: the map has no shape of it to show, so its
 * municipality is outlined); the one picked (*okrsok*) is pressed, and a
 * press goes back to the whole obec (`onPlace`). Nothing before the final
 * results, which alone have figures by okrsok, or while they load. */
function UnmappedOkrsky({ obec, ids, special, okrsok, onUnit, onPlace }) {
  useLive();
  const drawn = useDrawnOkrsky();
  const titleId = useOwnId('unmapped');
  const okrsky = obecOkrsky(ids, obec.code);
  if (!drawn || !okrsky) return null;
  const several = [...okrsky.keys()].filter((n) => !special?.[n]).length > 1;
  const unmapped = [...okrsky].filter(([n]) => special?.[n] || (several && !drawn.keys.has(`${obec.code}/${n}`)));
  if (!unmapped.length) return null;
  const obvodOf = (counted) =>
    obec.councils > 1
      ? (counted.map((id) => parseContest(id)).find((c) => c.kind === 'oz' && c.area === obec.code)?.sub ?? null)
      : null;
  return html`<div class="unmapped">
    <p class="unmapped-title" id=${titleId}><${LAYER_ICON.okrsky} />${t('okrsky.unmapped')}</p>
    <p class="unmapped-hint">${t('okrsky.unmapped_hint')}</p>
    <div class="unmapped-list" role="group" aria-labelledby=${titleId}>
      ${unmapped.map(([n, counted]) => {
        const s = special?.[n];
        const name = t('scope.okrsok', { n });
        const what = s
          ? t(s.kind === 'prison' ? 'okrsky.special_prison' : 'okrsky.special_covid', { n, facility: s.facility })
          : name;
        const picked = n === okrsok;
        return html`<button
          type="button"
          key=${n}
          aria-pressed=${picked ? 'true' : 'false'}
          aria-label=${what}
          title=${picked ? t('okrsky.unmapped_back', { name: obec.name }) : what}
          onClick=${() =>
            picked
              ? onPlace({ obec: obec.code })
              : onUnit({ obec: obec.code, obvod: obvodOf(counted), okrsok: n }, 'okrsok', counted[0])}
        >
          ${n}${s ? (s.kind === 'prison' ? html`<${PrisonIcon} />` : html`<${CovidIcon} />`) : null}
        </button>`;
      })}
    </div>
  </div>`;
}

/* The ballots of obec *code*; null for the country's ballots of a
 * country-wide election, before a place is chosen.
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
 * - onPlace(place, view): selects a place (as app.js `navigate`), from the
 *   list of where a by-election is held (`HeldPlaces`), or the whole obec
 *   again from an okrsok not on the map (`UnmappedOkrsky`).
 * - onUnit(place, level, contest): selects an okrsok not on the map and
 *   shows the ballots at its level (`UnmappedOkrsky`, app.js `openUnit`).
 * - onOverview(number): opens the overview of the election (overview.js),
 *   at party *number* where it is of parties' lists (0: the first), from
 *   each party's list (`PartyList`); overview {open, onToggle()}: the
 *   button before the contests, for the parties' lists or the questions of
 *   a referendum of several, a toggle as the map's ballot-box menu has it
 *   (controls.js `LayerMenus`), pressed while the overview shows.
 * The counted contests' results all show one scope (`Contest` *level*,
 * mapmode.js `useLevel`, kept from place to place): the whole contest, or
 * the place's kraj, okres, regional obvod, obec, council obvod or okrsok; the map
 * outlines that unit and fits the view to it as it is chosen, the results
 * on it, where they are a contest's, following it (mapmode.js
 * `followLevel`). */
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
  onPlace,
  onUnit,
  onOverview,
  overview = null,
}) {
  const { obvod = null, street = null, part = null } = scope;
  const [result, failed] = useLoaded(
    () => (code ? ballots(code, { obvod, street, part }) : countryBallots().then((list) => ({ obec: null, contests: list }))),
    [code, obvod, street, part],
  );
  const level = useLevel();
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
  const contestProps = { onCandidate, filter, actions, level, onLevel: followLevel, onOverview };
  // A referendum of one question has nothing to set side by side.
  const overviewButton =
    overview && (overviewKind === 'parties' || contests.length > 1)
      ? html`<button type="button" class="overview-open" aria-pressed=${overview.open ? 'true' : 'false'} onClick=${overview.onToggle}>
          <${ColumnsIcon} />${t(`overview.open.${overviewKind}`)}
        </button>`
      : null;
  if (!obec) {
    return html`
      <section class="ballots" aria-labelledby="km-place" ref=${section}>
        <header class="panel-head">
          <h2 id="km-place" tabindex="-1">${t('scope.country')}</h2>
          <p class="muted">${t('ballots.country')}</p>
        </header>
        <${FilterBar} filter=${filter} onFilter=${onFilter} actions=${actions} />
        ${overviewButton}
        ${contests.map((c) => html`<${BallotContest} key=${c.id} contest=${c} ...${contestProps} />`)}
      </section>
    `;
  }
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

  // Each a one-line summary and the whole note. Where the obvody are
  // another vote's standing in, without proof that they match, that matters
  // most, then where they are a guess, more than how the obvod was found; where
  // another election's rules stand in, that comes next, then documents
  // dated only approximately or filled in from a later source: every one
  // that applies is said, the first summarises.
  // Once the polls have closed the notes speak of the election as past.
  const past = Date.now() > polls[1];
  const n = obec.councils;
  const name = obec.name;
  const other = origin.reused?.slice(0, 4);
  const source = origin.adopted && standInSource(origin.adopted);
  const caveats = [
    source && [t('council.summary_adopted', { source }), t('council.adopted', { name, source })],
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
    // A country-wide election's okrsky are copied without a search for its
    // own documents (reuse.py), a municipal one's where none was found.
    origin.okrskyReused && [
      t('notice.summary_okrsky_reused', { other: okrskyFrom.slice(0, 4) }),
      t(isNational ? 'notice.okrsky_copied' : 'notice.okrsky_reused', { name, other: okrskyFrom.slice(0, 4) }),
    ],
    // An okrsok whose voters differ too much to share the borders is named.
    origin.okrskyAdopted && [
      t('notice.summary_okrsky_adopted', { source: standInSource(origin.okrskyAdopted) }),
      [
        t('notice.okrsky_adopted', { name, source: standInSource(origin.okrskyAdopted) }),
        ...(origin.okrskyOutliers ?? []).map(([n, voters, other]) =>
          t('notice.okrsky_outlier', {
            n,
            voters: formatNumber(voters),
            other: formatNumber(other),
            source: standInSource(origin.okrskyAdopted),
          }),
        ),
      ].join(' '),
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
  // The okrsky without territory (special.py: a COVID-19 one, a prison's):
  // the map draws none of them, so each is named, with what tells of it.
  const specialNotes = Object.entries(origin.special ?? {}).map(([n, s]) => {
    const vars = { n, name, voters: formatNumber(s.voters) };
    const text =
      s.kind === 'prison'
        ? t('notice.special_prison', { ...vars, facility: s.facility })
        : s.okresy.length > 1
          ? t('notice.special_covid_several', { ...vars, okresy: formatList(s.okresy) })
          : t('notice.special_covid', { ...vars, okres: s.okresy[0] });
    return html`
      <${Notice} key=${`special-${n}`} summary=${t('notice.summary_special', { n })}>${text}<//>
      <p key=${`special-source-${n}`} class="sources">
        ${t('notice.special_source')}
        <a href=${s.url} title=${s.title} rel="noopener noreferrer" target="_blank">${s.title}</a>
      </p>
    `;
  });
  const unmapped = html`<${UnmappedOkrsky}
    obec=${obec}
    ids=${contests.map((c) => c.id)}
    special=${origin.special}
    okrsok=${okrsok}
    onUnit=${onUnit}
    onPlace=${onPlace}
  />`;
  const place = {
    obec: obec.code,
    name: obec.name,
    obvod: placeObvod,
    okrsok: placeOkrsok,
    okresName: obec.okresName,
    krajName: obec.krajName,
    zsk: obec.zsk,
  };

  // The sources of a council's obvody follow the last of its contests.
  const withSources = (list, c, i) => {
    const last = i + 1 === list.length || officeOf(list[i + 1].id) !== officeOf(c.id);
    return html`
      <${BallotContest}
        key=${c.id}
        contest=${c}
        listed=${c.council === 'pending' || c.council === 'choose'}
        place=${place}
        ...${contestProps}
      />
      ${c.sources.length && last ? html`<${Sources} sources=${c.sources} />` : null}
    `;
  };

  const head = html`
    <header class="panel-head">
      <h2 id="km-place" tabindex="-1">${label ?? obec.name}</h2>
      <p class="muted">${where.join(' · ')}</p>
    </header>
    <${FilterBar} filter=${filter} onFilter=${onFilter} actions=${actions} />
  `;
  // A country-wide election's ballots are everyone's: the place scopes
  // their results.
  if (isNational) {
    return html`
      <section class="ballots" aria-labelledby="km-place" ref=${section}>
        ${head}
        <p class="panel-body intro">${t('ballots.intro_country')}</p>
        ${placeNotes.map(([summary, text]) => html`<${Notice} summary=${summary}>${text}<//>`)}
        ${specialNotes}
        ${unmapped}
        ${overviewButton}
        ${contests.map((c) => html`<${BallotContest} key=${c.id} contest=${c} place=${place} ...${contestProps} />`)}
      </section>
    `;
  }
  // A by-election elects in some places only: elsewhere, where it does.
  if (isByElection && !contests.length) {
    return html`
      <section class="ballots" aria-labelledby="km-place" ref=${section}>
        ${head}
        <${Notice}>${t('byelection.nothing', { name: obec.name })}<//>
        <${HeldPlaces} onPlace=${onPlace} />
      </section>
    `;
  }
  // A group with no contest is a half of the elections not voted on here:
  // of a by-election, one not held in this place; of an election of one
  // half (kinds.js `holds`), the other, held on a day of its own. Neither
  // is headed, nor is a council said to be missing where none was elected.
  const titled = (title, list, children) => (list.length ? html`<h3 class="group">${title}</h3>${children}` : null);
  return html`
    <section class="ballots" aria-labelledby="km-place" ref=${section}>
      ${head}
      ${previous ? null : html`<p class="panel-body intro">${t('ballots.no_incumbents')}</p>`}
      <p class="panel-body intro">${t('ballots.intro')}</p>
      ${placeNotes.map(([summary, text]) => html`<${Notice} summary=${summary}>${text}<//>`)}
      ${specialNotes}
      ${unmapped}
      ${titled(
        t('ballots.municipal'),
        municipal,
        html`
          ${municipal.map(
            (c, i) => html`
              ${i === firstCouncil ? councilNote : null}
              ${withSources(municipal, c, i)}
            `,
          )}
          ${council === 'none' && !isByElection ? html`<${Notice}>${t('council.none')}<//>` : null}
        `,
      )}
      ${titled(
        t('ballots.regional'),
        regional,
        regional.map((c, i) => withSources(regional, c, i)),
      )}
    </section>
  `;
}

/* Where a by-election is held (data.js `heldPlaces`), as the pane lists
 * it with no place chosen, and on a place where nothing is elected: each
 * municipality a button that selects it (`onPlace`), with what it elects;
 * a kraj's contests concern every municipality in it, so it is named
 * with them only. *heading*: the list's own, as the pane's title. */
export function HeldPlaces({ onPlace, heading = false }) {
  const [places, failed] = useLoaded(heldPlaces, []);
  if (failed) return html`<p class="panel-body error">${t('error.load')}</p>`;
  if (!places) return html`<p class="panel-body muted loading">${t('panel.loading')}</p>`;
  const list = html`<ul class="held">
    ${places.map((p) => {
      const what = p.contests.join(', ');
      if (p.kraj) {
        return html`<li key=${p.code} class="held-kraj">
          <span class="held-name">${p.name}</span>
          <span class="held-contests">${what}</span>
          <span class="held-where">${t('byelection.kraj_note')}</span>
        </li>`;
      }
      return html`<li key=${p.code}>
        <button type="button" class="held-place" onClick=${() => onPlace({ obec: p.code }, 'obec')}>
          <span class="held-name">${p.name}</span>
          <span class="held-contests">${what}</span>
          <span class="held-where">${p.detail}</span>
        </button>
      </li>`;
    })}
  </ul>`;
  if (!heading) return html`<h3 class="group">${t('byelection.where')}</h3>${list}`;
  return html`<section class="ballots" aria-labelledby="km-place">
    <header class="panel-head">
      <h2 id="km-place" tabindex="-1">${t('byelection.title')}</h2>
      <p class="muted">${t('byelection.count', { n: formatNumber(places.length) })}</p>
    </header>
    <p class="panel-body intro">${t('byelection.intro')}</p>
    ${list}
  </section>`;
}
