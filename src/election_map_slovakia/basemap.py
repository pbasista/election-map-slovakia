"""Turn OpenStreetMap into the faded base map under the election colours.

The map draws only our own files (no tiles from other servers), so the
base map is built here: the main roads by class, the railways, the rivers
and larger streams, the lakes and reservoirs, from Geofabrik's extract of
Slovakia (OpenStreetMap, © its contributors, ODbL 1.0; the files written
here are a derived database under the same licence, see NOTICE). It is for
orientation only: the app strokes and fills it faintly, above the area
fills and below every border and label (web/js/draw.js).

ZBGIS, the source of the boundaries, has no open download of its roads and
waters (only on order, or as rasters), and Natural Earth has nothing finer
than motorways; OpenStreetMap is complete down to every street, and the
pinned yearly extract makes the input the same everywhere.

Left out on purpose: forests and built-up areas. Forests cover two fifths of
Slovakia and built-up areas most of every town; a tint over that much of the
map would shift the steps of the results' colour scales, which differ by a
sixth of a tone, while lines leave the colour of an area as it is. Lone
houses, paths, tracks and service roads would be clutter at every zoom.

Each level of detail of the obce shards (:data:`geo.SHARD_LODS`) gets a base
file per okres, clipped to the okres, so the files of two okresy meet at
their border without overlapping (ZBGIS level 1 is enough for that: where
the cut runs does not show); the coarse view, below the shards, gets one
file for the country, clipped to Slovakia. The waters reach :data:`REACH`
beyond Slovakia's border, which the border rivers follow:

======  ==========================================  ========  ========  =======
lod     content                                     simplify  decimals  water
======  ==========================================  ========  ========  =======
coarse  motorways, expressways (trunk), rivers of   100 m     4         ≥ 1 km²
        a course of 50 km or more
2       + primary and secondary roads, railways,    20 m      4         ≥ 10 ha
        every river, canals
1       + tertiary and minor roads (drawn from      5 m       5         ≥ 1 ha
        zoom 13), trams, ramps, streams of a
        course of 10 km or more
0       + streams of a course of 5 km or more       2 m       5         ≥ 0.2 ha
======  ==========================================  ========  ========  =======

A course is the ways of one name that touch: a stream's length is that of
its whole named course in Slovakia, not of one way of it. Minor roads are
residential, unclassified, living streets and pedestrian streets; ramps
(``*_link``) go with their road. Railway sidings, yards and spurs (any
``service``) are left out, and so are culverts. The ways of a class are
merged where they meet end to end before they are simplified, so a road is
a few long lines rather than hundreds of short ones. Water areas
(``natural=water``, ``waterway=riverbank``, ``landuse=reservoir|basin``)
are merged into one area first, so the pieces a river is mapped in show no
seams; the parts smaller than the level's least area are dropped, then the
rest is simplified.

Output, ``data/build/base/`` (JSON, compact), topologies as in :mod:`geo`
(``{scale, arcs, lines, features}``, read by web/js/topo.js), where an arc
is a line of the base map or a ring of a water area, and ``lines`` gives
its class (:data:`CLASSES`; :data:`WATER` for a ring, which is filled, not
stroked); each water area is a feature ``{properties: {}, arcs:
[[ring, …]]}``, a ring one arc::

    okres/<okres>/<lod>.json  the base map of an okres at a shard level
    coarse.json               the base map of the coarse view
    index.json                {bands: [{lod, zoom: [from, until | null]}],
                               the shards' bands; okresy: [okres, …];
                               files: {path: bytes}}
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import osmium
import pyproj
import shapely
from osmium.filter import KeyFilter
from osmium.osm import Area, TagList, Way
from osmium.version import libosmium_version, pyosmium_release
from pyproj.enums import TransformDirection

from election_map_slovakia import geo, output, progress
from election_map_slovakia.output import format_size

INPUT = "osm-slovakia"
OUTPUT_DIR = "base"
INDEX_FILE = "index.json"
COARSE_FILE = "coarse.json"
LIBRARY = (pyosmium_release, libosmium_version)
"""What reads the extract and assembles its areas, besides our code."""

# Line classes (codes of ``lines``), in the order draw.js strokes them.
STREAM, CANAL, RIVER, MINOR, TERTIARY, SECONDARY, PRIMARY, TRUNK, MOTORWAY = range(9)
TRAM, RAIL = 9, 10
WATER = geo.FOREIGN
"""The code of a ring of a water area: as in the geo files, not stroked."""
CLASSES = {
    STREAM: "stream",
    CANAL: "canal",
    RIVER: "river",
    MINOR: "minor road",
    TERTIARY: "tertiary road",
    SECONDARY: "secondary road",
    PRIMARY: "primary road",
    TRUNK: "expressway",
    MOTORWAY: "motorway",
    TRAM: "tram",
    RAIL: "railway",
}

_ROADS = {
    "motorway": MOTORWAY,
    "trunk": TRUNK,
    "primary": PRIMARY,
    "secondary": SECONDARY,
    "tertiary": TERTIARY,
    "residential": MINOR,
    "unclassified": MINOR,
    "living_street": MINOR,
    "pedestrian": MINOR,
}
_RAILWAYS = {"rail": RAIL, "narrow_gauge": RAIL, "light_rail": RAIL, "tram": TRAM}
_WATERWAYS = {"river": RIVER, "canal": CANAL, "stream": STREAM}
_WATER_AREAS = {
    ("natural", "water"),
    ("waterway", "riverbank"),
    ("landuse", "reservoir"),
    ("landuse", "basin"),
}
_KEYS = ("highway", "railway", "waterway", "natural", "landuse")
"""The keys of the ways and areas read: of :data:`_ROADS` to :data:`_WATER_AREAS`."""
_MIN_POINTS = 2  # of a line
_LINESTRING, _POLYGON = 1, 3  # shapely type ids


@dataclass(frozen=True)
class Level:
    """What one level of detail of the base map holds; see the module doc."""

    name: str
    classes: frozenset[int]
    links: bool
    """Whether it has the ramps (``*_link``) of its roads."""
    course: Mapping[int, float]
    """Least length of the named course of a line of a class, in metres."""
    water_area: float
    """Least area of a water area, in m²."""
    tolerance: float
    """Simplification tolerance, in metres."""
    decimals: int


_MAIN = frozenset({MOTORWAY, TRUNK, PRIMARY, SECONDARY, RAIL, RIVER, CANAL})
COARSE = Level(
    "coarse", frozenset({MOTORWAY, TRUNK, RIVER}), False, {RIVER: 50e3}, 1e6, 100.0, 4
)
LEVELS = {
    2: Level("2", _MAIN, False, {}, 1e5, 20.0, 4),
    1: Level(
        "1", _MAIN | {TERTIARY, MINOR, TRAM, STREAM}, True, {STREAM: 10e3}, 1e4, 5.0, 5
    ),
    0: Level(
        "0", frozenset(CLASSES), True, {STREAM: 5e3}, 2e3, geo.DETAIL_TOLERANCE, 5
    ),
}
"""By ZBGIS level, as :data:`geo.SHARD_LODS` names its levels of detail."""


class BaseMapError(Exception):
    """The OpenStreetMap extract cannot be read or misses what the map needs."""


@dataclass
class Ways:
    """The lines and water of the extract, EPSG:5514."""

    lines: np.ndarray
    kind: np.ndarray
    """The class of each line."""
    link: np.ndarray
    """Whether each line is a ramp."""
    course: np.ndarray
    """The length of the named course of each line, in metres."""
    water: Any
    """The union of the water areas."""


def _line_class(tags: TagList) -> tuple[int | None, bool]:
    """Return the class of a way with *tags* (None: not drawn), and if a ramp."""
    if (value := tags.get("highway")) is not None:
        if tags.get("area") == "yes":
            return None, False
        return _ROADS.get(value.removesuffix("_link")), value.endswith("_link")
    if (value := tags.get("railway")) is not None:
        return (None if "service" in tags else _RAILWAYS.get(value)), False
    if (value := tags.get("waterway")) is not None:
        return (
            None if tags.get("tunnel") == "culvert" else _WATERWAYS.get(value)
        ), False
    return None, False


def _is_water(tags: TagList) -> bool:
    return any(tags.get(key) == value for key, value in _WATER_AREAS)


class _Collected:
    """What :func:`read` takes from the extract, in WGS84."""

    def __init__(self) -> None:
        self.lon: list[float] = []
        self.lat: list[float] = []
        self.counts: list[int] = []
        """The vertices of each line."""
        self.kinds: list[int] = []
        self.links: list[bool] = []
        self.names: list[str] = []
        self.rings: list[list[tuple[float, float]]] = []
        self.polygons: list[list[int]] = []
        """Per water polygon, its rings' indexes in :attr:`rings`, the shell first."""

    def area(self, o: Area) -> None:
        if not _is_water(o.tags):
            return
        for outer in o.outer_rings():
            shell = len(self.rings)
            self.rings.append([(n.lon, n.lat) for n in outer])
            self.rings += [[(n.lon, n.lat) for n in r] for r in o.inner_rings(outer)]
            self.polygons.append(list(range(shell, len(self.rings))))

    def way(self, o: Way) -> None:
        kind, link = _line_class(o.tags)
        if kind is None:
            return
        try:
            points = [(n.lon, n.lat) for n in o.nodes]
        except osmium.InvalidLocationError:
            return  # a node outside the extract
        if len(points) < _MIN_POINTS:
            return
        for x, y in points:
            self.lon.append(x)
            self.lat.append(y)
        self.counts.append(len(points))
        self.kinds.append(kind)
        self.links.append(link)
        self.names.append(o.tags.get("name") or "")


