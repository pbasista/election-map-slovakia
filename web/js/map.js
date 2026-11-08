/* The map: Leaflet for the view (pan, zoom, events), no tile layer, and one
 * canvas showing what the renderer (draw.js) drew of it.
 *
 * The page's main thread only follows the user. The renderer runs in a
 * worker (render.js): every file it fetches and decodes and every pixel it
 * draws is off this thread, so input is handled and frames are composited
 * however long a drawing takes. A finished drawing comes as an ImageBitmap
 * and is shown by handing it to the canvas (copying it in, in Firefox:
 * `COPY_DRAWINGS`), at the transform that puts it where its view is.
 * Nothing else is drawn on the page: a tooltip is an element over the map
 * (`hoverTooltip`). Meanwhile the canvas follows a move or zoom by CSS
 * transform, as Leaflet's own canvases do, which the compositor applies
 * (with the GPU where there is one) without a redraw.
 *
 * A drawing covers the view and PAD of it on every side. While a zoom goes
 * on, the view of the moment is drawn as a draft (DRAFT_RATIO canvas pixels
 * per CSS pixel: a quarter of the pixels on a sharp screen) whenever the
 * one asked for last no longer serves (`stale`): less than half its margin
 * is left on a side, or the zoom has gone ZOOM_SLACK from its own or to
 * another level. A pan is drawn again as it goes, sharp, or as a draft
 * where sharp drawings are slow (`PAN_DRAFT_MS`). A view goes to the
 * renderer only once the one before has come back drawn and the frame
 * that shows it has begun, so it never falls behind with views nobody
 * will see. Where the move or zoom ends, the view is drawn at full
 * sharpness. Nothing is drawn while Leaflet animates a zoom by CSS
 * transition (fitBounds, setView): the canvas is in the middle of that, and
 * the transition's end draws.
 *
 * The renderer never makes a drawing wait for data: it draws what has
 * loaded, and again as more comes. Clicks and the box of an obec to fit
 * the view to are its to answer too: it has the geometry. Without
 * OffscreenCanvas (Safari before 16.4) it runs on the page the same way,
 * on a canvas element. Colours come from the theme (app.css `--map-*`); a
 * theme change redraws. The 2026 results (mapmode.js) go to the renderer
 * as they change, which colours the land by them (`setResults`), and so
 * does the level the ballots show them at, whose unit of the selected
 * place it outlines (`setLevel`).
 */

import { html, render } from '../vendor/preact-htm.module.js';
import { dataIndex, electsAnywhere, getJSON, hasCouncilObvody, heldObce, obecInfo } from './data.js';
import { dataUrl, fetchJSON } from './files.js';
import { credits, dataSource, formatAsOf, stringsUnder, t } from './i18n.js';
import { InfoIcon } from './icons.js';
import { SERIES, STEPS } from './mapmode.js';
import { Z0 } from './topo.js';
import { dragAfterPinch, smoothZoom } from './zoom.js';

const L = globalThis.L;

/* Leaflet copies every enumerable field of a click (into the "preclick" it
 * fires first, and of a tap into a double click), and reading Firefox's
 * deprecated MouseEvent.mozPressure and mozInputSource logs a warning each
 * time. Made non-enumerable, they stay readable but are not copied. */
for (const name of ['mozPressure', 'mozInputSource']) {
  const field = Object.getOwnPropertyDescriptor(MouseEvent.prototype, name);
  if (field?.enumerable) Object.defineProperty(MouseEvent.prototype, name, { ...field, enumerable: false });
}

const SLOVAKIA = [
  [47.73, 16.83],
  [49.61, 22.57],
];
// Unless the view is too large for the countries drawn around (see
// `limitZoomOut`).
const MIN_ZOOM = 6;
// Share of the view added around it when loading shards and drawing, so a
// pan shows the map around until it is drawn again. Less would save
// pixels to draw, copy and upload (0.15: a quarter of them), but a brisk
// fling (3000 px/s) outruns the drawings: measured at 1920 × 1080 and
// 2560 × 1440 at 2 a pixel on an M1, the canvas left part of the map
// uncovered in 1 of 24 such flings at 0.25 (under 1 %), in 7 at 0.2 (up to
// 6 %) and in 16 at 0.15 (up to 10 %).
const PAD = 0.25;
// The canvas is drawn at most at this many pixels per CSS pixel: sharper
// is not visibly so on a phone, and a canvas costs its pixels squared.
const MAX_PIXEL_RATIO = 2;
// Pixels per CSS pixel of the drafts drawn while the view zooms, and while
// it pans where sharp drawings are slow (`PAN_DRAFT_MS`).
const DRAFT_RATIO = 1;
// A pan is drawn again as it goes sharp while a sharp drawing costs at most
// this long (smoothed, `onFrame`: the worker's time, and in Firefox the
// page's to copy it in), else as a draft (`follow`), which costs half as
// much or less and so keeps the edges and labels twice as close behind the
// pan. Drawn by the CPU (Chromium) on an M1, the country with results
// takes 43–48 ms in a map up to 1440 × 900 at 2 a pixel, which pans sharp;
// 65 ms in a 1920 × 1080 one and a city 100–150 ms, which pan in drafts,
// as does about everything on slower machines and larger screens.
const PAN_DRAFT_MS = 60;
// The weight of each sharp drawing's time in the smoothed one: the last
// few count, as the view and what it shows change.
const COST_SMOOTHING = 0.5;
// How far a zoom may go from that of the drawing asked for last before the
// view is drawn again: scaled up by CSS that much more, a drawing blurs.
const ZOOM_SLACK = 0.25;
// Pixels kept clear around a place the map moves to, beyond the insets.
const MARGIN = 24;
// The least room, across and down, that a place the map moves to is fitted
// into (`room`): any less, and it would be zoomed out to the country.
const MIN_ROOM = 160;
// The highest zoom the map fits a unit of the ballots' level at (`fitUnit`),
// as the selection fits an obec: an okrsok of a few blocks closer.
const UNIT_ZOOM = { kraj: 13, okres: 13, zsk: 13, obec: 14, obvod: 14, okrsok: 16 };
// The credits fold on a phone after this long (`foldCredits`).
const CREDITS_MS = 5000;

