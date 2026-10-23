/* Favourites: every candidate the visitor has circled, on whichever
 * ballots, by contest, municipal then regional, each group in the order
 * its first candidate was circled. A contest is listed as on the candidate
 * card: closed, just the circled candidates; opened by its header, the
 * others after them, the filter applying to those only. The page's
 * address holds the circles and the filter (app.js), and a button by the
 * title copies a link to them alone, without the place shown on the map.
 *
 * On a wide screen the list is a panel of its own beside the pane, as wide
 * as the page allows, so that the pane keeps the ballots or the card of a
 * candidate chosen here; on a narrower one it is what the pane shows
 * (app.js). */

import { html, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { Contest, FilterBar, isMunicipal, useRowActions } from './ballots.js';
import { contestArea, contests, dataIndex, useLoaded } from './data.js';
import { formatNumber, t } from './i18n.js';
import { BackIcon, CheckIcon, LinkIcon } from './icons.js';
import { byContest } from './picks.js';

// How long the button says that it has copied the link.
const COPIED_MS = 2500;

/* The button that copies *link*, an icon by the title; *state* and
 * `onState(next)` whether it has: null, 'copied' or 'failed' (CopyFailed). */
function CopyLink({ link, state, onState }) {
  useEffect(() => {
    if (state !== 'copied') return;
    const timer = setTimeout(() => onState(null), COPIED_MS);
    return () => clearTimeout(timer);
  }, [state]);

  const failed = (error) => {
    // The old way works where the Clipboard API is missing (an insecure
    // context) or refuses; failing that, the link is shown to copy by hand.
    if (copyBySelection(link)) onState('copied');
    else {
      if (error) console.error(error);
      onState('failed');
    }
  };
  const copy = () => {
    // Called at once, in the tap's own handler: some mobile browsers allow
    // writing to the clipboard only there.
    if (!navigator.clipboard) failed(null);
    else navigator.clipboard.writeText(link).then(() => onState('copied'), failed);
  };
  const label = t(state === 'copied' ? 'favourites.copied' : 'favourites.copy');
  return html`
    <button type="button" class="share-button" title=${label} aria-label=${label} onClick=${copy}>
      ${state === 'copied' ? html`<${CheckIcon} />` : html`<${LinkIcon} />`}
    </button>
    <span class="sr-only" role="status">${state === 'copied' ? t('favourites.copied') : ''}</span>
  `;
}

/* Copies *text* by selecting it in a field off to the side, as pages did
 * before the Clipboard API; whether the browser did. */
function copyBySelection(text) {
  const before = document.activeElement;
  const field = document.createElement('textarea');
  field.value = text;
  field.readOnly = true;
  // 16px, or iOS zooms the page to the field.
  Object.assign(field.style, { position: 'fixed', top: '0', left: '-9999px', fontSize: '16px' });
  document.body.append(field);
  field.select();
  field.setSelectionRange(0, text.length);
  let copied = false;
  try {
    copied = document.execCommand('copy');
  } catch {
    // Refused: the caller shows the link instead.
  }
  field.remove();
  before?.focus();
  return copied;
}

/* Where the browser does not let the page write to the clipboard, the link
 * is shown instead, selected, to be copied by hand. */
function CopyFailed({ link }) {
  const field = useRef(null);
  // setSelectionRange too: iOS ignores select() on a read-only field.
  const selectAll = () => field.current.setSelectionRange(0, link.length);
  useEffect(() => {
    field.current.select();
    selectAll();
  }, []);
  return html`<label class="share-field panel-body">
    ${t('favourites.copy_failed')}
    <input type="text" readonly value=${link} ref=${field} onFocus=${selectAll} onClick=${selectAll} />
  </label>`;
}

/* *picks* and `onPicks(next)` the circled candidates (picks.js); *filter*
 * and `onFilter(next)` the candidate filter (ballots.js); *link* the link
 * to share them by. `onPlace(target)` shows a contest's area on the map
 * (data.js `contestArea`); `onBack()`, where given, goes back to what the
 * pane showed before. *focus*: the candidacy whose card was just left,
 * whose row then takes the focus; else the title takes it once the list
 * is in. */
export function Favourites({ picks, onPicks, filter, onFilter, onCandidate, onPlace, onBack, focus, link }) {
  /* The contests listed since the list opened: one whose circles are all
   * taken off stays, so that they can be put back. */
  const seen = useRef([]);
  for (const id of byContest(picks).keys()) if (!seen.current.includes(id)) seen.current.push(id);
  const ids = seen.current;
  const [result, failed] = useLoaded(() => Promise.all([contests(ids), dataIndex()]), [ids.join(',')]);
  const [copy, setCopy] = useState(null);
  const heading = useRef(null);
  const section = useRef(null);
  const focused = useRef(false);
  const rowFocused = useRef(null);
  const list = result?.[0] ?? [];
  const actions = useRowActions(
    section,
    new Map(list.flatMap((c) => c.candidates.map((x) => [x.id, x]))),
    filter,
    onFilter,
    picks,
    onPicks,
  );

  useEffect(() => {
    if (!result) return;
    // Once per return from a card, and the heading only once: circles added
    // in the pane beside reload the list, which must not take focus then.
    if (focus !== rowFocused.current) {
      rowFocused.current = focus;
      const row = focus && section.current.querySelector(`[data-candidate="${CSS.escape(focus)}"]`);
      if (row) {
        row.focus();
        focused.current = true;
        return;
      }
    }
    if (!focused.current) heading.current.focus();
    focused.current = true;
  }, [result, focus]);

  const back = onBack
    ? html`<button type="button" class="back" aria-label=${t('card.back')} title=${t('card.back')} onClick=${onBack}>
        <${BackIcon} />
      </button>`
    : null;
  const head = html`<header class=${onBack ? 'panel-head has-back' : 'panel-head'}>
    ${back}
    <div>
      <div class="favourites-title">
        <h2 id="km-favourites" tabindex="-1" ref=${heading}>${t('favourites.title')}</h2>
        ${picks.length ? html`<${CopyLink} link=${link} state=${copy} onState=${setCopy} />` : null}
      </div>
      ${picks.length ? html`<p class="muted">${t('favourites.count', { n: formatNumber(picks.length) })}</p>` : null}
    </div>
  </header>`;

  let body;
  if (!ids.length) body = html`<p class="panel-body intro">${t('favourites.empty')}</p>`;
  else if (failed) body = html`<p class="panel-body error">${t('error.load')}</p>`;
  else if (!result) body = html`<p class="panel-body muted loading">${t('panel.loading')}</p>`;
  else {
    const index = result[1];
    const byId = new Map(list.map((c) => [c.id, c]));
    const shown = ids.map((id) => byId.get(id)).filter((c) => c?.candidates.length);
    const group = (title, members) =>
      members.length
        ? html`<h3 class="group">${title}</h3>
            <div class="favourite-contests">
              ${members.map((c) => {
                const target = contestArea(c.id, index);
                return html`<${Contest}
                  key=${c.id}
                  contest=${c}
                  pin
                  onCandidate=${onCandidate}
                  filter=${filter}
                  actions=${actions}
                  map=${{ label: t(`card.map_${target.what}`), onClick: () => onPlace(target) }}
                />`;
              })}
            </div>`
        : null;
    body = html`
      <${FilterBar} filter=${filter} onFilter=${onFilter} actions=${actions} />
      <p class="panel-body intro">${t('favourites.intro')}</p>
      ${group(
        t('ballots.municipal'),
        shown.filter((c) => isMunicipal(c.id)),
      )}
      ${group(
        t('ballots.regional'),
        shown.filter((c) => !isMunicipal(c.id)),
      )}
    `;
  }

  return html`
    <section class="favourites" aria-labelledby="km-favourites" ref=${section}>
      ${head}
      ${copy === 'failed' && picks.length ? html`<${CopyFailed} link=${link} />` : null}
      ${body}
    </section>
  `;
}