def read(path: Path, to_wgs84: pyproj.Transformer) -> Ways:
    """Return the lines and water of the OSM extract *path*, in EPSG:5514."""
    got = _Collected()
    with progress.stage(f"reading {path.name}") as s:
        processor = (
            osmium.FileProcessor(path)
            .with_locations()
            .with_areas()
            .with_filter(KeyFilter(*_KEYS))
        )
        try:
            for o in processor:
                s.advance()
                if isinstance(o, Area):
                    got.area(o)
                elif isinstance(o, Way):
                    got.way(o)
        except RuntimeError as e:
            raise BaseMapError(f"{path}: {e}") from e
    if not got.counts or not got.polygons:
        raise BaseMapError(f"{path}: no roads, waterways or water areas")
    with progress.stage("reprojecting the lines to S-JTSK"):
        xy = _to_metres(to_wgs84, np.array(got.lon), np.array(got.lat))
        lines = shapely.linestrings(
            xy, indices=np.repeat(np.arange(len(got.counts)), got.counts)
        )
        kind = np.array(got.kinds, dtype=np.uint8)
        course = _course_lengths(lines, kind, np.array(got.names, dtype=object))
    with progress.stage(f"merging {len(got.polygons):,} water areas"):
        flat = np.array([p for r in got.rings for p in r])
        metres = np.split(
            _to_metres(to_wgs84, flat[:, 0], flat[:, 1]),
            np.cumsum([len(r) for r in got.rings])[:-1],
        )
        polygons = [
            shapely.Polygon(metres[p[0]], [metres[i] for i in p[1:]])
            for p in got.polygons
        ]
        water = shapely.union_all(shapely.make_valid(np.array(polygons)))
    return Ways(lines, kind, np.array(got.links), course, geo._polygonal(water))


