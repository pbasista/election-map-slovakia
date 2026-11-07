/* The 2026 results on the map, in one of three modes: a candidate's share
 * of the votes across the areas of their contest, who got the most votes
 * where in a contest, or a turnout (of the municipal or the regional
 * elections across the country, or of one contest). A candidate is a
 * person, a party (of a party-list election) or an answer (of a
 * referendum); a person on a party's list has their preference votes'
 * share of the party's votes. The map colours the
 * land in STEPS intensities of a colour (draw.js `setResults`) on a scale
 * fitted to the values shown, or for a winner map in a colour per leading
 * candidate (a tie for the lead in stripes of the leaders' colours). A
 * legend with the scale or the candidates floats on the map, with a button
 * that folds it into a pill and one that takes the results off the map.
 * Without a mode, a by-election's map shows where something is
 * elected (`HELD`), with a legend of its own.
 *
 * The mode is one for the page, chosen in a candidate's row
 * (`MapButton`), a contest's header (`TurnoutMapButton`,
 * `WinnerMapButton`), the candidate card or the boundaries menu
 * (controls.js), so it lives here rather than being passed down through
 * the panes. The values come from the live results (live.js) and follow
 * them:
 * - a contest: its `areas` (an obec or city district each, or on election
 *   night a regional obvod `obvod:<n>` of the kraj), else its own figures
 *   over its own area (a mayor's obec, a council's obec or council obvod,
 *   a regional obvod, a kraj's obvody);
 * - the municipal turnout: the mayoral (else council) contests of every
 *   municipality and city district, as the results' `turnout` has them;
 * - Bratislava's and Košice's own elections: likewise from theirs;
 * - the regional turnout: each kraj's presidential contest;
 * - a country-wide election's turnout: one of its contests' (the menu's
 *   `turnoutChoices`).
 * Every figure of a unit made of finer ones is the results' own, summed by
 * `ems results` (docs/results.md), never here.
 *
 * The units follow the zoom, as the boundary overlays do (draw.js
 * `OVERLAYS`), each as fine as its figures go:
 * - below the obce's zoom, the coarsest units the results give: the
 *   regional obvody (a regional president's and a city contest's `units`,
 *   a regional council obvod's own figures, the turnouts' `turnout`), or
 *   the okresy where there are none (a country-wide contest's `units`, a
 *   municipal election alone or a by-election); none of a contest of one
 *   obec, which would colour a whole unit;
 * - from there, every obec by its own figure;
 * - from the council overlay's zoom, the council obvody of the obce split
 *   into several (a council's own figure, any other contest's okrsky
 *   summed, the okrsok files' `units`);
 * - from the okrsky overlay's zoom, every okrsok drawn (geo/index.json
 *   `okrsky.drawn`) with figures of its own in the final results (live.js
 *   `okrsky`).
 * An obec without finer figures keeps its own at every zoom. One scale
 * spans the units of every level, so that a colour means the same at each
 * zoom. Pointing at the map (on a touch screen, tapping it) names the unit
 * there with its figures, and an okrsok or an obec with those of the
 * election before as live.js `pastOf` finds them (the turnout, and the
 * candidate's or the leader's votes), labelled with how they were found
 * (live.js `pastLabel`).
 *
 * The level the ballots show the results at (`level`, one of live.js
 * SCOPES, ballots.js `ScopeChoice`) is the map's too, with a mode or
 * without: the map outlines that unit of the selected place (its kraj,
 * okres, regional obvod, obec, council obvod or okrsok; nothing for the
 * whole contest)
 * and veils the rest (draw.js `setLevel`), and each choice of a level
 * fits the view to the unit, or to the whole contest's area
 * (`followLevel`, `MapResults`). A contest's mode keeps the level its
 * contest shows there, which its link names.
 *
 * A candidate who stood for the same office then has a second map: their
 * share at the election before on the 2026 units (`gatherPrevious`), an
 * okrsok estimated from addresses hatched and one of okrsky changed beyond
 * matching grey (`PREVIOUS_PALETTE`), chosen by year in the legend
 * (`YearChoice`). */

import { html, render, useEffect, useLayoutEffect, useMemo, useRef, useState } from '../vendor/preact-htm.module.js';
import {
  candidateName,
  contestArea,
  contestLabel,
  contests,
  dataIndex,
  electsAnywhere,
  getJSON,
  hasCouncilObvody,
  heldObce,
  useLoaded,
} from './data.js';
import {
  election,
  formatDate,
  formatList,
  formatNumber,
  formatPercent,
  standInSource,
  t,
} from './i18n.js';
import { ArrowIcon, CloseIcon, ExpandIcon, MapResultsIcon, TurnoutIcon } from './icons.js';
import {
  areaName,
  contestOf,
  isByElection,
  isCity,
  isCountry,
  isList,
  isMunicipal,
  isNational,
  isParties,
  isSingle,
  parseContest,
} from './kinds.js';
import {
  NOT_COUNTED,
  okrskyLoading,
  PAST,
  pastLabel,
  pastOf,
  pastTitle,
  placeResults,
  SCOPES,
  unitWithin,
  useLive,
} from './live.js';

/* The intensities of the colour: app.css `--map-result-<n>` for a
 * candidate's votes, a turnout's tone mixed into the land (draw.js
 * `TONE_STEPS`, app.css `.map-legend.toned`). */
export const STEPS = 6;
/* The colours of a winner map, app.css `--map-series-<n>`: one for each of
 * the candidates with the most votes overall, the rest share
 * `--map-series-other`. */
export const SERIES = 8;
const PALETTE = [...Array.from({ length: SERIES }, (_, i) => `series-${i + 1}`), 'series-other'];
/* The colours of a candidate's map of the election before: the steps of
 * the votes; the same steps hatched with the land (draw.js `stepFill`
 * stripes) for an okrsok whose figures are estimated from addresses
 * (`PAST.approximate`); app.css `--map-past-unknown`, a grey, for one
 * whose figures are not known (`PAST.unknown`). */
const PREVIOUS_PALETTE = [
  ...Array.from({ length: STEPS }, (_, i) => `result-${i + 1}`),
  ...Array.from({ length: STEPS }, (_, i) => [`result-${i + 1}`, 'land']),
  'past-unknown',
];
const UNKNOWN_STEP = 2 * STEPS;
// Values beyond these quantiles (where there are enough to tell) take the
// end steps, so that a hamlet of a dozen voters does not stretch the scale.
const TRIM = 0.05;
const TRIM_FROM = 20;

/* What the map shows, one of:
 * - null;
 * - {kind: 'candidate', id, contest, number, name, surname, label, of,
 *   previous}: a candidacy, its contest's id and label, `surname` the
 *   short name a person, party or answer goes by, `of` the key of what
 *   the share is of (`shareOf`), `previous` for their votes at the
 *   election before rather than 2026's;
 * - {kind: 'winner', contest, label, names, of}: who got the most votes
 *   where, `names` number → [name, short name], `of` the key of what
 *   leads (`leaderOf`: in a council its top candidate, not all it
 *   elects);
 * - {kind: 'turnout', election: 'municipal' | 'city' | 'regional'}, 'city'
 *   for Bratislava's and Košice's own elections;
 * - {kind: 'turnout', contest, label}: one contest's (TurnoutMapButton, a
 *   country-wide election's turnout menu).
 * A contest's mode has `level` too, one of live.js SCOPES: the level the
 * ballots showed the contest's results at where it was made ('all' from
 * the candidate card and the menus), which its link names; and `place`,
 * the place of those ballots ({obec, obvod, okrsok}), whose unit at the
 * level the view is fitted to when the mode is made (`fitting`), null
 * where the mode was made elsewhere or came by a link. One from a link
 * has `keepView` too (`parseMode`). */
let mode = null;
const listeners = new Set();

/* The level the ballots show the results at, one of live.js SCOPES: one
 * choice for all their contests (ballots.js `ScopeChoice`), kept from
 * place to place as one looks through the okrsky of a town, say. The map
 * outlines its unit of the selected place (map.js `setLevel`). */
let chosenLevel = 'all';
const levelListeners = new Set();

/* The view the map is to fit to (`MapResults`), a new object for each
 * time it is to: {level, place, contest}, the unit at *level* (one of
 * live.js SCOPES) of *place* ({obec, obvod, okrsok}), or at 'all' (or
 * without a place) the whole area of *contest*; null for none yet. Asked
 * for by a level chosen (`followLevel`) and by a contest's mode made, at
 * a level other than the one shown before or of another contest (from
 * none, an election's turnout or another contest's mode): switching
 * between the modes of a contest at its level keeps the view the visitor
 * has zoomed to, as does a mode from a link that names its view. */
let fitting = null;

/* Renders a component again whenever a listener of *set* is called. It
 * listens from a layout effect, run as the render is committed: an effect
 * runs only after the next paint, and a change in between (a linked mode
 * set once the data index arrives, app.js) would leave the component
 * showing the old one (as `useLive`, live.js). */
function useListener(set) {
  const [, setTick] = useState(0);
  useLayoutEffect(() => {
    const listener = () => setTick((n) => n + 1);
    set.add(listener);
    return () => set.delete(listener);
  }, []);
}

/* Shows *next* (a mode, or null) on the map, fitted to as `fitting` has
 * it. A mode from a link (`parseMode`) brings its level to the ballots. */
export function setMapMode(next) {
  const made = Boolean(next?.contest) && !next.keepView && (next.contest !== mode?.contest || next.level !== mode?.level);
  if (made) fitting = { level: next.level, place: next.place, contest: next.contest };
  if (next && next.keepView !== undefined) chooseLevel(next.level);
  mode = next;
  for (const listener of listeners) listener();
}

/* The mode, for a component: renders it again when it changes. */
export function useMapMode() {
  useListener(listeners);
  return mode;
}

// Makes *level* the ballots' (`chosenLevel`).
function chooseLevel(level) {
  chosenLevel = level;
  for (const listener of levelListeners) listener();
}

/* The level the ballots show the results at (`chosenLevel`), for a
 * component: renders it again when it changes. */
export function useLevel() {
  useListener(levelListeners);
  return chosenLevel;
}

/* A button that shows mode *next* on the map, or takes it off while it is
 * shown (*on*). */
function ToggleButton({ cls, next, on, label, style, children }) {
  return html`<button
    type="button"
    class=${cls}
    style=${style}
    aria-pressed=${on ? 'true' : 'false'}
    title=${label}
    aria-label=${label}
    onClick=${() => setMapMode(on ? null : next)}
  >
    ${children}
  </button>`;
}

// A candidate's name in full (a party's whole name) and short (a person's
// surname, a party's abbreviation, an answer).
const fullName = (c) => (c.type === 'party' ? c.party.name : candidateName(c));
const shortName = (c) => c.surname ?? candidateName(c);

/* The key of what the shares of contest *id*'s candidates are of: the
 * valid votes; for a council, the voters with a valid ballot, each of
 * whom could vote for several; for a party's list, the party's votes,
 * of which a person's preference votes are a share. */
function shareOf(id) {
  if (isList(id)) return 'mapmode.share_party';
  return isSingle(id) ? 'mapmode.share_valid' : 'mapmode.share_voters';
}