const COLORS = [
  'land',
  'kraj',
  'okres',
  'obec',
  'pending',
  'none',
  'zsk',
  'city',
  'council',
  'okrsok',
  'accent',
  // A country-wide contest's turnout (mapmode.js `toneOf`).
  'turnout',
  // The ballots' level (draw.js `setLevel`): its unit's outline, and the
  // veil over the rest.
  'level',
  'level-veil',
  'pin',
  'house',
  'text',
  'label',
  'halo',
  'neighbour',
  'neighbour-line',
  'neighbour-label',
  'neighbour-halo',
  // The base map (draw.js `drawBase`): opaque colours, and the opacity the
  // whole of it is drawn at.
  'base-water',
  'base-waterway',
  'base-building',
  'base-road',
  'base-road-fill',
  'base-major',
  'base-major-fill',
  'base-motorway',
  'base-motorway-fill',
  'base-rail',
  'base-tram',
  'base-alpha',
  // The steps of a candidate's 2026 votes, lowest first (mapmode.js); a
  // turnout mixes its area's colour into the land (draw.js `TONE_STEPS`).
  ...Array.from({ length: STEPS }, (_, i) => `result-${i + 1}`),
  // A winner's colour, by the candidates' places overall, those beyond the
  // last in one colour (mapmode.js `SERIES`).
  ...Array.from({ length: SERIES }, (_, i) => `series-${i + 1}`),
  'series-other',
  // A candidate's map of the election before: an okrsok whose figures then
  // are not known (mapmode.js `PREVIOUS_PALETTE`).
  'past-unknown',
];

/* The theme's map colours by name (draw.js `COLOR`). */
function readColors() {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(COLORS.map((name) => [name, style.getPropertyValue(`--map-${name}`).trim()]));
}

/* How the canvas takes a drawing (an ImageBitmap). Chromium shows it
 * without a copy from a 'bitmaprenderer' context, and copies it into a 2D
 * one: about 65 ms of the page's thread for a drawing of 33 million pixels
 * (2560 × 1440 CSS pixels at 2 a pixel, padded: `viewAt`). Firefox (142
 * measured) hands a 'bitmaprenderer' canvas's bitmap to its compositor
 * again at every paint of the page, a copy of the whole of it each frame
 * that a tooltip moves or the map pans: profiled at that size, a pointer
 * moved over the map for 4 s kept the page's thread busy for 3.5 s, 80 %
 * of it in memcpy, and for 0.5 s with the drawing copied once into a 2D
 * canvas, whose bitmap Firefox hands over only when it changes. Nothing
 * tells the two apart but the engine. */
const COPY_DRAWINGS = L.Browser.gecko;

/* Whether the renderer draws its canvases with the CPU, in the worker
 * (draw.js `cpuRaster`). Chromium otherwise records what a worker draws
 * on a canvas and rasterizes it later in its GPU process, and a drawing
 * counts as done (`onFrame`) before it is rasterized. In a profile of
 * panning on the owner's i7-7700K with HD Graphics 630 (3840 × 2160 at 2
 * a pixel; Chromium rasterizes paths there without multisampling, as on
 * every Intel GPU before Ice Lake), the GPU process's main thread spent
 * 190–320 ms on each drawing that took the worker 9–103 ms: they queued,
 * 2 s behind by the end, and held up the compositing of every frame, so
 * the map panned at 4–5 frames a second. Rasterized in the worker, a
 * drawing reaches the GPU process finished, and done means done, which
 * the wait before the next view and the drafts of a slow pan
 * (`PAN_DRAFT_MS`) rely on. On phones too: their map is a few million
 * pixels, cheap for the CPU, and on the owner's Android phone the two
 * felt the same. Firefox pans well on the same machine without it. */
const RASTER_ON_CPU = L.Browser.chrome;

/* The map's canvas, in the overlay pane, showing the latest drawing (`show`)
 * where its view is; while a zoom runs it is scaled by CSS transform, as
 * Leaflet's own canvases and image overlays are (with the same internal,
 * `_latLngToNewLayerPoint`). Shapes and labels share it: a second canvas
 * would double the pixels to draw, move and composite. */
