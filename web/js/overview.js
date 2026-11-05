/* The overview of a country-wide election whose ballots are the same
 * everywhere (kinds.js `overviewKind`), as wide as the page allows:
 * - of parties' lists (NR SR, EP): every party of the ballot, as many to a
 *   line as fit, and the list of the one selected in full, its persons in
 *   as many columns as fit, so that a list of 150 takes little of the
 *   screen's height. Parties and persons are circled, crossed out and
 *   filtered as on the ballots (ballots.js `useRowActions`, `FilterBar`),
 *   the work kept with the rest of the page's;
 * - of a referendum: its questions side by side, each with its wording,
 *   answers and verdict.
 * The results are the whole country's: the ballots are the same
 * everywhere, and so is the overview.
 *
 * Like Favourites, on a wide screen it is a panel of its own beside the
 * pane, so that the pane keeps the ballots or the card of a candidate
 * chosen here; on a narrower one the pane shows it (app.js). */

import { html, useEffect, useRef } from '../vendor/preact-htm.module.js';
import {
  byFilter,
  Contest,
  ContestFacts,
  FilterBar,
  ListResearch,
  NoSeats,
  noSeatsReason,
  PartyList,
  PartyRow,
  SeatsWon,
  useRowActions,
  Votes,
  withResults,
} from './ballots.js';
import { countryBallots, useLoaded } from './data.js';
import { election, electionName, t } from './i18n.js';
import { BackIcon } from './icons.js';
import { isParties, overviewKind } from './kinds.js';
import { decodeResults, NOT_COUNTED, useLive } from './live.js';

/* The parties of the ballot *contest* and the list of the one numbered
 * *party* (any other number: the first of them), which `onParty(number)`
 * changes. The parties are in the order of the ballots (by votes once
 * counted), those the filter mutes last; once final, those without seats
 * greyed with why (ballots.js `noSeatsReason`). A party pressed whose
 * list starts out of view brings it into view. */
function Parties({ contest, party, onParty, onCandidate, filter, actions, focus }) {
  const listRef = useRef(null);
  const live = useLive();
  const entry = live.of(contest.id);
  const whole = entry && entry !== NOT_COUNTED ? decodeResults(contest, entry) : null;
  const { order, muted, unmuted } = byFilter(withResults(contest, whole), filter, actions, Boolean(whole));
  const selected = order.find((c) => c.number === party) ?? order[0];
  const picked = contest.candidates.filter((c) => actions.isPicked(c.id)).length;
  const select = (number) => {
    onParty(number);
    // Once the list has changed, which it has by the next frame.
    requestAnimationFrame(() => {
      const list = listRef.current;
      const pane = list?.closest('.pane-body');
      if (pane && list.getBoundingClientRect().top > pane.getBoundingClientRect().bottom - 120) {
        list.scrollIntoView({ block: 'start', behavior: 'smooth' });
      }
    });
  };

  const p = selected.party;
  const noSeats = noSeatsReason(selected, whole, contest.threshold);
  return html`
    <div class="panel-body overview-facts">
      <${ContestFacts}
        id="km-overview-facts"
        contest=${contest}
        unmuted=${unmuted}
        picked=${picked}
        results=${whole}
        pending=${entry === NOT_COUNTED}
      />
    </div>
    <p class="panel-body intro">${t('overview.intro.parties')}</p>
    <ol class="cands overview-parties" aria-label=${t('overview.parties')} aria-describedby="km-overview-facts">
      ${order.map(
        (c) => html`<li key=${c.id}>
          <${PartyRow}
            candidate=${c}
            onCandidate=${onCandidate}
            actions=${actions}
            muted=${muted.get(c)}
            noSeats=${noSeatsReason(c, whole, contest.threshold)}
            threshold=${contest.threshold}
            filter=${filter}
            selected=${c === selected}
            onSelect=${select}
          />
        </li>`,
      )}
    </ol>
    <section class="overview-list" ref=${listRef} aria-labelledby="km-overview-party">
      <header class="overview-party">
        ${p.logo ? html`<img class="party-logo" src=${p.logo} alt="" />` : null}
        <h3 id="km-overview-party">${p.name}</h3>
        ${p.short !== p.name ? html`<span class="party" title=${t('party.short_title', { name: p.name })}>${p.short}</span>` : null}
        ${selected.result?.won ? html`<${SeatsWon} result=${selected.result} />` : null}
        ${noSeats ? html`<${NoSeats} why=${noSeats} />` : null}
        ${selected.listResearch ? html`<${ListResearch} candidate=${selected} />` : null}
        ${selected.result ? html`<${Votes} candidate=${selected} />` : null}
      </header>
      <${PartyList}
        key=${selected.id}
        id="km-overview-persons"
        party=${selected}
        onCandidate=${onCandidate}
        filter=${filter}
        actions=${actions}
        full
        focus=${focus}
      />
    </section>
  `;
}