/* The key of what leads where in contest *id*: a candidate, a council's
 * top candidate (not all it elects), a party, an answer, a list's person
 * by preference votes. */
function leaderOf(id) {
  if (isList(id)) return 'mapmode.winner_of_list';
  if (isParties(id)) return 'mapmode.winner_of_party';
  if (parseContest(id).kind === 'referendum') return 'mapmode.winner_of_answer';
  return isSingle(id) ? 'mapmode.winner_of' : 'mapmode.winner_of_council';
}

// Place *p* of the ballots (as ballots.js `Contest` takes it) as a mode
// carries it, {obec, obvod, okrsok}; null for none.
const placeOf = (p) => (p ? { obec: p.obec, obvod: p.obvod ?? null, okrsok: p.okrsok ?? null } : null);

/* The level of a mode made on the ballots, as the mode carries it (see
 * `mode`): *at* {level, place}, the level the contest's results show at
 * there (one of live.js SCOPES) and the place they are of (as ballots.js
 * `Contest` takes it); the whole contest without. */
const levelled = (at) => ({ level: at?.level ?? 'all', place: placeOf(at?.place) });

/* The modes of a contest's results (see `mode`): candidate *c*'s votes,
 * *label* naming the contest; who got the most votes where; its turnout;
 * each at level *at* (`levelled`). */
const candidateMode = (c, label, at = null) => ({
  kind: 'candidate',
  id: c.id,
  contest: c.contest,
  number: c.number,
  name: fullName(c),
  surname: shortName(c),
  label,
  of: shareOf(c.contest),
  ...levelled(at),
});

const winnerMode = (contest, at = null) => ({
  kind: 'winner',
  contest: contest.id,
  label: contest.label,
  names: Object.fromEntries(contest.candidates.map((c) => [c.number, [fullName(c), shortName(c)]])),
  of: leaderOf(contest.id),
  ...levelled(at),
});

const turnoutMode = (contest, label = contest.label, at = null) => ({
  kind: 'turnout',
  contest: contest.id,
  label,
  ...levelled(at),
});

/* Moves the map with the ballots as their level changes to *level* (one
 * of live.js SCOPES) for *place* (as ballots.js `Contest` takes it), by a
 * press in the choice of contest *id* (ballots.js `ScopeChoice`) or a
 * unit opened from the candidate card (app.js): the level is chosen
 * (`chosenLevel`) and, once its units are known (`followKnown`), the
 * contest's mode shown, if any,
 * moves to the level its contest shows there, the finest of its units
 * not finer than the choice (live.js `placeResults`, `unitWithin`, as the
 * ballots pick it), else the whole, a link's view no longer kept; and the
 * view is fitted to what the press chose: contest *id*'s unit at the level
 * as its ballot shows it, or its whole area (`fitting`). Not the mode's
 * contest's: on the ballots of a town the mayor's map may be shown while
 * the governor's "whole contest" is pressed, which is the kraj. */
export function followLevel(level, place, id) {
  chooseLevel(level);
  following = { level, place, id };
  followKnown();
}

/* A level followed (`followLevel`) whose units are not known yet: {level,
 * place, id}; null for none. */
let following = null;

/* Follows `following` once the units of its contest and the mode's at its
 * place are known: a country-wide contest's okrsok is in its kraj's okrsok
 * file, which an okrsok opened from the candidate card (app.js) may not
 * have loaded yet (live.js `okrskyLoading`, which loads it). `MapResults`
 * asks again as the results load. */
function followKnown() {
  if (!following) return;
  const { level, place, id } = following;
  if (place && [id, mode?.contest].some((c) => c && okrskyLoading(c, place.obec))) return;
  following = null;
  const within = (contest) => (place ? unitWithin(placeResults(contest, place), level) : null);
  if (mode?.contest) {
    const { keepView, ...m } = mode;
    mode = { ...m, level: within(mode.contest)?.scope ?? 'all', place: placeOf(place) };
  }
  fitting = { level: within(id)?.scope ?? 'all', place: placeOf(place), contest: id };
  for (const listener of listeners) listener();
}

const ELECTIONS = ['municipal', 'city', 'regional'];

/* Whether something of turnout *election* (one of ELECTIONS) is held in
 * area *code* of a by-election, whose contests there are *ids*
 * (data/index.json `held`): a municipality's or city district's own, one
 * of Bratislava's and Košice's, a kraj's president. The regional turnout
 * is the presidents' (`gatherRegional`). */
function heldFor(election, code, ids, index) {
  if (election === 'municipal') return Boolean(index.obce[code]);
  if (election === 'city') return isCity(code);
  return ids.some((id) => parseContest(id).kind === 'predseda');
}

/* The turnouts the map's menu offers (controls.js): [{mode, label}]. Of
 * the regular elections the municipal, the two cities' and the regional
 * ones that some obec elects in (data.js `electsAnywhere`: those held
 * apart before 2022 have only their own); of a by-election those of them
 * held somewhere (data/index.json `held`); of a country-wide election its
 * contests' (each round of a presidential election; a referendum once, by
 * its first question, all being on one ballot paper; a party-list election
 * once, by its parties' contest, not their lists'). */
async function turnoutChoices() {
  if (isNational) {
    const file = await getJSON('/data/country.json');
    const ids = Object.keys(file.contests)
      .filter((id) => !isList(id))
      .sort((a, b) => parseContest(a).sub - parseContest(b).sub);
    const referendum = ids.some((id) => parseContest(id).kind === 'referendum');
    const found = await contests(referendum ? ids.slice(0, 1) : ids);
    return found.map((c) => {
      const label = referendum ? t('mapmode.turnout_referendum_option') : c.label;
      return { mode: turnoutMode(c, label), label };
    });
  }
  const index = await dataIndex();
  const held = index.held && Object.entries(index.held);
  const holds = (e) => (held ? held.some(([code, ids]) => heldFor(e, code, ids, index)) : electsAnywhere(index, e));
  return ELECTIONS.filter(holds).map((e) => ({
    mode: { kind: 'turnout', election: e },
    label: t(`mapmode.turnout_${e}_option`),
  }));
}

/* The turnouts of the menu (`turnoutChoices`), for a component; null
 * while they load. */
export function useTurnoutChoices() {
  const [choices] = useLoaded(turnoutChoices, []);
  return choices;
}

/* Mode *m* as a link names it (app.js `mr`): 'candidate:<candidacy>',
 * 'previous:<candidacy>' (the election before's), 'winner:<contest>',
 * 'turnout:<contest>' or 'turnout:<election>'; a contest's at a level of
 * its own with ',<level>' after it ('winner:nrsr:SK,okres'); null for
 * none. */
export function formatMode(m) {
  if (!m) return null;
  const level = m.level && m.level !== 'all' ? `,${m.level}` : '';
  if (m.kind === 'candidate') return `${m.previous ? 'previous' : 'candidate'}:${m.id}${level}`;
  return `${m.kind}:${m.contest ?? m.election}${level}`;
}

/* The mode a link names (`formatMode`), with *keepView*: the link names
 * the view as well, which fitting the map (`fitting`) would undo. A level
 * named is kept, from no place (see `mode`), and shown on the ballots too
 * (`setMapMode`); a link from before the levels names none, the whole.
 * Null for none, or for what is not known (a link made by hand, a contest
 * gone). */
export async function parseMode(value, keepView) {
  const at = value?.indexOf(':') ?? -1;
  if (at < 0) return null;
  const kind = value.slice(0, at);
  const comma = value.lastIndexOf(',');
  const level = comma > at && SCOPES.includes(value.slice(comma + 1)) ? value.slice(comma + 1) : 'all';
  const id = value.slice(at + 1, level === 'all' ? undefined : comma);
  // The regular elections' turnouts the menu offers (`turnoutChoices`):
  // not a country-wide election's, nor one this election does not hold.
  if (kind === 'turnout' && ELECTIONS.includes(id)) {
    const offered = (await turnoutChoices()).some((c) => c.mode.election === id);
    return offered ? { kind, election: id } : null;
  }
  const of = { level, place: null };
  const candidate = (then) => (contest) => {
    const c = contest.candidates.find((x) => x.id === id);
    return c && { ...candidateMode(c, contest.label, of), previous: then };
  };
  const make = {
    candidate: candidate(false),
    // A map that shows nothing where the contest has no election before
    // (`figures` `then`).
    previous: candidate(true),
    winner: (contest) => winnerMode(contest, of),
    turnout: (contest) => turnoutMode(contest, contest.label, of),
  }[kind];
  if (!make) return null;
  const [contest] = await contests([kind === 'winner' || kind === 'turnout' ? id : contestOf(id)]).catch(() => []);
  const m = contest?.candidates.length ? make(contest) : null;
  return m ? { ...m, keepView } : null;
}

/* The button that shows counted candidate *c*'s votes on the map, across
 * the areas of their contest where it has several, else over its one
 * area; *label* names the contest, *at* the level of the ballots it is on
 * (`levelled`; none on the candidate card). A ballot box, a value per
 * area, where the breakdown by leader has the folded map. At the end of
 * the candidate's row (ballots.js) and by the origins of their votes
 * (candidate.js). A person on a party's list has one only where the
 * results give the list's preference votes by obec (`areas`), which the
 * whole country's alone would not make a map of. */
export function MapButton({ candidate: c, label, at = null }) {
  const current = useMapMode();
  const live = useLive();
  if (isList(c.contest) && !live.of(c.contest)?.areas) return null;
  const on = current?.kind === 'candidate' && current.id === c.id;
  const next = candidateMode(c, label, at);
  return html`<${ToggleButton}
    cls="map-chip votes-map"
    next=${next}
    on=${on}
    label=${t(`mapmode.${c.type === 'party' || c.type === 'answer' ? c.type : 'candidate'}_${on ? 'hide' : 'show'}`)}
  >
    <${TurnoutIcon} />
  <//>`;
}

/* The colour the map shows mode *m* in (draw.js `setResults`): a
 * candidate's votes in the results' green, like the medal; a turnout in
 * the colour its area is drawn in otherwise (app.css `--map-<tone>`), so
 * that nothing changes colour unexpectedly: a municipality's red, a
 * council obvod's orange, Bratislava's and Košice's green, a regional
 * contest's violet. A country-wide contest's area is the whole map, drawn
 * in no colour of its own, and its turnout is the only one its election
 * has: an indigo of its own (`--map-turnout`), not the state border's
 * slate, as grey reads as muted or missing. The municipal turnout across
 * the country is the municipalities' colour, the two cities' own
 * elections theirs. A winner map has a colour per candidate instead:
 * null. */
export function toneOf(m, index) {
  if (m.kind === 'candidate') return 'result';
  if (m.kind === 'winner') return null;
  if (!m.contest) return { municipal: 'accent', city: 'city', regional: 'zsk' }[m.election];
  const { kind, area } = parseContest(m.contest);
  if (isCountry(m.contest)) return 'turnout';
  if (kind === 'predseda' || kind === 'zsk') return 'zsk';
  if (isCity(area)) return 'city';
  return kind === 'oz' && index && hasCouncilObvody(index, area) ? 'council' : 'accent';
}

