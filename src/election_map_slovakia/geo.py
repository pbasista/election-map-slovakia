"""Turn the ZBGIS boundaries into map geometry for the frontend.

ZBGIS publishes the boundaries in EPSG:5514 at four levels of detail: level 0
is the full survey; levels 1 and 2 are official simplifications that deviate
from it by at most about 10 and 50 m (Hausdorff distance, measured per obec).
Every level is a clean coverage: neighbouring obce share their border vertex
for vertex. Level 3 is not used: generalized on its own, its kraj and okres
borders lie up to 180 m off the obce of every other level, so drawn over
them they showed as a second line.

Every output file is a topology of one level of detail: the obce (or coarse
cells) of that level, simplified as one coverage where needed, reprojected to
WGS84 and rounded per coordinate, then cut into arcs at the vertices where
three or more units meet. Each border is stored once, as an arc; a feature
lists the arcs of its rings. Kraj, okres, country and obvod borders are no
geometry of their own: they are the arcs whose two sides differ in kraj,
okres, obvod, so at every zoom they are exactly the obce borders drawn with
them, and the frontend strokes each arc once, in the style of the highest
boundary it is part of.

At Leaflet zoom *z* a pixel spans about 103 km / 2^z at 48.7° N. Each level
serves the zoom band where its deviation stays under about a pixel:

======  ================================  ======  ===========  ===============
lod     geometry                          zoom    decimals     deviation
======  ================================  ======  ===========  ===============
coarse  level 2 cells, coverage_simplify  < 9.5   5 (≤ 0.6 m)  ≤ 73 m (p95 4 m)
        100 m                                                  from lod 2
2       ZBGIS level 2                     9.5–12  5 (≤ 0.6 m)  ≤ 50 m
1       ZBGIS level 1                     12–14   5            ≤ 10 m
0       level 0, coverage_simplify 2 m    ≥ 14    5            ≤ 2.3 m
======  ================================  ======  ===========  ===============

A coarse cell is the obce of one okres that share their regional and city
council obvod: the coarsest units that still have every border the coarse
view draws. At 4 decimals rounding folded a cell in Bratislava over two
neighbours (136 m²); 5 decimals cost 18 KiB more, gzipped.

Rounding shared vertices identically keeps borders shared, but it can fold
a sliver narrower than the grid onto its neighbour: at 4 decimals (11 m)
levels 1 and 2 overlapped by 170 and 370 m², at 5 decimals by nothing. The
vertices rounding repeats, and the tips of spikes it folds flat, are dropped;
both depend only on the vertices of the border, so neighbours drop the same.

The countries around Slovakia come from Natural Earth (admin 0, 1:10m), so
that Slovakia is not drawn as an island. The map draws them below Slovakia,
and they reach :data:`UNDER` metres under it: whichever level of detail
draws Slovakia, its fill meets theirs at its own ZBGIS border, with no gap,
and covers what they have under it. Natural Earth's border of Slovakia is
off the ZBGIS one by 0.9 km (median), up to 4 km. The area between the two,
and the strip under Slovakia's border that no neighbour reaches, goes to
the nearest neighbour (the Voronoi cells of points every :data:`SAMPLE`
metres along the neighbours' borders), so a border between two neighbours
runs on to Slovakia's, meeting it within a kilometre or two of the true
tripoint, as far as Natural Earth is off. Countries under :data:`MIN_AREA`
(Monaco, San Marino, Vatican) are left out, an enclave going to the country
around it. The areas are made an exact coverage by cutting them along all
their borders: each piece goes to the area it lies in, a sliver of under
:data:`MIN_AREA` that none claims to the one it shares the most border with.
Then they are simplified, rounded and cut into arcs like the obce. 1:50m
would be 1.1 km off (median), up to 6.5 km, with vertices 8 km apart
against 2.2 km: at zoom 9 (200 m a pixel), where the neighbours are drawn
with the obce, its borders between neighbours would be tens of pixels off,
and visibly angular.

======  ==================================  ======  ========  ===========
lod     extent                              zoom    simplify  decimals
======  ==================================  ======  ========  ===========
1       :data:`EXTENT`                      < 8     600 m     3 (≤ 110 m)
0       what views from zoom 8 show         ≥ 8     100 m     4 (≤ 11 m)
======  ==================================  ======  ========  ===========

600 m is 1.5 pixels at zoom 8, under a pixel at the zooms lod 1 is mostly
seen at. :data:`EXTENT` is what a 1440 × 900 view shows at the map's lowest
zoom (6) around the middle of its maxBounds (map.js); the map raises its
lowest zoom on larger views so that no view reaches past it. Lod 0 covers
what views up to 2560 × 1440 show from zoom 8 on, with the quarter view the
map draws beyond each side where they can pan; a larger view keeps lod 1.
Neither moves the edge under Slovakia by :data:`UNDER`, so its fill keeps
hiding it.

Output, ``data/build/<election day>/geo/`` (JSON, compact; codes are strings, obvod numbers
integers; ``label`` = [lon, lat] is the centre of a unit's largest inscribed
circle; ``parts`` = [[lon, lat, room], …] the same of each other polygon of a
unit of several, room the circle's radius in metres, those with room for a
label only, see PART_ROOM)::

    okres/<okres>/<lod>.json  topology of the obce of an okres, features
                              {id: obec, name, okres, kraj, zsk: n,
                               (city, city_obvod: n), label, (parts),
                               (oz: n, oz_label, (oz_parts), (approx: 1),
                                (estimated: 1))}
    coarse.json               topology of the coarse cells, features
                              {kraj, okres, zsk: n, (city, city_obvod: n)};
                              and land: the country outline as polygons of
                              arc indexes (a fill of one path, with a
                              fraction of the vertices of all cells),
                              kraje [{id, name, label, (parts)}],
                              okresy [{id, name, kraj, label, (parts)}],
                              obvody [{id: "zsk:<kraj>/<n>" | "oz:<city>/<n>",
                                       seats, label, (parts)}]
    okrsky/<okres>/<lod>.json topology of the okrsky of the obce of an okres
                              whose okrsky are drawn (below), features
                              {obec, okrsok: n, obvod: n, label,
                               (approx: 1)}, label the same at every lod
    neighbours/<lod>.json     topology of the countries around Slovakia,
                              features {id: ISO 3166 code, spots: [[lon,
                              lat, room], …]: places for its name, room the
                              metres to the edge of the part that shows
                              (see label_spots)}
    index.json                {shards: [{lod, zoom: [from, until | null]}],
                               okresy: {okres: [west, south, east, north]},
                               neighbours: [{lod, zoom: [from, until | null],
                                             extent: [west, south, east,
                                                      north]}],
                               okrsky: {bands: [{lod, zoom}] as shards,
                                        okresy: {okres: [west, south, east,
                                                         north]},
                                        drawn: {obec: [okrsok, …]}}}

A topology is ``{scale, arcs, lines, features}``. An arc is a list
[x0, y0, dx1, dy1, …] of integer lon, lat in 1/scale degree, each point but
the first relative to the one before. A feature's ``arcs`` are its polygons,
each a list of rings, each a list of arc indexes, ``~i`` (-i - 1) for arc i
reversed. ``lines`` has a code per arc: the rank of the highest boundary the
arc is part of (0 obec, 1 okres, 2 kraj, 3 country), plus 4 if it bounds a
regional council obvod, 8 if a city council obvod (the city outline too),
16 if the file does not draw it: an arc on an okres border is in the shards
of both okresy, so either can build its polygons, and drawn by the lower
code; the outer edges of the neighbours (coast, extent, under Slovakia) are
drawn by none. Between two neighbours an arc is a country border. 32 marks
a border between two council obvody within an obec, 64 one that is
approximate (below), 128 one between two okrsky of an obec.

An obec's ``zsk`` is its regional council obvod, 0 where the election has
no regional council by obvod (a country-wide election, a by-election
without one in its kraj); ``city`` and ``city_obvod`` are set on the
districts of Bratislava and Košice where it has their city councils.
Obvod membership comes from ``obvody/`` in the election's data (see
:mod:`election_map_slovakia.obvody`), of the kraje and cities whose
councils it elects; ``coarse.json`` ``obvody`` lists theirs alone.

An obec that elects its council and whose council obvody have a rule set (``obvody/oz/`` there)
is several features in the shards, one per obvod (``oz``; ``oz_label`` and
``oz_parts`` are its own, and the obec's ``label`` and ``parts`` are on the
one that holds its label). Where
the rules name k.ú., the obvody are unions of k.ú.; otherwise they are drawn
from the obvod of every address (``obvod-addresses/`` of the build, the rules
applied): unions of k.ú. where each k.ú. holds addresses of one obvod
(villages whose parts are their k.ú.), else cut from the obec by street
blocks (below). Both are ``approx``: the true border runs somewhere
between the houses. An obec whose rule set is a guess (``estimated``, see
:mod:`election_map_slovakia.obvody`) has ``estimated`` too. K.ú. unions
are made in every level before level 0 is simplified, so they share the
obce's vertices. The cuts by street blocks are placed on the grid, after
rounding: cut in metres, rounding folded the slivers and sharp tips they
leave by the border into rings that cross themselves or run the wrong
way. So the obvody, reaching beyond the obec (:data:`REACH`; their
borders simplified per coarser level, :data:`CUT_TOLERANCE`), are noded
with the rounded obec's border by snap rounding, which gives valid pieces
with integer vertices but bends the border through the points whose pixel
it crosses; every feature with such an edge, the neighbours too, is bent
alike (:func:`cut_council`), so the features stay a coverage that shares
its vertices. An edge that is a piece of one bent edge already is not bent
again through another's points: near the tip of a narrow wedge, snap
rounding bends both its edges through the same pixels.

The street blocks are the faces of the obec cut by the roads, railways and
waterways of the election's OpenStreetMap extract
(:func:`election_map_slovakia.basemap.barriers`), its k.ú. borders and
its own (:func:`_block_cut`), so that the borders between obvody run along
streets, railways, rivers and k.ú. borders, as the documents describe
them. A settled block whose addresses are all of one obvod is that
obvod's whole. A mixed block, a street split by house numbers, is cut
between its obvody by the Voronoi cells of its address points, the land
within :data:`HOUSE_REACH` of them theirs, the rest empty land; so is a
sparse block (a forest or field with a few cottages, :data:`SPARSE_SHARE`),
whose Voronoi lines stay within its houses' reach. Every located
address is so drawn in its own obvod, but where several obvody's
addresses share one point (entrances of a block of flats): the most
frequent one takes it. Empty land (blocks without addresses: fields,
forests, water) goes whole to the obvod it shares the most border with,
in rounds that start from the settled blocks only (not a cottage's reach),
then smoothed (:data:`SMOOTH_MAJORITY`, :data:`THIN_FACE`) so that it
makes no spikes or wedges; the blocks and faces are first cut across
their narrow places (:data:`NARROW`), so that a strip between a street and
a path beside it goes piece by piece to the land beside it. A piece of an
obvod without any of its addresses goes to the obvod around it. The rules
put single houses and addresses without a street in an obvod whose
streets are elsewhere: each is drawn, a block or a house's reach of it an
island in the obvod around; an island of a sparse block's cottages keeps
only their plots (:data:`ISLAND_REACH`, along their road where it is
near), the rest of their reach going to the obvod around. Parts of an
obvod narrower than :data:`_PINCH` without an address go to a neighbour
(the slivers among them told by width, not area, :data:`_SLIVER`), and
two parts of one nearer than that are bridged: rounded to the map's
grid, either would fold. The blocks are noded, and every overlay of areas
within the cut made, on one grid (:data:`_NODING_GRID`), polygons in and
out (:func:`_grid_overlay`): snapped, a tip under a grid unit wide
collapses into a line, which a further overlay takes no more than a ring
crossed by a rounding error. Then the borders between the obvody are
simplified, by :data:`DETAIL_TOLERANCE` along the street block lines and
the plots and :data:`INNER_TOLERANCE` within the blocks, keeping every
address point in its obvod and at least :data:`_CLEARANCE` from its
border, or as far as it was (:func:`_safely_simplified`): a point a few
centimetres inside would be drawn outside when rounded. The address
search keeps every address in the obvod its rules give it; only a click
on the map takes the obvod of the area drawn there.

The okrsky of an obec whose rule set places every address in one
(:attr:`election_map_slovakia.obvody.RuleSet.okrsok_areas`) are drawn within
its council obvody, at level 0 (EPSG:5514): an okrsok alone in its obvod is
the obvod; the okrsky of an obvod with several are unions of its k.ú. where
the obvod is one and each k.ú. holds one okrsok, else cut from the obvod
like the obvody from the obec, by the street blocks within the obvod.
They must tile their obvod; an obec with one council obvod
(``okrsky/<obec>.toml``) is one obvod, the whole obec. An obec with one
okrsok has none drawn: the obec is its okrsok 1.

On the map the okrsky are cut from the shards (:func:`okrsky_levels`), at
every shard level of detail, so that they tile the features of their obec
there: an okrsok alone in its obvod is the obvod's feature (the obec's, if
the shards do not cut it), the others are cut from it along the borders
between them, each okrsok extended beyond the obvod by the land nearest
to it (:data:`REACH`), so that the cuts cross the feature's border
only where okrsky meet; simplified per level (:data:`CUT_TOLERANCE`) and
noded by snap rounding like the obvody, every okrsky feature with an
edge so bent bent alike. Their
outline may thus differ from the obec's by points within a grid unit
(:data:`MAX_OKRSKY_OFFSET`). The okrsky of the obce of an okres are one file
per level, beside the shards; ``index.json`` ``okrsky`` lists the okresy
that have them and the okrsky drawn per obec (an ``addressless`` okrsok, or
one whose houses all share their points with another's, has none). ``label``
is the centre of the okrsok's largest
inscribed circle at level 0; ``obvod`` the council obvod it is in (1 in
an obec with one). Of the line codes, 128 marks each border between two
okrsky of one obec, with 32 if it is also one between council obvody and
64 if either okrsok is ``approx``; the obec borders, which the shards
draw, are coded 16 (rank 0), so a file draws only the okrsok borders. On
a council obvod border both a shard and an okrsky file draw a line: the
app strokes it once, as the overlays shown call for.

Every election reads the same ZBGIS levels and Natural Earth countries, and
many share an obec's rule set and its addresses (a by-election, a
country-wide vote on the register of the regular election before), so
what depends on those alone is made once and kept in a :class:`Cache`
(``data/build/shared/geo/``): the obce of each level read, simplified,
rounded and labelled (:func:`base`, per set of obce cut by k.ú.), the
countries around Slovakia, each level's overlaps and gaps, each obec's
cut into council obvody and okrsky with the okrsky reaching beyond their
obvod and its address points placed on the grid (:func:`address_cuts`,
keyed on its street block lines too, which change with the extract), and
the cuts placed in the shards (an obec's obvody at every
level, the okrsky of each obvod, :func:`_cached_each`), keyed on what they
are cut from. An
entry is the very value a worker process returned, so the output is the
same as if it were made again. What depends on the election (those cuts
bent alike, the arcs, properties and files, the checks) is made per
election, the cuts per obec and the levels side by side in worker
processes, started once for all the stages.

:func:`verify` (run by ``ems check``) merges the features of each level into
kraje, okresy, obvody and the country with ``coverage_union`` and requires
their borders to be exactly the arcs coded so. :func:`verify_neighbours`
requires the neighbours' borders to be exactly the arcs drawn, and the hole
they leave to be within Slovakia at every level of detail.
:func:`verify_okrsky` requires the okrsky files to hold the okrsky the
index lists, those of each obec to tile its shard features
(:func:`okrsky_problems`, which ``geo`` runs too), and the arcs drawn to
be exactly the borders between two okrsky of an obec, those coded 32
exactly the ones between two council obvody.
"""

from __future__ import annotations

