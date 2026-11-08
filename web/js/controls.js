/* The round buttons floating on the map: those with a small popover
 * (language; the map's layers: constituency boundaries, the ballots' (the
 * overview and the 2026 turnout) and the base map; theme, zoom, and help:
 * a short guide with the disclaimer) and Favourites, which shows the
 * candidates circled.
 *
 * A popover is a non-modal dialog next to its button: opening it moves focus
 * into it; Esc, a click elsewhere or focus leaving it closes it. Only one is
 * open at a time; app.js holds which. A button with a quick action of its
 * own (`onPress`) does that on click and opens its popover on a long press,
 * a right click, ArrowDown or Shift+F10 instead.
 */

import { html, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { useLoaded } from './data.js';
import { elections, formatNumber, lang, languagePage, languages, polls, switchLanguage, t } from './i18n.js';
import {
  ArrowIcon,
  BaseMapIcon,
  CheckIcon,
  ColumnsIcon,
  CountryIcon,
  ExpandIcon,
  EyeIcon,
  GlobeIcon,
  HeartIcon,
  HelpIcon,
  LAYER_ICON,
  LayersIcon,
  Logo,
  MinusIcon,
  MoonIcon,
  PlusIcon,
  SearchIcon,
  SunIcon,
  SystemIcon,
  TurnoutIcon,
} from './icons.js';
import { electionKind, electionLabel, isNational, kindIcon, kindStyle, overviewKind } from './kinds.js';
import { useLive } from './live.js';
import { CONSTITUENCIES, overlaysHere } from './map.js';
import { setMapMode, useMapMode, useTurnoutChoices } from './mapmode.js';
import { CrossedNumber, Guide, Notice, SampleNumber } from './pane.js';

// The legend of an overlay switched on: [swatch class (app.css), string].
const OVERLAY_KEYS = {
  oz: [
    ['council', 'layers.oz_council'],
    ['approximate', 'layers.oz_approximate'],
    // Once the polls have closed, the boundaries not known are not "yet".
    ['pending', Date.now() > polls[1] ? 'layers.oz_pending_past' : 'layers.oz_pending'],
    ['none', 'layers.oz_none'],
  ],
  okrsky: [
    ['okrsok', 'layers.okrsky_border'],
    ['okrsok-approximate', 'layers.okrsky_approximate'],
  ],
};
// Each turnout layer by the overlay icon of its areas, so that the turnout
// menu reads with the constituencies': the municipalities, the two cities,
// the regions.
const TURNOUT_ICON = { municipal: LAYER_ICON.oz, city: LAYER_ICON.city, regional: LAYER_ICON.zsk };
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
 * usePressOrMenu. *badge*, on the icon, shows the button's current state;
 * *on*, a dot, that what the popover sets is in effect. */
function Popover({ name, label, icon, badge, on, open, onToggle, onPress, children }) {
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
    // On screen whatever its content: at most as tall as the screen (app.css,
    // it scrolls past that), and moved up (in the lower column, down) by as
    // much as it would run past the screen's edge beside its button. Again
    // as its content grows or shrinks (a disclosure) and the window resizes.
    const place = () => {
      const edge = parseFloat(getComputedStyle(p).getPropertyValue('--edge'));
      const top = anchor.current.getBoundingClientRect().top + p.offsetTop;
      const shift = Math.min(0, innerHeight - edge - top - p.offsetHeight) || Math.max(0, edge - top);
      p.style.translate = shift ? `0 ${shift}px` : '';
    };
    const resize = new ResizeObserver(place);
    for (const e of [p, ...p.children]) resize.observe(e);
    document.addEventListener('pointerdown', outside);
    addEventListener('resize', place);
    return () => {
      document.removeEventListener('pointerdown', outside);
      removeEventListener('resize', place);
      resize.disconnect();
    };
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
        class=${on ? 'fab on' : 'fab'}
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
        ${badge ? html`<${Badge}>${badge}<//>` : null}
        ${on ? html`<span class="fab-dot" aria-hidden="true"></span>` : null}
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

/* A round button's current state on its icon: a language code, a count. */
const Badge = ({ children }) => html`<span class="fab-badge" aria-hidden="true">${children}</span>`;

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
    ${count ? html`<${Badge}>${formatNumber(count)}<//>` : null}
  </button>`;
}

/* The button opens the menu of every language, each by its own name, the
 * page's marked; choosing one keeps the election (i18n.js `languagePage`)
 * and the hash, so the same place stays selected. ArrowUp and ArrowDown
 * move between the languages. */
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
                href=${`${languagePage(code)}${hash}`}
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

/* A map layer's checkbox row, with the layer's icon. */
const LayerCheck = ({ layer, overlays, onOverlays, children }) => {
  const Icon = LAYER_ICON[layer];
  return html`
    <label class=${`option layer-${layer}`}>
      <input
        type="checkbox"
        value=${layer}
        checked=${overlays[layer]}
        onChange=${(e) => onOverlays({ ...overlays, [layer]: e.currentTarget.checked })}
      />
      <${Icon} />
      <span>${children}</span>
    </label>
  `;
};

/* The map's layers, one button each in one group, each with its popover:
 *
 * - the constituency overlays the election has (map.js `overlaysHere`;
 *   none, no button), each switched on or off on its own; whichever
 *   are on, the map draws each from the zoom where it reads (map.js
 *   `OVERLAYS`). The icons are in the colours their borders are drawn in.
 *   When each appears and the legend of those on are folded under them, so
 *   that the menu stays short (on a phone, on the screen);
 * - the ballots: of an election with an overview (kinds.js
 *   `overviewKind`), the overview shown or not, *overview* {open,
 *   onToggle()}, so that it opens without a place picked first; once there
 *   are 2026 results, the turnouts the election has on the map
 *   (mapmode.js `useTurnoutChoices`), each switched on or off, at most one
 *   at a time, as the map shows one mode. The button is dotted while
 *   either is in effect;
 * - the base map: roads, railways and waters, and buildings, both on by
 *   default.
 *
 * `menu` is the open popover (app.js), `toggle(name)` its onToggle. */
export function LayerMenus({ menu, toggle, overlays, onOverlays, overview }) {
  const { status } = useLive();
  const mode = useMapMode();
  const [here] = useLoaded(overlaysHere, []);
  const choices = useTurnoutChoices();
  const counting = status && status.phase !== 'none';
  const turnouts = counting && choices?.length ? choices : null;
  // The turnout shown, at whatever level the ballots gave it: a contest's
  // or an election's.
  const turnoutOf = (m) => m.contest ?? m.election;
  const chosen = mode?.kind === 'turnout' ? turnouts?.find((c) => turnoutOf(c.mode) === turnoutOf(mode)) : null;
  const constituencies = CONSTITUENCIES.filter((k) => here?.has(k));
  const legend = constituencies.flatMap((k) => (overlays[k] ? (OVERLAY_KEYS[k] ?? []) : []));
  // When each appears: in one sentence where the election has all of them.
  const auto =
    constituencies.length === CONSTITUENCIES.length
      ? t('layers.auto')
      : constituencies.map((k) => t(`layers.auto_${k}`)).join(' ');
  const layers = { overlays, onOverlays };
  // With the overview, the menu is named by both, the turnouts' group by
  // its own legend under the overview.
  let ballotsTitle = t('mapmode.title');
  if (overview) ballotsTitle = t(turnouts ? `mapmode.menu.${overviewKind}` : `overview.title.${overviewKind}`);
  return html`
    <div class="fab-group" role="group" aria-label=${t('layers.group')}>
      ${
        constituencies.length
          ? html`
              <${Popover}
                name="constituencies"
                label=${t('layers.button')}
                icon=${LayersIcon}
                open=${menu === 'constituencies'}
                onToggle=${toggle('constituencies')}
              >
                <${Title} name="constituencies">${t('layers.title')}<//>
                <fieldset class="options">
                  <legend class="sr-only">${t('layers.title')}</legend>
                  ${constituencies.map((k) => html`<${LayerCheck} key=${k} layer=${k} ...${layers}>${t(`layers.${k}`)}<//>`)}
                </fieldset>
                <details class="pop-more">
                  <summary>${t('layers.legend')}<${ExpandIcon} /></summary>
                  <p class="pop-note">${auto}</p>
                  ${
                    legend.length
                      ? html`
                          <div class="notice legend" role="note">
                            ${legend.map(([swatch, key]) => html`<p class="key"><span class=${`swatch ${swatch}`}></span>${t(key)}</p>`)}
                          </div>
                        `
                      : null
                  }
                </details>
              <//>
            `
          : null
      }
      ${
        overview || turnouts
          ? html`
              <${Popover}
                name="turnout"
                label=${overview ? ballotsTitle : t('mapmode.button', { layer: chosen ? chosen.label : t('mapmode.off') })}
                icon=${TurnoutIcon}
                on=${mode?.kind === 'turnout' || overview?.open}
                open=${menu === 'turnout'}
                onToggle=${toggle('turnout')}
              >
                <${Title} name="turnout">${ballotsTitle}<//>
                ${
                  overview
                    ? html`<div class="options">
                        <label class="option">
                          <input type="checkbox" checked=${overview.open} onChange=${overview.onToggle} />
                          <${ColumnsIcon} />
                          <span>${t(`overview.open.${overviewKind}`)}</span>
                        </label>
                      </div>`
                    : null
                }
                ${
                  turnouts
                    ? html`<fieldset class=${overview ? 'options pop-group' : 'options'}>
                        <legend class=${overview ? 'pop-title' : 'sr-only'}>${t('mapmode.title')}</legend>
                        ${turnouts.map(({ mode: next, label }) => {
                          const key = turnoutOf(next);
                          // A turnout of the regular elections by the overlay
                          // of its areas, a country-wide contest's by the
                          // country.
                          const Icon = next.election ? TURNOUT_ICON[next.election] : CountryIcon;
                          return html`
                            <label class=${`option turnout-${next.election ?? 'country'}`} key=${key}>
                              <input
                                type="checkbox"
                                checked=${chosen?.mode === next}
                                onChange=${() => setMapMode(chosen?.mode === next ? null : next)}
                              />
                              <${Icon} />
                              <span>${label}</span>
                            </label>
                          `;
                        })}
                      </fieldset>`
                    : null
                }
              <//>
            `
          : null
      }
      <${Popover}
        name="base"
        label=${t('layers.base_title')}
        icon=${BaseMapIcon}
        open=${menu === 'base'}
        onToggle=${toggle('base')}
      >
        <${Title} name="base">${t('layers.base_title')}<//>
        <fieldset class="options">
          <legend class="sr-only">${t('layers.base_title')}</legend>
          <${LayerCheck} layer="base" ...${layers}>${t('layers.base')}<//>
          <${LayerCheck} layer="buildings" ...${layers}>${t('layers.buildings')}<//>
        </fieldset>
      <//>
    </div>
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

// The year of the oldest election the site shows (as about.js says it).
const SINCE = elections.at(-1).day.slice(0, 4);

/* The title bar's button that opens the list of elections (search.js): the
 * logo with the badge of the page's election's kind. */
const ElectionSample = () => {
  const KindIcon = kindIcon(electionLabel);
  return html`<span class="election-sample" style=${kindStyle(electionLabel)}>
    <${Logo} /><span class="election-badge"><${KindIcon} /></span>
  </span>`;
};

/* What the page offers, a row each (Guide), only those the election has.
 * A referendum's answers are not circled or filtered (ballots.js
 * `AnswerRow`); a country-wide election's candidates carry no party tags
 * (`CandidateRow`). The boundaries row stands for the councils'
 * constituencies: the polling districts alone are a detail. The
 * disclaimer, then the link to the About dialog. */
export function HelpMenu({ open, onToggle, aboutHash, onAbout }) {
  const [here] = useLoaded(overlaysHere, []);
  const candidates = electionKind !== 'referendum';
  const rows = [
    [SearchIcon, t('help.place'), t('help.place_result')],
    candidates && [SampleNumber, t('help.circle'), t('help.circle_result')],
    candidates && [CrossedNumber, t('help.cross'), t('help.cross_result')],
    candidates && [EyeIcon, t(isNational ? 'help.filter_marks' : 'help.filter'), t('help.filter_result')],
    overviewKind && [ColumnsIcon, t(`overview.open.${overviewKind}`), t(`help.overview.${overviewKind}`)],
    ['zsk', 'city', 'oz'].some((k) => here?.has(k)) && [LayersIcon, t('help.layers'), t('help.layers_result')],
    elections.length > 1 && [ElectionSample, t('help.elections'), t('help.elections_result')],
  ].filter(Boolean);
  return html`
    <${Popover} name="help" label=${t('help.open')} icon=${HelpIcon} open=${open} onToggle=${onToggle}>
      <${Title} name="help">${t('app.name')}<//>
      <p>${t('help.lead', { since: SINCE })}</p>
      <${Guide} rows=${rows} />
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

const ZoomButton = ({ label, icon, disabled, onClick }) => html`
  <button type="button" class="fab" aria-label=${label} title=${label} disabled=${disabled} onClick=${onClick}>
    <${icon} />
  </button>
`;

/* Zoom by one level, animated (map.js `zoomIn`). */
export function ZoomButtons({ map, limits }) {
  return html`
    <div class="fab-group" role="group" aria-label=${t('map.zoom')}>
      <${ZoomButton}
        label=${t('map.zoom_in')}
        icon=${PlusIcon}
        disabled=${!limits.canZoomIn}
        onClick=${() => map?.zoomIn()}
      />
      <${ZoomButton}
        label=${t('map.zoom_out')}
        icon=${MinusIcon}
        disabled=${!limits.canZoomOut}
        onClick=${() => map?.zoomOut()}
      />
    </div>
  `;
}