/* The 2026 turnout at the end of a counted contest's header (ballots.js
 * `Turnout`, its meter the *children*) as the button that colours the
 * contest's area by it on the map, in the area's own colour (`toneOf`), and
 * takes that off again: the ballot box of the turnout's menu (controls.js)
 * beside the figure it puts on the map. *figures*: the turnout in words,
 * for the tooltip; *at*: the level of the ballots (`levelled`). */
export function TurnoutMapButton({ contest, figures, at = null, children }) {
  const current = useMapMode();
  const [index] = useLoaded(dataIndex, []);
  const on = current?.kind === 'turnout' && current.contest === contest.id;
  const next = turnoutMode(contest, contest.label, at);
  const action = t(on ? 'mapmode.contest_turnout_hide' : 'mapmode.contest_turnout_show');
  return html`<${ToggleButton}
    cls="map-chip turnout-map"
    style=${{ '--tone': `var(--map-${toneOf(next, index)})` }}
    next=${next}
    on=${on}
    label=${`${action}\n${figures}`}
  >
    <${TurnoutIcon} />
    ${children}
  <//>`;
}

/* The button before the turnout of a contest's header (ballots.js
 * `Contest`, and a party's list's facts, `PartyList`) once its
 * candidates' votes are counted: it colours each unit of the contest's
 * area (as `MapResults` has them at the zoom) by the candidate with the
 * most votes there, a breakdown with the folded map for its icon; *at*:
 * the level of the ballots (`levelled`). In a council that is its top
 * candidate there, not all it elects, as the legend says. */
export function WinnerMapButton({ contest, at = null }) {
  const current = useMapMode();
  const on = current?.kind === 'winner' && current.contest === contest.id;
  const next = winnerMode(contest, at);
  return html`<${ToggleButton}
    cls="map-chip winner-map"
    next=${next}
    on=${on}
    label=${t(on ? 'mapmode.winner_hide' : 'mapmode.winner_show')}
  >
    <${MapResultsIcon} />
  <//>`;
}

/* The names of the area files (kinds.js `areaName`) that hold the figures
 * of mode *m*: the contest's, or all of the election's that the live
 * results list. */
function areaFiles(m, live, index) {
  if (m.contest) return [areaName(m.contest, index)];
  const prefix = { municipal: 'okres/', city: 'city/', regional: 'kraj/' }[m.election];
  return Object.keys(live.status?.files ?? {}).filter((name) => name.startsWith(prefix));
}

/* The names of the area files whose figures by okrsok (live.js `okrsky`)
 * mode *m* shows, of its area files *names*: those, but for a
 * country-wide contest, whose okrsky are in files by kraj
 * (`country/<kraj>`, a party's list's `list/<p>/<kraj>`), those of the
 * kraje with okrsky drawn (*drawn* `keys`, `useDrawnOkrsky`). */
function okrskyFiles(m, names, index, drawn) {
  if (!m.contest || !isCountry(m.contest)) return names;
  const kraje = new Set([...drawn.keys].map((key) => index.obce[key.split('/')[0]]?.[2]).filter(Boolean));
  return [...kraje].map((kraj) => `${names[0]}/${kraj}`);
}

/* What the figures of *m* come from, as live.js has it now:
 * - main: the contest's entry, or the contests of each of area files
 *   *names* that has loaded (none for the municipal turnout, whose
 *   figures are all in `turnout`);
 * - okrsky: the figures by okrsok of area files *okrskyNames*
 *   (`okrskyFiles`);
 * - turnout: of the turnout of an election of many contests, the results'
 *   `turnout` (live.js), null for a contest or where there is none.
 * Each list holds only what exists and has loaded. Their identities
 * change exactly when the figures may. */
function sourcesOf(m, live, names, okrskyNames) {
  let main = [];
  if (m.contest) main = [live.of(m.contest)].filter((entry) => entry && entry !== NOT_COUNTED);
  else if (m.election !== 'municipal') main = names.map((name) => live.contests(name)).filter(Boolean);
  const okrsky = okrskyNames.map((name) => live.okrsky(name)).filter(Boolean);
  return { main, okrsky, turnout: m.contest ? null : (live.turnout() ?? null) };
}

/* The leaders of an area's *votes* ({number: votes}) of *valid*: [their
 * votes (each), valid, their numbers in the order *order* (a compare
 * function), votes], several on a tie for the lead, which a winner map
 * stripes in all their colours rather than leave the area blank as if it
 * had no votes; null without votes. */
function leader(votes, valid, order) {
  let best = 0;
  let numbers = [];
  for (const [n, v] of Object.entries(votes)) {
    if (v > best) {
      best = v;
      numbers = [Number(n)];
    } else if (v === best && v > 0) numbers.push(Number(n));
  }
  return numbers.length ? [best, valid, numbers.sort(order), votes] : null;
}

// An area's [eligible, voters, …] as a turnout figure, [voters, eligible].
const turnoutOf = ([eligible, voters]) => (eligible && voters != null ? [voters, eligible] : null);

// A contest's live entry (docs/results.md) as an area's record, [eligible,
// voters, valid, {number: votes}].
const recordOf = (e) => [
  e.eligible ?? null,
  e.voters ?? null,
  e.valid ?? null,
  Object.fromEntries((e.candidates ?? []).map(([n, v]) => [n, v])),
];

/* The records [eligible, voters, valid, {number: votes}] of a mode's units
 * as they are gathered from the live results, before `figures` turns them
 * into figures (a turnout's may be [eligible, voters] alone). A unit known
 * only by its parts has them summed in the results (docs/results.md), never
 * here. */
class Records {
  constructor(index, drawn) {
    this.index = index;
    this.drawn = drawn;
    // Obec code → record.
    this.obce = new Map();
    // Regional obvod '<kraj>/<n>' known only as a whole → record.
    this.whole = new Map();
    // Council obvod '<obec>/<k>' → its own record.
    this.councils = new Map();
    // The obce whose council obvody are filled by their own records alone:
    // a by-election's, of which the other obvody elect no one (the results'
    // `turnout` `councils` name those that do).
    this.byObvod = new Set();
    // The units held nowhere for want of candidates (`uncontestedUnits`),
    // on the municipal turnout: those its figures leave out for that.
    this.uncontested = new Set();
    // Drawn okrsok '<obec>/<n>' → record; the election before (live.js
    // `pastOf`, {day, method, record}) of the okrsky, obce and (on a map
    // of the election before) council obvody and regional obvody ('zsk')
    // where anything is known of it; on that map, the drawn okrsky whose
    // figures are not known.
    this.okrsky = new Map();
    this.past = { okrsky: new Map(), obce: new Map(), councils: new Map(), zsk: new Map() };
    this.unknown = new Set();
    // The okrsok files' units of the okrsky (`units`): by council obvod
    // and, of a contest without areas, by obec; for those with no record
    // of their own.
    this.okrskyCouncils = new Map();
    this.okrskyObce = new Map();
    // The cities (BA, KE) whose districts' figures are the `areas` of their
    // contest: a district missing from them is one whose votes are not
    // known (okrsky not told apart), which its known okrsky would belie.
    this.byAreas = new Set();
    // The record of all counted.
    this.total = null;
    // The okresy as the results have them summed (a country-wide contest's
    // or a city contest's `units`, the turnout of a municipal election
    // without regional obvody); null where they go by regional obvod.
    this.okresy = null;
    // The regional obvody as the results have them (a regional president's
    // or a city contest's `units`, a turnout's), '<kraj>/<n>' → record.
    this.regional = new Map();
    // Whether the contest is of one obec; whether of one council obvod of
    // an obec split into several; a winner map's candidates by votes.
    this.local = false;
    this.piece = false;
    this.ranking = [];
  }

  /* An area of the live results: an obec, or `obvod:<n>` of *kraj*. */
  put(key, kraj, rec) {
    if (key.startsWith('obvod:')) this.whole.set(`${kraj}/${key.slice('obvod:'.length)}`, rec);
    else if (this.index.obce[key]) this.obce.set(key, rec);
  }

  /* Every regional obvod of *kraj* as a whole. */
  wholeKraj(kraj, rec) {
    for (const [, , k, n] of Object.values(this.index.obce)) if (k === kraj) this.whole.set(`${kraj}/${n}`, rec);
  }

  /* The regional obvody of *kraj* as the results have them, *units*
   * (`units.zsk`: number → record). */
  addRegional(kraj, units) {
    for (const [n, rec] of Object.entries(units)) this.regional.set(`${kraj}/${n}`, rec);
  }

  /* The okrsky of contest *id* in okrsok file *file*: each drawn one a
   * unit of its own, with the election before there, and its obec's; and
   * the file's units of them (`units`). (An okrsok without an area,
   * addressless, is not drawn, nor is a special one without territory,
   * data/index.json `special`: neither shades the map or widens its scale,
   * their figures staying in their obec's.) */
  addOkrsky(file, id) {
    const day = file.past?.day;
    const obce = day ? (file.past.contests[id] ?? {}) : {};
    for (const [key, rec] of Object.entries(file.contests[id] ?? {})) {
      const code = key.split('/')[0];
      if (this.drawn.keys.has(key)) {
        this.okrsky.set(key, rec);
        const past = pastOf(file, id, key);
        if (past) this.past.okrsky.set(key, past);
      }
      if (obce[code]) this.past.obce.set(code, { day, method: PAST.same, record: obce[code] });
    }
    const units = file.units[id] ?? {};
    for (const [key, rec] of Object.entries(units.obvod ?? {})) this.okrskyCouncils.set(key, rec);
    for (const [code, rec] of Object.entries(units.obec ?? {})) this.okrskyObce.set(code, rec);
  }
}

/* One contest's records (mode *m* with a `contest`): its `areas`, else its
 * own figures over its own area; its coarsest units (`units`); and its
 * okrsky. */
function gatherContest(rs, m, sources) {
  const { index } = rs;
  const [entry] = sources.main;
  const [kind, area] = m.contest.split(':');
  const code = area.split('/')[0];
  const city = isCity(code);
  const areas = Object.entries(entry?.areas ?? {});
  for (const [key, rec] of areas) rs.put(key, code, rec);
  if (city && entry?.areas) rs.byAreas.add(code);
  const total = entry ? recordOf(entry) : null;
  rs.total = total;
  const units = entry?.units;
  if (units?.okres) rs.okresy = new Map(Object.entries(units.okres));
  // A regional president's kraj, a city contest's the city's.
  if (units?.zsk) rs.addRegional(city ? index.obce[code][2] : code, units.zsk);
  if (m.kind === 'winner') rs.ranking = [...(entry?.candidates ?? [])].sort((a, b) => b[1] - a[1]).map(([n]) => n);
  rs.local = isMunicipal(m.contest) && !city && Boolean(index.obce[code]);
  // A council of one obvod of an obec split into several: the obvod is its
  // whole area, and the obec as a whole has no figure of it.
  rs.piece = rs.local && kind === 'oz' && hasCouncilObvody(index, code);
  // A regional council obvod's own figures are its regional obvod's, known
  // only as a whole where it has no areas.
  if (kind === 'zsk' && total) (areas.length ? rs.regional : rs.whole).set(area, total);
  // Without areas, the contest's own area. A city contest's is its
  // districts (a city council obvod's, those in it), which are obce; the
  // city is not.
  if (!areas.length && total) {
    if (kind === 'predseda') rs.wholeKraj(code, total);
    else if (city) {
      const obvod = kind === 'oz' ? Number(area.split('/')[1]) : null;
      for (const [k, row] of Object.entries(index.obce)) {
        if (row[5] === code && (obvod === null || row[6] === obvod)) rs.obce.set(k, total);
      }
    } else if (rs.piece) rs.councils.set(area, total);
    else if (rs.local) rs.obce.set(code, total);
  }
  for (const file of sources.okrsky) rs.addOkrsky(file, m.contest);
}

