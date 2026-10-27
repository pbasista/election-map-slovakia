/* The pane with a place's ballots or a candidate card, the About dialog, and
 * the warning notices shown in the pane and the help popover.
 *
 * The pane floats beside the map on wide screens and is a bottom sheet on
 * phones (app.css) at one of three heights (SNAPS): `peek`, its grip, the
 * legend of the results on the map (mapmode.js) and the first row of the
 * content, `half` and `full`, up to just under the search card. Dragged
 * from its grip or the legend, or from the content when that is scrolled to
 * the top, it follows the finger and settles at the nearest height, or the
 * next one a flick goes to; dragged down from `peek`, it closes. The grip
 * is a button that steps through the heights.
 */

import { html, useCallback, useEffect, useLayoutEffect, useRef } from '../vendor/preact-htm.module.js';
import { About } from './about.js';
import { t } from './i18n.js';
import { CloseIcon, WarningIcon } from './icons.js';

/* Something the visitor should heed before relying on what follows. */
export const Notice = ({ children }) => html`
  <div class="notice" role="note"><${WarningIcon} /><div>${children}</div></div>
`;

export const PHONE = matchMedia('(max-width: 640px)');
/* Wide enough for a second pane beside the first (Favourites, app.js), as
 * the search results go beside the pane (app.css). */
export const WIDE = matchMedia('(min-width: 960px)');
// Pixels, or pixels per ms, down past `peek` that close the sheet when let
// go; a stroke as fast and at least STROKE long goes to the next height.
const SWIPE_DISTANCE = 96;
const SWIPE_SPEED = 0.5;
const STROKE = 24;

/* The sheet's heights, lowest first (app.js holds the current one). */
export const SNAPS = ['peek', 'half', 'full'];
// `half`, of the screen's height.
const HALF = 0.58;
// `peek`: at least PEEK high, and under the grip and the legend a row of
// the content PEEK_ROW high (the place's name, the candidate's).
const PEEK = 112;
const PEEK_ROW = 34;
// `full`: the gap left under the search card.
const FULL_GAP = 10;

/* The sheet's heights in pixels, {peek, half, full}, each including the
 * inset at the foot of the screen (the sheet's bottom padding). *top* is
 * the slot over the content that holds the legend. */
function heightsOf(sheet, top) {
  const safe = Number.parseFloat(getComputedStyle(sheet).paddingBottom) || 0;
  const grip = sheet.querySelector('.pane-grip').offsetHeight;
  const card = sheet.parentElement.querySelector('.finder').getBoundingClientRect().bottom;
  const peek = Math.round(Math.max(PEEK, grip + top.offsetHeight + PEEK_ROW) + safe);
  const full = Math.max(peek, Math.round(innerHeight - card - FULL_GAP));
  return { peek, half: Math.min(full, Math.max(peek, Math.round(innerHeight * HALF))), full };
}

/* Where a stroke settles that lets go of the sheet at *h* pixels high after
 * moving it *dy* pixels down (negative: up) at *speed* pixels per ms: a
 * flick goes to the next height in its direction, any other stroke to the
 * nearest; null closes the sheet. */
function settle(heights, h, dy, speed) {
  const below = heights.peek - h;
  if (below > SWIPE_DISTANCE || (below > STROKE && speed > SWIPE_SPEED)) return null;
  if (Math.abs(dy) > STROKE && Math.abs(speed) > SWIPE_SPEED) {
    const next = speed > 0 ? SNAPS.findLast((s) => heights[s] < h) : SNAPS.find((s) => heights[s] > h);
    return next ?? (speed > 0 ? 'peek' : 'full');
  }
  return SNAPS.reduce((a, b) => (Math.abs(heights[b] - h) < Math.abs(heights[a] - h) ? b : a));
}

/* *label* names the pane for screen readers; *beside* is the pane beside
 * the left column, which only wide screens have room for (app.css). On a
 * phone the sheet is *snap* high (SNAPS), which `onSnap(next)` changes;
 * *topRef* gets the slot over the content that the legend goes in
 * (mapmode.js `MapResults`). The height in pixels is app.css
 * `--sheet-height`, which app.js `insets` reads too. */
