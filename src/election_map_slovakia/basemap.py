"""Turn OpenStreetMap into the faded base map under the election colours.

The map draws only our own files (no tiles from other servers), so the
base map is built here: the main roads by class, the railways, the rivers
and larger streams, the lakes and reservoirs, and the buildings, from
Geofabrik's extract of Slovakia (OpenStreetMap, © its contributors, ODbL
1.0; the files written here are a derived database under the same licence,
see NOTICE). It is for orientation only: the app strokes and fills it
faintly, above the area fills and below every border and label
(web/js/draw.js).

ZBGIS, the source of the boundaries, has no open download of its roads and
waters (only on order, or as rasters), and Natural Earth has nothing finer
than motorways; OpenStreetMap is complete down to every street, and the
pinned yearly extract makes the input the same everywhere.

Left out on purpose: forests and built-up areas. Forests cover two fifths of
Slovakia and built-up areas most of every town; a tint over that much of the
map would shift the steps of the results' colour scales, which differ by a
sixth of a tone, while lines leave the colour of an area as it is. Paths,
tracks and service roads would be clutter at every zoom. The buildings are
small enough to leave the areas' colour readable around them, and are drawn
only from :data:`BUILDINGS_ZOOM`, where a street is wide enough to tell
them apart.

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

The buildings (``building=*``: closed ways and multipolygon relations, not
``building:part``) are not clipped but go whole to the obec (ZBGIS level 0)
that holds the mean of their outer ring's vertices, or else to the nearest
obec within :data:`BUILDINGS_REACH`; the rest lie abroad, which the extract
spills into. They are not simplified, only rounded to the grid of
:data:`BUILDINGS_SCALE` (about a metre): simplifying by a metre more would
drop a tenth of the vertices but cut the corners of the small houses. A
ring left with fewer than three vertices, or no area, is dropped (a
building with its outer ring). The buildings of a file follow a Hilbert
curve, so the steps between them stay short.

Output, ``data/build/base/`` (JSON, compact), topologies as in :mod:`geo`
(``{scale, arcs, lines, features}``, read by web/js/topo.js), where an arc
is a line of the base map or a ring of a water area, and ``lines`` gives
its class (:data:`CLASSES`; :data:`WATER` for a ring, which is filled, not
stroked); each water area is a feature ``{properties: {}, arcs:
[[ring, …]]}``, a ring one arc::

    okres/<okres>/<lod>.json  the base map of an okres at a shard level
    coarse.json               the base map of the coarse view
    obec/<obec>.json          the buildings of an obec, {scale, counts, xy}
    index.json                {bands: [{lod, zoom: [from, until | null]}],
                               the shards' bands; okresy: [okres, …];
                               buildings: {zoom, obce: [obec, …]};
                               files: {path: bytes}}

In a buildings file ``counts`` holds the number of vertices of each ring
and ``xy`` the vertices of all rings in turn, open (the first not repeated
at the end), as grid steps ``round(lon × scale)``, ``round(lat × scale)``
from the vertex before, the first from 0. A building is its outer ring,
counter-clockwise, then its holes, clockwise, so that the nonzero rule
fills it.
"""

from __future__ import annotations

import itertools
import os
from collections import Counter
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import osmium
import osmium.area
import osmium.geom
import osmium.index
import osmium.io
import pyproj
import shapely
from osmium.filter import EntityFilter, KeyFilter, TagFilter
from osmium.osm import (
    NODE,
    RELATION,
    WAY,
    Area,
    Relation,
    TagList,
    Way,
    osm_entity_bits,
)
from osmium.version import libosmium_version, pyosmium_release
from pyproj.enums import TransformDirection

from election_map_slovakia import geo, output, parallel, progress
from election_map_slovakia.output import format_size

INPUT = "osm-slovakia"
OUTPUT_DIR = "base"
INDEX_FILE = "index.json"
COARSE_FILE = "coarse.json"
LIBRARY = (pyosmium_release, libosmium_version)
"""What reads the extract and assembles its areas, besides our code."""
BUILDINGS_DIR = "obec"
BUILDINGS_SCALE = 100_000
"""Grid of the buildings files, per degree: about a metre."""
BUILDINGS_ZOOM = 16
"""The zoom from which the app draws the buildings."""
BUILDINGS_REACH = 50.0
"""How far from an obec a building outside every obec may lie to go to it,
in metres: ZBGIS and OpenStreetMap draw the border apart by that much."""

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
_LINE_TAGS = (
    *(("highway", v) for road in _ROADS for v in (road, f"{road}_link")),
    *(("railway", v) for v in _RAILWAYS),
    *(("waterway", v) for v in _WATERWAYS),
)
"""The tags of the ways :func:`_line_class` may draw."""
_MIN_POINTS = 2  # of a line
_MIN_RING = 3  # distinct vertices of a building's ring
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