/* A candidate's votes at the election before (mode *m* with `previous`),
 * from the okrsok files' `past` (live.js `pastOf`), on the 2026 units: an
 * obec by its own figures then where the contest covers all of it; a
 * drawn okrsok by its, unless not known (`unknown`); a council obvod of
 * an obec split into several by its okrsky summed, the least certain
 * method theirs, unless one of them is not known (`past.units`, summed
 * with the results: `obvod`, and a council obvod's own contest `all`);
 * the coarsest units likewise (`zsk`, `okres`; a regional council obvod's
 * `obce`). The total is the contest's own then (`totals`, a mayor's or a
 * president's), else that of its obce then (`obce`; of a contest of one
 * obec, the obec's) only where every one is known: a sum short of some
 * would tell a share the candidate never had. */
function gatherPrevious(rs, m, sources) {
  const { index } = rs;
  const area = m.contest.slice(m.contest.indexOf(':') + 1);
  const { kind, area: code } = parseContest(m.contest);
  rs.local = isMunicipal(m.contest) && !isCity(code) && Boolean(index.obce[code]);
  rs.piece = rs.local && kind === 'oz' && hasCouncilObvody(index, code);
  // A regional president's kraj, a city contest's the city's.
  const kraj = isCity(code) ? index.obce[code]?.[2] : code;
  let total = null;
  for (const file of sources.okrsky) {
    if (!file.past?.day) continue;
    const { day } = file.past;
    total = file.past.totals[m.contest] ?? total;
    for (const [key, rec] of Object.entries(file.past.contests[m.contest] ?? {})) {
      if (key.includes('/') || !index.obce[key]) continue;
      rs.obce.set(key, rec);
      rs.past.obce.set(key, { day, method: PAST.same, record: rec });
    }
    const units = file.past.units[m.contest];
    const councils = Object.entries(units?.obvod ?? {});
    if (rs.piece && units?.all) councils.push([area, units.all]);
    for (const [council, [method, record]] of councils) {
      rs.councils.set(council, record);
      rs.past.councils.set(council, { day, method, record });
      if (rs.piece && council === area) total = record;
    }
    if (units?.zsk) {
      const obvody = Object.entries(units.zsk);
      rs.addRegional(kraj, Object.fromEntries(obvody.map(([n, [, record]]) => [n, record])));
      for (const [n, [method, record]] of obvody) rs.past.zsk.set(`${kraj}/${n}`, { day, method, record });
    }
    if (units?.okres) {
      rs.okresy ??= new Map();
      for (const [okres, [, record]] of Object.entries(units.okres)) rs.okresy.set(okres, record);
    }
    if (units?.obce) {
      total ??= units.obce[1];
      if (kind === 'zsk') rs.regional.set(area, units.obce[1]);
    }
    for (const key of Object.keys(file.contests[m.contest] ?? {})) {
      if (!rs.drawn.keys.has(key)) continue;
      const past = pastOf(file, m.contest, key);
      if (!past) continue;
      if (past.record) {
        rs.okrsky.set(key, past.record);
        rs.past.okrsky.set(key, past);
      } else rs.unknown.add(key);
    }
  }
  rs.total = total ?? (rs.local && !rs.piece ? (rs.obce.get(code) ?? null) : null);
}

/* Whether candidate *m* (a candidate mode) stood for the same office at
 * the election before: their number among the votes then anywhere in
 * the okrsok files' `past` of *sources* (`sourcesOf`). */
const ranThen = (m, sources) =>
  sources.okrsky.some((file) =>
    Object.values(file.past?.contests?.[m.contest] ?? {}).some((record) => record[3][m.number] != null),
  );

/* The municipal turnout (mode *m*, election 'municipal' or 'city'), as the
 * results' `turnout` has it summed: a municipality's is its mayor's
 * contest's, where that has none (a contest not held, or without its
 * figures yet) its council obvody's summed; a council obvod's is its
 * council's. Bratislava's and Košice's districts are municipalities here,
 * electing their own. The two cities' own elections (a city mayor and
 * council over all their districts) are on ballots of their own, so a
 * layer of their own ('city', the city files): by district where the
 * mayor's contest has `areas`, else the whole city alike. Their okrsky
 * likewise. */
function gatherMunicipal(rs, m, sources) {
  const { index } = rs;
  const turnout = sources.turnout?.[m.election];
  if (turnout) {
    rs.total = turnout.total;
    if (turnout.zsk) for (const [key, rec] of Object.entries(turnout.zsk)) rs.regional.set(key, rec);
    if (turnout.okres) rs.okresy = new Map(Object.entries(turnout.okres));
    for (const [code, rec] of Object.entries(turnout.obce)) {
      if (!index.obce[code]) continue;
      if (m.election === 'municipal') {
        rs.obce.set(code, rec);
        continue;
      }
      // The city's mayor's districts, where the turnout is the mayor's.
      const mayor = sources.main.map((contests) => contests[`starosta:${code}`]).find(Boolean);
      const areas = mayor?.eligible && mayor.voters != null ? Object.entries(mayor.areas ?? {}) : [];
      if (areas.length) {
        rs.byAreas.add(code);
        for (const [key, a] of areas) rs.put(key, null, a);
      } else {
        for (const [k, row] of Object.entries(index.obce)) if (row[5] === code) rs.obce.set(k, rec);
      }
    }
    for (const [key, rec] of Object.entries(turnout.councils ?? {})) {
      rs.councils.set(key, rec);
      if (isByElection) rs.byObvod.add(key.split('/')[0]);
    }
  }
  rs.uncontested = uncontestedUnits(index);
  for (const file of sources.okrsky) {
    // The mayor's okrsky, else the council obvody's: each okrsok is in one
    // of them.
    const ids = Object.keys(file.contests);
    const withMayor = new Set(ids.filter((id) => id.startsWith('starosta:')).map((id) => id.split(':')[1]));
    for (const id of ids) {
      const [kind, area] = id.split(':');
      if (kind === 'starosta' || (kind === 'oz' && !withMayor.has(area.split('/')[0]))) rs.addOkrsky(file, id);
    }
  }
}

/* The regional turnout: each kraj's presidential contest, the whole as the
 * results' `turnout` has it summed. */
function gatherRegional(rs, sources) {
  rs.total = sources.turnout?.regional?.total ?? null;
  for (const contests of sources.main) {
    const [id, e] = Object.entries(contests).find(([key]) => key.startsWith('predseda:')) ?? [];
    if (!e?.eligible || e.voters == null) continue;
    const kraj = id.slice('predseda:'.length);
    const areas = Object.entries(e.areas ?? {});
    for (const [key, a] of areas) rs.put(key, kraj, a);
    if (e.units?.zsk) rs.addRegional(kraj, e.units.zsk);
    // Without areas, the kraj as a whole: each of its obvody.
    if (!areas.length) rs.wholeKraj(kraj, recordOf(e));
  }
  for (const file of sources.okrsky) {
    for (const id of Object.keys(file.contests)) if (id.startsWith('predseda:')) rs.addOkrsky(file, id);
  }
}

/* The figures of mode *m* from *sources* (`sourcesOf`) by unit, each
 * [part, whole]: [votes, valid] of a candidate, [voters, eligible] of a
 * turnout, [the leader's votes, valid, the leaders' numbers (several on a
 * tie), votes] of a winner map (`leader`):
 * - obce: by obec code;
 * - councils: by council obvod '<obec>/<k>' of an obec split into several;
 * - byObvod: the obce whose council obvody are filled by their own figures
 *   alone, the others electing no one (`Records`);
 * - uncontested: the units held nowhere, no candidate having registered
 *   (`uncontestedUnits`);
 * - okrsky: by okrsok '<obec>/<n>' of those drawn (*drawn* `keys`,
 *   `useDrawnOkrsky`);
 * - past: the election before by kind of unit (okrsky, obce, councils, zsk) and
 *   key, as `Records` has it; unknown: the drawn okrsky whose figures then
 *   are not known, on a map of the election before;
 * - regional: by regional obvod '<kraj>/<n>', as the results have it summed
 *   (`units`, `turnout`), or as a whole where only that is known (those in
 *   the Set `whole`);
 * - okresy: by okres, as the results have it summed, in place of
 *   `regional` where the results go by okres (a country-wide contest, an
 *   election without regional obvody);
 * - total: of all counted, null if unknown;
 * - local: whether the contest is of one obec;
 * - ranking: a winner map's candidates' numbers, most votes first;
 * - then: the day of the election before the contest is compared with
 *   (its okrsok files' `past`: 2022's regional contests 2017, its
 *   municipal ones 2018), null where none is known;
 * - ran: for a candidate, whether they stood for the office then too
 *   (`ranThen`), where there was an election before. */
function figures(m, sources, index, drawn) {
  const rs = new Records(index, drawn);
  if (m.previous) gatherPrevious(rs, m, sources);
  else if (m.contest) gatherContest(rs, m, sources);
  else if (m.election === 'municipal' || m.election === 'city') gatherMunicipal(rs, m, sources);
  else gatherRegional(rs, sources);

  for (const [key, rec] of rs.okrskyCouncils) if (!rs.councils.has(key)) rs.councils.set(key, rec);
  // An obec without a figure of its own: its okrsky's; but not the obec of
  // a council obvod's contest, whose okrsky are only the obvod's.
  if (!rs.piece) {
    for (const [code, rec] of rs.okrskyObce) {
      if (!rs.obce.has(code) && index.obce[code] && !rs.byAreas.has(index.obce[code][5])) rs.obce.set(code, rec);
    }
  }
  const regional = new Map(rs.regional);
  for (const [key, rec] of rs.whole) regional.set(key, rec);
  // A tie's leaders in the order of their colours (`presentWinner`).
  const place = new Map(rs.ranking.map((n, i) => [n, i]));
  const byPlace = (a, b) => (place.get(a) ?? place.size) - (place.get(b) ?? place.size) || a - b;
  const of = {
    // A candidate not on the ballot then in a unit has no figure there.
    candidate: ([, , valid, votes]) => {
      const v = m.previous ? votes[m.number] : (votes[m.number] ?? 0);
      return valid && v != null ? [v, valid] : null;
    },
    winner: ([, , valid, votes]) => (valid ? leader(votes, valid, byPlace) : null),
    turnout: turnoutOf,
  }[m.kind];
  const figs = (records, as = of) => {
    const out = new Map();
    for (const [key, rec] of records) {
      const fig = as(rec);
      if (fig) out.set(key, fig);
    }
    return out;
  };
  const then = sources.okrsky.find((file) => file.past?.day)?.past.day ?? null;
  return {
    obce: figs(rs.obce),
    councils: figs(rs.councils),
    byObvod: rs.byObvod,
    uncontested: rs.uncontested,
    okrsky: figs(rs.okrsky),
    regional: figs(regional),
    okresy: figs(rs.okresy ?? new Map()),
    whole: new Set(rs.whole.keys()),
    past: rs.past,
    unknown: rs.unknown,
    total: rs.total ? of(rs.total) : null,
    local: rs.local,
    ranking: rs.ranking,
    then,
    ran: m.kind === 'candidate' && then !== null && (m.previous || ranThen(m, sources)),
  };
}