const MapCanvas = L.Layer.extend({
  initialize() {
    this._view = null;
  },

  getEvents() {
    return {
      zoom: this._onZoom,
      zoomanim: this._onAnimZoom,
      // Leaflet moves the layer origin here: the canvas stays in place
      // until it is drawn again.
      viewreset: this._onZoom,
    };
  },

  onAdd(map) {
    this._canvas = L.DomUtil.create('canvas', 'km-canvas leaflet-zoom-animated', map.getPane('overlayPane'));
    this._context = this._canvas.getContext(COPY_DRAWINGS ? '2d' : 'bitmaprenderer');
  },

  onRemove() {
    L.DomUtil.remove(this._canvas);
  },

  _onZoom() {
    this._transform(this._map.getCenter(), this._map.getZoom());
  },

  _onAnimZoom(e) {
    this._transform(e.center, e.zoom);
  },

  _transform(center, zoom) {
    if (!this._view) return;
    const map = this._map;
    const scale = map.getZoomScale(zoom, this._view.zoom);
    const topLeft = map._latLngToNewLayerPoint(this._view.topLeft, zoom, center);
    // Unscaled on whole pixels, the drawing stays as sharp as drawn.
    L.DomUtil.setTransform(this._canvas, scale === 1 ? topLeft.round() : topLeft, scale);
  },

  /* Shows *bitmap*, a drawing of *view* (`viewAt`), instead of the one
   * shown. Returns the milliseconds the page's thread spent copying it in
   * (COPY_DRAWINGS, a new size's allocation included; else 0, a hand-over
   * without a copy). */
  show(bitmap, view) {
    const started = performance.now();
    const canvas = this._canvas;
    if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
    }
    canvas.style.width = `${view.w}px`;
    canvas.style.height = `${view.h}px`;
    if (COPY_DRAWINGS) {
      // Each drawing replaces the last, its transparent parts too (a
      // resize resets the context's state).
      this._context.globalCompositeOperation = 'copy';
      this._context.drawImage(bitmap, 0, 0);
      bitmap.close();
    } else {
      this._context.transferFromImageBitmap(bitmap);
    }
    this._view = view;
    this._onZoom();
    return COPY_DRAWINGS ? performance.now() - started : 0;
  },
});

/* Starts the renderer with *options* (draw.js `createRenderer`): in a worker
 * where the browser can draw in one, else on the page. Its drawings go to
 * *onFrame(bitmap, view, seq, ms)* (*ms* the time each took to draw), and
 * *onFail(error)* is called if it cannot start. Resolves to {send(method,
 * ...args)}, a call of a method of the renderer, and {call(method,
 * ...args)}, one whose result is wanted. */
async function startRenderer(options, onFrame, onFail) {
  if (typeof OffscreenCanvas === 'function') {
    const worker = new Worker(new URL('./render.js', import.meta.url), { type: 'module' });
    const calls = new Map();
    let ids = 0;
    worker.addEventListener('message', ({ data }) => {
      if (data.frame) {
        onFrame(data.frame, data.view, data.seq, data.ms);
      } else if (data.failed) {
        onFail(new Error(data.failed));
      } else {
        const { resolve, reject } = calls.get(data.id);
        calls.delete(data.id);
        if ('error' in data) reject(new Error(data.error));
        else resolve(data.value);
      }
    });
    worker.addEventListener('error', (e) => onFail(e.error ?? new Error(e.message)));
    // The bytes of coarse.json move to the worker rather than being copied.
    worker.postMessage({ method: 'init', args: [options] }, [options.coarse]);
    return {
      send: (method, ...args) => worker.postMessage({ method, args }),
      call: (method, ...args) =>
        new Promise((resolve, reject) => {
          const id = ++ids;
          calls.set(id, { resolve, reject });
          worker.postMessage({ method, args, id });
        }),
    };
  }
  const { createRenderer } = await import('./draw.js');
  const renderer = createRenderer({
    ...options,
    surface(w, h) {
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      return canvas;
    },
    present(canvas, view, seq, started) {
      createImageBitmap(canvas).then((bitmap) => onFrame(bitmap, view, seq, performance.now() - started));
    },
  });
  renderer.catch(onFail);
  const call = async (method, ...args) => (await renderer)[method](...args);
  return {
    send: (method, ...args) => {
      call(method, ...args).catch((e) => console.error(e));
    },
    call,
  };
}

/* The map's credits; on an earlier election's page (i18n.js `credits`)
 * with the dates its base map and addresses are of, and the later
 * boundaries it is drawn on. Its own boundaries are credited by name and
 * licence alone, the same in every language. */
function attribution() {
  if (!credits) return t('map.attribution');
  const [on, n] = credits.boundaries ?? [];
  return t('map.attribution_past', {
    boundaries: on ? t('map.credit_boundaries_other', { on, n }) : 'ZBGIS © ÚGKK SR, CC BY 4.0',
    osm: formatAsOf(credits.osm),
    addresses: formatAsOf(credits.addresses),
  });
}

/* On a phone the credits of *map* take three lines over the map (app.css):
 * there they show as the map loads, fold into an ⓘ button at the first
 * touch of the map or after CREDITS_MS, and the button unfolds and folds
 * them again. The OSMF's Attribution Guidelines
 * (https://osmfoundation.org/wiki/Licence/Attribution_Guidelines,
 * "Interactive maps") allow that of OpenStreetMap's credit: "You may use a
 * mechanism to fade/collapse the attribution under certain conditions: …
 * automatically on map interaction such as panning, clicking, or zooming;
 * automatically after five seconds", provided that "If the attribution has
 * been collapsed, the user must still be able to find the licence
 * information if they look for it, for example from an '(i)' button in the
 * corner of the map". Not one line as the map loads: OpenStreetMap's
 * credit, the second, would be past the screen's edge, and "The
 * attribution format should not require individuals to interact with the
 * map or produced work to see the attribution." Wider screens show them in
 * full throughout. Leaflet writes the credits once, at the start, so they
 * can be wrapped. */