def _pack(geometries: np.ndarray) -> Any:
    """Return *geometries*, all of one type, as a few flat arrays to pickle.

    Shapely pickles each geometry on its own, which takes over a second for
    the lines of the extract; they go to the worker processes.
    """
    return shapely.to_ragged_array(geometries) if len(geometries) else None


def _unpack(packed: Any) -> np.ndarray:
    """Return the geometries :func:`_pack` packed."""
    if packed is None:
        return np.array([], dtype=object)
    return shapely.from_ragged_array(*packed)


@dataclass
class Ways:
    """The lines of the extract, EPSG:5514."""

    lines: np.ndarray
    kind: np.ndarray
    """The class of each line."""
    link: np.ndarray
    """Whether each line is a ramp."""
    course: np.ndarray
    """The length of the named course of each line, in metres."""

    def __getstate__(self) -> dict[str, Any]:
        """Return the state to pickle, :attr:`lines` packed (:func:`_pack`)."""
        return vars(self) | {"lines": _pack(self.lines)}

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore the state :meth:`__getstate__` returned."""
        vars(self).update(state, lines=_unpack(state["lines"]))


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


@dataclass
class _Lines:
    """What :func:`read_lines` takes from the extract, in WGS84."""

    wkb: list[str] = field(default_factory=list)
    """Each line, in hex WKB: libosmium writes it far faster than Python
    reads the locations of its nodes one by one."""
    kinds: list[int] = field(default_factory=list)
    links: list[bool] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    factory: osmium.geom.WKBFactory = field(default_factory=osmium.geom.WKBFactory)

    def way(self, o: Way) -> None:
        kind, link = _line_class(o.tags)
        if kind is None or len(o.nodes) < _MIN_POINTS:
            return
        try:
            wkb = self.factory.create_linestring(o, use_nodes=osmium.geom.ALL)
        except osmium.InvalidLocationError:
            return  # a node outside the extract
        self.wkb.append(wkb)
        self.kinds.append(kind)
        self.links.append(link)
        self.names.append(o.tags.get("name") or "")


_WKB_HEADER = 18
"""Hex digits before the points of a line in WKB: byte order, type, count."""
_WKB_POINT = 32
"""Hex digits of a point in WKB: two little-endian doubles."""
_CHUNK = 1 << 16


@dataclass
class _Outlines:
    """What :func:`read_building_ways` takes from the extract, in WGS84.

    Their WKB (as :attr:`_Lines.wkb`) is turned into coordinates every
    :data:`_CHUNK` outlines, by NumPy rather than shapely: the strings and
    geometries of all of them would take gigabytes.
    """

    wkb: list[str] = field(default_factory=list)
    ids: list[int] = field(default_factory=list)
    lonlat: list[np.ndarray] = field(default_factory=list)
    counts: list[np.ndarray] = field(default_factory=list)
    """The number of points of each outline, closed."""
    factory: osmium.geom.WKBFactory = field(default_factory=osmium.geom.WKBFactory)

    def way(self, o: Way) -> None:
        try:
            self.wkb.append(
                self.factory.create_linestring(o, use_nodes=osmium.geom.ALL)
            )
        except osmium.InvalidLocationError:
            return  # a node outside the extract
        except RuntimeError:
            return  # a way of one node
        self.ids.append(o.id)
        if len(self.wkb) == _CHUNK:
            self.decode()

    def decode(self) -> None:
        """Turn the WKB read since the last time into coordinates."""
        self.counts.append(
            (np.array([len(w) for w in self.wkb]) - _WKB_HEADER) // _WKB_POINT
        )
        points = bytes.fromhex("".join([w[_WKB_HEADER:] for w in self.wkb]))
        self.lonlat.append(np.frombuffer(points, dtype="<f8").reshape(-1, 2))
        self.wkb.clear()

    def on_grid(self) -> tuple[Buildings, np.ndarray]:
        """Return the outlines as :class:`Buildings`, and their ids."""
        self.decode()
        counts = np.concatenate(self.counts)
        ring = np.repeat(np.arange(len(counts)), counts)
        lonlat = np.concatenate(self.lonlat)
        buildings, kept = _on_grid(lonlat, ring, np.ones(len(counts), dtype=np.int64))
        return buildings, np.array(self.ids, dtype=np.int64)[kept]


@dataclass
class _Polygons:
    """The polygons of areas :func:`read_areas` takes, in WGS84."""

    rings: list[list[tuple[float, float]]] = field(default_factory=list)
    polygons: list[list[int]] = field(default_factory=list)
    """Per polygon, its rings' indexes in :attr:`rings`, the shell first."""

    def area(self, o: Area) -> None:
        for outer in o.outer_rings():
            shell = len(self.rings)
            self.rings.append([(n.lon, n.lat) for n in outer])
            self.rings += [[(n.lon, n.lat) for n in r] for r in o.inner_rings(outer)]
            self.polygons.append(list(range(shell, len(self.rings))))

    def union(self) -> Any:
        """Return the union of the polygons, in EPSG:5514."""
        flat = np.array([p for r in self.rings for p in r])
        metres = np.split(
            _to_metres(flat[:, 0], flat[:, 1]),
            np.cumsum([len(r) for r in self.rings])[:-1],
        )
        polygons = [
            shapely.Polygon(metres[p[0]], [metres[i] for i in p[1:]])
            for p in self.polygons
        ]
        return geo.polygonal(shapely.union_all(shapely.make_valid(np.array(polygons))))

    def on_grid(self) -> Buildings:
        """Return the polygons as :class:`Buildings` (:func:`_on_grid`)."""
        lengths = [len(r) for r in self.rings]
        buildings, _ = _on_grid(
            np.array([p for r in self.rings for p in r], dtype=float).reshape(-1, 2),
            np.repeat(np.arange(len(lengths)), lengths),
            np.array([len(p) for p in self.polygons], dtype=np.int64),
        )
        return buildings