/* The units held nowhere of data/index.json *index*, no candidate having
 * registered (`uncontested`): the council obvody '<obec>/<k>' of an obec
 * of several, and the obce (or city districts) whose mayor and every
 * council obvod were held nowhere. */
function uncontestedUnits(index) {
  const out = new Set();
  const councils = new Map();
  const mayors = new Set();
  for (const id of index.uncontested) {
    const { kind, area, sub } = parseContest(id);
    if (kind === 'starosta') mayors.add(area);
    if (kind !== 'oz') continue;
    councils.set(area, (councils.get(area) ?? 0) + 1);
    if (hasCouncilObvody(index, area)) out.add(`${area}/${sub}`);
  }
  for (const [area, n] of councils) if (mayors.has(area) && n === index.obce[area]?.[4]) out.add(area);
  return out;
}

/* The figures of every unit of *figs* (`figures`), at every level: one
 * scale spans them all, so that a colour means the same at each zoom. */
const allFigures = (figs) => [
  ...figs.okrsky.values(),
  ...figs.councils.values(),
  ...figs.obce.values(),
  ...figs.regional.values(),
  ...figs.okresy.values(),
];

/* The figures of *figs* (`figures`) of the finest units: the okrsky, the
 * council obvody of the obce without those, the other obce, and the
 * regional obvody known only as a whole. */
function finestFigures(figs) {
  const obecOf = (key) => key.split('/')[0];
  const byOkrsky = new Set([...figs.okrsky.keys()].map(obecOf));
  const byCouncils = new Set([...figs.councils.keys()].map(obecOf));
  return [
    ...figs.okrsky.values(),
    ...[...figs.councils].filter(([key]) => !byOkrsky.has(obecOf(key))).map(([, fig]) => fig),
    ...[...figs.obce].filter(([key]) => !byOkrsky.has(key) && !byCouncils.has(key)).map(([, fig]) => fig),
    ...[...figs.regional].filter(([key]) => figs.whole.has(key)).map(([, fig]) => fig),
  ];
}

/* The cells draw.js `setResults` takes of *figs* (`figures`), each unit's
 * *cell(fig, level, key)*, *level* one of `past`'s, 'zsk' or 'okresy'; a
 * regional obvod known only as a whole marked so; the obce filled by
 * their council obvody's own cells alone (`byObvod`), and the units held
 * nowhere (`uncontested`). */
function cellsOf(figs, cell) {
  const cells = (map, level) => Object.fromEntries([...map].map(([key, fig]) => [key, cell(fig, level, key)]));
  const zsk = cells(figs.regional, 'zsk');
  for (const key of figs.whole) zsk[key]?.push(1);
  return {
    obce: cells(figs.obce, 'obce'),
    zsk,
    okresy: cells(figs.okresy, 'okresy'),
    councils: cells(figs.councils, 'councils'),
    okrsky: cells(figs.okrsky, 'okrsky'),
    byObvod: [...figs.byObvod],
    uncontested: [...figs.uncontested],
  };
}

/* What the map and the legend show of *figs* (`figures`) of mode *m*; null
 * with no values:
 * - shown: as draw.js `setResults` takes it;
 * - scale: [low, high], the shares of the lowest and the highest step;
 * - below, above: whether values lie beyond them;
 * - digits: of the percentages;
 * - estimated, unknown: on a map of the election before, the okrsky
 *   hatched (figures estimated from addresses) and grey (not known).
 * The scale spans the values of the units of every level (`allFigures`),
 * not from zero: areas not counted yet have no value and stay uncoloured,
 * so they do not widen it. */
function present(figs, m) {
  const share = ([part, all]) => part / all;
  const values = allFigures(figs)
    .map(share)
    .sort((a, b) => a - b);
  if (!values.length) return null;
  const trim = values.length >= TRIM_FROM ? TRIM : 0;
  const quantile = (q) => values[Math.min(values.length - 1, Math.floor(q * values.length))];
  // Whole percentage points, so that the ends read plainly.
  let low = Math.floor(quantile(trim) * 100 + 1e-9) / 100;
  let high = Math.ceil(quantile(1 - trim) * 100 - 1e-9) / 100;
  if (high <= low) {
    if (low >= 1) low = 0.99;
    else high = low + 0.01;
  }
  const digits = high < 0.1 ? 1 : 0;
  // All values alike (a single area, say): nothing to tell apart, so the
  // strongest step, for the area to show.
  const alike = values[0] === values.at(-1);
  const step = (v) =>
    alike ? STEPS - 1 : Math.min(STEPS - 1, Math.max(0, Math.floor(((v - low) / (high - low)) * STEPS)));
  const estimated = (level, key) => figs.past[level]?.get(key)?.method === PAST.approximate;
  const cells = cellsOf(figs, (fig, level, key) => [
    step(share(fig)) + (m.previous && estimated(level, key) ? STEPS : 0),
    formatPercent(share(fig), digits),
  ]);
  if (m.previous) for (const key of figs.unknown) cells.okrsky[key] = [UNKNOWN_STEP, '?'];
  const shown = m.previous
    ? { steps: PREVIOUS_PALETTE.length, palette: PREVIOUS_PALETTE, ...cells }
    : { steps: STEPS, ...cells };
  return {
    shown,
    scale: [low, high],
    below: values[0] < low,
    above: values.at(-1) > high,
    digits,
    estimated: m.previous ? [...figs.okrsky.keys()].filter((key) => estimated('okrsky', key)).length : 0,
    unknown: m.previous ? figs.unknown.size : 0,
  };
}

/* The names of the candidates *numbers* of winner map *m*: their full
 * names (*which* 0) or their surnames (1), or their numbers where unknown. */
const namesOf = (m, numbers, which) => numbers.map((n) => m.names[n]?.[which] ?? String(n));

// Those tied for the lead by surname, in the order of their stripes: a
// label on the map, where a list in words would rarely fit.
const surnames = (m, numbers) => namesOf(m, numbers, 1).join(' / ');

/* The same for a winner map (mode *m*): each unit in the colour of its
 * leader (`PALETTE`, by the candidates' votes overall) with the leader's
 * surname; a tie for the lead in stripes of the leaders' colours (a
 * palette entry of several, draw.js `stepFill`) with their surnames. The
 * legend's:
 * - leaders: [number, units led, colour, of those tied] of every candidate
 *   who leads one of the finest units (`finestFigures`), in the order of
 *   the colours; a tie counts for each of those tied, whose colours its
 *   stripes are;
 * - tie: {count, colours} where the map has stripes: the finest units
 *   tied, and the colours striped anywhere, else null.
 * Null with no values. */
function presentWinner(figs, m) {
  if (!allFigures(figs).length) return null;
  const colour = new Map(figs.ranking.map((n, i) => [n, Math.min(i, SERIES)]));
  const colourOf = (n) => colour.get(n) ?? SERIES;
  // A tie's palette entry by its colours, once each (those beyond SERIES
  // share one), in order as its leaders are; and all the colours striped.
  const palette = [...PALETTE];
  const striped = new Map();
  const stripedColours = new Set();
  const step = (numbers) => {
    const colours = [...new Set(numbers.map(colourOf))];
    if (colours.length === 1) return colours[0];
    const key = colours.join();
    if (!striped.has(key)) {
      striped.set(key, palette.length);
      palette.push(colours.map((c) => PALETTE[c]));
      for (const c of colours) stripedColours.add(c);
    }
    return striped.get(key);
  };
  const cells = cellsOf(figs, (fig) => [step(fig[2]), surnames(m, fig[2])]);
  const led = new Map();
  const tiedIn = new Map();
  let tied = 0;
  for (const [, , numbers] of finestFigures(figs)) {
    for (const n of numbers) led.set(n, (led.get(n) ?? 0) + 1);
    if (numbers.length === 1) continue;
    tied++;
    for (const n of numbers) tiedIn.set(n, (tiedIn.get(n) ?? 0) + 1);
  }
  const leaders = [...led]
    .map(([n, count]) => [n, count, colourOf(n), tiedIn.get(n) ?? 0])
    .sort((a, b) => a[2] - b[2] || b[1] - a[1]);
  return {
    shown: { steps: palette.length, palette, ...cells },
    leaders,
    tie: stripedColours.size ? { count: tied, colours: [...stripedColours].sort((a, b) => a - b) } : null,
    digits: 0,
  };
}

/* The kinds of unit that *figs* (`figures`) have figures of, coarsest
 * first, as the legend names them; on a map of the election before, the
 * okrsky whose figures then are not known count, being drawn grey. */
const levelsOf = (figs) =>
  [
    ['zsk', figs.regional.size],
    ['okresy', figs.okresy.size],
    ['obce', figs.obce.size],
    ['councils', figs.councils.size],
    ['okrsky', figs.okrsky.size + figs.unknown.size],
  ]
    .filter(([, size]) => size)
    .map(([level]) => t(`mapmode.level_${level}`));

/* The tooltip's lines of the election before in a unit, *past* (live.js
 * `pastOf`, {day, method, record}), on a map of mode *m* whose figure
 * there is *fig*: the year with how the figures were found, then (where
 * known) the turnout, and a candidate's or the leader's votes where they
 * stood. The year is that of the figures' own election: of 2022's
 * regional contests 2017, of its municipal ones 2018, of a referendum the
 * vote before of whatever kind (km-config `previous` names only the
 * elections before whose office holders are known). */
function pastLines(past, m, fig) {
  const lines = [t('mapmode.tip_previous', { previous: past.day.slice(0, 4), method: pastLabel(past.method) })];
  if (!past.record) return lines;
  const [eligible, voters, valid, votes] = past.record;
  if (eligible && voters != null) {
    lines.push(
      t('mapmode.tip_turnout', {
        turnout: formatPercent(voters / eligible),
        voters: formatNumber(Math.round(voters)),
        eligible: formatNumber(Math.round(eligible)),
      }),
    );
  }
  const numbers = { candidate: [m.number], winner: fig?.[2] ?? [] }[m.kind] ?? [];
  for (const n of numbers) {
    if (votes[n] == null || !valid) continue;
    const vars = {
      share: formatPercent(votes[n] / valid),
      votes: formatNumber(Math.round(votes[n])),
      valid: formatNumber(Math.round(valid)),
    };
    lines.push(
      m.kind === 'winner'
        ? t('mapmode.tip_previous_leader', { ...vars, name: namesOf(m, [n], 0)[0] })
        : t('mapmode.tip_votes', vars),
    );
  }
  return lines;
}