function foldCredits(map) {
  const box = map.attributionControl.getContainer();
  const credits = document.createElement('span');
  credits.className = 'km-credits';
  credits.append(...box.childNodes);
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'km-credits-button';
  button.title = t('map.credits');
  button.setAttribute('aria-label', t('map.credits'));
  render(html`<${InfoIcon} />`, button);
  box.replaceChildren(button, credits);
  const show = (folded) => {
    box.classList.toggle('folded', folded);
    button.setAttribute('aria-expanded', String(!folded));
  };
  const container = map.getContainer();
  const touches = ['pointerdown', 'wheel', 'keydown'];
  let timer = 0;
  const stop = () => {
    clearTimeout(timer);
    for (const type of touches) container.removeEventListener(type, fold);
  };
  function fold(e) {
    // The button's own press folds or unfolds them.
    if (e && box.contains(e.target)) return;
    stop();
    show(true);
  }
  timer = setTimeout(fold, CREDITS_MS);
  for (const type of touches) container.addEventListener(type, fold, { passive: true });
  button.addEventListener('click', () => {
    stop();
    show(!box.classList.contains('folded'));
  });
  show(false);
}

/* *name* as data.js `contestArea` names an area ('BA', 'BA/3', 'kraj:1',
 * 'kraj:1/3') as the renderer takes it: {city, obvod} or {kraj, zsk}. */
function parseArea(name) {
  const kraj = name.startsWith('kraj:');
  const [code, obvod] = name.slice(kraj ? 'kraj:'.length : 0).split('/');
  const n = obvod ? Number(obvod) : null;
  return kraj ? { kraj: code, zsk: n } : { city: code, obvod: n };
}

/* Whether views *a* and *b* (`viewAt` in `createMap`) draw alike. */
const sameView = (a, b) =>
  a.zoom === b.zoom && a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h && a.ratio === b.ratio;

/* The tooltip of what the pointer is over on *map*, where there is a
 * pointer that hovers: while a handler is set, asked of *renderer* one
 * question at a time, the latest position each, and not while the map
 * moves. Returns the setter of the handler (`setHover`; null for none).
 *
 * The handler follows the pointer at every move with the unit answered
 * last, and gets the answer for a newer position as it comes. An answer is
 * never held back for a pointer that has moved on: a mouse sends a move a
 * frame, more often than the worker answers when it is busy drawing, and a
 * tooltip that waited for an answer to the very latest position would stand
 * still for as long as the pointer moves. So the unit shown may be that of
 * a position one answer old, a pixel or few away. */
function hoverTooltip(map, renderer) {
  let onHover = null;
  // The pointer's latest position on the map (a mousemove event), null
  // while it is off the map or the map moves; whether it has been asked
  // about; the unit answered last, for an earlier position perhaps; and a
  // count of the pointer's leaving and the map's moves, which outdate the
  // answers asked for before.
  let pointer = null;
  let asked = true;
  let unit = null;
  let gone = 0;
  let asking = false;
  let moving = false;
  const hovers = window.matchMedia('(hover: hover)');
  const report = () => onHover?.(unit && { unit, x: pointer.containerPoint.x, y: pointer.containerPoint.y });
  async function ask() {
    asking = true;
    while (pointer && !asked && onHover) {
      asked = true;
      const { latlng } = pointer;
      const since = gone;
      const answer = await renderer.call('hover', latlng.lng, latlng.lat);
      if (since !== gone || !pointer) continue;
      unit = answer;
      report();
    }
    asking = false;
  }
  const leave = () => {
    gone++;
    pointer = null;
    unit = null;
  };
  map.on('mousemove', (e) => {
    if (!onHover || moving || !hovers.matches) return;
    pointer = e;
    asked = false;
    if (unit) report();
    if (!asking) ask();
  });
  map.on('mouseout movestart', (e) => {
    if (e.type === 'movestart') moving = true;
    leave();
    onHover?.(null);
  });
  map.on('moveend', () => {
    moving = false;
  });
  return (handler) => {
    onHover = handler;
    leave();
  };
}

/* The constituency overlays, broadest first (draw.js `OVERLAYS`). */
export const CONSTITUENCIES = ['zsk', 'city', 'oz', 'okrsky'];

/* The constituency overlays of the page's election, of zsk, city, oz and
 * okrsky, as a Set: those it has units of (data/index.json: obce electing
 * a regional or a city's council, data.js `electsAnywhere`, obce split
 * into council obvody; geo/index.json: okrsky drawn). A country-wide
 * contest has none of the first three, a by-election seldom any, the
 * regional or municipal elections held apart (2017, 2018) only their own.
 * The menu (controls.js) offers only these, a link (app.js `h`) names
 * only these, and the map draws only these (`setOverlays`). Fetched once. */