def _to_metres(
    to_wgs84: pyproj.Transformer, lon: np.ndarray, lat: np.ndarray
) -> np.ndarray:
    """Return WGS84 *lon*, *lat* in EPSG:5514, as an n × 2 array."""
    x, y = to_wgs84.transform(lon, lat, direction=TransformDirection.INVERSE)
    return np.column_stack([x, y])


_COURSES = (RIVER, CANAL, STREAM)
"""The classes whose lines :func:`_course_lengths` joins by name."""


def _course_lengths(
    lines: np.ndarray, kind: np.ndarray, names: np.ndarray
) -> np.ndarray:
    """Return the length of the named course of each of *lines*, in metres.

    A course is the waterways of one class and name that touch; any other
    line is a course of its own.
    """
    length = shapely.length(lines)
    named = np.flatnonzero(np.isin(kind, _COURSES) & (names != ""))
    a, b = shapely.STRtree(lines[named]).query(lines[named], predicate="intersects")
    a, b = named[a], named[b]
    same = (a < b) & (names[a] == names[b]) & (kind[a] == kind[b])
    parent = {int(i): int(i) for i in named}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in zip(a[same].tolist(), b[same].tolist(), strict=True):
        parent[root(i)] = root(j)
    roots = np.arange(len(lines))
    roots[named] = [root(int(i)) for i in named]
    return np.bincount(roots, weights=length, minlength=len(lines))[roots]