/* The tooltip's lines for the unit at the pointer, *hit* {kind, key}
 * (draw.js `unitAt`: the unit whose fill is drawn there), by figures *figs*
 * (`figures`) of mode *m*: those of `figureLines`, then where the map draws
 * the unit otherwise than this election had it (`originLines`); of a
 * council obvod that elects no one, or a unit held nowhere for want of
 * candidates (`unvoted`), its name and why no vote is held there. Null
 * where it has no figures. */
function tipLines(hit, figs, m, index) {
  if (hit.unvoted) {
    const [code, n] = hit.key.split('/');
    const name = index.obce[code]?.[0];
    const unit = n ? t('mapmode.tip_obvod', { n, name }) : name;
    return [unit, t(hit.unvoted === 'uncontested' ? 'mapmode.tip_uncontested' : 'mapmode.tip_not_held')];
  }
  if (m === HELD) return heldLines(hit, figs, index);
  const lines = figureLines(hit, figs, m, index);
  return lines && [...lines, ...originLines(hit, index)];
}

/* Where a by-election is held, which its map shows while no mode is
 * (`MapResults`): each place where something is elected (data.js
 * `heldObce`: an obec or city district; Bratislava or Košice, all their
 * districts; a kraj, all its obce) in a light tint of the accent colour,
 * as its turnout is drawn: each unit of the zoom tinted where something
 * is elected in it. Below the obce's zoom the okresy they are in, lighter
 * still: most of an okres votes in nothing. From the council obvody's
 * zoom an obec of several that elects only some of their councils by
 * those alone, its other obvody drawn as places without a vote (draw.js
 * `byObvod`). Light, as the turnout's lower steps are (draw.js
 * `TONE_STEPS`), so that the base map shows through and the selected
 * place's accent outline stands apart from it. */
const HELD = { kind: 'held' };
const HELD_STEP = 1;
const HELD_OKRES_STEP = 0;
// An okres's tooltip names its places held up to this many, else counts
// them.
const HELD_NAMED = 6;

/* The figures of `HELD`, as `MapResults` has a mode's: `figs` {obce: obec
 * code → the contests held there, councils: '<obec>/<n>' → those of a
 * council obvod of an obec electing nothing else, okresy: okres → the
 * codes of its obce held, no total}, `p` {shown (draw.js `setResults`),
 * counts: [obce, okresy]}. */
function heldFigures(index) {
  const obce = heldObce(index);
  const councils = new Map();
  for (const [code, ids] of obce) {
    const parts = ids.map(parseContest);
    if (!hasCouncilObvody(index, code) || parts.some((c) => c.kind !== 'oz' || c.area !== code)) continue;
    for (const [i, c] of parts.entries()) councils.set(`${code}/${c.sub}`, [ids[i]]);
  }
  const okresy = new Map();
  for (const code of obce.keys()) {
    const okres = index.obce[code][1];
    okresy.set(okres, [...(okresy.get(okres) ?? []), code]);
  }
  const cells = (map, step) => Object.fromEntries([...map.keys()].map((key) => [key, [step, '']]));
  return {
    figs: { obce, councils, okresy, total: null },
    p: {
      shown: {
        steps: STEPS,
        tone: 'accent',
        obce: cells(obce, HELD_STEP),
        okresy: cells(okresy, HELD_OKRES_STEP),
        zsk: {},
        councils: cells(councils, HELD_STEP),
        okrsky: {},
        byObvod: [...new Set([...councils.keys()].map((key) => key.split('/')[0]))],
        uncontested: [],
      },
      counts: [obce.size, okresy.size],
    },
  };
}

/* The tooltip's lines of `HELD` for the unit at the pointer, *hit*
 * (`tipLines`): an obec's or council obvod's name and the contests held
 * there, an okres's name and its places held; null for none. */
function heldLines({ kind, key }, figs, index) {
  if (kind === 'obce') {
    const ids = figs.obce.get(key);
    return ids ? [index.obce[key][0], ...ids.map((id) => contestLabel(id, index))] : null;
  }
  if (kind === 'councils') {
    const ids = figs.councils.get(key);
    const [code, n] = key.split('/');
    const unit = t('mapmode.tip_obvod', { n, name: index.obce[code][0] });
    return ids ? [unit, ...ids.map((id) => contestLabel(id, index))] : null;
  }
  const codes = kind === 'okresy' ? figs.okresy.get(key) : null;
  if (!codes) return null;
  const places =
    codes.length > HELD_NAMED
      ? t('mapmode.held_count', { n: formatNumber(codes.length) })
      : t('mapmode.held_in', { places: formatList(codes.map((code) => index.obce[code][0])) });
  return [t('mapmode.tip_okres', { name: index.okresy[key]?.[0] }), places];
}

/* The legend of `HELD`: the colour of the places held and the okresy's
 * lighter one, each with how many there are (*counts*). */
function HeldKey({ counts: [obce, okresy] }) {
  return html`<ul class="map-legend-leaders">
    <li>
      <span class="map-legend-swatch tint-held"></span>
      <span class="map-legend-name">${t('mapmode.held_obce')}</span>
      <span class="map-legend-count">${formatNumber(obce)}</span>
    </li>
    <li>
      <span class="map-legend-swatch tint-held-okres"></span>
      <span class="map-legend-name">${t('mapmode.held_okresy')}</span>
      <span class="map-legend-count">${formatNumber(okresy)}</span>
    </li>
  </ul>`;
}

/* What the map draws of unit *hit* that is not this election's own
 * (data/index.json, data.js `ballots` `origin`): okrsky from another
 * election's or a referendum's documents, council obvody drawn with
 * another election's rules, okrsky or obvody drawn with a later
 * election's without proof that they match, either from documents dated
 * only approximately or filled in from a later source, an obec whose
 * okrsky are not drawn (its figures by okrsok cannot be placed), or whose
 * boundary then differed; and, on an obec or its okrsky, its okrsky
 * without territory (`special`), which are never drawn. */
function originLines({ kind, key }, index) {
  const code = key.split('/')[0];
  if (kind === 'zsk' || kind === 'okresy') return [];
  const lines = [];
  const okrsky = index.okrsky_reused[code];
  const referendum = index.okrsky_referendum[code];
  if (kind === 'okrsky' && okrsky) lines.push(t('mapmode.tip_okrsky_reused', { other: okrsky.slice(0, 4) }));
  const okrskyAdopted = index.okrsky_adopted[code];
  if (kind === 'okrsky' && okrskyAdopted) {
    lines.push(t('notice.summary_okrsky_adopted', { source: standInSource(okrskyAdopted) }));
  }
  if (kind === 'okrsky' && referendum) lines.push(t('mapmode.tip_okrsky_referendum', { date: formatDate(referendum) }));
  if (kind === 'okrsky' && index.okrsky_date_approximate[code]) lines.push(t('notice.summary_okrsky_dated'));
  if (kind === 'okrsky' && index.okrsky_supplemented[code]) lines.push(t('notice.summary_okrsky_supplemented'));
  if (kind === 'councils' && index.reused[code]) lines.push(t('mapmode.tip_oz_reused', { other: index.reused[code].slice(0, 4) }));
  const adopted = index.adopted[code];
  if (kind === 'councils' && adopted) lines.push(t('council.summary_adopted', { source: standInSource(adopted) }));
  if (kind === 'councils' && index.date_approximate[code]) lines.push(t('council.summary_dated'));
  if (kind === 'councils' && index.supplemented[code]) lines.push(t('council.summary_supplemented'));
  if (kind === 'obce' && index.okrsky_unknown.includes(code)) lines.push(t('mapmode.tip_okrsky_unknown'));
  const special = index.special[code];
  if ((kind === 'obce' || kind === 'okrsky') && special) {
    lines.push(t('mapmode.tip_special', { n: Object.keys(special).join(', ') }));
  }
  if (index.boundaries?.obce[code]) lines.push(t('mapmode.tip_boundary', { on: index.boundaries.on }));
  return lines;
}

/* The figure lines of `tipLines`: the unit's name, its figures, and an
 * okrsok's or an obec's at the election before where anything is known of
 * it (`pastLines`); on a map of the election before, those alone. Null
 * where it has none. */
function figureLines(hit, figs, m, index) {
  const { kind, key } = hit;
  const fig = (kind === 'zsk' ? figs.regional : figs[kind]).get(key);
  const unknown = Boolean(m.previous) && kind === 'okrsky' && figs.unknown.has(key);
  if (!fig && !unknown) return null;
  const [code, n] = key.split('/');
  const name = index.obce[code]?.[0];
  const unit = {
    okrsky: () => t('mapmode.tip_okrsok', { n, name }),
    councils: () => t('mapmode.tip_obvod', { n, name }),
    obce: () => name,
    zsk: () => t('mapmode.tip_zsk', { n, kraj: index.kraje[code] }),
    okresy: () => t('mapmode.tip_okres', { name: index.okresy[code]?.[0] }),
  }[kind]();
  const past = unknown ? { day: figs.then, method: PAST.unknown, record: null } : figs.past[kind]?.get(key);
  if (m.previous) {
    // A regional obvod without units of the results: its obce's own
    // figures then, summed.
    if (past) return [unit, ...pastLines(past, m, fig)];
    const vars = { share: formatPercent(fig[0] / fig[1]), votes: formatNumber(fig[0]), valid: formatNumber(fig[1]) };
    const previous = figs.then.slice(0, 4);
    return [unit, t('mapmode.tip_previous', { previous, method: pastLabel(PAST.same) }), t('mapmode.tip_votes', vars)];
  }
  const share = formatPercent(fig[0] / fig[1]);
  let value;
  if (m.kind === 'candidate') {
    value = t('mapmode.tip_votes', { share, votes: formatNumber(fig[0]), valid: formatNumber(fig[1]) });
  } else if (m.kind === 'winner') {
    value = leadText(m, fig[2], share, 'mapmode.tip_winner', 'mapmode.tip_tie');
  } else {
    value = t('mapmode.tip_turnout', { turnout: share, voters: formatNumber(fig[0]), eligible: formatNumber(fig[1]) });
  }
  return [unit, value, ...(past ? pastLines(past, m, fig) : [])];
}

/* What winner map *m* says of the leaders *numbers* (a figure's, `leader`)
 * with *share* each: by message *one* the leader's full name, or by *tie*
 * those tied for the lead in a list. */
const leadText = (m, numbers, share, one, tie) =>
  numbers.length === 1
    ? t(one, { name: namesOf(m, numbers, 0)[0], share })
    : t(tie, { names: formatList(namesOf(m, numbers, 0)), share });

/* *lines* (`tipLines`) as a tooltip's or a card's content: the unit's name
 * in bold, then its figures. */
const tipContent = (lines) =>
  lines.map((line, i) => (i ? html`<span key=${i}>${line}</span>` : html`<strong key=${i}>${line}</strong>`));

// Pixels of each colour across a legend's stripes.
const SWATCH_STRIPE = 3;

/* The style of a legend's swatch of *colours* (indexes of PALETTE): one
 * plain, several in stripes as the map draws a tie (draw.js `stepFill`). */
