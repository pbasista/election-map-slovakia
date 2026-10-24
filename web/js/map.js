/* The map: Leaflet for the view (pan, zoom, events), no tile layer, and one
 * canvas showing what the renderer (draw.js) drew of it.
 *
 * The page's main thread only follows the user. The renderer runs in a
 * worker (render.js): every file it fetches and decodes and every pixel it
 * draws is off this thread, so input is handled and frames are composited
 * however long a drawing takes. A finished drawing comes as an ImageBitmap
 * and is shown by handing it to the canvas, at the transform that puts it
 * where its view is. Meanwhile the canvas follows a move or zoom by CSS
 * transform, as Leaflet's own canvases do, which the compositor applies
 * (with the GPU where there is one) without a redraw.
 *
 * A drawing covers the view and PAD of it on every side. While a move or
 * zoom goes on, the view of the moment is drawn as a draft (DRAFT_RATIO
 * canvas pixels per CSS pixel: a quarter of the pixels on a sharp screen)
 * whenever the one asked for last no longer serves (`stale`): less than half
 * its margin is left on a side, or the zoom has gone ZOOM_SLACK from its
 * own or to another level. A view goes to the renderer only once the one
 * before has come back drawn, so it never falls behind with views nobody
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
 * as they change, which colours the land by them (`setResults`).
 */

import { dataIndex, obecInfo } from './data.js';
import { dataUrl, fetchJSON } from './files.js';
import { dataVersion, stringsUnder, t } from './i18n.js';
import { STEPS } from './mapmode.js';
import { Z0 } from './topo.js';
import { smoothZoom } from './zoom.js';

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
// pan shows the map around until it is drawn again.
const PAD = 0.25;
// The canvas is drawn at most at this many pixels per CSS pixel: sharper
// is not visibly so on a phone, and a canvas costs its pixels squared.
const MAX_PIXEL_RATIO = 2;
// Pixels per CSS pixel of the drafts drawn while the view zooms.
const DRAFT_RATIO = 1;
// How far a zoom may go from that of the drawing asked for last before the
// view is drawn again: scaled up by CSS that much more, a drawing blurs.
const ZOOM_SLACK = 0.25;
// Pixels kept clear around a place the map moves to, beyond the insets.
const MARGIN = 24;

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
  'accent',
  'pin',
  'house',
  'text',
  'label',
  'halo',
  'neighbour',
  'neighbour-line',
  'neighbour-label',
  'neighbour-halo',
  // The steps of a candidate's 2026 votes, lowest first (mapmode.js); a
  // turnout mixes its area's colour into the land (draw.js `TONE_STEPS`).
  ...Array.from({ length: STEPS }, (_, i) => `result-${i + 1}`),
];

/* The theme's map colours by name (draw.js `COLOR`). */
function readColors() {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(COLORS.map((name) => [name, style.getPropertyValue(`--map-${name}`).trim()]));
}

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
    this._bitmaps = this._canvas.getContext('bitmaprenderer');
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
   * shown. */
  show(bitmap, view) {
    const canvas = this._canvas;
    if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
    }
    canvas.style.width = `${view.w}px`;
    canvas.style.height = `${view.h}px`;
    this._bitmaps.transferFromImageBitmap(bitmap);
    this._view = view;
    this._onZoom();
  },
});

/* Starts the renderer with *options* (draw.js `createRenderer`): in a worker
 * where the browser can draw in one, else on the page. Its drawings go to
 * *onFrame(bitmap, view, seq)*, and *onFail(error)* is called if it cannot
 * start. Resolves to {send(method, ...args)}, a call of a method of the
 * renderer, and {call(method, ...args)}, one whose result is wanted. */