def _locations() -> osmium.NodeLocationsForWays:
    """Return a handler that stores where each node is and puts it on the ways.

    It goes after the filters of the ways (unlike ``with_locations()``), so
    that it looks up the nodes of the ways read only, not of every building.
    """
    handler = osmium.NodeLocationsForWays(osmium.index.create_map("flex_mem"))
    handler.ignore_errors()
    return handler


def _tagged(
    tags: Collection[tuple[str, str]], entities: osm_entity_bits
) -> tuple[KeyFilter, TagFilter]:
    """Return the filters that let *entities* pass with any of *tags* only.

    The key filter goes first: libosmium's is quick, its tag filter slow.
    """
    keys, exact = KeyFilter(*sorted({key for key, _ in tags})), TagFilter(*tags)
    keys.enable_for(entities)
    exact.enable_for(entities)
    return keys, exact


def read_lines(path: Path) -> Ways:
    """Return the lines of the OSM extract *path*, in EPSG:5514.

    Read apart from :func:`read_areas` and :func:`read_building_ways`, in
    other processes.
    """
    got = _Lines()
    keys, tags = _tagged(_LINE_TAGS, WAY)  # the nodes pass, to be located
    processor = (
        osmium.FileProcessor(path, NODE | WAY)
        .with_filter(keys)
        .with_filter(tags)
        .with_filter(_locations())
        .with_filter(EntityFilter(WAY))
    )
    try:
        for o in processor:
            if isinstance(o, Way):
                got.way(o)
    except RuntimeError as e:
        raise BaseMapError(f"{path}: {e}") from e
    if not got.wkb:
        raise BaseMapError(f"{path}: no roads, railways or waterways")
    wgs84 = shapely.from_wkb([bytes.fromhex(line) for line in got.wkb])
    lonlat, index = shapely.get_coordinates(wgs84, return_index=True)
    # PROJ takes seconds for the millions of points: a share per worker.
    shares = np.array_split(lonlat, os.cpu_count() or 1)
    xy = np.concatenate(
        list(parallel.each(_to_metres, ((s[:, 0], s[:, 1]) for s in shares)))
    )
    lines = shapely.linestrings(xy, indices=index)
    kind = np.array(got.kinds, dtype=np.uint8)
    course = _course_lengths(lines, kind, np.array(got.names, dtype=object))
    return Ways(lines, kind, np.array(got.links), course)


def read_building_ways(path: Path) -> tuple[Buildings, np.ndarray]:
    """Return the buildings that are closed ways of the OSM extract *path*.

    And their ids. Read apart from :func:`read_lines`, in another process,
    though both decode the whole extract and locate all its nodes: making
    the outlines one by one takes longer than reading the extract.
    """
    outlines = _Outlines()
    keys = KeyFilter("building")
    keys.enable_for(WAY)  # the nodes pass, to be located
    processor = (
        osmium.FileProcessor(path, NODE | WAY)
        .with_filter(keys)
        .with_filter(_locations())
        .with_filter(EntityFilter(WAY))
    )
    try:
        for o in processor:
            # Not len(o.nodes): making the list takes a sixth of the time.
            if isinstance(o, Way) and o.is_closed():
                outlines.way(o)
    except RuntimeError as e:
        raise BaseMapError(f"{path}: {e}") from e
    del processor  # and the locations of the nodes, a gigabyte
    return outlines.on_grid()


