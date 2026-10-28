/* The map's renderer: everything the map draws, from the data it loads,
 * away from the page's main thread (render.js runs it in a worker), so that
 * fetching, decoding and above all rasterizing never hold up a pan or a
 * zoom. It touches no DOM: the page (map.js) sends it the view to draw, the
 * part of it left uncovered, colours and strings, and gets back each
 * drawing as an ImageBitmap with the view it is of.
 *
 * The background is our own geometry (files: see geo.py, in memory: topo.js).
 * At startup geo/coarse.json comes from the page, which preloads it: the
 * land, kraj and okres borders, obvod borders and the kraj, okres and obvod
 * labels. From zoom 9.5 the obce of every okres in view load from
 * geo/okres/<okres>/<lod>.json, the level of detail picked by the zoom
 * bands in geo/index.json, and shards that leave the view are dropped.
 * Loaded shards stay in a cache bounded by their vertices. From zoom 16 the
 * address files of the obce in view load and every house number is drawn.
 *
 * The countries around Slovakia (geo/neighbours/<lod>.json) are drawn below
 * it, duller, and are not picked by clicks or the layers. They reach under
 * its border, so its fill, at whatever level of detail, meets theirs at its
 * own border and hides the rest. Each is named at the one of the places
 * geo.py picked for it that leaves its name the most room in the view
 * (`drawNeighbourNames`). The lowest zoom keeps every view within them.
 *
 * The base map (base/, basemap.py: roads, railways, waters and buildings from
 * OpenStreetMap) loads with the shards, a file per okres at their level of
 * detail, and base/coarse.json with the coarse view. It is drawn faint (at
 * the theme's `base-alpha`) over the land and the results' fills, below
 * every border, highlight and label (`drawBase`), from cached paths per bin
 * and class, each class of line from the zoom it helps at: minor roads only
 * from zoom 13, the dense classes as hairlines below zoom 16, which keeps a
 * city view cheap to rasterize. So that no road or railway passes for a
 * border, they look as on the web maps people know: a wide road is a light
 * band in a casing, the major ones in yellow and orange (`BASE_ROADS`), a
 * railway a dark line with ticks across it (`BASE_RAILS`). The buildings
 * (base/obec/<obec>.json) load as the address files do, from the zoom in
 * base/index.json, for the obce in view (`loadBuildings`), and are filled
 * under the roads, cell by cell (`decodeBuildings`).
 *
 * Every geo file is a topology: each border is one arc, coded with the
 * highest boundary it is part of. Polygons are only filled (and hit tested
 * and highlighted); the lines are the arcs, each stroked once in the style
 * of its rank above all fills, and an overlay or highlight strokes the very
 * same arcs. Fills and lines are Path2D objects made once per shown shard
 * and scaled by the canvas transform (topo.js).
 *
 * An obec whose council obvod goes by address is one feature per obvod in
 * the shards (geo.py). The council overlay draws the borders between them,
 * dashed where drawn from the address points (approximate), with their
 * numbers; without it the obec is drawn whole. A click in it picks the
 * obvod there.
 *
 * The obvody of the three kinds of council (regional, Bratislava's and
 * Košice's city councils, municipal councils) are overlays, each switched on
 * or off on its own and drawn, when on, from the zoom where it reads
 * (`OVERLAYS`): the regional ones from the whole country, the cities' once
 * the cities are large enough, the municipal ones once the obce are. A
 * selected place highlights its obvod of the finest overlay drawn.
 *
 * The okrsky (polling districts) of the obce that have them drawn are
 * files of their own (geo/okrsky/<okres>/<lod>.json, geo/index.json
 * `okrsky`), loaded like the shards where the okrsky overlay is drawn or
 * the results show okrsky. They draw only the borders between two okrsky
 * of an obec (`OKRSOK`; the rest the shards draw), their numbers, the
 * selected place's okrsok, and a click picks the okrsok there too.
 *
 * The 2026 results (`setResults`, mapmode.js) colour the land in steps of
 * one colour, or a winner's in a colour of each candidate's (a tie in
 * stripes of the tied candidates' colours, `stepFill`), by the units
 * of the zoom, from the zoom each overlay draws its borders at (`OVERLAYS`
 * `lines`, whether the overlay is on or not): below the shards every
 * regional obvod by its own value or that of its obce together; in the
 * shards every obec by its own (or by its regional obvod's where only that
 * is known, election night); from the council overlay's zoom, the council
 * obvody of an obec drawn as its obvody by theirs (a council obvod's own
 * contest at every zoom, its obec having no value of it); from the okrsky
 * overlay's zoom, every okrsok drawn by its own, over its obec. An obec
 * without finer values keeps its own (`unitAt`). The fills are cached
 * paths like the land's, made again only when the values change, under
 * the borders and labels; every unit filled carries its value under its
 * label: an obec's name, a council obvod's or an okrsok's number, or for
 * a regional obvod at its label where no obec names stand for it. `hover`
 * tells the page which unit's fill is under the pointer, for its tooltip.
 *
 * Labels and house numbers are drawn above them with greedy collision
 * avoidance: thousands of DOM tooltips would be far too slow. Labels of
 * different kinds for one place (an obec's name, the number of its obvod)
 * are stacked rather than hiding each other, and an area partly in the
 * free part of the map (out from under the controls and pane) whose label
 * would not be is named in that part, or not at all where the label has no
 * room there: a name cut off reads as another. A street (or part of an
 * obec) chosen in the search is drawn too: a band around its houses under
 * the labels, a dot on each house above them. A click is resolved here by
 * point in polygon.
 *
 * Drawing goes by the latest view the page sent: views that come while one
 * is drawn are folded into the next drawing, and so is every file that
 * comes meanwhile; a drawing shows what has loaded, and a file that comes
 * later draws again. Zoom bands, styles and labels go by the whole level
 * below (`level`).
 */

import { addressFile, Cache, fetchJSON, setDataVersion, shownNumber } from './files.js';
import {
  addArc,
  addDashedArc,
  addFeature,
  arcOf,
  binPath,
  binsIn,
  borderArcs,
  boxContains,
  boxesIntersect,
  contains,
  decode,
  mercX,
  mercY,
  partAt,
  releasePaths,
  unionPath,
  Z0,
} from './topo.js';

const OKRES_ZOOM = 8;
// An obec is named once its area on screen is this many times the box of its
// name: the name then sits inside it and its borders stay readable. A 60 px
// name so needs an obec of about 40 km² at zoom 9.5 (towns), 20 km² at 10
// (and the larger villages), 5 km² at 11 (most villages) and 1.3 km² at 12.
const OBEC_ROOM = 3;
// Pixels kept clear around an obec name, so names never form a carpet.
const OBEC_GAP = 10;
const ADDRESS_ZOOM = 16;
const MAX_ADDRESS_FILES = 8;
// Shards kept loaded, in vertices (9 bytes each, with the paths of the ones
// shown about 30 more): about the obce of 300 km × 200 km at the finest
// level of detail.
const SHARD_VERTICES = 300000;
// Side of a bin of a shard (topo.js), in pixels at the lowest zoom the shard
// is drawn at: about a view, so that zoomed in only a few are drawn, and
// zoomed out there are not many.
const BIN_PIXELS = 1024;
// Pixels within which a click picks a house rather than the area.
const PICK_RADIUS = 14;
// The band around a highlighted street reaches this many metres beyond its
// houses, within these pixels: it must show in the view fitted to a long
// street and not cover the next street when zoomed in.
const STREET_REACH = 12;
const STREET_PIXELS = [5, 14];
// Houses of one street this many metres apart are not joined by the band:
// the street has a gap there, or is two streets with one name.
const STREET_GAP = 250;
const STREET_FILL = 0.18;

// Line codes of the geo files (geo.py): a rank, plus flags.
const RANK = 3;
const OKRES = 1;
const FLAG = { zsk: 4, city: 8 };
const FOREIGN = 16;
// A border between two council obvody within an obec, and one drawn from
// the address points (approximate). Drawn only by the council overlay.
const COUNCIL = 32;
const APPROX = 64;
// A border between two okrsky within an obec, the only lines the okrsky
// files draw (geo.py): their other arcs are FOREIGN, the shards' to draw.
// One that is also a council obvod border (COUNCIL) is drawn as an okrsok
// border only while the council overlay is not, which draws it then.
const OKRSOK = 128;
// Line layers of a file, drawn in this order: the kraj and state borders
// above the overlays, so that where an obvod border runs along one it still
// reads as that; the okrsky, finest, below every other.
const LINES = [
  'rank0',
  'okrsok',
  'okrsok-approx',
  'okrsok-council',
  'okrsok-council-approx',
  'rank1',
  'council',
  'approx',
  'zsk',
  'city',
  'rank2',
  'rank3',
];
// Dashes of an approximate council or okrsok border, in pixels.
const APPROX_DASH = [5, 4];
const OKRSOK_DASH = [3, 3];

// The base map (base/, basemap.py): its line classes, waterways first, each
// [code, colour, the width it is stroked at from each zoom level on:
// [[zoom, CSS px], …], not at all below the first; dense: whether it is a
// hairline below HAIRLINE_ZOOM]. The water areas (code 16) are filled.
const BASE_WATERWAYS = [
  [0, 'base-waterway', [[12, 0.6], [14, 0.9], [16, 1.3]], true], // streams
  [1, 'base-waterway', [[9, 0.6], [12, 0.9], [14, 1.3], [16, 2]], true], // canals
  [2, 'base-waterway', [[0, 1.2], [9, 1.2], [11, 1.4], [13, 1.8], [15, 2.5]], false], // rivers
];
// The roads, least first, so that a greater one runs over a lesser one where
// they meet. As on the web maps people know, and unlike any border, a road
// at least CASED_WIDTH wide is a band: stroked in its colour (the casing),
// then CASING narrower on each side in `<colour>-fill` over it, light (warm
// tints for the major classes); a narrower one is one line in its colour.
const BASE_ROADS = [
  // Minor roads from zoom 13 only: below it their mesh would grey the towns.
  [3, 'base-road', [[13, 1], [16, 2.4], [17, 3.5], [18, 5]], true],
  [4, 'base-road', [[12, 1], [16, 3], [17, 4.5], [18, 6.5]], true],
  [5, 'base-major', [[9, 0.6], [11, 0.9], [12, 1.2], [13, 1.6], [14, 2.2], [15, 3], [16, 4], [17, 6], [18, 8]], false],
  [6, 'base-major', [[9, 0.8], [11, 1.1], [12, 1.5], [13, 2], [14, 2.6], [15, 3.5], [16, 4.6], [17, 6.5], [18, 9]], false],
  [7, 'base-motorway', [[0, 1.2], [8, 1.4], [10, 1.6], [12, 2], [13, 2.4], [14, 3], [15, 4], [16, 5.2], [17, 7], [18, 10]], false],
  [8, 'base-motorway', [[0, 1.4], [8, 1.6], [10, 1.8], [12, 2.2], [13, 2.8], [14, 3.4], [15, 4.4], [16, 5.6], [17, 7.5], [18, 10]], false],
];
const CASED_WIDTH = 2.2;
const CASING = 0.7;
// The railways, over the roads: a line with ticks across it, the symbol of
// a railway on paper maps, which no border has; the trams thinner, lighter
// and with ticks only from zoom 14. Each is a line class, and its ticks
// from each zoom level on: [[zoom, [length across, width, gap]]] in CSS
// px, sparse: in Bratislava's rail yards they cost 2 ms of a drawing.
const BASE_RAILS = [
  [9, 'base-tram', [[12, 0.6], [14, 0.9], [16, 1.2]], true, [[14, [3, 1, 8]], [16, [4, 1.2, 10]]]],
  [10, 'base-rail', [[9, 0.7], [12, 0.9], [14, 1.2], [16, 1.6]], true, [[11, [3.5, 1, 9]], [14, [5, 1.2, 10]], [16, [6, 1.5, 12]]]],
];
// Below this zoom the dense classes (minor and tertiary streets, streams,
// railways) are at most one canvas pixel wide: the rasterizer draws those
// as hairlines, several times faster than a wider stroke, and in a city
// they are most of the lines in view (at zoom 15 in Bratislava, about 19
// ms of a drawing at their widths above against 6 ms). From it the view
// holds few enough of them to draw them wider.
const HAIRLINE_ZOOM = 16;
// Base map files kept loaded, in vertices, apart from the shards': about as
// many as the shards of the same okresy.
const BASE_VERTICES = 300000;
// Buildings files kept loaded (`loadBuildings`), in vertices: the obce of
// a few views of a city.
const BUILDING_VERTICES = 500000;
// The side of a cell of the buildings (`decodeBuildings`) in Z0 pixels:
// about 400 m, a sixth of a view across at zoom 16. Smaller cells leave
// fewer buildings out of view to fill: at zoom 16 in Bratislava (1440 ×
// 900 px) filling cells of 16 pixels took 11 ms, of 32 12 ms, whole obce
// 19 ms.
const BUILDING_BIN = 16;

// An overlay is drawn from zoom `lines`, its obvod numbers within
// `numbers` and the selected place's obvod highlighted within `highlight`
// (zooms by `level`): numbers and a highlight need the obvody neither much
// smaller nor much larger than the view.
const OVERLAYS = {
  zsk: { lines: 0, numbers: [9, 11], highlight: [0, 10] },
  city: { lines: 10, numbers: [11, 13], highlight: [10, 13] },
  oz: { lines: 11, numbers: [12, Infinity], highlight: [11, Infinity] },
  okrsky: { lines: 13, numbers: [14, Infinity], highlight: [13, Infinity] },
};
const within = (z, [from, to]) => z >= from && z <= to;

/* The value of *steps* ([[zoom, value], …], by zoom) from zoom *z* on, or
 * undefined below the first. */
const fromZoom = (steps, z) => steps.findLast(([from]) => z >= from)?.[1];

