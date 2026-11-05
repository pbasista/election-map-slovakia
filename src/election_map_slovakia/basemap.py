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

Output, ``data/build/base/<extract>/base/`` (JSON, compact), one per
OpenStreetMap extract, which every election on it shares: topologies as
in :mod:`geo` (``{scale, arcs, lines, features}``, read by
web/js/topo.js), where an arc is a line of the base map or a ring of a
water area, and ``lines`` gives
its class (:data:`CLASSES`; :data:`WATER` for a ring, which is filled, not
stroked); each water area is a feature ``{properties: {}, arcs:
[[ring, …]]}``, a ring one arc::

    okres/<okres>/<lod>.json  the base map of an okres at a shard level
    coarse.json               the base map of the coarse view
    obec/<obec>.json          the buildings of an obec, {scale, counts, xy}
    index.json                {bands: [{lod, zoom: [from, until | null]}],
                               the shards' bands; okresy: [okres, …];
                               buildings: {zoom, obce: [obec, …]}}

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
import tempfile
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from concurrent.futures import Executor, Future
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

from election_map_slovakia import geo, output, parallel, progress, stamp
from election_map_slovakia.output import format_size

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


@dataclass(frozen=True)
class File:
    """A file of the base map, encoded, and what :func:`report` counts of it."""

    data: bytes
    """The content, compact JSON."""
    vertices: int = 0
    lines: Counter[int] = field(default_factory=Counter)
    """Of a base file, its arcs of each class (:data:`WATER`: rings)."""
    holes: int = 0
    """Of a base file its water areas, of a buildings file the holes."""
    buildings: int = 0


def _pack(geometries: np.ndarray) -> Any:
    """Return *geometries*, all of one type, as a few flat arrays to pickle.

    Shapely pickles each geometry on its own, which takes over a second for
    the lines of a level; they go to the worker processes.
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
    classify: Callable[[TagList], tuple[int | None, bool]] = _line_class
    """The class of a way and whether a ramp, as :func:`_line_class`."""

    def way(self, o: Way) -> None:
        kind, link = self.classify(o.tags)
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

    Their WKB (as :attr:`_Lines.wkb`) is put on the grid every
    :data:`_CHUNK` outlines (:func:`_chunk_on_grid`), by NumPy rather than
    shapely: the strings and geometries of all of them would take gigabytes,
    and their coordinates, all on the grid at once, another gigabyte.
    """

    wkb: list[str] = field(default_factory=list)
    ids: list[int] = field(default_factory=list)
    chunks: list[tuple[Buildings, np.ndarray]] = field(default_factory=list)
    factory: osmium.geom.WKBFactory = field(default_factory=osmium.geom.WKBFactory)

    def way(self, o: Way) -> None:
        # Not len(o.nodes): making the list takes a sixth of the time.
        if not o.is_closed():
            return
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
            self.flush()

    def flush(self) -> None:
        """Put the outlines read since the last time on the grid."""
        if self.wkb:
            self.chunks.append(_chunk_on_grid(self.wkb, self.ids))
            self.wkb, self.ids = [], []

    def on_grid(self) -> tuple[Buildings, np.ndarray]:
        """Return the outlines as :class:`Buildings`, and their ids."""
        self.flush()
        if not self.chunks:
            none = np.zeros(0, dtype=np.int64)
            return Buildings(np.zeros((0, 2), dtype=np.int64), none, none), none
        return (
            _concat([buildings for buildings, _ in self.chunks]),
            np.concatenate([ids for _, ids in self.chunks]),
        )


def _chunk_on_grid(wkb: list[str], ids: list[int]) -> tuple[Buildings, np.ndarray]:
    """Return closed outlines in WKB, of *ids*, as :class:`Buildings` and their ids.

    Each outline is a building of one ring, so that a chunk of them is put on
    the grid (:func:`_on_grid`) as it would be among all of them.
    """
    counts = (np.array([len(w) for w in wkb]) - _WKB_HEADER) // _WKB_POINT
    points = bytes.fromhex("".join([w[_WKB_HEADER:] for w in wkb]))
    lonlat = np.frombuffer(points, dtype="<f8").reshape(-1, 2)
    ring = np.repeat(np.arange(len(counts)), counts)
    buildings, kept = _on_grid(lonlat, ring, np.ones(len(counts), dtype=np.int64))
    return buildings, np.array(ids, dtype=np.int64)[kept]


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