def read_areas(path: Path) -> tuple[Any, Buildings, np.ndarray]:
    """Return the areas of the OSM extract *path* that libosmium assembles.

    That is the union of the water areas, EPSG:5514, the buildings that are
    multipolygon relations, and the ids of these relations' outer ways, which
    may be tagged as the building too (:func:`read_building_ways` reads them).
    libosmium assembles the areas in a second pass, as ``with_areas()`` does,
    but is handed only the ways tagged as water and the members of the
    multipolygon relations tagged so or as buildings, which the first passes
    find: assembling every closed way (every building) took most of the time.
    """
    assembler = osmium.area.AreaManager()
    needed = osmium.IdTracker()
    water, buildings = _Polygons(), _Polygons()
    try:
        keys, tags = _tagged(_WATER_AREAS, WAY | RELATION)
        first = (
            osmium.FileProcessor(path, WAY | RELATION)
            .with_filter(keys)
            .with_filter(tags)
            .with_filter(assembler.first_pass_handler())
        )
        for o in first:
            if isinstance(o, Way):
                needed.add_way(o.id)
            else:
                needed.add_references(o)
        outer = _building_relations(path, assembler, needed)
        ways = needed.id_filter()
        ways.enable_for(WAY)  # all nodes pass, to be located
        areas = osmium.BufferIterator()
        with osmium.io.Reader(path, NODE | WAY) as reader:
            osmium.apply(
                reader, ways, _locations(), assembler.second_pass_to_buffer(areas)
            )
        for o in areas:
            if not isinstance(o, Area):
                continue
            if any(o.tags.get(k) == v for k, v in _WATER_AREAS):
                water.area(o)
            # A member way tagged as a building: read_building_ways has it.
            if "building" in o.tags and not o.from_way():
                buildings.area(o)
    except RuntimeError as e:
        raise BaseMapError(f"{path}: {e}") from e
    if not water.polygons:
        raise BaseMapError(f"{path}: no water areas")
    return (
        water.union(),
        buildings.on_grid(),
        np.array(sorted(outer), dtype=np.int64),
    )


def _building_relations(
    path: Path, assembler: osmium.area.AreaManager, needed: osmium.IdTracker
) -> set[int]:
    """Hand the buildings that are multipolygons of *path* to *assembler*.

    Their members go to *needed*; return the ids of their outer ways.
    """
    building = KeyFilter("building")
    building.enable_for(RELATION)
    multipolygon = TagFilter(("type", "multipolygon"))
    multipolygon.enable_for(RELATION)
    first = (
        osmium.FileProcessor(path, RELATION)
        .with_filter(building)
        .with_filter(multipolygon)
        .with_filter(assembler.first_pass_handler())
    )
    outer: set[int] = set()
    for o in first:
        if isinstance(o, Relation):
            needed.add_references(o)
            outer |= {m.ref for m in o.members if m.type == "w" and m.role == "outer"}
    return outer


def _ranges(starts: np.ndarray, lengths: np.ndarray) -> np.ndarray:
    """Return the indexes ``starts[i]`` to ``starts[i] + lengths[i] - 1``, in turn."""
    ends = np.cumsum(lengths)
    total = int(ends[-1]) if len(ends) else 0
    return np.arange(total) + np.repeat(starts - ends + lengths, lengths)


@dataclass
class Buildings:
    """Building outlines on the grid of :data:`BUILDINGS_SCALE` (lon, lat)."""

    xy: np.ndarray
    """The vertices of every ring in turn, open, as n × 2 ints."""
    counts: np.ndarray
    """The number of vertices of each ring."""
    rings: np.ndarray
    """The number of rings of each building, its outer ring first."""

    def take(self, indexes: np.ndarray) -> Buildings:
        """Return the buildings at *indexes*, in that order."""
        ring = _ranges(
            (np.cumsum(self.rings) - self.rings)[indexes], self.rings[indexes]
        )
        vertex = _ranges(
            (np.cumsum(self.counts) - self.counts)[ring], self.counts[ring]
        )
        return Buildings(self.xy[vertex], self.counts[ring], self.rings[indexes])

    def points(self) -> np.ndarray:
        """Return the mean of the vertices of each building's outer ring."""
        outer = np.zeros(len(self.counts), dtype=bool)
        outer[np.cumsum(self.rings) - self.rings] = True
        n = self.counts[outer]
        xy = self.xy[np.repeat(outer, self.counts)]
        building = np.repeat(np.arange(len(n)), n)
        return np.column_stack(
            [
                np.bincount(building, weights=xy[:, k], minlength=len(n)) / n
                for k in (0, 1)
            ]
        )


def _concat(parts: Sequence[Buildings]) -> Buildings:
    """Return the buildings of all *parts*, in turn."""
    return Buildings(
        np.concatenate([p.xy for p in parts]),
        np.concatenate([p.counts for p in parts]),
        np.concatenate([p.rings for p in parts]),
    )


