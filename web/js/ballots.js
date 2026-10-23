/* The ballots of one place: every contest a voter there votes in, each with
 * its candidates in ballot order. Which contests apply is decided in
 * data.js `ballots`. */

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { ballots, displayName, inOffice, officeOf, useLoaded } from './data.js';
import { formatDate, formatList, formatNumber, formatPercent, researchCategories, t } from './i18n.js';
import {
  ChairIcon,
  CloseIcon,
  EyeIcon,
  EyeOffIcon,
  FilterOffIcon,
  InkCircle,
  MapPinIcon,
  SearchIcon,
  WarningIcon,
} from './icons.js';
import { Notice } from './pane.js';
import { togglePick } from './picks.js';

/* The candidate filter (app.js keeps it across places, and in the URL:
 * filterParams): `parties` chosen ({short, name, logo}, INDEPENDENT among
 * them) and whether their candidates are the only ones shown or hidden
 * (`partyMode` 'only' or 'hide'); `marks`, mark name (MARKS) → its mode
 * likewise, for each mark added. Muted candidates stay on the list, faded
 * and after the others. */
export const NO_FILTER = { parties: [], partyMode: 'only', marks: {} };

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
 * whom it covers: research found controversies; research done (whatever
 * it found); holds the office the contest elects (the chair). */
const MARKS = [
  ['affairs', (c) => Boolean(c.research?.affairs), WarningIcon],
  ['researched', (c) => Boolean(c.research), SearchIcon],
  ['office', inOffice, ChairIcon],
];

const mutedBy = (mode, member) => (mode === 'hide' && member) || (mode === 'only' && !member);

/* Whether *filter* mutes candidate *c*: any group of it that does. */
function isMuted(c, filter) {
  const party = filter.parties.some((f) => standsFor(c, f.name));
  return Boolean(
    (filter.parties.length && mutedBy(filter.partyMode, party)) ||
      MARKS.some(([name, covers]) => name in filter.marks && mutedBy(filter.marks[name], covers(c))),
  );
}

/* The filter in the URL hash (app.js), as [key, value] pairs, none for a
 * group not used: `fp` the parties by their short forms (unique, see
 * config.py `load_parties`), "-" the independents, after a "!" when they
 * are hidden rather than the only ones shown; `fm` the marks added, each
 * after a "!" when hidden. */
export function filterParams(filter) {
  const params = [];
  const hide = (mode) => (mode === 'hide' ? '!' : '');
  if (filter.parties.length) {
    const shorts = filter.parties.map((p) => (p.name ? p.short : '-'));
    params.push(['fp', hide(filter.partyMode) + shorts.join(',')]);
  }
  const marks = MARKS.filter(([name]) => name in filter.marks).map(([name]) => hide(filter.marks[name]) + name);
  if (marks.length) params.push(['fm', marks.join(',')]);
  return params;
}

/* The filter that hash values *fp* and *fm* (filterParams) name, the
 * parties looked up by short form in data/index.json's *parties*; what is
 * not known there is left out (a party gone since the link was made). */
