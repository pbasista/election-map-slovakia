/* Fetching and caching data files: what the page and the map's renderer
 * (draw.js, in a worker) share, so nothing here touches the DOM. File
 * layouts: src/election_map_slovakia/addresses.py (addr/), geo.py (geo/). */

/* Least recently used cache of promises: concurrent requests for one file
 * share one fetch, and a failed fetch is forgotten so it can be retried.
 * Holds values of a total *weigh* (default: one each) up to *limit*, the
 * most recent one at least; a value is weighed once it has loaded. */
export class Cache {
  constructor(limit, weigh = () => 1) {
    this.limit = limit;
    this.weigh = weigh;
    this.entries = new Map();
    this.total = 0;
  }

  get(key, load) {
    let entry = this.entries.get(key);
    if (entry) {
      this.entries.delete(key);
    } else {
      entry = { value: load(key), size: 0 };
      entry.value.then(
        (value) => {
          if (this.entries.get(key) !== entry) return;
          entry.size = this.weigh(value);
          this.total += entry.size;
          this.trim();
        },
        () => {
          if (this.entries.get(key) === entry) this.drop(key);
        },
      );
    }
    this.entries.set(key, entry);
    this.trim();
    return entry.value;
  }

  drop(key) {
    this.total -= this.entries.get(key).size;
    this.entries.delete(key);
  }

  trim() {
    while (this.entries.size > 1 && (this.total > this.limit || this.entries.size > this.limit)) {
      this.drop(this.entries.keys().next().value);
    }
  }
}

/* The build's data version (km-config `dataVersion`), asked for with every
 * data file (`?v=`) so that a release with other data replaces the
 * browser's copies (build.py, Cache busting). The page sets it from its
 * config (i18n.js); the map's renderer, which may run in a worker without
 * the page, from its options (draw.js). */
let dataVersion = '';
export function setDataVersion(version) {
  dataVersion = version;
}

/* The URL to fetch the site's data file *path* (/geo/index.json) by. */
export const dataUrl = (path) => `${path}?v=${dataVersion}`;

/* *missing*, if given, stands for a file that does not exist (HTTP 404). */
export async function fetchJSON(path, missing) {
  const response = await fetch(dataUrl(path));
  if (response.status === 404 && missing !== undefined) return missing;
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

// Coordinates in addr/<obec>.json are integers in 1/SCALE degree.
const SCALE = 100000;
const addressFiles = new Cache(16);

/* addr/<obec>.json with its points decoded: every group (street or part of
 * the obec) gets `lon` and `lat` arrays parallel to `numbers`, NaN where the
 * address has no point, and where the obec's council obvod goes by address
 * (`council` 'address') `obvody`, the council obvod of each number. */
export function addressFile(obec) {
  return addressFiles.get(obec, async () => {
    const file = await fetchJSON(`/addr/${obec}.json`);
    let x = 0;
    let y = 0;
    const groups = [];
    for (const kind of ['streets', 'parts']) {
      for (const g of file[kind]) {
        const n = g.numbers.length;
        const lon = new Float64Array(n);
        const lat = new Float64Array(n);
        for (let i = 0; i < n; i++) {
          const dx = g.points[2 * i];
          if (dx === null) {
            lon[i] = Number.NaN;
            lat[i] = Number.NaN;
            continue;
          }
          x += dx;
          y += g.points[2 * i + 1];
          lon[i] = x / SCALE;
          lat[i] = y / SCALE;
        }
        const obvody = g.obvod ? new Array(n).fill(g.obvod) : (g.obvody ?? null);
        groups.push({ kind, name: g.name, numbers: g.numbers, lon, lat, obvody });
      }
    }
    return { council: file.council, groups };
  });
}

/* The number on the building: the orientačné číslo where there is one. */
export const shownNumber = (number) => number.slice(number.lastIndexOf('/') + 1);