def _on_grid(
    lonlat: np.ndarray, ring: np.ndarray, rings: np.ndarray
) -> tuple[Buildings, np.ndarray]:
    """Return closed rings as :class:`Buildings`, and which buildings are kept.

    *lonlat* are the vertices of the rings in turn, each ring closed (its
    first vertex repeated last), *ring* the ring of each vertex, from 0, and
    *rings* the number of rings of each building, its outer ring first. On
    the grid the closing vertex and each vertex that repeats the one before
    are dropped, then the rings with fewer than three vertices or no area
    (a building with its outer ring), and the rest are turned so that outer
    rings run counter-clockwise and holes clockwise.
    """
    xy = np.round(lonlat * BUILDINGS_SCALE).astype(np.int64)
    closing = np.r_[ring[1:] != ring[:-1], True]
    xy, ring = xy[~closing], ring[~closing]
    starts = np.r_[True, ring[1:] != ring[:-1]]
    keep = starts | np.r_[True, np.any(xy[1:] != xy[:-1], axis=1)]
    xy, ring = xy[keep], ring[keep]
    # The last vertex of a ring may now repeat its first.
    count = np.bincount(ring, minlength=int(rings.sum()))
    first = np.cumsum(count) - count
    last = first + count - 1
    again = (count > 1) & np.all(xy[last] == xy[first], axis=1)
    keep = np.ones(len(xy), dtype=bool)
    keep[last[again]] = False
    xy, ring = xy[keep], ring[keep]
    count[again] -= 1
    first = np.cumsum(count) - count
    area = _areas(xy, count)
    building = np.repeat(np.arange(len(rings)), rings)
    outer = np.zeros(len(count), dtype=bool)
    outer[np.cumsum(rings) - rings] = True
    valid = (count >= _MIN_RING) & (area != 0)
    kept = valid[outer]
    valid &= kept[building]
    turn = np.where(outer, area < 0, area > 0)[ring]
    position = np.arange(len(xy))
    source = np.where(turn, 2 * first[ring] + count[ring] - 1 - position, position)
    return Buildings(
        xy[source][valid[ring]],
        count[valid],
        np.bincount(building[valid], minlength=len(rings))[kept],
    ), kept


_CURVE_BITS = 16
"""Bits per axis of the Hilbert curve the buildings follow: across Slovakia
a cell of under ten metres, close enough for short steps between them."""


def _hilbert(x: np.ndarray, y: np.ndarray, bits: int) -> np.ndarray:
    """Return the distance along a Hilbert curve of each point (*x*, *y*).

    The coordinates are ints from 0 to ``2**bits - 1``.
    """
    side = 1 << bits
    d = np.zeros(len(x), dtype=np.int64)
    s = side >> 1
    while s:
        rx, ry = (x & s) > 0, (y & s) > 0
        d += s * s * ((3 * rx) ^ ry)
        flip = rx & ~ry
        x, y = np.where(flip, side - 1 - x, x), np.where(flip, side - 1 - y, y)
        x, y = np.where(ry, x, y), np.where(ry, y, x)
        s >>= 1
    return d


def _owners(points: np.ndarray, obce: np.ndarray) -> np.ndarray:
    """Return the index in *obce* of the obec of each of *points* (-1: none).

    That which holds the point, else the nearest within
    :data:`BUILDINGS_REACH`. *points* are on the grid of the buildings
    (:meth:`Buildings.points`), *obce* in EPSG:5514.
    """
    owner = np.full(len(points), -1)
    lonlat = points / BUILDINGS_SCALE
    geometries = shapely.points(_to_metres(lonlat[:, 0], lonlat[:, 1]))
    # The tree of the points, so that each obec is prepared once.
    o, p = shapely.STRtree(geometries).query(obce, predicate="contains")
    owner[p] = o
    outside = np.flatnonzero(owner < 0)
    p, o = shapely.STRtree(obce).query_nearest(
        geometries[outside], max_distance=BUILDINGS_REACH
    )
    p, first = np.unique(p, return_index=True)  # one of obce equally near
    owner[outside[p]] = o[first]
    return owner


def _buildings(
    multipolygons: Buildings, outer: np.ndarray, ways: Buildings, ids: np.ndarray
) -> Buildings:
    """Return the buildings of :func:`read_areas` and :func:`read_building_ways`.

    *multipolygons* and the ids of their *outer* ways come from the former,
    the *ways* and their *ids* from the latter, which may repeat the former.
    """
    return _concat([multipolygons, ways.take(np.flatnonzero(~np.isin(ids, outer)))])


