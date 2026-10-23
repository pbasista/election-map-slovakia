/* The round buttons floating on the map: those with a small popover
 * (language, boundaries, theme, zoom, and help with the disclaimer) and
 * Favourites, which shows the candidates circled.
 *
 * A popover is a non-modal dialog next to its button: opening it moves focus
 * into it; Esc, a click elsewhere or focus leaving it closes it. Only one is
 * open at a time; app.js holds which. A button with a quick action of its
 * own (`onPress`) does that on click and opens its popover on a long press,
 * a right click, ArrowDown or Shift+F10 instead.
 */

import { html, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { formatNumber, lang, languages, switchLanguage, t } from './i18n.js';
import {
  ArrowIcon,
  CheckIcon,
  GlobeIcon,
  HeartIcon,
  HelpIcon,
  LAYER_ICON,
  LayersIcon,
  MinusIcon,
  MoonIcon,
  PlusIcon,
  SunIcon,
  SystemIcon,
} from './icons.js';
import { Notice } from './pane.js';

// Broadest first.
const OVERLAYS = ['zsk', 'city', 'oz'];
const THEME_ICON = { system: SystemIcon, light: SunIcon, dark: MoonIcon };

// A held press opens the menu after this long, as a touch context menu does.
const HOLD_MS = 500;
// How far a held pointer may wander before it is a drag rather than a hold.
const HOLD_SLOP = 10;

/* Props for a button whose click, Enter or Space does `onPress()` and whose
 * long press, right click, ArrowDown or Shift+F10 (or the ContextMenu key,
 * which browsers deliver as a right click) does `onMenu()`. A long press
 * swallows the click that ends it. */
function usePressOrMenu(onPress, onMenu) {
  // The primary press in progress or just ended: { timer, x, y, held }.
  const press = useRef(null);
  const stop = () => clearTimeout(press.current?.timer);
  useEffect(() => stop, []);

  return {
    onPointerDown: (e) => {
      stop();
      if (e.button !== 0) {
        press.current = null;
        return;
      }
      const p = { x: e.clientX, y: e.clientY, held: false };
      p.timer = setTimeout(() => {
        p.held = true;
        onMenu();
      }, HOLD_MS);
      press.current = p;
    },
    onPointerMove: (e) => {
      const p = press.current;
      if (p && Math.hypot(e.clientX - p.x, e.clientY - p.y) > HOLD_SLOP) stop();
    },
    onPointerUp: stop,
    onPointerCancel: stop,
    onPointerLeave: stop,
    onClick: (e) => {
      const p = press.current;
      press.current = null;
      // `detail` is 0 for Enter and Space, which no hold can precede.
      if (p?.held && e.detail) return;
      onPress();
    },
    onContextMenu: (e) => {
      // No native menu (nor, on touch, the long-press callout) on the button.
      e.preventDefault();
      stop();
      // A touch hold may raise this before the timer: it still is a hold.
      if (press.current) press.current.held = true;
      onMenu();
    },
    onKeyDown: (e) => {
      if (e.key !== 'ArrowDown' && !(e.key === 'F10' && e.shiftKey)) return;
      e.preventDefault();
      onMenu();
    },
  };
}

/* A button and the popover it opens. `onToggle(open)`; with `onPress`, see
 * usePressOrMenu. *badge*, on the icon, shows the button's current state. */
function Popover({ name, label, icon, badge, open, onToggle, onPress, children }) {
  const anchor = useRef(null);
  const button = useRef(null);
  const panel = useRef(null);
  const pressOrMenu = usePressOrMenu(onPress, () => onToggle(true));

  useEffect(() => {
    if (!open) return;
    const p = panel.current;
    (p.querySelector(':checked, [aria-current="true"]') ?? p.querySelector('a, button') ?? p).focus();
    const outside = (e) => {
      if (!anchor.current.contains(e.target)) onToggle(false);
    };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);

  return html`
    <div
      class="anchor"
      ref=${anchor}
      onfocusout=${(e) => {
        // Lower case: this Preact passes the name on as written unless the
        // element has an `on…` property for it, which focusout has not.
        if (open && e.relatedTarget && !anchor.current.contains(e.relatedTarget)) onToggle(false);
      }}
      onKeyDown=${(e) => {
        if (e.key !== 'Escape' || !open) return;
        // Handled: app.js would close the pane as well.
        e.preventDefault();
        onToggle(false);
        button.current.focus();
      }}
    >
      <button
        type="button"
        class="fab"
        ref=${button}
        id=${`km-${name}-button`}
        aria-label=${label}
        title=${label}
        aria-expanded=${open}
        aria-controls=${`km-${name}`}
        aria-haspopup="dialog"
        ...${onPress ? pressOrMenu : { onClick: () => onToggle(!open) }}
      >
        <${icon} />
        ${badge ? html`<span class="fab-badge" aria-hidden="true">${badge}</span>` : null}
      </button>
      ${
        open
          ? html`<div
              class="popover"
              id=${`km-${name}`}
              role="dialog"
              aria-labelledby=${`km-${name}-title`}
              tabindex="-1"
              ref=${panel}
            >
              ${children}
            </div>`
          : null
      }
    </div>
  `;
}

const Title = ({ name, children }) => html`<h2 class="pop-title" id=${`km-${name}-title`}>${children}</h2>`;

/* Shows and hides Favourites (favourites.js), with how many are circled on
 * it once there are some. Pressed while they are shown. */
export function FavouritesButton({ count, open, onPress }) {
  const label = t('favourites.open', { n: formatNumber(count) });
  return html`<button
    type="button"
    class="fab"
    aria-label=${label}
    title=${label}
    aria-pressed=${open ? 'true' : 'false'}
    onClick=${onPress}
  >
    <${HeartIcon} />
    ${count ? html`<span class="fab-badge" aria-hidden="true">${formatNumber(count)}</span>` : null}
  </button>`;
}

/* The button opens the menu of every language, each by its own name, the
 * page's marked; choosing one keeps the hash, so the same place stays
 * selected. ArrowUp and ArrowDown move between the languages. */
export function LanguageMenu({ open, onToggle, hash }) {
  const current = languages.find(([code]) => code === lang)[1];
  const onKeyDown = (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const options = [...e.currentTarget.querySelectorAll('.option')];
    const at = options.indexOf(document.activeElement);
    const step = e.key === 'ArrowDown' ? 1 : -1;
    options[(at + step + options.length) % options.length].focus();
  };
  return html`
    <${Popover}
      name="language"
      label=${t('nav.switch', { current })}
      icon=${GlobeIcon}
      badge=${lang.toUpperCase()}
      open=${open}
      onToggle=${onToggle}
    >
      <${Title} name="language">${t('nav.language')}<//>
      <ul class="options" onKeyDown=${onKeyDown}>
        ${languages.map(
          ([code, name]) => html`
            <li key=${code}>
              <a
                class="option"
                href=${`/${code}/${hash}`}
                hreflang=${code}
                lang=${code}
                aria-current=${code === lang ? 'true' : undefined}
                onClick=${(e) => {
                  e.preventDefault();
                  switchLanguage(code);
                }}
              >
                <span class="grow">${name}</span>
                ${code === lang ? html`<${CheckIcon} />` : null}
              </a>
            </li>
          `,
        )}
      </ul>
    <//>
  `;
}

/* The constituency overlays, each switched on or off on its own; whichever
 * are on, the map draws each from the zoom where it reads (map.js
 * `OVERLAYS`). The icons are in the colours their borders are drawn in. */
export function LayerMenu({ open, onToggle, overlays, onOverlays }) {
  return html`
    <${Popover} name="layers" label=${t('layers.button')} icon=${LayersIcon} open=${open} onToggle=${onToggle}>
      <${Title} name="layers">${t('layers.title')}<//>
      <fieldset class="options">
        <legend class="sr-only">${t('layers.title')}</legend>
        ${OVERLAYS.map((k) => {
          const Icon = LAYER_ICON[k];
          return html`
            <label class=${`option layer-${k}`} key=${k}>
              <input
                type="checkbox"
                value=${k}
                checked=${overlays[k]}
                onChange=${(e) => onOverlays({ ...overlays, [k]: e.currentTarget.checked })}
              />
              <${Icon} />
              <span>${t(`layers.${k}`)}</span>
            </label>
          `;
        })}
      </fieldset>
      <p class="pop-note">${t('layers.auto')}</p>
      ${
        overlays.oz
          ? html`
              <div class="notice legend" role="note">
                <p class="key"><span class="swatch council"></span>${t('layers.oz_council')}</p>
                <p class="key"><span class="swatch approximate"></span>${t('layers.oz_approximate')}</p>
                <p class="key"><span class="swatch pending"></span>${t('layers.oz_pending')}</p>
                <p class="key"><span class="swatch none"></span>${t('layers.oz_none')}</p>
              </div>
            `
          : null
      }
    <//>
  `;
}

/* The button cycles the theme (theme.js `cycle`); its menu picks one. */
export function ThemeMenu({ open, onToggle }) {
  const [mode, setMode] = useState(() => globalThis.emsTheme.mode);
  return html`
    <${Popover}
      name="theme"
      label=${t('theme.button', { mode: t(`theme.${mode}`) })}
      icon=${THEME_ICON[mode]}
      open=${open}
      onToggle=${onToggle}
      onPress=${() => setMode(globalThis.emsTheme.cycle())}
    >
      <${Title} name="theme">${t('theme.title')}<//>
      <fieldset class="options">
        <legend class="sr-only">${t('theme.title')}</legend>
        ${globalThis.emsTheme.modes.map((m) => {
          const Icon = THEME_ICON[m];
          return html`
            <label class="option" key=${m}>
              <input
                type="radio"
                name="km-theme"
                value=${m}
                checked=${mode === m}
                onChange=${() => {
                  globalThis.emsTheme.set(m);
                  setMode(m);
                }}
              />
              <${Icon} />
              <span>${t(`theme.${m}`)}</span>
            </label>
          `;
        })}
      </fieldset>
    <//>
  `;
}

export function HelpMenu({ open, onToggle, aboutHash, onAbout }) {
  return html`
    <${Popover} name="help" label=${t('help.open')} icon=${HelpIcon} open=${open} onToggle=${onToggle}>
      <${Title} name="help">${t('app.name')}<//>
      <p>${t('help.how')}</p>
      <${Notice}>${t('disclaimer.short')}<//>
      <a
        class="more"
        href=${aboutHash}
        onClick=${(e) => {
          e.preventDefault();
          onAbout();
        }}
      >
        ${t('disclaimer.more')}<${ArrowIcon} />
      </a>
    <//>
  `;
}

/* Zoom by one level, animated (map.js `zoomIn`). */
export function ZoomButtons({ map, limits }) {
  return html`
    <div class="zoom" role="group" aria-label=${t('map.zoom')}>
      <button
        type="button"
        class="fab"
        aria-label=${t('map.zoom_in')}
        title=${t('map.zoom_in')}
        disabled=${!limits.canZoomIn}
        onClick=${() => map?.zoomIn()}
      >
        <${PlusIcon} />
      </button>
      <button
        type="button"
        class="fab"
        aria-label=${t('map.zoom_out')}
        title=${t('map.zoom_out')}
        disabled=${!limits.canZoomOut}
        onClick=${() => map?.zoomOut()}
      >
        <${MinusIcon} />
      </button>
    </div>
  `;
}