export function parseFilter(fp, fm, parties) {
  const known = new Map(Object.values(parties).map(([short, name, logo = null]) => [short, { short, name, logo }]));
  const named = (fp ?? '').replace(/^!/, '').split(',');
  const chosen = new Map();
  for (const short of named) {
    const p = short === '-' ? INDEPENDENT : known.get(short);
    if (p) chosen.set(p.name, p);
  }
  const marks = {};
  for (const token of (fm ?? '').split(',')) {
    const name = token.replace(/^!/, '');
    if (MARKS.some(([mark]) => mark === name)) marks[name] = token.startsWith('!') ? 'hide' : 'only';
  }
  const partyMode = chosen.size && fp.startsWith('!') ? 'hide' : 'only';
  return { parties: [...chosen.values()], partyMode, marks };
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
 * party's candidates, pressing it adds the party to the filter or, if
 * there already, removes it. */
function Parties({ candidate: c, actions }) {
  return (c.parties.length ? c.parties : [INDEPENDENT]).map((p) => {
    const name = partyName(p);
    const cls = p === INDEPENDENT ? 'party independent' : 'party';
    if (!actions) {
      return p.logo
        ? html`<img class="party-logo" src=${p.logo} alt=${name} title=${name} />`
        : html`<span class=${cls} title=${name} aria-label=${name}>${partyShort(p)}</span>`;
    }
    const on = actions.hasParty(p.name);
    const label = t(on ? 'filter.party_drop' : 'filter.party_add', { name });
    return html`<button
      type="button"
      class=${on ? 'party-button active' : 'party-button'}
      title=${label}
      aria-label=${label}
      ...${actions.hoverProps(p.name)}
      onClick=${() => actions.onParty(p)}
    >
      ${p.logo ? html`<img class="party-logo" src=${p.logo} alt="" />` : html`<span class=${cls}>${partyShort(p)}</span>`}
    </button>`;
  });
}

/* A mark after the parties, explained by *label* in its tooltip (and for
 * screen readers). With *actions* (the ballots), a button that adds the
 * mark *name* (MARKS) to the filter or, if there already, removes it. */
function Mark({ name, cls, label, actions, children }) {
  if (!actions) return html`<span class=${cls} role="img" title=${label} aria-label=${label}>${children}</span>`;
  const on = actions.hasMark(name);
  const full = `${label} ${t(on ? 'filter.drop' : 'filter.add', { name: t(`filter.${name}`) })}`;
  return html`<button
    type="button"
    class=${on ? `${cls} active` : cls}
    title=${full}
    aria-label=${full}
    onClick=${() => actions.onMark(name)}
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

/* Research found controversies about the candidate: a red warning sign
 * with their number, first of the marks, so that it is not passed over
 * among the findings. */
function Controversies({ candidate: c, actions }) {
  const r = c.research;
  const n = formatNumber(r.affairs);
  const label = t('research.affairs_badge', { scope: researchScope(r), date: formatDate(r.date), n });
  return html`<${Mark} name="affairs" cls="affairs" label=${label} actions=${actions}><${WarningIcon} />${n}<//>`;
}

/* One candidacy: its ballot number is a button that circles it (or takes
 * the circle off), as a voter circles the numbers of their candidates on
 * the ballot; its name is the button that opens the card (a click
 * elsewhere on the row does too), then who nominated it, then apart from
 * those its marks: what is known about the candidate. Party tags and marks
 * are buttons of their own. *actions*: {onParty(party), onMark(name),
 * hasParty(name), hasMark(name), hoverProps(name), isPicked(id),
 * onPick(id)}, see Parties, Mark and useRowActions. *muted*: the filter
 * fades the row. A row of the party pointed at is highlighted by Ballots. */
export function CandidateRow({ candidate, onCandidate, current = false, actions, muted = false }) {
  const c = candidate;
  const flagged = Boolean(c.research?.affairs);
  const picked = actions.isPicked(c.id);
  const metaId = useOwnId('km-meta');
  const classes = ['cand', current && 'current', flagged && 'flagged', muted && 'dimmed'];
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
        title=${t(picked ? 'pick.remove' : 'pick.add', { n: c.number })}
        onClick=${() => actions.onPick(c.id)}
      >
        ${c.number}<${InkCircle} />
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
            ${muted ? html`<span class="sr-only"> (${t('filter.muted')})</span>` : null}
          </button>
          ${' '}<${Parties} candidate=${c} actions=${actions} />
          <span class="marks">
            ${flagged ? html`<${Controversies} candidate=${c} actions=${actions} />` : null}
            ${inOffice(c) ? html`<${InOffice} candidate=${c} actions=${actions} />` : null}
            <${Researched} candidate=${c} actions=${actions} />
          </span>
        </span>
        <span class="meta" id=${metaId}>${t('candidate.age', { n: c.age })} · <${Occupation} candidate=${c} /></span>
      </span>
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
 * president; a council's seats where known, else the 2022 number, labelled
 * so) and how many stand, with how many of them the filter leaves shown
 * (*unmuted*) where it mutes some; and how many of them the visitor has
 * circled (*picked*), if any. More circled than are elected, both numbers
 * are highlighted with a warning: on the ballot itself that would make it
 * invalid. Circling more is still allowed: the visitor may circle whom
 * they like best, to choose among them later. */
function ContestHead({ contest, unmuted, picked }) {
  const n = contest.candidates.length;
  const kind = contestKind(contest.id);
  const single = kind.startsWith('starosta') || kind === 'predseda';
  const elected = single
    ? t('contest.single')
    : contest.seats
      ? t('contest.seats', { n: formatNumber(contest.seats) })
      : contest.seats2022
        ? t('contest.seats_2022', { n: formatNumber(contest.seats2022) })
        : null;
  const candidates =
    unmuted < n
      ? t('contest.candidates_filtered', { shown: formatNumber(unmuted), n: formatNumber(n) })
      : t('contest.candidates', { n: formatNumber(n) });
  const limit = single ? 1 : (contest.seats ?? contest.seats2022);
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
  `;
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

/* *candidates* in list order: those the *filter* leaves shown, then those it
 * mutes, each group in ballot order; and which are muted. The circled ones
 * (*actions* `isPicked`) never are. */
function byFilter(candidates, filter, actions) {
  const muted = new Map(candidates.map((c) => [c, !actions.isPicked(c.id) && isMuted(c, filter)]));
  const order = [...candidates.filter((c) => !muted.get(c)), ...candidates.filter((c) => muted.get(c))];
  return { order, muted, unmuted: order.length - [...muted.values()].filter(Boolean).length };
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
 * pin at the header's end that shows it there. */
export function Contest({ contest, current = null, pin = false, initiallyOpen = false, onOpen, onCandidate, filter, actions, map }) {
  const [open, setOpen] = useState(initiallyOpen);
  const kept = useRef(new Set());
  for (const c of contest.candidates) if (actions.isPicked(c.id)) kept.current.add(c.id);
  const rest = contest.candidates.filter((c) => c !== current);
  const keptRest = rest.filter((c) => kept.current.has(c.id));
  const { order, muted, unmuted } = byFilter(rest, filter, actions);
  let listed = keptRest;
  if (open) listed = pin ? [...keptRest, ...order.filter((c) => !kept.current.has(c.id))] : order;
  const opens = rest.length > 0;
  // Whether some candidates show while it is closed: then it opens to the others.
  const some = Boolean(current) || keptRest.length > 0;
  const tooltip = some
    ? t(open ? 'contest.hide_others' : 'contest.show_all')
    : t(open ? 'contest.hide_candidates' : 'contest.show_candidates');
  const picked = contest.candidates.filter((c) => actions.isPicked(c.id)).length;
  const head = html`<span class="contest-text">
    <${ContestHead} contest=${contest} unmuted=${unmuted + (current ? 1 : 0)} picked=${picked} />
  </span>`;
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
        ${
          map
            ? html`<button type="button" class="contest-map" title=${map.label} aria-label=${map.label} onClick=${map.onClick}>
                <${MapPinIcon} />
              </button>`
            : null
        }
      </div>
      ${open || !contest.candidates.length ? html`<${Holder} contest=${contest} />` : null}
      ${
        contest.candidates.length
          ? html`<ol class="cands" id=${list}>
              ${current ? row(current, { current: true }) : null}
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

/* The handlers that the buttons on candidate rows use (*actions* of
 * CandidateRow), for the rows inside *section* (a ref) of *candidates*
 * (id → candidate): the filter's (*filter*, `onFilter(next)`) and the
 * circles' (*picks*, `onPicks(next)`, picks.js). The party pointed at or
 * focused has its candidates highlighted by a class on their rows, not by
 * rendering them again, which with a few hundred candidates takes tens of
 * milliseconds, while a pointer on its way across the pane (dragging the
 * map, say) passes many party tags. */
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
  const picked = new Set(picks);
  return {
    hoverProps: (name) => ({ onMouseEnter: point(name), onMouseLeave: point(null), onFocus: point(name), onBlur: point(null) }),
    hasParty: (name) => filter.parties.some((f) => f.name === name),
    hasMark: (name) => name in filter.marks,
    onParty: (p) => {
      const rest = filter.parties.filter((f) => f.name !== p.name);
      if (rest.length === filter.parties.length) onFilter({ ...filter, parties: [...rest, p] });
      // The last party gone, the next one chosen starts as Only these.
      else onFilter({ ...filter, parties: rest, partyMode: rest.length ? filter.partyMode : 'only' });
    },
    onMark: (name) => {
      const { [name]: _, ...rest } = filter.marks;
      onFilter({ ...filter, marks: name in filter.marks ? rest : { ...rest, [name]: 'only' } });
    },
    isPicked: (id) => picked.has(id),
    onPick: (id) => onPicks(togglePick(picks, id)),
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
 * (the parties chosen, each mark added) its mode and its chips, a party's
 * highlighting its candidates like a party in the list, each removable
 * (*actions* as for CandidateRow); and a button that clears them all.
 * Stuck to the top while the lists scroll, it is ruled off from the pane's
 * close button beside it, which must not pass for the clear button. */
export function FilterBar({ filter, onFilter, actions }) {
  const { parties, marks } = filter;
  const added = MARKS.filter(([name]) => name in marks);
  const shown = parties.length > 0 || added.length > 0;
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
  return html`
    <div ref=${bar} class=${stuck ? 'filter-bar stuck' : 'filter-bar'} role="group" aria-label=${t('filter.label')}>
      ${
        parties.length
          ? group(
              'parties',
              t('filter.parties'),
              filter.partyMode,
              (partyMode) => onFilter({ ...filter, partyMode }),
              parties.map((p) => {
                const name = partyName(p);
                return html`<li key=${p.name} class="chip" title=${name} ...${actions.hoverProps(p.name)}>
                  ${p.logo ? html`<img class="party-logo" src=${p.logo} alt="" />` : null}
                  <span>${partyShort(p)}</span>
                  ${remove(name, () => actions.onParty(p))}
                </li>`;
              }),
            )
          : null
      }
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
            ${remove(label, () => actions.onMark(name))}
          </li>`,
        );
      })}
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
 * `onPicks(next)` the circled candidates (picks.js). */
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
}) {
  const { obvod = null, street = null, part = null } = scope;
  const [result, failed] = useLoaded(
    () => ballots(code, { obvod, street, part }),
    [code, obvod, street, part],
  );
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
  const withSources = (list, c, i) => html`
    <${BallotContest}
      key=${c.id}
      contest=${c}
      listed=${c.council === 'pending' || c.council === 'choose'}
      onCandidate=${onCandidate}
      filter=${filter}
      actions=${actions}
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