/* The overview.
 * - party and `onParty(number)`: the party whose list is shown, of
 *   parties' lists.
 * - picks and `onPicks(next)`: the circled candidates (picks.js); filter
 *   and `onFilter(next)`: the candidate filter (ballots.js).
 * - onBack(): where given, goes back to what the pane showed before.
 * - focus: the candidacy whose card was just left; its row takes the
 *   focus, else the title does once the overview is in, unless it was
 *   opened from the map's ballot-box menu (controls.js `LayerMenus`):
 *   there the focus stays, so that the menu stays open with its box
 *   ticked, to close the overview again. */
export function Overview({ party, onParty, picks, onPicks, filter, onFilter, onCandidate, onBack, focus }) {
  const [list, failed] = useLoaded(countryBallots, []);
  const section = useRef(null);
  const heading = useRef(null);
  const contest = list?.find((c) => isParties(c.id)) ?? null;
  const actions = useRowActions(
    section,
    new Map((list ?? []).flatMap((c) => c.candidates.map((x) => [x.id, x]))),
    filter,
    onFilter,
    picks,
    onPicks,
  );

  useEffect(() => {
    if (list && !focus && !document.activeElement?.closest('.controls')) heading.current.focus();
  }, [Boolean(list)]);

  const back = onBack
    ? html`<button type="button" class="back" aria-label=${t('card.back')} title=${t('card.back')} onClick=${onBack}>
        <${BackIcon} />
      </button>`
    : null;
  const head = html`<header class=${onBack ? 'panel-head has-back' : 'panel-head'}>
    ${back}
    <div>
      <h2 id="km-overview" tabindex="-1" ref=${heading}>${t(`overview.title.${overviewKind}`)}</h2>
      <p class="muted">${electionName(election)}</p>
    </div>
  </header>`;

  let body;
  if (failed) body = html`<p class="panel-body error">${t('error.load')}</p>`;
  else if (!list) body = html`<p class="panel-body muted loading">${t('panel.loading')}</p>`;
  else if (overviewKind === 'parties' && contest) {
    body = html`
      <${FilterBar} filter=${filter} onFilter=${onFilter} actions=${actions} />
      <${Parties}
        contest=${contest}
        party=${party}
        onParty=${onParty}
        onCandidate=${onCandidate}
        filter=${filter}
        actions=${actions}
        focus=${focus}
      />
    `;
  } else {
    body = html`
      <p class="panel-body intro">${t('overview.intro.referendum')}</p>
      <div class="overview-questions">
        ${list.map(
          (c) =>
            html`<${Contest} key=${c.id} contest=${c} initiallyOpen onCandidate=${onCandidate} filter=${filter} actions=${actions} />`,
        )}
      </div>
    `;
  }

  return html`
    <section class="overview" aria-labelledby="km-overview" ref=${section}>
      ${head}
      ${body}
    </section>
  `;
}
