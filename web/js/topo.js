/* The geo files (geo.py) in memory, and what the map computes on them.
 *
 * A geo file is a topology: arcs, delta coded in 1/scale degree, each with a
 * line code, and features whose rings list arcs by index (~i: reversed). It
 * is decoded once into typed arrays, in Web Mercator pixels at the reference
 * zoom Z0 relative to an origin of the file's own: 8 bytes a vertex and no
 * object per point. Near the origin a float32 stays within a few hundredths
 * of a pixel even at zoom 19, where world pixels would be several off.
 *
 * The map draws Path2D objects made from those arrays once per shown file
 * and scales them to the zoom by the canvas transform, so a redraw runs no
 * JavaScript per vertex. Each file is cut into bins, squares about a view
 * wide at the lowest zoom it is drawn at, and only the bins in view are
 * drawn: zoomed in, a large file costs what is on screen.
 *
 * Hit testing is even-odd ray casting over every ring of a feature, as the
 * fills are drawn: obce share their borders exactly, so a point on a border
 * may count for either neighbour; a click is never exactly on one.
 */

export const Z0 = 12;
const WORLD = 256 * 2 ** Z0;

/* Web Mercator pixels at zoom Z0, as Leaflet projects (EPSG:3857). */
export const mercX = (lon) => ((lon + 180) / 360) * WORLD;
export const mercY = (lat) =>
  (0.5 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / (2 * Math.PI)) * WORLD;

/* The arc a ref names: ~a for arc a reversed. */
export const arcOf = (r) => (r < 0 ? ~r : r);

/* Decodes *topo* (a geo file as parsed from JSON) into
 * {origin, xy, start, lines, features, bins, land?, kraje?, okresy?, obvody?}:
 * vertex i at (xy[2i], xy[2i+1]) + origin, arc a its vertices start[a] up to
 * start[a+1], lines[a] its code. A feature keeps `properties` and `arcs` and
 * gets `box` [x0, y0, x1, y1] (in Z0 pixels, like every coordinate here but
 * xy), `area` (squared pixels at zoom 0, times 4^z at zoom z) and the
 * position (lx, ly) of its label, if it has one. *binSize* is the side of a
 * bin in Z0 pixels. */
export function decode(topo, binSize) {
  const { scale } = topo;
  const count = topo.arcs.length;
  const start = new Uint32Array(count + 1);
  for (let a = 0; a < count; a++) start[a + 1] = start[a] + topo.arcs[a].length / 2;
  const xy = new Float32Array(2 * start[count]);
  const first = topo.arcs[0];
  const ox = first ? mercX(first[0] / scale) : 0;
  const oy = first ? mercY(first[1] / scale) : 0;
  // [x0, y0, x1, y1] of every arc, relative to the origin.
  const arcBox = new Float64Array(4 * count);
  let v = 0;
  for (let a = 0; a < count; a++) {
    const arc = topo.arcs[a];
    let x = 0;
    let y = 0;
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (let i = 0; i < arc.length; i += 2) {
      x += arc[i];
      y += arc[i + 1];
      const px = mercX(x / scale) - ox;
      const py = mercY(y / scale) - oy;
      xy[v++] = px;
      xy[v++] = py;
      if (px < x0) x0 = px;
      if (px > x1) x1 = px;
      if (py < y0) y0 = py;
      if (py > y1) y1 = py;
    }
    arcBox.set([x0, y0, x1, y1], 4 * a);
  }
  const file = { origin: [ox, oy], xy, start, lines: Uint8Array.from(topo.lines) };
  const features = topo.features.map((f) => {
    const feature = { properties: f.properties, arcs: f.arcs };
    // The outer rings bound the feature.
    const box = [Infinity, Infinity, -Infinity, -Infinity];
    for (const polygon of f.arcs) {
      for (const r of polygon[0]) {
        const a = 4 * arcOf(r);
        box[0] = Math.min(box[0], arcBox[a] + ox);
        box[1] = Math.min(box[1], arcBox[a + 1] + oy);
        box[2] = Math.max(box[2], arcBox[a + 2] + ox);
        box[3] = Math.max(box[3], arcBox[a + 3] + oy);
      }
    }
    feature.box = box;
    feature.area = area(file, feature) / 4 ** Z0;
    const label = f.properties.label;
    if (label) {
      feature.lx = mercX(label[0]);
      feature.ly = mercY(label[1]);
    }
    return feature;
  });
  file.features = features;
  file.bins = bins(file, arcBox, binSize);
  for (const key of ['land', 'kraje', 'okresy', 'obvody']) if (topo[key]) file[key] = topo[key];
  return file;
}

