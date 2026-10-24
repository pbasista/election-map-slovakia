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
 * The 2026 results (`setResults`, mapmode.js) colour the land in steps of
 * one colour: in the shards every obec by its value, or by that of its
 * regional obvod where only the obvod's is known (election night); below
 * them every regional obvod by its own value or that of its obce together.
 * The fills are cached paths like the land's, made again only when the
 * values change, under the borders and labels; an obec's name carries its
 * value, and an obvod's value is written at its label where no obec names
 * stand for it.
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
  binPath,
  binsIn,
  boxContains,
  boxesIntersect,
  contains,
  decode,
  mercX,
  mercY,
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
// Shards kept loaded, in vertices (8 bytes each, with the paths of the ones
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
// Line layers of a file, drawn in this order: the kraj and state borders
// above the overlays, so that where an obvod border runs along one it still
// reads as that.
const LINES = ['rank0', 'rank1', 'council', 'approx', 'zsk', 'city', 'rank2', 'rank3'];
// Dashes of an approximate council border, in pixels.
const APPROX_DASH = [5, 4];

// The theme's colours by name (map.js `readColors`), as the page last sent.
const COLOR = {};

// How much of a turnout's tone each step of the results has, the rest the
// land's, lowest first (app.css `.map-legend.toned` mixes the same).
const TONE_STEPS = [0.15, 0.32, 0.49, 0.66, 0.83, 1];

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

/* Whether an arc with line code *code* belongs to line layer *name*. */
function inLayer(name, code) {
  if (name in FLAG) return (code & FLAG[name]) !== 0;
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
  return rankStyle(Number(name.slice(4)), z);
}

const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
// Okres and obec names: one muted style, so names stay below the borders.
const NAME_SIZE = 12;
const NAME_FONT = `600 ${NAME_SIZE}px ${FONT}`;
const KRAJ_FONT = `700 14px ${FONT}`;
const OBVOD_FONT = `700 12px ${FONT}`;
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

/* Labels are placed greedily in priority order; a grid of buckets keeps the
 * overlap test cheap with thousands of house numbers. A label is
 * {box: [x0, y0, x1, y1], gap, kind, area}: its box (with a pixel or two
 * around the text), the pixels kept clear around it, its kind ('obec',
 * 'zsk', 'house'…) and the area it names, if any: {own, over}, its key
 * ('obec:<code>', 'zsk:<kraj>/<n>'…, see `cellKeys`) and the keys of the
 * areas it overlaps, its own among them. */
class Placer {
  constructor() {
    this.cell = 64;
    this.grid = new Map();
  }

  /* The labels placed that *label* would overlap, or null if one of them is
   * one it cannot stack with (`stackable`). Those it can stack with keep no
   * gap to it. */
  overlaps(label) {
    const [x0, y0, x1, y1] = label.box;
    const { gap } = label;
    const c = this.cell;
    const out = [];
    for (let gx = Math.floor((x0 - gap) / c); gx <= Math.floor((x1 + gap) / c); gx++) {
      for (let gy = Math.floor((y0 - gap) / c); gy <= Math.floor((y1 + gap) / c); gy++) {
        const bucket = this.grid.get(gx * 100003 + gy);
        if (!bucket) continue;
        for (const r of bucket) {
          const [rx0, ry0, rx1, ry1] = r.box;
          const g = gap + r.gap;
          if (!(x0 - g < rx1 && x1 + g > rx0 && y0 - g < ry1 && y1 + g > ry0)) continue;
          if (!stackable(label, r)) return null;
          if (x0 < rx1 && x1 > rx0 && y0 < ry1 && y1 > ry0) out.push(r);
        }
      }
    }
    return out;
  }