_WAY_KEYS = ("building", "highway", "railway", "waterway")
"""The keys of the ways :func:`read_lines` and :func:`read_building_ways`
read (:func:`locate_ways`)."""


def locate_ways(path: Path, out: Path, keys: Sequence[str] = _WAY_KEYS) -> None:
    """Write the ways of the OSM extract *path* with *keys* to *out*.

    With the location of each node on the way, so that the ways' readers
    need no index of the nodes (a gigabyte each) and can read *out* in
    pieces side by side (:func:`way_blocks`). The extract is read once, in
    C++ only; *out* is uncompressed, without metadata, as it is read at once.
    """
    filtered = KeyFilter(*keys)
    filtered.enable_for(WAY)  # the nodes pass, to be located
    options = "pbf,add_metadata=false,locations_on_ways=true,pbf_compression=none"
    writer = osmium.SimpleWriter(osmium.io.File(str(out), options))
    try:
        with osmium.io.Reader(path, NODE | WAY) as reader:
            osmium.apply(reader, filtered, _locations(), EntityFilter(WAY), writer)
    except RuntimeError as e:
        raise BaseMapError(f"{path}: {e}") from e
    finally:
        writer.close()


Block = tuple[int, int, int]
"""A piece of a PBF file: the end of its header blocks, then where its run of
data blocks starts and ends."""


def way_blocks(path: Path, pieces: int) -> list[Block]:
    """Return up to *pieces* runs of about as many data blocks of the PBF *path*.

    Each a file of its own with the header blocks before it (:func:`_piece`).
    """
    header_end = 0
    starts = []
    with path.open("rb") as f:
        while length := f.read(4):
            start = f.tell() - 4
            kind, size = _blob_header(f.read(int.from_bytes(length)))
            f.seek(size, os.SEEK_CUR)
            if kind == b"OSMHeader":
                header_end = f.tell()
            else:
                starts.append(start)
        end = f.tell()
    cuts = [starts[i] for i in np.linspace(0, len(starts), pieces + 1)[:-1].astype(int)]
    bounds = sorted({*cuts, end})
    return [(header_end, a, b) for a, b in itertools.pairwise(bounds)]


_TYPE, _DATASIZE = 1, 3
"""The fields of a PBF BlobHeader this reads (``fileformat.proto``)."""
_LENGTH_DELIMITED = 2
"""The wire type of a string or bytes field; the others here are varints."""
_MORE = 0x80
"""The bit of a varint's byte that says another byte follows."""


def _blob_header(data: bytes) -> tuple[bytes, int]:
    """Return the type and data size of a PBF BlobHeader (protocol buffers)."""
    kind, size, i = b"", 0, 0
    while i < len(data):
        key, i = _varint(data, i)
        if key & 7 == _LENGTH_DELIMITED:  # the type, or the index data
            length, i = _varint(data, i)
            if key >> 3 == _TYPE:
                kind = data[i : i + length]
            i += length
        else:
            value, i = _varint(data, i)
            if key >> 3 == _DATASIZE:
                size = value
    return kind, size


def _varint(data: bytes, i: int) -> tuple[int, int]:
    """Return the protocol buffers varint at *i* of *data*, and the index after it."""
    value = shift = 0
    while True:
        byte = data[i]
        i += 1
        value |= (byte & ~_MORE) << shift
        shift += 7
        if not byte & _MORE:
            return value, i


def _piece(path: Path, block: Block) -> osmium.io.FileBuffer:
    """Return the *block* of the PBF *path* as a file of its own."""
    header_end, start, end = block
    with path.open("rb") as f:
        header = f.read(header_end)
        f.seek(start)
        return osmium.io.FileBuffer(header + f.read(end - start), "pbf")


