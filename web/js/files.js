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

/* Where the page's election's files are and their versions: its map
 * (km-config `map`, `mapVersion`: geo/, base/, addr/) and its data
 * (`data`, `dataVersion`: data/, i18n/), each a bundle of its own (served
 * by `ems serve` at /map/2026 and /data/2026, deployed at the addresses of
 * their deployments). A file is asked for with its bundle's version
 * (`?v=`), so that other files replace the browser's copies (build.py,
 * Cache busting). The page sets them from its config (i18n.js); the map's
 * renderer, which may run in a worker without the page, from its options
 * (draw.js). */
let source = { data: '', dataVersion: '', map: '', mapVersion: '' };
export function setDataSource(next) {
  source = next;
}

// The directories of the map's bundle; any other file is the data's.
const MAP_ROOT = /^\/(?:geo|base|addr)\//;

/* The UI strings' version (km-config `stringsVersion`), asked for with
 * the site's shared files (/i18n/): the same on every election's page, so
 * that switching keeps the browser's copies. Set by the page (i18n.js). */
let stringsVersion = '';
export function setStringsVersion(version) {
  stringsVersion = version;
}

/* The URL to fetch the app's UI strings *path* (/i18n/sk.json) by, the
 * same for every election. */
export const sharedUrl = (path) => `${path}?v=${stringsVersion}`;

/* The URL to fetch the page's election's file *path* (/geo/index.json,
 * /data/index.json) by: in its map or its data bundle. */
export const dataUrl = (path) =>
  MAP_ROOT.test(path) ? `${source.map}${path}?v=${source.mapVersion}` : `${source.data}${path}?v=${source.dataVersion}`;

async function fetchFrom(url, path, missing) {
  const response = await fetch(url);
  if (response.status === 404 && missing !== undefined) return missing;
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

/* The page's election's data file *path* (`dataUrl`); *missing*, if given,
 * stands for a file that does not exist (HTTP 404). */
export const fetchJSON = (path, missing) => fetchFrom(dataUrl(path), path, missing);

// Coordinates in addr/<obec>.json are integers in 1/SCALE degree.
const SCALE = 100000;
const addressFiles = new Cache(16);

/* A value per number of a group of *n*: *one* for all of them, else *each*
 * as the file lists them; null where it gives neither. */
const perNumber = (n, one, each) => (one ? new Array(n).fill(one) : (each ?? null));

/* addr/<obec>.json with its points decoded: every group (street or part of
 * the obec) gets `lon` and `lat` arrays parallel to `numbers`, NaN where the
 * address has no point, where the obec's council obvod goes by address
 * (`council` 'address') `obvody`, the council obvod of each number, and
 * where its okrsky are drawn (geo/index.json `okrsky.drawn`) `okrsky`, the
 * okrsok of each; null where the file gives none. */
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
        const obvody = perNumber(n, g.obvod, g.obvody);
        const okrsky = perNumber(n, g.okrsok, g.okrsky);
        groups.push({ kind, name: g.name, numbers: g.numbers, lon, lat, obvody, okrsky });
      }
    }
    return { council: file.council, groups };
  });
}

/* The number on the building: the orientačné číslo where there is one. */
export const shownNumber = (number) => number.slice(number.lastIndexOf('/') + 1);