/* The level of detail of *bands* (geo/index.json: [{lod, zoom: [from,
 * to]}], `to` null for none) drawn at zoom *z*, or null for none. */
const lodAt = (bands, z) => bands.find((b) => z >= b.zoom[0] && (b.zoom[1] === null || z < b.zoom[1]))?.lod ?? null;

/* The side of a bin of a file of *band* (topo.js `decode`) in Z0 pixels:
 * BIN_PIXELS at the lowest zoom it is drawn at. */
const bandBinSize = (band) => BIN_PIXELS / 2 ** (band.zoom[0] - Z0);

/* The side of a bin of the files of each level of detail of *bands*. */
const binSizes = (bands) => Object.fromEntries(bands.map((b) => [b.lod, bandBinSize(b)]));

/* The vertices of a decoded file, by which the caches of files weigh it. */
const vertices = (file) => file.xy.length / 2;

// A file that fails to load is reported; the map goes on without it.
const logError = (e) => console.error(e);

// The theme's colours by name (map.js `readColors`), as the page last sent.
const COLOR = {};

// How much of a turnout's tone each step of the results has, the rest the
// land's, lowest first (app.css `.map-legend.toned` mixes the same).
const TONE_STEPS = [0.15, 0.32, 0.49, 0.66, 0.83, 1];

// CSS pixels each colour of a tie's stripes takes along a row (some 4
// across): broad enough to read at any zoom, as they keep to the screen
// rather than scale with the map.
const STRIPE = 6;

/* Colour *b* mixed into *a* by *f* (both #rrggbb), as CSS color-mix(in
 * srgb) mixes them. */
function mix(a, b, f) {
  const channel = (hex, i) => Number.parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  const rgb = [0, 1, 2].map((i) => Math.round(channel(a, i) + (channel(b, i) - channel(a, i)) * f));
  return `rgb(${rgb.join(' ')})`;
}

/* Line style of a rank (0 obec … 3 country) at zoom *z*. */
function rankStyle(rank, z) {
  if (rank === 0) return { color: COLOR.obec, weight: z >= 14 ? 1 : z >= 12 ? 0.8 : 0.6 };
  if (rank === OKRES) return { color: COLOR.okres, weight: z >= 12 ? 1.2 : 0.9 };
  return { color: COLOR.kraj, weight: rank === 2 ? 1.3 : 1.5 };
}

// The okrsok line layers by the bits of their arcs' codes.
const OKRSOK_LAYERS = {
  okrsok: OKRSOK,
  'okrsok-approx': OKRSOK | APPROX,
  'okrsok-council': OKRSOK | COUNCIL,
  'okrsok-council-approx': OKRSOK | COUNCIL | APPROX,
};

/* Whether an arc with line code *code* belongs to line layer *name*. */
function inLayer(name, code) {
  if (name in FLAG) return (code & FLAG[name]) !== 0;
  if (name in OKRSOK_LAYERS) return (code & (OKRSOK | COUNCIL | APPROX)) === OKRSOK_LAYERS[name];
  if (name === 'council') return (code & (COUNCIL | APPROX)) === COUNCIL;
  if (name === 'approx') return (code & APPROX) !== 0;
  return (code & COUNCIL) === 0 && (code & RANK) === Number(name.slice(4));
}

/* Line style of line layer *name* at zoom *z*. */
function lineStyle(name, z) {
  if (name in FLAG) return { color: COLOR[name], weight: 2 };
  if (name === 'council' || name === 'approx') {
    return { color: COLOR.council, weight: z >= 14 ? 2 : 1.5, dash: name === 'approx' ? APPROX_DASH : null };
  }
  if (name in OKRSOK_LAYERS) {
    const dash = (OKRSOK_LAYERS[name] & APPROX) !== 0 ? OKRSOK_DASH : null;
    return { color: COLOR.okrsok, weight: z >= 15 ? 1.2 : 0.9, dash };
  }
  return rankStyle(Number(name.slice(4)), z);
}

const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
// Okres and obec names: one muted style, so names stay below the borders.
const NAME_SIZE = 12;
const NAME_FONT = `600 ${NAME_SIZE}px ${FONT}`;
const KRAJ_FONT = `700 14px ${FONT}`;
const OBVOD_FONT = `700 12px ${FONT}`;
// An okrsok's number: lighter than an obvod's, as the finer unit.
const OKRSOK_FONT = `600 12px ${FONT}`;
// How far below a 12 px name or number its result value goes: their boxes
// (`drawText`, 14 px high) just touch, so the value is not stacked above.
const VALUE_DROP = 14;
const HOUSE_SIZE = 11;
const HOUSE_FONT = `${HOUSE_SIZE}px ${FONT}`;
// Names of the countries around: capitals, spaced out, as maps name what is
// beyond their subject. The font is used for nothing else, so the widths
// measured with the spacing stay apart from the others'.
const NEIGHBOUR_SIZE = 11;
const NEIGHBOUR_FONT = `600 ${NEIGHBOUR_SIZE}px ${FONT}`;
const NEIGHBOUR_SPACING = '2px';
// The dashes of their borders, in pixels.
const NEIGHBOUR_DASH = [6, 4];

// Side of a bucket of the labels' grid (`Placer`), in pixels.
const BUCKET = 64;

/* Labels are placed greedily in priority order; a grid of buckets keeps the
 * overlap test cheap with thousands of house numbers. A label is
 * {box: [x0, y0, x1, y1], gap, kind, area}: its box (with a pixel or two
 * around the text), the pixels kept clear around it, its kind ('obec',
 * 'zsk', 'house'…) and the area it names, if any: {own, over}, its key
 * ('obec:<code>', 'zsk:<kraj>/<n>'…, see `cellKeys`) and the keys of the
 * areas it overlaps, its own among them. */
class Placer {
  grid = new Map();

  /* The keys of the grid's buckets that *label* reaches into, its gap
   * included. */
  *buckets(label) {
    const [x0, y0, x1, y1] = label.box;
    const { gap } = label;
    for (let gx = Math.floor((x0 - gap) / BUCKET); gx <= Math.floor((x1 + gap) / BUCKET); gx++) {
      for (let gy = Math.floor((y0 - gap) / BUCKET); gy <= Math.floor((y1 + gap) / BUCKET); gy++) {
        // One number a bucket: no canvas is anywhere near 100003 buckets high.
        yield gx * 100003 + gy;
      }
    }
  }

  /* The labels placed that *label* would overlap, or null if one of them is
   * one it cannot stack with (`stackable`). Those it can stack with keep no
   * gap to it. */
  overlaps(label) {
    const [x0, y0, x1, y1] = label.box;
    const { gap } = label;
    const out = [];
    for (const key of this.buckets(label)) {
      for (const r of this.grid.get(key) ?? []) {
        const [rx0, ry0, rx1, ry1] = r.box;
        const g = gap + r.gap;
        if (!(x0 - g < rx1 && x1 + g > rx0 && y0 - g < ry1 && y1 + g > ry0)) continue;
        if (!stackable(label, r)) return null;
        if (x0 < rx1 && x1 > rx0 && y0 < ry1 && y1 > ry0) out.push(r);
      }
    }
    return out;
  }

  add(label) {
    for (const key of this.buckets(label)) {
      const bucket = this.grid.get(key);
      if (bucket) bucket.push(label);
      else this.grid.set(key, [label]);
    }
  }
}

/* Whether labels *a* and *b* name one place: they are of different kinds and
 * their areas overlap, as an obec's name and the number of its council
 * obvod, or of the regional obvod it is in. Neither may hide the other. */
function stackable(a, b) {
  if (a.kind === b.kind || !a.area || !b.area) return false;
  return b.area.over.includes(a.area.own) || a.area.over.includes(b.area.own);
}

// How many labels of one place a label may be stacked above or below.
const STACK = 3;

/* The keys of the areas a coarse cell or an obec with properties *p* lies in
 * (see `Placer`): its kraj, okres, regional obvod and city obvod. */
function cellKeys(p) {
  const keys = [`kraj:${p.kraj}`, `okres:${p.okres}`, `zsk:${p.kraj}/${p.zsk}`];
  if (p.city) keys.push(`oz:${p.city}/${p.city_obvod}`);
  return keys;
}

// Widths of texts by font: the same names and house numbers are measured on
// every redraw. Cleared when it grows past the bound.
const widths = new Map();

function textWidth(ctx, font, text) {
  const key = `${font}\n${text}`;
  let w = widths.get(key);
  if (w === undefined) {
    if (widths.size > 20000) widths.clear();
    ctx.font = font;
    w = ctx.measureText(text).width;
    widths.set(key, w);
  }
  return w;
}

/* Draws *text* (*font*, *size* px high, centred on (x, y) or, by *align*
 * 'left', from it) unless it would overlap one already placed; *gap*
 * pixels around it are kept clear of later labels. Where it would cover
 * labels of its place only (`stackable`), it goes just above them, or else
 * below, so that both read; if it is wholly within *bounds* [x0, y0, x1,
 * y1], it stays so. *kind* and *area* as in `Placer`. Returns the y it was
 * drawn at, or null where it was not. */
function drawText(ctx, placer, text, x, y, font, size, color, style = {}) {
  const { align = 'center', gap = 0, halo = COLOR.halo, kind = null, area = null, bounds = null } = style;
  const w = textWidth(ctx, font, text);
  const x0 = align === 'center' ? x - w / 2 : x;
  const half = size / 2 + 1;
  const label = { box: [x0 - 2, y - half, x0 + w + 2, y + half], gap, kind, area };
  const inside =
    bounds !== null &&
    label.box[0] >= bounds[0] &&
    label.box[2] <= bounds[2] &&
    y - half >= bounds[1] &&
    y + half <= bounds[3];
  const at = (cy) => {
    label.box[1] = cy - half;
    label.box[3] = cy + half;
    return placer.overlaps(label);
  };
  const hits = at(y);
  if (!hits) return null;
  // Above the labels of its place it would cover, or else below: a step
  // clear of those met at each, up to STACK of them. The box is left where
  // it was last tried.
  let cy = y;
  if (hits.length) {
    cy = null;
    for (const dir of [-1, 1]) {
      let met = hits;
      let ty = y;
      for (let i = 0; i < STACK && met?.length; i++) {
        ty = dir < 0 ? Math.min(...met.map((r) => r.box[1])) - half : Math.max(...met.map((r) => r.box[3])) + half;
        met = inside && (ty - half < bounds[1] || ty + half > bounds[3]) ? null : at(ty);
      }
      if (met?.length === 0) {
        cy = ty;
        break;
      }
    }
    if (cy === null) return null;
  }
  placer.add(label);
  ctx.font = font;
  ctx.textAlign = align;
  ctx.lineWidth = 3;
  ctx.strokeStyle = halo;
  ctx.strokeText(text, x, cy);
  ctx.fillStyle = color;
  ctx.fillText(text, x, cy);
  return cy;
}