def read_lines(
    path: Path,
    block: Block,
    tags: Collection[tuple[str, str]] = _LINE_TAGS,
    classify: Callable[[TagList], tuple[int | None, bool]] = _line_class,
) -> _Read:
    """Return the lines of *block* of the located ways *path*, in EPSG:5514.

    (:func:`locate_ways`); :func:`_ways` makes those of every block :class:`Ways`.
    The ways with any of *tags* are read, of the class *classify* gives them.
    """
    got = _Lines(classify=classify)
    keys, exact = _tagged(tags, WAY)
    try:
        with osmium.io.Reader(_piece(path, block), WAY) as reader:
            osmium.apply(reader, keys, exact, got)
    except RuntimeError as e:
        raise BaseMapError(f"{path}: {e}") from e
    wgs84 = shapely.from_wkb([bytes.fromhex(line) for line in got.wkb])
    lonlat, index = shapely.get_coordinates(wgs84, return_index=True)
    return _Read(
        _to_metres(lonlat[:, 0], lonlat[:, 1]),
        index,
        np.array(got.kinds, dtype=np.uint8),
        np.array(got.links, dtype=bool),
        np.array(got.names, dtype=object),
    )


@dataclass
class _Read:
    """The lines :func:`read_lines` takes from a block of the located ways."""

    xy: np.ndarray
    """The vertices of every line in turn, EPSG:5514."""
    index: np.ndarray
    """The line of each vertex."""
    kind: np.ndarray
    link: np.ndarray
    names: np.ndarray


def _ways(reads: Sequence[_Read]) -> Ways:
    """Return the lines of all *reads*, in turn, as :class:`Ways`."""
    kind = np.concatenate([r.kind for r in reads])
    if not len(kind):
        raise BaseMapError("the extract has no roads, railways or waterways")
    lines = _lines_of(reads)
    names = np.concatenate([r.names for r in reads])
    course = _course_lengths(lines, kind, names)
    return Ways(lines, kind, np.concatenate([r.link for r in reads]), course)


def _lines_of(reads: Sequence[_Read]) -> np.ndarray:
    """Return the lines of all *reads*, in turn, EPSG:5514."""
    lines_before = np.cumsum([0, *(len(r.kind) for r in reads[:-1])])
    index = np.concatenate(
        [r.index + n for r, n in zip(reads, lines_before, strict=True)]
    )
    return shapely.linestrings(np.concatenate([r.xy for r in reads]), indices=index)


def read_building_ways(path: Path, block: Block) -> tuple[Buildings, np.ndarray]:
    """Return the buildings that are closed ways of *block* of the located ways *path*.

    And their ids (:func:`locate_ways`). Making the outlines one by one takes
    far longer than reading them: the blocks are read side by side.
    libosmium hands the ways to :class:`_Outlines` itself (``apply``), a
    tenth faster than a loop over them here.
    """
    keys = KeyFilter("building")
    keys.enable_for(WAY)
    outlines = _Outlines()
    try:
        with osmium.io.Reader(_piece(path, block), WAY) as reader:
            osmium.apply(reader, keys, outlines)
    except RuntimeError as e:
        raise BaseMapError(f"{path}: {e}") from e
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
    (:meth:`Buildings.points`), *obce* in EPSG:5514 as WKB: shapely pickles
    each geometry on its own, which took most of a second for the obce sent
    to every worker.
    """
    obce = shapely.from_wkb(obce)
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


def building_order(points: np.ndarray, owner: np.ndarray) -> np.ndarray:
    """Return the indexes of the buildings in the order of their files.

    By obec, then along a Hilbert curve; those of no obec (*owner* -1) left
    out. *points* are :meth:`Buildings.points`, and *owner* the index of the
    obec of each building.
    """
    if not len(points):
        return np.array([], dtype=np.int64)
    low = points.min(axis=0)
    span = max(float(np.max(points - low)), 1.0)
    grid = ((points - low) * (((1 << _CURVE_BITS) - 1) / span)).astype(np.int64)
    curve = _hilbert(grid[:, 0], grid[:, 1], _CURVE_BITS)
    order = np.lexsort((curve, owner))
    return order[owner[order] >= 0]


def building_files(
    buildings: Buildings, owner: np.ndarray, codes: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Return the buildings file of each obec: path below ``base/`` → content.

    *buildings* are in :func:`building_order`, and *owner* the index in
    *codes* of the obec of each.
    """
    if not len(buildings.rings):
        return {}
    # Where the rings and vertices of each obec end, after those before.
    obec, per_obec = np.unique(owner, return_counts=True)
    ring_ends = np.cumsum(buildings.rings)[np.cumsum(per_obec) - 1]
    vertex_ends = np.cumsum(buildings.counts)[ring_ends - 1]
    ring_starts = np.r_[0, ring_ends[:-1]]
    vertex_starts = np.r_[0, vertex_ends[:-1]]
    xy = buildings.xy
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
            "counts": buildings.counts[r0:r1].tolist(),
            "xy": steps[v0:v1].ravel().tolist(),
        }
    return files