async function startRenderer(options, onFrame, onFail) {
  if (typeof OffscreenCanvas === 'function') {
    const worker = new Worker(new URL('./render.js', import.meta.url), { type: 'module' });
    const calls = new Map();
    let ids = 0;
    worker.addEventListener('message', ({ data }) => {
      if (data.frame) {
        onFrame(data.frame, data.view, data.seq);
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
    present(canvas, view, seq) {
      createImageBitmap(canvas).then((bitmap) => onFrame(bitmap, view, seq));
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

/* *name* as data.js `contestArea` names an area ('BA', 'BA/3', 'kraj:1',
 * 'kraj:1/3') as the renderer takes it: {city, obvod} or {kraj, zsk}. */
function parseArea(name) {
  const kraj = name.startsWith('kraj:');
  const [code, obvod] = name.slice(kraj ? 'kraj:'.length : 0).split('/');
  const n = obvod ? Number(obvod) : null;
  return kraj ? { kraj: code, zsk: n } : { city: code, obvod: n };
}

/* Creates the map in *element*. `onPick({obec, lat, lon, label?})` is called
 * when the user clicks a place; `insets()` returns the pixels {top, right,
 * bottom, left} of the map that floating controls and panes cover, which
 * moves to a place keep it out of; `onZoom({canZoomIn, canZoomOut})` reports
 * the zoom limits whenever they change. Resolves once the country outline is
 * shown. */
export async function createMap(element, { onPick, insets, onZoom }) {
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
  map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
  map.attributionControl.addAttribution(t('map.attribution'));
  const padding = () => {
    const i = insets();
    return {
      paddingTopLeft: [i.left + MARGIN, i.top + MARGIN],
      paddingBottomRight: [i.right + MARGIN, i.bottom + MARGIN],
    };
  };
  // The country as wide as the map allows; only the search card above (on
  // phones as wide as the screen) must not cover it. A portrait phone is
  // narrower than Slovakia is wide, so there the country runs edge to edge
  // (the kraj names keep inside the map).
  const side = map.getSize().x < map.getSize().y ? 2 : MARGIN / 2;
  map.fitBounds(SLOVAKIA, {
    paddingTopLeft: [side, insets().top + MARGIN / 2],
    paddingBottomRight: [side, MARGIN / 2],
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
  // Views sent, the one sent last, and the latest that has come back drawn.
  let seq = 0;
  let sent = null;
  let drawn = 0;
  // A move went on while the renderer was drawing: `follow` once it is done.
  let owed = false;

  function onFrame(bitmap, view, s) {
    drawn = Math.max(drawn, s);
    if (map._animatingZoom) {
      bitmap.close();
    } else {
      canvas.show(bitmap, view);
      shown.resolve();
    }
    if (owed) follow();
  }

  function onFail(e) {
    console.error(e);
    shown.reject(e);
  }

  const renderer = await startRenderer(
    {
      geoIndex,
      coarse,
      dataVersion,
      colors: readColors(),
      strings: { obvod: t('map.obvod', { n: '{n}' }), countries: stringsUnder('country.') },
    },
    onFrame,
    onFail,
  );

  /* Has the view the map shows now drawn, at *ratio* canvas pixels per CSS
   * pixel (`viewAt`). */
  function request(ratio) {
    if (map._animatingZoom) return;
    sent = viewAt(ratio);
    seq++;
    renderer.send('show', sent, freePart(sent), seq);
  }
  const sharp = () => request(Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO));

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

  // While the view moves, once the last drawing has come back: a pan, a
  // drag's inertia included, is drawn again as it goes, so the labels at
  // the edges of the map keep in view (draw.js `spot`) rather than jumping
  // once it stops; a zoom gets a draft when the last drawing no longer
  // serves.
  function follow() {
    owed = false;
    if (map._animatingZoom || !sent) return;
    if (drawn < seq) owed = true;
    else if (panned()) sharp();
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
  map.on('click', async (e) => {
    const { lat, lng } = e.latlng;
    const picked = await renderer.call('pick', lng, lat, map.getZoom());
    if (picked) onPick(picked);
  });
  document.addEventListener('themechange', () => renderer.send('setColors', readColors()));
  sharp();
  await firstShown;

  // The overlays switched on (`setOverlays`), and the number of council
  // obvody of every obec once the council overlay has been on.
  let overlays = null;
  let councils = null;
  // Counts calls of `select`: a slower one that comes back late is dropped.
  let selection = 0;

  /* Fits the map to *box* (Z0 pixels, from the renderer) at most at
   * *maxZoom*, unless there is none or selection *gen* is no longer the
   * latest. */
  function fit(box, maxZoom, gen) {
    if (!box || gen !== selection) return;
    const [x0, y0, x1, y1] = box;
    const bounds = L.latLngBounds(map.unproject([x0, y1], Z0), map.unproject([x1, y0], Z0));
    map.fitBounds(bounds, { ...padding(), maxZoom });
  }

  return {
    /* Shows *p* ({obec, lat?, lon?, label?, obvod?, street?, part?}, or
     * {area} for a contest's area (data.js `contestArea`): 'BA' the city of
     * Bratislava, 'BA/3' its council obvod, 'kraj:1' a kraj, 'kraj:1/3' its
     * regional obvod) as the selected place, or nothing; a street or part
     * is highlighted. *view*: 'place' zooms to the house of an address (one
     * with a label), to the street or part, to the council obvod or area, or
     * to the whole obec otherwise; 'obec' to the obec; null only pans a
     * picked point out from under the insets. */
    async select(p, view = null) {
      const gen = ++selection;
      if (p?.area) {
        const area = parseArea(p.area);
        if ((await renderer.call('select', { area })) === undefined || gen !== selection) return;
        // The pane that opens or closes with it changes the free part.
        sharp();
        if (view) {
          zoomer.stop();
          fit(await renderer.call('areaBox', area), 13, gen);
        }
        return;
      }
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
        const i = insets();
        const offset = L.point((i.left - i.right) / 2, (i.top - i.bottom) / 2);
        map.setView(map.unproject(map.project(point, zoom).subtract(offset), zoom), zoom);
      } else if (view === 'place' && street) {
        map.fitBounds(L.latLngBounds(street), { ...padding(), maxZoom: 17 });
      } else if (place && (view === 'obec' || view === 'place')) {
        // A council obvod picked by its contest (a click has a point): the obvod.
        const obvod = view === 'place' && !point ? place.obvod : null;
        fit(await renderer.call('obecBox', info, obvod), 14, gen);
      } else if (point && !zoomer.running()) {
        // A click: the pane that opens may cover it. Not while the user zooms
        // (a double-click picks a place too).
        map.panInside(point, padding());
      }
    },

    /* Switches the overlays on or off: *wanted* {zsk, city, oz}. */
    async setOverlays(wanted) {
      overlays = wanted;
      if (wanted.oz && !councils) {
        const index = await dataIndex();
        councils = Object.fromEntries(Object.entries(index.obce).map(([code, row]) => [code, row[4] ?? 0]));
      }
      if (overlays !== wanted) return;
      renderer.send('setOverlays', wanted, councils);
    },

    /* Fits the map to *target* (data.js `contestArea`: {area} or {obec,
     * obvod}) without selecting it: the area of a contest whose results it
     * shows (mapmode.js), or with *highlight* of a contest whose pin was
     * pressed on the ballots or in Favourites, which highlights it beside
     * the selected place until the selection changes (draw.js `showArea`).
     * A selection made meanwhile moves the map instead. */
    async fitArea(target, highlight = false) {
      const gen = selection;
      const area = target.area ? parseArea(target.area) : null;
      const info = area ? null : await obecInfo(target.obec);
      const box = area ? await renderer.call('areaBox', area) : await renderer.call('obecBox', info, target.obvod);
      if (gen !== selection) return;
      if (highlight) renderer.send('showArea', area ? { area } : { info, obvod: target.obvod });
      zoomer.stop();
      fit(box, area ? 13 : 14, gen);
    },

    /* Colours the land by the 2026 results *shown* (draw.js `setResults`),
     * or no longer for null. Their legend, coming or going, changes the
     * free part. */
    setResults(shown) {
      renderer.send('setResults', shown);
      sharp();
    },

    zoomIn() {
      zoomer.zoomBy(1);
    },

    zoomOut() {
      zoomer.zoomBy(-1);
    },
  };
}