/* Squared distance from (px, py) to the segment (ax, ay)–(bx, by). */
function segmentDistance2(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const l2 = dx * dx + dy * dy;
  const t = l2 ? Math.min(Math.max(((px - ax) * dx + (py - ay) * dy) / l2, 0), 1) : 0;
  return (ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2;
}

// Precision of `visibleSpot` in pixels, the most points it tries (a label
// needs no finer place, and a redraw must stay quick however intricate the
// area), and the weight it gives the plain room.
const SPOT_PRECISION = 2;
const SPOT_PROBES = 1500;
const SPOT_ROUND = 0.02;

/* Where in the part of *area* ({file, features, box}) inside *rect* [x0,
 * y0, x1, y1] (CSS pixels of the canvas in *view*) a box *w* × *h* centred
 * has the most room: {x, y}, or null if it fits nowhere there. The pole of
 * inaccessibility (polylabel: cells searched best first, each bounded by
 * its centre's value plus its half diagonal times the most the value
 * changes per pixel) of that part with x scaled by h / w, which makes the
 * box a square: the room is that of a box of the label's shape, not of a
 * circle. A part wider than that box's shape leaves it room to slide up
 * and down, all of it as good: a little of the plain room (SPOT_ROUND)
 * added picks the middle. The border of the area is its arcs in an odd
 * number of its rings (an area of several features is their union). Only
 * its segments across the rows of *rect* count, and of those the ones
 * right of it only for telling inside (a ray to the right crosses them):
 * any other is further from a point inside than a side of *rect*. */
function visibleSpot(area, rect, view, w, h) {
  const { file, box } = area;
  const { k } = view;
  const s = h / w;
  const need = h / Math.SQRT2;
  // The part of the rect the area's box covers.
  const x0 = Math.max(rect[0], box[0] * k - view.x);
  const y0 = Math.max(rect[1], box[1] * k - view.y);
  const x1 = Math.min(rect[2], box[2] * k - view.x);
  const y1 = Math.min(rect[3], box[3] * k - view.y);
  if ((x1 - x0) * s < 2 * need || y1 - y0 < 2 * need) return null;
  const { xy, start } = file;
  const [ox, oy] = file.origin;
  const near = [];
  // The rows spanned by the segments right of the rect: y0, y1 of each.
  const right = [];
  for (const a of borderArcs(area.features).keys()) {
    let px = 0;
    let py = 0;
    for (let i = start[a]; i < start[a + 1]; i++) {
      const x = (xy[2 * i] + ox) * k - view.x;
      const y = (xy[2 * i + 1] + oy) * k - view.y;
      const across = (py >= rect[1] || y >= rect[1]) && (py <= rect[3] || y <= rect[3]);
      if (i > start[a] && across && (px >= rect[0] || x >= rect[0])) {
        if (px > rect[2] && x > rect[2]) right.push(py, y);
        else near.push(px, py, x, y);
      }
      px = x;
      py = y;
    }
  }
  // The room at (x, y), [scaled, plain]: the signed distance to the edge
  // of the part. Inside, to the nearer of the area's border and the rect's
  // sides; outside, where a bound will do, minus that to the nearer of the
  // border taken and the sides of the rect (0 beyond them, where the
  // crossings no longer tell inside).
  const room = (x, y) => {
    let inside = false;
    for (let i = 0; i < right.length; i += 2) if (right[i] > y !== right[i + 1] > y) inside = !inside;
    let scaled = Infinity;
    let plain = Infinity;
    for (let i = 0; i < near.length; i += 4) {
      const ax = near[i];
      const ay = near[i + 1];
      const bx = near[i + 2];
      const by = near[i + 3];
      if (ay > y !== by > y && x < ((bx - ax) * (y - ay)) / (by - ay) + ax) inside = !inside;
      scaled = Math.min(scaled, segmentDistance2(x * s, y, ax * s, ay, bx * s, by));
      plain = Math.min(plain, segmentDistance2(x, y, ax, ay, bx, by));
    }
    const rows = Math.min(y - rect[1], rect[3] - y);
    const sides = Math.min(x - rect[0], rect[2] - x);
    if (!inside) {
      return [
        -Math.min(Math.sqrt(scaled), Math.max(Math.min(rows, sides * s), 0)),
        -Math.min(Math.sqrt(plain), Math.max(Math.min(rows, sides), 0)),
      ];
    }
    return [Math.min(Math.sqrt(scaled), rows, sides * s), Math.min(Math.sqrt(plain), rows, sides)];
  };
  // Cells in the scaled plane, where the plain room changes by up to 1 / s
  // per pixel.
  const slope = 1 + SPOT_ROUND / s;
  const cell = (x, y, half) => {
    const [d, plain] = room(x / s, y);
    const value = d + SPOT_ROUND * plain;
    return { x, y, half, d, value, max: value + slope * half * Math.SQRT2 };
  };
  const heap = new CellHeap();
  const size = Math.min((x1 - x0) * s, y1 - y0);
  for (let x = x0 * s; x < x1 * s; x += size) {
    for (let y = y0; y < y1; y += size) heap.push(cell(x + size / 2, y + size / 2, size / 2));
  }
  let best = cell(((x0 + x1) / 2) * s, (y0 + y1) / 2, 0);
  let probes = heap.length;
  while (heap.length && probes < SPOT_PROBES) {
    const c = heap.pop();
    if (c.value > best.value) best = c;
    // A cell that cannot hold a better spot, or one with room, is done.
    if (c.max - best.value <= SPOT_PRECISION || c.d + c.half * Math.SQRT2 < need) continue;
    const half = c.half / 2;
    for (const [dx, dy] of QUARTERS) heap.push(cell(c.x + dx * half, c.y + dy * half, half));
    probes += 4;
  }
  return best.d >= need ? { x: Math.round(best.x / s), y: Math.round(best.y) } : null;
}

// The directions of the quarters of a cell from its centre.
const QUARTERS = [
  [-1, -1],
  [1, -1],
  [-1, 1],
  [1, 1],
];

/* The cells `visibleSpot` has yet to search, the one that may hold the
 * most room (`max`) on top: a binary max-heap. */
class CellHeap {
  items = [];

  get length() {
    return this.items.length;
  }

  push(c) {
    const heap = this.items;
    let i = heap.length;
    heap.push(c);
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (heap[parent].max >= c.max) break;
      heap[i] = heap[parent];
      i = parent;
    }
    heap[i] = c;
  }

  pop() {
    const heap = this.items;
    const top = heap[0];
    const last = heap.pop();
    if (heap.length) {
      let i = 0;
      for (;;) {
        let m = 2 * i + 1;
        if (m >= heap.length) break;
        if (m + 1 < heap.length && heap[m + 1].max > heap[m].max) m++;
        if (heap[m].max <= last.max) break;
        heap[i] = heap[m];
        i = m;
      }
      heap[i] = last;
    }
    return top;
  }
}

/* Sets the transform of *ctx* to draw the coordinates of *file* in *view*. */
function placeFile(ctx, file, view) {
  const s = view.ratio * view.k;
  const [ox, oy] = file.origin;
  ctx.setTransform(s, 0, 0, s, view.ratio * (ox * view.k - view.x), view.ratio * (oy * view.k - view.y));
}

/* Fills each of *bins* with its path *key* at zoom level *z* (`binPath`),
 * made by *make(bin)*, even-odd. */
function fillBins(ctx, bins, z, key, make) {
  for (const bin of bins) {
    const path = binPath(bin, key, z, () => make(bin));
    if (path) ctx.fill(path, 'evenodd');
  }
}

/* Strokes the path *key* of each of *bins*, as `fillBins` fills. */
function strokeBins(ctx, bins, z, key, make) {
  for (const bin of bins) {
    const path = binPath(bin, key, z, () => make(bin));
    if (path) ctx.stroke(path);
  }
}

/* The water areas of *bin* of base map *file* as one path at zoom level
 * *z*, or null. */
function waterPath(file, bin, z) {
  if (!bin.features.length) return null;
  const path = new Path2D();
  for (const f of bin.features) addFeature(path, file, f, z);
  return path;
}

/* The buildings of an obec (base/obec/<code>.json: {scale, counts, xy},
 * the rings' vertices delta coded in 1/scale degree, one sequence for the
 * whole file, each hole after its outer ring) as {origin, cells,
 * vertices}: in Z0 pixels relative to *origin* as a decoded geo file
 * (`placeFile`), a path for each cell of BUILDING_BIN pixels a building
 * starts in, with its holes, for the nonzero rule (they wind the other
 * way), and the box around it: {box, path}. A drawing fills only the
 * cells in view: an obec's buildings are several times those in view. */
function decodeBuildings({ scale, counts, xy }) {
  const ox = mercX(xy[0] / scale);
  const oy = mercY(xy[1] / scale);
  const cells = new Map();
  let cell = null;
  const ring = [];
  let lon = 0;
  let lat = 0;
  let i = 0;
  for (const n of counts) {
    ring.length = 0;
    let area = 0;
    for (let j = 0; j < n; j++, i += 2) {
      lon += xy[i];
      lat += xy[i + 1];
      ring.push(mercX(lon / scale) - ox, mercY(lat / scale) - oy);
      if (j) area += ring[2 * j - 2] * ring[2 * j + 1] - ring[2 * j] * ring[2 * j - 1];
    }
    area += ring[2 * n - 2] * ring[1] - ring[0] * ring[2 * n - 1];
    // An outer ring winds counter-clockwise in lon/lat, so its area by the
    // shoelace formula is negative with y down; a hole goes with its outer
    // ring.
    if (area < 0 || !cell) {
      const key = `${Math.floor(ring[0] / BUILDING_BIN)} ${Math.floor(ring[1] / BUILDING_BIN)}`;
      cell = cells.get(key);
      if (!cell) {
        cell = { box: emptyBox(), path: new Path2D() };
        cells.set(key, cell);
      }
    }
    const { box, path } = cell;
    path.moveTo(ring[0], ring[1]);
    for (let k = 0; k < ring.length; k += 2) {
      if (k) path.lineTo(ring[k], ring[k + 1]);
      box[0] = Math.min(box[0], ring[k] + ox);
      box[1] = Math.min(box[1], ring[k + 1] + oy);
      box[2] = Math.max(box[2], ring[k] + ox);
      box[3] = Math.max(box[3], ring[k + 1] + oy);
    }
    path.closePath();
  }
  return { origin: [ox, oy], cells: [...cells.values()], vertices: i / 2 };
}

/* The arcs of *file* among *arcs* this file draws whose code passes
 * *pick*, as one path at zoom level *z*, or null if there are none. */
function linesPath(file, arcs, pick, z) {
  const path = new Path2D();
  let any = false;
  for (const a of arcs) {
    const code = file.lines[a];
    if (code & FOREIGN || !pick(code)) continue;
    addArc(path, file, a, z);
    any = true;
  }
  return any ? path : null;
}

/* The dashes, *dash* CSS pixels long and apart (setLineDash), of the arcs
 * of *file* in *bins* whose code passes *pick* that *view* shows, as one
 * path to stroke without a dash pattern (topo.js `addDashedArc`), or null
 * if there are none. Made for each drawing: it depends on the view. */
function dashedPath(file, bins, view, dash, pick) {
  const [ox, oy] = file.origin;
  // A cap reaching into the canvas from a dash just outside it.
  const m = 4 / view.k;
  const box = [view.box[0] - ox - m, view.box[1] - oy - m, view.box[2] - ox + m, view.box[3] - oy + m];
  const lengths = dash.map((d) => d / view.k);
  const z = Math.floor(view.zoom);
  const path = new Path2D();
  let any = false;
  for (const bin of bins) {
    for (const a of bin.arcs) {
      const code = file.lines[a];
      if (code & FOREIGN || !pick(code)) continue;
      addDashedArc(path, file, a, box, lengths, z);
      any = true;
    }
  }
  return any ? path : null;
}

/* The box [x0, y0, x1, y1] around nothing, for `grow` to widen. */
const emptyBox = () => [Infinity, Infinity, -Infinity, -Infinity];

/* Widens *box* to take in box *b*. */
function grow(box, b) {
  box[0] = Math.min(box[0], b[0]);
  box[1] = Math.min(box[1], b[1]);
  box[2] = Math.max(box[2], b[2]);
  box[3] = Math.max(box[3], b[3]);
}

/* The box around *features*. */
function boxOf(features) {
  const box = emptyBox();
  for (const f of features) grow(box, f.box);
  return box;
}

// The length of the equator, in metres (EPSG:3857).
const EQUATOR = 40075016.686;

/* The metres a pixel spans at latitude *lat* at *zoom*. */
const metresPerPixel = (lat, zoom) => (EQUATOR * Math.cos((lat * Math.PI) / 180)) / (256 * 2 ** zoom);

/* The point (x, y) in Z0 pixels in CSS pixels of the canvas of *view*:
 * whole pixels, as Leaflet's layer points, so that labels whose boxes just
 * touch do not overlap. */
const pixelAt = (view, x, y) => ({ x: Math.round(x * view.k) - view.x, y: Math.round(y * view.k) - view.y });

/* The point (lat, lon) likewise. */
const toPixel = (view, lat, lon) => pixelAt(view, mercX(lon), mercY(lat));

/* The part of *view* the map shows (not the canvas around it) and *pad*
 * times its size on every side, in Z0 pixels. */
function viewPixels(view, pad) {
  const [x0, y0, x1, y1] = view.visible;
  const dx = (x1 - x0) * pad;
  const dy = (y1 - y0) * pad;
  const { k } = view;
  return [(view.x + x0 - dx) / k, (view.y + y0 - dy) / k, (view.x + x1 + dx) / k, (view.y + y1 + dy) / k];
}

/* The first feature of *file* whose properties pass *which* that holds the
 * point (x, y) in Z0 pixels, or undefined. */
const featureAt = (file, x, y, which = () => true) =>
  file.features.find((f) => which(f.properties) && boxContains(f.box, x, y) && contains(file, f, x, y));

/* [x, y] in Z0 pixels of every house of address *group*, NaN where it has
 * no point; made once per group. */
const houseCache = new WeakMap();

function housePixels(group) {
  let xy = houseCache.get(group);
  if (!xy) {
    xy = new Float64Array(2 * group.lon.length);
    for (let i = 0; i < group.lon.length; i++) {
      xy[2 * i] = mercX(group.lon[i]);
      xy[2 * i + 1] = mercY(group.lat[i]);
    }
    houseCache.set(group, xy);
  }
  return xy;
}

/* The located houses of the street or part of the obec that *p* ({obec,
 * street?, part?}) names: {points: [[lat, lon]], edges: [[i, j]]}, the edges
 * those of a minimum spanning tree of the points (without the ones longer
 * than STREET_GAP), which traces the street. Null if *p* names none or it
 * has no located house. */
async function streetShape(p) {
  const kind = p.street ? 'streets' : p.part ? 'parts' : null;
  if (!kind) return null;
  const name = p.street ?? p.part;
  const file = await addressFile(p.obec);
  const group = file.groups.find((g) => g.kind === kind && g.name === name);
  if (!group) return null;
  const points = [];
  for (let i = 0; i < group.lat.length; i++) {
    if (!Number.isNaN(group.lat[i])) points.push([group.lat[i], group.lon[i]]);
  }
  return points.length ? { points, edges: spanningTree(points) } : null;
}

/* Prim's algorithm on the plane: a street has at most a few hundred houses. */
function spanningTree(points) {
  const n = points.length;
  const metres = 111320;
  const across = metres * Math.cos((points[0][0] * Math.PI) / 180);
  const best = new Float64Array(n).fill(Infinity);
  const from = new Int32Array(n);
  const done = new Uint8Array(n);
  const edges = [];
  let current = 0;
  for (let k = 1; k < n; k++) {
    done[current] = 1;
    const [lat, lon] = points[current];
    let next = -1;
    for (let j = 0; j < n; j++) {
      if (done[j]) continue;
      const d = ((points[j][0] - lat) * metres) ** 2 + ((points[j][1] - lon) * across) ** 2;
      if (d < best[j]) {
        best[j] = d;
        from[j] = current;
      }
      if (next < 0 || best[j] < best[next]) next = j;
    }
    if (best[next] <= STREET_GAP ** 2) edges.push([from[next], next]);
    current = next;
  }
  return edges;
}

/* The renderer of the map, once geo/coarse.json is decoded (an error if it
 * cannot be). *geoIndex* is geo/index.json, *coarse* the bytes of
 * geo/coarse.json, *dataVersion* the build's (files.js `setDataVersion`),
 * *colors* the theme's (`COLOR`), *strings* the labels'
 * {obvod: 'No. {n}', countries: {AT: 'Austria', …}} in the page's language,
 * *surface(w, h)* makes a canvas and *present(canvas, view, seq)* hands a
 * drawing of *view* over (the page's latest view: its *seq*). The methods
 * are what render.js passes the page's messages to. */