def _obec_files(
    buildings: Buildings, owner: np.ndarray, codes: Sequence[str]
) -> dict[str, File]:
    """Return the files of :func:`building_files`, encoded, and their counts."""
    area = _areas(buildings.xy, buildings.counts)
    ring_owner = np.repeat(owner, buildings.rings)
    outer = np.bincount(ring_owner[area > 0], minlength=len(codes)).tolist()
    holes = np.bincount(ring_owner[area < 0], minlength=len(codes)).tolist()
    index = {buildings_path(code): i for i, code in enumerate(codes)}
    return {
        path: File(
            output.to_json(content),
            vertices=len(content["xy"]) // 2,
            holes=holes[index[path]],
            buildings=outer[index[path]],
        )
        for path, content in building_files(buildings, owner, codes).items()
    }


def _shares(owner: np.ndarray, n: int) -> list[tuple[int, int]]:
    """Return up to *n* ranges of *owner*, sorted, of whole obce, about as long."""
    starts = np.flatnonzero(np.r_[True, owner[1:] != owner[:-1]])
    wanted = np.linspace(0, len(owner), n + 1)[1:-1]
    cuts = starts[np.minimum(np.searchsorted(starts, wanted), len(starts) - 1)]
    bounds = sorted({0, *cuts.tolist(), len(owner)})
    return list(itertools.pairwise(bounds))


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
    _packed: Any = field(default=None, init=False, repr=False, compare=False)
    """The state :meth:`__getstate__` returned: a level goes to a task per
    share of the okresy, and packing it took a second for them all."""

    def __getstate__(self) -> tuple[dict[int, Any], Any]:
        """Return the state to pickle, the geometries packed (:func:`_pack`)."""
        if self._packed is None:
            self._packed = (
                {k: _pack(g) for k, g in self.lines.items()},
                _pack(self.water),
            )
        return self._packed

    def __setstate__(self, state: tuple[dict[int, Any], Any]) -> None:
        """Restore the state :meth:`__getstate__` returned."""
        lines, water = state
        self.lines = {k: _unpack(g) for k, g in lines.items()}
        self.water = _unpack(water)
        self._packed = None


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


def _level_files(drawn: _Drawn, where: Sequence[_Area], level: Level) -> list[File]:
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
        content = base_file(
            clipped, water.within(area.waters), to_wgs84, 10**level.decimals
        )
        files.append(
            File(
                output.to_json(content),
                vertices=sum(len(a) for a in content["arcs"]) // 2,
                lines=Counter(content["lines"]),
                holes=len(content["features"]),
            )
        )
    return files