export function Pane({
  paneRef,
  onClose,
  label = t('panel.label'),
  beside = false,
  snap = 'half',
  onSnap,
  topRef,
  children,
}) {
  const body = useRef(null);
  const top = useRef(null);
  const drag = useRef(null);
  const current = useRef(snap);
  current.current = snap;
  // Set once: a new callback each render would be called again each time.
  const topSlot = useCallback((el) => {
    top.current = el;
    topRef?.(el);
  }, []);

  const sheet = () => paneRef.current;

  /* Beside the map the pane is as tall as its content, so the placeholder
   * of content still loading (`.loading`: the ballots, a candidate card)
   * would shrink it for a moment and flash the map behind. Its height is
   * held until the content is in: the resize observer knows the last height
   * shown, and the mutation observer, running before the next paint, holds
   * it as the placeholder comes in. */
  useEffect(() => {
    const s = sheet();
    let shown = 0;
    const resize = new ResizeObserver(() => {
      shown = s.offsetHeight;
    });
    const mutate = new MutationObserver(() => {
      const hold = !PHONE.matches && shown && body.current.querySelector('.loading');
      s.style.minHeight = hold ? `${shown}px` : '';
    });
    resize.observe(s);
    mutate.observe(body.current, { childList: true, subtree: true });
    return () => {
      resize.disconnect();
      mutate.disconnect();
    };
  }, []);

  /* Sets app.css `--sheet-height` to the height of *snap* now; the heights
   * {peek, half, full}. */
  function place() {
    const heights = heightsOf(sheet(), top.current);
    document.documentElement.style.setProperty('--sheet-height', `${heights[current.current]}px`);
    return heights;
  }

  useLayoutEffect(() => {
    if (!beside) place();
  }, [snap]);

  // The heights follow the screen, the search card and the legend.
  useEffect(() => {
    if (beside) return undefined;
    const resize = new ResizeObserver(() => place());
    resize.observe(top.current);
    resize.observe(sheet().parentElement.querySelector('.finder'));
    addEventListener('resize', place);
    return () => {
      resize.disconnect();
      removeEventListener('resize', place);
    };
  }, []);

  function onTouchStart(e) {
    // Zoomed in, a stroke pans the page instead (and a pinch zooms it).
    if (beside || !PHONE.matches || e.touches.length !== 1 || visualViewport.scale > 1) return;
    const fromContent = body.current.contains(e.target);
    if (fromContent && body.current.scrollTop > 0) return;
    // A long press in a text field selects its text, and moving the finger
    // then moves the selection, not the sheet.
    if (e.target.closest('input, textarea')) return;
    const { clientX: x, clientY: y } = e.touches[0];
    drag.current = { x, y, time: e.timeStamp, dy: 0, moved: false, fromContent, from: sheet().offsetHeight, heights: place() };
  }

  function onTouchMove(e) {
    const d = drag.current;
    if (!d) return;
    const { clientX, clientY } = e.touches[0];
    d.dy = clientY - d.y;
    if (!d.moved) {
      // A sideways stroke scrolls the legend's candidates; an upward one on
      // the content of the sheet at full height scrolls the content.
      const sideways = Math.abs(clientX - d.x) > Math.abs(d.dy);
      if (sideways || (d.fromContent && d.dy < 0 && current.current === 'full')) {
        drag.current = null;
        return;
      }
      d.moved = true;
      sheet().classList.add('dragging');
    }
    e.preventDefault();
    // Below `peek` the sheet slides down whole, on its way to closing.
    const h = d.from - d.dy;
    const { peek, full } = d.heights;
    const s = sheet();
    s.style.height = `${Math.min(full, Math.max(peek, h))}px`;
    s.style.transform = h < peek ? `translateY(${peek - h}px)` : '';
  }

  function onTouchEnd(e) {
    const d = drag.current;
    drag.current = null;
    // A tap: the grip's or the content's click does what it does.
    if (!d?.moved) return;
    const speed = d.dy / Math.max(1, e.timeStamp - d.time);
    const next = settle(d.heights, d.from - d.dy, d.dy, speed);
    if (next === null) {
      onClose();
      return;
    }
    // From where it was let go to the height's (app.css transition).
    const s = sheet();
    s.classList.remove('dragging');
    s.style.height = '';
    s.style.transform = '';
    if (next !== current.current) onSnap(next);
  }

  // At `peek` the content shows its first row only, and is inert: a tap on
  // it goes to the sheet, and raises it rather than doing what it would.
  const peek = !beside && snap === 'peek' && PHONE.matches;
  const classes = ['pane', beside ? 'beside' : `sheet-${snap}`];
  const gripLabel = t(snap === 'full' ? 'panel.lower' : 'panel.raise');
  return html`
    <aside
      class=${classes.join(' ')}
      ref=${paneRef}
      aria-label=${label}
      onTouchStart=${onTouchStart}
      onTouchMove=${onTouchMove}
      onTouchEnd=${onTouchEnd}
      onTouchCancel=${onTouchEnd}
      onClick=${(e) => {
        if (peek && e.target === e.currentTarget) onSnap('half');
      }}
    >
      ${
        beside
          ? null
          : html`<button
              type="button"
              class="pane-grip"
              aria-label=${gripLabel}
              title=${gripLabel}
              aria-expanded=${snap === 'full' ? 'true' : 'false'}
              onClick=${() => onSnap(SNAPS[(SNAPS.indexOf(snap) + 1) % SNAPS.length])}
            ></button>
            <div class="pane-top" ref=${topSlot}></div>`
      }
      <button
        type="button"
        class="close"
        aria-label=${t('panel.close')}
        title=${t('panel.close')}
        onClick=${onClose}
      >
        <${CloseIcon} />
      </button>
      <div class="pane-body" ref=${body} inert=${peek}>${children}</div>
    </aside>
  `;
}

/* The About text in a modal dialog: the browser keeps focus inside, Esc and
 * a click on the backdrop close it, and focus goes back where it was. The
 * section props are About's (about.js). */
export function AboutDialog({ section, sectionHash, onSection, onClose }) {
  const dialog = useRef(null);
  // Set when the app closes the dialog (Back), which must not navigate again.
  const unmounting = useRef(false);

  useEffect(() => {
    const d = dialog.current;
    const before = document.activeElement;
    d.showModal();
    return () => {
      unmounting.current = true;
      if (d.open) d.close();
      // Opened from the help popover, which is gone by now, or from a link:
      // the help button is where the About text lives.
      const back = before?.isConnected && before !== document.body ? before : null;
      (back ?? document.getElementById('km-help-button'))?.focus();
    };
  }, []);

  return html`
    <dialog
      class="about-dialog"
      ref=${dialog}
      aria-labelledby="km-about"
      onClose=${() => {
        if (!unmounting.current) onClose();
      }}
      onClick=${(e) => {
        if (e.target === dialog.current) dialog.current.close();
      }}
    >
      <${About}
        section=${section}
        sectionHash=${sectionHash}
        onSection=${onSection}
        onClose=${() => dialog.current.close()}
      />
    </dialog>
  `;
}