function swatchStyle(colours) {
  const vars = colours.map((c) => `var(--map-${PALETTE[c]})`);
  if (vars.length === 1) return { background: vars[0] };
  const stops = vars.map((v, i) => `${v} ${i * SWATCH_STRIPE}px ${(i + 1) * SWATCH_STRIPE}px`);
  return { background: `repeating-linear-gradient(45deg, ${stops.join(', ')})` };
}

// The title of a winner map's *count* of units led, *ties* of them tied.
const ledTitle = (count, ties) =>
  ties
    ? t('mapmode.winner_count_ties', { n: formatNumber(count), ties: formatNumber(ties) })
    : t('mapmode.winner_count', { n: formatNumber(count) });

// The title of the finest units tied, *tie* as `presentWinner` has it.
const tieTitle = (tie) => (tie.count ? t('mapmode.tie_count', { n: formatNumber(tie.count) }) : undefined);

/* The candidates of a winner map who lead somewhere, each in their colour,
 * with how many of the units shown they lead (ties included, as their
 * colour is in the stripes); then, where any unit is striped, the stripes
 * of a tie (`presentWinner` *tie*) with the finest units tied. */
function Leaders({ m, leaders, tie }) {
  return html`<ul class="map-legend-leaders">
    ${leaders.map(
      ([n, count, colour, ties]) => html`<li key=${n}>
        <span class="map-legend-swatch" style=${swatchStyle([colour])}></span>
        <span class="map-legend-name">${m.names[n]?.[0] ?? n}</span>
        <span class="map-legend-count" title=${ledTitle(count, ties)}>${formatNumber(count)}</span>
      </li>`,
    )}
    ${
      tie &&
      html`<li key="tie">
        <span class="map-legend-swatch" style=${swatchStyle(tie.colours)}></span>
        <span class="map-legend-name">${t('mapmode.tie')}</span>
        <span class="map-legend-count" title=${tieTitle(tie)}>${tie.count ? formatNumber(tie.count) : ''}</span>
      </li>`
    }
  </ul>`;
}

/* The same as a row of chips, by surname as the map names them, scrolled
 * sideways where wider than the screen: the legend in a phone's sheet. */
function Chips({ m, leaders, tie }) {
  return html`<ul class="map-legend-chips">
    ${leaders.map(
      ([n, count, colour, ties]) => html`<li key=${n} title=${ledTitle(count, ties)}>
        <span class="map-legend-swatch" style=${swatchStyle([colour])}></span>
        <span class="map-legend-name">${m.names[n]?.[1] ?? n}</span>
        <span class="map-legend-count">${formatNumber(count)}</span>
      </li>`,
    )}
    ${
      tie &&
      html`<li key="tie" title=${tieTitle(tie)}>
        <span class="map-legend-swatch" style=${swatchStyle(tie.colours)}></span>
        <span class="map-legend-name">${t('mapmode.tie')}</span>
        ${tie.count ? html`<span class="map-legend-count">${formatNumber(tie.count)}</span>` : null}
      </li>`
    }
  </ul>`;
}

/* On a map of the election before, of day *then* (`figures`), what the
 * okrsky hatched and grey are (`present` *estimated*, *unknown*), each
 * with its swatch and how many of the drawn okrsky it is; nothing where
 * there are none. */
function PastKey({ estimated, unknown, then }) {
  const rows = [
    ['approximate', estimated, 'map-legend-swatch hatched'],
    ['unknown', unknown, 'map-legend-swatch past-unknown'],
  ].filter(([, count]) => count);
  if (!rows.length) return null;
  return html`<ul class="map-legend-leaders map-legend-past">
    ${rows.map(
      ([method, count, cls]) => html`<li key=${method} title=${pastTitle(PAST[method], then)}>
        <span class=${cls}></span>
        <span class="map-legend-name">${t(`mapmode.legend_${method}`)}</span>
        <span class="map-legend-count">${formatNumber(count)}</span>
      </li>`,
    )}
  </ul>`;
}

/* The choice between a candidate's 2026 votes and those at the election
 * before (mode *m*'s `previous`), of day *then* (`figures`: the contest's
 * own, which for 2022's regional contests is 2017's), for one who stood
 * for the same office then (`ranThen`): two buttons named by the years. */
function YearChoice({ m, then }) {
  const previous = then.slice(0, 4);
  const years = [
    [false, election.slice(0, 4), 'mapmode.current_show'],
    [true, previous, 'mapmode.previous_show'],
  ];
  return html`<div class="map-legend-years" role="group" aria-label=${t('mapmode.years')}>
    ${years.map(
      ([past, year, title]) => html`<button
        type="button"
        key=${year}
        title=${t(title, { previous })}
        aria-pressed=${Boolean(m.previous) === past ? 'true' : 'false'}
        onClick=${() => setMapMode({ ...m, previous: past })}
      >
        ${year}
      </button>`,
    )}
  </div>`;
}

/* The figure of all counted in mode *m* (*total* as `figures` has it, of
 * the election before of day *then* on its map) in short, beside the
 * legend's title, which names the turnout or the candidate: the turnout,
 * the candidate's share, or the share of the one with the most votes
 * (each of those tied for them) after their surname. Null where unknown. */
function keyFigure(m, total, then) {
  if (!total?.[1]) return null;
  const share = formatPercent(total[0] / total[1]);
  if (m.kind === 'turnout') return t('mapmode.turnout_total', { turnout: share });
  const year = m.previous ? ` · ${then.slice(0, 4)}` : '';
  if (m.kind === 'candidate') return `${share}${year}`;
  return `${surnames(m, total[2])} ${share}${year}`;
}

/* The legend's title, subtitle and summary (the figure of all counted,
 * *total* as `figures` has it, null where unknown) for mode *m*, on the
 * map of the election before that of day *then* (null until known). */
function legendText(m, total, then) {
  if (m === HELD) return { title: t('mapmode.held_title'), subtitle: t('mapmode.held_by'), summary: null };
  const share = total?.[1] ? formatPercent(total[0] / total[1]) : null;
  if (m.kind === 'candidate') {
    const of = t(m.of);
    let subtitle = `${m.label} · ${of}`;
    if (m.previous) {
      subtitle = then ? `${m.label} · ${t('mapmode.previous_of', { share: of, previous: then.slice(0, 4) })}` : m.label;
    }
    return {
      title: m.name,
      subtitle,
      summary: total
        ? `${formatPercent(total[0] / total[1])} · ${t(isList(m.contest) ? 'mapmode.preferences' : 'results.votes', { n: formatNumber(total[0]) })}`
        : null,
    };
  }
  if (m.kind === 'winner') {
    return {
      title: t('mapmode.winner_title'),
      subtitle: `${m.label} · ${t(m.of)}`,
      summary: total
        ? leadText(m, total[2], formatPercent(total[0] / total[1]), 'mapmode.winner_total', 'mapmode.winner_total_tie')
        : null,
    };
  }
  return {
    title: m.contest ? t('mapmode.turnout_title') : t(`mapmode.turnout_${m.election}`),
    subtitle: m.contest ? `${m.label} · ${t('mapmode.turnout_of')}` : t('mapmode.turnout_by'),
    summary: share && t('mapmode.turnout_total', { turnout: share }),
  };
}

/* Renders *children* into element *into*, a root of its own: the legend in
 * the sheet (pane.js), as this Preact has no portals. */
function Portal({ into, children }) {
  useLayoutEffect(() => {
    render(children, into);
  });
  useLayoutEffect(() => () => render(null, into), [into]);
  return null;
}

// Pixels between the tapped point, or the edges of the map left uncovered,
// and the card of the unit tapped.
const CARD_GAP = 12;

/* The unit tapped on a touch screen (map.js `setInspect`), *at* {x, y,
 * pick}: its figures, *lines* (`tipLines`), in a card by the tap, kept
 * within the part of the map left uncovered (*insets*, app.js), with a
 * button that picks the place there as the tap would have. Esc or a press
 * outside the map closes it (`onClose`); on the map, map.js and MapResults
 * see to that. */
function TapCard({ lines, at, insets, onClose }) {
  const card = useRef(null);

  useLayoutEffect(() => {
    const el = card.current;
    const i = insets();
    const right = innerWidth - i.right - el.offsetWidth - CARD_GAP;
    const bottom = innerHeight - i.bottom - el.offsetHeight - CARD_GAP;
    // Below the tap, or above it where there is no room below.
    const below = at.y + CARD_GAP;
    const top = below <= bottom ? below : at.y - el.offsetHeight - CARD_GAP;
    el.style.left = `${Math.max(i.left + CARD_GAP, Math.min(right, at.x - el.offsetWidth / 2))}px`;
    el.style.top = `${Math.max(i.top + CARD_GAP, Math.min(bottom, top))}px`;
  });

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      // Handled: app.js would close the pane as well.
      e.preventDefault();
      onClose();
    };
    const outside = (e) => {
      if (!card.current.contains(e.target) && !e.target.closest('.leaflet-container')) onClose();
    };
    // Before app.js's Esc and any press's own handling.
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('pointerdown', outside, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('pointerdown', outside, true);
    };
  }, []);

  return html`<div class="map-tip map-card" ref=${card} role="dialog" aria-label=${lines[0]}>
    ${tipContent(lines)}
    <button
      type="button"
      class="map-card-ballots"
      onClick=${() => {
        onClose();
        at.pick();
      }}
    >
      ${t('mapmode.show_ballots')}<${ArrowIcon} />
    </button>
  </div>`;
}

/* Where the tooltip of the pointer at *tip* {x, y} goes: below and right
 * of it, or left of it near the right edge of the page, where it would
 * not fit. */
const tipStyle = ({ x, y }) => ({
  left: `${x}px`,
  top: `${y}px`,
  transform: x > innerWidth - 300 ? 'translate(calc(-100% - 14px), 14px)' : 'translate(14px, 14px)',
});

/* The okrsky the map draws (geo/index.json `okrsky.drawn`, obec → the
 * numbers of its okrsky that have an area), for a component: {keys: Set of
 * '<obec>/<n>'}; null while it loads. */
export function useDrawnOkrsky() {
  const [geo] = useLoaded(() => getJSON('/geo/index.json'), []);
  return useMemo(() => {
    if (!geo) return null;
    const entries = Object.entries(geo.okrsky.drawn);
    return { keys: new Set(entries.flatMap(([obec, numbers]) => numbers.map((n) => `${obec}/${n}`))) };
  }, [geo]);
}

/* Whether the visitor folded the legend (true) or unfolded it (false), the
 * same for every mode and kept across visits, so that results switched or
 * reloaded do not bring back a legend put away; null until they choose. */
const FOLD_KEY = 'election-map-slovakia.legend';

function storedFold() {
  try {
    const stored = localStorage.getItem(FOLD_KEY);
    return stored === 'folded' ? true : stored === 'unfolded' ? false : null;
  } catch {
    // Storage disabled: the screen's default it is.
    return null;
  }
}

function storeFold(folded) {
  try {
    localStorage.setItem(FOLD_KEY, folded ? 'folded' : 'unfolded');
  } catch {
    // Storage disabled: the choice holds for this visit.
  }
}

