/* Favourites: every candidate the visitor has circled, on whichever
 * ballots, by contest, municipal then regional, the contests in the order
 * their first candidate was circled. A contest is listed as on the
 * candidate card: closed, just the circled candidates; opened by its
 * header, the others after them, the filter applying to those only. The
 * page's address holds the circles and the filter (app.js); buttons by the
 * title copy a link to them alone, without the place shown on the map, or
 * show it as a QR code for another device's camera.
 *
 * On a wide screen the list is a panel of its own beside the pane, as wide
 * as the page allows, so that the pane keeps the ballots or the card of a
 * candidate chosen here; on a narrower one the pane shows it (app.js). */

import { html, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { Contest, FilterBar, isMunicipal, useRowActions } from './ballots.js';
import { contests, useLoaded } from './data.js';
import { formatNumber, t } from './i18n.js';
import { BackIcon, CheckIcon, CloseIcon, LinkIcon, QrIcon } from './icons.js';
import { decodeResults, NOT_COUNTED, useLive } from './live.js';
import { byContest } from './picks.js';

// How long the button says that it has copied the link.
const COPIED_MS = 2500;

/* The button that copies *link*, an icon by the title. *state* and
 * `onState(next)`: whether it has, null, 'copied' or 'failed' (CopyFailed). */
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

/* Where the browser does not let the page write to the clipboard, the
 * link, selected, to copy by hand. */
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

/* The button that opens the QR code dialog (QrDialog): `onOpen()`. */
function QrButton({ onOpen }) {
  const label = t('favourites.qr');
  return html`<button type="button" class="share-button" title=${label} aria-label=${label} aria-haspopup="dialog" onClick=${onOpen}>
    <${QrIcon} />
  </button>`;
}

/* The error correction levels to try, most robust first: M recovers a
 * code partly hidden by glare on a screen; L holds the longest links. */
const QR_LEVELS = ['M', 'L'];

/* The modules of *text* as a QR code (the encoder's object), the version
 * the smallest that holds it; null where the text is too long for any. */
function encodeQr(qrcode, text) {
  for (const level of QR_LEVELS) {
    try {
      const code = qrcode(0, level);
      code.addData(text);
      code.make();
      return code;
    } catch {
      // Too long at this level: the next holds more.
    }
  }
  return null;
}

/* The quiet zone around a code that the standard asks for, in modules. */
const QUIET = 4;

/* *link* as a QR code: one path, each row's runs of dark modules a
 * rectangle, dark on white whatever the theme, as scanners expect. The
 * encoder is loaded only once a code is asked for. */
function QrCode({ link }) {
  const [lib, failed] = useLoaded(() => import('../vendor/qrcode-generator.module.js'), []);
  if (failed) return html`<p class="error">${t('error.load')}</p>`;
  if (!lib) return html`<p class="muted loading">${t('panel.loading')}</p>`;
  const code = encodeQr(lib.qrcode, link);
  if (!code) return html`<p class="muted">${t('favourites.qr_too_long')}</p>`;
  const n = code.getModuleCount();
  let d = '';
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      if (!code.isDark(r, c)) continue;
      const start = c;
      while (c + 1 < n && code.isDark(r, c + 1)) c++;
      d += `M${start + QUIET} ${r + QUIET}h${c - start + 1}v1H${start + QUIET}z`;
    }
  }
  const size = n + 2 * QUIET;
  return html`<svg class="qr" viewBox=${`0 0 ${size} ${size}`} role="img" aria-label=${t('favourites.qr_label')} shape-rendering="crispEdges">
    <rect width=${size} height=${size} fill="#fff" />
    <path d=${d} fill="#000" />
  </svg>`;
}

/* The QR code of *link* in a modal dialog over the page, as large as the
 * screen allows, for another device's camera to read from across a table;
 * it does not push the list down. Esc, the close button or a click on the
 * backdrop close it (`onClose()`), and focus goes back to the button that
 * opened it. It follows the link as it changes. */