/* Arcs and features grouped into squares of *size* by the middle of their
 * box: [{box, arcs, features, paths}], box (relative to the origin) around
 * all that is in the bin, `paths` the Path2D cache of `binPath`. */
function bins(file, arcBox, size) {
  const [ox, oy] = file.origin;
  const grid = new Map();
  const binAt = (x0, y0, x1, y1) => {
    const key = `${Math.floor((x0 + x1) / 2 / size)},${Math.floor((y0 + y1) / 2 / size)}`;
    let bin = grid.get(key);
    if (!bin) {
      bin = { box: [Infinity, Infinity, -Infinity, -Infinity], arcs: [], features: [], paths: null };
      grid.set(key, bin);
    }
    const b = bin.box;
    b[0] = Math.min(b[0], x0);
    b[1] = Math.min(b[1], y0);
    b[2] = Math.max(b[2], x1);
    b[3] = Math.max(b[3], y1);
    return bin;
  };
  for (let a = 0; a < file.lines.length; a++) {
    binAt(arcBox[4 * a], arcBox[4 * a + 1], arcBox[4 * a + 2], arcBox[4 * a + 3]).arcs.push(a);
  }
  for (const f of file.features) {
    const [x0, y0, x1, y1] = f.box;
    binAt(x0 - ox, y0 - oy, x1 - ox, y1 - oy).features.push(f);
  }
  return [...grid.values()].map((b) => ({ ...b, arcs: Uint32Array.from(b.arcs) }));
}

/* The bins of *file* that reach into *box* (Z0 pixels). */
export function binsIn(file, box) {
  const [ox, oy] = file.origin;
  const x0 = box[0] - ox;
  const y0 = box[1] - oy;
  const x1 = box[2] - ox;
  const y1 = box[3] - oy;
  return file.bins.filter((b) => b.box[0] <= x1 && b.box[2] >= x0 && b.box[1] <= y1 && b.box[3] >= y0);
}

/* The path *key* of *bin*, made by *make* (a Path2D or null) on first use. */
export function binPath(bin, key, make) {
  bin.paths ??= new Map();
  let path = bin.paths.get(key);
  if (path === undefined) {
    path = make();
    bin.paths.set(key, path);
  }
  return path;
}

/* Frees the paths of *file*, which is no longer drawn; `binPath` makes them
 * again when it is. */
export function releasePaths(file) {
  for (const b of file.bins) b.paths = null;
}

/* Feeds the ring *refs* of *file* to *sink*: moveTo at the first vertex,
 * lineTo along the rest. */
export function traceRing(file, refs, sink) {
  const { xy, start } = file;
  let first = true;
  for (const r of refs) {
    const a = arcOf(r);
    const n = start[a + 1] - start[a];
    // Every arc after the first begins where the one before ends.
    for (let j = first ? 0 : 1; j < n; j++) {
      const i = r >= 0 ? start[a] + j : start[a + 1] - 1 - j;
      if (first) sink.moveTo(xy[2 * i], xy[2 * i + 1]);
      else sink.lineTo(xy[2 * i], xy[2 * i + 1]);
      first = false;
    }
  }
}

/* Adds every ring of *feature* (of *file*) to *path*, closed. */
export function addFeature(path, file, feature) {
  for (const polygon of feature.arcs) {
    for (const ring of polygon) {
      traceRing(file, ring, path);
      path.closePath();
    }
  }
}

