/* The pane with a place's ballots or a candidate card, the About dialog, and
 * the warning notices shown in the pane and the help popover.
 *
 * The pane floats beside the map on wide screens and is a bottom sheet on
 * phones (app.css), where a swipe down closes it: from its grip, or from the
 * content when that is scrolled to the top.
 */

import { html, useEffect, useRef } from '../vendor/preact-htm.module.js';
import { About } from './about.js';
import { t } from './i18n.js';
import { CloseIcon, WarningIcon } from './icons.js';

/* Something the visitor should heed before relying on what follows. */
export const Notice = ({ children }) => html`
  <div class="notice" role="note"><${WarningIcon} /><div>${children}</div></div>
`;

export const PHONE = matchMedia('(max-width: 640px)');
// Pixels down, or pixels per ms, that close the sheet when let go.
const SWIPE_DISTANCE = 96;
const SWIPE_SPEED = 0.5;

export function Pane({ paneRef, onClose, children }) {
  const body = useRef(null);
  const drag = useRef(null);

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

  function onTouchStart(e) {
    // Zoomed in, a stroke pans the page instead (and a pinch zooms it).
    if (!PHONE.matches || e.touches.length !== 1 || visualViewport.scale > 1) return;
    const fromGrip = Boolean(e.target.closest('.pane-grip'));
    if (!fromGrip && body.current.scrollTop > 0) return;
    drag.current = { y: e.touches[0].clientY, time: e.timeStamp, dy: 0, fromGrip };
  }

  function onTouchMove(e) {
    const d = drag.current;
    if (!d) return;
    d.dy = e.touches[0].clientY - d.y;
    if (d.dy <= 0) {
      sheet().style.transform = '';
      // An upward stroke on the content scrolls it.
      if (!d.fromGrip) drag.current = null;
      return;
    }
    e.preventDefault();
    sheet().style.transform = `translateY(${d.dy}px)`;
  }

  function onTouchEnd(e) {
    const d = drag.current;
    drag.current = null;
    // A tap, or a stroke that came back up, left the sheet where it was.
    if (!d || d.dy <= 0) return;
    const speed = d.dy / Math.max(1, e.timeStamp - d.time);
    if (d.dy > SWIPE_DISTANCE || (d.dy > 24 && speed > SWIPE_SPEED)) {
      onClose();
      return;
    }
    const s = sheet();
    s.classList.add('settling');
    s.style.transform = '';
    s.addEventListener('transitionend', () => s.classList.remove('settling'), { once: true });
  }

  return html`
    <aside
      class="pane"
      ref=${paneRef}
      aria-label=${t('panel.label')}
      onTouchStart=${onTouchStart}
      onTouchMove=${onTouchMove}
      onTouchEnd=${onTouchEnd}
      onTouchCancel=${onTouchEnd}
    >
      <div class="pane-grip" aria-hidden="true"></div>
      <button
        type="button"
        class="close"
        aria-label=${t('panel.close')}
        title=${t('panel.close')}
        onClick=${onClose}
      >
        <${CloseIcon} />
      </button>
      <div class="pane-body" ref=${body}>${children}</div>
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