function QrDialog({ link, onClose }) {
  const dialog = useRef(null);
  useEffect(() => {
    const d = dialog.current;
    const before = document.activeElement;
    d.showModal();
    return () => {
      if (d.open) d.close();
      if (before?.isConnected) before.focus();
    };
  }, []);
  return html`<dialog
    class="qr-dialog"
    ref=${dialog}
    aria-labelledby="km-qr-title"
    onClose=${onClose}
    onClick=${(e) => {
      if (e.target === dialog.current) dialog.current.close();
    }}
    onKeyDown=${(e) => {
      // Esc closes the dialog alone, not Favourites behind it (app.js).
      if (e.key === 'Escape') e.stopPropagation();
    }}
  >
    <header class="qr-head">
      <h2 id="km-qr-title">${t('favourites.qr_title')}</h2>
      <button type="button" class="close" aria-label=${t('panel.close')} title=${t('panel.close')} onClick=${() => dialog.current.close()}>
        <${CloseIcon} />
      </button>
    </header>
    <${QrCode} link=${link} />
    <p class="muted">${t('favourites.qr_caption')}</p>
  </dialog>`;
}

/* The list of favourites.
 * - picks and `onPicks(next)`: the circled candidates (picks.js); filter
 *   and `onFilter(next)`: the candidate filter (ballots.js); link: the
 *   link to share them by.
 * - onBack(): where given, goes back to what the pane showed before.
 * - focus: the candidacy whose card was just left; its row takes the
 *   focus, else the title does once the list is in. */
export function Favourites({ picks, onPicks, filter, onFilter, onCandidate, onBack, focus, link }) {
  // The contests listed since the list opened: one whose circles are all
  // taken off stays, so that they can be put back.
  const seen = useRef([]);
  for (const id of byContest(picks).keys()) if (!seen.current.includes(id)) seen.current.push(id);
  const ids = seen.current;
  const [result, failed] = useLoaded(() => contests(ids), [ids.join(',')]);
  const [copy, setCopy] = useState(null);
  const [qr, setQr] = useState(false);
  const heading = useRef(null);
  const section = useRef(null);
  const focused = useRef(false);
  const rowFocused = useRef(null);
  const list = result ?? [];
  const actions = useRowActions(
    section,
    new Map(list.flatMap((c) => c.candidates.map((x) => [x.id, x]))),
    filter,
    onFilter,
    picks,
    onPicks,
  );
  // How many of the circled the 2026 results have elected so far.
  const live = useLive();
  let elected = 0;
  for (const c of list) {
    const entry = live.of(c.id);
    if (!entry || entry === NOT_COUNTED) continue;
    const { byNumber } = decodeResults(c, entry);
    elected += c.candidates.filter((x) => actions.isPicked(x.id) && byNumber.get(x.number)?.elected).length;
  }

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
        ${
          picks.length
            ? html`<${CopyLink} link=${link} state=${copy} onState=${setCopy} />
                <${QrButton} onOpen=${() => setQr(true)} />`
            : null
        }
      </div>
      ${
        picks.length
          ? html`<p class="muted">
              ${t('favourites.count', { n: formatNumber(picks.length) })}
              ${elected ? html` · <span class="favourites-elected">${t('favourites.elected', { n: formatNumber(elected) })}</span>` : null}
            </p>`
          : null
      }
    </div>
  </header>`;

  let body;
  if (!ids.length) body = html`<p class="panel-body intro">${t('favourites.empty')}</p>`;
  else if (failed) body = html`<p class="panel-body error">${t('error.load')}</p>`;
  else if (!result) body = html`<p class="panel-body muted loading">${t('panel.loading')}</p>`;
  else {
    const byId = new Map(list.map((c) => [c.id, c]));
    const shown = ids.map((id) => byId.get(id)).filter((c) => c?.candidates.length);
    const group = (title, members) =>
      members.length
        ? html`<h3 class="group">${title}</h3>
            <div class="favourite-contests">
              ${members.map(
                (c) => html`<${Contest}
                  key=${c.id}
                  contest=${c}
                  pin
                  onCandidate=${onCandidate}
                  filter=${filter}
                  actions=${actions}
                />`,
              )}
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
      ${qr && picks.length ? html`<${QrDialog} link=${link} onClose=${() => setQr(false)} />` : null}
      ${body}
    </section>
  `;
}