def build(
    path: Path, okres_gpkg: Path, obec_gpkg: Path, scratch: Path
) -> dict[str, File]:
    """Return the files of the base map: path below ``base/`` → file.

    *path* is the OSM extract, *okres_gpkg* the ZBGIS GeoPackage whose okresy
    the files are clipped to, *obec_gpkg* that whose obce get the buildings
    (level 0, the shards' obce). A worker writes the ways with their nodes'
    locations to a file in *scratch* (:func:`locate_ways`) while others read
    the water and the multipolygon buildings; then the workers read the
    lines and the buildings of that file, a run of its blocks each, simplify
    each level's lines of a class and its water apart, clip each level to a
    share of the okresy as soon as it is simplified, place the buildings in
    the obce and make the files of a share of the obce each. The workers
    encode the files they make, which took seconds here.
    """
    if set(LEVELS) != {lod.level for lod in geo.SHARD_LODS}:
        raise BaseMapError("LEVELS must name the levels of detail of geo.SHARD_LODS")
    okresy = {
        code: g
        for code, (_, g) in geo.read_layer(okres_gpkg, "okres", "IDN3", "NM3").items()
    }
    obce = geo.read_layer(obec_gpkg, "obec", "IDN4", "NM4")
    obec_codes = sorted(obce)
    polygons = shapely.to_wkb(np.array([obce[c][1] for c in obec_codes]))
    with (
        parallel.pool() as pool,
        tempfile.TemporaryDirectory(dir=scratch, prefix="basemap-") as tmp,
    ):
        located = Path(tmp) / "ways.osm.pbf"
        # The longest task first.
        locating = pool.submit(locate_ways, path, located)
        water_areas = pool.submit(read_areas, path)
        strip = pool.submit(areas, okresy)
        with progress.stage(f"locating the nodes of the ways of {path.name}"):
            locating.result()
        # More blocks than workers, so that none is left with a long one.
        blocks = way_blocks(located, 2 * (os.cpu_count() or 1))
        lines = [pool.submit(read_lines, located, block) for block in blocks]
        building_ways = [
            pool.submit(read_building_ways, located, block) for block in blocks
        ]
        with progress.stage(f"reading the lines of {path.name}"):
            ways = _ways([read.result() for read in lines])
        with progress.stage(
            f"reading the waters of {path.name}, the strip around Slovakia"
        ):
            water, multipolygons, outer = water_areas.result()
            by_okres, slovakia = strip.result()
        simplifying = _simplifying(pool, ways, water)
        del ways, water
        with progress.stage(f"reading the buildings of {path.name}"):
            read = [block.result() for block in building_ways]
            outlines = _concat([buildings for buildings, _ in read])
            ids = np.concatenate([way_ids for _, way_ids in read])
            del read
        # The multipolygons, then the closed ways but their outer ways, which
        # may be tagged as the building too.
        kept = np.flatnonzero(~np.isin(ids, outer))
        points = np.concatenate([multipolygons.points(), outlines.points()[kept]])
        if not len(points):
            raise BaseMapError(f"{path}: no buildings")
        # PROJ and the tests of the points take seconds: a share per worker,
        # while the other workers make the base files.
        owners = [
            pool.submit(_owners, share, polygons)
            for share in np.array_split(points, os.cpu_count() or 1)
        ]
        buildings = _concat([multipolygons, outlines.take(kept)])
        del outlines
        base = _base_files(pool, simplifying, by_okres, slovakia)
        with progress.stage("placing the buildings in the obce"):
            owner = np.concatenate([f.result() for f in owners])
            order = building_order(points, owner)
            owner = owner[order]
        shares = _shares(owner, os.cpu_count() or 1)
        with progress.stage("making the buildings files", len(shares)) as s:
            making = [
                pool.submit(
                    _obec_files, buildings.take(order[a:b]), owner[a:b], obec_codes
                )
                for a, b in shares
            ]
            files = {}
            for share in s.track(making):
                files |= share.result()
    built = sorted(Path(p).stem for p in files)
    files |= base
    index = {
        "bands": [
            {"lod": str(lod.level), "zoom": [lod.from_zoom, lod.until_zoom]}
            for lod in geo.SHARD_LODS
        ],
        "okresy": sorted(okresy),
        "buildings": {"zoom": BUILDINGS_ZOOM, "obce": built},
    }
    files[INDEX_FILE] = File(output.to_json(index))
    return files