/* The border of the union of *features*: arc → its ref in its last ring,
 * for the arcs in an odd number of their rings. An arc between two of the
 * features is in both of their rings and drops out. */
export function borderArcs(features) {
  const border = new Map();
  for (const f of features) {
    for (const polygon of f.arcs) {
      for (const ring of polygon) {
        for (const r of ring) {
          const a = arcOf(r);
          if (border.has(a)) border.delete(a);
          else border.set(a, r);
        }
      }
    }
  }
  return border;
}

/* The area of *features* (of *file*) as one path to fill even-odd: only
 * their border (`borderArcs`), joined into closed rings. Filling every ring
 * would cover the same pixels, at the cost of rasterizing all the inner
 * edges. Null if there are no features. */
export function unionPath(file, features) {
  const border = borderArcs(features);
  if (!border.size) return null;
  const { xy, start } = file;
  const head = (r) => (r >= 0 ? start[r] : start[~r + 1] - 1);
  const tail = (r) => (r >= 0 ? start[r + 1] - 1 : start[~r]);
  const key = (i) => `${xy[2 * i]},${xy[2 * i + 1]}`;
  // The border arcs at each end point. Every point has an even number of
  // them, so a walk along unused ones only ends where it began.
  const at = new Map();
  for (const r of border.values()) {
    for (const k of [key(head(r)), key(tail(r))]) {
      const list = at.get(k);
      if (list) list.push(r);
      else at.set(k, [r]);
    }
  }
  const used = new Set();
  const path = new Path2D();
  for (const [a0, r0] of border) {
    if (used.has(a0)) continue;
    const ring = [];
    const origin = key(head(r0));
    let r = r0;
    while (r !== undefined) {
      used.add(arcOf(r));
      ring.push(r);
      const end = key(tail(r));
      if (end === origin) break;
      const next = at.get(end).find((n) => !used.has(arcOf(n)));
      // Walked from this end.
      r = next === undefined || key(head(next)) === end ? next : ~next;
    }
    traceRing(file, ring, path);
    path.closePath();
  }
  return path;
}

/* Adds arc *a* of *file* to *path* as a line of its own. */
export function addArc(path, file, a) {
  const { xy, start } = file;
  path.moveTo(xy[2 * start[a]], xy[2 * start[a] + 1]);
  for (let i = start[a] + 1; i < start[a + 1]; i++) path.lineTo(xy[2 * i], xy[2 * i + 1]);
}

/* Adds to *path* the dashes of arc *a* of *file* that reach into *box* [x0,
 * y0, x1, y1] (relative to the file's origin), for a stroke without a dash
 * pattern: *dash* the lengths as setLineDash takes them (an even number),
 * starting at the arc's first vertex as the canvas starts each subpath. The
 * canvas dashes the whole of a path, and zoomed in the borders it dashes run
 * on for hundreds of views beyond the one drawn: that cost more than all
 * else in a drawing. */
export function addDashedArc(path, file, a, box, dash) {
  const { xy, start } = file;
  const period = dash.reduce((sum, d) => sum + d, 0);
  // Distance along the arc, and whether the last point added ends a dash
  // that goes on.
  let along = 0;
  let down = false;
  for (let i = start[a]; i + 1 < start[a + 1]; i++) {
    const x0 = xy[2 * i];
    const y0 = xy[2 * i + 1];
    const x1 = xy[2 * i + 2];
    const y1 = xy[2 * i + 3];
    const length = Math.hypot(x1 - x0, y1 - y0);
    const out =
      Math.max(x0, x1) < box[0] || Math.min(x0, x1) > box[2] || Math.max(y0, y1) < box[1] || Math.min(y0, y1) > box[3];
    if (out || !length) {
      along += length;
      down &&= !out;
      continue;
    }
    // The dash or gap *along* is in (k, even for a dash), and how far into
    // it; rounding may leave it at the very end of the last gap.
    let into = along % period;
    let k = 0;
    while (k < dash.length - 1 && into >= dash[k]) into -= dash[k++];
    if (into >= dash[k]) {
      into = 0;
      k = 0;
    }
    for (let t = 0; t < length; ) {
      const step = Math.min(dash[k] - into, length - t);
      if (k % 2 === 0) {
        if (!down) path.moveTo(x0 + ((x1 - x0) * t) / length, y0 + ((y1 - y0) * t) / length);
        path.lineTo(x0 + ((x1 - x0) * (t + step)) / length, y0 + ((y1 - y0) * (t + step)) / length);
        down = true;
      } else {
        down = false;
      }
      t += step;
      into += step;
      if (into >= dash[k]) {
        into = 0;
        k = (k + 1) % dash.length;
      }
    }
    along += length;
  }
}