let here = null;
export function overlaysHere() {
  here ??= Promise.all([dataIndex(), getJSON('/geo/index.json')]).then(([index, geo]) => {
    const has = {
      zsk: electsAnywhere(index, 'regional'),
      city: electsAnywhere(index, 'city'),
      oz: Object.keys(index.obce).some((code) => hasCouncilObvody(index, code)),
      okrsky: Object.keys(geo.okrsky.drawn).length > 0,
    };
    return new Set(Object.keys(has).filter((name) => has[name]));
  });
  return here;
}

/* Creates the map in *element*. `onPick(p)` is called when the user clicks
 * a place (draw.js `pick`); `insets()` returns the pixels {top, right,
 * bottom, left} of the map that floating controls and panes cover, which
 * moves to a place keep it out of, and {legend} the part of `top` that the
 * results' legend alone covers (`room`); `onZoom({canZoomIn, canZoomOut})`
 * reports the zoom limits whenever they change. *view* ({lat, lon, zoom},
 * a link's) is the first view, else the whole country; `onView(view)`
 * reports the view at the end of every move. Resolves once the country
 * outline is shown. */
export async function createMap(element, { onPick, insets, onZoom, view, onView }) {
  const map = L.map(element, {
    minZoom: MIN_ZOOM,
    maxZoom: 19,
    maxBounds: L.latLngBounds(SLOVAKIA).pad(0.3),
    // Continuous: the first view fills the map exactly, and zoom.js and
    // pinches end where the gesture does.
    zoomSnap: 0,
    // The app draws its own buttons (zoomIn, zoomOut below).
    zoomControl: false,
  });
  const zoomer = smoothZoom(map);
  dragAfterPinch(map);
  map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
  map.attributionControl.addAttribution(attribution());
  foldCredits(map);
  /* The insets (`insets()`) that a place the map moves to keeps out from
   * under, giving way where they would leave it less than MIN_ROOM pixels
   * down or across: the legend's part of the top first (`legend`), then the
   * bottom (a phone's sheet); the left (the pane). */
  function room() {
    const i = insets();
    const size = map.getSize();
    let short = MIN_ROOM - (size.y - i.top - i.bottom - 2 * MARGIN);
    if (short > 0) {
      const legend = Math.min(short, i.legend ?? 0);
      i.top -= legend;
      i.bottom = Math.max(0, i.bottom - (short - legend));
    }
    short = MIN_ROOM - (size.x - i.left - i.right - 2 * MARGIN);
    if (short > 0) i.left = Math.max(0, i.left - short);
    return i;
  }
  const padding = () => {
    const i = room();
    return {
      paddingTopLeft: [i.left + MARGIN, i.top + MARGIN],
      paddingBottomRight: [i.right + MARGIN, i.bottom + MARGIN],
    };
  };
  // The country as wide as the map allows; only the search card above (on
  // phones as wide as the screen) must not cover it. A portrait phone is
  // narrower than Slovakia is wide, so there the country runs edge to edge
  // (the kraj names keep inside the map). The first view, and that of a
  // country-wide contest's results (`fitCountry`): the pane beside it
  // cannot make it smaller, as the map zooms out no further.
  const showCountry = () => {
    const side = map.getSize().x < map.getSize().y ? 2 : MARGIN / 2;
    map.fitBounds(SLOVAKIA, {
      paddingTopLeft: [side, insets().top + MARGIN / 2],
      paddingBottomRight: [side, MARGIN / 2],
    });
  };
  if (view) map.setView([view.lat, view.lon], view.zoom);
  else showCountry();
  map.on('moveend', () => {
    const { lat, lng } = map.getCenter();
    onView({ lat, lon: lng, zoom: map.getZoom() });
  });
  // Only a change is reported: each report renders the app again, pane and
  // all, which at the end of every zoom would hold up the next gesture.
  let limits = '';
  const reportZoom = () => {
    const z = map.getZoom();
    const now = { canZoomIn: z < map.getMaxZoom(), canZoomOut: z > map.getMinZoom() };
    const key = `${now.canZoomIn} ${now.canZoomOut}`;
    if (key === limits) return;
    limits = key;
    onZoom(now);
  };
  map.on('zoomend', reportZoom);
  reportZoom();

  // coarse.json comes as it is, which the page preloads, and the renderer
  // parses it.
  const [geoIndex, coarse] = await Promise.all([
    fetchJSON('/geo/index.json'),
    fetch(dataUrl('/geo/coarse.json')).then((response) => {
      if (!response.ok) throw new Error(`/geo/coarse.json: HTTP ${response.status}`);
      return response.arrayBuffer();
    }),
  ]);

  // The lowest zoom: a view larger than maxBounds is centred on them (as
  // Leaflet does), and must stay within the countries drawn, the extent of
  // the coarsest level.
  const coarsest = geoIndex.neighbours.reduce((a, b) => (b.zoom[0] < a.zoom[0] ? b : a));
  function limitZoomOut() {
    const [west, south, east, north] = coarsest.extent;
    const bounds = map.options.maxBounds;
    const middle = map.project(bounds.getNorthEast(), 0).add(map.project(bounds.getSouthWest(), 0)).divideBy(2);
    const nw = map.project([north, west], 0);
    const se = map.project([south, east], 0);
    const size = map.getSize();
    const fits = Math.max(
      size.x / 2 / Math.min(middle.x - nw.x, se.x - middle.x),
      size.y / 2 / Math.min(middle.y - nw.y, se.y - middle.y),
    );
    map.setMinZoom(Math.max(MIN_ZOOM, Math.log2(fits)));
    reportZoom();
  }
  limitZoomOut();
  map.on('resize', limitZoomOut);

  /* The view the map shows now, for a drawing at *ratio* canvas pixels per
   * CSS pixel: `zoom`, `k` the scale from Z0 pixels, (x, y) the top left
   * corner of the canvas in pixels of the zoom, `w` and `h` its CSS size,
   * `box` its area in Z0 pixels and `bounds` in degrees [west, south, east,
   * north], `topLeft` its corner {lat, lng}, and `visible` the map's own box
   * [x0, y0, x1, y1] in CSS pixels of the canvas. */
  function viewAt(ratio) {
    const size = map.getSize();
    const pad = size.multiplyBy(PAD).round();
    const origin = map.containerPointToLayerPoint(pad.multiplyBy(-1));
    const corner = origin.add(map.getPixelOrigin());
    const zoom = map.getZoom();
    const k = 2 ** (zoom - Z0);
    const w = size.x + 2 * pad.x;
    const h = size.y + 2 * pad.y;
    const nw = map.layerPointToLatLng(origin);
    const se = map.layerPointToLatLng(origin.add([w, h]));
    return {
      zoom,
      k,
      x: corner.x,
      y: corner.y,
      w,
      h,
      ratio,
      box: [corner.x / k, corner.y / k, (corner.x + w) / k, (corner.y + h) / k],
      bounds: [nw.lng, se.lat, se.lng, nw.lat],
      topLeft: { lat: nw.lat, lng: nw.lng },
      visible: [pad.x, pad.y, pad.x + size.x, pad.y + size.y],
    };
  }

  /* The part of the map in *view* that no control or pane covers, nor the
   * attribution, which runs across the foot of a phone: [x0, y0, x1, y1] in
   * CSS pixels of the canvas. */
  function freePart(view) {
    const i = insets();
    const bottom = Math.max(i.bottom, map.attributionControl.getContainer().offsetHeight);
    const [x0, y0, x1, y1] = view.visible;
    return [x0 + i.left, y0 + i.top, x1 - i.right, y1 - bottom];
  }

  const canvas = new MapCanvas().addTo(map);
  let shown;
  const firstShown = new Promise((resolve, reject) => {
    shown = { resolve, reject };
  });
  // Views sent, the one sent last and the free part with it, and the latest
  // that has come back drawn.
  let seq = 0;
  let sent = null;
  let sentFree = null;
  let drawn = 0;
  // A move went on while the renderer was drawing: `follow` once it is done.
  let owed = false;
  // A drawing just shown, until the frame that puts it on screen begins:
  // the next view waits for it, so that drawings never queue up to the
  // compositor faster than it takes them in. That is the only sign of it
  // to be had cheaply; whether a GPU has rasterized a canvas (Firefox's
  // accelerated ones) only a readback would tell.
  let presenting = false;
  // The time a sharp drawing costs, smoothed, from the second one on: the
  // first, on an M1 half as long again as the next, pays for compiling the
  // code and making the paths. Null before then. The worker's time to draw
  // it (`onFrame`'s *ms*) and, in Firefox, the page's to copy it in
  // (`show`): in a profile of panning on the owner's i7-7700K with HD
  // Graphics 630 (3840 × 2160 at 2 a pixel), each copy was a blit on the
  // CPU of 47–120 ms, which held up the frame it fell in; the same machine
  // also spent up to 65 ms uploading a drawing to the GPU, which nothing
  // on the page can time.
  let sharpCost = null;
  let sharpDrawings = 0;

  function onFrame(bitmap, view, s, ms) {
    drawn = Math.max(drawn, s);
    if (map._animatingZoom) {
      bitmap.close();
      // Asked for again, should the zoom end where it began.
      if (s === seq) sentFree = null;
      return;
    }
    const cost = ms + canvas.show(bitmap, view);
    shown.resolve();
    if (view.ratio > DRAFT_RATIO && ++sharpDrawings > 1) {
      sharpCost = sharpCost === null ? cost : sharpCost + (cost - sharpCost) * COST_SMOOTHING;
    }
    presenting = true;
    requestAnimationFrame(() => {
      presenting = false;
      if (owed) follow();
    });
  }

  function onFail(e) {
    console.error(e);
    shown.reject(e);
  }

  const renderer = await startRenderer(
    {
      geoIndex,
      coarse,
      dataSource,
      colors: readColors(),
      strings: {
        obvod: t('map.obvod', { n: '{n}' }),
        okrsok: t('map.okrsok', { n: '{n}' }),
        countries: stringsUnder('country.'),
      },
      cpuRaster: RASTER_ON_CPU,
    },
    onFrame,
    onFail,
  );

  /* Has the view the map shows now drawn, at *ratio* canvas pixels per CSS
   * pixel (`viewAt`), unless it is the one asked for last with the same
   * free part (a pan's end after its last move, a resize reported twice):
   * the renderer draws again by itself whatever else changes. */
  function request(ratio) {
    if (map._animatingZoom) return;
    const view = viewAt(ratio);
    const free = freePart(view);
    if (sentFree && sameView(view, sent) && free.every((v, i) => v === sentFree[i])) return;
    sent = view;
    sentFree = free;
    seq++;
    renderer.send('show', sent, free, seq);
  }
  const sharpRatio = () => Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
  const sharp = () => request(sharpRatio());

  /* Whether the drawing asked for last no longer serves the view: less than
   * half its margin is left on a side, or the zoom has gone ZOOM_SLACK from
   * its own or to another level. */
  function stale() {
    const zoom = map.getZoom();
    if (Math.abs(zoom - sent.zoom) > ZOOM_SLACK || Math.floor(zoom) !== Math.floor(sent.zoom)) return true;
    // The view in pixels of the drawing's zoom, from its top left corner.
    const scale = 2 ** (sent.zoom - zoom);
    const { min, max } = map.getPixelBounds();
    const [x0, y0, x1, y1] = [min.x * scale - sent.x, min.y * scale - sent.y, max.x * scale - sent.x, max.y * scale - sent.y];
    const mx = sent.visible[0] / 2;
    const my = sent.visible[1] / 2;
    return x0 < mx || y0 < my || x1 > sent.w - mx || y1 > sent.h - my;
  }

  /* Whether the view has panned from the drawing asked for last, at its
   * zoom. */
  function panned() {
    if (map.getZoom() !== sent.zoom) return false;
    const { min } = map.getPixelBounds();
    return Math.abs(min.x - sent.visible[0] - sent.x) >= 1 || Math.abs(min.y - sent.visible[1] - sent.y) >= 1;
  }

  // While the view moves, once the last drawing has come back and been
  // put on screen: a pan, a drag's inertia included, is drawn again as it
  // goes, so the labels at the edges of the map keep in view (draw.js
  // `spot`) rather than jumping once it stops, sharp where a sharp drawing
  // takes at most PAN_DRAFT_MS, else as a draft; a zoom gets a draft when
  // the last drawing no longer serves.
  function follow() {
    owed = false;
    if (map._animatingZoom || !sent) return;
    if (drawn < seq || presenting) owed = true;
    else if (panned()) request(sharpCost > PAN_DRAFT_MS ? DRAFT_RATIO : sharpRatio());
    else if (stale()) request(DRAFT_RATIO);
  }

  map.on('move', follow);
  map.on('moveend resize', sharp);
  // The shards of the view a zoom heads for start loading when it starts:
  // `zoomgoal` (zoom.js) and Leaflet's animated zoom tell where it ends.
  map.on('zoomgoal zoomanim', ({ center, zoom }) => {
    const b = map.getPixelBounds(center, zoom);
    const box = L.latLngBounds(map.unproject(b.min, zoom), map.unproject(b.max, zoom)).pad(PAD);
    renderer.send('prefetch', zoom, [box.getWest(), box.getSouth(), box.getEast(), box.getNorth()]);
  });
  // A tap where nothing hovers, while a handler is set (`setInspect`): it
  // may take the tap, to show the figures of the unit there, and pick the
  // place later; else the tap picks it, as a click does.
  let onInspect = null;
  const touch = window.matchMedia('(hover: none)');
  map.on('click', async (e) => {
    const { lat, lng } = e.latlng;
    const zoom = map.getZoom();
    const pick = async () => {
      const picked = await renderer.call('pick', lng, lat, zoom);
      if (picked) onPick(picked);
    };
    if (onInspect && touch.matches) {
      const unit = await renderer.call('hover', lng, lat);
      if (onInspect?.({ unit, x: e.containerPoint.x, y: e.containerPoint.y, pick })) return;
    }
    pick();
  });
  map.on('movestart', () => onInspect?.(null));
  const setHoverHandler = hoverTooltip(map, renderer);
  document.addEventListener('themechange', () => renderer.send('setColors', readColors()));
  sharp();
  await firstShown;

  // The overlays switched on (`setOverlays`), and the number of council
  // obvody of every obec once the council overlay has been on.
  let overlays = null;
  let councils = null;
  // Counts calls of `select`: a slower one that comes back late is dropped.
  let selection = 0;

  /* The bounds of *box* (Z0 pixels, from the renderer). */
  const boundsOf = ([x0, y0, x1, y1]) => L.latLngBounds(map.unproject([x0, y1], Z0), map.unproject([x1, y0], Z0));

  /* Fits the map to *box* (Z0 pixels, from the renderer) at most at
   * *maxZoom*, unless there is none or selection *gen* is no longer the
   * latest. */
  function fit(box, maxZoom, gen) {
    if (!box || gen !== selection) return;
    map.fitBounds(boundsOf(box), { ...padding(), maxZoom });
  }

  return {
    /* Shows *p* ({obec, lat?, lon?, label?, obvod?, okrsok?, street?, part?})
     * as the selected place, or nothing; a street or part is highlighted.
     * *view*: 'place' zooms to the house of an address (one with a label),
     * to the street or part, to the council obvod, or to the whole obec
     * otherwise; 'obec' to the obec; null only pans a picked point out from
     * under the insets. */
    async select(p, view = null) {
      const gen = ++selection;
      const info = p ? await obecInfo(p.obec) : null;
      if (gen !== selection) return;
      const place = info ? { ...p, info } : null;
      const street = await renderer.call('select', place);
      if (gen !== selection || street === undefined) return;
      // The pane that opens or closes with it changes the free part, which
      // the labels keep to (`freePart`).
      sharp();
      const point = place && Number.isFinite(place.lat) ? L.latLng(place.lat, place.lon) : null;
      if (place && view) zoomer.stop();
      if (view === 'place' && point && place.label) {
        // The house in the middle of the part of the map left uncovered.
        const zoom = Math.max(map.getZoom(), 17);
        const i = room();
        const offset = L.point((i.left - i.right) / 2, (i.top - i.bottom) / 2);
        map.setView(map.unproject(map.project(point, zoom).subtract(offset), zoom), zoom);
      } else if (view === 'place' && street) {
        map.fitBounds(L.latLngBounds(street), { ...padding(), maxZoom: 17 });
      } else if (place && (view === 'obec' || view === 'place')) {
        // A council obvod named without a point (by a link): the obvod.
        const obvod = view === 'place' && !point ? place.obvod : null;
        fit(await renderer.call('obecBox', info, obvod), 14, gen);
      } else if (point && !zoomer.running()) {
        // A click: the pane that opens may cover it. Not while the user zooms
        // (a double-click picks a place too).
        map.panInside(point, padding());
      }
    },

    /* Switches the overlays on or off: *wanted* {zsk, city, oz, okrsky,
     * base, buildings}, `base` the roads, railways and waters of the base
     * map. A constituency overlay the election has no units of stays off
     * (`overlaysHere`): the council overlay would grey every obec as one
     * without a council. Its counts are of the obce of the election, of a
     * by-election those where it is held (data.js `heldObce`): the others
     * are no part of it, and drawn as land, not as obce without a council
     * election. */
    async setOverlays(wanted) {
      overlays = wanted;
      const exist = await overlaysHere();
      const drawn = Object.fromEntries(
        Object.entries(wanted).map(([name, on]) => [name, on && (!CONSTITUENCIES.includes(name) || exist.has(name))]),
      );
      if (drawn.oz && !councils) {
        const index = await dataIndex();
        const held = heldObce(index);
        const rows = Object.entries(index.obce).filter(([code]) => !held || held.has(code));
        councils = Object.fromEntries(rows.map(([code, row]) => [code, row[4] ?? 0]));
      }
      if (overlays !== wanted) return;
      renderer.send('setOverlays', drawn, councils);
    },

    /* Fits the map to *target* (data.js `contestArea`: {area} or {obec,
     * obvod}), the area of a contest whose results it shows (mapmode.js),
     * without selecting it. A selection made meanwhile moves the map
     * instead. */
    async fitArea(target) {
      const gen = selection;
      const area = target.area ? parseArea(target.area) : null;
      const info = area ? null : await obecInfo(target.obec);
      const box = area ? await renderer.call('areaBox', area) : await renderer.call('obecBox', info, target.obvod);
      if (gen !== selection) return;
      zoomer.stop();
      fit(box, area ? 13 : 14, gen);
    },

    /* Shows the whole country as the first view does, as the area of a
     * country-wide contest whose results the map shows (mapmode.js). */
    fitCountry() {
      zoomer.stop();
      showCountry();
    },

    /* Outlines the unit at *level* (one of live.js SCOPES; 'all' for none)
     * of the selected place, the rest of the map veiled (draw.js
     * `setLevel`): the level the ballots show the results at (mapmode.js
     * `MapResults`). */
    setLevel(level) {
      renderer.send('setLevel', level);
    },

    /* Fits the map to the unit at *level* (one of live.js SCOPES but 'all')
     * of place *p* ({obec, obvod, okrsok}) as draw.js `unitBox` finds it,
     * zooming in or out, without selecting it: the level chosen on the
     * ballots, or that of a contest's results put on the map there
     * (mapmode.js `MapResults`). A selection made meanwhile moves the map
     * instead. */
    async fitUnit(level, p) {
      const gen = selection;
      const info = await obecInfo(p.obec);
      const unit = info && (await renderer.call('unitBox', level, { info, obvod: p.obvod, okrsok: p.okrsok }));
      if (gen !== selection || !unit) return;
      zoomer.stop();
      fit(unit.box, UNIT_ZOOM[unit.level], gen);
    },

    /* Colours the land by the 2026 results *shown* (draw.js `setResults`),
     * or no longer for null. Their legend, coming or going, changes the
     * free part. */
    setResults(shown) {
      renderer.send('setResults', shown);
      sharp();
    },

    /* Calls *handler*({unit, x, y}) with the unit of the results the
     * pointer is over (draw.js `unitAt`) at (x, y) in the map's pixels, and
     * handler(null) when it is over none or the map moves; none for null. */
    setHover(handler) {
      setHoverHandler(handler);
    },

    /* While *handler* is set, a tap on a device without hover (a touch
     * screen) calls handler({unit, x, y, pick}) first: the unit of the
     * results there (draw.js `unitAt`, null where none) at (x, y) in the
     * map's pixels, and `pick()` that picks the place there as the tap would
     * have; true if the handler took the tap, which then picks nothing. It
     * is called with null when the map moves. None for null. */
    setInspect(handler) {
      onInspect = handler;
    },

    /* Draws the view again for what covers the map now (`insets`): the
     * sheet has changed height, the legend has unfolded. */
    redraw() {
      sharp();
    },

    zoomIn() {
      zoomer.zoomBy(1);
    },

    zoomOut() {
      zoomer.zoomBy(-1);
    },

    /* Moves to *view* ({lat, lon, zoom}, a link's) at once. */
    setView({ lat, lon, zoom }) {
      zoomer.stop();
      map.setView([lat, lon], zoom, { animate: false });
    },
  };
}