Simplifying = list[tuple[Level, list[Future[_Drawn]]]]
"""Each level, and the pieces of it being simplified (:func:`_simplifying`)."""


def _simplifying(pool: Executor, ways: Ways, water: Any) -> Simplifying:
    """Start simplifying the pieces of each level (:func:`_pieces`) in *pool*.

    The most detailed level first, so that no worker is left with a long
    task at the end.
    """
    levels = [*(LEVELS[lod.level] for lod in reversed(geo.SHARD_LODS)), COARSE]
    return [
        (
            level,
            [pool.submit(_simplify, p, level) for p in _pieces(ways, water, level)],
        )
        for level in levels
    ]


def _base_files(
    pool: Executor,
    simplifying: Simplifying,
    by_okres: Mapping[str, _Area],
    slovakia: _Area,
) -> dict[str, File]:
    """Return the base files of every level: path → file.

    Each level, once *simplifying* is done with it, clipped by a task per
    worker of *pool*, each a share of *by_okres*, or for the coarse view to
    *slovakia*.
    """
    shares = os.cpu_count() or 1
    codes = sorted(by_okres)
    clips: list[tuple[list[str], Future[list[File]]]] = []
    with progress.stage("simplifying the levels of detail", len(simplifying)) as s:
        for level, pieces in simplifying:
            drawn = _joined([piece.result() for piece in pieces])
            s.advance()
            if level is COARSE:
                clip = pool.submit(_level_files, drawn, [slovakia], level)
                clips.append(([COARSE_FILE], clip))
                continue
            for share in (codes[i::shares] for i in range(min(shares, len(codes)))):
                where = [by_okres[code] for code in share]
                clip = pool.submit(_level_files, drawn, where, level)
                clips.append(([okres_path(code, level.name) for code in share], clip))
    files: dict[str, File] = {}
    with progress.stage("clipping them to the okresy", len(clips)) as s:
        for names, clip in s.track(clips):
            files.update(zip(names, clip.result(), strict=True))
    return files


# --- the lines geo cuts street blocks by ------------------------------------------

BARRIERS_DIR = "barriers"
"""Below ``data/build/shared/``: the lines of :func:`barriers` per extract."""
_BARRIER_KEYS = ("highway", "railway", "waterway")
_BARRIER_TAGS = (
    *(("highway", v) for road in _ROADS for v in (road, f"{road}_link")),
    *(
        ("highway", v)
        for v in ("road", "service", "track", "footway", "path", "cycleway", "steps")
    ),
    *(("railway", v) for v in _RAILWAYS),
    *(("waterway", v) for v in _WATERWAYS),
)
_DOUBLING = ("sidewalk", "crossing")
"""The footways (``footway=*``) that only double a street."""
_UNDERNEATH = ("tunnel", "covered", "indoor")


def _barrier_class(tags: TagList) -> tuple[int | None, bool]:
    """Return 0 for a way that bounds street blocks, else None; never a ramp.

    As :func:`_line_class` for :func:`read_lines`; see :func:`barriers`.
    """
    if (
        any(tags.get(key, "no") != "no" for key in _UNDERNEATH)
        or tags.get("area") == "yes"
        or tags.get("footway") in _DOUBLING
        or ("railway" in tags and "service" in tags)
    ):
        return None, False
    return 0, False