def _level(ways: Ways, level: Level) -> tuple[dict[int, np.ndarray], np.ndarray]:
    """Return the lines of *level* by class and its water areas, simplified."""
    keep = np.isin(ways.kind, sorted(level.classes))
    if not level.links:
        keep &= ~ways.link
    for kind, least in level.course.items():
        keep &= (ways.kind != kind) | (ways.course >= least)
    lines = {}
    for kind in sorted(level.classes):
        chosen = ways.lines[keep & (ways.kind == kind)]
        if len(chosen):
            merged = shapely.line_merge(shapely.multilinestrings(chosen))
            lines[kind] = shapely.simplify(shapely.get_parts(merged), level.tolerance)
    water = shapely.get_parts(ways.water)
    water = shapely.simplify(
        water[shapely.area(water) >= level.water_area], level.tolerance
    )
    water = shapely.get_parts(geo._polygonal(shapely.make_valid(water)))
    return lines, water


REACH = 1000.0
"""How far beyond Slovakia's border its waters are drawn, in metres: the
Danube, the Morava, the Ipeľ and the other border rivers run along the
border, which would cut their lines into dashes and their areas in half."""


@dataclass(frozen=True)
class _Area:
    """Where the files of an okres (or the country) draw, EPSG:5514."""

    land: Any
    """The okres: the lines but the waters end at its border."""
    waters: Any
    """The okres and its part of the strip :data:`REACH` around Slovakia."""


def areas(okresy: Mapping[str, Any]) -> tuple[dict[str, _Area], _Area]:
    """Return the :class:`_Area` of each of *okresy* and of Slovakia.

    The strip around Slovakia goes to the okresy within :data:`REACH` of
    it, each piece to one only, so that no water is drawn twice.
    """
    slovakia = shapely.coverage_union_all(list(okresy.values()))
    strip = shapely.difference(shapely.buffer(slovakia, REACH), slovakia)
    taken = shapely.Polygon()
    out = {}
    for code, okres in sorted(okresy.items()):
        piece = shapely.difference(
            shapely.intersection(strip, shapely.buffer(okres, REACH)), taken
        )
        taken = shapely.union(taken, piece)
        out[code] = _Area(okres, shapely.union(okres, piece))
    return out, _Area(slovakia, shapely.union(slovakia, strip))


class _Layer:
    """Geometries of one shapely type, indexed to clip them fast."""

    def __init__(self, geometries: np.ndarray, type_id: int) -> None:
        self.geometries = geometries
        self.type_id = type_id
        self.tree = shapely.STRtree(geometries)

    def within(self, area: Any) -> np.ndarray:
        """Return the parts of the geometries inside *area*, clipped to it."""
        hits = self.geometries[np.sort(self.tree.query(area))]
        shapely.prepare(area)
        inside = shapely.contains_properly(area, hits)
        cut = shapely.get_parts(shapely.intersection(hits[~inside], area))
        cut = cut[(shapely.get_type_id(cut) == self.type_id) & ~shapely.is_empty(cut)]
        return np.concatenate([hits[inside], cut])