import functools
import hashlib
import heapq
import itertools
import json
import math
import pickle
import re
import shutil
from collections import Counter, defaultdict
from collections.abc import (
    Callable,
    Collection,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, NamedTuple, TypeVar
from xml.sax.saxutils import escape

import numpy as np
import pyproj
import shapely
from pyproj.enums import TransformDirection

from election_map_slovakia import config, obvody, output, parallel, progress
from election_map_slovakia.candidates import (
    CITIES,
    CITY_CODES,
    Admin,
    load_admin,
    search_key,
)
from election_map_slovakia.gpkg import GeoPackage, geometry, srs_id
from election_map_slovakia.output import format_size

NEIGHBOURS_INPUT = "natural-earth-countries"
OUTPUT_DIR = "geo"
OKRSKY_DIR = "okrsky"
"""Below :data:`OUTPUT_DIR`: the okrsky per okres (see the module doc)."""
PREVIEW_DIR = "preview"
COARSE_FILE = "coarse.json"
SOURCE_SRS = 5514
# EPSG:4836 "S-JTSK to WGS 84 (4)", the Helmert transformation for Slovakia
# (1 m). Left to choose, PROJ may take a Czech variant near the border.
_TRANSFORMATION = ("EPSG", 4836)
DETAIL_TOLERANCE = 2.0
"""``coverage_simplify`` tolerance for level 0, in metres (see module doc)."""
CUT_TOLERANCE = {2: 20.0, 1: 5.0}
"""``coverage_simplify`` tolerance of the cuts drawn from address points per
coarser level, in metres: a cut has the detail of the borders it meets. At
level 0 a cut is as drawn, its borders simplified by :data:`DETAIL_TOLERANCE`
keeping every address point in its unit (:func:`_safely_simplified`)."""
COARSE_LEVEL = 2
COARSE_TOLERANCE = 100.0
"""``coverage_simplify`` tolerance for the coarse cells, in metres."""
DECIMALS = 5
BBOX_DECIMALS = 4
# Overlap or gap area tolerated per layer after rounding, in m². Rounding
# leaves triangles of about 0.1 m² where three obce meet; a missing or
# doubled obec is far larger.
MAX_COVERAGE_ERROR = 10.0
MAX_OKRSKY_OFFSET = 0.5
"""Mean distance tolerated between the outline of an obec's okrsky and its
shard features, in metres (the area between them over the obec's
perimeter): the cuts bend the okrsky's outline through points within a
grid unit (0.7–1.1 m) of the obec's border, which the shards do not; in
the 2026 okrsky at most 0.15 m. A missing okrsok is far more."""

# Line codes (see the module doc): a rank, plus flags.
OBEC, OKRES, KRAJ, COUNTRY = range(4)
RANK = 3
ZSK = 4
CITY = 8
FOREIGN = 16
COUNCIL = 32
APPROX = 64
OKRSOK = 128

# Grid coordinates are within ±2^30 (1/scale degree), so a vertex fits one
# int64 key.
_OFFSET = 1 << 30
_MIN_RING = 3  # distinct vertices of a ring that encloses anything
_SIDES = 2  # a border between two units


@dataclass(frozen=True)
class Lod:
    """A level of detail of the per-okres obce shards."""

    level: int
    """ZBGIS level the geometry comes from."""
    from_zoom: float
    """The map draws it from this zoom on ..."""
    until_zoom: float | None
    """... up to this one, exclusive (None: up to the highest)."""


# Level 2 from half a level before zoom 10: the obce get their names there.
SHARD_LODS = (Lod(2, 9.5, 12), Lod(1, 12, 14), Lod(0, 14, None))

# The countries around Slovakia (see the module doc).
NEIGHBOURS_DIR = "neighbours"
EXTENT = (3.7, 41.6, 35.7, 54.9)
"""West, south, east, north of the countries drawn, in degrees."""
UNDER = 1500.0
"""How far the neighbours reach under Slovakia, in metres: more than lod 1
simplifies and rounds them (and the strip's own simplification, a third of
it), plus the 73 m the coarse view's border is off ZBGIS level 0."""
SAMPLE = 200.0
"""Spacing of the points that split the area between Slovakia and its
neighbours by nearest neighbour, in metres."""
NEAR_SLOVAKIA = 10_000.0
"""Points are taken up to this far from Slovakia (Natural Earth is up to
4 km off), in metres."""
MIN_AREA = 100e6
"""Smallest country drawn, and largest sliver merged, in m²."""
SPOT_CELL = 16_000.0
"""Side of the smallest square a country's part is cut into for the places
of its name, in metres: about a view at zoom 13, so that one along the
border has a place for each neighbour it shows."""
_ISO_CODE = re.compile(r"[A-Z]{2}")
_METRES_PER_DEGREE = 111_320
# Square metres in a square degree at Slovakia's latitude.
_M2_PER_DEGREE2 = _METRES_PER_DEGREE**2 * math.cos(math.radians(48.7))
PART_ROOM = 30.0
"""Least room, in metres from its label's centre to its edge, for which a
part of an area other than the one with its label is labelled too: about
what a short name needs at the highest zoom."""


@dataclass(frozen=True)
class NeighbourLod:
    """A level of detail of the countries around Slovakia."""

    level: int
    extent: tuple[float, float, float, float]
    tolerance: float
    """``coverage_simplify`` tolerance, in metres."""
    decimals: int
    from_zoom: float
    until_zoom: float | None


NEIGHBOUR_LODS = (
    NeighbourLod(1, EXTENT, 600.0, 3, 0, 8),
    NeighbourLod(0, (12.5, 46.0, 27.0, 51.3), 100.0, 4, 8, None),
)


class GeoError(Exception):
    """The boundaries are inconsistent or the output fails its checks."""


@dataclass(frozen=True)
class Coverage:
    """How well a level's features tile their union, after rounding."""

    name: str
    features: int
    vertices: int
    """Vertices stored, each border once."""
    overlap: float
    """Area covered twice, m²."""
    gaps: float
    """Area of holes in the union, m²."""


@dataclass
class Result:
    """Everything ``geo`` writes, plus the checks for the report."""

    files: dict[str, dict[str, Any]]
    """Path below ``geo/`` → JSON content."""
    coverage: list[Coverage] = field(default_factory=list)
    seats: dict[str, int] = field(default_factory=dict)
    """Seats per kraj code and per city (BA, KE)."""
    short: list[tuple[str, int, int]] = field(default_factory=list)
    """Obvody with fewer candidates than seats: (id, candidates, seats)."""
    council: dict[str, tuple[int, bool, bool]] = field(default_factory=dict)
    """Obec cut into council obvody → (obvody, approximate, by k.ú.)."""
    council_points: dict[str, Points] = field(default_factory=dict)
    """Obec cut by its address points → those points, in grid units."""
    okrsky: dict[str, list[Okrsok]] = field(default_factory=dict)
    """Obec → its okrsky drawn (:func:`address_cuts`), in ``okrsky/``."""
    okrsky_points: dict[str, Points] = field(default_factory=dict)
    """Obec with okrsky drawn → the points of their addresses, in grid units."""
    okrsky_by_obvod: list[str] = field(default_factory=list)
    """Obce whose okrsky are known only by obvod, not drawn."""
    figures: dict[str, Figures] = field(
        default_factory=lambda: {"council": Figures(), "okrsky": Figures()}
    )
    """How the council obvody cut by their address points and the okrsky
    drawn look at full detail (:func:`figures`)."""


@functools.cache
def transformer() -> pyproj.Transformer:
    """Return the EPSG:5514 → WGS84 (lon, lat) transformation for Slovakia.

    Made once per process: finding it in PROJ's database takes a while.
    """
    group = pyproj.transformer.TransformerGroup(
        f"EPSG:{SOURCE_SRS}", "EPSG:4326", always_xy=True
    )
    for t in group.transformers:
        steps = [s.get("id", {}) for s in t.to_json_dict().get("steps", [])]
        if any((s.get("authority"), s.get("code")) == _TRANSFORMATION for s in steps):
            return t
    raise GeoError("PROJ lacks EPSG:4836 (S-JTSK to WGS 84 for Slovakia)")


class Cache:
    """What ``geo`` computes alike for several elections, kept between runs.

    Every election reads the same ZBGIS levels and Natural Earth countries,
    and many share an obec's rule set and addresses, so the obce read,
    simplified and rounded (:func:`base`), the countries around Slovakia
    (:func:`_add_neighbours`) and each obec's cut (:func:`address_cuts`)
    are made once. Below *directory* (``data/build/shared/geo/``) one
    subdirectory per version of the code (*code*, a digest of it with
    Python and the libraries, as the stamp of ``geo`` has them:
    :mod:`election_map_slovakia.stamp`): a run removes the others, which no
    run reads again. An entry is a pickle named by the SHA-256 of *inputs*
    (a digest of the pinned input files) and the key of what else it
    depends on; written whole (:func:`output.write_file`), it is exactly
    what a worker process returns, so a result taken from it is the one
    computed.
    """

    def __init__(self, directory: Path, code: str, inputs: str) -> None:
        """Open the cache of *code* below *directory*; see the class doc."""
        self.directory = directory / code[:32]
        self.inputs = inputs
        if directory.is_dir():
            for other in directory.iterdir():
                if other != self.directory:
                    shutil.rmtree(other)

    def entry(self, kind: str, *key: str) -> Path:
        """Return the file of the entry of *kind* with *key* (strings)."""
        digest = hashlib.sha256("\0".join([self.inputs, *key]).encode()).hexdigest()
        return self.directory / kind / f"{digest}.pickle"

    def get(self, entry: Path) -> Any:
        """Return the value of *entry*, None if there is none yet."""
        try:
            data = entry.read_bytes()
        except FileNotFoundError:
            return None
        return pickle.loads(data)

    def put(self, entry: Path, value: object) -> None:
        """Write *value* as *entry*."""
        output.write_file(entry, pickle.dumps(value, pickle.HIGHEST_PROTOCOL))


def _from_wgs84(lonlat: np.ndarray, to_wgs84: pyproj.Transformer) -> np.ndarray:
    """Return the n × 2 WGS84 points *lonlat* in EPSG:5514."""
    x, y = to_wgs84.transform(
        lonlat[:, 0], lonlat[:, 1], direction=TransformDirection.INVERSE
    )
    return np.column_stack([x, y])


def _to_wgs84(xy: np.ndarray, to_wgs84: pyproj.Transformer) -> np.ndarray:
    """Return the n × 2 EPSG:5514 points *xy* in WGS84 (lon, lat)."""
    lon, lat = to_wgs84.transform(xy[:, 0], xy[:, 1])
    return np.column_stack([lon, lat])


def read_layer(
    path: Path, prefix: str, key: str, name: str
) -> dict[str, tuple[str, shapely.Geometry]]:
    """Return code → (name, 2D geometry) for the layer *prefix* of *path*."""
    with (
        progress.stage(f"reading the {prefix} layer of {path.name}") as s,
        GeoPackage(path) as g,
    ):
        layer = g.layer(prefix)
        out = {}
        columns = [key, name, g.geometry_column(layer)]
        for code, label, blob in s.track(g.rows(layer, columns)):
            srs = srs_id(blob)
            if srs != SOURCE_SRS:
                raise GeoError(f"{path}: {layer} {code}: SRS {srs}, not {SOURCE_SRS}")
            out[str(code)] = (label, shapely.force_2d(geometry(blob)))
    return out


Ku = tuple[str, str, shapely.Geometry]
"""A k.ú. (katastrálne územie): code, name, 2D geometry."""


def read_kus(path: Path) -> dict[str, list[Ku]]:
    """Return obec → its k.ú., by code, of the ``ku`` layer of *path*.

    The k.ú. of an obec tile it, sharing its vertices, at every level.
    """
    out: dict[str, list[Ku]] = {}
    with progress.stage(f"reading the ku layer of {path.name}"), GeoPackage(path) as g:
        layer = g.layer("ku")
        columns = ["IDN5", "NM5", "IDN4", g.geometry_column(layer)]
        for code, name, obec, blob in g.rows(layer, columns):
            if srs_id(blob) != SOURCE_SRS:
                raise GeoError(f"{path}: {layer} {code}: SRS is not {SOURCE_SRS}")
            out.setdefault(str(obec), []).append(
                (str(code), name, shapely.force_2d(geometry(blob)))
            )
    return {o: sorted(kus, key=lambda k: k[0]) for o, kus in sorted(out.items())}


def obec_codes(admin: Admin) -> list[str]:
    """Return the codes of the ZBGIS obce (without the two cities), sorted."""
    return sorted(c for c, o in admin.obce.items() if o.okres is not None)


Unit = tuple[str, int]
"""A feature of the shards: obec code and council obvod (0: the whole obec)."""


def obec_levels(
    paths: Mapping[int, Path], admin: Admin, splits: Mapping[str, Split]
) -> tuple[list[Unit], dict[int, np.ndarray]]:
    """Return the base features and their geometry per level, EPSG:5514.

    The base features are the obce in the order of :func:`obec_codes`; an obec
    of *splits* by k.ú. is already its council obvody (:func:`ku_pieces`), cut
    before level 0 is simplified so that the cuts are simplified with the
    borders they meet. An obec cut by its address points is still whole here:
    :func:`cut_council` cuts it once rounded to the grid.
    """
    codes = obec_codes(admin)
    levels: dict[int, np.ndarray] = {}
    units: list[Unit] = []
    by_ku = {c: s for c, s in splits.items() if s.kus is not None}
    for lod in SHARD_LODS:
        rows = read_layer(paths[lod.level], "obec", "IDN4", "NM4")
        if sorted(rows) != codes:
            raise GeoError(f"{paths[lod.level]}: obce differ from level 0")
        kus = read_kus(paths[lod.level]) if by_ku else {}
        here: list[Unit] = []
        geometries = []
        for c in codes:
            if c not in by_ku:
                here.append((c, 0))
                geometries.append(rows[c][1])
                continue
            for n, piece in ku_pieces(c, rows[c][1], by_ku[c], kus.get(c, [])):
                here.append((c, n))
                geometries.append(piece)
        if units and here != units:
            raise GeoError(
                f"{paths[lod.level]}: the council obvody cut differently than at"
                f" level {SHARD_LODS[0].level}"
            )
        units = here
        levels[lod.level] = np.array(geometries)
    with progress.stage(f"simplifying level 0 to {DETAIL_TOLERANCE:g} m"):
        levels[0] = shapely.coverage_simplify(levels[0], DETAIL_TOLERANCE)
    return units, levels


def merge_units(units: Sequence[Unit], geometries: np.ndarray) -> np.ndarray:
    """Return the obce of *geometries* (of *units*), their pieces merged."""
    pieces: dict[str, list[Any]] = {}
    for (code, _), g in zip(units, geometries, strict=True):
        pieces.setdefault(code, []).append(g)
    return np.array(
        [
            g[0] if len(g) == 1 else shapely.coverage_union_all(g)
            for g in pieces.values()
        ]
    )


# --- council obvody within an obec (see the module doc) ----------------------

_AREA_ERROR = 1.0
"""Square metres the k.ú. of an obec may miss it by."""


@dataclass(frozen=True)
class Split:
    """How an obec is cut into its council obvody."""

    numbers: tuple[int, ...]
    approximate: bool
    """Whether the cut is drawn from the address points, not the document."""
    kus: dict[str, int] | None = None
    """k.ú. code → obvod, where the obvody are unions of k.ú."""
    regions: tuple[tuple[int, Any], ...] = ()
    """Otherwise (obvod, its area, EPSG:5514): drawn from the obvod's
    address points by street blocks, reaching beyond the obec."""
    points: Points | None = None
    """And those points, in grid units (:func:`_grid_points`): what the map
    places, made once in the cut."""
    estimated: bool = False
    """Whether the rules themselves are a guess (an estimated rule set)."""


@dataclass(frozen=True)
class Points:
    """The address points a cut is drawn from."""

    xy: np.ndarray
    """n × 2, distinct, EPSG:5514 (or grid units)."""
    unit: np.ndarray
    """The unit (obvod or okrsok) each point is drawn in."""
    addresses: tuple[tuple[tuple[int, int], ...], ...]
    """Per point (unit, addresses) of each unit its addresses are in."""


class Barriers:
    """The lines that bound street blocks, EPSG:5514, to find an obec's.

    Roads, railways and waterways of an OpenStreetMap extract
    (:func:`election_map_slovakia.basemap.barriers`), read once first asked
    for.
    """

    def __init__(self, read: Callable[[], np.ndarray], key: str) -> None:
        """Take the lines *read* returns, named by *key* (what they are read from)."""
        self._read = read
        self.key = key

    @functools.cached_property
    def _lines(self) -> tuple[np.ndarray, shapely.STRtree]:
        lines = self._read()
        return lines, shapely.STRtree(lines)

    def of(self, kus: Sequence[Ku]) -> np.ndarray:
        """Return the lines that cross the obec of *kus* (its k.ú.), in order."""
        lines, tree = self._lines
        if not kus:
            return lines[:0]
        _, hit = tree.query(np.array([g for _, _, g in kus]), predicate="intersects")
        return lines[np.unique(hit)]


Reaching = tuple[np.ndarray, dict[int, Any]]
"""The okrsky of an obvod reaching beyond it and their borders simplified per
level (:func:`_reaching_cuts`), in grid units, not rounded."""


class Cuts(NamedTuple):
    """How the obce are cut by their addresses (:func:`address_cuts`)."""

    splits: dict[str, Split]
    """Obec → its cut into council obvody."""
    okrsky: dict[str, list[Okrsok]]
    """Obec → its okrsky drawn."""
    by_obvod: list[str]
    """The obce whose rule sets give their okrsky only by obvod."""
    reaching: dict[tuple[str, int], Reaching]
    """(obec, obvod) → its okrsky reaching beyond it, where it has several."""
    okrsky_points: dict[str, Points]
    """Obec → the points of the addresses of its okrsky drawn, by okrsok, in
    grid units."""


def address_cuts(
    election_dir: Path,
    places_dir: Path,
    kus: Mapping[str, Sequence[Ku]],
    barriers: Barriers,
    councils: bool = True,
    cache: Cache | None = None,
) -> Cuts:
    """Return how the obce are cut by their addresses.

    That is obec → its cut into council obvody, for every obec with a rule
    set where the election has *councils* (else none: nothing is cut into
    obvody); obec → its okrsky, where its rule set places every address in
    one, and those of each obvod with several reaching beyond it; the
    obce whose rule sets give their okrsky only by obvod; and the points of
    the okrsky drawn.
    *election_dir* is :meth:`election_map_slovakia.config.Config.election_dir`;
    *places_dir* holds the addresses ``ems addresses`` wrote
    (:func:`election_map_slovakia.obvody.write_places`); *kus* is
    :func:`read_kus` of level 0, of the input files of *cache*; *barriers*
    the lines of the election's street blocks. Each obec is done in a
    worker process (:func:`_cut_obec`), unless *cache* has it from another
    election or run: keyed on its rule sets (:func:`rules_key`), the digest
    of its addresses file and that of its barrier lines. Those digests are
    kept too, by the lines' :attr:`Barriers.key`, so that a run with every
    cut cached reads no lines.
    """
    rule_sets = obvody.load_rule_sets(election_dir)
    council = rule_sets if councils else {}
    okrsky = obvody.okrsok_rule_sets(election_dir, rule_sets)
    by_obvod = [c for c, r in okrsky.items() if not r.okrsok_areas]
    drawn = {c: r for c, r in okrsky.items() if r.okrsok_areas}
    codes = sorted(council.keys() | drawn.keys())
    lines: dict[str, np.ndarray] = {}

    def lines_of(code: str) -> np.ndarray:
        if code not in lines:
            lines[code] = barriers.of(kus.get(code, []))
        return lines[code]

    entries: dict[str, Path] = {}
    done: dict[str, ObecCut] = {}
    if cache is not None:
        entries = _cut_entries(
            cache, codes, council, drawn, places_dir, barriers.key, lines_of
        )
        for code, entry in entries.items():
            cut = cache.get(entry)
            if cut is not None:
                done[code] = cut
    todo = [code for code in codes if code not in done]
    tasks = [
        (
            code,
            council.get(code),
            drawn.get(code),
            places_dir,
            kus.get(code, []),
            lines_of(code),
        )
        for code in todo
    ]
    # An obec takes about as long as its addresses file is large: the cities
    # take seconds, most villages a fraction of one.
    size = {code: _places_path(places_dir, code).stat().st_size for code in todo}
    for code, cut in zip(
        todo, parallel.each(_cut_obec, tasks, cost=lambda t: size[t[0]]), strict=True
    ):
        done[code] = cut
        if cache is not None:
            cache.put(entries[code], cut)
    return _gathered([(code, done[code]) for code in codes], by_obvod)


def _gathered(cuts: Iterable[tuple[str, ObecCut]], by_obvod: list[str]) -> Cuts:
    """Return the :class:`Cuts` of obec → its cut, *cuts*."""
    out = Cuts({}, {}, by_obvod, {}, {})
    for code, (split, okrsky_drawn, reaching, points) in cuts:
        if split is not None:
            out.splits[code] = split
        if okrsky_drawn is not None:
            out.okrsky[code] = okrsky_drawn
        if points is not None:
            out.okrsky_points[code] = points
        out.reaching.update(((code, n), r) for n, r in reaching.items())
    return out


def _cut_entries(
    cache: Cache,
    codes: Sequence[str],
    council: Mapping[str, obvody.RuleSet],
    drawn: Mapping[str, obvody.RuleSet],
    places_dir: Path,
    lines_key: str,
    lines_of: Callable[[str], np.ndarray],
) -> dict[str, Path]:
    """Return obec → the entry of *cache* of its cut (see :func:`address_cuts`).

    The digests of the obce's barrier lines (*lines_of*) are kept in
    *cache* too, by *lines_key*, so that a run with every cut cached reads
    no lines.
    """
    known = cache.entry("lines", lines_key)
    digests: dict[str, str] = cache.get(known) or {}
    missing = [code for code in codes if code not in digests]
    if missing:
        digests |= {code: _digest(lines_of(code)) for code in missing}
        cache.put(known, digests)
    entries = {}
    for code in codes:
        with _places_path(places_dir, code).open("rb") as f:
            places = hashlib.file_digest(f, "sha256").hexdigest()
        key = (
            rules_key(council.get(code)),
            rules_key(drawn.get(code)),
            places,
            digests[code],
        )
        entries[code] = cache.entry("cut", code, *key)
    return entries


# The fields of a rule set, and of its rules, that only record where they
# come from: no cut depends on them, and elections that reuse a rule set
# differ in them.
_PROVENANCE = {
    "date": None,
    "documents": (),
    "note": None,
    "reused": None,
    "adoption": None,
    "dating": None,
    "supplement": None,
    "okrsky_date": None,
    "okrsky_note": None,
    "okrsky_reused": None,
    "okrsky_referendum": None,
    "okrsky_dating": None,
    "okrsky_supplement": None,
    "okrsky_adoption": None,
}
_RULE_PROVENANCE = {
    "written": None,
    "inferred": False,
    "note": None,
    "supplemented": False,
}


def rules_key(rules: obvody.RuleSet | None) -> str:
    """Return what an obec's cut by *rules* depends on of them, as a string.

    The ``repr`` of the rule set without the fields that only record where
    it comes from (its documents, dates and notes): every other field, one
    added later too, is in it.
    """
    if rules is None:
        return repr(None)
    return repr(
        replace(
            rules,
            rules=tuple(replace(r, **_RULE_PROVENANCE) for r in rules.rules),
            okrsok_rules=tuple(
                replace(r, **_RULE_PROVENANCE) for r in rules.okrsok_rules
            ),
            **_PROVENANCE,
        )
    )


def rules_digest(rules: obvody.RuleSet) -> str:
    """Return the SHA-256 of :func:`rules_key` of *rules*."""
    return hashlib.sha256(rules_key(rules).encode()).hexdigest()


def _cut_obec(
    code: str,
    council: obvody.RuleSet | None,
    okrsky: obvody.RuleSet | None,
    places_dir: Path,
    kus: Sequence[Ku],
    barriers: np.ndarray,
) -> ObecCut:
    """Return the cut of obec *code* by *council* and its okrsky by *okrsky*.

    And the okrsky of each obvod with several reaching beyond it
    (:func:`okrsky_reaching`), and the points of the okrsky's addresses.
    Either rule set may be missing; where both are given they are the same
    (:func:`election_map_slovakia.obvody.okrsok_rule_sets`). *barriers* are
    the lines that cross the obec (:meth:`Barriers.of`). The okrsky of an
    obec with one council obvod are cut from the whole obec
    (:func:`whole_split`). An election without councils (a country-wide
    one) draws the okrsky of a rule set of several obvody within the whole
    obec too: the obvody only place them, so each okrsok is cut as of
    obvod 1. Where the obvody are drawn by street blocks, they and their
    okrsky are one cut (:func:`council_split`). Fails where an address is
    in no obvod or okrsok or in two, or an okrsok rule selects addresses of
    another obvod only.
    """
    rules = council or okrsky
    assert rules is not None
    to_wgs84 = transformer()
    p = _load_places(places_dir, code)
    assigned, problems, k = _assigned(rules, okrsky, p)
    within = None
    cut: dict[int, Any] = {}
    # The obvody of the council, or those that place the okrsky of a
    # country-wide vote, drawn with the okrsky in one cut where both are.
    if council is not None or (okrsky is not None and len(okrsky.seats) > 1):
        if problems:
            raise GeoError(f"{rules.name} ({code}): " + "; ".join(problems))
        within, cut = council_split(
            rules,
            p,
            assigned,
            kus,
            barriers,
            to_wgs84,
            k,
        )
    split = within if council is not None else None
    if okrsky is None or k is None:
        return split, None, {}, None
    drawn = okrsky_split(
        okrsky,
        p,
        k,
        within or whole_split(kus),
        kus,
        barriers,
        to_wgs84,
        cut,
    )
    if council is None:
        drawn = [replace(o, obvod=1) for o in drawn]
    located = ~np.isnan(p.points[:, 0])
    points = _point_votes(
        _from_wgs84(p.points[located] / 10**DECIMALS, to_wgs84),
        np.array(k)[located],
    )
    return (
        split,
        drawn,
        okrsky_reaching(drawn, to_wgs84, 10**DECIMALS),
        _grid_points(points, to_wgs84, 10**DECIMALS),
    )


def _assigned(
    rules: obvody.RuleSet, okrsky: obvody.RuleSet | None, p: obvody.ObecPlaces
) -> tuple[list[int], list[str], list[int] | None]:
    """Return the obvod of each address of *p* by *rules*, its problems, and the okrsok.

    The okrsok by *okrsky*, if given (else None). As ``ems addresses``
    assigned them, checked, where the file holds them by these rule sets
    (:attr:`election_map_slovakia.obvody.ObecPlaces.obvody`): assigning
    them again took some 3 % of the cuts. Fails where an address is in no
    okrsok or in two, or an okrsok rule selects addresses of another obvod
    only.
    """
    stored = p.obvody
    if stored is not None and stored.rules == rules_digest(rules):
        if okrsky is None:
            return stored.units, [], None
        if p.okrsky is not None and p.okrsky.rules == rules_digest(okrsky):
            return stored.units, [], p.okrsky.units
    planar = p.planar()
    a = obvody.assign(rules, p.places, p.kus, planar)
    if okrsky is None:
        return a.units, a.problems(p.places), None
    k = obvody.assign_okrsky(okrsky, p.places, a.units, p.kus, planar)
    problems = k.problems(p.places)
    if problems:
        raise GeoError(f"{rules.name} ({rules.obec}), okrsky: " + "; ".join(problems))
    return a.units, a.problems(p.places), k.units


def _places_path(places_dir: Path, code: str) -> Path:
    """Return the addresses file of obec *code*, which ``ems addresses`` wrote."""
    path = places_dir / f"{code}.json"
    if not path.is_file():
        raise GeoError(f"{path} missing; run `ems addresses` first")
    return path


def _load_places(places_dir: Path, code: str) -> obvody.ObecPlaces:
    return obvody.load_places(_places_path(places_dir, code))


def _obec_area(rules: obvody.RuleSet, kus: Sequence[Ku]) -> Any:
    """Return the obec of *rules* as the union of its *kus*."""
    if not kus:
        raise GeoError(f"{rules.name} ({rules.obec}): no k.ú.")
    return shapely.coverage_union_all([g for _, _, g in kus])


def council_split(
    rules: obvody.RuleSet,
    places: obvody.ObecPlaces,
    assigned: Sequence[int],
    kus: Sequence[Ku],
    barriers: np.ndarray,
    to_wgs84: pyproj.Transformer,
    okrsky: Sequence[int] | None = None,
) -> tuple[Split, dict[int, Any]]:
    """Return how to cut an obec with *rules* (see :func:`address_cuts`).

    *assigned* is the obvod of each of *places*, *kus* the obec's k.ú.,
    *barriers* the lines that cross it (:meth:`Barriers.of`). With
    *okrsky*, the okrsok of each of *places* where they are drawn too, an
    obec cut by street blocks is cut into its okrsky, each obvod the union
    of its okrsky (:attr:`election_map_slovakia.obvody.RuleSet.okrsok_obvod`):
    one cut for both, whose obvody's borders are their okrsky's. Returns
    the okrsky's areas so drawn too, okrsok → area (EPSG:5514), else none.
    """
    numbers = tuple(rules.seats)
    located = ~np.isnan(places.points[:, 0])
    xy = _from_wgs84(places.points[located] / 10**DECIMALS, to_wgs84)
    obvod = np.array(assigned)[located]
    ku_obvod = _ku_obvody(rules, places, assigned, kus)
    if ku_obvod is not None:
        return Split(
            numbers,
            not rules.by_ku,
            _with_empty_kus(ku_obvod, kus, xy, obvod),
            estimated=rules.estimated,
        ), {}
    points = _point_votes(xy, obvod, keep=set(obvod.tolist()))
    obvod_of: Mapping[int, int] = {}
    cut = points
    if okrsky is not None:
        okrsok = np.array(okrsky)[located]
        obvod_of = rules.okrsok_obvod
        cut = _point_votes(xy, okrsok)
        # Every obvod drawn, as the council's points have it: one whose
        # houses all share points with another's keeps its largest okrsok.
        missing = set(points.unit.tolist()) - {obvod_of[u] for u in cut.unit.tolist()}
        if missing:
            keep = {
                Counter(okrsok[obvod == m].tolist()).most_common(1)[0][0]
                for m in missing
            }
            cut = _point_votes(xy, okrsok, keep)
    units = sorted(set(cut.unit.tolist()))
    obec = _obec_area(rules, kus)
    areas = (
        [obec]
        if len(units) == 1
        else list(_block_cut(obec, _with_kus(barriers, kus), cut))
    )
    present = sorted({obvod_of.get(u, u) for u in units})
    if len(present) == 1:
        # Beyond the obec at every level of detail.
        whole = shapely.box(*shapely.multipoints(points.xy).bounds).buffer(1e6)
        regions: tuple[tuple[int, Any], ...] = ((present[0], whole),)
    else:
        merged = [
            shapely.coverage_union_all(
                [
                    a
                    for u, a in zip(units, areas, strict=True)
                    if obvod_of.get(u, u) == o
                ]
            )
            for o in present
        ]
        regions = tuple(zip(present, _reaching(merged), strict=True))
    split = Split(
        numbers,
        True,
        None,
        regions,
        _grid_points(points, to_wgs84, 10**DECIMALS),
        rules.estimated,
    )
    return split, ({} if okrsky is None else dict(zip(units, areas, strict=True)))


def _point_votes(
    xy: np.ndarray, units: np.ndarray, keep: Collection[int] = ()
) -> Points:
    """Return the distinct points of the addresses at *xy* (EPSG:5514), of *units*.

    *units* are their obvod or okrsok. Entrances of a block can share a
    point, rarely across units, where the more frequent one takes it. A
    unit of *keep* outvoted at every point it has keeps the one where it
    has the most addresses, so that it is drawn (a council obvod must be:
    Veľká Ida 2022, whose Gomboš houses share their points with the
    village's).
    """
    # As np.unique(axis=0, return_inverse=True), which sorts rows as records,
    # several times slower.
    rounded = np.round(xy, 2)
    order = np.lexsort((rounded[:, 1], rounded[:, 0]))
    ordered = rounded[order]
    first = np.ones(len(order), dtype=bool)
    first[1:] = np.any(ordered[1:] != ordered[:-1], axis=1)
    keys = ordered[first]
    inverse = np.empty(len(order), dtype=int)
    inverse[order] = np.cumsum(first) - 1
    # The (point, unit) pairs and their addresses, by point, then unit: one
    # Counter per point took long in the cities.
    names, unit_index = np.unique(units, return_inverse=True)
    pair, count = np.unique(inverse * len(names) + unit_index, return_counts=True)
    point, unit = pair // len(names), names[pair % len(names)]
    # Per point the unit with the most addresses there, the lowest on a tie.
    best = np.lexsort((unit, -count, point))
    top = np.ones(len(best), dtype=bool)
    top[1:] = point[best][1:] != point[best][:-1]
    chosen = unit[best][top]
    for u in sorted(set(keep) - set(chosen.tolist())):
        mine = np.flatnonzero(unit == u)
        chosen[point[mine[np.lexsort((point[mine], -count[mine]))[0]]]] = u
    bounds = [0, *(np.flatnonzero(np.diff(point)) + 1).tolist(), len(point)]
    pairs = list(zip(unit.tolist(), count.tolist(), strict=True))
    addresses = tuple(tuple(pairs[s:e]) for s, e in itertools.pairwise(bounds) if e > s)
    return Points(keys, chosen, addresses)


HOUSE_REACH = 50.0
"""How far from its address points the land of a mixed or sparse street
block is theirs, in metres: a house and its yard. The rest of such a block
(the fields behind the houses of a village street, the forest around a few
cottages) is empty land; a settled block with the addresses of one unit is
that unit's whole."""
SPARSE_SHARE = 0.1
"""A street block whose address points' reach (:data:`HOUSE_REACH`) covers
less than this share of it is sparse: a forest or field with a few cottages,
which go to their unit with their reach only, so that they do not take the
hillside. Chosen on the hilly obce cut into several units (Brezno, Tisovec,
Čierny Balog, Skalité): below 0.1 a few cottages still took the forest
blocks around them; at 0.2 settled blocks of scattered villages became
islands of house discs in another unit's land."""
ISLAND_REACH = 25.0
"""Reach, in metres, of the address points of an island of sparse blocks
(cottages of one unit amid another's land, :func:`_plotted`): drawn as the
land within this of each, or of the line from it to its block's border if
that is within :data:`HOUSE_REACH` (a plot along its road), rather than
the discs of :data:`HOUSE_REACH` that decided where the land around goes,
a hundred metres across in a forest."""
_REACH_CELL = 25.0
"""Side of the cells, in metres, whose points of a block one stands for in
drawing their reach: off by at most 18 m, so every point stays well within
it. A cell is within the reach of its points (35 m across), so the cells
wholly within a block are the least of its reach."""
NARROW = 15.0
"""Width, in metres, under which street blocks and their faces are cut
across where lines meet their border (:func:`_narrow_cuts`): the strip
between a street and a path beside it, the tail of a block between two
roads that meet; each piece then goes its own way, rather than the unit of
one end reaching along it as a spike. An empty block narrower than this on
average, a corridor (a dual carriageway, a railway beside a road), is cut
where up to twice as wide."""
_PINCH = 3.0
"""Width, in metres, under which an empty face is cut across from any vertex
(:func:`_narrow_cuts`): a strip under two grid units of the map, between
two parts of a unit, would fold when rounded."""
THIN_FACE = 10.0
"""Mean width (twice the area over the perimeter), in metres, under which
an empty face goes to the unit it shares the most border with by a bare
majority, not :data:`SMOOTH_MAJORITY`: a strip that would be a spike of
either unit."""
SMOOTH_ROUNDS = 10
SMOOTH_MAJORITY = 2.0
"""Once every face of a cut has a unit, at most :data:`SMOOTH_ROUNDS` passes
over the empty ones (land without an address point) move each that shares
more than :data:`SMOOTH_MAJORITY` times as much border with another unit as
with its own to that one, so that empty land makes no spikes between two
units. A bare majority let a chain of empty blocks, about even between
two units, flip one after another into a long wedge."""
INNER_TOLERANCE = 8.0
"""Tolerance, in metres, by which the borders within street blocks (between
the houses of a mixed block, around the reach of a sparse one) are
simplified, so that they do not zigzag from house to house; those along the
street block lines by :data:`DETAIL_TOLERANCE` (:func:`_safely_simplified`).
Twice as much left more thin parts than it took zigzags."""
_SIMPLIFY_ROUNDS = 3
"""Times the borders within blocks are simplified again, keeping as they are
the segments near the points that changed sides or came too near a border
(:func:`_safely_simplified`)."""
_SLIVER = 1e-4
"""Mean width (twice the area over the perimeter), in metres, up to which a
part an opening (:func:`_opened`) takes off an area is what buffering moved
by a rounding error (some 1e-8 m), not a narrow part (:func:`_untailed`):
by width, not area, so that a short sliver centimetres wide counts."""
_CLEARANCE = 1.0
"""Distance, in metres, from the borders that simplifying keeps an address
point at, or as far as it was if nearer: rounding the borders to the map's
grid (1e-5°, 0.74 × 1.11 m) moves them by up to half a grid unit's diagonal,
so that a point simplified a few centimetres inside its unit is drawn
outside it."""


class _Faces(NamedTuple):
    """The faces a cut by street blocks assigns (:func:`_block_faces`)."""

    faces: np.ndarray
    """Polygons, EPSG:5514, that share their borders vertex for vertex."""
    block: np.ndarray
    """The street block of each face."""
    sparse: np.ndarray
    """Whether the block of each face is sparse (:data:`SPARSE_SHARE`)."""
    reach: np.ndarray
    """The unit whose houses' reach in a sparse block each face is, else -1."""
    plot: np.ndarray
    """Whether each face is of the plots in that reach (:func:`_plots`)."""
    at: np.ndarray
    """The face of each address point."""


def _block_cut(area: Any, barriers: np.ndarray, points: Points) -> np.ndarray:
    """Return *area* (EPSG:5514) cut into the units of *points* by street blocks.

    The area of each unit present, in order, a coverage of *area*. *area*
    is cut into faces (:func:`_block_faces`); a face with address points
    goes to their unit, and keeps it, as do the faces of the reach of a
    sparse block's houses. The empty faces grow from those (:func:`_grown`),
    but for the faces of sparse blocks, so that empty land goes to the unit
    of the settled land around it rather than of a cottage in it; they are
    smoothed (:data:`SMOOTH_MAJORITY`, :data:`THIN_FACE`), and a piece of a
    unit that holds none of its addresses goes to the unit around it
    (:func:`_unstrayed`). The islands of cottages are drawn as their plots
    (:func:`_plotted`), and the borders simplified, keeping every point in
    its unit (:func:`_safely_simplified`).
    """
    present = sorted(set(points.unit.tolist()))
    cut = _block_faces(area, barriers, points)
    faces = cut.faces
    unit = np.full(len(faces), -1)
    held = np.zeros(len(faces), dtype=int)
    # A face holds the points of one unit, but for a point beyond *area*,
    # which goes to the nearest face: the face takes the most frequent unit
    # of its points within *area*, of those beyond if it has none.
    shapely.prepare(area)
    beyond = ~shapely.contains_xy(area, *points.xy.T)
    count = Counter(
        zip(cut.at.tolist(), beyond.tolist(), points.unit.tolist(), strict=True)
    )
    for (f, _, u), n in sorted(count.items(), key=lambda c: (c[0][1], -c[1], c[0])):
        if unit[f] < 0:
            unit[f], held[f] = u, n
    ring = (unit < 0) & (cut.reach >= 0)
    unit[ring] = cut.reach[ring]
    borders = _borders(faces)
    seeds = np.where(cut.sparse, -1, unit)
    drawn = _grown(borders, seeds if (seeds >= 0).any() else unit)
    alone = np.flatnonzero(drawn < 0)
    if len(alone):
        # A piece of *area* without addresses, touching no other: the unit
        # of the nearest face that has one.
        given = np.flatnonzero(drawn >= 0)
        _, nearest = shapely.STRtree(faces[given]).query_nearest(
            faces[alone], all_matches=False
        )
        drawn[alone] = drawn[given[nearest]]
    drawn = np.where(unit >= 0, unit, drawn)
    thin = 2 * shapely.area(faces) < THIN_FACE * shapely.length(faces)
    drawn = _smoothed(
        borders, drawn, unit < 0, np.where(thin, 1.0, SMOOTH_MAJORITY).tolist()
    )
    drawn = _unstrayed(borders, drawn, held)
    plotted = _plotted(drawn, cut, _pieces(borders, drawn, held))
    if (plotted != drawn).any():
        # Lest the land given away part a unit's piece without addresses.
        drawn = _unstrayed(borders, plotted, held)
    areas = np.array([shapely.coverage_union_all(faces[drawn == u]) for u in present])
    areas = _unpinched(_untailed(areas, points.xy), points.xy)
    # A plot's outline is simplified as the street lines are: an island
    # drawn round, not as a polygon of a few corners.
    inner = _inner_segments(faces, 2 * cut.block + cut.plot)
    return _safely_simplified(areas, points.xy, inner)


def _untailed(areas: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Return *areas* (a coverage) with their parts narrower than :data:`_PINCH` given away.

    Such a part (the tip of a wedge between two others, a strip between two
    street lines) folds when rounded to the map's grid. One without a point
    of *xy* goes to the area it shares the most border with.
    """
    points = shapely.STRtree(shapely.points(xy))
    tree = shapely.STRtree(areas)
    to: defaultdict[int, list[Any]] = defaultdict(list)
    for i, tails in enumerate(shapely.difference(areas, _opened(areas)).tolist()):
        parts = shapely.get_parts(shapely.get_parts(tails))
        parts = parts[
            (shapely.get_type_id(parts) == shapely.GeometryType.POLYGON)
            & (2 * shapely.area(parts) > _SLIVER * shapely.length(parts))
        ]
        held = points.query(parts, predicate="intersects")[0]
        for part in np.delete(parts, held).tolist():
            near = tree.query(part, predicate="intersects")
            near = near[near != i]
            if not len(near):
                continue
            shared = shapely.length(
                shapely.intersection(shapely.boundary(part), areas[near])
            )
            to[int(near[np.argmax(shared)])].append(part)
    if not to:
        return areas
    # Noded and polygonized together, the faces share their borders exactly,
    # as overlays of each area did not.
    given = np.array([p for parts in to.values() for p in parts])
    receiver = np.repeat(list(to), [len(parts) for parts in to.values()])
    faces = shapely.get_parts(
        shapely.polygonize(
            shapely.get_parts(
                shapely.union_all(
                    [_outlines(areas), _outlines(given)], grid_size=_NODING_GRID
                )
            )
        )
    )
    inner = shapely.point_on_surface(faces)
    owner = _containing(areas, inner)
    part, face = shapely.STRtree(inner).query(given, predicate="contains_properly")
    owner[face] = receiver[part]
    return np.array(
        [shapely.coverage_union_all(faces[owner == i]) for i in range(len(areas))]
    )


def _plotted(drawn: np.ndarray, cut: _Faces, pieces: dict[int, _Piece]) -> np.ndarray:
    """Return *drawn* (the unit of each face of *cut*) with the islands of cottages as plots.

    An island is a piece of a unit (*pieces*) with addresses, all of whose
    faces are of sparse blocks: cottages amid another unit's land, where
    their reach (:data:`HOUSE_REACH`) decided where the land around goes.
    It keeps the faces of their plots (:func:`_plots`); the rest goes to
    the unit it shares the most border with.
    """
    out = drawn.copy()
    for p in pieces.values():
        faces = np.array(p.faces)
        if not p.addresses or not cut.sparse[faces].all():
            continue
        around: defaultdict[int, float] = defaultdict(float)
        for q, s in p.borders.items():
            around[pieces[q].unit] += s
        if around:
            out[faces[~cut.plot[faces]]] = min(around, key=lambda o: (-around[o], o))
    return out


def _unpinched(areas: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Return *areas* (a coverage) with near parts of one area bridged.

    Where two parts of an area come within :data:`_PINCH` of each other,
    the land of others within :data:`_PINCH` of the gap between them,
    without a point of *xy*, is that area's: so narrow a gap, or strip of
    another area through it, would fold when rounded to the map's grid.
    """
    out = list(areas)
    points = shapely.points(xy)
    for i in range(len(out)):
        parts = shapely.get_parts(out[i])
        if len(parts) < _SIDES:
            continue
        one, other = shapely.STRtree(parts).query(
            parts, predicate="dwithin", distance=_PINCH
        )
        pair = one < other
        if not pair.any():
            continue
        gaps = shapely.union_all(
            shapely.buffer(
                shapely.shortest_line(parts[one[pair]], parts[other[pair]]), _PINCH
            )
        )
        # The others' land there, each's apart: their union took long.
        others = np.array([g for j, g in enumerate(out) if j != i])
        near = others[shapely.STRtree(others).query(gaps, predicate="intersects")]
        bridge = shapely.get_parts(
            polygonal(
                shapely.union_all(
                    _grid_overlay(shapely.intersection, gaps, near),
                    grid_size=_NODING_GRID,
                )
            )
        )
        held = shapely.STRtree(bridge).query(points, predicate="intersects")[1]
        bridge = np.delete(bridge, held)
        if not len(bridge):
            continue
        taken = shapely.union_all(bridge, grid_size=_NODING_GRID)
        for j, g in enumerate(out):
            out[j] = _grid_overlay(
                shapely.union if j == i else shapely.difference, g, taken
            )
    return np.array(out)


def _block_faces(area: Any, barriers: np.ndarray, points: Points) -> _Faces:
    """Return the faces *area* (EPSG:5514) is cut into, by *barriers* and *points*.

    The street blocks are the faces of the lines *barriers* within *area*
    (roads, railways, waterways and k.ú. borders, :func:`_with_kus`). A
    settled block whose address points are all of one unit is one face. A
    mixed block, of several units (a street split by house numbers), is cut
    between them by the Voronoi cells of its points; a mixed or sparse one
    (:data:`SPARSE_SHARE`) the land within :data:`HOUSE_REACH` of them from
    the rest: that is empty land (the fields behind the houses, the forest
    around the cottages), which goes by shared border like the empty
    blocks. The Voronoi lines of a settled block run across it, of a sparse
    one only within its houses' reach: no Voronoi lines over a forest. The
    blocks, then the faces, are cut across their narrow places
    (:func:`_narrow_cuts`).
    """
    edges, blocks = _street_blocks(area, barriers)
    xy = points.xy
    at = _containing(blocks, shapely.points(xy))
    rows = np.argsort(at, kind="stable")
    occupied, start = np.unique(at[rows], return_index=True)
    mine = np.split(rows, start[1:])
    index = np.repeat(np.arange(len(occupied)), [len(m) for m in mine])
    pairs = np.unique(np.column_stack([index, points.unit[rows]]), axis=0)
    mixed = np.bincount(pairs[:, 0]) > 1
    # A block's points drawn one per cell of :data:`_REACH_CELL`: a disc
    # per house took long.
    cell = np.floor(xy[rows] / _REACH_CELL)
    _, one = np.unique(np.column_stack([index, cell]), axis=0, return_index=True)
    size = shapely.area(blocks[occupied])
    shapely.prepare(blocks)
    # The reach drawn only where it cuts the block or may: mixed blocks, and
    # those whose cells (each within its points' reach) cover too little of
    # them to tell them settled; a cell is counted where its centre is in
    # the block, a third of it as if all of it might lie beyond.
    centre = (cell[one] + 0.5) * _REACH_CELL
    counted = shapely.contains_xy(blocks[occupied[index[one]]], *centre.T)
    least = np.bincount(index[one][counted], minlength=len(occupied)) * (
        _REACH_CELL**2 / 3
    )
    drawn = np.flatnonzero(mixed | (least < SPARSE_SHARE * size))
    of = np.isin(index[one], drawn)
    # On the noding grid, as the overlays that take it and the blocks: one
    # grid, so their edges meet exactly.
    reach = _grid_overlay(
        shapely.intersection,
        shapely.buffer(
            shapely.multipoints(
                xy[rows][one][of], indices=np.searchsorted(drawn, index[one][of])
            ),
            HOUSE_REACH,
            quad_segs=4,
        ),
        blocks[occupied[drawn]],
    )
    sparse = np.zeros(len(occupied), dtype=bool)
    sparse[drawn] = shapely.area(reach) < SPARSE_SHARE * size[drawn]
    split = mixed[drawn] | sparse[drawn]
    # The rest of a block narrower than :data:`_PINCH` between the reach and
    # the block's border (a house a little more than the reach from a road)
    # is the houses' too: such a strip would fold when rounded.
    within = blocks[occupied[drawn[split]]]
    reach[split] = _grid_overlay(
        shapely.difference,
        within,
        _opened(_grid_overlay(shapely.difference, within, reach[split])),
    )
    # Within the block, as the reach is.
    cuts = [_outlines(reach[split])]
    # The plots of a sparse block's houses, within their reach: all an
    # island of them keeps (:func:`_plotted`). Of every house, not of one
    # per cell: a cell's are up to its diagonal apart, more than a plot.
    loose = np.flatnonzero(sparse[drawn])
    houses = np.isin(index, drawn[loose])
    plots = _plots(
        xy[rows][houses],
        np.searchsorted(drawn[loose], index[houses]),
        blocks[occupied[drawn[loose]]],
        reach[loose],
    )
    cuts.append(_outlines(plots))
    for k, r in zip(drawn.tolist(), reach.tolist(), strict=True):
        if mixed[k]:
            m = mine[k]
            within = r if sparse[k] else blocks[occupied[k]]
            cuts.append(
                shapely.intersection(_dividing(xy[m], points.unit[m], within), within)
            )
    empty = np.ones(len(blocks), dtype=bool)
    empty[occupied] = False
    corridor = np.flatnonzero(
        empty & (2 * shapely.area(blocks) < NARROW * shapely.length(blocks))
    )
    if len(corridor):
        cuts += list(_corridor_cuts(blocks[corridor], edges, cuts))
    faces, inner = _faces_in(
        shapely.union_all([*edges, *cuts], grid_size=_NODING_GRID), area
    )
    block = _containing(blocks, inner)
    at = _containing(faces, shapely.points(xy))
    empty = np.ones(len(faces), dtype=bool)
    empty[at] = False
    narrow, of = _narrow_cuts(faces, empty)
    if len(narrow):
        faces, origin = _split(faces, narrow, of)
        block = block[origin]
        at = _containing(faces, shapely.points(xy))
    is_sparse = np.zeros(len(blocks), dtype=bool)
    is_sparse[occupied] = sparse
    # The faces of a sparse block's reach: the unit of the houses nearest
    # (one, but in a mixed block), and those of their plots.
    reach_of = np.full(len(faces), -1)
    plot = np.zeros(len(faces), dtype=bool)
    candidates = np.flatnonzero(is_sparse[block])
    tree = shapely.STRtree(shapely.point_on_surface(faces[candidates]))
    plot[candidates[tree.query(plots, predicate="contains_properly")[1]]] = True
    k, face = tree.query(reach[loose], predicate="contains_properly")
    face, of = candidates[face], drawn[loose][k]
    for b in np.unique(of).tolist():
        m, these = mine[b], face[of == b]
        if mixed[b]:
            _, near = shapely.STRtree(shapely.points(xy[m])).query_nearest(
                shapely.point_on_surface(faces[these]), all_matches=False
            )
            reach_of[these] = points.unit[m][near]
        else:
            reach_of[these] = points.unit[m[0]]
    return _Faces(faces, block, is_sparse[block], reach_of, plot, at)


def _street_blocks(area: Any, barriers: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the lines *barriers* within *area* noded with its border, and the street blocks.

    The blocks are the faces of those lines within *area* (:func:`_faces_in`).
    """
    shapely.prepare(area)
    # Not clipped to *area*, which took longer than noding them whole: the
    # faces beyond it are left out.
    lines = barriers[shapely.intersects(area, barriers)]
    edges = shapely.get_parts(
        shapely.union_all(
            [shapely.boundary(area), *shapely.get_parts(lines)],
            grid_size=_NODING_GRID,
        )
    )
    blocks, _ = _faces_in(edges, area)
    return edges, blocks


def _plots(
    xy: np.ndarray, block: np.ndarray, blocks: np.ndarray, reach: np.ndarray
) -> np.ndarray:
    """Return the plots of the points *xy* in each of *blocks*, within its *reach*.

    *block* is the index of the block of each point, in order. A point's
    plot is the land within :data:`ISLAND_REACH` of it, or of the line from
    it to the nearest point of its block's border if that is within
    :data:`HOUSE_REACH`: a cottage's plot along its road. Strips of the
    reach beside the plots narrower than :data:`_PINCH` are theirs too.
    """
    if not len(xy):
        return np.array([], dtype=object)
    near = shapely.get_coordinates(
        shapely.get_point(
            shapely.shortest_line(shapely.points(xy), shapely.boundary(blocks[block])),
            1,
        )
    )
    near = np.where((np.hypot(*(near - xy).T) > HOUSE_REACH)[:, None], xy, near)
    # A line of no length is buffered as its point.
    plots = shapely.intersection(
        shapely.buffer(
            shapely.multilinestrings(
                shapely.linestrings(np.stack([xy, near], axis=1)), indices=block
            ),
            ISLAND_REACH,
            quad_segs=4,
        ),
        reach,
    )
    plots = _polygonals(plots)
    return _grid_overlay(
        shapely.difference,
        reach,
        _opened(_grid_overlay(shapely.difference, reach, plots)),
    )


def _opened(polygons: Any) -> Any:
    """Return *polygons* without their parts narrower than :data:`_PINCH`."""
    return shapely.buffer(
        shapely.buffer(polygons, -_PINCH / 2, join_style="mitre"),
        _PINCH / 2,
        join_style="mitre",
    )


def _polygonals(geometries: np.ndarray) -> np.ndarray:
    """Return the polygons of each of *geometries* (:func:`polygonal`).

    The parts of all at once: :func:`polygonal` of each took long.
    """
    parts, index = shapely.get_parts(geometries, return_index=True)
    parts, part = shapely.get_parts(parts, return_index=True)
    index = index[part]
    polygons = shapely.get_type_id(parts) == shapely.GeometryType.POLYGON
    out = np.empty(len(geometries), dtype=object)
    shapely.multipolygons(parts[polygons], indices=index[polygons], out=out)
    for i in np.flatnonzero(shapely.is_missing(out)).tolist():
        out[i] = shapely.multipolygons(parts[:0])
    return out


def _grid_overlay(overlay: Callable[..., Any], a: Any, b: Any) -> Any:
    """Return *overlay* (a shapely set operation) of areas *a* and *b* on the noding grid.

    Polygons only: snapped to the grid, the tip of a part narrower than a
    grid unit (a sliver between two nearly parallel lines) collapses into a
    line, and an overlay takes no input with lines and polygons. Invalid
    input is repaired first (:func:`_repaired`).
    """
    out = overlay(_repaired(a), _repaired(b), grid_size=_NODING_GRID)
    return _polygonals(out) if isinstance(out, np.ndarray) else polygonal(out)


def _repaired(polygons: Any) -> Any:
    """Return *polygons* (one or an array), each invalid one made valid.

    A mitred buffer (:func:`_opened`) may return a ring that crosses itself
    by a rounding error where it touched itself (two vertices 1e-15 m
    apart), which an overlay fails on, snapped to the grid or not.
    """
    valid = shapely.is_valid(polygons)
    if np.all(valid):
        return polygons
    if not isinstance(polygons, np.ndarray):
        return shapely.make_valid(polygons, method="structure", keep_collapsed=False)
    out = polygons.copy()
    out[~valid] = shapely.make_valid(
        polygons[~valid], method="structure", keep_collapsed=False
    )
    return out


def _outlines(polygons: np.ndarray) -> Any:
    """Return the boundaries of the polygons of *polygons*, as one geometry.

    An overlay may return a collection with lines and points, whose
    boundary is none.
    """
    parts = shapely.get_parts(shapely.get_parts(polygons))
    return shapely.multilinestrings(
        shapely.get_parts(
            shapely.boundary(
                parts[shapely.get_type_id(parts) == shapely.GeometryType.POLYGON]
            )
        )
    )


def _corridor_cuts(
    corridors: np.ndarray, edges: np.ndarray, cuts: Sequence[Any]
) -> np.ndarray:
    """Return lines across the empty blocks *corridors* where other lines meet them.

    A corridor (an empty block narrower than :data:`NARROW` on average: a
    dual carriageway, a railway beside a road, a street and a path beside
    it) runs along the land of several units: it is cut across where the
    land beside it may change, where three of the noded *edges* meet on its
    border or one of the *cuts* within a block beside it ends there; to the
    nearest point across, up to twice :data:`NARROW` away (across as in
    :func:`_narrow_cuts`), or a vertex within half that way of it, so that
    two such points facing each other give one line. Its faces are cut
    across their own narrow places later (:func:`_narrow_cuts`).
    """
    ends = _ends(edges)
    key, count = np.unique(_grid_keys(ends), return_index=True, return_counts=True)[1:]
    sites = np.concatenate([ends[key[count > _SIDES]], _ends(cuts)])
    rings, corridor = shapely.get_rings(corridors, return_index=True)
    xy, ring = shapely.get_coordinates(rings, return_index=True)
    along = np.flatnonzero((ring[:-1] == ring[1:]) & np.any(xy[:-1] != xy[1:], axis=1))
    a, b = xy[along], xy[along + 1]
    length = np.hypot(*(b - a).T)
    ring_of = ring[along]
    first = np.flatnonzero(np.r_[True, ring_of[1:] != ring_of[:-1]])
    start = np.cumsum(length) - length
    start -= np.repeat(start[first], np.diff(np.r_[first, len(along)]))
    perimeter = np.zeros(len(rings))
    np.add.at(perimeter, ring_of, length)
    tree = shapely.STRtree(shapely.linestrings(np.stack([a, b], axis=1)))
    # The segments each site is on, and where along them. Queried by boxes,
    # the distances measured here: the tree's distance predicate took long.
    j, s = tree.query(_squares(sites, _NODING_GRID))
    f = _along(sites[j], a[s], b[s])
    on = np.hypot(*(a[s] + f[:, None] * (b[s] - a[s]) - sites[j]).T) <= _NODING_GRID
    j, s, f = j[on], s[on], f[on]
    once = np.unique(
        np.column_stack([j, corridor[ring_of[s]]]), axis=0, return_index=True
    )[1]
    j, s, f = j[once], s[once], f[once]
    here = start[s] + f * length[s]
    near, t = tree.query(_squares(sites[j], 2 * NARROW))
    i = s[near]
    f = _along(sites[j[near]], a[t], b[t])
    to = a[t] + f[:, None] * (b[t] - a[t])
    gap = np.hypot(*(to - sites[j[near]]).T)
    way = np.abs(start[t] + f * length[t] - here[near])
    way = np.minimum(way, perimeter[ring_of[t]] - way)
    keep = (
        (corridor[ring_of[t]] == corridor[ring_of[i]])
        & (gap > _NODING_GRID)
        & (gap < 2 * NARROW)
        & ((ring_of[t] != ring_of[i]) | (way > 3 * gap))
    )
    near, t, f, to, gap = near[keep], t[keep], f[keep], to[keep], gap[keep]
    if not len(near):
        return np.array([], dtype=object)
    order = np.lexsort((gap, near))
    near, t, f, to, gap = near[order], t[order], f[order], to[order], gap[order]
    best = np.r_[True, near[1:] != near[:-1]]
    near, t, f, to, gap = near[best], t[best], f[best], to[best], gap[best]
    end = np.where((2 * f < 1)[:, None], a[t], b[t])
    to = np.where((np.hypot(*(to - end).T) < gap / 2)[:, None], end, to)
    lines = shapely.linestrings(np.stack([sites[j[near]], to], axis=1))
    of = corridor[ring_of[t]]
    pair = np.sort(
        np.column_stack([_grid_keys(sites[j[near]]), _grid_keys(to)]), axis=1
    )
    once = np.unique(pair, axis=0, return_index=True)[1]
    lines, of = lines[once], of[once]
    shapely.prepare(corridors)
    inside = shapely.covers(corridors[of], lines) & shapely.contains_properly(
        corridors[of], shapely.line_interpolate_point(lines, 0.5, normalized=True)
    )
    return lines[inside]


def _ends(lines: Any) -> np.ndarray:
    """Return the first and last points of the parts of *lines*, n × 2."""
    xy, part = shapely.get_coordinates(shapely.get_parts(lines), return_index=True)
    last = np.flatnonzero(np.r_[part[1:] != part[:-1], True])
    return np.concatenate([xy[np.r_[0, last[:-1] + 1]], xy[last]]) if len(xy) else xy


def _along(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return where along each segment a→b the point of it nearest to *p* is, 0 to 1."""
    d = b - a
    square = np.einsum("ij,ij->i", d, d)
    return np.clip(
        np.einsum("ij,ij->i", p - a, d) / np.where(square > 0, square, 1), 0, 1
    )


def _squares(xy: np.ndarray, half: Any) -> np.ndarray:
    """Return squares around the points *xy*, *half* (one or one each) from each side.

    A tree queried by them, the distances then measured, takes far less
    than its distance predicate.
    """
    h = np.reshape(half, (-1, 1)) if np.ndim(half) else half
    return shapely.box(*(xy - h).T, *(xy + h).T)


def _grid_keys(xy: np.ndarray) -> np.ndarray:
    """Return a key of each point *xy* (EPSG:5514) on the noding grid."""
    return _keys(np.round(xy / _NODING_GRID).astype(np.int64))


def _narrow_cuts(faces: np.ndarray, empty: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return lines across *faces* at their narrow places, and the face of each.

    From each vertex of a face where three or more segments of the faces'
    borders end (where another border meets it) to the nearest vertex of
    its border across, if nearer than :data:`NARROW`, twice that in an
    *empty* face narrower than that on average (a corridor). Across is
    farther along the border, either way, than three times as far straight,
    or on another ring. Between vertices, a face so cut gains none on its
    border. Each line lies within its face.
    """
    rings, face = shapely.get_rings(faces, return_index=True)
    xy, ring = shapely.get_coordinates(rings, return_index=True)
    key = _grid_keys(xy)
    along = np.flatnonzero((ring[:-1] == ring[1:]) & (key[:-1] != key[1:]))
    length = np.hypot(*(xy[along + 1] - xy[along]).T)
    # Where along its ring each vertex is (but the closing one), and the
    # ring's length.
    ring_of = ring[along]
    first = np.flatnonzero(np.r_[True, ring_of[1:] != ring_of[:-1]])
    start = np.cumsum(length) - length
    start -= np.repeat(start[first], np.diff(np.r_[first, len(along)]))
    perimeter = np.zeros(len(rings))
    np.add.at(perimeter, ring_of, length)
    owner = face[ring_of]
    a, b = key[along], key[along + 1]
    segments, _ = _unique_rows(np.column_stack([np.minimum(a, b), np.maximum(a, b)]))
    vertex, count = np.unique(segments, return_counts=True)
    junction = np.isin(a, vertex[count > _SIDES])
    mean = 2 * shapely.area(faces) < NARROW * shapely.length(faces)
    limit = np.where(empty & mean, 2 * NARROW, NARROW)
    # An empty face is cut at a pinch from any vertex too: a strip of land
    # narrower than a grid unit of the map between two parts of a unit
    # would fold when rounded.
    source = np.flatnonzero(junction | empty[owner])
    half = np.where(junction[source], limit[owner[source]], _PINCH)
    p = xy[along]
    # Each face's vertices moved apart from the others', so that the tree
    # gives the pairs within a face only: a vertex is on the rings of every
    # face around it, and the pairs across faces were most of those given.
    apart = p.copy()
    apart[:, 0] += owner * (np.ptp(p[:, 0]) + 4 * NARROW) if len(p) else 0
    near, to = shapely.STRtree(shapely.points(apart)).query(
        _squares(apart[source], half)
    )
    i = source[near]
    gap = np.hypot(*(p[to] - p[i]).T)
    way = np.abs(start[to] - start[i])
    way = np.minimum(way, perimeter[ring_of[i]] - way)
    keep = (
        (owner[to] == owner[i])
        & (gap > _NODING_GRID)
        & (gap < half[near])
        & ((ring_of[to] != ring_of[i]) | (way > 3 * gap))
    )
    i, to, gap = i[keep], to[keep], gap[keep]
    if not len(i):
        return np.array([], dtype=object), np.array([], dtype=int)
    # The nearest across of each junction, each pair once.
    order = np.lexsort((gap, i))
    i, to = i[order], to[order]
    best = np.r_[True, i[1:] != i[:-1]]
    pair = np.unique(np.sort(np.column_stack([i[best], to[best]]), axis=1), axis=0)
    lines = shapely.linestrings(np.stack([p[pair[:, 0]], p[pair[:, 1]]], axis=1))
    of = owner[pair[:, 0]]
    shapely.prepare(faces)
    inside = shapely.covers(faces[of], lines) & shapely.contains_properly(
        faces[of], shapely.line_interpolate_point(lines, 0.5, normalized=True)
    )
    return lines[inside], of[inside]


def _split(
    faces: np.ndarray, lines: np.ndarray, of: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return *faces* with those of *of* cut by *lines*, and the face each comes from.

    Each line lies within its face and ends at vertices of it, so that the
    pieces share their borders with the faces around vertex for vertex.
    """
    cut = np.unique(of)
    pieces = shapely.get_parts(
        shapely.polygonize(
            shapely.get_parts(
                shapely.union_all([*shapely.boundary(faces[cut]), *lines])
            )
        )
    )
    # Polygonized, the holes of the faces cut are pieces too: left out.
    face, piece = shapely.STRtree(shapely.point_on_surface(pieces)).query(
        faces[cut], predicate="contains_properly"
    )
    kept = np.ones(len(faces), dtype=bool)
    kept[cut] = False
    origin = np.concatenate([np.flatnonzero(kept), cut[face]])
    return np.concatenate([faces[kept], pieces[piece]]), origin


def _dividing(xy: np.ndarray, units: np.ndarray, block: Any) -> Any:
    """Return the edges between Voronoi cells of points *xy* of different *units*.

    Over *block* at least; a line where two units' houses meet.
    """
    cells = shapely.get_parts(
        shapely.voronoi_polygons(shapely.multipoints(xy), extend_to=block, ordered=True)
    )
    if len(cells) != len(xy):
        raise GeoError(f"{len(cells)} Voronoi cells for {len(xy)} points")
    segments, cell, one, other = _twin_segments(cells)
    between = one[units[cell[one]] != units[cell[other]]]
    return shapely.multilinestrings(
        shapely.linestrings(segments[between].reshape(-1, 2, 2))
    )


def _with_kus(barriers: np.ndarray, kus: Sequence[Ku]) -> np.ndarray:
    """Return *barriers* and the borders of the obec's *kus*, which bound blocks too."""
    return np.concatenate(
        [barriers, shapely.boundary(np.array([g for _, _, g in kus]))]
    )


def _faces_in(edges: Any, area: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return the faces of the noded *edges* (lines) within *area*, and a point in each."""
    faces = shapely.get_parts(shapely.polygonize(shapely.get_parts(edges)))
    inner = shapely.point_on_surface(faces)
    shapely.prepare(area)
    keep = shapely.intersects(area, inner)
    # Noding bends *area*'s border by a fraction of a grid unit, so a thin
    # face along it can have its point just beyond: kept if mostly within.
    doubt = np.flatnonzero(~keep)
    doubt = doubt[shapely.intersects(area, faces[doubt])]
    keep[doubt] = (
        shapely.area(shapely.intersection(faces[doubt], area))
        > shapely.area(faces[doubt]) / 2
    )
    return faces[keep], inner[keep]


def _containing(areas: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Return the index of the one of *areas* each of *points* is within.

    A point on the border between two is within none: it gets the nearest.
    """
    found = np.full(len(points), -1)
    # The areas queried, prepared: the points queried took far longer.
    area, point = shapely.STRtree(points).query(areas, predicate="contains_properly")
    found[point] = area
    lost = np.flatnonzero(found < 0)
    if len(lost):
        found[lost] = _nearest(shapely.STRtree(areas), points[lost])
    return found


def _grown(borders: Sequence[tuple[int, int, float]], unit: np.ndarray) -> np.ndarray:
    """Return the unit of each face, those without one (-1) given one.

    *borders* are those of the faces (:func:`_borders`). In rounds, each
    face without a unit takes that of the neighbours it shares the most
    border with, all as the round found them, so that the units grow over
    the empty land alike. Faces that touch no unit stay without.
    """
    around: list[list[tuple[int, float]]] = [[] for _ in unit]
    for i, j, s in borders:
        around[i].append((j, s))
        around[j].append((i, s))
    out = unit.tolist()  # Python ints, not NumPy scalars one by one
    todo = [i for i, u in enumerate(out) if u < 0]
    while todo:
        found: dict[int, int] = {}
        for i in todo:
            shared: defaultdict[int, float] = defaultdict(float)
            for j, s in around[i]:
                if out[j] >= 0:
                    shared[out[j]] += s
            if shared:
                found[i] = min(shared, key=lambda o: (-shared[o], o))
        if not found:
            break
        for i, u in found.items():
            out[i] = u
        todo = [i for i in todo if i not in found]
    return np.array(out, dtype=unit.dtype)


def _smoothed(
    borders: Sequence[tuple[int, int, float]],
    unit: np.ndarray,
    movable: np.ndarray,
    majority: Sequence[float],
) -> np.ndarray:
    """Return the unit of each face, smoothed (see :data:`SMOOTH_ROUNDS`).

    *borders* are those of the faces (:func:`_borders`), *unit* the unit of
    each; only the *movable* faces (the empty ones) move, each to a unit it
    shares more than *majority* times as much border with as with its own.
    """
    around: list[list[tuple[int, float]]] = [[] for _ in unit]
    for i, j, s in borders:
        around[i].append((j, s))
        around[j].append((i, s))
    # Python lists and ints: indexing a NumPy array element by element in
    # these loops took most of their time.
    out = unit.tolist()
    # A face is looked at again only once a neighbour moved: else it would
    # stay as it is, as it did.
    dirty = [bool(m and near) for m, near in zip(movable.tolist(), around, strict=True)]
    for _ in range(SMOOTH_ROUNDS):
        moved = False
        for i, near in enumerate(around):
            if not dirty[i]:
                continue
            dirty[i] = False
            shared: dict[int, float] = {}
            for j, s in near:
                o = out[j]
                shared[o] = shared.get(o, 0.0) + s
            own = out[i]
            to = min(shared, key=lambda o: (-shared[o], o))
            if shared[to] > majority[i] * shared.get(own, 0.0):
                out[i] = to
                moved = True
                for j, _ in near:
                    dirty[j] = bool(movable[j])
        if not moved:
            break
    return np.array(out, dtype=unit.dtype)


def _safely_simplified(
    areas: np.ndarray, xy: np.ndarray, inner: np.ndarray
) -> np.ndarray:
    """Return the borders between *areas* (EPSG:5514) simplified, keeping *xy* in them.

    *areas* are a coverage; their outline stays as it is. The borders
    between them are simplified as lines (Douglas-Peucker, preserving their
    topology): first those along the street block lines by
    :data:`DETAIL_TOLERANCE`, each segment within that and
    :data:`_CLEARANCE` of a point of *xy* kept as it is (a simplified border
    lies within the tolerance of the one it replaces, so no point changes
    sides or comes near one); then, those fixed, the borders within the
    blocks (*inner*, the keys of their segments, :func:`_inner_segments`)
    by :data:`INNER_TOLERANCE`. A point that so left its area, or came
    nearer a border than :data:`_CLEARANCE` and than it was, keeps the inner
    segments within that tolerance of it as they are (twice that the next
    time, and so on), and they are simplified again, at most
    :data:`_SIMPLIFY_ROUNDS` times, then left as they are. Should a point
    still be so, the borders are left as they are.
    """
    if len(areas) < _SIDES:
        return areas
    outline = shapely.boundary(shapely.coverage_union_all(areas))
    arcs = shapely.get_parts(
        shapely.line_merge(
            shapely.difference(shapely.union_all(shapely.boundary(areas)), outline)
        )
    )
    vertices, arc = shapely.get_coordinates(arcs, return_index=True)
    along = np.flatnonzero(arc[:-1] == arc[1:])
    within = np.zeros(len(vertices), dtype=bool)
    within[along] = np.isin(_segment_keys(vertices[along], vertices[along + 1]), inner)
    points = shapely.points(xy)
    points_tree = shapely.STRtree(points)
    near, _, _ = _near_segments(
        points_tree,
        xy,
        vertices[along],
        vertices[along + 1],
        DETAIL_TOLERANCE + _CLEARANCE,
    )
    kept = np.zeros(len(vertices), dtype=bool)
    kept[along[near]] = kept[along[near] + 1] = True
    inside = along[within[along]]
    kept[inside] = kept[inside + 1] = True
    chains = _chains(arcs, arc, vertices, kept)
    street = [c for c, start in chains if not within[start]]
    # The outline and the borders within blocks in segments, which
    # simplifying cannot move, so that no border is simplified across them.
    ring_xy, ring = shapely.get_coordinates(
        shapely.get_parts(outline), return_index=True
    )
    on = np.flatnonzero(ring[:-1] == ring[1:])
    border = list(np.stack([ring_xy[on], ring_xy[on + 1]], axis=1))
    segments = list(np.stack([vertices[inside], vertices[inside + 1]], axis=1))
    simple = shapely.get_parts(
        _simplified_lines([*street, *border, *segments], DETAIL_TOLERANCE)
    )
    # Then those, fixed in segments, keep the borders within blocks from
    # being simplified across them; these are merged into lines, each
    # vertex where a fixed segment ends kept.
    fixed = [*border, *_segments_of_lines(simple[: len(street)])]
    lines = shapely.get_parts(
        shapely.line_merge(shapely.multilinestrings(_lines(segments)))
    )
    xy_in, line = shapely.get_coordinates(lines, return_index=True)
    lock = np.isin(_grid_keys(xy_in), _grid_keys(np.array(fixed).reshape(-1, 2)))
    step = np.flatnonzero(line[:-1] == line[1:])
    tree = shapely.STRtree(
        shapely.linestrings(np.stack([xy_in[step], xy_in[step + 1]], axis=1))
    )
    area, point = points_tree.query(areas, predicate="covers")
    before = _clearance(
        points_tree, xy, np.concatenate([arcs, shapely.get_parts(outline)])
    )
    for attempt in range(_SIMPLIFY_ROUNDS + 1):
        if attempt == _SIMPLIFY_ROUNDS or not len(step):
            lock[:] = True
        free = [c for c, _ in _chains(lines, line, xy_in, lock)]
        simple = shapely.get_parts(_simplified_lines([*free, *fixed], INNER_TOLERANCE))
        faces = shapely.get_parts(shapely.polygonize(simple))
        # Each face is one of a part of *areas*, a little moved: to the one
        # its inner point is in (overlaps took long; a face so given wrong
        # would move its points, which the check finds).
        owner = _containing(areas, shapely.point_on_surface(faces))
        out = np.array(
            [shapely.coverage_union_all(faces[owner == i]) for i in range(len(areas))]
        )
        shapely.prepare(out)
        nearer = _clearance(points_tree, xy, simple) < before - _NODING_GRID
        left = np.union1d(
            point[~shapely.covers(out[area], points[point])], np.flatnonzero(nearer)
        )
        if not len(left):
            return out
        if lock.all():
            break
        # Twice as far each time: a segment simplified away may have run
        # farther from the point than the line that replaced it.
        _, near = tree.query(
            points[left], predicate="dwithin", distance=INNER_TOLERANCE * 2**attempt
        )
        lock[step[near]] = lock[step[near] + 1] = True
    return areas


def _clearance(tree: shapely.STRtree, xy: np.ndarray, lines: np.ndarray) -> np.ndarray:
    """Return how far each point *xy* is from *lines*, at most :data:`_CLEARANCE`.

    *tree* holds the points of *xy*, in order.
    """
    _, point, gap = _near_segments(tree, xy, *_segment_ends(lines), _CLEARANCE)
    out = np.full(len(xy), _CLEARANCE)
    np.minimum.at(out, point, gap)
    return out


def _near_segments(
    tree: shapely.STRtree, xy: np.ndarray, a: np.ndarray, b: np.ndarray, distance: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (segment, point, distance) of the segments a→b within *distance* of points *xy*.

    *tree* holds the points of *xy*, in order. Queried by boxes, the
    distances measured here: the tree's distance predicate took long. The
    boxes are made of the fewer: of the segments, or of the points, then
    queried in a tree of the segments' boxes.
    """
    low, high = np.minimum(a, b), np.maximum(a, b)
    if len(a) <= len(xy):
        segment, point = tree.query(
            shapely.box(*(low - distance).T, *(high + distance).T)
        )
    else:
        point, segment = shapely.STRtree(shapely.box(*low.T, *high.T)).query(
            _squares(xy, distance)
        )
    f = _along(xy[point], a[segment], b[segment])
    gap = np.hypot(*(a[segment] + f[:, None] * (b[segment] - a[segment]) - xy[point]).T)
    near = gap <= distance
    return segment[near], point[near], gap[near]


def _chains(
    arcs: np.ndarray, arc: np.ndarray, vertices: np.ndarray, kept: np.ndarray
) -> list[tuple[np.ndarray, int]]:
    """Return the lines *arcs* split at their *kept* vertices, and where each starts.

    *vertices* and *arc* are the coordinates of *arcs* and the arc of each;
    a line is the vertices of one piece, its start an index of *vertices*.
    The ends of an arc are kept; a closed one is kept in three, so that it
    cannot fold flat either.
    """
    out = []
    starts = np.flatnonzero(np.diff(arc)) + 1
    groups = np.split(np.arange(len(arc)), starts) if len(arc) else []
    for a, rows in zip(arcs, groups, strict=True):
        cut = kept[rows]
        cut[0] = cut[-1] = True
        if a.is_closed:
            cut[[len(rows) // 3, 2 * len(rows) // 3]] = True
        at = rows[np.flatnonzero(cut)]
        out += [(vertices[s : e + 1], s) for s, e in itertools.pairwise(at.tolist())]
    return out


def _lines(coordinates: Sequence[np.ndarray]) -> np.ndarray:
    """Return linestrings of *coordinates*, each an n × 2 array."""
    if not coordinates:
        return np.array([], dtype=object)
    return shapely.linestrings(
        np.concatenate(coordinates),
        indices=np.repeat(np.arange(len(coordinates)), [len(c) for c in coordinates]),
    )


def _simplified_lines(coordinates: Sequence[np.ndarray], tolerance: float) -> Any:
    """Return lines *coordinates* simplified together by *tolerance*, keeping their topology."""
    return shapely.simplify(shapely.multilinestrings(_lines(coordinates)), tolerance)


def _segments_of_lines(lines: Any) -> list[np.ndarray]:
    """Return the segments of the parts of *lines*, each 2 × 2."""
    return list(np.stack(_segment_ends(lines), axis=1))


def _segment_ends(lines: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return the starts and ends of the segments of the parts of *lines*, n × 2 each."""
    xy, line = shapely.get_coordinates(shapely.get_parts(lines), return_index=True)
    step = np.flatnonzero(line[:-1] == line[1:])
    return xy[step], xy[step + 1]


def _segment_keys(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return a key of each segment a→b (points on the noding grid), the same either way."""
    ends = np.sort(np.column_stack([_grid_keys(a), _grid_keys(b)]), axis=1)
    return np.ascontiguousarray(ends).view(np.dtype((np.void, 16))).ravel()


def _inner_segments(faces: np.ndarray, group: np.ndarray) -> np.ndarray:
    """Return the keys of the segments between two *faces* of one *group* (:func:`_segment_keys`)."""
    segments, owner, first, second = _twin_segments(faces)
    same = first[group[owner[first]] == group[owner[second]]]
    return _segment_keys(segments[same, :2], segments[same, 2:])


def _borders(cells: np.ndarray) -> list[tuple[int, int, float]]:
    """Return (i, j, length) for each pair of *cells* that share a border.

    The cells share their borders vertex for vertex (they are polygonized
    from noded lines), so a border is the same segments on both sides.
    Cells that meet in a point share none: drawn, they are separate pieces.
    """
    segments, owner, first, second = _twin_segments(cells)
    length = np.hypot(*(segments[first, 2:] - segments[first, :2]).T)
    i, j = owner[first], owner[second]
    keep = (length > 0) & (i != j)
    low, high = np.minimum(i, j)[keep], np.maximum(i, j)[keep]
    pair, at, inverse = np.unique(
        low * len(cells) + high, return_index=True, return_inverse=True
    )
    # Summed in the order of the segments, from 0.0, as one by one; the pairs
    # in the order they first appear.
    shared = np.zeros(len(pair))
    np.add.at(shared, inverse, length[keep])
    order = np.argsort(at)
    return list(
        zip(
            (pair[order] // len(cells)).tolist(),
            (pair[order] % len(cells)).tolist(),
            shared[order].tolist(),
            strict=True,
        )
    )


def _twin_segments(
    polygons: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return the segments of the rings of *polygons* that two rings share.

    Returns every segment as [x0, y0, x1, y1], the lesser end first; the
    polygon of each; and the indexes of the two segments of each shared
    pair.
    """
    rings, polygon = shapely.get_rings(polygons, return_index=True)
    xy, ring = shapely.get_coordinates(rings, return_index=True)
    along = ring[:-1] == ring[1:]
    a, b = xy[:-1][along], xy[1:][along]
    owner = polygon[ring[:-1][along]]
    swap = ((a[:, 0] > b[:, 0]) | ((a[:, 0] == b[:, 0]) & (a[:, 1] > b[:, 1])))[:, None]
    segments = np.column_stack([np.where(swap, b, a), np.where(swap, a, b)])
    # Sorted as records by np.unique(axis=0), several times slower; lexsort
    # is stable, so twins come in the order of their polygons alike. Each
    # end a complex number, which sorts by x, then y: half the passes.
    ends = segments.view(np.complex128)
    order = np.lexsort((ends[:, 1], ends[:, 0]))
    rows = segments[order]
    twin = np.flatnonzero(np.all(rows[:-1] == rows[1:], axis=1))
    return segments, owner, order[twin], order[twin + 1]


@dataclass
class _Piece:
    """Faces of one unit that share borders, as :func:`_unstrayed` grows them."""

    unit: int
    faces: list[int] = field(default_factory=list)
    addresses: int = 0
    """The points of its unit it holds."""
    borders: defaultdict[int, float] = field(default_factory=lambda: defaultdict(float))
    """Length of border with each neighbouring piece (of another unit)."""


def _pieces(
    borders: Sequence[tuple[int, int, float]], unit: np.ndarray, held: np.ndarray
) -> dict[int, _Piece]:
    """Return the pieces of the faces of a cut (see :func:`_unstrayed`).

    Keyed by the root each gets in a union-find of the borders in order:
    the order of the pieces, and their keys, settle ties later.
    """
    if not len(unit):
        return {}
    units = unit.tolist()  # not NumPy scalars, one by one
    root = _roots(borders, units)
    of = np.array(root)
    # The faces of each piece, in order, the pieces in the order of their
    # first face; by array, not face by face.
    order = np.argsort(of, kind="stable")
    starts = np.flatnonzero(np.r_[True, of[order][1:] != of[order][:-1]])
    addresses = np.add.reduceat(held[order], starts)
    groups = np.split(order, starts[1:])
    pieces: dict[int, _Piece] = {}
    for k in np.argsort(order[starts], kind="stable").tolist():
        faces = groups[k].tolist()
        r = root[faces[0]]
        pieces[r] = _Piece(units[faces[0]], faces, int(addresses[k]))
    for i, j, s in borders:
        a, b = root[i], root[j]
        if a != b:
            pieces[a].borders[b] += s
            pieces[b].borders[a] += s
    return pieces


def _roots(borders: Sequence[tuple[int, int, float]], units: list[int]) -> list[int]:
    """Return the root of each face in a union-find of *borders* in order.

    Two faces of one of *units* that share a border are joined, the root
    of the first's tree put under that of the second's.
    """
    root = list(range(len(units)))
    for i, j, _ in borders:
        if units[i] == units[j]:
            # The root of j's tree, then of i's (halving the paths); inline,
            # as calls took most of the time.
            while root[j] != j:
                root[j] = root[root[j]]
                j = root[j]
            while root[i] != i:
                root[i] = root[root[i]]
                i = root[i]
            root[i] = j
    for i in range(len(root)):
        while root[root[i]] != root[i]:
            root[i] = root[root[i]]
    return root


def _main_pieces(pieces: dict[int, _Piece]) -> dict[int, int]:
    """Return unit → its piece (of *pieces*) that holds the most of its addresses."""
    largest: dict[int, int] = {}
    for r, p in pieces.items():
        if p.addresses > pieces[largest.setdefault(p.unit, r)].addresses:
            largest[p.unit] = r
    return largest


def _unstrayed(
    borders: Sequence[tuple[int, int, float]], unit: np.ndarray, held: np.ndarray
) -> np.ndarray:
    """Return the unit each face of a cut is drawn in.

    The faces tile the area cut, with *borders* (:func:`_borders`), each in
    unit *unit* holding *held* address points of it. A piece of a unit
    (faces that share borders) that holds none goes to the unit it shares
    the most border with, the smallest first, unless it is the unit's
    largest (by addresses held) or touches no other unit (an obec in two
    pieces). A piece that holds an address of its unit stays, whatever its
    size: every located address is drawn in its own unit.
    """
    pieces = _pieces(borders, unit, held)
    kept = set(_main_pieces(pieces).values())

    def is_stray(r: int) -> bool:
        return r not in kept and not pieces[r].addresses

    drawn = unit.copy()
    # A piece only grows, so one that is no stray never becomes one.
    queue = [(len(p.faces), r) for r, p in pieces.items() if is_stray(r)]
    heapq.heapify(queue)
    while queue:
        _, r = heapq.heappop(queue)
        if r not in pieces or not is_stray(r):
            continue
        p = pieces[r]
        around: defaultdict[int, float] = defaultdict(float)
        for q, s in p.borders.items():
            around[pieces[q].unit] += s
        if not around:
            continue
        to = min(around, key=lambda o: (-around[o], o))
        drawn[p.faces] = to
        # Now of unit *to*, it joins every piece of it that it borders.
        group = [r, *(q for q in p.borders if pieces[q].unit == to)]
        into = max(group, key=lambda q: (q in kept, pieces[q].addresses, q))
        _join(pieces, group, into, to)
        if is_stray(into):
            heapq.heappush(queue, (len(pieces[into].faces), into))
    return drawn


def _join(pieces: dict[int, _Piece], group: list[int], into: int, unit: int) -> None:
    """Merge the neighbouring *pieces* of *group* into *into*, of *unit*."""
    joined = pieces[into]
    merged: defaultdict[int, float] = defaultdict(float)
    for q in group:
        g = pieces.pop(q)
        for n, s in g.borders.items():
            if n not in group:
                del pieces[n].borders[q]
                pieces[n].borders[into] += s
                merged[n] += s
        if q != into:
            joined.faces += g.faces
            joined.addresses += g.addresses
    joined.unit = unit
    joined.borders = merged
    pieces[into] = joined


def _ku_obvody(
    rules: obvody.RuleSet,
    places: obvody.ObecPlaces,
    assigned: Sequence[int],
    kus: Sequence[Ku],
) -> dict[str, int] | None:
    """Return k.ú. code → obvod where the obvody are unions of k.ú.

    That is where the rules name k.ú., or where the addresses of every
    k.ú. are in one obvod and every obvod has a k.ú. (villages whose parts
    are their k.ú.), else None. K.ú. without addresses are left out.
    """
    code_of = {search_key(name): c for c, name, _ in kus}
    if rules.by_ku:
        named = {code_of[search_key(r.ku)]: r.unit for r in rules.rules if r.ku}
        rest = next((r.unit for r in rules.rules if r.rest), None)
        if rest is not None:
            named |= {c: rest for c, _, _ in kus if c not in named}
        return named
    per: dict[str, set[int]] = {}
    # Per name, not per address: the names repeat over the addresses.
    code_by_name = {k: code_of[search_key(k)] for k in set(places.kus) if k is not None}
    for ku, o in zip(places.kus, assigned, strict=True):
        if ku is not None:
            per.setdefault(code_by_name[ku], set()).add(o)
    if len(kus) < _SIDES or any(len(s) != 1 for s in per.values()):
        return None
    named = {c: min(s) for c, s in per.items()}
    return named if set(named.values()) == set(rules.seats) else None


def _with_empty_kus(
    named: Mapping[str, int], kus: Sequence[Ku], xy: np.ndarray, obvod: np.ndarray
) -> dict[str, int]:
    """Return *named* with every other k.ú. in the obvod of the nearest point."""
    out = dict(named)
    if len(xy):
        tree = shapely.STRtree(shapely.points(xy))
        for c, _, g in kus:
            if c not in out:
                out[c] = int(obvod[int(tree.query_nearest(g, all_matches=False)[1][0])])
    return out


def ku_pieces(
    code: str, obec: Any, split: Split, kus: Sequence[Ku]
) -> list[tuple[int, Any]]:
    """Return the council obvody of *obec* (EPSG:5514) cut by k.ú.

    *kus* are those of the obec at the same level, which tile it vertex for
    vertex, so the pieces do too. Fails unless they tile *obec*.
    """
    assert split.kus is not None
    groups: dict[int, list[Any]] = {}
    for c, _, g in kus:
        if c not in split.kus:
            raise GeoError(f"obec {code}: k.ú. {c} differs between the levels")
        groups.setdefault(split.kus[c], []).append(g)
    pieces = [(n, shapely.coverage_union_all(gs)) for n, gs in sorted(groups.items())]
    geometries = np.array([g for _, g in pieces])
    union = shapely.union_all(geometries)
    missed = shapely.symmetric_difference(union, obec).area
    if not shapely.is_valid(geometries).all() or missed > _AREA_ERROR:
        raise GeoError(
            f"obec {code}: its k.ú. do not tile it (they miss it by {missed:.1f} m²)"
        )
    return pieces


def to_grid_float(geometries: Any, to_wgs84: pyproj.Transformer, scale: int) -> Any:
    """Return EPSG:5514 *geometries* in WGS84 times *scale*, not rounded."""
    return shapely.transform(geometries, lambda xy: _to_wgs84(xy, to_wgs84) * scale)


_Point = tuple[float, float]
_Edge = tuple[_Point, _Point]
"""An edge by its end points, the lesser first."""

Bends = dict[_Edge, set[_Point]]
"""Per edge of a feature, the points snap rounding bent it through."""


def cut_council(
    units: Sequence[Unit],
    gridded: np.ndarray,
    splits: Mapping[str, Split],
    to_wgs84: pyproj.Transformer,
    scale: int,
) -> tuple[list[Unit], np.ndarray]:
    """Cut the obce of *splits* by address points into their council obvody.

    *gridded* are the features *units* rounded to the grid (:func:`to_grid`).
    Each such obec is cut along the borders of its obvody's regions
    (:func:`council_cut`), then the features bent alike
    (:func:`with_council`). Returns the features with those obce replaced by
    their pieces, in grid units.
    """
    cuts = {
        c: council_cut(c, gridded[i], splits[c], to_wgs84, scale)
        for i, (c, n) in enumerate(units)
        if not n and c in splits
    }
    numbers = {c: [n for n, _ in splits[c].regions] for c in cuts}
    return with_council(units, gridded, numbers, cuts)


def council_cut(
    code: str, obec: Any, split: Split, to_wgs84: pyproj.Transformer, scale: int
) -> tuple[list[tuple[int, Any]], Bends]:
    """Return gridded *obec* cut by *split* (drawn from address points).

    Its pieces (obvod, geometry in grid units), and the points snap rounding
    bent its edges through. The cut follows the borders of the obvody's
    regions, noded with the obec's border and rounded to the grid by snap
    rounding, so the pieces are valid as they will be drawn. Snap rounding
    bends an edge of the border through the points whose pixel it crosses:
    where a cut meets it, and vertices closer than half a unit. The points
    of *split* are in grid units of 1/*scale* degree already.
    """
    assert split.points is not None
    regions = [(n, to_grid_float(g, to_wgs84, scale)) for n, g in split.regions]
    bends: Bends = {}
    return _grid_cut(code, obec, regions, split.points, bends), bends


def with_council(
    units: Sequence[Unit],
    gridded: np.ndarray,
    numbers: Mapping[str, Sequence[int]],
    cuts: Mapping[str, tuple[list[tuple[int, Any]], Bends]],
) -> tuple[list[Unit], np.ndarray]:
    """Return the features *units* (*gridded*) with the obce *cuts* cut.

    *cuts* are :func:`council_cut` of each obec cut by address points,
    *numbers* its obvody. Every feature with an edge bent by a cut, the
    neighbour too, gets the same points (:func:`_bend`), so all stay a
    coverage that shares its vertices. Fails unless each obec's pieces tile
    it (:func:`_check_cut`).
    """
    out_units: list[Unit] = []
    out: list[Any] = []
    whole: list[tuple[str, Any, list[int]]] = []
    bends: Bends = {}
    for i, unit in enumerate(units):
        code = unit[0]
        if unit[1] or code not in cuts:
            out_units.append(unit)
            out.append(gridded[i])
            continue
        pieces, bent = cuts[code]
        for edge, points in bent.items():
            bends.setdefault(edge, set()).update(points)
        whole.append((code, gridded[i], list(range(len(out), len(out) + len(pieces)))))
        out_units += [(code, n) for n, _ in pieces]
        out += [g for _, g in pieces]
    chains = _Chains(bends)
    geometries = _bend(np.array(out), chains)
    for code, obec, rows in whole:
        _check_cut(
            code,
            _bend(np.array([obec]), chains)[0],
            [(out_units[r][1], geometries[r]) for r in rows],
            numbers[code],
        )
    return out_units, shapely.orient_polygons(geometries)


def council_geometry(
    code: str,
    obec: Any,
    split: Split,
    kus: Sequence[Ku],
    to_wgs84: pyproj.Transformer,
) -> list[tuple[int, Any]]:
    """Return the council obvody of one *obec* (EPSG:5514) as the map draws them.

    Alone, without its neighbours: (number, piece in grid units). *kus* are
    its k.ú.
    """
    scale = 10**DECIMALS
    if split.kus is not None:
        pieces = ku_pieces(code, obec, split, kus)
        grid = to_grid(np.array([g for _, g in pieces]), to_wgs84, scale)
        return [(n, g) for (n, _), g in zip(pieces, grid, strict=True)]
    units, grid = cut_council(
        [(code, 0)],
        to_grid(np.array([obec]), to_wgs84, scale),
        {code: split},
        to_wgs84,
        scale,
    )
    return [(n, g) for (_, n), g in zip(units, grid, strict=True)]


def whole_split(kus: Sequence[Ku]) -> Split:
    """Return the cut of an obec with one council obvod: obvod 1, all its *kus*."""
    return Split((1,), False, {c: 1 for c, _, _ in kus})


# --- okrsky within the council obvody (see the module doc) ---------------------


@dataclass(frozen=True)
class Okrsok:
    """An okrsok as drawn: its obvod and area (EPSG:5514)."""

    number: int
    obvod: int
    area: Any
    approximate: bool
    """Whether its border is drawn from the address points, not the document."""


def okrsky_split(
    rules: obvody.RuleSet,
    places: obvody.ObecPlaces,
    assigned: Sequence[int],
    split: Split,
    kus: Sequence[Ku],
    barriers: np.ndarray,
    to_wgs84: pyproj.Transformer,
    cut: Mapping[int, Any],
) -> list[Okrsok]:
    """Return the okrsky of an obec cut into its council obvody by *split*.

    *assigned* is the okrsok of each of *places*, *kus* the obec's k.ú.
    (EPSG:5514), *barriers* the lines that cross it (:meth:`Barriers.of`).
    An okrsok alone in its obvod is the obvod's area. The okrsky of an obvod
    with several are unions of its k.ú. where it is one and each of its k.ú.
    holds addresses of one okrsok; *cut* where the obvody were drawn by
    street blocks with their okrsky (:func:`council_split`); else drawn
    from their address points by the street blocks within the obvod, like
    the obvody (:func:`_block_cut`). Fails unless they tile the obvod. An
    okrsok whose houses all share their points with another's (a block
    split by entrance) gets no area of its own and is left out.
    """
    obec = _obec_area(rules, kus)
    located = np.flatnonzero(~np.isnan(places.points[:, 0])).tolist()
    obvod_of = rules.okrsok_obvod
    out = []
    for obvod, numbers in rules.mapped.items():
        name = f"{rules.name} ({rules.obec}), obvod {obvod}"
        if len(numbers) == 1 and numbers[0] in cut:
            out.append(Okrsok(numbers[0], obvod, cut[numbers[0]], split.approximate))
            continue
        rows = [i for i in located if obvod_of.get(assigned[i]) == obvod]
        units = np.array([assigned[i] for i in rows], dtype=int)
        missing = sorted(set(numbers) - set(units.tolist()))
        if len(numbers) > 1 and missing:
            raise GeoError(
                f"{name}: okrsky {', '.join(map(str, missing))} have no address point"
            )
        if len(numbers) > 1 and cut:
            # They tile their obvod, the union of them.
            out += [Okrsok(n, obvod, cut[n], True) for n in numbers if n in cut]
            continue
        area = (
            shapely.coverage_union_all(
                [g for c, _, g in kus if split.kus.get(c) == obvod]
            )
            if split.kus is not None
            else polygonal(shapely.intersection(dict(split.regions)[obvod], obec))
        )
        if len(numbers) == 1:
            out.append(Okrsok(numbers[0], obvod, area, split.approximate))
            continue
        xy = _from_wgs84(places.points[rows] / 10**DECIMALS, to_wgs84)
        by_ku = _ku_okrsky(places, rows, xy, units, kus, split, obvod)
        if by_ku is not None:
            groups: dict[int, list[Any]] = defaultdict(list)
            for c, _, g in kus:
                if c in by_ku:
                    groups[by_ku[c]].append(g)
            exact = all(
                r.ku or r.rest for r in rules.okrsok_rules if obvod_of[r.unit] == obvod
            )
            pieces = [(n, shapely.coverage_union_all(groups[n])) for n in numbers]
        else:
            # The blocks are noded on a grid, so the obvod they tile is too;
            # snap rounding moves its border by a fraction of a grid unit,
            # which clipping takes back.
            area = shapely.set_precision(area, _NODING_GRID)
            points = _point_votes(xy, units)
            present = sorted(set(points.unit.tolist()))
            areas = (
                [area]
                if len(present) == 1
                else [
                    polygonal(g)
                    for g in shapely.intersection(
                        _block_cut(area, _with_kus(barriers, kus), points),
                        area,
                    )
                ]
            )
            exact = False
            pieces = list(zip(present, areas, strict=True))
        _check_tiling(name, area, [g for _, g in pieces])
        out += [
            Okrsok(n, obvod, g, not exact) for n, g in pieces if not shapely.is_empty(g)
        ]
    return sorted(out, key=lambda o: o.number)


def _ku_okrsky(
    places: obvody.ObecPlaces,
    rows: Sequence[int],
    xy: np.ndarray,
    units: np.ndarray,
    kus: Sequence[Ku],
    split: Split,
    obvod: int,
) -> dict[str, int] | None:
    """Return k.ú. code → okrsok where the okrsky of *obvod* are unions of k.ú.

    That is where the obvod is a union of k.ú. (*split*) and the addresses
    *rows* (points *xy*, okrsky *units*) of each of them are in one okrsok,
    every okrsok having one; a k.ú. without addresses goes to the okrsok of
    the nearest. Else None.
    """
    if split.kus is None:
        return None
    mine = [ku for ku in kus if split.kus.get(ku[0]) == obvod]
    code_of = {search_key(name): c for c, name, _ in mine}
    per: dict[str, set[int]] = defaultdict(set)
    keys = {k: search_key(k) for k in {places.kus[i] for i in rows} if k is not None}
    for i, u in zip(rows, units.tolist(), strict=True):
        ku = places.kus[i]
        if ku is not None and keys[ku] in code_of:
            per[code_of[keys[ku]]].add(u)
    if any(len(s) != 1 for s in per.values()):
        return None
    named = {c: min(s) for c, s in per.items()}
    if set(named.values()) != set(units.tolist()):
        return None
    return _with_empty_kus(named, mine, xy, units)


def _check_tiling(name: str, area: Any, pieces: Sequence[Any]) -> None:
    """Fail unless *pieces* tile *area* (EPSG:5514) within :data:`MAX_COVERAGE_ERROR`."""
    union = shapely.union_all(pieces)
    overlap = float(shapely.area(np.array(pieces)).sum()) - union.area
    gaps = shapely.difference(area, union).area
    outside = shapely.difference(union, area).area
    if max(overlap, gaps, outside) > MAX_COVERAGE_ERROR:
        raise GeoError(
            f"{name}: the okrsky do not tile the obvod (overlap {overlap:.1f} m²,"
            f" gaps {gaps:.1f} m², outside {outside:.1f} m²)"
        )


OkrsokUnit = tuple[str, Okrsok]
"""A feature of the okrsky files: its obec, and the okrsok."""

ObecCut = tuple[Split | None, list[Okrsok] | None, dict[int, Reaching], Points | None]
"""What :func:`_cut_obec` makes of one obec."""


def okrsky_levels(
    okrsky: Mapping[str, Sequence[Okrsok]],
    reaching: Mapping[tuple[str, int], Reaching],
    units: Sequence[Unit],
    gridded: Mapping[int, np.ndarray],
    cache: Cache | None = None,
) -> tuple[list[OkrsokUnit], dict[int, np.ndarray]]:
    """Return the okrsky drawn and their geometry per level, in grid units.

    *units* and *gridded* are the shard features and geometry per level
    (:func:`grid_levels`). An okrsok alone in its obvod is the obvod's
    feature (the obec's, if the shards do not cut it); the okrsky of an
    obvod with several are cut from it like the council obvody from an obec
    (:func:`_cut_faces`), along the borders of their areas reaching beyond
    the obvod (*reaching*, :func:`okrsky_reaching`), simplified as the
    level's are (:data:`CUT_TOLERANCE`), and every feature with an edge the
    cuts bent is bent alike, so that they stay a coverage that shares its
    vertices. Each such obvod is cut in a worker process
    (:func:`_okrsky_cut`), unless *cache* has its cut (:func:`_cached_each`),
    then each level bent in one (:func:`_bent`).
    """
    row = {u: i for i, u in enumerate(units)}
    features = [(c, o) for c, os in okrsky.items() for o in os]
    groups: dict[tuple[str, int], list[int]] = defaultdict(list)
    for i, (c, o) in enumerate(features):
        groups[(c, o.obvod)].append(i)
    whole = Counter(c for c, n in groups if (c, n) not in row)
    for c, count in whole.items():
        if count > 1 or (c, 0) not in row:
            raise GeoError(f"obec {c}: okrsky in council obvody the map does not cut")
    levels = [lod.level for lod in SHARD_LODS]
    feature = {(c, n): row[(c, n)] if (c, n) in row else row[(c, 0)] for c, n in groups}
    names = [(c, o.number) for c, o in features]
    several = [(key, rows) for key, rows in groups.items() if len(rows) > 1]
    tasks = [
        (
            [names[r] for r in rows],
            {level: gridded[level][feature[key]] for level in levels},
            reaching[key],
        )
        for key, rows in several
    ]
    cuts = _cached_each(
        cache,
        "okrsky",
        _okrsky_cut,
        tasks,
        cost=lambda t: shapely.get_num_coordinates(t[2][0]).sum(),
    )
    geometries = {level: np.empty(len(names), dtype=object) for level in levels}
    bends: dict[int, dict[_Edge, set[_Point]]] = {level: {} for level in levels}
    for (_, rows), cut in zip(several, cuts, strict=True):
        for level, (pieces, bent) in cut.items():
            geometries[level][rows] = pieces
            for edge, points in bent.items():
                bends[level].setdefault(edge, set()).update(points)
    for key, rows in groups.items():
        if len(rows) == 1:
            for level in levels:
                geometries[level][rows[0]] = gridded[level][feature[key]]
    drawn = parallel.each(
        _bent, [(geometries[level], bends[level]) for level in levels]
    )
    return features, dict(zip(levels, drawn, strict=True))


def _okrsky_cut(
    names: Sequence[tuple[str, int]],
    pieces: Mapping[int, Any],
    reaching: Reaching,
) -> dict[int, tuple[list[Any], dict[_Edge, set[_Point]]]]:
    """Return the okrsky of one obvod per level, and the points the cuts bent.

    *names* are its okrsky (obec, okrsok), *pieces* its shard feature per
    level, *reaching* their areas reaching beyond it and their borders per
    level, all in grid units (see :func:`okrsky_levels`). The bends are
    those of the edges of its feature (:func:`_add_bends`).
    """
    areas, cuts = reaching
    out = {}
    for level, piece in pieces.items():
        faces, owner = _cut_faces(piece, cuts[level], areas)
        bends: dict[_Edge, set[_Point]] = {}
        _add_bends(piece, faces, bends)
        geometries = []
        for k, (c, number) in enumerate(names):
            mine = faces[owner == k]
            if not len(mine):
                raise GeoError(f"obec {c}, okrsok {number}: no area at level {level}")
            geometries.append(shapely.coverage_union_all(mine))
        out[level] = (geometries, bends)
    return out


def _bent(geometries: np.ndarray, bends: Mapping[_Edge, set[_Point]]) -> np.ndarray:
    """Return the features *geometries* bent through *bends*, oriented."""
    return shapely.orient_polygons(_bend(geometries, _Chains(bends)))


REACH = 200.0
"""How far beyond its obec (or obvod) a council obvod's (or okrsok's) area
drawn from address points is extended to cut it from the shards, in metres:
more than a coarser level's obec lies off the full detail one (ZBGIS level 2
by up to about 50 m, plus :data:`CUT_TOLERANCE`)."""
_REACH_SPACING = 10.0
"""Spacing of the points along an obec's or obvod's border that divide the
land around it among its units, in metres."""
_BESIDE = 0.05
"""Distance from a point where two units meet on that border to the points
beside it of either, in metres: a fraction of a grid unit."""

_NODING_GRID = 0.01
"""Grid the street blocks are noded on (:func:`_block_faces`), and the units
to extend them (:func:`_reaching`), in metres."""


def okrsky_reaching(
    okrsky: Sequence[Okrsok], to_wgs84: pyproj.Transformer, scale: int
) -> dict[int, Reaching]:
    """Return obvod → its okrsky reaching beyond it, of each with several.

    *okrsky* are those of one obec (EPSG:5514); the areas and their borders
    simplified per level (:func:`_reaching_cuts`) are returned in WGS84
    times *scale*, not rounded, as :func:`okrsky_levels` cuts them from the
    shards.
    """
    areas: dict[int, list[Any]] = defaultdict(list)
    for o in okrsky:
        areas[o.obvod].append(o.area)
    out = {}
    for obvod, mine in areas.items():
        if len(mine) > 1:
            regions, by_level = _reaching_cuts(mine)
            out[obvod] = (
                to_grid_float(regions, to_wgs84, scale),
                {lvl: to_grid_float(c, to_wgs84, scale) for lvl, c in by_level.items()},
            )
    return out


def _reaching_cuts(areas: Sequence[Any]) -> tuple[np.ndarray, dict[int, Any]]:
    """Return *areas* (the okrsky of an obvod) reaching beyond it, and cuts.

    The cuts are their borders simplified for each coarser level
    (:data:`CUT_TOLERANCE`), as drawn for level 0, EPSG:5514 as the areas
    (see :func:`_reaching`).
    """
    regions = _reaching(areas)
    lines = shapely.union_all(shapely.boundary(regions))
    return regions, {
        lod.level: (
            shapely.simplify(lines, CUT_TOLERANCE[lod.level])
            if lod.level in CUT_TOLERANCE
            else lines
        )
        for lod in SHARD_LODS
    }


def _reaching(areas: Sequence[Any]) -> np.ndarray:
    """Return *areas* (units that tile an obec or obvod, EPSG:5514) reaching beyond it.

    Each also gets the land within :data:`REACH` outside the obec or obvod
    nearest to it, in the Voronoi cells of points along its border, so that
    the regions are a coverage whose borders meet the obec's or obvod's only
    where the units meet there. Cut along the units' own outer borders
    instead, an obvod drawn a little apart from them was noded at every
    crossing: thousands of vertices, and bends that crossed the
    neighbours' near the border.
    """
    inside = np.array(areas)
    whole = shapely.union_all(inside, grid_size=_NODING_GRID)
    # Its outline simplified first, as buffering every vertex of it took
    # long; off by far less than the reach.
    reach = shapely.buffer(shapely.simplify(whole, _REACH_SPACING), REACH)
    border = shapely.boundary(whole)
    # A point of either unit beside each point where two meet on the border,
    # so that the line between their land beyond starts where they meet: up
    # to half the spacing apart, the two ran along the border in between,
    # where the shards' snap rounding bent them unlike the border.
    meet = shapely.get_parts(
        shapely.intersection(
            shapely.difference(
                shapely.union_all(shapely.boundary(inside), grid_size=_NODING_GRID),
                border,
            ),
            border,
        )
    )
    meet = meet[shapely.get_type_id(meet) == shapely.GeometryType.POINT]
    at = shapely.line_locate_point(border, meet)
    beside = shapely.line_interpolate_point(
        border, np.concatenate([at - _BESIDE, at + _BESIDE])
    )
    # A vertex of the border every :data:`_REACH_SPACING` along it, not
    # every one: so many sites took long to divide among.
    vertices, ring = shapely.get_coordinates(
        shapely.segmentize(shapely.get_parts(border), _REACH_SPACING),
        return_index=True,
    )
    other = ring[1:] != ring[:-1]
    step = np.hypot(*np.diff(vertices, axis=0).T)
    bucket = np.floor(np.concatenate([[0], np.cumsum(step)]) / _REACH_SPACING)
    keep = np.ones(len(vertices), dtype=bool)
    keep[1:] = (bucket[1:] != bucket[:-1]) | other
    xy = np.unique(
        np.concatenate([vertices[keep], shapely.get_coordinates(beside)]), axis=0
    )
    points = shapely.points(xy)
    okrsky = shapely.STRtree(inside)
    label = _nearest(okrsky, points)
    # The edges between the Voronoi cells of points of two units divide the
    # land beyond; the cells share their edges vertex for vertex.
    cells = shapely.get_parts(
        shapely.voronoi_polygons(
            shapely.multipoints(xy),
            extend_to=shapely.buffer(shapely.envelope(reach), REACH),
            ordered=True,
        )
    )
    segments, cell, one, other = _twin_segments(cells)
    between = one[label[cell[one]] != label[cell[other]]]
    dividing = shapely.linestrings(segments[between].reshape(-1, 2, 2))
    # Noded together on a fine grid, which keeps the noding robust, and
    # polygonized, the faces share their borders exactly; each goes to the
    # okrsok it is in, or beyond the obvod to that of the nearest point.
    edges = shapely.union_all(
        [*shapely.boundary(inside), *dividing, shapely.boundary(reach)],
        grid_size=_NODING_GRID,
    )
    faces, inner = _faces_in(edges, reach)
    within = shapely.intersects(whole, inner)
    owner = np.empty(len(faces), dtype=int)
    rows = np.flatnonzero(within)
    owner[rows] = _nearest(okrsky, inner[rows])
    rows = np.flatnonzero(~within)
    _, nearest = shapely.STRtree(points).query_nearest(inner[rows], all_matches=False)
    owner[rows] = label[nearest]
    return np.array(
        [shapely.coverage_union_all(faces[owner == i]) for i in range(len(inside))]
    )


def _nearest(tree: shapely.STRtree, points: np.ndarray) -> np.ndarray:
    """Return the index of the geometry of *tree* nearest to each of *points*.

    As ``tree.query_nearest(points, all_matches=False)``, which measures the
    distance to every candidate polygon in full, even one around the point.
    A point within :data:`_NODING_GRID` of one geometry only, the usual case
    here, is near it by a prepared query of the geometries instead.
    """
    area, point = shapely.STRtree(points).query(
        tree.geometries, predicate="dwithin", distance=_NODING_GRID
    )
    count = np.bincount(point, minlength=len(points))
    out = np.empty(len(points), dtype=int)
    alone = count[point] == 1
    out[point[alone]] = area[alone]
    rest = np.flatnonzero(count != 1)
    out[rest] = tree.query_nearest(points[rest], all_matches=False)[1]
    return out


def okrsok_properties(
    features: Sequence[OkrsokUnit], drawn: np.ndarray, scale: int
) -> list[dict[str, Any]]:
    """Return the properties of the okrsky *features*; see the module doc.

    *drawn* are their geometries at level 0 in grid units
    (:func:`okrsky_levels`), which hold their labels: an okrsok's label is
    where the map draws it, cut from its obvod's feature in the shards, not
    its area drawn from the address points, which may reach a little
    beyond the obvod as the shards draw it.
    """
    labels = np.round(label_points(drawn) / scale, DECIMALS).tolist()
    out = []
    for (c, o), label in zip(features, labels, strict=True):
        p: dict[str, Any] = {
            "obec": c,
            "okrsok": o.number,
            "obvod": o.obvod,
            "label": label,
        }
        if o.approximate:
            p["approx"] = 1
        out.append(p)
    return out


def okrsok_code(sides: Sequence[Mapping[str, Any]]) -> int:
    """Return the line code of an arc of an okrsky file; see the module doc."""
    if len(sides) < _SIDES or sides[0]["obec"] != sides[1]["obec"]:
        return FOREIGN
    a, b = sides
    code = OBEC | OKRSOK | (APPROX if "approx" in a or "approx" in b else 0)
    return code | (COUNCIL if a["obvod"] != b["obvod"] else 0)


def okrsky_path(okres: str, lod: str) -> str:
    """Return the path below ``geo/`` of the okrsky of *okres* at level *lod*."""
    return f"{OKRSKY_DIR}/{okres}/{lod}.json"


def okrsky_problems(
    properties: Sequence[Mapping[str, Any]],
    geometries: np.ndarray,
    obce: Mapping[str, Any],
    scale: int,
) -> list[str]:
    """Return where the okrsky of an obec do not tile its shard features.

    *properties* and *geometries* (grid units) are the okrsky of one level,
    *obce* obec → its shard features merged, of that level. Each obec's
    okrsky must overlap by at most :data:`MAX_COVERAGE_ERROR` and differ
    from it by at most :data:`MAX_OKRSKY_OFFSET`, each okrsok once.
    """
    m2 = _M2_PER_DEGREE2 / scale**2
    metres = math.sqrt(m2)
    problems = []
    for code, r in sorted(_rows_by(properties, lambda p: p["obec"]).items()):
        numbers = [properties[i]["okrsok"] for i in r]
        if len(set(numbers)) != len(numbers):
            problems.append(f"obec {code}: an okrsok drawn twice")
        if code not in obce:
            problems.append(f"obec {code}: not in the shards")
            continue
        g = shapely.make_valid(geometries[r])
        union = shapely.union_all(g)
        overlap = (float(shapely.area(g).sum()) - union.area) * m2
        # Gridded, an obec drawn whole may touch itself (Stupava does).
        obec = shapely.make_valid(obce[code])
        off = shapely.symmetric_difference(union, obec).area * m2
        mean = off / (obec.length * metres)
        if overlap > MAX_COVERAGE_ERROR or mean > MAX_OKRSKY_OFFSET:
            problems.append(
                f"obec {code}: the okrsky overlap by {overlap:.1f} m² and lie"
                f" {mean:.2f} m off the obec on average"
            )
    return problems


def verify_okrsky(
    files: Iterable[Mapping[str, Any]],
    shards: Iterable[Mapping[str, Any]],
    drawn: Mapping[str, Sequence[int]],
) -> list[str]:
    """Return the problems of the okrsky files of one level of detail.

    *shards* are the obce shards of that level of the same okresy, *drawn*
    the okrsky ``index.json`` says are drawn, per obec. The files must hold
    exactly those; the okrsky of each obec must tile it
    (:func:`okrsky_problems`); and the arcs drawn (all but those coded
    FOREIGN) must be exactly the borders between two okrsky of one obec,
    each once, those coded COUNCIL exactly the ones between okrsky of two
    council obvody.
    """
    level = _read_level(files)
    numbers: dict[str, list[int]] = defaultdict(list)
    for p in level.properties:
        numbers[p["obec"]].append(p["okrsok"])
    problems = [
        f"obec {c}: okrsky {sorted(numbers.get(c, []))} drawn, the index says"
        f" {sorted(drawn.get(c, []))}"
        for c in sorted(numbers.keys() | drawn.keys())
        if sorted(numbers.get(c, [])) != sorted(drawn.get(c, []))
    ]
    if not len(level.features):
        return problems
    problems += _okrsok_lines(
        level.features, level.properties, level.segments, level.codes
    )
    # Only the obce with okrsky are compared with them.
    pieces: dict[str, list[Any]] = {p["obec"]: [] for p in level.properties}
    for content in shards:
        _, g = decode(content)
        for f, piece in zip(content["features"], g, strict=True):
            mine = pieces.get(f["properties"]["id"])
            if mine is not None:
                mine.append(piece)
    areas = {
        c: shapely.union_all(shapely.make_valid(p)) for c, p in pieces.items() if p
    }
    return problems + okrsky_problems(
        level.properties, level.features, areas, level.scale
    )


def _okrsok_lines(
    features: np.ndarray,
    properties: Sequence[Mapping[str, Any]],
    segment: np.ndarray,
    code: np.ndarray,
) -> list[str]:
    """Return the problems of the lines drawn by the okrsky *features*.

    *segment* and *code* are the segments drawn and their line codes; see
    :func:`verify_okrsky`.
    """
    problems = []
    if ((code & OKRSOK) == 0).any():
        problems.append(f"{((code & OKRSOK) == 0).sum()} segments drawn of no okrsok")
    _, counts = _unique_rows(segment)
    if (counts > 1).any():
        problems.append(f"{(counts > 1).sum()} segments drawn more than once")

    def outline(key: Callable[[Mapping[str, Any]], Hashable]) -> np.ndarray:
        return _boundary_segments(_merged(features, _rows_by(properties, key).values()))

    obce = outline(lambda p: p["obec"])
    council = outline(lambda p: (p["obec"], p["obvod"]))
    every = _boundary_segments(features)
    for name, inner, flag in (
        ("okrsky", _without(every, obce), OKRSOK),
        ("council obvody", _without(council, obce), COUNCIL),
    ):
        problems += _compare(
            f"the {name} within an obec", inner, segment[(code & flag) == flag]
        )
    return problems


def _without(segments: np.ndarray, others: np.ndarray) -> np.ndarray:
    """Return the rows of the n × 2 *segments* that are not rows of *others*."""

    def rows(a: np.ndarray) -> np.ndarray:
        return np.ascontiguousarray(a, dtype=np.int64).view(np.dtype((np.void, 16)))

    return segments[~np.isin(rows(segments).ravel(), rows(others).ravel())]


_K = TypeVar("_K", bound=Hashable)


def _rows_by(
    properties: Iterable[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], _K]
) -> dict[_K, list[int]]:
    """Return each *key* of *properties* → the indexes with it, in order."""
    rows: dict[_K, list[int]] = {}
    for i, p in enumerate(properties):
        rows.setdefault(key(p), []).append(i)
    return rows


def _merged(features: np.ndarray, groups: Iterable[Sequence[int]]) -> np.ndarray:
    """Return each group of the coverage *features* merged into one geometry."""
    return np.array(
        [shapely.coverage_union_all(features[list(r)]) for r in groups], dtype=object
    )


class _Level(NamedTuple):
    """The topology files of one level of detail, decoded."""

    properties: list[Mapping[str, Any]]
    features: np.ndarray
    """Their geometries, grid units."""
    segments: np.ndarray
    """The segments drawn (all but on arcs coded FOREIGN), as sorted key pairs."""
    codes: np.ndarray
    """The line code of each segment."""
    scale: int


def _read_level(files: Iterable[Mapping[str, Any]]) -> _Level:
    properties: list[Mapping[str, Any]] = []
    geometries = [np.empty(0, dtype=object)]
    segments = [np.empty((0, 2), np.int64)]
    codes = [np.empty(0, np.int64)]
    scale = 1
    for content in files:
        arcs, g = decode(content)
        geometries.append(g)
        properties += [f["properties"] for f in content["features"]]
        scale = content["scale"]
        for xy, code in zip(arcs, content["lines"], strict=True):
            if not code & FOREIGN:
                segments.append(_segments(xy))
                codes.append(np.full(len(xy) - 1, code))
    return _Level(
        properties,
        np.concatenate(geometries),
        np.concatenate(segments),
        np.concatenate(codes),
        scale,
    )


def _grid_cut(
    code: str,
    obec: Any,
    regions: Sequence[tuple[int, Any]],
    points: Points,
    bends: dict[_Edge, set[_Point]],
) -> list[tuple[int, Any]]:
    """Return gridded *obec* cut by *regions* (grid units), one piece per obvod.

    The regions are drawn from *points* (grid units); a piece of an obvod
    that holds none of its points, a sliver the simplified and rounded cut
    leaves, goes to the obvod around it (:func:`_unstrayed`). Adds to
    *bends*, per edge of *obec*, the points snap rounding bent it through:
    the vertices of the pieces' outline in whose pixel the edge does not end.
    """
    if len(regions) == 1:
        return [(regions[0][0], obec)]
    areas = np.array([g for _, g in regions])
    faces, owner = _cut_faces(obec, shapely.union_all(shapely.boundary(areas)), areas)
    obvod = np.array([regions[i][0] for i in owner.tolist()])
    # Each point to a face of its obvod it is in, or within a pixel of:
    # rounding moves the border.
    face, seed = shapely.STRtree(shapely.points(points.xy)).query(
        faces, predicate="dwithin", distance=1.0
    )
    # Each point counted once, in the first face of its obvod the query gave
    # it (by array: a loop over the pairs took long in the cities).
    mine = np.flatnonzero(obvod[face] == points.unit[seed])
    _, first = np.unique(seed[mine], return_index=True)
    held = np.bincount(face[mine[first]], minlength=len(faces))
    obvod = _unstrayed(_borders(faces), obvod, held)
    groups: dict[int, list[Any]] = {}
    for f, n in zip(faces, obvod.tolist(), strict=True):
        groups.setdefault(n, []).append(f)
    _add_bends(obec, faces, bends)
    pieces = [(n, shapely.coverage_union_all(groups[n])) for n in sorted(groups)]
    if not shapely.is_valid(np.array([g for _, g in pieces])).all():
        raise GeoError(f"obec {code}: a council obvod is not a valid polygon")
    return pieces


def _cut_faces(
    obec: Any, lines: Any, areas: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return gridded *obec* cut by *lines*, and per face the index of its area.

    The faces are noded on the grid; each goes to the one of *areas* (grid
    units) its inner point is in, else the nearest.
    """
    # Rounding can fold an obec's border across itself; its rings are kept as
    # they are (its neighbours have the same), only what is inside is asked
    # of a valid version.
    inside = obec if shapely.is_valid(obec) else shapely.make_valid(obec)
    lines = shapely.intersection(lines, inside)
    edges = shapely.union_all([shapely.boundary(obec), lines], grid_size=1.0)
    faces, inner = _faces_in(edges, inside)
    return faces, _containing(areas, inner)


def _add_bends(obec: Any, faces: np.ndarray, bends: dict[_Edge, set[_Point]]) -> None:
    """Add to *bends* the points snap rounding bent the edges of *obec* through.

    Those are the vertices of the outline of *faces*, cut from gridded
    *obec*, in whose pixel an edge of *obec* does not end.
    """
    # Each vertex once, as a complex number: np.unique by rows took long.
    corners = shapely.get_coordinates(shapely.coverage_union_all(faces))
    outline = np.unique(corners.view(np.complex128)).view(np.float64).reshape(-1, 2)
    # The edges of every ring in one query: one per ring made the pixels of
    # the whole outline again for each.
    a, b = _segment_ends(shapely.boundary(obec))
    p, e = _crossings(a, b, outline)
    for i, k in zip(p.tolist(), e.tolist(), strict=True):
        bends.setdefault(_edge(a[k], b[k]), set()).add(tuple(outline[i]))


def _check_cut(
    code: str,
    obec: Any,
    pieces: Sequence[tuple[int, Any]],
    numbers: Sequence[int],
) -> None:
    """Fail unless *pieces* tile the gridded *obec*, one piece per obvod.

    Their outline must have exactly the vertices of *obec* (bent as its
    neighbours are), or the two would not share their border. (Bent, a
    piece may touch itself where a spike folded flat; the topology drops
    those, see :func:`rings`.)
    """
    geometries = np.array([g for _, g in pieces])
    problems = []
    if [n for n, _ in pieces] != list(numbers):
        problems.append(f"obvody {[n for n, _ in pieces]}, not {list(numbers)}")
    union = shapely.coverage_union_all(geometries)
    # As the topology sees them: a spike that the bending folded flat is
    # dropped there (`rings`), as snap rounding drops it from the pieces.
    outline = {tuple(v) for p in rings(union) for r in p for v in r.tolist()}
    border = {tuple(v) for p in rings(obec) for r in p for v in r.tolist()}
    if outline != border:
        some = sorted(outline ^ border)[:3]
        problems.append(
            f"{len(outline ^ border)} vertices of its border differ, e.g. {some}"
        )
    elif shapely.symmetric_difference(union, obec).area:
        problems.append("the pieces do not cover it")
    if problems:
        raise GeoError(
            f"obec {code}: cannot cut it into its council obvody: {'; '.join(problems)}"
        )


def _edge(a: Sequence[float], b: Sequence[float]) -> _Edge:
    p, q = (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
    return (p, q) if p < q else (q, p)


def _crossings(
    a: np.ndarray, b: np.ndarray, points: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return (point, edge) index pairs: an edge a→b through a point's pixel.

    Edges that end at the point are left out: snap rounding bends the others
    through it (its hot pixel).
    """
    if not len(a) or not len(points):
        return np.empty(0, dtype=int), np.empty(0, dtype=int)
    edges = shapely.linestrings(
        np.stack([a, b], axis=1).reshape(-1, 2), indices=np.repeat(np.arange(len(a)), 2)
    )
    half = 0.5
    boxes = shapely.box(
        points[:, 0] - half,
        points[:, 1] - half,
        points[:, 0] + half,
        points[:, 1] + half,
    )
    p, e = shapely.STRtree(edges).query(boxes, predicate="intersects")
    ends = (points[p] == a[e]).all(1) | (points[p] == b[e]).all(1)
    return p[~ends], e[~ends]


class _Chains:
    """The edges snap rounding bent, each with the points it was bent through.

    A chain is an edge's start, those points in their order along it, and
    its end.
    """

    def __init__(self, bends: Mapping[_Edge, set[_Point]]) -> None:
        self.chains: list[list[_Point]] = []
        self.where: dict[_Point, dict[int, int]] = {}
        """Point → chain → its position in it."""
        for (a, b), points in sorted(bends.items()):
            dx, dy = b[0] - a[0], b[1] - a[1]
            inner = sorted(
                points, key=lambda p: ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy, p)
            )
            for position, p in enumerate([a, *inner, b]):
                self.where.setdefault(p, {})[len(self.chains)] = position
            self.chains.append([a, *inner, b])

    def between(self, u: _Point, w: _Point) -> list[_Point]:
        """Return the points of a chain strictly between *u* and *w*, from *u*.

        Nothing if *u* and *w* follow each other in a chain: the edge is a
        piece of that bent edge already, though another chain, bent through
        the same pixels near the tip of a narrow wedge, passes both.
        """
        at_u, at_w = self.where.get(u), self.where.get(w)
        if not at_u or not at_w:
            return []
        found: list[_Point] = []
        for chain, i in at_u.items():
            j = at_w.get(chain)
            if j is None:
                continue
            if abs(j - i) == 1:
                return []
            if not found:
                points = self.chains[chain]
                found = points[i + 1 : j] if i < j else points[j + 1 : i][::-1]
        return found


def _bend(geometries: np.ndarray, chains: _Chains) -> np.ndarray:
    """Return *geometries* with every edge of a chain bent through its points.

    An edge from one point of a chain to a later (or earlier) one gets the
    points between them, so a border that two features share, whole or in
    part bent already (the pieces of a cut obec), ends up with the same
    vertices in both; not one from a point to the next in some chain: it is
    a piece of that bent edge already, though another chain, bent through
    the same pixels near the tip of a narrow wedge, passes both. A ring
    bent is cleaned (:func:`_cleaned`): a spike the bending folds flat is
    dropped, as :func:`rings` drops it (both sides alike), left in, its tip
    can be the uppermost vertex, from which the orientation of a ring is
    read; a hole so collapsed goes, an exterior with its holes. All rings
    at once: feature by feature took long.
    """
    if not chains.chains:
        return geometries
    parts, feature = shapely.get_parts(geometries, return_index=True)
    rings, part = shapely.get_rings(parts, return_index=True)
    xy, ring = shapely.get_coordinates(rings, return_index=True)
    point = np.ascontiguousarray(xy).view(np.complex128).ravel()
    # The chains' points, sorted, each with its chain and place in it.
    flat = [
        (complex(*p), c, i)
        for c, chain in enumerate(chains.chains)
        for i, p in enumerate(chain)
    ]
    known = np.array([p for p, _, _ in flat])
    order = np.argsort(known, kind="stable")
    known = known[order]
    of_chain = np.array([c for _, c, _ in flat])[order]
    place = np.array([i for _, _, i in flat])[order]
    start = np.cumsum([0, *(len(c) for c in chains.chains)])
    coords = np.array([p for chain in chains.chains for p in chain], dtype=float)
    # The edges between two chain points, each end's chains joined on the
    # edge and chain.
    edge = np.flatnonzero(ring[:-1] == ring[1:])
    low = np.searchsorted(known, point, "left")
    count = np.searchsorted(known, point, "right") - low
    edge = edge[(count[edge] > 0) & (count[edge + 1] > 0)]

    def members(end: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = count[end]
        e = np.repeat(np.arange(len(end)), n)
        row = low[end][e] + np.arange(len(e)) - np.repeat(np.cumsum(n) - n, n)
        return e * len(chains.chains) + of_chain[row], place[row]

    key_u, at_u = members(edge)
    key_w, at_w = members(edge + 1)
    both, iu, iw = np.intersect1d(key_u, key_w, return_indices=True)
    which, chain = both // len(chains.chains), both % len(chains.chains)
    i, j = at_u[iu], at_w[iw]
    # A piece of a bent edge already in any chain is not bent; else by the
    # first chain that has both ends apart.
    whole = np.ones(len(edge), dtype=bool)
    whole[which[np.abs(j - i) == 1]] = False
    apart = np.flatnonzero(whole[which] & (np.abs(j - i) > 1))
    pick = (
        apart[np.r_[True, which[apart][1:] != which[apart][:-1]]]
        if len(apart)
        else apart
    )
    edge, chain, i, j = edge[which[pick]], chain[pick], i[pick], j[pick]
    if not len(edge):
        return geometries
    # The points between, from u, after the vertex each edge starts at.
    size = np.abs(j - i) - 1
    step = np.where(j > i, 1, -1)
    k = np.repeat(np.arange(len(edge)), size)
    offset = np.arange(len(k)) - np.repeat(np.cumsum(size) - size, size) + 1
    extra = np.zeros(len(xy), dtype=int)
    extra[edge] = size
    at = np.cumsum(extra + 1) - extra - 1
    out_xy = np.empty((len(xy) + len(k), 2))
    out_xy[at] = xy
    out_xy[np.repeat(at[edge], size) + offset] = coords[
        start[chain][k] + i[k] + step[k] * offset
    ]
    out_ring = np.repeat(ring, extra + 1)
    # Each bent ring cleaned, open; the others as they are.
    bent = np.zeros(len(rings), dtype=bool)
    bent[ring[edge]] = True
    bent_count = int(bent.sum())
    closing = np.r_[out_ring[1:] != out_ring[:-1], True]
    mine = bent[out_ring] & ~closing
    cleaned, cleaned_ring = _cleaned(
        out_xy[mine], (np.cumsum(bent) - 1)[out_ring[mine]], bent_count
    )
    alive = np.ones(len(rings), dtype=bool)
    alive[bent] = np.bincount(cleaned_ring, minlength=bent_count) >= _MIN_RING
    # An exterior collapsed takes its holes, and a part without its exterior
    # goes.
    exterior = np.r_[True, part[1:] != part[:-1]]
    alive &= alive[np.flatnonzero(exterior)[np.cumsum(exterior) - 1]]
    changed = np.zeros(len(geometries), dtype=bool)
    changed[feature[part[ring[edge]]]] = True
    # The rings of the changed features, open: the unbent as they were, the
    # bent cleaned; in order (a stable sort keeps each ring's).
    plain = (
        changed[feature[part[ring]]] & ~bent[ring] & ~np.r_[ring[1:] != ring[:-1], True]
    )
    of = np.concatenate([ring[plain], np.flatnonzero(bent)[cleaned_ring]])
    order = np.argsort(of, kind="stable")
    of, vertices = of[order], np.concatenate([xy[plain], cleaned])[order]
    keep = alive[of]
    of, vertices = of[keep], vertices[keep]
    # Closed again: each ring's first vertex after its last.
    head = np.flatnonzero(np.r_[True, of[1:] != of[:-1]])
    tail = np.r_[head[1:], len(of)]
    closed = np.insert(vertices, tail, vertices[head], axis=0)
    taken = of[head]
    sizes = tail - head + 1
    ring_part = part[taken]
    new_part = np.r_[True, ring_part[1:] != ring_part[:-1]]
    polygons = shapely.from_ragged_array(
        shapely.GeometryType.POLYGON,
        closed,
        (np.r_[0, np.cumsum(sizes)], np.r_[np.flatnonzero(new_part), len(sizes)]),
    )
    owner = feature[ring_part[new_part]]
    out = geometries.copy()
    merged = np.empty(len(geometries), dtype=object)
    shapely.multipolygons(polygons, indices=owner, out=merged)
    out[changed] = merged[changed]
    # A feature of one part left is that polygon; of none, an empty one.
    single = np.flatnonzero(changed & (np.bincount(owner, minlength=len(out)) == 1))
    out[single] = polygons[np.searchsorted(owner, single)]
    for f in np.flatnonzero(changed & shapely.is_missing(out)).tolist():
        out[f] = shapely.multipolygons(polygons[:0])
    return out


def _is_obvod_contest(contest: Mapping[str, Any]) -> bool:
    return contest["kind"] == "zsk" or (
        contest["kind"] == "oz" and contest["area"] in CITY_CODES
    )


Membership = tuple[config.ObvodList, dict[int, tuple[str, ...]]]
"""A membership file and its obvody resolved to obce."""


def memberships(
    election_dir: Path,
    admin: Admin,
    contests: Iterable[Mapping[str, Any]],
    *,
    partial: bool = False,
) -> dict[str, Membership]:
    """Return file name → membership, for each kraj and city with obvod contests.

    ``zsk-<kraj>`` for a kraj with regional council contests, ``BA`` and
    ``KE`` for a city with city council contests: an election without them
    (country-wide, most by-elections) has none to load. The file must have
    as many obvody as the contests, or, *partial* (a by-election, held in
    some obvody only), have theirs. Where a contest has ``seats`` of its own
    (``candidates.json``), its obvod must have as many. All membership files
    are checked before failing, so one run lists every problem.
    """
    councils = [c for c in contests if _is_obvod_contest(c)]
    numbers: dict[str, set[int]] = defaultdict(set)
    for c in councils:
        numbers[str(c["area"])].add(int(c["obvod"]))
    stated = {
        (str(c["area"]), c["obvod"]): c["seats"] for c in councils if "seats" in c
    }
    areas = {
        f"zsk-{kraj}": (
            kraj,
            {c: o for c, o in admin.obce.items() if o.kraj == kraj and o.okres},
        )
        for kraj in sorted(admin.kraje)
    } | {
        city.code: (
            city.code,
            {c: o for c, o in admin.obce.items() if o.city == city.code},
        )
        for city in CITIES
    }
    result, errors = {}, []
    for name, (area, obce) in areas.items():
        if not numbers[area]:
            continue
        listed = config.load_obvody(election_dir / obvody.DIRECTORY / f"{name}.toml")
        expected = len(numbers[area])
        if partial:
            expected = len(listed.obvody)
            errors += [
                f"{listed.path}: no obvod {n} of the candidate lists"
                for n in sorted(numbers[area] - {o.number for o in listed.obvody})
            ]
        try:
            result[name] = (listed, obvody.resolve(listed, obce, expected))
        except obvody.ObvodyError as e:
            errors.append(str(e))
        errors += [
            f"{listed.path}: obvod {o.number} has {o.seats} seats, the candidate"
            f" lists {stated[(area, o.number)]}"
            for o in listed.obvody
            if stated.get((area, o.number), o.seats) != o.seats
        ]
    if errors:
        raise obvody.ObvodyError("\n".join(errors))
    return result


def obec_properties(
    admin: Admin,
    codes: Sequence[str],
    members: Mapping[str, Membership],
) -> dict[str, dict[str, Any]]:
    """Return obec → its shard properties without ``label``; see the module doc.

    *members* is the result of :func:`memberships`. ``zsk`` is 0 where the
    election has no regional obvody, so that every obec has one.
    """
    props: dict[str, dict[str, Any]] = {}
    for c in codes:
        o = admin.obce[c]
        props[c] = {"id": c, "name": o.name, "okres": o.okres, "kraj": o.kraj, "zsk": 0}
    for kraj in admin.kraje:
        for n, area in members.get(f"zsk-{kraj}", (None, {}))[1].items():
            for c in area:
                props[c]["zsk"] = n
    for city in CITIES:
        for n, area in members.get(city.code, (None, {}))[1].items():
            for c in area:
                props[c] |= {"city": city.code, "city_obvod": n}
    return props


def to_grid(
    geometries: np.ndarray, to_wgs84: pyproj.Transformer, scale: int
) -> np.ndarray:
    """Return EPSG:5514 *geometries* in WGS84, rounded to 1/*scale* degree.

    Coordinates are in that unit (integral), so shared vertices compare
    exactly; rings are oriented as in GeoJSON.
    """
    return shapely.orient_polygons(
        shapely.transform(
            geometries, lambda xy: np.rint(_to_wgs84(xy, to_wgs84) * scale)
        )
    )


Rings = list[list[np.ndarray]]
"""A feature's polygons, each a list of rings: open int64 vertex arrays."""


def rings(geometry: shapely.Geometry) -> Rings:
    """Return the polygons of a gridded *geometry* (see :func:`to_grid`).

    Repeated vertices and the tips of spikes folded flat are dropped (see the
    module doc), and so are rings left with fewer than three vertices.
    """
    return feature_rings([geometry])[0]


def feature_rings(geometries: Sequence[Any] | np.ndarray) -> list[Rings]:
    """Return :func:`rings` of each of *geometries*.

    The rings of all cleaned at once: ring by ring took most of the time of
    cutting the features into arcs.
    """
    polygons, feature = shapely.get_parts(
        np.asarray(geometries, dtype=object), return_index=True
    )
    shells, polygon = shapely.get_rings(polygons, return_index=True)
    xy, ring = shapely.get_coordinates(shells, return_index=True)
    # Open, without the vertex that closes each ring.
    closing = np.r_[ring[1:] != ring[:-1], True][: len(ring)]
    xy, ring = _cleaned(xy[~closing].astype(np.int64), ring[~closing], len(shells))
    bounds = np.searchsorted(ring, np.arange(len(shells) + 1)).tolist()
    owner, of = polygon.tolist(), feature.tolist()
    out: list[Rings] = [[] for _ in range(len(geometries))]
    kept: list[np.ndarray] | None = None
    for r, p in enumerate(owner):
        s, e = bounds[r], bounds[r + 1]
        if not r or owner[r - 1] != p:
            # An exterior; collapsed, its holes go with it.
            kept = [xy[s:e]] if e - s >= _MIN_RING else None
            if kept is not None:
                out[of[p]].append(kept)
        elif kept is not None and e - s >= _MIN_RING:
            kept.append(xy[s:e])
    return out


def _clean(xy: np.ndarray) -> np.ndarray:
    """Return the open ring *xy* cleaned (see :func:`_cleaned`)."""
    return _cleaned(xy, np.zeros(len(xy), dtype=np.int64), 1)[0]


def _cleaned(
    xy: np.ndarray, ring: np.ndarray, count: int
) -> tuple[np.ndarray, np.ndarray]:
    """Return the open rings *xy* cleaned, and the ring of each vertex.

    *ring* is the ring of each vertex (of *count*, in order). While a ring
    has three vertices: those equal to the one before go; then, if any is
    the tip of a spike (the vertices beside it equal), those go, and again.
    """
    active = np.ones(count, dtype=bool)
    while True:
        size = np.bincount(ring, minlength=count)
        active &= size >= _MIN_RING
        if not active.any():
            return xy, ring
        keep = ~active[ring] | np.any(xy != xy[_beside(ring, size, -1)], axis=1)
        xy, ring = xy[keep], ring[keep]
        size = np.bincount(ring, minlength=count)
        spike = active[ring] & np.all(
            xy[_beside(ring, size, -1)] == xy[_beside(ring, size, 1)], axis=1
        )
        active &= np.bincount(ring[spike], minlength=count) > 0
        xy, ring = xy[~spike], ring[~spike]


def _beside(ring: np.ndarray, size: np.ndarray, step: int) -> np.ndarray:
    """Return the index of the vertex *step* along its ring from each, round it.

    *ring* is the ring of each vertex, in order, *size* the vertices of each.
    """
    start = (np.cumsum(size) - size)[ring]
    return start + (np.arange(len(ring)) - start + step) % size[ring]


def _keys(xy: np.ndarray) -> np.ndarray:
    return ((xy[:, 0] + _OFFSET) << 32) | (xy[:, 1] + _OFFSET)


def _unique_rows(pairs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the distinct rows of the n × 2 *pairs*, sorted, and their counts.

    As ``np.unique(pairs, axis=0, return_counts=True)``, which sorts rows as
    records and takes several times longer on the vertex key pairs here.
    """
    rows = pairs[np.lexsort((pairs[:, 1], pairs[:, 0]))]
    first = np.ones(len(rows), dtype=bool)
    first[1:] = np.any(rows[1:] != rows[:-1], axis=1)
    starts = np.flatnonzero(first)
    return rows[starts], np.diff(np.append(starts, len(rows)))


@dataclass
class Topology:
    """A coverage cut into arcs, each border once."""

    arcs: list[np.ndarray]
    """Vertices (n × 2, int64) from one end of the arc to the other."""
    refs: list[list[list[list[int]]]]
    """Per feature: polygons → rings → arc indexes, ``~i`` for arc i reversed."""
    sides: list[list[int]]
    """Per arc: the feature it bounds, or the two."""


def topology(features: Sequence[Rings], scale: int) -> Topology:
    """Cut the rings of a gridded coverage into arcs; see the module doc.

    Arcs end at junctions, the vertices with other than two neighbours; a
    ring without one (an island) is one arc from its least vertex, so its
    two sides cut it alike. Fails unless every arc bounds one feature, or
    two that run along it in opposite directions as neighbours do.
    """
    flat = [
        (f, p, r, xy)
        for f, polygons in enumerate(features)
        for p, polygon in enumerate(polygons)
        for r, xy in enumerate(polygon)
    ]
    # The keys of all rings at once, each vertex's next round its ring (key
    # by key, np.roll of each, took long).
    size = np.array([len(xy) for *_, xy in flat], dtype=np.int64)
    ends = np.cumsum(size)
    a = _keys(np.concatenate([xy for *_, xy in flat]))
    after = np.arange(1, len(a) + 1)
    after[ends - 1] = ends - size
    b = a[after]
    edges, _ = _unique_rows(np.column_stack([np.minimum(a, b), np.maximum(a, b)]))
    vertex, degree = np.unique(edges, return_counts=True)
    is_junction = np.isin(a, vertex[degree != _SIDES])
    starts = ends[:-1]
    keys = np.split(a, starts)
    topo = Topology([], [[[[] for _ in p] for p in f] for f in features], [])
    index: dict[bytes, int] = {}
    ways: list[list[bool]] = []
    for (f, p, r, xy), k, junction in zip(
        flat, keys, np.split(is_junction, starts), strict=True
    ):
        at = np.flatnonzero(junction)
        start = int(at[0]) if len(at) else int(np.argmin(k))
        # From the start round, back to it.
        k = np.concatenate([k[start:], k[: start + 1]])
        xy = np.concatenate([xy[start:], xy[: start + 1]])
        for i, j in itertools.pairwise(
            [*(at - start), len(k) - 1] if len(at) else [0, len(k) - 1]
        ):
            forward = k[i : j + 1].tobytes()
            key = min(forward, k[i : j + 1][::-1].tobytes())
            arc = index.get(key)
            if arc is None:
                arc = index[key] = len(topo.arcs)
                chain = xy[i : j + 1]
                topo.arcs.append(chain if key == forward else chain[::-1])
                topo.sides.append([])
                ways.append([])
            topo.sides[arc].append(f)
            ways[arc].append(key == forward)
            topo.refs[f][p][r].append(arc if key == forward else ~arc)
    bad = [
        i
        for i, (sides, way) in enumerate(zip(topo.sides, ways, strict=True))
        if len(sides) > _SIDES
        or (len(sides) == _SIDES and (sides[0] == sides[1] or way[0] == way[1]))
    ]
    if bad:
        lon, lat = topo.arcs[bad[0]][0] / scale
        raise GeoError(
            f"{len(bad)} borders are not shared by exactly two neighbours,"
            f" e.g. at {lat:.5f}, {lon:.5f}"
        )
    return topo


def line_code(a: Mapping[str, Any], b: Mapping[str, Any] | None) -> int:
    """Return the line code of the border of units *a* and *b* (None: abroad)."""
    if b is None:
        return COUNTRY | ZSK | (CITY if "city" in a else 0)
    if "id" in a and a["id"] == b["id"]:
        return OBEC | COUNCIL | (APPROX if "approx" in a else 0)
    if a["kraj"] != b["kraj"]:
        code = KRAJ
    else:
        code = OKRES if a["okres"] != b["okres"] else OBEC
    if (a["kraj"], a["zsk"]) != (b["kraj"], b["zsk"]):
        code |= ZSK
    if (a.get("city"), a.get("city_obvod")) != (b.get("city"), b.get("city_obvod")):
        code |= CITY
    return code


LineCode = Callable[[Sequence[Mapping[str, Any]]], int]
"""The line code of an arc, from the properties of the features it bounds."""


def unit_code(okres: str | None = None) -> LineCode:
    """Return the line codes of a file of obce or coarse cells.

    With *okres*, the file is that okres's shard: of the arcs on its border
    it draws those whose other side has a higher okres code.
    """

    def code(sides: Sequence[Mapping[str, Any]]) -> int:
        c = line_code(sides[0], sides[1] if len(sides) > 1 else None)
        if okres is not None and min(s["okres"] for s in sides) != okres:
            c |= FOREIGN
        return c

    return code


def neighbour_code(sides: Sequence[Mapping[str, Any]]) -> int:
    """Return the line code of an arc of the countries around Slovakia."""
    return COUNTRY if len(sides) == _SIDES else COUNTRY | FOREIGN


def topology_file(
    topo: Topology,
    scale: int,
    rows: Iterable[int],
    properties: Sequence[Mapping[str, Any]],
    code: LineCode,
) -> dict[str, Any]:
    """Return the file of the features *rows* of *topo*; see the module doc.

    *properties* are those of every feature of *topo*.
    """
    local: dict[int, int] = {}

    def ref(r: int) -> int:
        i = local.setdefault(r if r >= 0 else ~r, len(local))
        return i if r >= 0 else ~i

    features = [
        {
            "properties": dict(properties[f]),
            "arcs": [[[ref(r) for r in ring] for ring in p] for p in topo.refs[f]],
        }
        for f in rows
    ]
    # The arcs' deltas at once: np.diff of each took long.
    chains = [topo.arcs[i] for i in local]
    xy = np.concatenate(chains) if chains else np.empty((0, 2), dtype=np.int64)
    ends = np.cumsum([len(c) for c in chains], dtype=np.int64)
    delta = np.diff(xy, axis=0, prepend=xy[:1])
    delta[ends[:-1]] = xy[ends[:-1]]
    delta[:1] = xy[:1]
    flat = delta.ravel().tolist()
    arcs = [flat[2 * s : 2 * e] for s, e in itertools.pairwise([0, *ends.tolist()])]
    lines = [code([properties[s] for s in topo.sides[i]]) for i in local]
    return {"scale": scale, "arcs": arcs, "lines": lines, "features": features}


def _arcs(content: Mapping[str, Any]) -> list[np.ndarray]:
    return [
        np.cumsum(np.asarray(a, dtype=np.int64).reshape(-1, 2), axis=0)
        for a in content["arcs"]
    ]


def decode(content: Mapping[str, Any]) -> tuple[list[np.ndarray], np.ndarray]:
    """Return the arcs (int64 vertices) and feature geometries of a topology.

    Both are in grid units, 1/``scale`` degree.
    """
    arcs = _arcs(content)

    def ring(refs: Sequence[int]) -> np.ndarray:
        parts = [arcs[r] if r >= 0 else arcs[~r][::-1] for r in refs]
        return np.concatenate([parts[0], *(p[1:] for p in parts[1:])])

    geometries = []
    for f in content["features"]:
        polygons = []
        for p in f["arcs"]:
            exterior, *holes = (ring(refs) for refs in p)
            polygons.append(shapely.Polygon(exterior, holes))
        geometries.append(
            polygons[0] if len(polygons) == 1 else shapely.MultiPolygon(polygons)
        )
    return arcs, np.array(geometries)


def _polygons(features: Sequence[Rings]) -> np.ndarray:
    return np.array(
        [
            shapely.MultiPolygon([shapely.Polygon(p[0], p[1:]) for p in f])
            for f in features
        ]
    )


def label_points(geometries: np.ndarray) -> np.ndarray:
    """Return the centre of the largest circle inside each of *geometries*."""
    return shapely.get_coordinates(
        shapely.get_point(shapely.maximum_inscribed_circle(geometries), 0)
    )


def lonlat(xy: np.ndarray, to_wgs84: pyproj.Transformer) -> list[float]:
    """Return the EPSG:5514 point *xy* as rounded WGS84 [lon, lat]."""
    lon, lat = to_wgs84.transform(xy[0], xy[1])
    return [round(float(lon), DECIMALS), round(float(lat), DECIMALS)]


def labels(geometries: np.ndarray, to_wgs84: pyproj.Transformer) -> list[list[float]]:
    """Return the WGS84 centre of the largest circle inside each of *geometries*."""
    lonlat = _to_wgs84(label_points(geometries), to_wgs84)
    return np.round(lonlat, DECIMALS).tolist()


def other_parts(geometry: Any) -> list[tuple[float, float, float]]:
    """Return (x, y, radius) of the largest circle in each other polygon.

    The other polygons of *geometry* are all but the one holding the largest
    circle of all, its label's; a single polygon has none.
    """
    parts = shapely.get_parts(geometry)
    if len(parts) <= 1:
        return []
    circles = shapely.maximum_inscribed_circle(parts)
    radii = shapely.length(circles)
    xy = shapely.get_coordinates(shapely.get_point(circles, 0))
    main = int(np.argmax(radii))
    return [
        (float(x), float(y), float(r))
        for i, ((x, y), r) in enumerate(zip(xy, radii, strict=True))
        if i != main
    ]


def part_labels(
    geometries: np.ndarray, to_wgs84: pyproj.Transformer
) -> list[list[list[float]]]:
    """Return the labels of the other parts of each of *geometries*.

    *geometries* are in EPSG:5514; a label is [lon, lat, room], room in whole
    metres, of the parts with room for one (:data:`PART_ROOM`).
    """
    return [
        [
            [*lonlat(np.array([x, y]), to_wgs84), round(r)]
            for x, y, r in other_parts(g)
            if r >= PART_ROOM
        ]
        for g in geometries
    ]


def grid_part_labels(geometry: Any, scale: int) -> list[list[float]]:
    """Return :func:`part_labels` of one *geometry* in grid units.

    Grid units are WGS84 degrees times *scale*; a degree of longitude, the
    shorter, measures the room.
    """
    out = []
    for x, y, r in other_parts(geometry):
        lat = y / scale
        room = r / scale * _METRES_PER_DEGREE * math.cos(math.radians(lat))
        if room >= PART_ROOM:
            out.append([round(x / scale, DECIMALS), round(lat, DECIMALS), round(room)])
    return out


def unit_properties(
    units: Sequence[Unit],
    gridded: np.ndarray,
    props: Mapping[str, Mapping[str, Any]],
    centres: Mapping[str, np.ndarray],
    splits: Mapping[str, Split],
    scale: int,
) -> list[dict[str, Any]]:
    """Return the properties of the shard features *units*; see the module doc.

    *gridded* are their geometries at level 0 in grid units, *props* the
    obce's with ``label`` (and ``parts``), whose point (grid units) *centres*
    holds. A council obvod gets ``oz``, its own ``oz_label`` (and
    ``oz_parts``) and ``approx``; the obec's ``label`` and ``parts`` go to
    the piece that holds its point.
    """
    pieces = [i for i, (_, n) in enumerate(units) if n]
    own = label_points(gridded[pieces]) if pieces else np.empty((0, 2))
    piece_label = dict(zip(pieces, own, strict=True))
    # The piece holding the obec's point, else its first.
    first: dict[str, int] = {}
    labelled: dict[str, int] = {}
    for i in pieces:
        code = units[i][0]
        first.setdefault(code, i)
        if shapely.intersects_xy(gridded[i], *centres[code]):
            labelled.setdefault(code, i)
    holder = first | labelled
    out = []
    for i, (code, n) in enumerate(units):
        p = dict(props[code])
        if n:
            if holder[code] != i:
                del p["label"]
                p.pop("parts", None)
            p |= {
                "oz": n,
                "oz_label": np.round(piece_label[i] / scale, DECIMALS).tolist(),
            }
            if parts := grid_part_labels(gridded[i], scale):
                p["oz_parts"] = parts
            if splits[code].approximate:
                p["approx"] = 1
            if splits[code].estimated:
                p["estimated"] = 1
        out.append(p)
    return out


class Base(NamedTuple):
    """What the shards of an election start from (:func:`base`)."""

    units: list[Unit]
    """The obce, those cut by k.ú. already in their council obvody
    (:func:`obec_levels`)."""
    gridded: dict[int, np.ndarray]
    """Their geometry per level, rounded to the grid (:func:`to_grid`)."""
    labels: dict[str, dict[str, Any]]
    """Obec → its ``label`` and ``parts`` (if any), of level 0."""
    coarse: np.ndarray
    """The obce of :data:`COARSE_LEVEL`, EPSG:5514, in the order of
    :func:`obec_codes`."""
    slovakia: Any
    """Their union."""


def base(
    paths: Mapping[int, Path],
    admin: Admin,
    splits: Mapping[str, Split],
    scale: int,
    cache: Cache | None = None,
) -> Base:
    """Return the obce of every level read, simplified and rounded; see :class:`Base`.

    The same for every election whose obce cut by k.ú. (of *splits*) are cut
    alike, so taken from *cache*, keyed on those cuts, where another election
    or run made it. The levels are rounded and the labels placed in worker
    processes.
    """
    by_ku = {c: s.kus for c, s in sorted(splits.items()) if s.kus is not None}
    entry = None if cache is None else cache.entry("base", repr(by_ku), str(scale))
    if entry is not None:
        with progress.stage("reading the levels of detail cached"):
            cached = cache.get(entry) if cache is not None else None
        if cached is not None:
            return cached
    units, obce = obec_levels(paths, admin, splits)
    levels = [lod.level for lod in SHARD_LODS]
    with progress.stage("rounding the levels and placing the obce labels"):
        *gridded, labels, (coarse, slovakia) = parallel.each(
            parallel.call,
            [
                *((_to_grid, obce[level], scale) for level in levels),
                (_obec_labels, units, obce[0]),
                (_coarse_obce, units, obce[COARSE_LEVEL]),
            ],
        )
    out = Base(units, dict(zip(levels, gridded, strict=True)), labels, coarse, slovakia)
    if cache is not None and entry is not None:
        cache.put(entry, out)
    return out


def _to_grid(geometries: np.ndarray, scale: int) -> np.ndarray:
    return to_grid(geometries, transformer(), scale)


def _obec_labels(units: Sequence[Unit], obce: np.ndarray) -> dict[str, dict[str, Any]]:
    """Return obec → its ``label`` and ``parts``, of the features *units* (*obce*)."""
    to_wgs84 = transformer()
    merged = merge_units(units, obce)
    codes = list(dict.fromkeys(c for c, _ in units))
    return {
        c: {"label": lonlat(xy, to_wgs84)} | ({"parts": parts} if parts else {})
        for c, xy, parts in zip(
            codes, label_points(merged), part_labels(merged, to_wgs84), strict=True
        )
    }


def _coarse_obce(units: Sequence[Unit], obce: np.ndarray) -> tuple[np.ndarray, Any]:
    """Return the obce of the features *units* (*obce*) merged, and their union."""
    return merge_units(units, obce), shapely.coverage_union_all(obce)


def grid_levels(
    units: Sequence[Unit],
    gridded: Mapping[int, np.ndarray],
    splits: Mapping[str, Split],
    scale: int,
    cache: Cache | None = None,
) -> tuple[list[Unit], dict[int, np.ndarray]]:
    """Return the shard features and each level rounded to the grid.

    *units* and *gridded* are those of :func:`base`; the obce cut by their
    address points are cut here, alike at every level, their cuts simplified
    as the level's borders are (:data:`CUT_TOLERANCE`). Each such obec is cut
    in a worker process (:func:`_council_cuts`), unless *cache* has its cut
    (:func:`_cached_each`), then each level bent in one
    (:func:`with_council`): a level at a time, the cities kept the others
    waiting.
    """
    levels = [lod.level for lod in SHARD_LODS]
    cut = [(i, c) for i, (c, n) in enumerate(units) if not n and c in splits]
    tasks = [
        (c, splits[c], {level: gridded[level][i] for level in levels}, scale)
        for i, c in cut
    ]
    if not cut:
        # Rounded by to_grid, the features are oriented as cutting leaves them.
        return list(units), dict(gridded)
    # An obec takes about as long as it has address points.
    size = {c: len(s.points.xy) for c, s in splits.items() if s.points is not None}
    cuts = dict(
        zip(
            (c for _, c in cut),
            _cached_each(
                cache,
                "council",
                _council_cuts,
                tasks,
                cost=lambda t: size.get(t[0], 0),
            ),
            strict=True,
        )
    )
    numbers = {c: [n for n, _ in splits[c].regions] for c in cuts}
    out: dict[int, np.ndarray] = {}
    first: list[Unit] = []
    for level, (here, out[level]) in zip(
        levels,
        parallel.each(
            with_council,
            [
                (units, gridded[level], numbers, {c: cuts[c][level] for c in cuts})
                for level in levels
            ],
        ),
        strict=True,
    ):
        if first and here != first:
            raise GeoError(
                f"level {level}: the council obvody cut differently than at"
                f" level {levels[0]}"
            )
        first = here
    return first, out


def _council_cuts(
    code: str, split: Split, obce: Mapping[int, Any], scale: int
) -> dict[int, tuple[list[tuple[int, Any]], Bends]]:
    """Return level → :func:`council_cut` of obec *code*, gridded *obce* per level."""
    to_wgs84 = transformer()
    return {
        level: council_cut(
            code,
            obec,
            replace(split, regions=_simplified(split.regions, level)),
            to_wgs84,
            scale,
        )
        for level, obec in obce.items()
    }


def _simplified(
    regions: tuple[tuple[int, Any], ...], level: int
) -> tuple[tuple[int, Any], ...]:
    """Return *regions* (a coverage) simplified for ZBGIS *level*.

    By :data:`CUT_TOLERANCE`; at level 0 as they are.
    """
    if len(regions) < _SIDES or level not in CUT_TOLERANCE:
        return regions
    simple = shapely.coverage_simplify(
        np.array([g for _, g in regions]), CUT_TOLERANCE[level]
    )
    return tuple((n, g) for (n, _), g in zip(regions, simple, strict=True))


# One set of worker processes for every stage: starting them took a third of
# a second a stage.
@parallel.shared()
def build(
    paths: Mapping[int, Path],
    countries: Path,
    election_dir: Path,
    places: Path,
    contests: Sequence[Mapping[str, Any]],
    candidates: Mapping[str, int],
    barriers: Barriers,
    *,
    partial: bool = False,
    cache: Cache | None = None,
) -> Result:
    """Build and check all output files; see the module doc.

    *paths* maps each ZBGIS level to its GeoPackage, *countries* is the
    Natural Earth GeoJSON; *election_dir* the election's curated data
    (:meth:`election_map_slovakia.config.Config.election_dir`); *places*
    the addresses of the obce with several council obvody
    (``data/build/<election day>/obvod-addresses/``); *contests* are those of
    ``candidates.json``, *candidates* the number of candidacies per contest;
    *barriers* the lines of the street blocks of the election's
    OpenStreetMap extract; *partial*: the contests are held in some areas
    only (a by-election); *cache* holds what other elections and runs made
    of the same input files (:class:`Cache`).
    """
    admin = load_admin(paths[0])
    with progress.stage("checking the obvod membership"):
        members = memberships(election_dir, admin, contests, partial=partial)
    to_wgs84 = transformer()
    kus = read_kus(paths[0])
    # An election without council contests cuts no obec into council obvody.
    councils = any(c["kind"] == "oz" for c in contests)
    with progress.stage("cutting the obce into council obvody and okrsky"):
        cuts = address_cuts(election_dir, places, kus, barriers, councils, cache)
    splits, okrsky = cuts.splits, cuts.okrsky
    codes = obec_codes(admin)
    scale = 10**DECIMALS
    start = base(paths, admin, splits, scale, cache)
    props = obec_properties(admin, codes, members)
    for c in codes:
        props[c] |= start.labels[c]
    with progress.stage("cutting council obvody"):
        units, gridded = grid_levels(start.units, start.gridded, splits, scale, cache)
    with progress.stage("placing the council obvody labels"):
        grid_centres = {c: np.array(props[c]["label"]) * scale for c in splits}
        properties = unit_properties(
            units, gridded[0], props, grid_centres, splits, scale
        )
    result = Result({}, okrsky=okrsky, okrsky_by_obvod=cuts.by_obvod)
    result.council = {
        c: (len(s.numbers), s.approximate, s.kus is not None) for c, s in splits.items()
    }
    result.council_points = {
        c: s.points for c, s in splits.items() if s.points is not None
    }
    result.okrsky_points = cuts.okrsky_points
    by_okres: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(properties):
        by_okres[p["okres"]].append(i)
    okres_rows = {okres: by_okres[okres] for okres in sorted(admin.okresy)}
    levels = [lod.level for lod in SHARD_LODS]
    # Each level's shards, its coverage, and its okrsky files and their
    # tiling, all in one pool: the largest, level 0, first. The coverage
    # depends on the level's features alone, the same in every election
    # that cuts the same obce alike: taken from *cache* where it has it.
    tasks: dict[tuple[str, int], tuple[Any, ...]] = {}
    errors, entries = _known_coverage(cache, gridded, scale)
    for level in levels:
        tasks["shards", level] = (
            _shard_files,
            level,
            gridded[level],
            properties,
            okres_rows,
            scale,
        )
        if level not in errors:
            tasks["coverage", level] = (_shard_coverage, gridded[level], scale)
    okrsky_index: dict[str, Any] = {
        "bands": _bands(),
        "okresy": {},
        "drawn": {c: sorted(o.number for o in os) for c, os in sorted(okrsky.items())},
    }
    if okrsky:
        with progress.stage("cutting the okrsky from the shards"):
            features, drawn = okrsky_levels(
                okrsky, cuts.reaching, units, gridded, cache
            )
        tasks |= _okrsky_tasks(features, drawn, units, gridded, admin, scale)
        tasks |= _figure_tasks(
            "okrsky", [(c, o.number) for c, o in features], drawn[0], result, scale
        )
    tasks |= _figure_tasks("council", units, gridded[0], result, scale)
    with progress.stage("cutting the levels of detail into arcs"):
        done = dict(
            zip(
                tasks,
                parallel.each(parallel.call, tasks.values(), cost=_vertices),
                strict=True,
            )
        )
    for (key, _), value in done.items():
        if key.endswith(_FIGURES):
            result.figures[key.removesuffix(_FIGURES)] += value
    bboxes = _add_shards(result, gridded, done, errors, entries, cache)
    if okrsky:
        _add_okrsky(result.files, okrsky_index, done)
    with progress.stage("coarse view"):
        coarse, cells = _coarse(
            start.coarse, [props[c] for c in codes], admin, members, to_wgs84
        )
    result.files[COARSE_FILE] = coarse
    result.coverage.insert(0, cells)
    _count_seats(result, coarse["obvody"], contests, candidates, partial)
    bad = [
        f"{c.name}: overlap {c.overlap:.1f} m², gaps {c.gaps:.1f} m²"
        for c in result.coverage
        if max(c.overlap, c.gaps) > MAX_COVERAGE_ERROR
    ]
    if bad:
        raise GeoError("\n  ".join(["neighbours do not share borders:", *bad]))
    result.files["index.json"] = {
        "shards": _bands(),
        "okresy": bboxes,
        "neighbours": [
            {
                "lod": str(n.level),
                "zoom": [n.from_zoom, n.until_zoom],
                "extent": list(n.extent),
            }
            for n in NEIGHBOUR_LODS
        ],
        "okrsky": okrsky_index,
    }
    with progress.stage("countries around Slovakia"):
        _add_neighbours(result.files, countries, start.slovakia, to_wgs84, cache)
    return result


def _bands() -> list[dict[str, Any]]:
    """Return the shard levels of detail as ``index.json`` lists them."""
    return [
        {"lod": str(lod.level), "zoom": [lod.from_zoom, lod.until_zoom]}
        for lod in SHARD_LODS
    ]


def _vertices(task: tuple[Any, ...]) -> int:
    """Return the vertices of the geometries of *task*, as its cost."""
    return sum(
        int(shapely.get_num_coordinates(a).sum())
        for a in task
        if isinstance(a, np.ndarray) and a.dtype == object
    )


def _digest(geometries: np.ndarray) -> str:
    """Return the SHA-256 of the WKB of *geometries*, in order."""
    digest = hashlib.sha256()
    for wkb in shapely.to_wkb(geometries).tolist():
        digest.update(len(wkb).to_bytes(8) + wkb)
    return digest.hexdigest()


_R = TypeVar("_R")


def _cached_each(
    cache: Cache | None,
    kind: str,
    fn: Callable[..., _R],
    tasks: Sequence[tuple[Any, ...]],
    cost: Callable[[tuple[Any, ...]], float] | None = None,
) -> list[_R]:
    """Return ``fn(*task)`` of each of *tasks*, in order, as :func:`parallel.each`.

    From *cache*, entries of *kind* keyed on the pickled task, where it has
    them; the others are run in worker processes and kept. The cuts placed
    in the shards are the same in every run and election that cuts an obec
    alike from the same features.
    """
    if cache is None:
        return list(parallel.each(fn, tasks, cost))
    entries = [
        cache.entry(
            kind, hashlib.sha256(pickle.dumps(t, pickle.HIGHEST_PROTOCOL)).hexdigest()
        )
        for t in tasks
    ]
    out = [cache.get(entry) for entry in entries]
    todo = [i for i, value in enumerate(out) if value is None]
    for i, value in zip(
        todo, parallel.each(fn, [tasks[i] for i in todo], cost), strict=True
    ):
        cache.put(entries[i], value)
        out[i] = value
    return out


def _shard_files(
    level: int,
    gridded: np.ndarray,
    properties: Sequence[Mapping[str, Any]],
    okres_rows: Mapping[str, Sequence[int]],
    scale: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[float]], int]:
    """Return the shards of ZBGIS *level*, the okresy's boxes, the vertices stored.

    *gridded* are its features in grid units, *properties* theirs, the shard
    of each okres those of its *okres_rows*. Run in a worker process per
    level (:func:`build`).
    """
    features = feature_rings(gridded)
    topo = topology(features, scale)
    files = {
        f"okres/{okres}/{level}.json": topology_file(
            topo, scale, rows, properties, unit_code(okres)
        )
        for okres, rows in okres_rows.items()
    }
    bboxes = {
        okres: _rows_bbox(features, rows, scale) for okres, rows in okres_rows.items()
    }
    return files, bboxes, sum(len(a) for a in topo.arcs)


def _shard_coverage(gridded: np.ndarray, scale: int) -> tuple[float, float]:
    """Return the overlaps and gaps of the features *gridded* (:func:`overlaps`).

    Run in a worker process per level, beside :func:`_shard_files`.
    """
    return overlaps(feature_rings(gridded), scale, transformer())


def _rows_bbox(
    features: Sequence[Rings], rows: Iterable[int], scale: int
) -> list[float]:
    """Return the :func:`_bbox` of the gridded *features* of *rows*."""
    xy = np.concatenate([r for f in rows for p in features[f] for r in p])
    return _bbox(xy / scale)


def _count_seats(
    result: Result,
    drawn: Sequence[Mapping[str, Any]],
    contests: Sequence[Mapping[str, Any]],
    candidates: Mapping[str, int],
    partial: bool = False,
) -> None:
    """Set the seats and short obvody of *result* from the obvody *drawn*.

    Fails unless every obvod contest has one. *partial* (a by-election):
    only the obvody with a contest count, the others electing no one.
    """
    ids = {o["id"] for o in drawn}
    held = {str(c["id"]) for c in contests}
    missing = sorted(
        str(c["id"]) for c in contests if _is_obvod_contest(c) and c["id"] not in ids
    )
    if missing:
        raise GeoError(f"contests without an obvod: {', '.join(missing)}")
    for o in drawn:
        if partial and o["id"] not in held:
            continue
        area = o["id"].split(":")[1].split("/")[0]
        result.seats[area] = result.seats.get(area, 0) + o["seats"]
        if candidates.get(o["id"], 0) < o["seats"]:
            result.short.append((o["id"], candidates.get(o["id"], 0), o["seats"]))


def _add_shards(
    result: Result,
    gridded: Mapping[int, np.ndarray],
    done: Mapping[tuple[str, int], Any],
    errors: dict[int, tuple[float, float]],
    entries: Mapping[int, Path],
    cache: Cache | None,
) -> dict[str, list[float]]:
    """Add the shards and coverage of every level to *result*; return the boxes.

    *done* are the results of the tasks of :func:`build`, *errors* the
    overlaps and gaps *cache* had (:func:`_known_coverage`): it gets the
    others, as *entries*. The okresy's boxes are of the finest level.
    """
    bboxes: dict[str, list[float]] = {}
    for lod in SHARD_LODS:
        level = lod.level
        # The finest level is the last.
        files, bboxes, vertices = done["shards", level]
        result.files |= files
        if level not in errors:
            errors[level] = done["coverage", level]
            if cache is not None:
                cache.put(entries[level], errors[level])
        name = f"okres/*/{level}.json obce"
        result.coverage.append(
            Coverage(name, len(gridded[level]), vertices, *errors[level])
        )
    return bboxes


def _known_coverage(
    cache: Cache | None, gridded: Mapping[int, np.ndarray], scale: int
) -> tuple[dict[int, tuple[float, float]], dict[int, Path]]:
    """Return the overlaps and gaps *cache* has of the levels *gridded*.

    And the entry of each level: keyed on its features (:func:`_digest`).
    """
    errors: dict[int, tuple[float, float]] = {}
    entries: dict[int, Path] = {}
    if cache is None:
        return errors, entries
    for level, features in gridded.items():
        entries[level] = cache.entry("coverage", _digest(features), str(scale))
        known = cache.get(entries[level])
        if known is not None:
            errors[level] = known
    return errors, entries


def _add_okrsky(
    files: dict[str, dict[str, Any]],
    index: dict[str, Any],
    done: Mapping[tuple[str, int], Any],
) -> None:
    """Add the okrsky files of every level to *files*, their boxes to *index*.

    *done* are the results of :func:`_okrsky_tasks`. Fails unless the
    okrsky of each obec tile it at every level (:func:`okrsky_problems`).
    """
    problems: list[str] = []
    for lod in SHARD_LODS:
        # The okresy's boxes are of the finest level, the last.
        level_files, index["okresy"] = done["okrsky", lod.level]
        files |= level_files
        problems += [
            p
            for (key, _), found in done.items()
            if key == f"problems {lod.level}"
            for p in found
        ]
    if problems:
        raise GeoError("\n  ".join(["the okrsky do not tile their obce:", *problems]))


_PROBLEM_PARTS = 4
"""Parts of the obce whose okrsky's tiling is checked apart, per level."""


def _okrsky_tasks(
    features: Sequence[OkrsokUnit],
    drawn: Mapping[int, np.ndarray],
    units: Sequence[Unit],
    gridded: Mapping[int, np.ndarray],
    admin: Admin,
    scale: int,
) -> dict[tuple[str, int], tuple[Any, ...]]:
    """Return the tasks that make the okrsky files and check their tiling.

    For :func:`parallel.call`, by ("okrsky", level) :func:`_okrsky_files` and
    by ("problems <level>", part) :func:`_okrsky_problems` of each of
    :data:`_PROBLEM_PARTS` parts of the obce, in order. *features* and
    *drawn* are the okrsky and their geometry per level
    (:func:`okrsky_levels`), *units* and *gridded* the shard features
    (:func:`grid_levels`).
    """
    properties = okrsok_properties(features, drawn[0], scale)
    by_okres: dict[str, list[int]] = defaultdict(list)
    for i, (c, _) in enumerate(features):
        okres = admin.obce[c].okres
        assert okres is not None  # okrsky are drawn in ZBGIS obce only
        by_okres[okres].append(i)
    okres_rows = sorted(by_okres.items())
    # The tiling is checked per obec, in parts of about as many vertices,
    # the obce in order: one task per level kept the other workers waiting.
    rows_of: dict[str, list[int]] = defaultdict(list)
    for i, (c, _) in enumerate(features):
        rows_of[c].append(i)
    codes = sorted(rows_of)
    vertices = shapely.get_num_coordinates(drawn[0])
    cumulative = np.cumsum([vertices[rows_of[c]].sum() for c in codes])
    part_of = {
        c: int(p)
        for c, p in zip(
            codes, (cumulative - 1) * _PROBLEM_PARTS // cumulative[-1], strict=True
        )
    }
    # Only the shard features of the obce with okrsky are compared with them.
    shard_rows: dict[int, list[int]] = defaultdict(list)
    for i, (c, _) in enumerate(units):
        if c in part_of:
            shard_rows[part_of[c]].append(i)
    okrsok_rows: dict[int, list[int]] = defaultdict(list)
    for c in codes:
        okrsok_rows[part_of[c]] += rows_of[c]
    tasks: dict[tuple[str, int], tuple[Any, ...]] = {}
    for lod in SHARD_LODS:
        level, geometries = lod.level, drawn[lod.level]
        tasks["okrsky", level] = (
            _okrsky_files,
            level,
            geometries,
            properties,
            okres_rows,
            scale,
        )
        for part, mine in sorted(okrsok_rows.items()):
            shards = shard_rows[part]
            tasks[f"problems {level}", part] = (
                _okrsky_problems,
                level,
                geometries[mine],
                [properties[i] for i in mine],
                [units[i] for i in shards],
                gridded[level][shards],
                scale,
            )
    return tasks


def _okrsky_files(
    level: int,
    geometries: np.ndarray,
    properties: Sequence[Mapping[str, Any]],
    okres_rows: Sequence[tuple[str, Sequence[int]]],
    scale: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[float]]]:
    """Return the okrsky files of ZBGIS *level* and the okresy's boxes.

    *geometries* and *properties* are the okrsky's (:func:`_okrsky_tasks`).
    Run in a worker process per level.
    """
    drawn = feature_rings(geometries)
    topo = topology(drawn, scale)
    files = {
        okrsky_path(okres, str(level)): topology_file(
            topo, scale, rows, properties, okrsok_code
        )
        for okres, rows in okres_rows
    }
    return files, {okres: _rows_bbox(drawn, rows, scale) for okres, rows in okres_rows}


def _okrsky_problems(
    level: int,
    geometries: np.ndarray,
    properties: Sequence[Mapping[str, Any]],
    units: Sequence[Unit],
    gridded: np.ndarray,
    scale: int,
) -> list[str]:
    """Return how the okrsky of ZBGIS *level* fail to tile their obce.

    See :func:`okrsky_problems`; *units* and *gridded* are the level's shard
    features of those obce. Run in a worker process per level.
    """
    codes = list(dict.fromkeys(c for c, _ in units))
    obce = dict(zip(codes, merge_units(units, gridded), strict=True))
    return [
        f"level {level}: {p}"
        for p in okrsky_problems(properties, geometries, obce, scale)
    ]


def _add_neighbours(
    files: dict[str, dict[str, Any]],
    countries: Path,
    slovakia: Any,
    to_wgs84: pyproj.Transformer,
    cache: Cache | None = None,
) -> None:
    """Add the countries around *slovakia* to *files*, which have all else.

    Their files depend on *slovakia* and the input files alone, so they are
    taken from *cache* where another election or run made them. Fails
    unless they meet it at every level of detail (see the module doc).
    """
    entry = None
    if cache is not None:
        wkb = hashlib.sha256(shapely.to_wkb(slovakia)).hexdigest()
        entry = cache.entry("neighbours", wkb)
    made = None if cache is None or entry is None else cache.get(entry)
    if made is None:
        areas = neighbour_areas(read_countries(countries, to_wgs84), slovakia)
        with progress.stage("placing their names"):
            spots = {k: label_spots(g, slovakia, to_wgs84) for k, g in areas.items()}
        made = {
            neighbours_path(str(n.level)): neighbours_file(areas, spots, n, to_wgs84)
            for n in NEIGHBOUR_LODS
        }
        if cache is not None and entry is not None:
            cache.put(entry, made)
    files |= made
    with progress.stage("checking them against Slovakia's border"):
        outlines = {
            name: country_outline([files[rel] for rel in rels])
            for name, rels in level_files(files["index.json"]).items()
        }
        bad = [
            f"{neighbours_path(str(n.level))}: {p}"
            for n in NEIGHBOUR_LODS
            for p in verify_neighbours(files[neighbours_path(str(n.level))], outlines)
        ]
    if bad:
        raise GeoError("\n  ".join(["the countries around Slovakia:", *bad]))


def neighbours_path(lod: str) -> str:
    """Return the path below ``geo/`` of the neighbours' level *lod*."""
    return f"{NEIGHBOURS_DIR}/{lod}.json"


def level_files(index: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return the files of Slovakia per level of detail of ``index.json``.

    Keys name the level (``coarse.json``, ``okres/*/<lod>.json``), values are
    paths below ``geo/``.
    """
    return {COARSE_FILE: [COARSE_FILE]} | {
        f"okres/*/{band['lod']}.json": [
            f"okres/{okres}/{band['lod']}.json" for okres in index["okresy"]
        ]
        for band in index["shards"]
    }


def read_countries(path: Path, to_wgs84: pyproj.Transformer) -> dict[str, Any]:
    """Return ISO 3166 code → land, in EPSG:5514, of the countries in EXTENT.

    *path* is the Natural Earth GeoJSON of admin 0 countries.
    """
    try:
        data = json.loads(path.read_bytes())
    except ValueError as e:
        raise GeoError(f"{path.name}: {e}") from e
    extent = shapely.box(*EXTENT)
    out: dict[str, Any] = {}
    for f in data["features"]:
        land = shapely.make_valid(shapely.from_geojson(json.dumps(f["geometry"])))
        if not shapely.intersects(land, extent):
            continue
        code = f["properties"].get("ISO_A2_EH")
        if not isinstance(code, str) or not _ISO_CODE.fullmatch(code):
            raise GeoError(
                f"{path.name}: {f['properties'].get('ADMIN')} has no ISO 3166 code"
            )
        land = polygonal(shapely.intersection(land, extent))
        out[code] = shapely.union(out[code], land) if code in out else land
    if "SK" not in out:
        raise GeoError(f"{path.name}: no Slovakia")
    return {k: _metres(g, to_wgs84) for k, g in out.items()}


def _metres(lonlat: Any, to_wgs84: pyproj.Transformer) -> Any:
    """Return WGS84 *lonlat* in EPSG:5514, its long edges bent as they project."""
    lonlat = shapely.segmentize(lonlat, 0.05)
    return shapely.transform(lonlat, lambda xy: _from_wgs84(xy, to_wgs84))


def polygonal(g: Any) -> Any:
    """Return the polygons of *g* (an overlay may add lines and points)."""
    parts = shapely.get_parts(shapely.get_parts(g))
    return shapely.multipolygons(
        parts[shapely.get_type_id(parts) == shapely.GeometryType.POLYGON]
    )


def neighbour_areas(countries: Mapping[str, Any], slovakia: Any) -> dict[str, Any]:
    """Return ISO 3166 code → area of each country around Slovakia.

    *countries* are those of :func:`read_countries`, Slovakia included,
    *slovakia* is the ZBGIS one; all in EPSG:5514. The areas are not yet an
    exact coverage (see :func:`neighbours_file`).
    """
    neighbours = {
        k: g for k, g in countries.items() if k != "SK" and shapely.area(g) >= MIN_AREA
    }
    under = shapely.simplify(shapely.buffer(slovakia, -UNDER), UNDER / 3)
    # Between Natural Earth's Slovakia and ZBGIS's, and the strip under the
    # border: whatever no neighbour has.
    between = shapely.difference(
        shapely.difference(shapely.union(countries["SK"], slovakia), under),
        shapely.union_all(list(neighbours.values())),
    )
    near = shapely.buffer(slovakia, NEAR_SLOVAKIA)
    points, owners = [], []
    for k, g in neighbours.items():
        line = shapely.intersection(shapely.boundary(g), near)
        xy = shapely.get_coordinates(shapely.segmentize(line, SAMPLE))
        points.append(xy)
        owners += [k] * len(xy)
    # A point on the border of two neighbours counts for one of them.
    xy, first = np.unique(np.concatenate(points), axis=0, return_index=True)
    owner = np.array(owners)[first]
    cells = shapely.get_parts(
        shapely.voronoi_polygons(
            shapely.multipoints(xy), extend_to=between, ordered=True
        )
    )
    return {
        k: polygonal(
            shapely.union(
                shapely.difference(g, under),
                shapely.intersection(between, shapely.union_all(cells[owner == k])),
            )
        )
        for k, g in neighbours.items()
    }


def _exact_coverage(areas: Mapping[str, Any], clip: Any) -> dict[str, Any]:
    """Return *areas* within *clip* as an exact coverage; see the module doc."""
    keys = list(areas)
    clipped = [polygonal(shapely.intersection(areas[k], clip)) for k in keys]
    lines = shapely.union_all(shapely.boundary(np.array(clipped)))
    pieces = shapely.get_parts(shapely.polygonize(shapely.get_parts(lines)))
    inside = shapely.point_on_surface(pieces)
    owner = np.full(len(pieces), -1)
    for i, g in enumerate(clipped):
        shapely.prepare(g)
        owner[(owner < 0) & shapely.contains(g, inside)] = i
    tree = shapely.STRtree(pieces)
    small = shapely.area(pieces) < MIN_AREA
    for p in np.flatnonzero((owner < 0) & small):
        shared: Counter[int] = Counter()
        for q in tree.query(pieces[p], predicate="touches"):
            if owner[q] >= 0:
                border = shapely.intersection(
                    shapely.boundary(pieces[p]), shapely.boundary(pieces[q])
                )
                shared[int(owner[q])] += shapely.length(border)
        if shared:
            owner[p] = shared.most_common(1)[0][0]
    return {
        k: shapely.coverage_union_all(pieces[owner == i])
        for i, k in enumerate(keys)
        if (owner == i).any()
    }


def neighbours_file(
    areas: Mapping[str, Any],
    spots: Mapping[str, list[list[float]]],
    lod: NeighbourLod,
    to_wgs84: pyproj.Transformer,
) -> dict[str, Any]:
    """Return the topology of the countries *areas* at *lod*.

    *spots* are the places for each country's name (:func:`label_spots`).
    """
    exact = _exact_coverage(areas, _metres(shapely.box(*lod.extent), to_wgs84))
    codes = sorted(exact)
    simple = shapely.coverage_simplify(
        np.array([exact[k] for k in codes]), lod.tolerance
    )
    scale = 10**lod.decimals
    features = feature_rings(to_grid(simple, to_wgs84, scale))
    kept = [i for i, f in enumerate(features) if f]
    topo = topology([features[i] for i in kept], scale)
    properties = [{"id": codes[i], "spots": spots[codes[i]]} for i in kept]
    return topology_file(topo, scale, range(len(kept)), properties, neighbour_code)


def label_spots(
    area: Any, slovakia: Any, to_wgs84: pyproj.Transformer
) -> list[list[float]]:
    """Return the places for the name of the country *area*: [lon, lat, room].

    *area* and *slovakia* are in EPSG:5514. The part of the country that
    shows, out of Slovakia and within EXTENT, is covered by a square, and
    every square that reaches into Slovakia is cut in four, down to
    :data:`SPOT_CELL`: the views a visitor looks at show Slovakia, so at
    every zoom one of them has a square as large as itself, or smaller,
    along the border. A square's place is the centre of the largest circle
    within the country's part of it; in the smallest ones, within
    :data:`SPOT_CELL` / 4 of Slovakia, so that it is near enough to the
    border for the most zoomed in views. ``room`` is the distance of
    the place to the edge of the part that shows, in metres.
    """
    shows = polygonal(
        shapely.intersection(
            shapely.difference(area, slovakia),
            _metres(shapely.box(*EXTENT), to_wgs84),
        )
    )
    if shows.is_empty:
        return []
    edge = shapely.boundary(shows)
    shapely.prepare(shows)
    shapely.prepare(slovakia)
    west, south, east, north = shows.bounds
    squares = [(west, south, max(east - west, north - south))]
    centres = []
    # The strip along Slovakia the smallest squares keep their place in.
    strip = shapely.buffer(slovakia, SPOT_CELL / 4)
    shapely.prepare(strip)
    while squares:
        x, y, side = squares.pop()
        square = shapely.box(x, y, x + side, y + side)
        piece = polygonal(shapely.intersection(shows, square))
        smallest = side <= SPOT_CELL
        if smallest:
            piece = polygonal(shapely.intersection(piece, strip))
        if piece.is_empty:
            continue
        centres.append(shapely.get_point(shapely.maximum_inscribed_circle(piece), 0))
        if not smallest and shapely.intersects(slovakia, square):
            half = side / 2
            squares += [(x + dx, y + dy, half) for dx in (0, half) for dy in (0, half)]
    room = shapely.distance(np.array(centres), edge).tolist()
    lonlat = _to_wgs84(shapely.get_coordinates(np.array(centres)), to_wgs84).tolist()
    return sorted(
        [round(lon, BBOX_DECIMALS), round(lat, BBOX_DECIMALS), round(r)]
        for (lon, lat), r in zip(lonlat, room, strict=True)
    )


def country_outline(files: Iterable[Mapping[str, Any]]) -> Any:
    """Return Slovakia as the topology *files* of one level draw it, in degrees."""
    lines = [
        shapely.LineString(xy / content["scale"])
        for content in files
        for xy, code in zip(_arcs(content), content["lines"], strict=True)
        if code & RANK == COUNTRY and not code & FOREIGN
    ]
    return shapely.union_all(shapely.get_parts(shapely.polygonize(lines)))


def verify_neighbours(
    content: Mapping[str, Any], outlines: Mapping[str, Any]
) -> list[str]:
    """Return the problems of a topology of the countries around Slovakia.

    The countries must be a valid coverage, the arcs drawn exactly the
    borders between two of them, each once, and the hole they leave must be
    within Slovakia as each of *outlines* (level name → its
    :func:`country_outline`) draws it: else the map shows a gap there.
    """
    arcs, features = decode(content)
    problems = []
    invalid = ~shapely.is_empty(shapely.coverage_invalid_edges(features))
    if invalid.any():
        country = content["features"][int(np.argmax(invalid))]["properties"]["id"]
        problems.append(
            f"{invalid.sum()} countries do not share their borders exactly with"
            f" their neighbours, e.g. {country}"
        )
    drawn = np.concatenate(
        [np.empty((0, 2), np.int64)]
        + [
            _segments(xy)
            for xy, code in zip(arcs, content["lines"], strict=True)
            if not code & FOREIGN
        ]
    )
    unique, counts = _unique_rows(drawn)
    if (counts > 1).any():
        problems.append(f"{(counts > 1).sum()} border segments drawn more than once")
    borders, sides = _unique_rows(_boundary_segments(features))
    problems += _compare("two countries", borders[sides == _SIDES], unique)
    holes = [
        shapely.Polygon(ring)
        for part in shapely.get_parts(shapely.coverage_union_all(features))
        for ring in part.interiors
    ]
    if not holes:
        return [*problems, "they leave no hole for Slovakia"]
    hole = shapely.transform(shapely.union_all(holes), lambda xy: xy / content["scale"])
    for name, outline in outlines.items():
        gap = shapely.area(shapely.difference(hole, outline)) * _M2_PER_DEGREE2
        if gap > MAX_COVERAGE_ERROR:
            problems.append(f"{gap:,.0f} m² between them and Slovakia at {name}")
    return problems


def _bbox(lonlat: np.ndarray) -> list[float]:
    scale = 10**BBOX_DECIMALS
    west, south = np.floor(lonlat.min(axis=0) * scale) / scale
    east, north = np.ceil(lonlat.max(axis=0) * scale) / scale
    return [float(west), float(south), float(east), float(north)]


def _coarse(
    obce: np.ndarray,
    properties: Sequence[Mapping[str, Any]],
    admin: Admin,
    members: Mapping[str, Membership],
    to_wgs84: pyproj.Transformer,
) -> tuple[dict[str, Any], Coverage]:
    """Return ``coarse.json`` and its coverage check; see the module doc.

    *obce* are the geometries of :data:`COARSE_LEVEL` and *properties* theirs.
    """
    keys = ("kraj", "okres", "zsk", "city", "city_obvod")
    cells = _rows_by(properties, lambda p: tuple(p.get(k) for k in keys))
    cell_props = [
        {k: v for k, v in zip(keys, key, strict=True) if v is not None} for key in cells
    ]
    scale = 10**DECIMALS
    simple = shapely.coverage_simplify(_merged(obce, cells.values()), COARSE_TOLERANCE)
    features = feature_rings(to_grid(simple, to_wgs84, scale))
    topo = topology(features, scale)
    content = topology_file(topo, scale, range(len(features)), cell_props, unit_code())
    content["land"] = [[ring] for ring in _outline(content)]

    def placed(geometries: np.ndarray) -> list[dict[str, Any]]:
        """``label`` and, for an area of several parts, ``parts``."""
        return [
            {"label": label} | ({"parts": parts} if parts else {})
            for label, parts in zip(
                labels(geometries, to_wgs84),
                part_labels(geometries, to_wgs84),
                strict=True,
            )
        ]

    def placed_by(key: str) -> list[tuple[str, dict[str, Any]]]:
        """Each value of *key*, sorted, and its area :func:`placed`."""
        rows = _rows_by(properties, lambda p: p[key])
        codes = sorted(rows)
        merged = _merged(obce, [rows[c] for c in codes])
        return list(zip(codes, placed(merged), strict=True))

    content["kraje"] = [
        {"id": k, "name": admin.kraje[k]} | where for k, where in placed_by("kraj")
    ]
    content["okresy"] = [
        {"id": o, "name": admin.okresy[o][0], "kraj": admin.okresy[o][1]} | where
        for o, where in placed_by("okres")
    ]
    index = {p["id"]: i for i, p in enumerate(properties)}
    areas = [
        *((f"zsk-{k}", f"zsk:{k}") for k in sorted(admin.kraje)),
        *((c.code, f"oz:{c.code}") for c in CITIES),
    ]
    obvod_rows = []
    for name, prefix in areas:
        if name not in members:
            continue
        listed, resolved = members[name]
        obvod_rows += [
            (f"{prefix}/{o.number}", o.seats, [index[c] for c in resolved[o.number]])
            for o in listed.obvody
        ]
    # The obvody drawn: none where the election has no council by obvod.
    content["obvody"] = (
        [
            {"id": obvod, "seats": seats} | where
            for (obvod, seats, _), where in zip(
                obvod_rows,
                placed(_merged(obce, [rows for *_, rows in obvod_rows])),
                strict=True,
            )
        ]
        if obvod_rows
        else []
    )
    vertices = sum(len(a) for a in topo.arcs)
    errors = overlaps(features, scale, to_wgs84)
    return content, Coverage(f"{COARSE_FILE} cells", len(features), vertices, *errors)


def _outline(content: Mapping[str, Any]) -> list[list[int]]:
    """Return the rings around all features of a topology file, as arc refs.

    They are its arcs on the country border, chained end to start.
    """
    arcs, _ = decode(content)
    after: dict[tuple[int, ...], tuple[int, tuple[int, ...]]] = {}
    for f in content["features"]:
        for polygon in f["arcs"]:
            for ring in polygon:
                for r in ring:
                    i = r if r >= 0 else ~r
                    if content["lines"][i] & RANK != COUNTRY:
                        continue
                    xy = arcs[i] if r >= 0 else arcs[i][::-1]
                    start = tuple(xy[0].tolist())
                    if start in after:
                        raise GeoError(f"the outline touches itself at {start}")
                    after[start] = (r, tuple(xy[-1].tolist()))
    rings = []
    while after:
        start, (r, end) = after.popitem()
        ring = [r]
        while end != start:
            r, end = after.pop(end)
            ring.append(r)
        rings.append(ring)
    return rings


def overlaps(
    features: Sequence[Rings], scale: int, to_wgs84: pyproj.Transformer
) -> tuple[float, float]:
    """Return the overlaps and gaps between the gridded *features*, in m²."""
    g = shapely.make_valid(
        shapely.transform(
            _polygons(features), lambda xy: _from_wgs84(xy / scale, to_wgs84)
        )
    )
    union = shapely.union_all(g)
    holes = [
        shapely.Polygon(ring)
        for part in shapely.get_parts(union)
        if isinstance(part, shapely.Polygon)
        for ring in part.interiors
    ]
    return (
        max(0.0, float(shapely.area(g).sum()) - union.area),
        float(sum(h.area for h in holes)),
    )


def _segments(xy: np.ndarray) -> np.ndarray:
    """Return the segments of the line *xy* (grid units) as sorted key pairs."""
    k = _keys(xy.astype(np.int64))
    return np.sort(np.column_stack([k[:-1], k[1:]]), axis=1)


def _boundary_segments(geometries: np.ndarray) -> np.ndarray:
    """Return the segments of the boundaries of *geometries*, as :func:`_segments`."""
    lines = shapely.get_parts(shapely.boundary(geometries))
    xy, line = shapely.get_coordinates(lines, return_index=True)
    k = _keys(xy.astype(np.int64))
    along = line[:-1] == line[1:]
    return np.sort(np.column_stack([k[:-1][along], k[1:][along]]), axis=1)


# The units verify() merges: name, the key of a feature's unit (None: in
# none), and which line codes are borders of such units.
_UNITS: tuple[
    tuple[
        str,
        Callable[[Mapping[str, Any]], Hashable],
        Callable[[np.ndarray], np.ndarray],
    ],
    ...,
] = (
    ("country", lambda p: "SK", lambda c: c & RANK == COUNTRY),
    ("kraj", lambda p: p["kraj"], lambda c: c & RANK >= KRAJ),
    ("okres", lambda p: p["okres"], lambda c: c & RANK >= OKRES),
    ("regional council obvod", lambda p: (p["kraj"], p["zsk"]), lambda c: c & ZSK != 0),
    (
        "city council obvod",
        lambda p: (p["city"], p["city_obvod"]) if "city" in p else None,
        lambda c: c & CITY != 0,
    ),
)


def verify(files: Iterable[Mapping[str, Any]]) -> list[str]:
    """Return the problems of the topology files of one level of detail.

    The features must be a valid coverage; the arcs drawn (all but those
    coded FOREIGN) must be its borders, each exactly once; and every kraj,
    okres, obvod and the country, merged from the features with
    ``coverage_union``, must be bounded by exactly the arcs coded as its
    border. So every higher-level border is made of the obce's own edges.
    """
    properties, features, segments, code, _ = _read_level(files)
    problems = []
    invalid = ~shapely.is_empty(shapely.coverage_invalid_edges(features))
    if invalid.any():
        problems.append(
            f"{invalid.sum()} features do not share their borders exactly with"
            f" their neighbours, e.g. {_name(properties[int(np.argmax(invalid))])}"
        )
    unique, counts = _unique_rows(segments)
    if (counts > 1).any():
        problems.append(f"{(counts > 1).sum()} border segments drawn more than once")
    problems += _compare("the features", _boundary_segments(features), unique)
    problems += _verify_council(features, properties, segments, code)
    for name, key, test in _UNITS:
        units = _rows_by(properties, key)
        units.pop(None, None)
        try:
            merged = _merged(features, units.values())
        except shapely.errors.GEOSException as e:
            problems.append(f"cannot merge the features into every {name}: {e}")
            continue
        problems += _compare(
            f"every {name}", _boundary_segments(merged), segments[test(code)]
        )
    return problems


def _verify_council(
    features: np.ndarray,
    properties: Sequence[Mapping[str, Any]],
    segments: np.ndarray,
    code: np.ndarray,
) -> list[str]:
    """Return the problems of the council obvod borders within obce.

    The arcs coded COUNCIL must be exactly the borders of the obce's council
    obvody that are not borders of the obce, and those coded APPROX the ones
    of the obce cut by their address points.
    """
    if not any("oz" in p for p in properties) and not (code & COUNCIL).any():
        return []
    problems = []
    for name, which in (
        ("", lambda p: True),
        (" approximate", lambda p: "approx" in p),
    ):
        pieces = [i for i, p in enumerate(properties) if "oz" in p and which(p)]
        rows = _rows_by((properties[i] for i in pieces), lambda p: p["id"])
        obce = _merged(features[pieces], rows.values())
        inner = _without(_boundary_segments(features[pieces]), _boundary_segments(obce))
        flag = COUNCIL if not name else COUNCIL | APPROX
        problems += _compare(
            f"every{name} council obvod within its obec",
            inner,
            segments[(code & flag) == flag],
        )
    return problems


def _compare(name: str, borders: np.ndarray, drawn: np.ndarray) -> list[str]:
    """Return the problems of *drawn* segments that should be *borders*."""
    want, _ = _unique_rows(borders)
    have, _ = _unique_rows(drawn)
    if np.array_equal(want, have):
        return []
    wanted = {tuple(s) for s in want.tolist()}
    had = {tuple(s) for s in have.tolist()}
    missing, extra = wanted - had, had - wanted
    problems = []
    if missing:
        problems.append(f"{len(missing)} segments bounding {name} are not drawn so")
    if extra:
        problems.append(f"{len(extra)} segments drawn as bounding {name} do not")
    return problems


def _name(p: Mapping[str, Any]) -> str:
    return f"obec {p['id']}" if "id" in p else f"cell {dict(p)}"


# --- how the cuts drawn from address points look (see the report) -------------

_FIGURES = " figures"
"""The suffix of the keys of the tasks of :func:`figures` in :func:`build`."""


@dataclass
class Figures:
    """How the units of cuts drawn from address points look at full detail.

    Summed over the obce of an election for the report (:func:`figures`).
    """

    units: int = 0
    pieces: int = 0
    """Polygons besides the largest of each unit."""
    pieces_held: int = 0
    """Of those, the ones that hold an address point of their unit."""
    addresses: int = 0
    """Located addresses."""
    shared: int = 0
    """Located addresses drawn outside their own unit at a point that
    another unit's addresses share, which that unit takes."""
    outside: int = 0
    """Located addresses outside every unit: beyond the obec as drawn."""
    misplaced: int = 0
    """Other located addresses drawn outside their own unit."""
    compactness: float = 0.0
    """Sum of the units' Polsby-Popper scores, 4πA/P²: 1 for a disc, near 0
    for a ragged or long, thin shape."""
    border: float = 0.0
    """Length of the borders between the units, m."""

    def __add__(self, other: Figures) -> Figures:
        """Return the figures of both."""
        return Figures(
            **{
                f.name: getattr(self, f.name) + getattr(other, f.name)
                for f in fields(self)
            }
        )


def figures(
    numbers: Sequence[int], geometries: np.ndarray, points: Points, scale: int
) -> Figures:
    """Return the :class:`Figures` of the units of one obec as drawn.

    *numbers* are the units (obvody or okrsky) and *geometries* their
    features at level 0, *points* the address points they are drawn from,
    all in grid units of 1/*scale* degree. Lengths and areas are measured
    in degrees scaled to metres at the obec's latitude: near enough for the
    report, and cheap.
    """
    out = Figures(units=len(numbers))
    xy = shapely.points(points.xy)
    _count_pieces(out, numbers, geometries, xy, points)
    _count_placed(out, numbers, geometries, xy, points)
    latitude = math.radians(float(points.xy[:, 1].mean()) / scale)
    metres = np.array([math.cos(latitude), 1.0]) * _METRES_PER_DEGREE / scale
    shapes = shapely.transform(geometries, lambda c: c * metres)
    perimeter = shapely.length(shapes)
    out.compactness = float((4 * math.pi * shapely.area(shapes) / perimeter**2).sum())
    out.border = (
        float(perimeter.sum() - shapely.length(shapely.coverage_union_all(shapes))) / 2
    )
    return out


def _count_pieces(
    out: Figures,
    numbers: Sequence[int],
    shapes: np.ndarray,
    xy: np.ndarray,
    points: Points,
) -> None:
    """Count in *out* the pieces of the units *shapes* besides their largest.

    And those that hold a point *xy* with an address of their unit.
    """
    own: dict[int, list[int]] = {n: [] for n in numbers}
    for i, votes in enumerate(points.addresses):
        for u, _ in votes:
            if u in own:
                own[u].append(i)
    for n, g in zip(numbers, shapes, strict=True):
        parts = shapely.get_parts(g)
        others = parts[np.argsort(-shapely.area(parts))[1:]]
        out.pieces += len(others)
        if len(others):
            held, _ = shapely.STRtree(xy[own[n]]).query(others, predicate="covers")
            out.pieces_held += len(np.unique(held))


def _count_placed(
    out: Figures,
    numbers: Sequence[int],
    shapes: np.ndarray,
    xy: np.ndarray,
    points: Points,
) -> None:
    """Count in *out* the addresses of *points* (at *xy*) and where drawn."""
    # The shapes queried, prepared: the points queried took far longer.
    feature, point = shapely.STRtree(xy).query(shapes, predicate="intersects")
    drawn: defaultdict[int, set[int]] = defaultdict(set)
    for p, f in zip(point.tolist(), feature.tolist(), strict=True):
        drawn[p].add(numbers[f])
    for i, votes in enumerate(points.addresses):
        here = drawn[i]
        for u, n in votes:
            out.addresses += n
            if u in here:
                continue
            if not here:
                out.outside += n
            elif len(votes) > 1:
                out.shared += n
            else:
                out.misplaced += n


def _figure_tasks(
    kind: str,
    units: Sequence[tuple[str, int]],
    geometries: np.ndarray,
    result: Result,
    scale: int,
) -> dict[tuple[str, int], tuple[Any, ...]]:
    """Return the tasks of :func:`figures` of each obec of *units* drawn from points.

    For :func:`parallel.call`, by (*kind* + :data:`_FIGURES`, i). *kind* is
    "council": *units* are the shard features, *geometries* their level 0;
    or "okrsky": *units* are (obec, okrsok) of the okrsky drawn,
    *geometries* their level 0. The points are those of *result*.
    """
    points = result.council_points if kind == "council" else result.okrsky_points
    rows: defaultdict[str, list[int]] = defaultdict(list)
    for i, (c, n) in enumerate(units):
        if n and c in points:
            rows[c].append(i)
    return {
        (kind + _FIGURES, i): (
            figures,
            [units[r][1] for r in mine],
            geometries[mine],
            points[c],
            scale,
        )
        for i, (c, mine) in enumerate(sorted(rows.items()))
    }


def _grid_points(points: Points, to_wgs84: pyproj.Transformer, scale: int) -> Points:
    """Return *points* (EPSG:5514) in WGS84 times *scale*, as the grid is."""
    return replace(points, xy=_to_wgs84(points.xy, to_wgs84) * scale)


def write(result: Result, directory: Path) -> dict[str, int]:
    """Replace *directory* with the files of *result*; return path → bytes."""
    with (
        progress.stage(f"writing {directory.name}/", len(result.files)) as s,
        output.replacing(directory) as tmp,
    ):
        return {
            path: _write_json(tmp / path, content)
            for path, content in s.track(sorted(result.files.items()))
        }


def _write_json(path: Path, content: object) -> int:
    data = output.to_json(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


def report(result: Result, sizes: Mapping[str, int]) -> Iterator[str]:
    """Yield the human-readable summary lines of a written *result*."""
    regional = sum(n for area, n in result.seats.items() if area.isdigit())
    yield "seats per kraj and city:"
    yield "  " + ", ".join(f"{area} {n}" for area, n in result.seats.items())
    yield f"  regional councils in total: {regional}"
    yield f"obvody with fewer candidates than seats: {len(result.short)}"
    for obvod, n, seats in result.short:
        yield f"  {obvod}: {n} candidates for {seats} seats"
    approximate = sorted(c for c, (_, approx, _) in result.council.items() if approx)
    by_ku = sorted(c for c, (_, _, ku) in result.council.items() if ku)
    yield (
        f"obce cut into their council obvody: {len(result.council)}, of which"
        f" {len(by_ku)} by k.ú. and {len(approximate)} approximate (drawn from"
        " their address points, or their k.ú. where each holds one obvod)"
    )
    split = [c for c in result.okrsky if c in result.council]
    yield (
        f"okrsky drawn: {sum(map(len, result.okrsky.values()))} in"
        f" {len(result.okrsky)} obce ({len(split)} cut into council obvody,"
        f" {len(result.okrsky) - len(split)} with one; {OKRSKY_DIR}/);"
        f" known only by obvod in {len(result.okrsky_by_obvod)} obce"
    )
    yield from _figure_lines(result)
    yield "coverage after rounding:     features   vertices  overlap m²  gaps m²"
    for c in result.coverage:
        yield (
            f"  {c.name:<26} {c.features:>7,} {c.vertices:>10,}"
            f" {c.overlap:>10.1f} {c.gaps:>8.1f}"
        )
    yield "files:                  count       total         max"
    groups: dict[str, list[int]] = {}
    for path, size in sizes.items():
        top = path.split("/", 1)[0]
        key = (
            f"{top}/*/{path.rsplit('/', 1)[1]}"
            if top in ("okres", OKRSKY_DIR)
            else path
        )
        groups.setdefault(key, []).append(size)
    for key, group in groups.items():
        yield (
            f"  {key:<20} {len(group):>6} {format_size(sum(group)):>11}"
            f" {format_size(max(group)):>11}"
        )
    yield f"  {'all':<20} {len(sizes):>6} {format_size(sum(sizes.values())):>11}"


def _figure_lines(result: Result) -> Iterator[str]:
    """Yield the :class:`Figures` of *result* as a table."""
    yield (
        "at full detail:  units  pieces (with addresses)  addresses  outside"
        "  shared  misplaced  compactness  borders km"
    )
    names = {
        "council": f"obvody, {len(result.council_points)} obce",
        "okrsky": "okrsky",
    }
    for kind, f in result.figures.items():
        compact = f.compactness / f.units if f.units else 0.0
        yield (
            f"  {names[kind]:<20} {f.units:>5} {f.pieces:>6} ({f.pieces_held:>5})"
            f" {f.addresses:>10,} {f.outside:>8} {f.shared:>7} {f.misplaced:>10}"
            f" {compact:>11.3f} {f.border / 1000:>11.1f}"
        )


# SVG previews for the visual check; not part of the published output.

_PREVIEW_WIDTH = 1600


@dataclass(frozen=True)
class _Sheet:
    files: list[dict[str, Any]]
    fill: str
    """Property whose value picks a feature's fill colour."""
    stroke: Callable[[int], tuple[str, float] | None]
    """Line code → stroke colour and width, or None: not drawn."""
    labels: list[tuple[list[float], str]] = field(default_factory=list)
    obec: str | None = None
    """Draw the features of this obec only."""
    points: Points | None = None
    """Address points to draw (grid units), coloured by their unit (the
    *fill* of the features); one outside its unit ringed red."""


def preview(result: Result, okres: str, directory: Path) -> list[Path]:
    """Write SVG previews of the country, Bratislava and *okres*.

    And of each obec of *okres* cut by its address points into council
    obvody or okrsky, at full detail with those points.
    """
    files = result.files
    if f"okres/{okres}/0.json" not in files:
        raise GeoError(f"preview: no okres {okres}")
    coarse = files[COARSE_FILE]
    ba = next(c for c in CITIES if c.code == "BA")
    city_level = SHARD_LODS[1].level
    districts = [
        files[f"okres/{o}/{city_level}.json"] for o in sorted(ba.district_okresy)
    ]
    shard = files[f"okres/{okres}/0.json"]

    def ranks(code: int) -> tuple[str, float] | None:
        return [("#0006", 0.4), ("#0009", 0.7), ("#000", 1.5), ("#000", 2)][code & RANK]

    def cuts(code: int) -> tuple[str, float] | None:
        if code & COUNCIL:
            return ("#000", 2.5)
        return ("#000", 1.0) if code & OKRSOK else ("#0008", 0.6)

    sheets = {
        "country.svg": _Sheet(
            [coarse],
            "zsk",
            lambda c: ranks(c) if c & RANK else None,
            [(k["label"], k["name"]) for k in coarse["kraje"]],
        ),
        "bratislava.svg": _Sheet(
            districts,
            "city_obvod",
            lambda c: ("#000", 2) if c & CITY else ("#0006", 0.4),
            [
                (o["label"], o["id"])
                for o in coarse["obvody"]
                if o["id"].startswith("oz:BA/")
            ],
        ),
        f"okres-{okres}.svg": _Sheet(
            [shard],
            "zsk",
            ranks,
            # An obec cut into council obvody has its label on one of them.
            [
                (f["properties"]["label"], f["properties"]["name"])
                for f in shard["features"]
                if "label" in f["properties"]
            ],
        ),
    }
    okrsky = files.get(okrsky_path(okres, "0"))
    for code in dict.fromkeys(f["properties"]["id"] for f in shard["features"]):
        if okrsky is not None and code in result.okrsky_points:
            sheets[f"obec-{code}.svg"] = _Sheet(
                [okrsky],
                "okrsok",
                cuts,
                [
                    (o["properties"]["label"], str(o["properties"]["okrsok"]))
                    for o in okrsky["features"]
                    if o["properties"]["obec"] == code
                ],
                code,
                result.okrsky_points[code],
            )
        elif code in result.council_points:
            sheets[f"obec-{code}.svg"] = _Sheet(
                [shard],
                "oz",
                cuts,
                [
                    (o["properties"]["oz_label"], str(o["properties"]["oz"]))
                    for o in shard["features"]
                    if o["properties"]["id"] == code
                ],
                code,
                result.council_points[code],
            )
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, sheet in sheets.items():
        path = directory / name
        path.write_text(_svg(sheet), encoding="utf-8")
        written.append(path)
    return written


def _hue(value: object) -> int:
    """Return the preview's hue of the fill *value*."""
    return int.from_bytes(str(value).encode(), "little") * 137 % 360


def _svg(sheet: _Sheet) -> str:
    decoded = []
    for f in sheet.files:
        arcs, geometries = decode(f)
        rows = [
            i
            for i, feature in enumerate(f["features"])
            if sheet.obec is None
            or sheet.obec
            in (feature["properties"].get("id"), feature["properties"].get("obec"))
        ]
        refs = {
            ~i if i < 0 else i
            for r in rows
            for polygon in f["features"][r]["arcs"]
            for ring in polygon
            for i in ring
        }
        drawn = [(i, a) for i, a in enumerate(arcs) if i in refs]
        decoded.append((f, drawn, rows, geometries))
    xy = np.concatenate([a / f["scale"] for f, arcs, _, _ in decoded for _, a in arcs])
    west, south = xy.min(axis=0)
    east, north = xy.max(axis=0)
    aspect = math.cos(math.radians((south + north) / 2))
    scale = _PREVIEW_WIDTH / ((east - west) * aspect)

    def path(lonlat: np.ndarray) -> str:
        x = (lonlat[:, 0] - west) * aspect * scale
        y = (north - lonlat[:, 1]) * scale
        return "M" + " ".join(f"{a:.1f},{b:.1f}" for a, b in zip(x, y, strict=True))

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_PREVIEW_WIDTH}"'
        f' height="{math.ceil((north - south) * scale)}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
    ]
    for f, _, rows, geometries in decoded:
        for r in rows:
            hue = _hue(f["features"][r]["properties"].get(sheet.fill, ""))
            d = "".join(
                path(shapely.get_coordinates(ring) / f["scale"]) + "Z"
                for p in shapely.get_parts(geometries[r])
                for ring in (p.exterior, *p.interiors)
            )
            out.append(f'<path d="{d}" fill="hsl({hue},55%,75%)" fill-rule="evenodd"/>')
    for f, arcs, _, _ in decoded:
        for i, a in arcs:
            code = f["lines"][i]
            style = None if code & FOREIGN else sheet.stroke(code)
            if style:
                out.append(
                    f'<path d="{path(a / f["scale"])}" fill="none"'
                    f' stroke="{style[0]}" stroke-width="{style[1]}"/>'
                )
    if sheet.points is not None:
        out += _point_marks(sheet, decoded, path)
    for (lon, lat), text in sheet.labels:
        x, y = path(np.array([[lon, lat]]))[1:].split(",")
        out.append(
            f'<text x="{x}" y="{y}" font-size="11" font-family="sans-serif"'
            f' text-anchor="middle">{escape(text)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


def _point_marks(
    sheet: _Sheet,
    decoded: Sequence[tuple[dict[str, Any], Any, list[int], np.ndarray]],
    path: Callable[[np.ndarray], str],
) -> list[str]:
    """Return the SVG of the address points of *sheet*, by the features drawn."""
    assert sheet.points is not None
    f, _, rows, geometries = decoded[0]
    units = [f["features"][r]["properties"][sheet.fill] for r in rows]
    xy = sheet.points.xy
    point, feature = shapely.STRtree(geometries[rows]).query(
        shapely.points(xy), predicate="intersects"
    )
    drawn: defaultdict[int, set[int]] = defaultdict(set)
    for p, k in zip(point.tolist(), feature.tolist(), strict=True):
        drawn[p].add(units[k])
    out = []
    for i, (unit, votes) in enumerate(
        zip(sheet.points.unit.tolist(), sheet.points.addresses, strict=True)
    ):
        x, y = path(xy[i : i + 1] / f["scale"])[1:].split(",")
        ring = (
            ' stroke="#e00" stroke-width="1.5"'
            if any(u not in drawn[i] for u, _ in votes)
            else ""
        )
        out.append(
            f'<circle cx="{x}" cy="{y}" r="1.8"'
            f' fill="hsl({_hue(unit)},70%,30%)"{ring}/>'
        )
    return out