def building_files(
    buildings: Buildings, points: np.ndarray, owner: np.ndarray, codes: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Return the buildings file of each obec: path below ``base/`` → content.

    *points* are :meth:`Buildings.points`, and *owner* the index in *codes*
    of the obec of each building (-1: none).
    """
    if not len(buildings.rings):
        return {}
    low = points.min(axis=0)
    span = max(float(np.max(points - low)), 1.0)
    grid = ((points - low) * (((1 << _CURVE_BITS) - 1) / span)).astype(np.int64)
    curve = _hilbert(grid[:, 0], grid[:, 1], _CURVE_BITS)
    order = np.lexsort((curve, owner))
    order = order[owner[order] >= 0]
    ordered = buildings.take(order)
    # Where the rings and vertices of each obec end, after those before.
    obec, per_obec = np.unique(owner[order], return_counts=True)
    ring_ends = np.cumsum(ordered.rings)[np.cumsum(per_obec) - 1]
    vertex_ends = np.cumsum(ordered.counts)[ring_ends - 1]
    ring_starts = np.r_[0, ring_ends[:-1]]
    vertex_starts = np.r_[0, vertex_ends[:-1]]
    xy = ordered.xy
    steps = np.diff(xy, axis=0, prepend=xy[:1])
    steps[vertex_starts] = xy[vertex_starts]
    files = {}
    for i, r0, r1, v0, v1 in zip(
        obec.tolist(),
        ring_starts.tolist(),
        ring_ends.tolist(),
        vertex_starts.tolist(),
        vertex_ends.tolist(),
        strict=True,
    ):
        files[buildings_path(codes[i])] = {
            "scale": BUILDINGS_SCALE,
            "counts": ordered.counts[r0:r1].tolist(),
            "xy": steps[v0:v1].ravel().tolist(),
        }
    return files


def _to_metres(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Return WGS84 *lon*, *lat* in EPSG:5514, as an n × 2 array."""
    x, y = geo.transformer().transform(lon, lat, direction=TransformDirection.INVERSE)
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


@dataclass
class _Drawn:
    """Lines by class and water areas of a level of detail, EPSG:5514."""

    lines: dict[int, np.ndarray]
    water: np.ndarray

    def __getstate__(self) -> tuple[dict[int, Any], Any]:
        """Return the state to pickle, the geometries packed (:func:`_pack`)."""
        return {k: _pack(g) for k, g in self.lines.items()}, _pack(self.water)

    def __setstate__(self, state: tuple[dict[int, Any], Any]) -> None:
        """Restore the state :meth:`__getstate__` returned."""
        lines, water = state
        self.lines = {k: _unpack(g) for k, g in lines.items()}
        self.water = _unpack(water)


def _pieces(ways: Ways, water: Any, level: Level) -> list[_Drawn]:
    """Return what *level* draws of *ways* and *water*, not yet simplified.

    In pieces to simplify apart (:func:`_simplify`): the lines of each class,
    then the water areas.
    """
    keep = np.isin(ways.kind, sorted(level.classes))
    if not level.links:
        keep &= ~ways.link
    for kind, least in level.course.items():
        keep &= (ways.kind != kind) | (ways.course >= least)
    none = np.array([], dtype=object)
    pieces = []
    for kind in sorted(level.classes):
        chosen = ways.lines[keep & (ways.kind == kind)]
        if len(chosen):
            pieces.append(_Drawn({kind: chosen}, none))
    parts = shapely.get_parts(water)
    return [*pieces, _Drawn({}, parts[shapely.area(parts) >= level.water_area])]


def _simplify(drawn: _Drawn, level: Level) -> _Drawn:
    """Return *drawn* simplified for *level*, each class's lines merged first."""
    lines = {}
    for kind, chosen in drawn.lines.items():
        merged = shapely.line_merge(shapely.multilinestrings(chosen))
        lines[kind] = shapely.simplify(shapely.get_parts(merged), level.tolerance)
    water = shapely.simplify(drawn.water, level.tolerance)
    water = shapely.get_parts(geo.polygonal(shapely.make_valid(water)))
    return _Drawn(lines, water)


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
        grid = geo.to_grid(geometries, to_wgs84, scale)
        xy, line = shapely.get_coordinates(grid, return_index=True)
        xy = xy.astype(np.int64)
        # All lines at once: drop each vertex that repeats the one before on
        # its line, then give each line's first vertex and the steps after it.
        first = np.r_[True, line[1:] != line[:-1]]
        keep = first | np.r_[True, np.any(xy[1:] != xy[:-1], axis=1)]
        xy, first = xy[keep], first[keep]
        steps = np.diff(xy, axis=0, prepend=xy[:1])
        steps[first] = xy[first]
        flat = steps.ravel().tolist()
        bounds = 2 * np.r_[np.flatnonzero(first), len(xy)]
        for start, end in itertools.pairwise(bounds.tolist()):
            if end - start >= 2 * _MIN_POINTS:
                arcs.append(flat[start:end])
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


def _joined(pieces: Sequence[_Drawn]) -> _Drawn:
    """Return the *pieces* of a level of detail (:func:`_pieces`) as one."""
    lines = {kind: g for piece in pieces for kind, g in piece.lines.items()}
    return _Drawn(lines, np.concatenate([piece.water for piece in pieces]))


def _level_files(
    drawn: _Drawn, where: Sequence[_Area], level: Level
) -> list[dict[str, Any]]:
    """Return the file of *level* for each of *where*: *drawn* clipped to it."""
    to_wgs84 = geo.transformer()
    lines = {kind: _Layer(g, _LINESTRING) for kind, g in drawn.lines.items()}
    water = _Layer(drawn.water, _POLYGON)
    files = []
    for area in where:
        clipped = {
            kind: layer.within(area.waters if kind in _COURSES else area.land)
            for kind, layer in lines.items()
        }
        files.append(
            base_file(clipped, water.within(area.waters), to_wgs84, 10**level.decimals)
        )
    return files


def build(path: Path, okres_gpkg: Path, obec_gpkg: Path) -> dict[str, dict[str, Any]]:
    """Return the files of the base map: path below ``base/`` → content.

    *path* is the OSM extract, *okres_gpkg* the ZBGIS GeoPackage whose okresy
    the files are clipped to, *obec_gpkg* that whose obce get the buildings
    (level 0, the shards' obce). Worker processes read the lines, the water
    and the buildings side by side, then simplify each level's lines of a
    class and its water apart, then clip each level to a share of the okresy.
    """
    if set(LEVELS) != {lod.level for lod in geo.SHARD_LODS}:
        raise BaseMapError("LEVELS must name the levels of detail of geo.SHARD_LODS")
    okresy = {
        code: g
        for code, (_, g) in geo.read_layer(okres_gpkg, "okres", "IDN3", "NM3").items()
    }
    obce = geo.read_layer(obec_gpkg, "obec", "IDN4", "NM4")
    with progress.stage(f"reading {path.name}, the strip around Slovakia"):
        # The longest tasks first.
        (outlines, ids), (water, multipolygons, outer), ways, (by_okres, slovakia) = (
            parallel.each(
                parallel.call,
                [
                    (read_building_ways, path),
                    (read_areas, path),
                    (read_lines, path),
                    (areas, okresy),
                ],
            )
        )
    with progress.stage("placing the buildings in the obce"):
        buildings = _buildings(multipolygons, outer, outlines, ids)
        if not len(buildings.rings):
            raise BaseMapError(f"{path}: no buildings")
        points = buildings.points()
        obec_codes = sorted(obce)
        polygons = np.array([obce[c][1] for c in obec_codes])
        # PROJ and the tests of the points take seconds: a share per worker.
        shares = np.array_split(points, os.cpu_count() or 1)
        owner = np.concatenate(
            list(parallel.each(_owners, ((s, polygons) for s in shares)))
        )
        files = building_files(buildings, points, owner, obec_codes)
    built = sorted(Path(p).stem for p in files)
    # The most detailed level first, so that no worker is left with a long
    # task at the end.
    levels = [*(LEVELS[lod.level] for lod in reversed(geo.SHARD_LODS)), COARSE]
    split = [_pieces(ways, water, level) for level in levels]
    tasks = [
        (p, level) for level, pieces in zip(levels, split, strict=True) for p in pieces
    ]
    with progress.stage("simplifying the levels of detail", len(tasks)) as s:
        done = s.track(parallel.each(_simplify, tasks))
        simplified = [_joined(list(itertools.islice(done, len(p)))) for p in split]
    # A task per worker and level, each a share of the okresy.
    shares = os.cpu_count() or 1
    codes = sorted(by_okres)
    paths: list[list[str]] = []
    clips: list[tuple[_Drawn, list[_Area], Level]] = []
    for level, drawn in zip(levels, simplified, strict=True):
        if level is COARSE:
            paths.append([COARSE_FILE])
            clips.append((drawn, [slovakia], level))
            continue
        for share in (codes[i::shares] for i in range(min(shares, len(codes)))):
            paths.append([okres_path(code, level.name) for code in share])
            clips.append((drawn, [by_okres[code] for code in share], level))
    with progress.stage("clipping them to the okresy", len(clips)) as s:
        for names, contents in zip(
            paths, s.track(parallel.each(_level_files, clips)), strict=True
        ):
            files.update(zip(names, contents, strict=True))
    files[INDEX_FILE] = {
        "bands": [
            {"lod": str(lod.level), "zoom": [lod.from_zoom, lod.until_zoom]}
            for lod in geo.SHARD_LODS
        ],
        "okresy": sorted(okresy),
        "buildings": {"zoom": BUILDINGS_ZOOM, "obce": built},
    }
    return files


def okres_path(okres: str, lod: str) -> str:
    """Return the path below ``base/`` of the base map of *okres* at *lod*."""
    return f"okres/{okres}/{lod}.json"


def buildings_path(obec: str) -> str:
    """Return the path below ``base/`` of the buildings of *obec*."""
    return f"{BUILDINGS_DIR}/{obec}.json"


def _is_buildings(path: str) -> bool:
    return path.startswith(f"{BUILDINGS_DIR}/")


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
        *(buildings_path(o) for o in index["buildings"]["obce"]),
    ]