def _delta(xy: np.ndarray) -> list[int]:
    return np.concatenate([xy[:1], np.diff(xy, axis=0)]).ravel().tolist()


def base_file(
    lines: Mapping[int, np.ndarray],
    water: np.ndarray,
    to_wgs84: pyproj.Transformer,
    scale: int,
) -> dict[str, Any]:
    """Return the topology of *lines* by class and *water* (EPSG:5514)."""
    arcs: list[list[int]] = []
    codes: list[int] = []
    for kind, geometries in sorted(lines.items()):
        if not len(geometries):
            continue
        for g in geo.to_grid(geometries, to_wgs84, scale):
            xy = shapely.get_coordinates(g).astype(np.int64)
            xy = xy[np.r_[True, np.any(xy[1:] != xy[:-1], axis=1)]]
            if len(xy) >= _MIN_POINTS:
                arcs.append(_delta(xy))
                codes.append(kind)
    features = []
    for g in geo.to_grid(water, to_wgs84, scale) if len(water) else ():
        for polygon in geo.rings(g):
            features.append(
                {
                    "properties": {},
                    "arcs": [[[len(arcs) + i] for i in range(len(polygon))]],
                }
            )
            arcs += [_delta(ring) for ring in polygon]
            codes += [WATER] * len(polygon)
    return {"scale": scale, "arcs": arcs, "lines": codes, "features": features}


def _level_file(
    lines: Mapping[int, _Layer],
    water: _Layer,
    area: _Area,
    level: Level,
    to_wgs84: pyproj.Transformer,
) -> dict[str, Any]:
    clipped = {
        kind: layer.within(area.waters if kind in _COURSES else area.land)
        for kind, layer in lines.items()
    }
    return base_file(clipped, water.within(area.waters), to_wgs84, 10**level.decimals)


def build(path: Path, okres_gpkg: Path) -> dict[str, dict[str, Any]]:
    """Return the files of the base map: path below ``base/`` → content.

    *path* is the OSM extract, *okres_gpkg* the ZBGIS GeoPackage whose okresy
    the files are clipped to.
    """
    if set(LEVELS) != {lod.level for lod in geo.SHARD_LODS}:
        raise BaseMapError("LEVELS must name the levels of detail of geo.SHARD_LODS")
    to_wgs84 = geo.transformer()
    okresy = {
        code: g
        for code, (_, g) in geo.read_layer(okres_gpkg, "okres", "IDN3", "NM3").items()
    }
    ways = read(path, to_wgs84)
    with progress.stage("the strip around Slovakia"):
        by_okres, slovakia = areas(okresy)
    files = {}
    for level in (COARSE, *(LEVELS[lod.level] for lod in geo.SHARD_LODS)):
        with progress.stage(f"level of detail {level.name}") as s:
            kinds, water = _level(ways, level)
            lines = {kind: _Layer(g, _LINESTRING) for kind, g in kinds.items()}
            waters = _Layer(water, _POLYGON)
            if level is COARSE:
                files[COARSE_FILE] = _level_file(
                    lines, waters, slovakia, level, to_wgs84
                )
                continue
            for code in s.track(sorted(by_okres)):
                files[okres_path(code, level.name)] = _level_file(
                    lines, waters, by_okres[code], level, to_wgs84
                )
    files[INDEX_FILE] = {
        "bands": [
            {"lod": str(lod.level), "zoom": [lod.from_zoom, lod.until_zoom]}
            for lod in geo.SHARD_LODS
        ],
        "okresy": sorted(okresy),
    }
    return files


def okres_path(okres: str, lod: str) -> str:
    """Return the path below ``base/`` of the base map of *okres* at *lod*."""
    return f"okres/{okres}/{lod}.json"