  add(label) {
    const [x0, y0, x1, y1] = label.box;
    const { gap } = label;
    const c = this.cell;
    for (let gx = Math.floor((x0 - gap) / c); gx <= Math.floor((x1 + gap) / c); gx++) {
      for (let gy = Math.floor((y0 - gap) / c); gy <= Math.floor((y1 + gap) / c); gy++) {
        const key = gx * 100003 + gy;
        const bucket = this.grid.get(key);
        if (bucket) bucket.push(label);
        else this.grid.set(key, [label]);
      }
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
  const border = new Set();
  for (const f of area.features) {
    for (const polygon of f.arcs) {
      for (const ring of polygon) {
        for (const r of ring) {
          const a = r < 0 ? ~r : r;
          if (border.has(a)) border.delete(a);
          else border.add(a);
        }
      }
    }
  }
  const { xy, start } = file;
  const [ox, oy] = file.origin;
  const near = [];
  // The rows spanned by the segments right of the rect: y0, y1 of each.
  const right = [];
  for (const a of border) {
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
  const heap = [];
  const push = (c) => {
    let i = heap.length;
    heap.push(c);
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (heap[parent].max >= c.max) break;
      heap[i] = heap[parent];
      i = parent;
    }
    heap[i] = c;
  };
  const pop = () => {
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
  };
  const size = Math.min((x1 - x0) * s, y1 - y0);
  for (let x = x0 * s; x < x1 * s; x += size) {
    for (let y = y0; y < y1; y += size) push(cell(x + size / 2, y + size / 2, size / 2));
  }
  let best = cell(((x0 + x1) / 2) * s, (y0 + y1) / 2, 0);
  let probes = heap.length;
  while (heap.length && probes < SPOT_PROBES) {
    const c = pop();
    if (c.value > best.value) best = c;
    // A cell that cannot hold a better spot, or one with room, is done.
    if (c.max - best.value <= SPOT_PRECISION || c.d + c.half * Math.SQRT2 < need) continue;
    const half = c.half / 2;
    for (const [dx, dy] of [
      [-1, -1],
      [1, -1],
      [-1, 1],
      [1, 1],
    ]) {
      push(cell(c.x + dx * half, c.y + dy * half, half));
    }
    probes += 4;
  }
  return best.d >= need ? { x: Math.round(best.x / s), y: Math.round(best.y) } : null;
}

/* Sets the transform of *ctx* to draw the coordinates of *file* in *view*. */
function placeFile(ctx, file, view) {
  const s = view.ratio * view.k;
  const [ox, oy] = file.origin;
  ctx.setTransform(s, 0, 0, s, view.ratio * (ox * view.k - view.x), view.ratio * (oy * view.k - view.y));
}

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
  const grow = (box, b) => {
    box[0] = Math.min(box[0], b[0]);
    box[1] = Math.min(box[1], b[1]);
    box[2] = Math.max(box[2], b[2]);
    box[3] = Math.max(box[3], b[3]);
  };
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
        a = { own, over: [own], file: coarse, features: [], box: [Infinity, Infinity, -Infinity, -Infinity] };
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
        const box = [Infinity, Infinity, -Infinity, -Infinity];
        obec = { own, over: [own, ...cellKeys(p)], file, features: [], box, label: null, area: 0 };
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
  // The shards drawn at zoom *z*: each band runs from zoom[0] up to zoom[1].
  const lodFor = (z) =>
    bands.find((b) => z >= b.zoom[0] && (b.zoom[1] === null || z < b.zoom[1]))?.lod ?? null;
  const binSize = Object.fromEntries(
    bands.map((b) => [b.lod, BIN_PIXELS / 2 ** (b.zoom[0] - Z0)]),
  );

  // The countries around: the finest level whose band has begun at the zoom
  // and whose extent holds all that is drawn (a very large view keeps a
  // coarser one). {lod, file} once one has come.
  const neighbourBands = [...geoIndex.neighbours].sort((a, b) => b.zoom[0] - a.zoom[0]);
  const neighbourFiles = new Map();
  let neighbours = null;
  const neighbourBand = (zoom, box) =>
    neighbourBands.find(
      (b) =>
        zoom >= b.zoom[0] && b.extent[0] <= box[0] && b.extent[1] <= box[1] && b.extent[2] >= box[2] && b.extent[3] >= box[3],
    ) ?? neighbourBands.at(-1);
  function loadNeighbours(band) {
    let file = neighbourFiles.get(band.lod);
    if (!file) {
      file = fetchJSON(`/geo/neighbours/${band.lod}.json`).then((topo) =>
        decode(topo, BIN_PIXELS / 2 ** (band.zoom[0] - Z0)),
      );
      neighbourFiles.set(band.lod, file);
      file.catch(() => neighbourFiles.delete(band.lod));
    }
    return file;
  }

  // The overlays switched on, and the number of council obvody of every obec
  // (data/index.json), which the council overlay colours them by.
  let overlays = { zsk: true, city: true, oz: true };
  let councils = null;
  // The 2026 results shown (`setResults`): {steps, tone, obce, zsk,
  // councils}, `tone` 'result' (the colours `result-<n>`) or the colour a
  // turnout is mixed from ('accent', 'council', 'city', 'zsk'), `obce` obec
  // code → [step, text], `zsk` '<kraj>/<n>' → [step, text, whole], `whole`
  // where the obvod is known only as a whole, `councils` '<obec>/<n>' →
  // [step, text] a municipal council obvod's; null for none.
  let results = null;
  const zskOf = (p) => `${p.kraj}/${p.zsk}`;
  let place = null;
  // Counts calls of `select`: a slower one that comes back late is dropped.
  let selection = 0;
  // The selected obec for when its shard is not drawn: {code, obec}, obec
  // ({file, feature}) from the coarsest shard once that has come.
  let selectedObec = null;
  // A contest's area shown from its pin on the ballots or in Favourites
  // (`showArea`), highlighted beside the selected place until the selection
  // changes: {area} as `inArea` takes it, or {info, obvod, obec} an obec or
  // its council obvod, with *obec* from its coarsest shard (`obecFeature`)
  // for while its own is not drawn. `areaAsked`: the one last asked for.
  let areaShown = null;
  let areaAsked = null;
  // The page's latest view: {view, free, seq} (`show`).
  let current = null;
  const level = () => Math.floor(current.view.zoom);
  // okres → {lod, file}: the shards drawn; the okresy in view and the level
  // of detail they are wanted at (`refresh`).
  const shown = new Map();
  let wanted = new Set();
  let wantedLod = null;
  const shards = new Cache(SHARD_VERTICES, (file) => file.xy.length / 2);
  const addresses = new Map();
  let wantedAddresses = new Set();

  const loadShard = (okres, lod) =>
    shards.get(`${okres}/${lod}`, async () =>
      decode(await fetchJSON(`/geo/okres/${okres}/${lod}.json`), binSize[lod]),
    );

  // The part of *view* the map shows (not the canvas around it) and *pad*
  // times its size on every side, in Z0 pixels.
  const viewPixels = (view, pad) => {
    const [x0, y0, x1, y1] = view.visible;
    const dx = (x1 - x0) * pad;
    const dy = (y1 - y0) * pad;
    const { k } = view;
    return [(view.x + x0 - dx) / k, (view.y + y0 - dy) / k, (view.x + x1 + dx) / k, (view.y + y1 + dy) / k];
  };
  // Whole pixels, as Leaflet's layer points: labels whose boxes just touch
  // do not overlap.
  const toPixel = (view, lat, lon) => ({
    x: Math.round(mercX(lon) * view.k) - view.x,
    y: Math.round(mercY(lat) * view.k) - view.y,
  });

  // An overlay is drawn from zoom `lines`, its obvod numbers within
  // `numbers` and the selected place's obvod highlighted within `highlight`
  // (zooms by `level`): numbers and a highlight need the obvody neither much
  // smaller nor much larger than the view.
  const OVERLAYS = {
    zsk: { lines: 0, numbers: [9, 11], highlight: [0, 10] },
    city: { lines: 10, numbers: [11, 13], highlight: [10, 13] },
    oz: { lines: 11, numbers: [12, Infinity], highlight: [11, Infinity] },
  };
  const drawsOverlay = (name, z) => overlays[name] && z >= OVERLAYS[name].lines;
  const within = (z, [from, to]) => z >= from && z <= to;

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

  /* The step of the results of a feature with properties *p* in the
   * shards: its council obvod's where it is one and that is shown (a
   * council candidate's), else its obec's own, else its regional obvod's
   * where only that is known; undefined for none. */
  function obecStep(p) {
    const piece = p.oz === undefined ? undefined : results.councils.get(`${p.id}/${p.oz}`);
    if (piece) return piece[0];
    const own = results.obce.get(p.id);
    if (own) return own[0];
    const obvod = results.zsk.get(zskOf(p));
    return obvod?.[2] ? obvod[0] : undefined;
  }

  /* Fills the features of *file* in *bins* in the colour of their step of
   * the results, *stepOf(feature)*, over the land: one path per step and
   * bin, cached under *group* (`setResults` lets go of them). */
  function fillResults(ctx, file, bins, group, stepOf) {
    for (let s = 0; s < results.steps; s++) {
      ctx.fillStyle =
        results.tone === 'result' ? COLOR[`result-${s + 1}`] : mix(COLOR.land, COLOR[results.tone], TONE_STEPS[s]);
      for (const bin of bins) {
        const path = binPath(bin, `${group} result-${s}`, () =>
          unionPath(file, bin.features.filter((f) => stepOf(f) === s)),
        );
        if (path) ctx.fill(path, 'evenodd');
      }
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
    return out.map(([file, names]) => [file, names, binsIn(file, view.box)]).filter((d) => d[2].length);
  }

  /* The countries around, below Slovakia: their land, then their borders,
   * dashed. What they have under Slovakia its fill covers. */
  function drawNeighbours(ctx, view) {
    if (!neighbours) return;
    const { file } = neighbours;
    const bins = binsIn(file, view.box);
    placeFile(ctx, file, view);
    ctx.fillStyle = COLOR.neighbour;
    for (const bin of bins) {
      const path = binPath(bin, 'land', () => unionPath(file, bin.features));
      if (path) ctx.fill(path, 'evenodd');
    }
    ctx.strokeStyle = COLOR['neighbour-line'];
    ctx.lineWidth = 1 / view.k;
    const dashes = dashedPath(file, bins, view, NEIGHBOUR_DASH, () => true);
    if (dashes) ctx.stroke(dashes);
  }

  function drawShapes(ctx, view) {
    const z = level();
    const files = drawn(view);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    drawNeighbours(ctx, view);
    for (const [file, , bins] of files) {
      placeFile(ctx, file, view);
      if (file === coarse) {
        // The land, not the coarse cells: one path, and no seam shows where
        // two cells meet.
        coarse.landPath ??= unionPath(coarse, [{ arcs: coarse.land }]);
        ctx.fillStyle = COLOR.land;
        ctx.fill(coarse.landPath, 'evenodd');
        // The results by regional obvod, cell by cell.
        if (results) fillResults(ctx, coarse, bins, 'coarse', (f) => results.zsk.get(zskOf(f.properties))?.[0]);
        continue;
      }
      const groups = fillGroups(z);
      for (const [name, color, which] of groups) {
        ctx.fillStyle = color;
        for (const bin of bins) {
          const path = binPath(bin, name, () => unionPath(file, bin.features.filter(which)));
          if (path) ctx.fill(path, 'evenodd');
        }
      }
      // Over the land only: the council overlay's obce of no known obvod or
      // no council keep their colours.
      if (results) {
        const [land, , which] = groups[0];
        fillResults(ctx, file, bins, land, (f) => (which(f) ? obecStep(f.properties) : undefined));
      }
    }
    for (const name of LINES) {
      const style = lineStyle(name, z);
      ctx.strokeStyle = style.color;
      for (const [file, names, bins] of files) {
        if (!names.includes(name)) continue;
        placeFile(ctx, file, view);
        ctx.lineWidth = style.weight / view.k;
        const pick = (code) => inLayer(name, code);
        if (style.dash) {
          const path = dashedPath(file, bins, view, style.dash, pick);
          if (path) ctx.stroke(path);
          continue;
        }
        for (const bin of bins) {
          const path = binPath(bin, name, () => linesPath(file, bin.arcs, pick));
          if (path) ctx.stroke(path);
        }
      }
    }
    drawHighlight(ctx, view);
  }

  /* The arcs of *file* among *arcs* this file draws whose code passes
   * *pick*, as one path, or null if there are none. */
  function linesPath(file, arcs, pick) {
    const path = new Path2D();
    let any = false;
    for (const a of arcs) {
      const code = file.lines[a];
      if (code & FOREIGN || !pick(code)) continue;
      addArc(path, file, a);
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
    const path = new Path2D();
    let any = false;
    for (const bin of bins) {
      for (const a of bin.arcs) {
        const code = file.lines[a];
        if (code & FOREIGN || !pick(code)) continue;
        addDashedArc(path, file, a, box, lengths);
        any = true;
      }
    }
    return any ? path : null;
  }

  /* The overlay whose obvod of the selected place is highlighted at zoom
   * *z*: the finest drawn there that cuts the place out of what is around.
   * A selected area (a contest's without a place: a Bratislava or Košice
   * city contest's, a regional one's) is its overlay's at every zoom,
   * whether or not that is on: it is all there is to see of the
   * selection. */
  function highlighted(z) {
    if (place?.area) return 'kraj' in place.area ? 'zsk' : 'city';
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
   * of the files drawn now, the outline along the arcs *edge* picks around
   * them (for *overlay* 'oz', a council obvod within one obec, its
   * outline): an arc on an okres border is in both shards, and only one of
   * the two copies has a member on its side. */
  function drawArea(ctx, view, member, overlay, edge, color) {
    const files = lodFor(view.zoom) === null ? [coarse] : [...shown.values()].map((s) => s.file);
    const units = [];
    for (const file of files) {
      const fill = new Path2D();
      let line = new Path2D();
      const around = new Set();
      const members = file.features.filter((f) => member(f.properties));
      for (const f of members) {
        addFeature(fill, file, f);
        for (const p of f.arcs) for (const ring of p) for (const r of ring) around.add(r < 0 ? ~r : r);
      }
      if (!around.size) continue;
      if (overlay === 'oz') line = unionPath(file, members);
      else for (const a of around) if (edge(file.lines[a])) addArc(line, file, a);
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
    const path = unionPath(obec.file, obec.features);
    placeFile(ctx, obec.file, view);
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.08;
    ctx.fill(path, 'evenodd');
    ctx.globalAlpha = 1;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.5 / view.k;
    ctx.stroke(path);
  }

  /* Its border: of a whole kraj the kraj (or state) border, else the
   * overlay's. */
  const areaEdge = (area, overlay) =>
    area && 'kraj' in area && area.zsk === null ? (code) => (code & RANK) >= 2 : (code) => (code & FLAG[overlay]) !== 0;

  /* The selected obvod or area (its border from the files drawn now, so it
   * is theirs), the selected obec, a contest's area shown from its pin
   * (`areaShown`, in its overlay's colour, instead of the selected place's
   * obvod, which would read as part of it) and the selected point. */
  function drawHighlight(ctx, view) {
    const info = place?.info;
    const overlay = highlighted(level());
    const member = place?.area
      ? (p) => inArea(place.area, p)
      : {
          zsk: (p) => p.kraj === info.kraj && p.zsk === info.zsk,
          city: (p) => p.city === info.city && p.city_obvod === info.cityObvod,
          oz: (p) => p.id === info.code && p.oz === place.obvod,
        }[overlay];
    if (member && !areaShown) {
      const color = overlay === 'oz' ? COLOR.council : COLOR[overlay];
      drawArea(ctx, view, member, overlay, areaEdge(place?.area, overlay), color);
    }
    const obec = info?.okres ? shownObec(info) : null;
    if (obec) drawObec(ctx, view, obec, COLOR.accent);
    if (areaShown?.area) {
      const a = areaShown.area;
      const kind = 'kraj' in a ? 'zsk' : 'city';
      drawArea(ctx, view, (p) => inArea(a, p), kind, areaEdge(a, kind), COLOR[kind]);
    } else if (areaShown) {
      // An obec other than the selected one (which is outlined already),
      // and its council obvod where it is drawn as its obvody.
      const { info: shownInfo, obvod } = areaShown;
      const own = shown.get(shownInfo.okres);
      const o = own ? featureOf(own.file, shownInfo) : areaShown.obec;
      if (o && shownInfo.code !== info?.code) drawObec(ctx, view, o, COLOR.accent);
      const pieces = o && obvod !== null ? o.features.filter((f) => f.properties.oz === obvod) : [];
      if (pieces.length) drawObec(ctx, view, { file: o.file, features: pieces }, COLOR.council);
    }
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

  /* Loads what *view* shows and lets go of what it no longer does: the
   * shards of the okresy in its canvas at the level of detail of its zoom,
   * the countries around and (`loadAddresses`) the address files. Each
   * draws when it comes, if the latest view still wants it. */
  function refresh(view) {
    const lod = lodFor(view.zoom);
    const box = view.bounds;
    wantedLod = lod;
    wanted = new Set(
      lod === null ? [] : Object.keys(geoIndex.okresy).filter((o) => boxesIntersect(geoIndex.okresy[o], box)),
    );
    // An okres of another band stays drawn until its new shard has come: a
    // zoom shows the detail it had meanwhile, not a hole.
    for (const [okres, s] of shown) {
      if (!wanted.has(okres)) {
        shown.delete(okres);
        releasePaths(s.file);
      }
    }
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
        .catch((e) => console.error(e));
    }
    for (const okres of wanted) {
      if (shown.get(okres)?.lod === lod) continue;
      loadShard(okres, lod)
        .then((file) => {
          const old = shown.get(okres);
          if (!wanted.has(okres) || wantedLod !== lod || old?.lod === lod) return;
          if (old) releasePaths(old.file);
          shown.set(okres, { lod, file });
          settle();
          redraw();
        })
        .catch((e) => console.error(e));
    }
    settle();
  }

  /* Once every shard in view has come: coarse.json is no longer drawn (it
   * is below the zoom bands of the shards, and in them until then), and the
   * address files load. */
  function settle() {
    if (wantedLod === null) coarseShown = true;
    if (![...wanted].every((o) => shown.get(o)?.lod === wantedLod)) return;
    if (wantedLod !== null) coarseShown = false;
    loadAddresses();
  }

  function loadAddresses() {
    if (level() < ADDRESS_ZOOM) {
      wantedAddresses = new Set();
      if (addresses.size) redraw();
      addresses.clear();
      return;
    }
    const view = viewPixels(current.view, 0.1);
    const codes = new Set();
    for (const s of shown.values()) {
      for (const f of s.file.features) {
        if (boxesIntersect(f.box, view)) codes.add(f.properties.id);
      }
    }
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
        .catch((e) => console.error(e));
    }
  }

  /* The band around the houses of the highlighted street (`streetShape`) at
   * *pixels*: one stroke, so it is no darker where its parts overlap, hollowed
   * out by a narrower one to a light fill inside an outline. Hollowing erases
   * what is under it, so the band is made on a canvas of its own. */
  function streetBand(ctx, view, pixels, edges) {
    const lat = place.shape.points[0][0];
    const perPixel = (40075016.686 * Math.cos((lat * Math.PI) / 180)) / (256 * 2 ** view.zoom);
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

  /* Names the countries around in *view*, each at the one of its places
   * (geo.py `label_spots`) that leaves the name the most room: the least of
   * the place's own room at this zoom and its distance to the edges of
   * *free*, the free part of the map (map.js `freePart`), with the whole name
   * inside both. The places are in the country, out of Slovakia, so a name
   * never covers it; one that would cover a Slovak name tries the next
   * place. The names with the most room go first. */
  function drawNeighbourNames(ctx, placer, view, free) {
    // Metres a pixel spans at the equator.
    const metres = 40075016.686 / (256 * 2 ** view.zoom);
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
    const z = level();
    const placer = new Placer();
    const viewKey = `${view.zoom} ${view.x} ${view.y} ${free}`;
    if (spots.view !== viewKey) spots = { view: viewKey, of: new Map() };
    if (kept.zoom !== view.zoom) kept = { zoom: view.zoom, at: new Map() };
    const street = place?.shape?.points.map(([lat, lon]) => toPixel(view, lat, lon));
    if (street) streetBand(ctx, view, street, place.shape.edges);
    // The selected point's dot (radius 6 + stroke) is drawn above the labels;
    // a label that would sit under it moves just below it instead.
    const pin = place && Number.isFinite(place.lat) ? toPixel(view, place.lat, place.lon) : null;
    const PIN = 9;
    // *p* null (`spot`): the label is not drawn. Returns as `drawText`.
    const label = (name, p, font, size, color, { kind, area, keepInside = false, gap = 0 }) => {
      if (!p) return null;
      let { x, y } = p;
      if (pin) {
        const half = textWidth(ctx, font, name) / 2 + 2;
        const hits = Math.abs(p.x - pin.x) < half + PIN && Math.abs(p.y - pin.y) < size / 2 + PIN;
        if (hits) y = pin.y + PIN + size / 2 + 2;
      }
      if (keepInside) {
        // Kraj names label the whole country view; one at the edge of a
        // narrow (phone) map or by the pane, with no room in the part of
        // its kraj in view, would be cut off, so it slides inwards.
        const half = textWidth(ctx, font, name) / 2 + 4;
        x = Math.min(Math.max(x, free[0] + half), free[2] - half);
        y = Math.min(Math.max(y, free[1] + size / 2), free[3] - size / 2);
      }
      return drawText(ctx, placer, name, x, y, font, size, color, { gap, kind, area, bounds: free });
    };
    const at = ([lon, lat]) => toPixel(view, lat, lon);
    // Whether a label *w* × *h* centred at *q* is whole in the free part.
    const fits = (q, w, h) => q.x - w / 2 >= free[0] && q.x + w / 2 <= free[2] && q.y - h / 2 >= free[1] && q.y + h / 2 <= free[3];
    /* Where the label *text* of *area* goes, or null where it would be cut
     * off: a name half under the pane or past the edge of the map reads as
     * another word. Where it was last drawn at this zoom, if the whole label
     * is still in the free part of the map: a pan moves a label only once
     * the edge of the map or a pane reaches it. Else at the area's own spot
     * *p*, if the whole label is in the free part. Else, so that an area
     * seen only in part (its spot panned away or under a pane) is still
     * named, where the part of it in the free part leaves the label the
     * most room (`visibleSpot`), if it fits there. */
    const spot = (area, p, text, font, size) => {
      if (!area) return p;
      const w = textWidth(ctx, font, text) + 4;
      const h = size + 2;
      const key = `${area.own} ${text}`;
      const last = kept.at.get(key);
      const q = last && { x: Math.round(last.x * view.k) - view.x, y: Math.round(last.y * view.k) - view.y };
      if (q && fits(q, w, h)) return q;
      if (fits(p, w, h)) {
        kept.at.set(key, { x: (p.x + view.x) / view.k, y: (p.y + view.y) / view.k });
        return p;
      }
      let found = spots.of.get(key);
      if (found?.file !== area.file) {
        found = { file: area.file, at: visibleSpot(area, free, view, w, h) };
        spots.of.set(key, found);
      }
      if (found.at) kept.at.set(key, { x: (found.at.x + view.x) / view.k, y: (found.at.y + view.y) / view.k });
      else kept.at.delete(key);
      return found.at;
    };
    // The other parts of an area of several (geo.py `parts`: [lon, lat,
    // room in metres]) are labelled too where *text* fits in the room: the
    // box of the text within the largest circle inside the part.
    const metresPerPixel = (lat) => (40075016.686 * Math.cos((lat * Math.PI) / 180)) / (256 * 2 ** view.zoom);
    const inParts = (parts, text, font, size, draw) => {
      if (!parts) return;
      const w = textWidth(ctx, font, text) + 4;
      const need = Math.hypot(w / 2, size / 2 + 1);
      for (const [lon, lat, room] of parts) {
        const p = at([lon, lat]);
        if (room / metresPerPixel(lat) >= need && fits(p, w, size + 2)) draw(p);
      }
    };
    // Obvod numbers before the names: where an overlay is drawn, which obvod
    // is which is what the map is looked at for. Where the cities' numbers
    // are drawn, the regional obvody within them go unnumbered: two numbers
    // of two councils side by side would read as one series.
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
      const number = (o) => (p) =>
        p &&
        drawText(ctx, placer, text(o), p.x, p.y, OBVOD_FONT, 12, COLOR[name], {
          kind: name,
          area: coarseAreas.get(o.id),
          bounds: free,
        });
      for (const o of obvody) number(o)(spot(coarseAreas.get(o.id), at(o.label), text(o), OBVOD_FONT, 12));
      for (const o of obvody) inParts(o.parts, text(o), OBVOD_FONT, 12, number(o));
    }
    // Obce are named from the zoom their shards are drawn at, okresy before.
    const obce = lodFor(view.zoom) !== null;
    if (z < OKRES_ZOOM) {
      for (const k of coarse.kraje) {
        const area = coarseAreas.get(`kraj:${k.id}`);
        // Where no whole spot is free, at its own, slid inwards.
        const p = spot(area, at(k.label), k.name, KRAJ_FONT, 14) ?? at(k.label);
        label(k.name, p, KRAJ_FONT, 14, COLOR.kraj, { kind: 'kraj', area, keepInside: true });
      }
      for (const k of coarse.kraje) {
        const area = coarseAreas.get(`kraj:${k.id}`);
        inParts(k.parts, k.name, KRAJ_FONT, 14, (p) => label(k.name, p, KRAJ_FONT, 14, COLOR.kraj, { kind: 'kraj', area }));
      }
    }
    // The results of the regional obvody where no obec names carry them: all
    // below the shards, else those known only as a whole. After the names of
    // the kraje, before those of the okresy, both stacking with them.
    for (const o of results ? coarse.obvody : []) {
      const r = o.id.startsWith('zsk:') && results.zsk.get(o.id.slice('zsk:'.length));
      if (!r || (obce && !r[2])) continue;
      const area = coarseAreas.get(o.id);
      const p = spot(area, at(o.label), r[1], OBVOD_FONT, 12);
      if (p) drawText(ctx, placer, r[1], p.x, p.y, OBVOD_FONT, 12, COLOR.text, { kind: 'result', area, bounds: free });
    }
    if (z >= OKRES_ZOOM && !obce) {
      const okresName = (o) => (p) =>
        label(o.name, p, NAME_FONT, NAME_SIZE, COLOR.label, { kind: 'okres', area: coarseAreas.get(`okres:${o.id}`) });
      for (const o of coarse.okresy) {
        okresName(o)(spot(coarseAreas.get(`okres:${o.id}`), at(o.label), o.name, NAME_FONT, NAME_SIZE));
      }
      for (const o of coarse.okresy) inParts(o.parts, o.name, NAME_FONT, NAME_SIZE, okresName(o));
    }
    if (obce) {
      const scale = 4 ** view.zoom;
      // The features in view ({feature, obec, piece}, see `areasOf`), and
      // the obce they are of.
      const features = [];
      const inView = new Set();
      for (const s of shown.values()) {
        const areas = areasOf(s.file);
        for (const f of s.file.features) {
          if (!boxesIntersect(f.box, view.box)) continue;
          const a = areas.get(f);
          features.push(a);
          if (a.obec.label) inView.add(a.obec);
        }
      }
      // The council obvody of the obce drawn as theirs, each with its value
      // under its number where the results give one.
      if (drawsOverlay('oz', z) && within(z, OVERLAYS.oz.numbers)) {
        const pieces = features.filter((a) => a.piece);
        const text = (a) => obvodText(a.feature.properties.oz);
        const number = (a) => (p) =>
          p &&
          drawText(ctx, placer, text(a), p.x, p.y, OBVOD_FONT, 12, COLOR.council, {
            kind: 'oz',
            area: a.piece,
            bounds: free,
          });
        for (const a of pieces) {
          const { id, oz, oz_label: labelAt } = a.feature.properties;
          const p = spot(a.piece, at(labelAt), text(a), OBVOD_FONT, 12);
          const y = p && number(a)(p);
          const r = typeof y === 'number' && results?.councils.get(`${id}/${oz}`);
          if (r) drawText(ctx, placer, r[1], p.x, y + VALUE_DROP, OBVOD_FONT, 12, COLOR.text, { kind: 'result', area: a.piece, bounds: free });
        }
        for (const a of pieces) inParts(a.feature.properties.oz_parts, text(a), OBVOD_FONT, 12, number(a));
      }
      // Larger obce first: they are the likelier landmarks. An obec cut into
      // its council obvody is named once (at the label of the piece that
      // has it), by the area of the whole obec; then its other parts, if it
      // has several.
      const named = [...inView].sort((a, b) => b.area - a.area);
      // With the results, an obec's value goes under its name, where that is
      // drawn, as a label of its own, so that the name stays where it was.
      const obecName = (a) => (p) =>
        label(a.label.properties.name, p, NAME_FONT, NAME_SIZE, COLOR.label, { kind: 'obec', area: a, gap: OBEC_GAP });
      for (const a of named) {
        const { lx, ly } = a.label;
        const text = a.label.properties.name;
        if (a.area * scale < OBEC_ROOM * textWidth(ctx, NAME_FONT, text) * NAME_SIZE) continue;
        const p = spot(a, { x: Math.round(lx * view.k) - view.x, y: Math.round(ly * view.k) - view.y }, text, NAME_FONT, NAME_SIZE);
        const y = obecName(a)(p);
        const r = typeof y === 'number' && results?.obce.get(a.label.properties.id);
        if (r) drawText(ctx, placer, r[1], p.x, y + VALUE_DROP, OBVOD_FONT, 12, COLOR.text, { kind: 'result', area: a, bounds: free });
      }
      for (const a of named) inParts(a.label.properties.parts, a.label.properties.name, NAME_FONT, NAME_SIZE, obecName(a));
    }
    if (neighbours) drawNeighbourNames(ctx, placer, view, free);
    if (z >= ADDRESS_ZOOM) drawHouses(ctx, placer, view);
    if (street) streetDots(ctx, street);
  }

  function drawHouses(ctx, placer, view) {
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

  async function obecAt(lon, lat) {
    const slack = 0.001;
    const x = mercX(lon);
    const y = mercY(lat);
    for (const okres of Object.keys(geoIndex.okresy)) {
      const b = geoIndex.okresy[okres];
      if (!boxContains([b[0] - slack, b[1] - slack, b[2] + slack, b[3] + slack], lon, lat)) {
        continue;
      }
      const file = shown.get(okres)?.file ?? (await loadShard(okres, coarsestLod));
      for (const f of file.features) {
        if (boxContains(f.box, x, y) && contains(file, f, x, y)) return f.properties;
      }
    }
    return null;
  }

  // The box around *features*.
  const boxOf = (features) => {
    const box = [Infinity, Infinity, -Infinity, -Infinity];
    for (const f of features) {
      box[0] = Math.min(box[0], f.box[0]);
      box[1] = Math.min(box[1], f.box[1]);
      box[2] = Math.max(box[2], f.box[2]);
      box[3] = Math.max(box[3], f.box[3]);
    }
    return box;
  };

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
        .catch((e) => console.error(e));
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
     * from the addresses, so the ballots say it is approximate. */
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
          };
        }
      }
      const props = await obecAt(lon, lat);
      if (!props) return null;
      return { obec: props.id, lat, lon, obvod: props.oz ?? null, approximate: Boolean(props.approx) };
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
      areaShown = null;
      areaAsked = null;
      redraw();
      return shape?.points ?? null;
    },

    /* Highlights a contest's area beside the selected place (`areaShown`):
     * {area} as `inArea` takes it, or {info, obvod} an obec or its council
     * obvod; null for none. The next selection lets go of it. */
    async showArea(asked) {
      areaAsked = asked;
      const obec = asked?.info ? await obecFeature(asked.info) : null;
      if (areaAsked !== asked) return;
      areaShown = asked && { ...asked, obec };
      redraw();
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

    /* Switches the overlays on or off: *wanted* {zsk, city, oz}; *counts*,
     * once the council overlay is on, the number of council obvody of every
     * obec by code. */
    setOverlays(wanted, counts) {
      overlays = wanted;
      councils = counts ?? councils;
      redraw();
    },

    /* Colours the land by the 2026 results *next* (mapmode.js): {steps,
     * tone, obce: {code: [step, text]}, zsk: {'<kraj>/<n>': [step, text,
     * whole]}, councils: {'<obec>/<n>': [step, text]}}, step 0 the lowest
     * of *steps*, `tone` as `results` has it, `whole` where the obvod is
     * known only as a whole; null for none. The fills cached for the values
     * before are let go. */
    setResults(next) {
      results = next && {
        steps: next.steps,
        tone: next.tone,
        obce: new Map(Object.entries(next.obce)),
        zsk: new Map(Object.entries(next.zsk)),
        councils: new Map(Object.entries(next.councils)),
      };
      for (const file of [coarse, ...[...shown.values()].map((s) => s.file)]) {
        for (const bin of file.bins) {
          for (const key of bin.paths?.keys() ?? []) if (key.includes(' result-')) bin.paths.delete(key);
        }
      }
      redraw();
    },

    /* Draws again in the theme's colours *colors* (`COLOR`). */
    setColors(colors) {
      Object.assign(COLOR, colors);
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