/* Area of *feature* in squared Z0 pixels: holes taken off whichever way they
 * wind (shoelace). */
function area(file, feature) {
  let sum = 0;
  const shoelace = {
    a: 0,
    moveTo(x, y) {
      this.a = 0;
      this.x0 = x;
      this.y0 = y;
      this.x = x;
      this.y = y;
    },
    lineTo(x, y) {
      this.a += (this.x - x) * (this.y + y);
      this.x = x;
      this.y = y;
    },
  };
  for (const polygon of feature.arcs) {
    polygon.forEach((ring, i) => {
      traceRing(file, ring, shoelace);
      shoelace.lineTo(shoelace.x0, shoelace.y0);
      sum += i === 0 ? Math.abs(shoelace.a) / 2 : -Math.abs(shoelace.a) / 2;
    });
  }
  return sum;
}

/* Whether the point (x, y) in Z0 pixels is inside *feature* of *file*. */
export function contains(file, feature, x, y) {
  const px = x - file.origin[0];
  const py = y - file.origin[1];
  const ray = {
    inside: false,
    moveTo(x0, y0) {
      this.x0 = x0;
      this.y0 = y0;
      this.x = x0;
      this.y = y0;
    },
    lineTo(xj, yj) {
      const { x: xi, y: yi } = this;
      if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) this.inside = !this.inside;
      this.x = xj;
      this.y = yj;
    },
  };
  for (const polygon of feature.arcs) {
    for (const ring of polygon) {
      traceRing(file, ring, ray);
      ray.lineTo(ray.x0, ray.y0);
    }
  }
  return ray.inside;
}

/* The part of the union of *features* (of *file*) that holds the point (x,
 * y) in Z0 pixels, as one feature {arcs, box} of its polygons, or null where
 * none holds it. Polygons that share an arc are of one part. */
export function partAt(file, features, x, y) {
  const polygons = features.flatMap((f) => f.arcs);
  const hit = polygons.findIndex((polygon) => contains(file, { arcs: [polygon] }, x, y));
  if (hit < 0) return null;
  const root = polygons.map((_, i) => i);
  const find = (i) => {
    while (root[i] !== i) i = root[i] = root[root[i]];
    return i;
  };
  const owner = new Map();
  polygons.forEach((polygon, i) => {
    for (const ring of polygon) {
      for (const r of ring) {
        const j = owner.get(arcOf(r));
        if (j === undefined) owner.set(arcOf(r), i);
        else root[find(i)] = find(j);
      }
    }
  });
  const arcs = polygons.filter((_, i) => find(i) === find(hit));
  // The outer rings bound the part, as `decode` boxes a feature.
  const [ox, oy] = file.origin;
  const box = [Infinity, Infinity, -Infinity, -Infinity];
  const grow = (px, py) => {
    box[0] = Math.min(box[0], px + ox);
    box[1] = Math.min(box[1], py + oy);
    box[2] = Math.max(box[2], px + ox);
    box[3] = Math.max(box[3], py + oy);
  };
  for (const polygon of arcs) traceRing(file, polygon[0], { moveTo: grow, lineTo: grow });
  return { arcs, box };
}

export const boxContains = (b, x, y) => x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3];

export const boxesIntersect = (a, b) => a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1];