def write(
    files: Mapping[str, Mapping[str, Any]], directory: Path
) -> dict[str, tuple[int, int]]:
    """Replace *directory* with *files*; return path → (bytes, gzip bytes).

    ``index.json`` is written last and lists the sizes of all other files.
    """
    blobs = {
        path: output.to_json(content)
        for path, content in sorted(files.items())
        if path != INDEX_FILE
    }
    index = dict(files[INDEX_FILE]) | {"files": {p: len(b) for p, b in blobs.items()}}
    blobs[INDEX_FILE] = output.to_json(index)
    with (
        progress.stage(f"writing {directory.name}/", len(blobs)) as s,
        output.replacing(directory) as tmp,
    ):
        for path, data in s.track(blobs.items()):
            (tmp / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp / path).write_bytes(data)
    gz = output.gzip_sizes(list(blobs.values()))
    return {p: (len(b), g) for (p, b), g in zip(blobs.items(), gz, strict=True)}


def requested(index: Mapping[str, Any]) -> list[str]:
    """Return the paths below ``base/`` the app may request by *index*."""
    return [
        COARSE_FILE,
        *(okres_path(o, b["lod"]) for o in index["okresy"] for b in index["bands"]),
    ]


def verify(path: str, content: Mapping[str, Any]) -> list[str]:
    """Return the problems of the base map file *path* (below ``base/``).

    Every arc has a line code of its level of detail, or is a ring of
    exactly one water area (:data:`WATER`), and at least two vertices.
    """
    if path == COARSE_FILE:
        level = COARSE
    else:
        level = LEVELS[int(path.rsplit("/", 1)[1].removesuffix(".json"))]
    lines, arcs = content["lines"], content["arcs"]
    if len(lines) != len(arcs):
        return [f"{len(arcs)} arcs but {len(lines)} line codes"]
    problems = [
        f"line code {c} not drawn at level {level.name}"
        for c in sorted(set(lines) - level.classes - {WATER})
    ]
    rings = sorted(
        r for f in content["features"] for p in f["arcs"] for ring in p for r in ring
    )
    if rings != [i for i, c in enumerate(lines) if c == WATER]:
        problems.append("the rings of the water areas are not the arcs coded WATER")
    short = sum(len(a) < 2 * _MIN_POINTS or len(a) % 2 for a in arcs)
    if short:
        problems.append(f"{short} arcs of fewer than {_MIN_POINTS} vertices")
    return problems


def report(
    files: Mapping[str, Mapping[str, Any]], sizes: Mapping[str, tuple[int, int]]
) -> Iterator[str]:
    """Yield per level of detail its lines per class, water areas and sizes."""
    groups: dict[str, list[str]] = {}
    for path in files:
        if path != INDEX_FILE:
            name = "coarse" if path == COARSE_FILE else path.rsplit("/", 1)[1][:-5]
            groups.setdefault(name, []).append(path)
    yield (
        f"{'lod':<7} {'files':>5} {'vertices':>10} {'water':>7}"
        f" {'bytes':>10} {'gzip':>10} {'max gzip':>10}  lines per class"
    )
    for name in ("coarse", *(str(lod.level) for lod in geo.SHARD_LODS)):
        paths = groups.get(name, [])
        counts: Counter[int] = Counter()
        vertices = water = 0
        for path in paths:
            counts.update(files[path]["lines"])
            vertices += sum(len(a) for a in files[path]["arcs"]) // 2
            water += len(files[path]["features"])
        per_class = ", ".join(
            f"{CLASSES[k]} {n:,}" for k, n in sorted(counts.items()) if k in CLASSES
        )
        yield (
            f"{name:<7} {len(paths):>5} {vertices:>10,} {water:>7,}"
            f" {format_size(sum(sizes[p][0] for p in paths)):>10}"
            f" {format_size(sum(sizes[p][1] for p in paths)):>10}"
            f" {format_size(max(sizes[p][1] for p in paths)):>10}  {per_class}"
        )