/* Shows the mode on *map* (map.js) with its legend: what is shown, by
 * which units, the scale (or the leaders) and the share or turnout of all
 * counted. While the pointer is over the map, a tooltip names the unit
 * under it; on a touch screen a card shows the unit tapped (`TapCard`).
 * The level the ballots show the results at has its unit of the selected
 * place outlined (`chosenLevel`), and the view is fitted as `fitting`
 * asks. *legendRef* gets the legend's element over the map
 * (app.js `insets`, which *insets* is). Without a mode, a by-election's
 * map shows where it is held (`HELD`), with a legend that closes the same
 * way, for good.
 *
 * The legend folds into a pill with its title and the figure of all
 * counted (`keyFigure`), which unfolds it again; folding leaves the
 * results on the map, which only the close button takes off. The choice
 * is kept (`storedFold`); until there is one, the legend starts whole,
 * and folded on a *phone*, where the pill goes under the search card.
 * With a phone's sheet open, the legend is a bar at the top of the sheet,
 * rendered into element *sheet* (pane.js): the title, the figure, the
 * scale or the leaders' chips, the rest shown when unfolded. */
export function MapResults({ map, legendRef, phone, sheet, insets }) {
  const mode = useMapMode();
  const live = useLive();
  const [index] = useLoaded(dataIndex, []);
  const [tip, setTip] = useState(null);
  // The unit tapped (map.js `setInspect`), and the visitor's choice of the
  // legend folded or not.
  const [tapped, setTapped] = useState(null);
  const [foldChoice, setFoldChoice] = useState(storedFold);
  const folded = foldChoice ?? Boolean(phone);
  const setFolded = (next) => {
    setFoldChoice(next);
    storeFold(next);
  };
  // Whether the visitor has closed the legend of where a by-election is
  // held, which then stays off.
  const [heldClosed, setHeldClosed] = useState(false);
  // What the map shows: the mode, else where a by-election is held.
  const m = mode ?? (isByElection && !heldClosed && index?.held ? HELD : null);
  const held = m === HELD;
  const drawn = useDrawnOkrsky();
  const ready = Boolean(m && index && drawn);
  const names = ready && !held ? areaFiles(m, live, index) : [];
  const sources =
    ready && !held
      ? sourcesOf(m, live, names, okrskyFiles(m, names, index, drawn))
      : { main: [], okrsky: [], turnout: null };
  const tone = held ? 'accent' : m ? toneOf(m, index) : null;
  const result = useMemo(() => {
    if (!ready) return null;
    if (held) return heldFigures(index);
    const figs = figures(m, sources, index, drawn);
    const p = m.kind === 'winner' ? presentWinner(figs, m) : present(figs, m);
    return { figs, p: p && { ...p, shown: { ...p.shown, tone } } };
  }, [m, index, drawn, ...sources.main, ...sources.okrsky, sources.turnout]);
  const shown = result?.p ?? null;
  const total = result?.figs.total ?? null;
  // For the tap handler, which is set once per mode.
  const latest = useRef(null);
  latest.current = { m, index, figs: shown ? result.figs : null, tapped };

  useEffect(() => {
    map?.setResults(shown?.shown ?? null);
  }, [map, shown]);

  const level = useLevel();
  useEffect(() => {
    map?.setLevel(level);
  }, [map, level]);

  // A level followed while its units loaded, once they have.
  useEffect(followKnown);

  // Each fit asked for once, when the map and the index are there.
  const fitted = useRef(null);
  useEffect(() => {
    const asked = fitting;
    if (!map || !index || !asked || fitted.current === asked) return;
    fitted.current = asked;
    if (asked.level !== 'all' && asked.place) map.fitUnit(asked.level, asked.place);
    else if (isCountry(asked.contest)) map.fitCountry();
    else map.fitArea(contestArea(asked.contest, index));
  }, [map, index, fitting]);

  useEffect(() => {
    if (!map || !m) return undefined;
    map.setHover(setTip);
    // A tap on a unit with figures shows them; one beside the card closes
    // it; elsewhere the tap picks the place.
    map.setInspect((hit) => {
      const now = latest.current;
      const lines = hit?.unit && now.figs ? tipLines(hit.unit, now.figs, now.m, now.index) : null;
      setTapped(lines ? hit : null);
      return Boolean(lines || now.tapped);
    });
    return () => {
      map.setHover(null);
      map.setInspect(null);
      setTip(null);
      setTapped(null);
    };
  }, [map, m]);

  // The legend unfolded or folded covers more or less of the map. The
  // focus goes on to the button that undoes the change, rather than being
  // lost with the one pressed.
  const refocus = useRef(false);
  useLayoutEffect(() => {
    map?.redraw();
    if (!refocus.current) return;
    refocus.current = false;
    legendRef.current?.querySelector(folded ? '.map-legend-unfold' : '.map-legend-fold')?.focus();
  }, [folded]);
  const toggleFold = (next) => {
    refocus.current = true;
    setFolded(next);
  };

  if (!m) return null;
  const percent = (share) => formatPercent(share, shown?.digits ?? 0);
  // The day of the election before the contest is compared with.
  const then = result?.figs.then ?? null;
  const { title, subtitle, summary } = legendText(m, total, then);
  const scale = shown?.scale;
  const steps = (extra = '') => html`<div class=${`map-legend-scale${extra}`} aria-hidden="true">
    ${Array.from({ length: STEPS }, (_, i) => html`<span class=${`step-${i + 1}`}></span>`)}
  </div>`;
  const low = scale && (shown.below ? `≤ ${percent(scale[0])}` : percent(scale[0]));
  const high = scale && (shown.above ? `≥ ${percent(scale[1])}` : percent(scale[1]));
  let body;
  if (held) {
    body = shown ? html`<${HeldKey} counts=${shown.counts} />` : null;
  } else if (shown && m.kind === 'winner') {
    body = html`
      <${Leaders} m=${m} leaders=${shown.leaders} tie=${shown.tie} />
      ${summary ? html`<p class="map-legend-ends"><span class="map-legend-total">${summary}</span></p>` : null}
    `;
  } else if (scale) {
    body = html`
      ${steps()}
      <p class="map-legend-ends">
        <span>${low}</span>
        ${summary ? html`<span class="map-legend-total">${summary}</span>` : null}
        <span>${high}</span>
      </p>
      <${PastKey} estimated=${shown.estimated} unknown=${shown.unknown} then=${then} />
    `;
  } else {
    body = html`<p class="map-legend-none">${t('mapmode.none')}</p>`;
  }
  const years = result?.figs.ran ? html`<${YearChoice} m=${m} then=${then} />` : null;
  const classes = ['map-legend', tone && tone !== 'result' && 'toned', m.kind === 'winner' && 'winner'];
  const style = tone ? { '--tone': `var(--map-${tone})` } : undefined;
  const lines = tip && shown && index ? tipLines(tip.unit, result.figs, m, index) : null;
  const tappedLines = tapped && shown && index ? tipLines(tapped.unit, result.figs, m, index) : null;
  // Where a by-election is held, its subtitle says by which units.
  const levels = shown && !held ? levelsOf(result.figs) : [];
  const levelsLine = levels.length
    ? html`<p class="map-legend-levels">${t(levels.length > 1 ? 'mapmode.levels' : 'mapmode.levels_one', { units: formatList(levels) })}</p>`
    : null;
  const key = keyFigure(m, total, then);
  const closeLabel = t(held ? 'mapmode.held_close' : 'mapmode.close');
  const close = html`<button
    type="button"
    class="map-legend-close"
    title=${closeLabel}
    aria-label=${closeLabel}
    onClick=${() => (held ? setHeldClosed(true) : setMapMode(null))}
  >
    <${CloseIcon} />
  </button>`;
  const foldButton = html`<button
    type="button"
    class="map-legend-fold"
    title=${t(folded ? 'mapmode.legend_more' : 'mapmode.legend_less')}
    aria-label=${t(folded ? 'mapmode.legend_more' : 'mapmode.legend_less')}
    aria-expanded=${folded ? 'false' : 'true'}
    onClick=${() => toggleFold(!folded)}
  >
    <${ExpandIcon} />
  </button>`;

  let legend;
  if (sheet) {
    let row;
    if (held) row = body;
    else if (shown && m.kind === 'winner') row = html`<${Chips} m=${m} leaders=${shown.leaders} tie=${shown.tie} />`;
    else if (scale) row = html`<div class="map-legend-row"><span>${low}</span>${steps()}<span>${high}</span></div>`;
    else row = html`<p class="map-legend-none">${t('mapmode.none')}</p>`;
    legend = html`<${Portal} into=${sheet}>
      <section class=${[...classes, 'bar'].filter(Boolean).join(' ')} style=${style} aria-label=${t('mapmode.legend')}>
        <div class="map-legend-head">
          <p class="map-legend-title"><strong>${title}</strong></p>
          ${key ? html`<span class="map-legend-key">${key}</span>` : null}
          ${foldButton}${close}
        </div>
        ${years}
        ${folded ? null : html`<p class="map-legend-sub">${subtitle}</p>${levelsLine}`}
        ${row}
        ${!folded && shown ? html`<${PastKey} estimated=${shown.estimated} unknown=${shown.unknown} />` : null}
      </section>
    <//>`;
  } else if (folded) {
    // The leader overall in their colour, the first (`presentWinner`);
    // those tied for the lead overall in stripes of the first colours.
    const mark =
      m.kind === 'winner'
        ? html`<span
            class="map-legend-swatch"
            style=${swatchStyle(total ? total[2].map((_, i) => Math.min(i, SERIES)) : [0])}
          ></span>`
        : held
          ? html`<span class="map-legend-swatch tint-held"></span>`
          : steps(' mini');
    legend = html`<section
      class=${[...classes, 'float', 'pill'].filter(Boolean).join(' ')}
      style=${style}
      ref=${legendRef}
      aria-label=${t('mapmode.legend')}
    >
      <button
        type="button"
        class="map-legend-unfold"
        title=${t('mapmode.legend_more')}
        aria-expanded="false"
        onClick=${() => toggleFold(false)}
      >
        ${shown ? mark : null}
        <strong>${title}</strong>
        ${key ? html`<span class="map-legend-key">${key}</span>` : null}
        <${ExpandIcon} />
      </button>
      ${close}
    </section>`;
  } else {
    legend = html`<section
      class=${[...classes, 'float'].filter(Boolean).join(' ')}
      style=${style}
      ref=${legendRef}
      aria-label=${t('mapmode.legend')}
    >
      <div class="map-legend-head">
        <p class="map-legend-title"><strong>${title}</strong><span>${subtitle}</span></p>
        ${foldButton}${close}
      </div>
      ${years}
      ${levelsLine}
      ${body}
    </section>`;
  }
  return html`
    ${legend}
    ${lines ? html`<div class="map-tip" role="tooltip" style=${tipStyle(tip)}>${tipContent(lines)}</div>` : null}
    ${tappedLines ? html`<${TapCard} lines=${tappedLines} at=${tapped} insets=${insets} onClose=${() => setTapped(null)} />` : null}
  `;
}