export async function createRenderer({ geoIndex, coarse: bytes, dataVersion, colors, strings, surface, present }) {
  // In a worker this module has its own files.js, which the page's config
  // did not reach.
  setDataVersion(dataVersion);
  Object.assign(COLOR, colors);
  const coarse = decode(JSON.parse(new TextDecoder().decode(bytes)), Infinity);
  // The regional obvody that hold a part of Bratislava or Košice.
  const cityZsk = new Set(
    coarse.features.filter((f) => f.properties.city).map((f) => `zsk:${f.properties.kraj}/${f.properties.zsk}`),
  );
  /* The areas the labels name, as `Placer` and `visibleSpot` take them:
   * {own, over, file, features, box}. Those of coarse.json by key
   * ('kraj:1', 'okres:101', 'zsk:1/1', 'oz:BA/1'), each the union of its
   * cells, which overlaps the areas of every one of them. */
  const coarseAreas = new Map();
  for (const f of coarse.features) {
    const keys = cellKeys(f.properties);
    for (const own of keys) {
      let a = coarseAreas.get(own);
      if (!a) {
        a = { own, over: [own], file: coarse, features: [], box: emptyBox() };
        coarseAreas.set(own, a);
      }
      a.features.push(f);
      grow(a.box, f.box);
      for (const key of keys) if (!a.over.includes(key)) a.over.push(key);
    }
  }
  /* Those of the features of shard *file*, made on first use: feature →
   * {feature, obec, piece}. `obec` is the whole obec ('obec:<code>'), with
   * `label` its feature that holds its label and `area` its area (topo.js);
   * `piece` its council obvod ('council:<code>/<n>') where the obec is cut
   * into them, else null. */
  const shardAreas = new WeakMap();
  function areasOf(file) {
    let areas = shardAreas.get(file);
    if (areas) return areas;
    areas = new Map();
    const obce = new Map();
    for (const f of file.features) {
      const p = f.properties;
      let obec = obce.get(p.id);
      if (!obec) {
        const own = `obec:${p.id}`;
        obec = { own, over: [own, ...cellKeys(p)], file, features: [], box: emptyBox(), label: null, area: 0 };
        obce.set(p.id, obec);
      }
      obec.features.push(f);
      grow(obec.box, f.box);
      obec.area += f.area;
      if (f.lx !== undefined) obec.label = f;
      const own = `council:${p.id}/${p.oz}`;
      const piece = p.oz ? { own, over: [own, ...obec.over], file, features: [f], box: f.box } : null;
      areas.set(f, { feature: f, obec, piece });
    }
    shardAreas.set(file, areas);
    return areas;
  }
  const bands = geoIndex.shards;
  const coarsestLod = bands[0].lod;
  const binSize = binSizes(bands);
  const lodFor = (z) => lodAt(bands, z);
  // The okrsky (polling districts) of the obce that have them drawn
  // (geo/index.json `okrsky`): a file per okres and level of detail, in
  // bands of their own.
  const okrsokBands = geoIndex.okrsky.bands;
  const okrsokBinSize = binSizes(okrsokBands);
  const okrsokObce = new Set(Object.keys(geoIndex.okrsky.drawn));

  // The countries around: the finest level whose band has begun at the zoom
  // and whose extent holds all that is drawn (a very large view keeps a
  // coarser one). {lod, file} once one has come.
  const neighbourBands = [...geoIndex.neighbours].sort((a, b) => b.zoom[0] - a.zoom[0]);
  const neighbourFiles = new Cache(Infinity);
  let neighbours = null;
  const neighbourBand = (zoom, box) =>
    neighbourBands.find(
      (b) =>
        zoom >= b.zoom[0] && b.extent[0] <= box[0] && b.extent[1] <= box[1] && b.extent[2] >= box[2] && b.extent[3] >= box[3],
    ) ?? neighbourBands.at(-1);
  const loadNeighbours = (band) =>
    neighbourFiles.get(band.lod, async () =>
      decode(await fetchJSON(`/geo/neighbours/${band.lod}.json`), bandBinSize(band)),
    );

  // The overlays switched on, and the number of council obvody of every obec
  // (data/index.json), which the council overlay colours them by.
  let overlays = { zsk: true, city: true, oz: true, okrsky: true, base: true, buildings: true };
  let councils = null;
  // The 2026 results shown (`setResults`): {steps, tone, palette, obce,
  // zsk, councils, okrsky, okrsokObce}, `tone` 'result' (the colours
  // `result-<n>`) or the colour a turnout is mixed from ('accent',
  // 'council', 'city', 'zsk'); `palette`, where set, the colour of each step
  // by name instead (a winner's, `series-<n>`, or a tie's several names,
  // in stripes: `stepFill`); `obce` obec code → [step, text], `zsk`
  // '<kraj>/<n>' → [step, text, whole], `whole` where the obvod is known
  // only as a whole, `councils` '<obec>/<n>' → [step, text] a municipal
  // council obvod's, `okrsky` '<obec>/<n>' → [step, text] an okrsok's,
  // `okrsokObce` the obce those are of; null for none.
  let results = null;
  const zskOf = (p) => `${p.kraj}/${p.zsk}`;
  const okrsokKey = (p) => `${p.obec}/${p.okrsok}`;
  // The selected place (`select`): {obec, info, lat?, lon?, label?, obvod?,
  // okrsok?, shape} or {area}; null for none.
  let place = null;
  // Counts calls of `select`: a slower one that comes back late is dropped.
  let selection = 0;
  // The selected obec for when its shard is not drawn: {code, obec}, obec
  // from the coarsest shard (`featureOf`) once that has come.
  let selectedObec = null;
  // The page's latest view: {view, free, seq} (`show`).
  let current = null;
  const level = () => Math.floor(current.view.zoom);
  // okres → {lod, file}: the shards drawn; the okresy in view and the level
  // of detail they are wanted at (`refresh`).
  const shown = new Map();
  let wanted = new Set();
  let wantedLod = null;
  // okres → {lod, file}: the okrsky files drawn, and as for the shards those
  // wanted (`refresh`).
  const okrskyShown = new Map();
  let okrskyWanted = new Set();
  let okrskyLod = null;
  const shards = new Cache(SHARD_VERTICES, vertices);
  const addresses = new Map();
  let wantedAddresses = new Set();

  const loadShard = (okres, lod) =>
    shards.get(`${okres}/${lod}`, async () =>
      decode(await fetchJSON(`/geo/okres/${okres}/${lod}.json`), binSize[lod]),
    );
  const loadOkrsky = (okres, lod) =>
    shards.get(`okrsky/${okres}/${lod}`, async () => {
      const file = decode(await fetchJSON(`/geo/okrsky/${okres}/${lod}.json`), okrsokBinSize[lod]);
      file.okrsky = true;
      return file;
    });
  // The base map: okres → {lod, file} drawn, as the shards, and the coarse
  // view's file once it has come (small, kept). Its paths are cached per
  // bin like the shards' (`drawBase`) and let go when it is no longer drawn.
  const baseShown = new Map();
  let baseCoarse = null;
  const baseFiles = new Cache(BASE_VERTICES, vertices);
  const loadBase = (path, size) => baseFiles.get(path, async () => decode(await fetchJSON(`/base/${path}`), size));
  // The buildings (`loadBuildings`): base/index.json `buildings`, {zoom,
  // obce: Set of the codes that have a file}, once it has come; obec code
  // → its decoded file (`decodeBuildings`) drawn, and those wanted.
  let buildingsIndex = null;
  let buildingsAsked = false;
  const buildingsShown = new Map();
  let wantedBuildings = new Set();
  const buildingFiles = new Cache(BUILDING_VERTICES, (file) => file.vertices);
  const loadBuildingFile = (code) =>
    buildingFiles.get(code, async () => decodeBuildings(await fetchJSON(`/base/obec/${code}.json`)));

  const drawsOverlay = (name, z) => overlays[name] && z >= OVERLAYS[name].lines;
  // The results' units of the council obvody and of the okrsky show from
  // the zoom their overlay draws their borders at, whether it is on or not.
  const showsUnits = (name, z) => z >= OVERLAYS[name].lines;
  // Whether the okrsky files are wanted at zoom *z*: for their borders, or
  // for the results by okrsok.
  const wantsOkrsky = (z) => drawsOverlay('okrsky', z) || (Boolean(results?.okrsky.size) && showsUnits('okrsky', z));

  /* The fill of the obce: [name, colour, which] for each group at zoom *z*,
   * *which(feature)* telling its members. */
  function fillGroups(z) {
    if (!drawsOverlay('oz', z) || !councils) return [['all', COLOR.land, () => true]];
    const count = (f) => councils[f.properties.id] ?? 0;
    // An obec whose council obvod goes by address is drawn as its obvody.
    const known = (f) => count(f) === 1 || 'oz' in f.properties;
    return [
      ['oz-land', COLOR.land, known],
      ['oz-pending', COLOR.pending, (f) => !known(f) && count(f) > 1],
      ['oz-none', COLOR.none, (f) => count(f) === 0],
    ];
  }

  /* The unit of the results whose value a feature with properties *p* in
   * the shards is filled with at zoom *z*, as [kind, key] (`results`):
   * its council obvod where it is one, from the zoom of their units
   * (`showsUnits`); else its obec; else its council obvod at any zoom (a
   * council obvod's own contest, of which the obec has no value); else its
   * regional obvod where only that is known; null for none. */
  function shardUnit(p, z) {
    const piece = p.oz === undefined ? null : `${p.id}/${p.oz}`;
    if (piece && showsUnits('oz', z) && results.councils.has(piece)) return ['councils', piece];
    if (results.obce.has(p.id)) return ['obce', p.id];
    if (piece && results.councils.has(piece)) return ['councils', piece];
    const zsk = zskOf(p);
    return results.zsk.get(zsk)?.[2] ? ['zsk', zsk] : null;
  }

  // The step a feature with properties *p* in the shards is filled in at
  // zoom *z* (`shardUnit`); undefined for none.
  const obecStep = (p, z) => {
    const unit = shardUnit(p, z);
    return unit ? results[unit[0]].get(unit[1])[0] : undefined;
  };

  // The ties' stripes (`stripes`) by pixel ratio and colours, let go with
  // the results and the theme they are of.
  const stripePatterns = new Map();

  /* A pattern of diagonal stripes of the colours *names*, each STRIPE CSS
   * pixels along a row at pixel ratio *ratio*: a tile of one turn of them,
   * which repeats seamlessly, its side `size`. */
  function stripes(names, ratio) {
    const key = `${ratio} ${names}`;
    let made = stripePatterns.get(key);
    if (made) return made;
    const w = Math.max(1, Math.round(STRIPE * ratio));
    const n = names.length;
    const size = w * n;
    const t = surface(size, size).getContext('2d');
    // The first colour under all, so that no seam of two stripes lets the
    // land through.
    t.fillStyle = COLOR[names[0]];
    t.fillRect(0, 0, size, size);
    // Each stripe runs down to the right; those from left of the tile
    // cover its lower left.
    for (let i = 1 - n; i < n; i++) {
      if (i === 0) continue;
      t.fillStyle = COLOR[names[(i + n) % n]];
      t.beginPath();
      t.moveTo(i * w, 0);
      t.lineTo((i + 1) * w, 0);
      t.lineTo((i + 1) * w + size, size);
      t.lineTo(i * w + size, size);
      t.fill();
    }
    made = { pattern: t.createPattern(t.canvas, 'repeat'), size };
    stripePatterns.set(key, made);
    return made;
  }

  /* The fill of step *s* of the results on *ctx*, placed for a file of
   * *view* (`placeFile`): its colour, or a tie's stripes (a palette entry
   * of several colours) in screen pixels from the map's corner, which keep
   * their width at every zoom and move with the map as it pans. */
  function stepFill(ctx, view, s) {
    const name = results.palette?.[s];
    if (Array.isArray(name)) {
      const { pattern, size } = stripes(name, view.ratio);
      const at = (d) => (-view.ratio * d) % size;
      pattern.setTransform(ctx.getTransform().inverse().translate(at(view.x), at(view.y)));
      return pattern;
    }
    if (name) return COLOR[name];
    if (results.tone === 'result') return COLOR[`result-${s + 1}`];
    return mix(COLOR.land, COLOR[results.tone], TONE_STEPS[s]);
  }

  /* Fills the features of *file* in *bins* of *view* in the fill of their
   * step of the results, *stepOf(feature)*, over the land: one path per
   * step and bin, cached under *group* (`setResults` lets go of them). */
  function fillResults(ctx, view, file, bins, group, stepOf) {
    const z = Math.floor(view.zoom);
    for (let s = 0; s < results.steps; s++) {
      ctx.fillStyle = stepFill(ctx, view, s);
      fillBins(ctx, bins, z, `${group} result-${s}`, (bin) =>
        unionPath(file, bin.features.filter((f) => stepOf(f) === s), z),
      );
    }
  }

  // Whether coarse.json is drawn: below the zoom bands of the shards, and in
  // them until the shards in view have come.
  let coarseShown = true;

  /* What a drawing shows: [file, its line layers, its bins in *view*]. */
  function drawn(view) {
    const z = level();
    const flagged = Object.keys(FLAG).filter((name) => drawsOverlay(name, z));
    const out = [];
    if (coarseShown) {
      const names = z >= OKRES_ZOOM ? ['rank1', 'rank2', 'rank3'] : ['rank2', 'rank3'];
      out.push([coarse, [...names, ...flagged]]);
    }
    const council = drawsOverlay('oz', z) ? ['council', 'approx'] : [];
    for (const s of shown.values()) {
      out.push([s.file, ['rank0', 'rank1', 'rank2', 'rank3', ...council, ...flagged]]);
    }
    // The okrsky over the obce they are of; their borders along a council
    // obvod border where the council overlay does not draw those.
    const alongCouncil = drawsOverlay('oz', z) ? [] : ['okrsok-council', 'okrsok-council-approx'];
    const okrsky = drawsOverlay('okrsky', z) ? ['okrsok', 'okrsok-approx', ...alongCouncil] : [];
    for (const s of okrskyShown.values()) out.push([s.file, okrsky]);
    return out.map(([file, names]) => [file, names, binsIn(file, view.box)]).filter((d) => d[2].length);
  }

  /* Strokes *dash* (CSS pixels, `dashedPath`) of the arcs that *pick*
   * passes of *file* in *bins* at line width *w* (CSS pixels): butt
   * capped, each dash longer by the width the round caps would add, the
   * same marks for a stroke without a cap at either end of each of
   * thousands of dashes (in Bratislava at zoom 15, the dashed okrsok
   * borders cost half as much). */
  function strokeDashes(ctx, view, file, bins, dash, w, pick) {
    const path = dashedPath(
      file,
      bins,
      view,
      dash.map((d, i) => (i % 2 ? d - w : d + w)),
      pick,
    );
    if (!path) return;
    ctx.lineCap = 'butt';
    ctx.lineWidth = w / view.k;
    ctx.stroke(path);
    ctx.lineCap = 'round';
  }

  /* The countries around, below Slovakia: their land, then their borders,
   * dashed. What they have under Slovakia its fill covers. */
  function drawNeighbours(ctx, view) {
    if (!neighbours) return;
    const { file } = neighbours;
    const z = Math.floor(view.zoom);
    const bins = binsIn(file, view.box);
    placeFile(ctx, file, view);
    ctx.fillStyle = COLOR.neighbour;
    fillBins(ctx, bins, z, 'land', (bin) => unionPath(file, bin.features, z));
    ctx.strokeStyle = COLOR['neighbour-line'];
    strokeDashes(ctx, view, file, bins, NEIGHBOUR_DASH, 1, () => true);
  }

  /* The base map: waters, buildings, roads and railways, faint, over the
   * land and the results' fills (the waters opaque over the fills) and
   * under every border, highlight and label, at the theme's `base-alpha`.
   * Each class is one path per bin in view, made once and scaled by the
   * transform, and the buildings one per cell: the rasterizer works only on
   * what is near the view, and nothing is built again for a pan or zoom but
   * the railways' ticks. Each step goes over all the files, so that the
   * casing of a road in one never cuts the fill of a road in the next.
   * (Drawn opaque on a canvas of its
   * own and laid on at `base-alpha`, the casings would not show faintly
   * under the fills, but that took 2.5 ms more of a drawing of 30.) */
  function drawBase(ctx, view) {
    const z = level();
    const files = [];
    if (overlays.base) {
      if (coarseShown && baseCoarse) files.push(baseCoarse);
      for (const s of baseShown.values()) files.push(s.file);
    }
    const drawnFiles = files.map((file) => [file, binsIn(file, view.box)]).filter(([, bins]) => bins.length);
    // One canvas pixel, in the units of the paths (`placeFile`).
    const hairline = 1 / (view.k * view.ratio);
    // The width of line class [code, colour, widths, dense] in CSS px, and
    // whether it is a hairline.
    const widthOf = ([, , widths, dense]) => [fromZoom(widths, z) ?? 0, dense && z < HAIRLINE_ZOOM];
    const stroke = (code, color, px, hair) => {
      ctx.strokeStyle = COLOR[color];
      ctx.lineWidth = hair ? Math.min(px / view.k, hairline) : px / view.k;
      for (const [file, bins] of drawnFiles) {
        placeFile(ctx, file, view);
        strokeBins(ctx, bins, z, `base-${code}`, (bin) => linesPath(file, bin.arcs, (c) => c === code, z));
      }
    };
    const alpha = Number(COLOR['base-alpha']);
    // Over the results' fills, the waters are opaque, in the colour they
    // have on the bare land: faint, a lake would take on the colour of the
    // unit under it, a blue-tinted shade that reads as another value or
    // candidate. So the colours stop at the shore; the borders and the
    // labels still cross it, and a click in a lake still picks its unit.
    if (results) {
      ctx.globalAlpha = 1;
      ctx.fillStyle = mix(COLOR.land, COLOR['base-water'], alpha);
    } else {
      ctx.globalAlpha = alpha;
      ctx.fillStyle = COLOR['base-water'];
    }
    for (const [file, bins] of drawnFiles) {
      placeFile(ctx, file, view);
      fillBins(ctx, bins, z, 'base-water', (bin) => waterPath(file, bin, z));
    }
    ctx.globalAlpha = alpha;
    if (overlays.buildings && z >= buildingsIndex?.zoom) {
      ctx.fillStyle = COLOR['base-building'];
      for (const file of buildingsShown.values()) {
        placeFile(ctx, file, view);
        for (const cell of file.cells) if (boxesIntersect(cell.box, view.box)) ctx.fill(cell.path);
      }
    }
    for (const line of BASE_WATERWAYS) {
      const [px, hair] = widthOf(line);
      if (px) stroke(line[0], line[1], px, hair);
    }
    // The roads' casings (or whole narrow roads), then their fills.
    for (const line of BASE_ROADS) {
      const [px, hair] = widthOf(line);
      if (px) stroke(line[0], line[1], px, hair);
    }
    for (const line of BASE_ROADS) {
      const [px, hair] = widthOf(line);
      if (!hair && px >= CASED_WIDTH) stroke(line[0], `${line[1]}-fill`, px - 2 * CASING, false);
    }
    for (const [code, color, widths, dense, ticks] of BASE_RAILS) {
      const [px, hair] = widthOf([code, color, widths, dense]);
      if (!px) continue;
      stroke(code, color, px, hair);
      const tick = fromZoom(ticks, z);
      if (!tick) continue;
      const [across, along, gap] = tick;
      ctx.lineCap = 'butt';
      ctx.lineWidth = across / view.k;
      for (const [file, bins] of drawnFiles) {
        placeFile(ctx, file, view);
        const path = dashedPath(file, bins, view, [along, gap], (c) => c === code);
        if (path) ctx.stroke(path);
      }
      ctx.lineCap = 'round';
    }
    ctx.globalAlpha = 1;
  }

  function drawShapes(ctx, view) {
    const z = level();
    const files = drawn(view);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    drawNeighbours(ctx, view);
    for (const [file, , bins] of files) {
      placeFile(ctx, file, view);
      if (file.okrsky) {
        // Each okrsok by its own figure, over its obec's, from their zoom.
        if (results?.okrsky.size && showsUnits('okrsky', z)) {
          fillResults(ctx, view, file, bins, 'okrsky', (f) => results.okrsky.get(okrsokKey(f.properties))?.[0]);
        }
        continue;
      }
      if (file === coarse) {
        // The land, not the coarse cells: one path, and no seam shows where
        // two cells meet. Made for each zoom level (topo.js `levels`).
        if (coarse.landPath?.z !== z) coarse.landPath = { z, path: unionPath(coarse, [{ arcs: coarse.land }], z) };
        ctx.fillStyle = COLOR.land;
        ctx.fill(coarse.landPath.path, 'evenodd');
        // The results by regional obvod, cell by cell.
        if (results) fillResults(ctx, view, coarse, bins, 'coarse', (f) => results.zsk.get(zskOf(f.properties))?.[0]);
        continue;
      }
      const groups = fillGroups(z);
      for (const [name, color, which] of groups) {
        ctx.fillStyle = color;
        fillBins(ctx, bins, z, name, (bin) => unionPath(file, bin.features.filter(which), z));
      }
      // Over the land only: the council overlay's obce of no known obvod or
      // no council keep their colours. Cached apart below and from the
      // council obvody's zoom: a shard's level of detail spans both.
      if (results) {
        const [land, , which] = groups[0];
        const group = showsUnits('oz', z) ? `${land} by-oz` : land;
        fillResults(ctx, view, file, bins, group, (f) => (which(f) ? obecStep(f.properties, z) : undefined));
      }
    }
    drawBase(ctx, view);
    // The obec and okres borders along a regional or city obvod border
    // drawn too: its wider stroke covers them.
    const covered = Object.keys(FLAG)
      .filter((name) => drawsOverlay(name, z))
      .reduce((bits, name) => bits | FLAG[name], 0);
    for (const name of LINES) {
      const style = lineStyle(name, z);
      const under = name === 'rank0' || name === 'rank1' ? covered : 0;
      const pick = (code) => inLayer(name, code) && !(code & under);
      ctx.strokeStyle = style.color;
      for (const [file, names, bins] of files) {
        if (!names.includes(name)) continue;
        placeFile(ctx, file, view);
        if (style.dash) {
          strokeDashes(ctx, view, file, bins, style.dash, style.weight, pick);
          continue;
        }
        ctx.lineWidth = style.weight / view.k;
        strokeBins(ctx, bins, z, `${name} ${under}`, (bin) => linesPath(file, bin.arcs, pick, z));
      }
    }
    drawHighlight(ctx, view);
  }

  /* The overlay whose obvod of the selected place is highlighted at zoom
   * *z*: the finest drawn there that cuts the place out of what is around. */
  function highlighted(z) {
    const info = place?.info;
    if (!info?.okres) return null;
    const can = (name) => drawsOverlay(name, z) && within(z, OVERLAYS[name].highlight);
    if (place.obvod && can('oz')) return 'oz';
    if (info.city && can('city')) return 'city';
    return can('zsk') ? 'zsk' : null;
  }

  /* Whether a feature with properties *p* is in *area*: {city, obvod} the
   * whole city or its council obvod, {kraj, zsk} the whole kraj or its
   * regional obvod. */
  const inArea = (area, p) =>
    'kraj' in area
      ? p.kraj === area.kraj && (area.zsk === null || p.zsk === area.zsk)
      : p.city === area.city && (area.obvod === null || p.city_obvod === area.obvod);

  /* Fills faintly and outlines in *color* the features that *member* picks
   * of the files drawn now, the outline along the arcs of *overlay* around
   * them (for 'oz', a council obvod within one obec, its outline): an arc
   * on an okres border is in both shards, and only one of the two copies
   * has a member on its side. */
  function drawArea(ctx, view, member, overlay, color) {
    const z = Math.floor(view.zoom);
    const files = lodFor(view.zoom) === null ? [coarse] : [...shown.values()].map((s) => s.file);
    const units = [];
    for (const file of files) {
      const fill = new Path2D();
      let line = new Path2D();
      const around = new Set();
      const members = file.features.filter((f) => member(f.properties));
      for (const f of members) {
        addFeature(fill, file, f, z);
        for (const p of f.arcs) for (const ring of p) for (const r of ring) around.add(arcOf(r));
      }
      if (!around.size) continue;
      if (overlay === 'oz') line = unionPath(file, members, z);
      else for (const a of around) if (file.lines[a] & FLAG[overlay]) addArc(line, file, a, z);
      units.push([file, fill, line]);
    }
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.12;
    for (const [file, fill] of units) {
      placeFile(ctx, file, view);
      ctx.fill(fill, 'evenodd');
    }
    ctx.globalAlpha = 1;
    ctx.strokeStyle = color;
    for (const [file, , line] of units) {
      placeFile(ctx, file, view);
      ctx.lineWidth = 3 / view.k;
      ctx.stroke(line);
    }
  }

  /* Outlines obec *obec* ({file, features}, `shownObec`) in *color*, with a
   * faint fill. */
  function drawObec(ctx, view, obec, color) {
    // An obec cut into council obvody is several features.
    const path = unionPath(obec.file, obec.features, Math.floor(view.zoom));
    placeFile(ctx, obec.file, view);
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.08;
    ctx.fill(path, 'evenodd');
    ctx.globalAlpha = 1;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.5 / view.k;
    ctx.stroke(path);
  }

  /* The selected obvod (its border from the files drawn now, so it is
   * theirs), the selected obec and the selected point. */
  function drawHighlight(ctx, view) {
    const info = place?.info;
    const overlay = highlighted(level());
    const member = {
      zsk: (p) => p.kraj === info.kraj && p.zsk === info.zsk,
      city: (p) => p.city === info.city && p.city_obvod === info.cityObvod,
      oz: (p) => p.id === info.code && p.oz === place.obvod,
    }[overlay];
    if (member) drawArea(ctx, view, member, overlay, overlay === 'oz' ? COLOR.council : COLOR[overlay]);
    const obec = info?.okres ? shownObec(info) : null;
    if (obec) drawObec(ctx, view, obec, COLOR.accent);
    // The selected place's okrsok, where its okrsky are drawn.
    const okrsokShown = place?.okrsok && info?.okres && within(level(), OVERLAYS.okrsky.highlight);
    const okrsky = okrsokShown ? okrskyShown.get(info.okres)?.file : null;
    const okrsok = okrsky?.features.filter((f) => f.properties.obec === info.code && f.properties.okrsok === place.okrsok);
    if (okrsok?.length) drawObec(ctx, view, { file: okrsky, features: okrsok }, COLOR.okrsok);
    if (place && Number.isFinite(place.lat)) {
      const p = toPixel(view, place.lat, place.lon);
      ctx.setTransform(view.ratio, 0, 0, view.ratio, 0, 0);
      ctx.beginPath();
      ctx.arc(p.x, p.y, 6, 0, 2 * Math.PI);
      ctx.fillStyle = COLOR.accent;
      ctx.fill();
      ctx.strokeStyle = COLOR.pin;
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }

  // Draws the latest view again. Calls until the drawing starts make one:
  // the page's views and the files that come while one is drawn queue
  // behind it, so the next drawing has them all.
  let pending = 0;
  function redraw() {
    if (!pending) pending = setTimeout(flush, 0);
  }
  // The canvas drawn on, made again when the size changes.
  let canvas = null;
  function flush() {
    pending = 0;
    if (!current) return;
    const { view, free, seq } = current;
    const cw = Math.round(view.w * view.ratio);
    const ch = Math.round(view.h * view.ratio);
    // A map with no size (not laid out yet) has nothing to draw.
    if (!cw || !ch) return;
    if (canvas?.width !== cw || canvas.height !== ch) canvas = surface(cw, ch);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, cw, ch);
    drawShapes(ctx, view);
    drawLabels(ctx, view, free);
    present(canvas, view, seq);
  }

  /* Lets go of the files of *drawnFiles* (okres → {lod, file}) whose okres
   * *keep(okres)* no longer wants. */
  function dropUnwanted(drawnFiles, keep) {
    for (const [okres, s] of drawnFiles) {
      if (!keep(okres)) {
        drawnFiles.delete(okres);
        releasePaths(s.file);
      }
    }
  }

  /* Loads the file of *okres* at *lod* (*load()*) into *drawnFiles*, unless
   * it is drawn already. Once it comes, it replaces the one drawn, if
   * *wants()* still and no other came meanwhile, and *done()* is called. */
  function loadInto(drawnFiles, okres, lod, load, wants, done = redraw) {
    if (drawnFiles.get(okres)?.lod === lod) return;
    load()
      .then((file) => {
        const old = drawnFiles.get(okres);
        if (!wants() || old?.lod === lod) return;
        if (old) releasePaths(old.file);
        drawnFiles.set(okres, { lod, file });
        done();
      })
      .catch(logError);
  }

  /* Loads what *view* shows and lets go of what it no longer does: the
   * shards of the okresy in its canvas at the level of detail of its zoom,
   * their base map (`refreshBase`), the countries around and
   * (`loadAddresses`) the address files. Each draws when it comes, if the
   * latest view still wants it. */
  function refresh(view) {
    const lod = lodFor(view.zoom);
    const box = view.bounds;
    wantedLod = lod;
    wanted = new Set(
      lod === null ? [] : Object.keys(geoIndex.okresy).filter((o) => boxesIntersect(geoIndex.okresy[o], box)),
    );
    // An okres of another band stays drawn until its new shard has come: a
    // zoom shows the detail it had meanwhile, not a hole.
    dropUnwanted(shown, (okres) => wanted.has(okres));
    const band = neighbourBand(view.zoom, box);
    if (neighbours?.lod !== band.lod) {
      loadNeighbours(band)
        .then((file) => {
          const { zoom, bounds } = current.view;
          if (neighbourBand(zoom, bounds) !== band || neighbours?.lod === band.lod) return;
          if (neighbours) releasePaths(neighbours.file);
          neighbours = { lod: band.lod, file };
          redraw();
        })
        .catch(logError);
    }
    for (const okres of wanted) {
      const wants = () => wanted.has(okres) && wantedLod === lod;
      loadInto(shown, okres, lod, () => loadShard(okres, lod), wants, () => {
        settle();
        redraw();
      });
    }
    settle();
    refreshOkrsky(view);
    refreshBase();
  }

  /* Loads the base map of what `refresh` wants, while it is on: the coarse
   * view's (once), and that of the okresy wanted at the shards' level of
   * detail, drawn as soon as it comes (it is not needed to replace the
   * coarse view). */
  function refreshBase() {
    dropUnwanted(baseShown, (okres) => overlays.base && wanted.has(okres));
    if (!overlays.base) return;
    if (!baseCoarse) {
      loadBase('coarse.json', Infinity)
        .then((file) => {
          baseCoarse = file;
          redraw();
        })
        .catch(logError);
    }
    const lod = wantedLod;
    for (const okres of wanted) {
      const wants = () => overlays.base && wanted.has(okres) && wantedLod === lod;
      loadInto(baseShown, okres, lod, () => loadBase(`okres/${okres}/${lod}.json`, binSize[lod]), wants);
    }
  }

  /* Loads the okrsky files *view* wants (`wantsOkrsky`), as `refresh` the
   * shards: those of the okresy in it that have okrsky drawn. */
  function refreshOkrsky(view) {
    const lod = wantsOkrsky(Math.floor(view.zoom)) ? lodAt(okrsokBands, view.zoom) : null;
    const extents = geoIndex.okrsky.okresy;
    okrskyLod = lod;
    okrskyWanted = new Set(
      lod === null ? [] : Object.keys(extents).filter((o) => boxesIntersect(extents[o], view.bounds)),
    );
    dropUnwanted(okrskyShown, (okres) => okrskyWanted.has(okres));
    for (const okres of okrskyWanted) {
      const wants = () => okrskyWanted.has(okres) && okrskyLod === lod;
      loadInto(okrskyShown, okres, lod, () => loadOkrsky(okres, lod), wants);
    }
  }

  /* Once every shard in view has come: coarse.json is no longer drawn (it
   * is below the zoom bands of the shards, and in them until then), and the
   * address and buildings files load. */
  function settle() {
    if (wantedLod === null) coarseShown = true;
    if (![...wanted].every((o) => shown.get(o)?.lod === wantedLod)) return;
    if (wantedLod !== null) coarseShown = false;
    loadAddresses();
    loadBuildings();
  }

  /* The codes of the obce whose shards' features reach into the view, or
   * the tenth of it around. */
  function obceInView() {
    const view = viewPixels(current.view, 0.1);
    const codes = new Set();
    for (const s of shown.values()) {
      for (const f of s.file.features) {
        if (boxesIntersect(f.box, view)) codes.add(f.properties.id);
      }
    }
    return codes;
  }

  function loadAddresses() {
    if (level() < ADDRESS_ZOOM) {
      wantedAddresses = new Set();
      if (addresses.size) redraw();
      addresses.clear();
      return;
    }
    const codes = obceInView();
    wantedAddresses = new Set([...codes].slice(0, MAX_ADDRESS_FILES));
    for (const code of addresses.keys()) if (!wantedAddresses.has(code)) addresses.delete(code);
    for (const code of wantedAddresses) {
      if (addresses.has(code)) continue;
      addressFile(code)
        .then((file) => {
          if (!wantedAddresses.has(code)) return;
          addresses.set(code, file);
          redraw();
        })
        .catch(logError);
    }
  }

  /* Loads the buildings of the obce in view that have them, while they
   * are on and from their zoom (base/index.json `buildings`, asked for
   * once), and lets go of the others. */
  function loadBuildings() {
    if (overlays.buildings && !buildingsIndex && !buildingsAsked) {
      buildingsAsked = true;
      fetchJSON('/base/index.json')
        .then(({ buildings }) => {
          buildingsIndex = { zoom: buildings.zoom, obce: new Set(buildings.obce) };
          loadBuildings();
        })
        .catch((e) => {
          buildingsAsked = false;
          logError(e);
        });
    }
    const on = overlays.buildings && buildingsIndex && level() >= buildingsIndex.zoom;
    wantedBuildings = on ? new Set([...obceInView()].filter((code) => buildingsIndex.obce.has(code))) : new Set();
    const before = buildingsShown.size;
    for (const code of buildingsShown.keys()) if (!wantedBuildings.has(code)) buildingsShown.delete(code);
    if (buildingsShown.size !== before) redraw();
    for (const code of wantedBuildings) {
      if (buildingsShown.has(code)) continue;
      loadBuildingFile(code)
        .then((file) => {
          if (!wantedBuildings.has(code)) return;
          buildingsShown.set(code, file);
          redraw();
        })
        .catch(logError);
    }
  }

  /* The band around the houses of the highlighted street (`streetShape`) at
   * *pixels*: one stroke, so it is no darker where its parts overlap, hollowed
   * out by a narrower one to a light fill inside an outline. Hollowing erases
   * what is under it, so the band is made on a canvas of its own. */
  function streetBand(ctx, view, pixels, edges) {
    const lat = place.shape.points[0][0];
    const perPixel = metresPerPixel(lat, view.zoom);
    const r = Math.min(Math.max(STREET_REACH / perPixel, STREET_PIXELS[0]), STREET_PIXELS[1]);
    const path = new Path2D();
    for (const [i, j] of edges) {
      path.moveTo(pixels[i].x, pixels[i].y);
      path.lineTo(pixels[j].x, pixels[j].y);
    }
    // Every house too, for the ones on their own: a segment too short to
    // see, which the round cap makes a disc.
    for (const p of pixels) {
      path.moveTo(p.x, p.y);
      path.lineTo(p.x + 0.01, p.y);
    }
    // Its box (and a pixel more) within the canvas, in canvas pixels.
    const reach = r + 3;
    const xs = pixels.map((p) => p.x);
    const ys = pixels.map((p) => p.y);
    const { ratio } = view;
    const x0 = Math.max(Math.floor((Math.min(...xs) - reach) * ratio), 0);
    const y0 = Math.max(Math.floor((Math.min(...ys) - reach) * ratio), 0);
    const x1 = Math.min(Math.ceil((Math.max(...xs) + reach) * ratio), Math.round(view.w * ratio));
    const y1 = Math.min(Math.ceil((Math.max(...ys) + reach) * ratio), Math.round(view.h * ratio));
    if (x1 <= x0 || y1 <= y0) return;
    const band = surface(x1 - x0, y1 - y0).getContext('2d');
    band.setTransform(ratio, 0, 0, ratio, -x0, -y0);
    band.lineCap = 'round';
    band.lineJoin = 'round';
    band.strokeStyle = COLOR.accent;
    band.lineWidth = 2 * r + 4;
    band.stroke(path);
    band.globalCompositeOperation = 'destination-out';
    band.globalAlpha = 1 - STREET_FILL;
    band.lineWidth = 2 * r;
    band.stroke(path);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(band.canvas, x0, y0);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  /* A dot on each house of the highlighted street, in the style of the pin. */
  function streetDots(ctx, pixels) {
    ctx.fillStyle = COLOR.accent;
    ctx.strokeStyle = COLOR.pin;
    ctx.lineWidth = 1;
    for (const p of pixels) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 3, 0, 2 * Math.PI);
      ctx.fill();
      ctx.stroke();
    }
  }

  // The spots found by `visibleSpot` and the view they are for: a redraw of
  // the same view (a shard or address file comes, a selection, a theme)
  // takes them again. Key: area and text; value: {file, at}.
  let spots = { view: '', of: new Map() };
  // Where `spot` put each label, in Z0 pixels, at one zoom: a label stays
  // there while the map pans as long as it is whole in the free part, rather
  // than following the middle of what is in view. Key as in `spots`.
  let kept = { zoom: null, at: new Map() };
  // The selected point's dot (radius 6 + stroke) is drawn above the labels;
  // a label that would sit under it moves this far below its centre.
  const PIN = 9;

  /* What the labels of a drawing share: {ctx, view, free, z, placer} (*free*
   * the part of *view* left uncovered, map.js `freePart`; `z` by `level`)
   * and the ways to place and draw a label. */
  function labelling(ctx, view, free) {
    const placer = new Placer();
    const pin = place && Number.isFinite(place.lat) ? toPixel(view, place.lat, place.lon) : null;
    // Whether a label *w* × *h* centred at *q* is whole in the free part.
    const fits = (q, w, h) => q.x - w / 2 >= free[0] && q.x + w / 2 <= free[2] && q.y - h / 2 >= free[1] && q.y + h / 2 <= free[3];
    const keep = (key, p) => kept.at.set(key, { x: (p.x + view.x) / view.k, y: (p.y + view.y) / view.k });
    // Where the labels of the other parts of an area of several go (geo.py
    // `parts`: [lon, lat, room in metres]): those of the parts whose room
    // holds the box *w* × *size* of the text, whole in the free part.
    const partSpots = (parts, w, size) => {
      const need = Math.hypot(w / 2, size / 2 + 1);
      return (parts ?? []).flatMap(([lon, lat, room]) => {
        const q = toPixel(view, lat, lon);
        return room / metresPerPixel(lat, view.zoom) >= need && fits(q, w, size + 2) ? [q] : [];
      });
    };
    return {
      ctx,
      view,
      free,
      z: level(),
      placer,

      /* The point [lon, lat] in pixels of the canvas (`toPixel`). */
      at: ([lon, lat]) => toPixel(view, lat, lon),

      /* Where the label *text* of *area* goes, or null where it would be
       * cut off: a name half under the pane or past the edge of the map
       * reads as another word. Where it was last drawn at this zoom, if the
       * whole label is still in the free part of the map: a pan moves a
       * label only once the edge of the map or a pane reaches it. Else at
       * the area's own spot *p*, if the whole label is in the free part.
       * Else, so that an area seen only in part (its spot panned away or
       * under a pane) is still named, where the part of it in the free part
       * leaves the label the most room (`visibleSpot`), if it fits there.
       * Where one of its other *parts* is labelled in view (`inParts`), it
       * stays in its own part, the one holding *p* (`partAt`): it would
       * else stand a second time in a part named already. */
      spot(area, p, text, font, size, parts) {
        if (!area) return p;
        const w = textWidth(ctx, font, text) + 4;
        const h = size + 2;
        const key = `${area.own} ${text}`;
        const z0 = (r) => [(r.x + view.x) / view.k, (r.y + view.y) / view.k];
        let within = area;
        if (partSpots(parts, w, size).length) {
          const part = partAt(area.file, area.features, ...z0(p));
          within = part && { file: area.file, features: [part], box: part.box };
        }
        const last = kept.at.get(key);
        const q = last && pixelAt(view, last.x, last.y);
        const ours = (r) => within === area || (within && contains(area.file, within.features[0], ...z0(r)));
        if (q && fits(q, w, h) && ours(q)) return q;
        if (fits(p, w, h)) {
          keep(key, p);
          return p;
        }
        let found = spots.of.get(key);
        if (found?.file !== area.file) {
          found = { file: area.file, at: within && visibleSpot(within, free, view, w, h) };
          spots.of.set(key, found);
        }
        if (found.at) keep(key, found.at);
        else kept.at.delete(key);
        return found.at;
      },

      /* Draws the name *text* at *p* (`spot`), out from under the pin, and
       * with *keepInside* slid into the free part; none where *p* is null.
       * Returns as `drawText`. */
      label(text, p, font, size, color, { kind, area, keepInside = false, gap = 0 }) {
        if (!p) return null;
        let { x, y } = p;
        if (pin) {
          const half = textWidth(ctx, font, text) / 2 + 2;
          const hits = Math.abs(p.x - pin.x) < half + PIN && Math.abs(p.y - pin.y) < size / 2 + PIN;
          if (hits) y = pin.y + PIN + size / 2 + 2;
        }
        if (keepInside) {
          // Kraj names label the whole country view; one at the edge of a
          // narrow (phone) map or by the pane, with no room in the part of
          // its kraj in view, would be cut off, so it slides inwards.
          const half = textWidth(ctx, font, text) / 2 + 4;
          x = Math.min(Math.max(x, free[0] + half), free[2] - half);
          y = Math.min(Math.max(y, free[1] + size / 2), free[3] - size / 2);
        }
        return drawText(ctx, placer, text, x, y, font, size, color, { gap, kind, area, bounds: free });
      },

      /* Draws the 12 px number *text* of *area*, a label of *kind*, at *p*;
       * none where *p* is null. Returns as `drawText`. */
      number(text, p, font, color, kind, area) {
        return p && drawText(ctx, placer, text, p.x, p.y, font, 12, color, { kind, area, bounds: free });
      },

      /* Draws the value *text* of the results of *area* at (x, y). */
      value(text, x, y, area) {
        drawText(ctx, placer, text, x, y, OBVOD_FONT, 12, COLOR.text, { kind: 'result', area, bounds: free });
      },

      /* Draws a label at *p* by *draw(p)* (`label`, `number`; none where
       * *p* is null) and the *value* of the results of *area*, if any,
       * under it. Returns whether the label was drawn. */
      labelWithValue(draw, p, value, area) {
        const y = draw(p);
        if (typeof y !== 'number') return false;
        if (value) this.value(value, p.x, y + VALUE_DROP, area);
        return true;
      },

      /* Labels the other parts of an area of several (geo.py `parts`) by
       * *draw(p)* where *text* fits in the room: the box of the text within
       * the largest circle inside the part (`partSpots`). */
      inParts(parts, text, font, size, draw) {
        for (const p of partSpots(parts, textWidth(ctx, font, text) + 4, size)) draw(p);
      },
    };
  }

  /* Names the countries around in the view, each at the one of its places
   * (geo.py `label_spots`) that leaves the name the most room: the least of
   * the place's own room at this zoom and its distance to the edges of the
   * free part of the map, with the whole name inside both. The places are
   * in the country, out of Slovakia, so a name never covers it; one that
   * would cover a Slovak name tries the next place. The names with the most
   * room go first. */
  function drawNeighbourNames({ ctx, placer, view, free }) {
    // Metres a pixel spans at the equator.
    const metres = EQUATOR / (256 * 2 ** view.zoom);
    ctx.letterSpacing = NEIGHBOUR_SPACING;
    const names = [];
    for (const f of neighbours.file.features) {
      if (!boxesIntersect(f.box, view.box)) continue;
      const name = (strings.countries[f.properties.id] ?? f.properties.id).toUpperCase();
      const half = textWidth(ctx, NEIGHBOUR_FONT, name) / 2 + 4;
      const places = [];
      for (const [lon, lat, room] of f.properties.spots) {
        const p = toPixel(view, lat, lon);
        const fits =
          p.x - half >= free[0] &&
          p.x + half <= free[2] &&
          p.y - NEIGHBOUR_SIZE >= free[1] &&
          p.y + NEIGHBOUR_SIZE <= free[3];
        const r = room / (metres * Math.cos((lat * Math.PI) / 180));
        if (!fits || r < half) continue;
        places.push([Math.min(r, p.x - free[0], free[2] - p.x, p.y - free[1], free[3] - p.y), p]);
      }
      if (places.length) names.push([name, places.sort((a, b) => b[0] - a[0])]);
    }
    names.sort((a, b) => b[1][0][0] - a[1][0][0]);
    const style = { halo: COLOR['neighbour-halo'] };
    for (const [name, places] of names) {
      places.find(([, p]) =>
        drawText(ctx, placer, name, p.x, p.y, NEIGHBOUR_FONT, NEIGHBOUR_SIZE, COLOR['neighbour-label'], style) !== null,
      );
    }
    ctx.letterSpacing = '0px';
  }

  // The number of obvod *n* on the map.
  const obvodText = (n) => strings.obvod.replace('{n}', n);

  /* The labels, by priority (`Placer`), *free* the part of *view* left
   * uncovered: obvod numbers, then the names of the kraje, the results of
   * the regional obvody, the names of the okresy or obce (with their
   * results), the countries around and house numbers. */
  function drawLabels(ctx, view, free) {
    ctx.setTransform(view.ratio, 0, 0, view.ratio, 0, 0);
    // The halo of the labels in the canvas's default line style.
    ctx.lineCap = 'butt';
    ctx.lineJoin = 'miter';
    ctx.textBaseline = 'middle';
    const viewKey = `${view.zoom} ${view.x} ${view.y} ${free}`;
    if (spots.view !== viewKey) spots = { view: viewKey, of: new Map() };
    if (kept.zoom !== view.zoom) kept = { zoom: view.zoom, at: new Map() };
    const street = place?.shape?.points.map(([lat, lon]) => toPixel(view, lat, lon));
    if (street) streetBand(ctx, view, street, place.shape.edges);
    const l = labelling(ctx, view, free);
    // Obvod numbers before the names: where an overlay is drawn, which obvod
    // is which is what the map is looked at for.
    drawObvodNumbers(l);
    // Obce are named from the zoom their shards are drawn at, okresy before.
    const obce = lodFor(view.zoom) !== null;
    if (l.z < OKRES_ZOOM) drawKrajNames(l);
    // After the names of the kraje, before those of the okresy, both
    // stacking with them.
    drawZskResults(l, obce);
    if (l.z >= OKRES_ZOOM && !obce) drawOkresNames(l);
    if (obce) drawShardLabels(l);
    if (neighbours) drawNeighbourNames(l);
    if (l.z >= ADDRESS_ZOOM) drawHouses(l);
    if (street) streetDots(ctx, street);
  }

  /* The numbers of the regional and the city obvody where their overlays
   * number them (`labelling` *l*). Where the cities' numbers are drawn, the
   * regional obvody within them go unnumbered: two numbers of two councils
   * side by side would read as one series. */
  function drawObvodNumbers(l) {
    const { z } = l;
    const cityNumbers = drawsOverlay('city', z) && within(z, OVERLAYS.city.numbers);
    for (const [name, prefix] of [
      ['zsk', 'zsk:'],
      ['city', 'oz:'],
    ]) {
      if (!drawsOverlay(name, z) || !within(z, OVERLAYS[name].numbers)) continue;
      const obvody = coarse.obvody.filter(
        (o) => o.id.startsWith(prefix) && !(name === 'zsk' && cityNumbers && cityZsk.has(o.id)),
      );
      const text = (o) => obvodText(o.id.slice(o.id.lastIndexOf('/') + 1));
      const number = (o) => (p) => l.number(text(o), p, OBVOD_FONT, COLOR[name], name, coarseAreas.get(o.id));
      for (const o of obvody) number(o)(l.spot(coarseAreas.get(o.id), l.at(o.label), text(o), OBVOD_FONT, 12, o.parts));
      for (const o of obvody) l.inParts(o.parts, text(o), OBVOD_FONT, 12, number(o));
    }
  }

  /* The names of the kraje (`labelling` *l*). */
  function drawKrajNames(l) {
    for (const k of coarse.kraje) {
      const area = coarseAreas.get(`kraj:${k.id}`);
      // Where no whole spot is free, at its own, slid inwards.
      const p = l.spot(area, l.at(k.label), k.name, KRAJ_FONT, 14) ?? l.at(k.label);
      l.label(k.name, p, KRAJ_FONT, 14, COLOR.kraj, { kind: 'kraj', area, keepInside: true });
    }
    for (const k of coarse.kraje) {
      const area = coarseAreas.get(`kraj:${k.id}`);
      l.inParts(k.parts, k.name, KRAJ_FONT, 14, (p) => l.label(k.name, p, KRAJ_FONT, 14, COLOR.kraj, { kind: 'kraj', area }));
    }
  }

  /* The results of the regional obvody where no obec names carry them
   * (`labelling` *l*): all below the shards, else, where *obce* are named,
   * those known only as a whole. */
  function drawZskResults(l, obce) {
    if (!results) return;
    for (const o of coarse.obvody) {
      const r = o.id.startsWith('zsk:') && results.zsk.get(o.id.slice('zsk:'.length));
      if (!r || (obce && !r[2])) continue;
      const area = coarseAreas.get(o.id);
      const p = l.spot(area, l.at(o.label), r[1], OBVOD_FONT, 12);
      if (p) l.value(r[1], p.x, p.y, area);
    }
  }

  /* The names of the okresy (`labelling` *l*). */
  function drawOkresNames(l) {
    const name = (o) => (p) =>
      l.label(o.name, p, NAME_FONT, NAME_SIZE, COLOR.label, { kind: 'okres', area: coarseAreas.get(`okres:${o.id}`) });
    for (const o of coarse.okresy) {
      name(o)(l.spot(coarseAreas.get(`okres:${o.id}`), l.at(o.label), o.name, NAME_FONT, NAME_SIZE, o.parts));
    }
    for (const o of coarse.okresy) l.inParts(o.parts, o.name, NAME_FONT, NAME_SIZE, name(o));
  }

  // Whether an obec (or council obvod) with properties *props* is filled by
  // its okrsky at zoom *z*, which then carry the values.
  const byOkrsky = (props, z) =>
    Boolean(results) && showsUnits('okrsky', z) && results.okrsokObce.has(props.id) && okrskyShown.has(props.okres);
  // Whether a feature of the shards with properties *props* is filled at
  // zoom *z* by its own value as a unit of *kind* ('obce', 'councils').
  const valuedAs = (kind, props, z) => Boolean(results) && !byOkrsky(props, z) && shardUnit(props, z)?.[0] === kind;

  /* The labels of the shards in view (`labelling` *l*): the numbers of the
   * council obvody, the names of the obce, the numbers of the okrsky. */
  function drawShardLabels(l) {
    // The features in view ({feature, obec, piece}, see `areasOf`), and the
    // obce they are of.
    const features = [];
    const inView = new Set();
    for (const s of shown.values()) {
      const areas = areasOf(s.file);
      for (const f of s.file.features) {
        if (!boxesIntersect(f.box, l.view.box)) continue;
        const a = areas.get(f);
        features.push(a);
        if (a.obec.label) inView.add(a.obec);
      }
    }
    drawCouncilNumbers(l, features);
    drawObecNames(l, inView);
    drawOkrsokNumbers(l);
  }

  /* The council obvody among *features* (`drawShardLabels`) of the obce
   * drawn as theirs, numbered where the overlay numbers them or they are
   * filled by their own values, each value under its number: the main
   * one, else the first of its other parts numbered. */
  function drawCouncilNumbers(l, features) {
    const { z } = l;
    const numbered = drawsOverlay('oz', z) && within(z, OVERLAYS.oz.numbers);
    const pieces = features.filter((a) => a.piece && (numbered || valuedAs('councils', a.feature.properties, z)));
    const text = (a) => obvodText(a.feature.properties.oz);
    const number = (a) => (p) => l.number(text(a), p, OBVOD_FONT, COLOR.council, 'oz', a.piece);
    const resultOf = (a) => {
      const props = a.feature.properties;
      return valuedAs('councils', props, z) ? results.councils.get(`${props.id}/${props.oz}`)?.[1] : undefined;
    };
    const unvalued = new Set();
    for (const a of pieces) {
      const props = a.feature.properties;
      const p = l.spot(a.piece, l.at(props.oz_label), text(a), OBVOD_FONT, 12, props.oz_parts);
      if (!l.labelWithValue(number(a), p, resultOf(a), a.piece)) unvalued.add(a);
    }
    for (const a of pieces) {
      let value = unvalued.has(a) ? resultOf(a) : undefined;
      l.inParts(a.feature.properties.oz_parts, text(a), OBVOD_FONT, 12, (p) => {
        if (l.labelWithValue(number(a), p, value, a.piece)) value = undefined;
      });
    }
  }

  /* The names of the obce *inView* (`drawShardLabels`) that have room for
   * them (OBEC_ROOM), larger obce first: they are the likelier landmarks.
   * An obec cut into its council obvody is named once (at the label of the
   * piece that has it), by the area of the whole obec; then its other
   * parts, if it has several. With the results, an obec's value goes under
   * its name (else under that of the first of its other parts named), as a
   * label of its own, so that the name stays where it was; not where finer
   * units are filled with theirs. */
  function drawObecNames(l, inView) {
    const { ctx, view, z } = l;
    const scale = 4 ** view.zoom;
    const named = [...inView].sort((a, b) => b.area - a.area);
    const name = (a) => (p) =>
      l.label(a.label.properties.name, p, NAME_FONT, NAME_SIZE, COLOR.label, { kind: 'obec', area: a, gap: OBEC_GAP });
    const resultOf = (a) => (valuedAs('obce', a.label.properties, z) ? results.obce.get(a.label.properties.id)?.[1] : undefined);
    const unvalued = new Set();
    for (const a of named) {
      const props = a.label.properties;
      if (a.area * scale < OBEC_ROOM * textWidth(ctx, NAME_FONT, props.name) * NAME_SIZE) continue;
      const p = l.spot(a, pixelAt(view, a.label.lx, a.label.ly), props.name, NAME_FONT, NAME_SIZE, props.parts);
      if (!l.labelWithValue(name(a), p, resultOf(a), a)) unvalued.add(a);
    }
    for (const a of named) {
      let value = unvalued.has(a) ? resultOf(a) : undefined;
      l.inParts(a.label.properties.parts, a.label.properties.name, NAME_FONT, NAME_SIZE, (p) => {
        if (l.labelWithValue(name(a), p, value, a)) value = undefined;
      });
    }
  }

  /* Areas of the okrsky of okrsky file *file* for the labels (`Placer`),
   * made on first use: feature → {own, over, file, features, box}, each
   * overlapping its obec and its council obvod, whose labels it may stack
   * with. */
  const okrsokAreas = new WeakMap();
  function okrsokAreasOf(file) {
    let areas = okrsokAreas.get(file);
    if (areas) return areas;
    areas = new Map();
    for (const f of file.features) {
      const { obec, okrsok, obvod } = f.properties;
      const own = `okrsok:${obec}/${okrsok}`;
      areas.set(f, { own, over: [own, `obec:${obec}`, `council:${obec}/${obvod}`], file, features: [f], box: f.box });
    }
    okrsokAreas.set(file, areas);
    return areas;
  }

  /* The number of every okrsok in view where the okrsky are numbered, and
   * from the zoom of their units (`showsUnits`) of those with a value of
   * the results, with the value under it; larger okrsky first
   * (`labelling` *l*). */
  function drawOkrsokNumbers(l) {
    const { view, z } = l;
    const numbered = drawsOverlay('okrsky', z) && within(z, OVERLAYS.okrsky.numbers);
    const valued = Boolean(results?.okrsky.size) && showsUnits('okrsky', z);
    if (!numbered && !valued) return;
    const labels = [];
    for (const s of okrskyShown.values()) {
      const areas = okrsokAreasOf(s.file);
      for (const f of s.file.features) {
        if (f.lx === undefined || !boxesIntersect(f.box, view.box)) continue;
        const r = valued ? results.okrsky.get(okrsokKey(f.properties)) : undefined;
        if (numbered || r) labels.push([f, areas.get(f), r]);
      }
    }
    labels.sort((a, b) => b[0].area - a[0].area);
    for (const [f, area, r] of labels) {
      const text = strings.okrsok.replace('{n}', f.properties.okrsok);
      const p = l.spot(area, pixelAt(view, f.lx, f.ly), text, OKRSOK_FONT, 12);
      const y = l.number(text, p, OKRSOK_FONT, COLOR.okrsok, 'okrsok', area);
      if (r && typeof y === 'number') l.value(r[1], p.x, y + VALUE_DROP, area);
    }
  }

  /* The houses in view, a dot and the number of each (`labelling` *l*). */
  function drawHouses({ ctx, placer, view }) {
    const [x0, y0, x1, y1] = view.box;
    const dots = new Path2D();
    // Number, x, y of every house drawn.
    const text = [];
    for (const file of addresses.values()) {
      for (const g of file.groups) {
        const xy = housePixels(g);
        for (let i = 0; i < g.numbers.length; i++) {
          const hx = xy[2 * i];
          const hy = xy[2 * i + 1];
          if (!(hx >= x0 && hx <= x1 && hy >= y0 && hy <= y1)) continue;
          const x = Math.round(hx * view.k) - view.x;
          const y = Math.round(hy * view.k) - view.y;
          dots.moveTo(x + 2, y);
          dots.arc(x, y, 2, 0, 2 * Math.PI);
          text.push(shownNumber(g.numbers[i]), x + 4, y);
        }
      }
    }
    ctx.fillStyle = COLOR.house;
    ctx.fill(dots);
    const style = { align: 'left', kind: 'house' };
    for (let i = 0; i < text.length; i += 3) {
      drawText(ctx, placer, text[i], text[i + 1], text[i + 2], HOUSE_FONT, HOUSE_SIZE, COLOR.text, style);
    }
  }

  /* The house nearest to (lon, lat) within PICK_RADIUS pixels at *zoom*, as
   * {obec, group, i}, or null. */
  function nearestHouse(lon, lat, zoom) {
    const k = 2 ** (zoom - Z0);
    const px = mercX(lon) * k;
    const py = mercY(lat) * k;
    let best = null;
    let bestDistance = PICK_RADIUS * PICK_RADIUS;
    for (const [obec, file] of addresses) {
      for (const group of file.groups) {
        const xy = housePixels(group);
        for (let i = 0; i < group.numbers.length; i++) {
          const d = (xy[2 * i] * k - px) ** 2 + (xy[2 * i + 1] * k - py) ** 2;
          if (d < bestDistance) {
            best = { obec, group, i };
            bestDistance = d;
          }
        }
      }
    }
    return best;
  }

  /* The properties of the obec at (lon, lat), from its shard drawn now,
   * else from its coarsest one; null where there is none. */
  async function obecAt(lon, lat) {
    // Degrees an okres's extent is widened by, for a point on its edge.
    const slack = 0.001;
    const x = mercX(lon);
    const y = mercY(lat);
    for (const [okres, b] of Object.entries(geoIndex.okresy)) {
      if (!boxContains([b[0] - slack, b[1] - slack, b[2] + slack, b[3] + slack], lon, lat)) continue;
      const file = shown.get(okres)?.file ?? (await loadShard(okres, coarsestLod));
      const f = featureAt(file, x, y);
      if (f) return f.properties;
    }
    return null;
  }

  /* The okrsok of obec *p* (properties of its shard's feature) at (lon,
   * lat) at *zoom*, from its okrsky file drawn now, else of the level of
   * detail of its shard drawn now or of the zoom, as its properties; null
   * where the obec has none drawn. */
  async function okrsokAt(p, lon, lat, zoom) {
    if (!okrsokObce.has(p.id)) return null;
    const x = mercX(lon);
    const y = mercY(lat);
    // The okrsky at the level of the shard the obec was found in, or else
    // of the zoom: a coarser one may put a point near a border in the
    // wrong okrsok.
    const lod = shown.get(p.okres)?.lod ?? lodAt(okrsokBands, zoom) ?? okrsokBands[0].lod;
    const file = okrskyShown.get(p.okres)?.file ?? (await loadOkrsky(p.okres, lod));
    const f = featureAt(file, x, y, (q) => q.obec === p.id);
    return f?.properties ?? null;
  }

  /* The unit of the results whose fill is drawn at (lon, lat), from what
   * is drawn now, without loading anything: {kind, key}, `kind` 'okrsky',
   * 'councils', 'obce' or 'zsk' and `key` as `results` has them (as
   * `drawShapes` fills them); null where none is. */
  function unitAt(lon, lat) {
    if (!results) return null;
    const z = level();
    const x = mercX(lon);
    const y = mercY(lat);
    const at = (file, which) => featureAt(file, x, y, which);
    let f = null;
    for (const s of shown.values()) {
      f = at(s.file);
      if (f) break;
    }
    if (!f) {
      const cell = at(coarse);
      const key = cell && zskOf(cell.properties);
      return key && results.zsk.has(key) ? { kind: 'zsk', key } : null;
    }
    const p = f.properties;
    const okrsky = showsUnits('okrsky', z) && okrsokObce.has(p.id) ? okrskyShown.get(p.okres)?.file : null;
    const okrsok = okrsky ? at(okrsky, (q) => q.obec === p.id) : null;
    const key = okrsok ? okrsokKey(okrsok.properties) : null;
    if (key && results.okrsky.has(key)) return { kind: 'okrsky', key };
    const [, , which] = fillGroups(z)[0];
    const unit = which(f) ? shardUnit(p, z) : null;
    return unit && { kind: unit[0], key: unit[1] };
  }

  const featureOf = (file, info) => {
    const features = file.features.filter((f) => f.properties.id === info.code);
    return features.length ? { file, features, box: boxOf(features) } : null;
  };

  /* The obec *info* as {file, features, box}: from its shard drawn now, so
   * its border is theirs, else from the coarsest one. An obec cut into its
   * council obvody is several features. */
  async function obecFeature(info) {
    const own = shown.get(info.okres);
    return featureOf(own?.file ?? (await loadShard(info.okres, coarsestLod)), info);
  }

  /* The selected obec *info* to draw now (see `obecFeature`), as
   * {file, features, box}; null while its coarsest shard loads, which then draws. */
  function shownObec(info) {
    const own = shown.get(info.okres);
    if (own) return featureOf(own.file, info);
    if (selectedObec?.code !== info.code) {
      const entry = { code: info.code, obec: null };
      selectedObec = entry;
      loadShard(info.okres, coarsestLod)
        .then((file) => {
          if (selectedObec !== entry) return;
          entry.obec = featureOf(file, info);
          redraw();
        })
        .catch(logError);
    }
    return selectedObec.obec;
  }

  return {
    /* Draws *view* (map.js `viewAt`), the page's latest, with *free* the
     * part of it left uncovered (map.js `freePart`); *seq* counts the views
     * and comes back with the drawing. */
    show(view, free, seq) {
      current = { view, free, seq };
      refresh(view);
      redraw();
    },

    /* What a click at (lon, lat) at *zoom* picks, as map.js `onPick` takes
     * it, or null: from zoom 16 the house there, else the obec; in one drawn
     * as its council obvody the obvod clicked, whose boundary may be drawn
     * from the addresses, so the ballots say it is approximate; likewise
     * the okrsok, where the obec's okrsky are drawn. */
    async pick(lon, lat, zoom) {
      if (Math.floor(zoom) >= ADDRESS_ZOOM) {
        const h = nearestHouse(lon, lat, zoom);
        if (h) {
          return {
            obec: h.obec,
            lat: h.group.lat[h.i],
            lon: h.group.lon[h.i],
            label: `${h.group.name} ${h.group.numbers[h.i]}`,
            obvod: h.group.obvody?.[h.i] ?? null,
            okrsok: h.group.okrsky?.[h.i] ?? null,
          };
        }
      }
      const props = await obecAt(lon, lat);
      if (!props) return null;
      const okrsok = await okrsokAt(props, lon, lat, zoom);
      return {
        obec: props.id,
        lat,
        lon,
        obvod: props.oz ?? null,
        approximate: Boolean(props.approx),
        okrsok: okrsok?.okrsok ?? null,
        okrsokApproximate: Boolean(okrsok?.approx),
      };
    },

    /* The unit of the results under the pointer at (lon, lat), for its
     * tooltip (`unitAt`). */
    hover(lon, lat) {
      return unitAt(lon, lat);
    },

    /* Shows *p* ({obec, info, lat?, lon?, label?, obvod?, street?, part?},
     * info as data.js `obecInfo` gives it) as the selected place, or
     * nothing; a street or part is highlighted. Resolves to the located
     * houses of the street or part ([[lat, lon]]) or null, or undefined if
     * a later call came meanwhile. */
    async select(p) {
      const gen = ++selection;
      const shape = p
        ? await streetShape(p).catch((e) => {
            // The obec is still selected, only not the street.
            console.error(e);
            return null;
          })
        : null;
      if (gen !== selection) return undefined;
      place = p ? { ...p, shape } : null;
      redraw();
      return shape?.points ?? null;
    },

    /* The box in Z0 pixels of obec *info* (data.js `obecInfo`), or of its
     * council *obvod* where it is drawn as its obvody; null if it has none. */
    async obecBox(info, obvod = null) {
      const obec = await obecFeature(info);
      if (!obec) return null;
      const pieces = obvod === null ? [] : obec.features.filter((f) => f.properties.oz === obvod);
      return pieces.length ? boxOf(pieces) : obec.box;
    },

    /* The box in Z0 pixels of *area* (as `inArea` takes it), or null. */
    areaBox(area) {
      const cells = coarse.features.filter((f) => inArea(area, f.properties));
      return cells.length ? boxOf(cells) : null;
    },

    /* Switches the overlays on or off: *wanted* {zsk, city, oz, okrsky,
     * base, buildings}, `base` the roads, railways and waters of the base
     * map; *counts*, once the council overlay is on, the number of council
     * obvody of every obec by code. */
    setOverlays(wanted, counts) {
      overlays = wanted;
      councils = counts ?? councils;
      if (current) {
        refreshOkrsky(current.view);
        loadBuildings();
      }
      refreshBase();
      redraw();
    },

    /* Colours the land by the 2026 results *next* (mapmode.js): {steps,
     * tone, palette?, obce: {code: [step, text]}, zsk: {'<kraj>/<n>':
     * [step, text, whole]}, councils: {'<obec>/<n>': [step, text]}, okrsky:
     * {'<obec>/<n>': [step, text]}}, step 0 the lowest of *steps*, `tone`
     * and `palette` as `results` has them, `whole` where the obvod is known
     * only as a whole; null for none. The fills cached for the values
     * before are let go, and the stripes of their ties. */
    setResults(next) {
      results = next && {
        steps: next.steps,
        tone: next.tone,
        palette: next.palette ?? null,
        obce: new Map(Object.entries(next.obce)),
        zsk: new Map(Object.entries(next.zsk)),
        councils: new Map(Object.entries(next.councils)),
        okrsky: new Map(Object.entries(next.okrsky)),
        okrsokObce: new Set(Object.keys(next.okrsky).map((key) => key.split('/')[0])),
      };
      stripePatterns.clear();
      const drawnFiles = [...shown.values(), ...okrskyShown.values()].map((s) => s.file);
      for (const file of [coarse, ...drawnFiles]) {
        for (const bin of file.bins) {
          for (const key of bin.paths?.keys() ?? []) if (key.includes(' result-')) bin.paths.delete(key);
        }
      }
      if (current) refreshOkrsky(current.view);
      redraw();
    },

    /* Draws again in the theme's colours *colors* (`COLOR`). */
    setColors(colors) {
      Object.assign(COLOR, colors);
      stripePatterns.clear();
      redraw();
    },

    /* Starts loading the shards of the view a zoom heads for: *zoom* and its
     * canvas *box* [west, south, east, north]. */
    prefetch(zoom, box) {
      const lod = lodFor(zoom);
      if (lod === null) return;
      for (const [okres, extent] of Object.entries(geoIndex.okresy)) {
        // A failed load is retried, and reported, when the view needs it.
        if (boxesIntersect(extent, box)) loadShard(okres, lod).catch(() => {});
      }
    },
  };
}