def barriers(path: Path, scratch: Path, shared: Path) -> geo.Barriers:
    """Return the lines of the OSM extract *path* that bound street blocks.

    In EPSG:5514. ``geo`` cuts council obvody and okrsky by the blocks
    these lines and the k.ú. borders make
    (:func:`election_map_slovakia.geo.address_cuts`): the roads, service
    roads, tracks, footways, paths and steps, but sidewalks and crossings,
    which double a street; the railways and tram lines, but sidings and
    yards; the rivers, canals and streams; none in a tunnel or culvert,
    covered or indoors, or mapped as an area. Tried on the cities and
    villages cut into several obvody, each class takes a share of the
    borders between them off the Voronoi lines between houses and onto a
    line on the ground: footways and service roads in the housing estates
    and garage rows, tracks and streams in the villages and between them.
    Read only once asked for (a run with every obec's cut cached needs
    none), and once per extract and version of the code that reads them,
    kept below *shared* (a :class:`geo.Cache`): the ways are located into a
    file in *scratch* (:func:`locate_ways`), then read in blocks side by
    side. That code is this module's and the transformation to EPSG:5514
    (:func:`election_map_slovakia.stamp.source_digest`), not all of
    ``geo``'s, whose every change would else read them again.
    """
    code = stamp.source_digest("basemap", LIBRARY, geo.transformer().definition)
    digest = stamp.file_digest(path)
    cache = geo.Cache(shared, code, digest)
    entry = cache.entry("lines")

    def lines() -> np.ndarray:
        packed = cache.get(entry)
        if packed is None:
            with (
                progress.stage(f"reading the street block lines of {path.name}"),
                parallel.pool() as pool,
                tempfile.TemporaryDirectory(dir=scratch, prefix="barriers-") as tmp,
            ):
                located = Path(tmp) / "ways.osm.pbf"
                locate_ways(path, located, _BARRIER_KEYS)
                reads = [
                    pool.submit(
                        read_lines, located, block, _BARRIER_TAGS, _barrier_class
                    )
                    for block in way_blocks(located, 2 * (os.cpu_count() or 1))
                ]
                packed = _pack(_lines_of([read.result() for read in reads]))
            cache.put(entry, packed)
        return _unpack(packed)

    return geo.Barriers(lines, f"{code} {digest}")


def okres_path(okres: str, lod: str) -> str:
    """Return the path below ``base/`` of the base map of *okres* at *lod*."""
    return f"okres/{okres}/{lod}.json"


def buildings_path(obec: str) -> str:
    """Return the path below ``base/`` of the buildings of *obec*."""
    return f"{BUILDINGS_DIR}/{obec}.json"


def _is_buildings(path: str) -> bool:
    return path.startswith(f"{BUILDINGS_DIR}/")


def write(
    files: Mapping[str, bytes], directory: Path, memo: Path | None = None
) -> dict[str, tuple[int, int]]:
    """Replace *directory* with *files*, path → JSON.

    Return path → (bytes, gzip bytes), the gzip sizes kept in *memo*
    (:func:`election_map_slovakia.output.gzip_sizes`).
    """
    blobs = dict(sorted(files.items()))
    with (
        progress.stage(f"writing {directory.name}/", len(blobs)) as s,
        output.replacing(directory) as tmp,
    ):
        made: set[Path] = set()
        for path, data in s.track(blobs.items()):
            target = tmp / path
            if target.parent not in made:
                target.parent.mkdir(parents=True, exist_ok=True)
                made.add(target.parent)
            target.write_bytes(data)
    gz = output.gzip_sizes(list(blobs.values()), memo)
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
    files: Mapping[str, File], sizes: Mapping[str, tuple[int, int]]
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
            counts.update(files[path].lines)
            vertices += files[path].vertices
            water += files[path].holes
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
        vertices += files[path].vertices
        buildings += files[path].buildings
        holes += files[path].holes
    largest = max(paths, key=lambda p: sizes[p][0])
    yield (
        f"{BUILDINGS_DIR:<7} {len(paths):>5} {vertices:>10,} {holes:>7,}"
        f" {format_size(sum(sizes[p][0] for p in paths)):>10}"
        f" {format_size(sum(sizes[p][1] for p in paths)):>10}"
        f" {format_size(max(sizes[p][1] for p in paths)):>10}  buildings {buildings:,},"
        f" largest {largest} {format_size(sizes[largest][0])}"
    )