def _areas(xy: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Return twice the signed area of each ring of *xy* (:class:`Buildings`).

    Taken from each ring's first vertex: exact in floats, as a building
    spans far fewer than 2**26 steps of the grid.
    """
    ring = np.repeat(np.arange(len(counts)), counts)
    first = np.cumsum(counts) - counts
    after = np.arange(len(xy)) + 1
    some = counts > 0
    after[first[some] + counts[some] - 1] = first[some]
    rel = xy - xy[first[ring]]
    cross = rel[:, 0] * rel[after, 1] - rel[after, 0] * rel[:, 1]
    return np.bincount(ring, weights=cross, minlength=len(counts))


def _decoded(content: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Return the vertices and ring lengths of the buildings file *content*."""
    steps = np.array(content["xy"], dtype=np.int64).reshape(-1, 2)
    return np.cumsum(steps, axis=0), np.array(content["counts"], dtype=np.int64)


def verify(path: str, content: Mapping[str, Any]) -> list[str]:
    """Return the problems of the base map file *path* (below ``base/``).

    Every arc has a line code of its level of detail, or is a ring of
    exactly one water area (:data:`WATER`), and at least two vertices; in
    a buildings file, see :func:`_verify_buildings`.
    """
    if _is_buildings(path):
        return _verify_buildings(content)
    level = _level_of(path)
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


def _verify_buildings(content: Mapping[str, Any]) -> list[str]:
    """Return the problems of a buildings file.

    Its scale is :data:`BUILDINGS_SCALE`, its vertices pairs, as many as the
    rings' counts add up to, each ring has at least three and an area, and
    the first, a building's outer ring, runs counter-clockwise.
    """
    if content["scale"] != BUILDINGS_SCALE:
        return [f"scale {content['scale']}, not {BUILDINGS_SCALE}"]
    counts, xy = content["counts"], content["xy"]
    if len(xy) % 2 or sum(counts) != len(xy) // 2:
        return [f"{len(xy)} coordinates for rings of {sum(counts)} vertices"]
    problems = []
    short = sum(c < _MIN_RING for c in counts)
    if short:
        problems.append(f"{short} rings of fewer than {_MIN_RING} vertices")
        return problems
    area = _areas(*_decoded(content))
    if not np.all(area):
        problems.append(f"{int(np.sum(area == 0))} rings of no area")
    if len(area) and area[0] < 0:
        problems.append("the first ring, an outer ring, runs clockwise")
    return problems


def _level_of(path: str) -> Level:
    """Return the level of detail of the base map file *path*."""
    return COARSE if path == COARSE_FILE else LEVELS[int(Path(path).stem)]


def report(
    files: Mapping[str, Mapping[str, Any]], sizes: Mapping[str, tuple[int, int]]
) -> Iterator[str]:
    """Yield per level of detail its lines per class, water areas and sizes.

    Then the same of the buildings files, their holes in place of water.
    """
    groups: dict[str, list[str]] = {}
    for path in files:
        if _is_buildings(path):
            groups.setdefault(BUILDINGS_DIR, []).append(path)
        elif path != INDEX_FILE:
            groups.setdefault(_level_of(path).name, []).append(path)
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
    paths = groups.get(BUILDINGS_DIR, [])
    if not paths:
        return
    vertices = buildings = holes = 0
    for path in paths:
        area = _areas(*_decoded(files[path]))
        vertices += len(files[path]["xy"]) // 2
        buildings += int(np.sum(area > 0))
        holes += int(np.sum(area < 0))
    largest = max(paths, key=lambda p: sizes[p][0])
    yield (
        f"{BUILDINGS_DIR:<7} {len(paths):>5} {vertices:>10,} {holes:>7,}"
        f" {format_size(sum(sizes[p][0] for p in paths)):>10}"
        f" {format_size(sum(sizes[p][1] for p in paths)):>10}"
        f" {format_size(max(sizes[p][1] for p in paths)):>10}  buildings {buildings:,},"
        f" largest {largest} {format_size(sizes[largest][0])}"
    )
