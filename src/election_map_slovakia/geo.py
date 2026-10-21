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

Output, ``data/build/geo/`` (JSON, compact; codes are strings, obvod numbers
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
                               files: {path: bytes}}

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
approximate (below).

An obec's ``zsk`` is its regional council obvod; ``city`` and ``city_obvod``
are set on the districts of Bratislava and Košice. Obvod membership comes
from ``data/curated/obvody/`` (see :mod:`election_map_slovakia.obvody`).

An obec whose council obvody have a rule set (``data/curated/obvody/oz/``)
is several features in the shards, one per obvod (``oz``; ``oz_label`` and
``oz_parts`` are its own, and the obec's ``label`` and ``parts`` are on the
one that holds its label). Where
the rules name k.ú., the obvody are unions of k.ú.; otherwise they are drawn
from the obvod of every address (``data/build/obvod-addresses/``, the rules
applied): unions of k.ú. where each k.ú. holds addresses of one obvod
(villages whose parts are their k.ú.), else the Voronoi cells of the address
points merged per obvod, within the obec. Both are ``approx``: the true
border runs somewhere between the houses. An obec whose rule set is a
guess (``estimated``, see :mod:`election_map_slovakia.obvody`) has
``estimated`` too. K.ú. unions are made in every
level before level 0 is simplified, so they share the obce's vertices. The
Voronoi cuts are made on the grid, after rounding: cut in metres, rounding
folded the slivers and sharp tips they leave by the border into rings that
cross themselves or run the wrong way. So the cells (simplified per level,
:data:`CUT_TOLERANCE`) are noded with the rounded obec's border by snap
rounding, which gives valid pieces with integer vertices but bends the
border through the points whose pixel it crosses; every feature with such
an edge, the neighbours too, is bent alike (:func:`cut_council`), so the
features stay a coverage that shares its vertices.

Drawn from the address points, obvody would be a patchwork: the rules put
single houses, short streets and addresses without a street in an obvod
whose streets are elsewhere, and between interleaved houses the cells
zigzag. So the drawing prefers plausible areas to exactness: the cells of
the points, clipped to the obec, are smoothed (a cell that shares twice as
much border with another obvod as with its own goes to that one), every
piece of an obvod but its largest goes to the obvod around it unless it
is substantial (:data:`STRAY_SHARE`), and the borders between the obvody
are simplified (:data:`SMOOTH_TOLERANCE`). The address search keeps every
address in the obvod its rules give it; only a click on the map takes the
obvod of the area drawn there.

:func:`verify` (run by ``ems check``) merges the features of each level into
kraje, okresy, obvody and the country with ``coverage_union`` and requires
their borders to be exactly the arcs coded so. :func:`verify_neighbours`
requires the neighbours' borders to be exactly the arcs drawn, and the hole
they leave to be within Slovakia at every level of detail.
"""

from __future__ import annotations

import heapq
import itertools
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
import pyproj
import shapely
from pyproj.enums import TransformDirection

from election_map_slovakia import config, obvody, output, progress
from election_map_slovakia.candidates import (
    CITIES,
    CITY_CODES,
    Admin,
    load_admin,
    search_key,
)
from election_map_slovakia.gpkg import GeoPackage, geometry, srs_id
from election_map_slovakia.output import format_size

# Inputs in config/inputs.toml, by ZBGIS level of detail.
INPUTS = {level: f"zbgis-{level}" for level in range(3)}
NEIGHBOURS_INPUT = "natural-earth-countries"
OUTPUT_DIR = "geo"
PREVIEW_DIR = "preview"
COARSE_FILE = "coarse.json"
SOURCE_SRS = 5514
# EPSG:4836 "S-JTSK to WGS 84 (4)", the Helmert transformation for Slovakia
# (1 m). Left to choose, PROJ may take a Czech variant near the border.
_TRANSFORMATION = ("EPSG", 4836)
DETAIL_TOLERANCE = 2.0
"""``coverage_simplify`` tolerance for level 0, in metres (see module doc)."""
CUT_TOLERANCE = {2: 20.0, 1: 5.0, 0: DETAIL_TOLERANCE}
"""``coverage_simplify`` tolerance of the cuts drawn from address points per
level, in metres: a cut has the detail of the borders it meets."""
COARSE_LEVEL = 2
COARSE_TOLERANCE = 100.0
"""``coverage_simplify`` tolerance for the coarse cells, in metres."""
DECIMALS = 5
BBOX_DECIMALS = 4
# Overlap or gap area tolerated per layer after rounding, in m². Rounding
# leaves triangles of about 0.1 m² where three obce meet; a missing or
# doubled obec is far larger.
MAX_COVERAGE_ERROR = 10.0

# Line codes (see the module doc): a rank, plus flags.
OBEC, OKRES, KRAJ, COUNTRY = range(4)
RANK = 3
ZSK = 4
CITY = 8
FOREIGN = 16
COUNCIL = 32
APPROX = 64

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
_HECTARE = 10_000.0
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
    council_pieces: list[list[float]] = field(default_factory=list)
    """Per council obvod within an obec, the areas of its polygons at full
    detail, m², largest first."""


def transformer() -> pyproj.Transformer:
    """Return the EPSG:5514 → WGS84 (lon, lat) transformation for Slovakia."""
    group = pyproj.transformer.TransformerGroup(
        f"EPSG:{SOURCE_SRS}", "EPSG:4326", always_xy=True
    )
    for t in group.transformers:
        steps = [s.get("id", {}) for s in t.to_json_dict().get("steps", [])]
        if any((s.get("authority"), s.get("code")) == _TRANSFORMATION for s in steps):
            return t
    raise GeoError("PROJ lacks EPSG:4836 (S-JTSK to WGS 84 for Slovakia)")


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
    """Otherwise (obvod, its area, EPSG:5514): the Voronoi cells of the
    obvod's address points, merged."""
    points: Points | None = None
    """And those points."""
    estimated: bool = False
    """Whether the rules themselves are a guess (an estimated rule set)."""


Home = tuple[str, str]
"""An address as a stray piece counts it: its house, and its part."""


@dataclass(frozen=True)
class Points:
    """The address points an obec's cut is drawn from."""

    xy: np.ndarray
    """n × 2, EPSG:5514 (or grid units)."""
    obvod: np.ndarray
    """The obvod of each point."""
    homes: tuple[tuple[Home, ...], ...]
    """The addresses of each point."""


def council_splits(
    curated: Path,
    places_dir: Path,
    kus: Mapping[str, Sequence[Ku]],
    to_wgs84: pyproj.Transformer,
) -> dict[str, Split]:
    """Return obec → its cut, for every obec with a rule set.

    *places_dir* holds the addresses ``ems addresses`` wrote
    (:func:`election_map_slovakia.obvody.write_places`); *kus* is
    :func:`read_kus` of level 0.
    """
    out = {}
    for code, rules in obvody.load_rule_sets(curated).items():
        path = places_dir / f"{code}.json"
        if not path.is_file():
            raise GeoError(f"{path} missing; run `ems addresses` first")
        p = obvody.load_places(path)
        a = obvody.assign(rules, p.places, p.kus, p.planar())
        problems = a.problems(p.places)
        if problems:
            raise GeoError(f"{rules.name} ({code}): " + "; ".join(problems))
        out[code] = council_split(rules, p, a.obvody, kus.get(code, []), to_wgs84)
    return out


def council_split(
    rules: obvody.RuleSet,
    places: obvody.ObecPlaces,
    assigned: Sequence[int],
    kus: Sequence[Ku],
    to_wgs84: pyproj.Transformer,
) -> Split:
    """Return how to cut an obec with *rules* (see :func:`council_splits`).

    *assigned* is the obvod of each of *places*, *kus* the obec's k.ú.
    """
    numbers = tuple(rules.seats)
    located = ~np.isnan(places.points[:, 0])
    lon, lat = places.points[located].T / 10**DECIMALS
    x, y = to_wgs84.transform(lon, lat, direction=TransformDirection.INVERSE)
    xy = np.column_stack([x, y])
    obvod = np.array(assigned)[located]
    ku_obvod = _ku_obvody(rules, places, assigned, kus)
    if ku_obvod is not None:
        return Split(
            numbers,
            not rules.by_ku,
            _with_empty_kus(ku_obvod, kus, xy, obvod),
            estimated=rules.estimated,
        )
    # One point per place: entrances of a block can share it, rarely across
    # obvody, where the more frequent one takes it.
    keys, inverse = np.unique(np.round(xy, 2), axis=0, return_inverse=True)
    votes: dict[int, Counter[int]] = {}
    homes: list[list[Home]] = [[] for _ in keys]
    rows = np.flatnonzero(located).tolist()
    for k, o, i in zip(inverse.ravel().tolist(), obvod.tolist(), rows, strict=True):
        votes.setdefault(k, Counter())[o] += 1
        # A house by its súpisné číslo alone: the register has some twice,
        # at one point, in two parts (Rykynčice).
        p = places.places[i]
        homes[k].append((p.supisne or f"@{k}", p.part))
    chosen = np.array(
        [min(v, key=lambda o: (-v[o], o)) for _, v in sorted(votes.items())]
    )
    if not kus:
        raise GeoError(f"{rules.name} ({rules.obec}): no k.ú.")
    obec = shapely.coverage_union_all([g for _, _, g in kus])
    split = _voronoi_split(numbers, keys, chosen, homes, obec)
    return replace(split, estimated=rules.estimated)


STRAY_HOUSES = 10
STRAY_SHARE = 0.1
"""A piece of an obvod drawn from address points, other than its largest,
is a stray, drawn in the obvod around it, unless it has at least
:data:`STRAY_HOUSES` houses and either :data:`STRAY_SHARE` of the obvod's
addresses or most of the addresses of a part of the obec (a village of a
town). A piece without any address point is always a stray: a Voronoi
cell cut in two by the obec's border, or a sliver of the simplified cuts.

The rules put many addresses in an obvod whose streets are elsewhere:
addresses without a street that a rule by part or the rest places, houses
far from the rest of their street (a wrong point, or a number the rule did
not mean), points the register has twice, and short streets or blocks that
the document puts in another obvod, by name or by number. Drawn, they were
islands and slivers: in the 2026 rule sets, at full detail, the 612 obvody
had 297 pieces besides their largest, 99 of them under a hectare (Lučenec
24, Bratislava-Vrakuňa 23, Brezno 21); now 46, one under a hectare. Kept
are a separate village or a large cluster (Michalovce, obvod 6: three
villages; Nové Zámky, obvod 2: a dense cluster in the north)."""
SMOOTH_ROUNDS = 10
SMOOTH_MAJORITY = 2.0
"""At most :data:`SMOOTH_ROUNDS` passes over the cells smooth an obvod
drawn from address points: each moves a cell that shares more than
:data:`SMOOTH_MAJORITY` times as much border with another obvod as with
its own to that one, removing the fingers and lone cells of interleaved
houses. A bare majority let large cells where houses are sparse, about
even between two obvody, flip one after another into a long wedge
(Skalité)."""
SMOOTH_TOLERANCE = 25.0
"""``coverage_simplify`` tolerance, in metres, of the borders between the
obvody drawn from address points: their Voronoi edges zigzag between the
houses."""


def _voronoi_split(
    numbers: tuple[int, ...],
    xy: np.ndarray,
    obvod: np.ndarray,
    homes: Sequence[Sequence[Home]],
    obec: Any,
) -> Split:
    """Return the cut by the Voronoi cells of the address points *xy*.

    *obvod* and *homes* are the obvod and the addresses of each point,
    *obec* its area (EPSG:5514). The cells are smoothed and freed of strays
    within *obec* (see the module doc) and reach beyond it, so that the
    cut fits the obec's border at every level of detail.
    """
    points = Points(xy, obvod, tuple(tuple(h) for h in homes))
    present = sorted(set(obvod.tolist()))
    if len(present) == 1:
        whole = shapely.box(*shapely.multipoints(xy).bounds).buffer(1e6)
        return Split(numbers, True, None, ((present[0], whole),), points)
    box = shapely.box(*shapely.multipoints(xy).bounds).buffer(1e5)
    cells = shapely.get_parts(
        shapely.voronoi_polygons(shapely.multipoints(xy), extend_to=box, ordered=True)
    )
    if len(cells) != len(xy):
        raise GeoError(f"{len(cells)} Voronoi cells for {len(xy)} points")
    faces, cell, seeded = _faces(cells, obec, xy)
    borders = _borders(faces)
    drawn = _smoothed(borders, obvod[cell])
    kept = seeded & (drawn == obvod[cell])
    drawn = _unstrayed(
        borders,
        drawn,
        [points.homes[c] if k else () for c, k in zip(cell, kept, strict=True)],
        _stray(points),
    )
    # Each cell in the obvod of its point's face (else of one of its faces):
    # beyond the obec it is all there is.
    cell_obvod = obvod.copy()
    first = np.flatnonzero(~seeded)
    cell_obvod[cell[first]] = drawn[first]
    cell_obvod[cell[seeded]] = drawn[seeded]
    regions = shapely.coverage_simplify(
        np.array([shapely.coverage_union_all(cells[cell_obvod == n]) for n in present]),
        SMOOTH_TOLERANCE,
        simplify_boundary=False,
    )
    return Split(numbers, True, None, tuple(zip(present, regions, strict=True)), points)


def _faces(
    cells: np.ndarray, obec: Any, xy: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the Voronoi *cells* of points *xy* cut by the border of *obec*.

    Returns the faces within *obec*, which share their borders vertex for
    vertex (:func:`_borders`), the cell of each, and whether it holds the
    cell's point.
    """
    lines = shapely.intersection(shapely.union_all(shapely.boundary(cells)), obec)
    edges = shapely.union_all([shapely.boundary(obec), lines])
    faces = shapely.get_parts(shapely.polygonize(shapely.get_parts(edges)))
    inner = shapely.point_on_surface(faces)
    keep = shapely.intersects(obec, inner)
    faces, inner = faces[keep], inner[keep]
    tree = shapely.STRtree(cells)
    face, found = tree.query(inner, predicate="within")
    cell = np.full(len(faces), -1)
    cell[face] = found
    # An inner point on a cell's border is within none: the nearest.
    for i in np.flatnonzero(cell < 0).tolist():
        cell[i] = tree.query_nearest(inner[i], all_matches=False)[0]
    return faces, cell, shapely.contains(faces, shapely.points(xy[cell]))


def _smoothed(
    borders: Sequence[tuple[int, int, float]], obvod: np.ndarray
) -> np.ndarray:
    """Return the obvod of each face, smoothed (see :data:`SMOOTH_ROUNDS`).

    *borders* are those of the faces (:func:`_borders`), *obvod* the obvod of
    each. The last face of an obvod stays.
    """
    around: list[list[tuple[int, float]]] = [[] for _ in obvod]
    for i, j, s in borders:
        around[i].append((j, s))
        around[j].append((i, s))
    out = obvod.copy()
    count = Counter(out.tolist())
    for _ in range(SMOOTH_ROUNDS):
        moved = False
        for i, near in enumerate(around):
            shared: defaultdict[int, float] = defaultdict(float)
            for j, s in near:
                shared[int(out[j])] += s
            own = int(out[i])
            to = min(shared, key=lambda o: (-shared[o], o), default=own)
            if shared[to] > SMOOTH_MAJORITY * shared[own] and count[own] > 1:
                count[own] -= 1
                count[to] += 1
                out[i] = to
                moved = True
        if not moved:
            break
    return out


def _stray(points: Points) -> Callable[[_Piece], bool]:
    """Return whether a piece of a cut drawn from *points* is a stray.

    See :data:`STRAY_HOUSES`.
    """
    totals: Counter[int] = Counter()
    in_part: Counter[str] = Counter()
    for o, h in zip(points.obvod.tolist(), points.homes, strict=True):
        totals[o] += len(h)
        in_part.update(part for _, part in h)

    def stray(p: _Piece) -> bool:
        return len(p.houses) < STRAY_HOUSES or (
            p.addresses < STRAY_SHARE * totals[p.obvod]
            and all(2 * n <= in_part[part] for part, n in p.parts.items())
        )

    return stray


@dataclass
class _Piece:
    """Faces of one obvod that share borders, as :func:`_unstrayed` grows them."""

    obvod: int
    faces: list[int] = field(default_factory=list)
    houses: set[str] = field(default_factory=set)
    parts: Counter[str] = field(default_factory=Counter)
    addresses: int = 0
    borders: defaultdict[int, float] = field(default_factory=lambda: defaultdict(float))
    """Length of border with each neighbouring piece (of another obvod)."""

    def add(self, faces: Iterable[int], homes: Iterable[Home]) -> None:
        self.faces += faces
        for house, part in homes:
            self.houses.add(house)
            self.parts[part] += 1
            self.addresses += 1


def _borders(cells: np.ndarray) -> list[tuple[int, int, float]]:
    """Return (i, j, length) for each pair of *cells* that share a border.

    The cells share their borders vertex for vertex (they are polygonized
    from noded lines), so a border is the same segments on both sides.
    Cells that meet in a point share none: drawn, they are separate pieces.
    """
    rings, cell = shapely.get_rings(cells, return_index=True)
    xy, ring = shapely.get_coordinates(rings, return_index=True)
    along = ring[:-1] == ring[1:]
    a, b = xy[:-1][along], xy[1:][along]
    owner = cell[ring[:-1][along]]
    swap = ((a[:, 0] > b[:, 0]) | ((a[:, 0] == b[:, 0]) & (a[:, 1] > b[:, 1])))[:, None]
    segments = np.column_stack([np.where(swap, b, a), np.where(swap, a, b)])
    _, inverse = np.unique(segments, axis=0, return_inverse=True)
    order = np.argsort(inverse.ravel(), kind="stable")
    key = inverse.ravel()[order]
    twin = np.flatnonzero(key[:-1] == key[1:])
    first, second = order[twin], order[twin + 1]
    length = np.hypot(*(segments[first, 2:] - segments[first, :2]).T)
    shared: defaultdict[tuple[int, int], float] = defaultdict(float)
    for i, j, s in zip(
        owner[first].tolist(), owner[second].tolist(), length.tolist(), strict=True
    ):
        if s > 0 and i != j:
            shared[min(i, j), max(i, j)] += s
    return [(i, j, s) for (i, j), s in shared.items()]


def _pieces(
    borders: Sequence[tuple[int, int, float]],
    obvod: np.ndarray,
    homes: Sequence[Sequence[Home]],
) -> dict[int, _Piece]:
    """Return the pieces of the faces of a cut (see :func:`_unstrayed`)."""
    root = list(range(len(obvod)))

    def find(i: int) -> int:
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    for i, j, _ in borders:
        if obvod[i] == obvod[j]:
            root[find(i)] = find(j)
    pieces: dict[int, _Piece] = {}
    for i, h in enumerate(homes):
        pieces.setdefault(find(i), _Piece(int(obvod[i]))).add([i], h)
    for i, j, s in borders:
        a, b = find(i), find(j)
        if a != b:
            pieces[a].borders[b] += s
            pieces[b].borders[a] += s
    return pieces


def _unstrayed(
    borders: Sequence[tuple[int, int, float]],
    obvod: np.ndarray,
    homes: Sequence[Sequence[Home]],
    stray: Callable[[_Piece], bool],
) -> np.ndarray:
    """Return the obvod each face of a cut is drawn in.

    The faces tile the obec, with *borders* (:func:`_borders`), each in
    obvod *obvod* with addresses *homes*. A piece of an obvod (faces that
    share borders) other than its largest goes to the obvod it shares the
    most border with if it is a *stray*, the smallest first, so that the
    obvody stay one piece but for exclaves. A stray touching no other obvod
    (an obec in two pieces) stays.
    """
    pieces = _pieces(borders, obvod, homes)
    largest: dict[int, int] = {}
    for r, p in pieces.items():
        if p.addresses > pieces[largest.setdefault(p.obvod, r)].addresses:
            largest[p.obvod] = r
    kept = set(largest.values())

    def is_stray(r: int) -> bool:
        return r not in kept and stray(pieces[r])

    drawn = obvod.copy()
    # A piece only grows, so one that is no stray never becomes one.
    queue = [(len(p.houses), p.addresses, r) for r, p in pieces.items()]
    queue = [q for q in queue if is_stray(q[2])]
    heapq.heapify(queue)
    while queue:
        _, _, r = heapq.heappop(queue)
        if r not in pieces or not is_stray(r):
            continue
        p = pieces[r]
        around: defaultdict[int, float] = defaultdict(float)
        for q, s in p.borders.items():
            around[pieces[q].obvod] += s
        if not around:
            continue
        to = min(around, key=lambda o: (-around[o], o))
        drawn[p.faces] = to
        # Now of obvod *to*, it joins every piece of it that it borders.
        group = [r, *(q for q in p.borders if pieces[q].obvod == to)]
        into = max(group, key=lambda q: (q in kept, pieces[q].addresses, q))
        _join(pieces, group, into, to)
        if is_stray(into):
            heapq.heappush(
                queue, (len(pieces[into].houses), pieces[into].addresses, into)
            )
    return drawn


def _join(pieces: dict[int, _Piece], group: list[int], into: int, obvod: int) -> None:
    """Merge the neighbouring *pieces* of *group* into *into*, of *obvod*."""
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
            joined.houses |= g.houses
            joined.parts += g.parts
            joined.addresses += g.addresses
    joined.obvod = obvod
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
        named = {code_of[search_key(r.ku)]: r.obvod for r in rules.rules if r.ku}
        rest = next((r.obvod for r in rules.rules if r.rest), None)
        if rest is not None:
            named |= {c: rest for c, _, _ in kus if c not in named}
        return named
    per: dict[str, set[int]] = {}
    for ku, o in zip(places.kus, assigned, strict=True):
        if ku is not None:
            per.setdefault(code_of[search_key(ku)], set()).add(o)
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

    def grid(xy: np.ndarray) -> np.ndarray:
        lon, lat = to_wgs84.transform(xy[:, 0], xy[:, 1])
        return np.column_stack([lon, lat]) * scale

    return shapely.transform(geometries, grid)


def cut_council(
    units: Sequence[Unit],
    gridded: np.ndarray,
    splits: Mapping[str, Split],
    to_wgs84: pyproj.Transformer,
    scale: int,
) -> tuple[list[Unit], np.ndarray]:
    """Cut the obce of *splits* by address points into their council obvody.

    *gridded* are the features *units* rounded to the grid (:func:`to_grid`).
    Each such obec is cut along the borders of its obvody's regions, the
    cuts noded with its border and rounded to the grid by snap rounding, so
    the pieces are valid as they will be drawn. Snap rounding bends an edge
    of the border through the points whose pixel it crosses: where a cut
    meets it, and vertices closer than half a unit. Every feature with that
    edge, the neighbour too, gets the same points (:func:`_bend`), so all
    stay a coverage that shares its vertices. Returns the features with
    those obce replaced by their pieces, in grid units.
    """
    voronoi = {i for i, (c, n) in enumerate(units) if not n and c in splits}
    out_units: list[Unit] = []
    out: list[Any] = []
    whole: list[tuple[str, Any, list[int], list[int]]] = []
    bends: dict[_Edge, set[_Point]] = {}
    for i, unit in enumerate(units):
        if i not in voronoi:
            out_units.append(unit)
            out.append(gridded[i])
            continue
        code = unit[0]
        split = splits[code]
        assert split.points is not None
        regions = [(n, to_grid_float(g, to_wgs84, scale)) for n, g in split.regions]
        x, y = to_wgs84.transform(*split.points.xy.T)
        points = replace(split.points, xy=np.column_stack([x, y]) * scale)
        pieces = _grid_cut(code, gridded[i], regions, points, bends)
        rows = list(range(len(out), len(out) + len(pieces)))
        whole.append((code, gridded[i], [n for n, _ in regions], rows))
        out_units += [(code, n) for n, _ in pieces]
        out += [g for _, g in pieces]
    chains = _Chains(bends)
    geometries = _bend(np.array(out), chains)
    for code, obec, numbers, rows in whole:
        _check_cut(
            code,
            _bend(np.array([obec]), chains)[0],
            [(out_units[r][1], geometries[r]) for r in rows],
            numbers,
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


_Point = tuple[float, float]
_Edge = tuple[_Point, _Point]
"""An edge by its end points, the lesser first."""


def _grid_cut(
    code: str,
    obec: Any,
    regions: Sequence[tuple[int, Any]],
    points: Points,
    bends: dict[_Edge, set[_Point]],
) -> list[tuple[int, Any]]:
    """Return gridded *obec* cut by *regions* (grid units), one piece per obvod.

    The regions are drawn from *points* (grid units); their stray pieces
    (:data:`STRAY_HOUSES`) go to the obvod around them. Adds to *bends*, per
    edge of *obec*, the points snap rounding bent it through: the vertices
    of the pieces' outline in whose pixel the edge does not end.
    """
    if len(regions) == 1:
        return [(regions[0][0], obec)]
    areas = np.array([g for _, g in regions])
    # Rounding can fold an obec's border across itself; its rings are kept as
    # they are (its neighbours have the same), only what is inside is asked
    # of a valid version.
    inside = obec if shapely.is_valid(obec) else shapely.make_valid(obec)
    lines = shapely.intersection(shapely.union_all(shapely.boundary(areas)), inside)
    edges = shapely.union_all([shapely.boundary(obec), lines], grid_size=1.0)
    faces = shapely.get_parts(shapely.polygonize(shapely.get_parts(edges)))
    inner = shapely.point_on_surface(faces)
    keep = shapely.intersects(inside, inner)
    faces, inner = faces[keep], inner[keep]
    tree = shapely.STRtree(areas)
    face, region = tree.query(inner, predicate="within")
    owner = dict(zip(face.tolist(), region.tolist(), strict=False))
    # A face's inner point on a region's border is within none: the nearest.
    for i in sorted(set(range(len(faces))) - owner.keys()):
        owner[i] = int(tree.query_nearest(inner[i], all_matches=False)[0])
    obvod = np.array([regions[owner[i]][0] for i in range(len(faces))])
    # Each point to a face of its obvod it is in, or within a pixel of:
    # rounding moves the border.
    face, seed = shapely.STRtree(shapely.points(points.xy)).query(
        faces, predicate="dwithin", distance=1.0
    )
    homes: list[list[Home]] = [[] for _ in faces]
    placed: set[int] = set()
    for f, s in zip(face.tolist(), seed.tolist(), strict=True):
        if obvod[f] == points.obvod[s] and s not in placed:
            placed.add(s)
            homes[f] += points.homes[s]
    obvod = _unstrayed(_borders(faces), obvod, homes, _stray(points))
    groups: dict[int, list[Any]] = {}
    for f, n in zip(faces, obvod.tolist(), strict=True):
        groups.setdefault(n, []).append(f)
    outline = np.unique(
        shapely.get_coordinates(shapely.coverage_union_all(faces)), axis=0
    )
    for ring in shapely.get_parts(shapely.boundary(obec)):
        a, b = _segments_of(ring)
        p, e = _crossings(a, b, outline)
        for i, k in zip(p.tolist(), e.tolist(), strict=True):
            bends.setdefault(_edge(a[k], b[k]), set()).add(tuple(outline[i]))
    pieces = [(n, shapely.coverage_union_all(groups[n])) for n in sorted(groups)]
    if not shapely.is_valid(np.array([g for _, g in pieces])).all():
        raise GeoError(f"obec {code}: a council obvod is not a valid polygon")
    return pieces


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


def _segments_of(ring: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return the start and end points of the edges of *ring*."""
    xy = shapely.get_coordinates(ring)
    return xy[:-1], xy[1:]


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
                points, key=lambda p: (p[0] - a[0]) * dx + (p[1] - a[1]) * dy
            )
            for position, p in enumerate([a, *inner, b]):
                self.where.setdefault(p, {})[len(self.chains)] = position
            self.chains.append([a, *inner, b])

    def between(self, u: _Point, w: _Point) -> list[_Point]:
        """Return the points of a chain strictly between *u* and *w*, from *u*."""
        at_u, at_w = self.where.get(u), self.where.get(w)
        if not at_u or not at_w:
            return []
        for chain, i in at_u.items():
            j = at_w.get(chain)
            if j is not None and abs(j - i) > 1:
                points = self.chains[chain]
                return points[i + 1 : j] if i < j else points[j + 1 : i][::-1]
        return []


def _bend(geometries: np.ndarray, chains: _Chains) -> np.ndarray:
    """Return *geometries* with every edge of a chain bent through its points.

    An edge from one point of a chain to a later (or earlier) one gets the
    points between them, so a border that two features share, whole or in
    part bent already (the pieces of a cut obec), ends up with the same
    vertices in both. A spike the bending folds flat is dropped, as
    :func:`rings` drops it (both sides alike): left in, its tip can be the
    uppermost vertex, from which the orientation of a ring is read.
    """
    if not chains.chains:
        return geometries
    out = geometries.copy()
    for f, feature in enumerate(geometries):
        polygons = []
        changed = False
        for part in shapely.get_parts(feature):
            rings = []
            for ring in (part.exterior, *part.interiors):
                xy = shapely.get_coordinates(ring)
                bent = _bend_ring(xy, chains)
                if bent is None:
                    rings.append(xy)
                    continue
                changed = True
                if len(bent) >= _MIN_RING:
                    rings.append(bent)
                elif not rings:
                    break  # the exterior folded flat, and its holes with it
            if rings:
                polygons.append(shapely.Polygon(rings[0], rings[1:]))
        if changed:
            out[f] = (
                polygons[0] if len(polygons) == 1 else shapely.MultiPolygon(polygons)
            )
    return out


def _bend_ring(xy: np.ndarray, chains: _Chains) -> np.ndarray | None:
    """Return the closed ring *xy* bent and cleaned, open; None if unbent."""
    keys = [(x, y) for x, y in xy.tolist()]
    filled: list[_Point] = [keys[0]]
    for u, w in itertools.pairwise(keys):
        filled += chains.between(u, w)
        filled.append(w)
    if len(filled) == len(keys):
        return None
    return _clean(np.array(filled[:-1]))


def _is_obvod_contest(contest: Mapping[str, Any]) -> bool:
    return contest["kind"] == "zsk" or (
        contest["kind"] == "oz" and contest["area"] in CITY_CODES
    )


Membership = tuple[config.ObvodList, dict[int, tuple[str, ...]]]
"""A membership file and its obvody resolved to obce."""


def memberships(
    curated: Path, admin: Admin, contests: Iterable[Mapping[str, Any]]
) -> dict[str, Membership]:
    """Return file name → membership for every kraj and for BA / KE.

    All membership files are checked before failing, so one run lists every
    problem.
    """
    expected = Counter(str(c["area"]) for c in contests if _is_obvod_contest(c))
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
        listed = config.load_obvody(curated / obvody.DIRECTORY / f"{name}.toml")
        try:
            result[name] = (listed, obvody.resolve(listed, obce, expected[area]))
        except obvody.ObvodyError as e:
            errors.append(str(e))
    if errors:
        raise obvody.ObvodyError("\n".join(errors))
    return result


def obec_properties(
    admin: Admin,
    codes: Sequence[str],
    members: Mapping[str, Membership],
) -> dict[str, dict[str, Any]]:
    """Return obec → its shard properties without ``label``; see the module doc.

    *members* is the result of :func:`memberships`.
    """
    props: dict[str, dict[str, Any]] = {}
    for c in codes:
        o = admin.obce[c]
        props[c] = {"id": c, "name": o.name, "okres": o.okres, "kraj": o.kraj}
    for kraj in admin.kraje:
        for n, area in members[f"zsk-{kraj}"][1].items():
            for c in area:
                props[c]["zsk"] = n
    for city in CITIES:
        for n, area in members[city.code][1].items():
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

    def grid(xy: np.ndarray) -> np.ndarray:
        lon, lat = to_wgs84.transform(xy[:, 0], xy[:, 1])
        return np.rint(np.column_stack([lon, lat]) * scale)

    return shapely.orient_polygons(shapely.transform(geometries, grid))


Rings = list[list[np.ndarray]]
"""A feature's polygons, each a list of rings: open int64 vertex arrays."""


def rings(geometry: shapely.Geometry) -> Rings:
    """Return the polygons of a gridded *geometry* (see :func:`to_grid`).

    Repeated vertices and the tips of spikes folded flat are dropped (see the
    module doc), and so are rings left with fewer than three vertices.
    """
    polygons = []
    for part in shapely.get_parts(geometry):
        out = []
        for ring in (part.exterior, *part.interiors):
            xy = _clean(shapely.get_coordinates(ring)[:-1].astype(np.int64))
            if len(xy) >= _MIN_RING:
                out.append(xy)
            elif not out:
                break  # the exterior collapsed, and its holes with it
        if out:
            polygons.append(out)
    return polygons


def _clean(xy: np.ndarray) -> np.ndarray:
    while len(xy) >= _MIN_RING:
        xy = xy[np.any(xy != np.roll(xy, 1, axis=0), axis=1)]
        spike = np.all(np.roll(xy, 1, axis=0) == np.roll(xy, -1, axis=0), axis=1)
        if not spike.any():
            break
        xy = xy[~spike]
    return xy


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
    keys = [_keys(xy) for *_, xy in flat]
    a = np.concatenate(keys)
    b = np.concatenate([np.roll(k, -1) for k in keys])
    edges, _ = _unique_rows(np.column_stack([np.minimum(a, b), np.maximum(a, b)]))
    vertex, degree = np.unique(edges, return_counts=True)
    is_junction = np.isin(a, vertex[degree != _SIDES])
    starts = np.cumsum([len(k) for k in keys])[:-1]
    topo = Topology([], [[[[] for _ in p] for p in f] for f in features], [])
    index: dict[bytes, int] = {}
    ways: list[list[bool]] = []
    for (f, p, r, xy), k, junction in zip(
        flat, keys, np.split(is_junction, starts), strict=True
    ):
        at = np.flatnonzero(junction)
        start = int(at[0]) if len(at) else int(np.argmin(k))
        k = np.roll(k, -start)
        k = np.append(k, k[0])
        xy = np.roll(xy, -start, axis=0)
        xy = np.vstack([xy, xy[:1]])
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
    arcs, lines = [], []
    for i in local:
        xy = topo.arcs[i]
        arcs.append(np.concatenate([xy[:1], np.diff(xy, axis=0)]).ravel().tolist())
        lines.append(code([properties[s] for s in topo.sides[i]]))
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
    xy = label_points(geometries)
    lon, lat = to_wgs84.transform(xy[:, 0], xy[:, 1])
    return np.round(np.column_stack([lon, lat]), DECIMALS).tolist()


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
    labelled: dict[str, int] = {}
    for i in pieces:
        code = units[i][0]
        if shapely.intersects_xy(gridded[i], *centres[code]):
            labelled.setdefault(code, i)
    out = []
    for i, (code, n) in enumerate(units):
        p = dict(props[code])
        if n:
            if labelled.get(code, next(j for j in pieces if units[j][0] == code)) != i:
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


def grid_levels(
    bases: Sequence[Unit],
    obce: Mapping[int, np.ndarray],
    splits: Mapping[str, Split],
    to_wgs84: pyproj.Transformer,
    scale: int,
) -> tuple[list[Unit], dict[int, np.ndarray]]:
    """Return the shard features and each level rounded to the grid.

    *bases* and *obce* are :func:`obec_levels`; the obce cut by their address
    points are cut here (:func:`cut_council`), alike at every level, their
    cuts simplified as the level's borders are (:data:`CUT_TOLERANCE`).
    """
    gridded: dict[int, np.ndarray] = {}
    units: list[Unit] = []
    for lod in SHARD_LODS:
        with progress.stage(f"rounding level {lod.level} and cutting council obvody"):
            simple = {
                code: replace(s, regions=_simplified(s.regions, lod.level))
                for code, s in splits.items()
            }
            here, gridded[lod.level] = cut_council(
                bases,
                to_grid(obce[lod.level], to_wgs84, scale),
                simple,
                to_wgs84,
                scale,
            )
        if units and here != units:
            raise GeoError(
                f"level {lod.level}: the council obvody cut differently than at"
                f" level {SHARD_LODS[0].level}"
            )
        units = here
    return units, gridded


def _simplified(
    regions: tuple[tuple[int, Any], ...], level: int
) -> tuple[tuple[int, Any], ...]:
    """Return *regions* (a coverage) simplified for ZBGIS *level*."""
    if len(regions) < _SIDES:
        return regions
    simple = shapely.coverage_simplify(
        np.array([g for _, g in regions]), CUT_TOLERANCE[level]
    )
    return tuple((n, g) for (n, _), g in zip(regions, simple, strict=True))


def build(
    paths: Mapping[int, Path],
    countries: Path,
    curated: Path,
    places: Path,
    contests: Sequence[Mapping[str, Any]],
    candidates: Mapping[str, int],
) -> Result:
    """Build and check all output files; see the module doc.

    *paths* maps each ZBGIS level to its GeoPackage, *countries* is the
    Natural Earth GeoJSON; *places* the addresses of the obce with several
    council obvody (``data/build/obvod-addresses/``); *contests* are those
    of ``candidates.json``, *candidates* the number of candidacies per
    contest.
    """
    admin = load_admin(paths[0])
    with progress.stage("checking the obvod membership in data/curated/obvody/"):
        members = memberships(curated, admin, contests)
    to_wgs84 = transformer()
    with progress.stage("placing the addresses of the council obvody by their rules"):
        splits = council_splits(curated, places, read_kus(paths[0]), to_wgs84)
    codes = obec_codes(admin)
    bases, obce = obec_levels(paths, admin, splits)
    props = obec_properties(admin, codes, members)
    scale = 10**DECIMALS
    units, gridded = grid_levels(bases, obce, splits, to_wgs84, scale)
    with progress.stage("placing the obce labels"):
        merged = merge_units(bases, obce[0])
        centres = label_points(merged)
        for c, xy, parts in zip(
            codes, centres, part_labels(merged, to_wgs84), strict=True
        ):
            props[c]["label"] = lonlat(xy, to_wgs84)
            if parts:
                props[c]["parts"] = parts
        grid_centres = {c: np.array(props[c]["label"]) * scale for c in splits}
        properties = unit_properties(
            units, gridded[0], props, grid_centres, splits, scale
        )
    result = Result({})
    result.council = {
        c: (len(s.numbers), s.approximate, s.kus is not None) for c, s in splits.items()
    }
    m2 = _M2_PER_DEGREE2 / scale**2
    result.council_pieces = [
        sorted((shapely.area(shapely.get_parts(g)) * m2).tolist(), reverse=True)
        for (_, n), g in zip(units, gridded[0], strict=True)
        if n
    ]
    bboxes: dict[str, list[float]] = {}
    okres_rows = {
        okres: [i for i, p in enumerate(properties) if p["okres"] == okres]
        for okres in sorted(admin.okresy)
    }
    for lod in SHARD_LODS:
        with progress.stage(f"level of detail {lod.level}"):
            features = [rings(g) for g in gridded[lod.level]]
            with progress.stage("cutting the borders into arcs"):
                topo = topology(features, scale)
                for okres, rows in okres_rows.items():
                    result.files[f"okres/{okres}/{lod.level}.json"] = topology_file(
                        topo, scale, rows, properties, unit_code(okres)
                    )
                    if lod is SHARD_LODS[-1]:
                        xy = np.concatenate(
                            [r for f in rows for p in features[f] for r in p]
                        )
                        bboxes[okres] = _bbox(xy / scale)
            with progress.stage("measuring overlaps and gaps"):
                result.coverage.append(
                    coverage(
                        f"okres/*/{lod.level}.json obce",
                        features,
                        topo,
                        scale,
                        to_wgs84,
                    )
                )
    with progress.stage("coarse view"):
        coarse, cells = _coarse(
            merge_units(bases, obce[COARSE_LEVEL]),
            [props[c] for c in codes],
            admin,
            members,
            to_wgs84,
        )
    result.files[COARSE_FILE] = coarse
    result.coverage.insert(0, cells)
    drawn = {o["id"] for o in coarse["obvody"]}
    missing = sorted(
        str(c["id"]) for c in contests if _is_obvod_contest(c) and c["id"] not in drawn
    )
    if missing:
        raise GeoError(f"contests without an obvod: {', '.join(missing)}")
    for o in coarse["obvody"]:
        area = o["id"].split(":")[1].split("/")[0]
        result.seats[area] = result.seats.get(area, 0) + o["seats"]
        if candidates.get(o["id"], 0) < o["seats"]:
            result.short.append((o["id"], candidates.get(o["id"], 0), o["seats"]))
    bad = [
        f"{c.name}: overlap {c.overlap:.1f} m², gaps {c.gaps:.1f} m²"
        for c in result.coverage
        if max(c.overlap, c.gaps) > MAX_COVERAGE_ERROR
    ]
    if bad:
        raise GeoError("\n  ".join(["neighbours do not share borders:", *bad]))
    result.files["index.json"] = {
        "shards": [
            {"lod": str(lod.level), "zoom": [lod.from_zoom, lod.until_zoom]}
            for lod in SHARD_LODS
        ],
        "okresy": bboxes,
        "neighbours": [
            {
                "lod": str(n.level),
                "zoom": [n.from_zoom, n.until_zoom],
                "extent": list(n.extent),
            }
            for n in NEIGHBOUR_LODS
        ],
    }
    with progress.stage("countries around Slovakia"):
        _add_neighbours(
            result.files,
            countries,
            shapely.coverage_union_all(obce[COARSE_LEVEL]),
            to_wgs84,
        )
    return result


def _add_neighbours(
    files: dict[str, dict[str, Any]],
    countries: Path,
    slovakia: Any,
    to_wgs84: pyproj.Transformer,
) -> None:
    """Add the countries around *slovakia* to *files*, which have all else.

    Fails unless they meet it at every level of detail (see the module doc).
    """
    areas = neighbour_areas(read_countries(countries, to_wgs84), slovakia)
    with progress.stage("placing their names"):
        spots = {k: label_spots(g, slovakia, to_wgs84) for k, g in areas.items()}
    for n in NEIGHBOUR_LODS:
        files[neighbours_path(str(n.level))] = neighbours_file(
            areas, spots, n, to_wgs84
        )
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
        land = _polygonal(shapely.intersection(land, extent))
        out[code] = shapely.union(out[code], land) if code in out else land
    if "SK" not in out:
        raise GeoError(f"{path.name}: no Slovakia")
    return {k: _metres(g, to_wgs84) for k, g in out.items()}


def _metres(lonlat: Any, to_wgs84: pyproj.Transformer) -> Any:
    """Return WGS84 *lonlat* in EPSG:5514, its long edges bent as they project."""

    def back(xy: np.ndarray) -> np.ndarray:
        x, y = to_wgs84.transform(
            xy[:, 0], xy[:, 1], direction=TransformDirection.INVERSE
        )
        return np.column_stack([x, y])

    return shapely.transform(shapely.segmentize(lonlat, 0.05), back)


def _polygonal(g: Any) -> Any:
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
        k: _polygonal(
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
    clipped = [_polygonal(shapely.intersection(areas[k], clip)) for k in keys]
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
    features = [rings(g) for g in to_grid(simple, to_wgs84, scale)]
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
    shows = _polygonal(
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
        piece = _polygonal(shapely.intersection(shows, square))
        smallest = side <= SPOT_CELL
        if smallest:
            piece = _polygonal(shapely.intersection(piece, strip))
        if piece.is_empty:
            continue
        centres.append(shapely.get_point(shapely.maximum_inscribed_circle(piece), 0))
        if not smallest and shapely.intersects(slovakia, square):
            half = side / 2
            squares += [(x + dx, y + dy, half) for dx in (0, half) for dy in (0, half)]
    room = shapely.distance(np.array(centres), edge)
    xy = shapely.get_coordinates(np.array(centres))
    lon, lat = to_wgs84.transform(xy[:, 0], xy[:, 1])
    return sorted(
        [
            round(float(a), BBOX_DECIMALS),
            round(float(b), BBOX_DECIMALS),
            round(float(r)),
        ]
        for a, b, r in zip(lon, lat, room, strict=True)
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

    def groups(key: Callable[[Mapping[str, Any]], Hashable]) -> dict[Any, list[int]]:
        out: dict[Any, list[int]] = {}
        for i, p in enumerate(properties):
            out.setdefault(key(p), []).append(i)
        return out

    def unions(areas: Iterable[Sequence[int]]) -> np.ndarray:
        return np.array([shapely.coverage_union_all(obce[list(a)]) for a in areas])

    cells = groups(lambda p: tuple(p.get(k) for k in keys))
    cell_props = [
        {k: v for k, v in zip(keys, key, strict=True) if v is not None} for key in cells
    ]
    scale = 10**DECIMALS
    simple = shapely.coverage_simplify(unions(cells.values()), COARSE_TOLERANCE)
    features = [rings(g) for g in to_grid(simple, to_wgs84, scale)]
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

    kraje = groups(lambda p: p["kraj"])
    content["kraje"] = [
        {"id": k, "name": admin.kraje[k]} | where
        for k, where in zip(
            sorted(kraje), placed(unions(kraje[k] for k in sorted(kraje))), strict=True
        )
    ]
    okresy = groups(lambda p: p["okres"])
    content["okresy"] = [
        {"id": o, "name": admin.okresy[o][0], "kraj": admin.okresy[o][1]} | where
        for o, where in zip(
            sorted(okresy),
            placed(unions(okresy[o] for o in sorted(okresy))),
            strict=True,
        )
    ]
    index = {p["id"]: i for i, p in enumerate(properties)}
    areas = [
        *((f"zsk-{k}", f"zsk:{k}") for k in sorted(admin.kraje)),
        *((c.code, f"oz:{c.code}") for c in CITIES),
    ]
    obvod_rows = []
    for name, prefix in areas:
        listed, resolved = members[name]
        obvod_rows += [
            (f"{prefix}/{o.number}", o.seats, [index[c] for c in resolved[o.number]])
            for o in listed.obvody
        ]
    content["obvody"] = [
        {"id": obvod, "seats": seats} | where
        for (obvod, seats, _), where in zip(
            obvod_rows,
            placed(unions(rows for *_, rows in obvod_rows)),
            strict=True,
        )
    ]
    return content, coverage(f"{COARSE_FILE} cells", features, topo, scale, to_wgs84)


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


def coverage(
    name: str,
    features: Sequence[Rings],
    topo: Topology,
    scale: int,
    to_wgs84: pyproj.Transformer,
) -> Coverage:
    """Measure overlaps and gaps between the gridded *features*, in m²."""

    def back(xy: np.ndarray) -> np.ndarray:
        x, y = to_wgs84.transform(
            xy[:, 0] / scale, xy[:, 1] / scale, direction=TransformDirection.INVERSE
        )
        return np.column_stack([x, y])

    g = shapely.make_valid(shapely.transform(_polygons(features), back))
    union = shapely.union_all(g)
    holes = [
        shapely.Polygon(ring)
        for part in shapely.get_parts(union)
        if isinstance(part, shapely.Polygon)
        for ring in part.interiors
    ]
    return Coverage(
        name,
        len(features),
        sum(len(a) for a in topo.arcs),
        max(0.0, float(shapely.area(g).sum()) - union.area),
        float(sum(h.area for h in holes)),
    )


def _segments(xy: np.ndarray) -> np.ndarray:
    """Return the segments of the line *xy* (grid units) as sorted key pairs."""
    k = _keys(xy.astype(np.int64))
    return np.sort(np.column_stack([k[:-1], k[1:]]), axis=1)


def _boundary_segments(geometries: np.ndarray) -> np.ndarray:
    lines = shapely.get_parts(shapely.boundary(geometries))
    return np.concatenate(
        [np.empty((0, 2), np.int64)]
        + [_segments(shapely.get_coordinates(g)) for g in lines]
    )


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
    properties: list[Mapping[str, Any]] = []
    geometries, drawn, codes = [], [], []
    for content in files:
        arcs, g = decode(content)
        geometries.append(g)
        properties += [f["properties"] for f in content["features"]]
        for xy, code in zip(arcs, content["lines"], strict=True):
            if not code & FOREIGN:
                drawn.append(_segments(xy))
                codes.append(np.full(len(xy) - 1, code))
    features = np.concatenate(geometries)
    segments = np.concatenate(drawn)
    code = np.concatenate(codes)
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
        units: dict[Hashable, list[int]] = {}
        for i, p in enumerate(properties):
            k = key(p)
            if k is not None:
                units.setdefault(k, []).append(i)
        try:
            merged = np.array(
                [shapely.coverage_union_all(features[r]) for r in units.values()],
                dtype=object,
            )
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
    cut = sorted({p["id"] for p in properties if "oz" in p})
    if not cut and not (code & COUNCIL).any():
        return []
    problems = []
    for name, which in (
        ("", lambda p: True),
        (" approximate", lambda p: "approx" in p),
    ):
        rows: dict[str, list[int]] = {}
        pieces = []
        for i, p in enumerate(properties):
            if "oz" in p and which(p):
                rows.setdefault(p["id"], []).append(i)
                pieces.append(i)
        obce = [shapely.coverage_union_all(features[r]) for r in rows.values()]
        outer = {
            tuple(s) for s in _boundary_segments(np.array(obce, dtype=object)).tolist()
        }
        inner = np.array(
            [
                s
                for s in _boundary_segments(features[pieces]).tolist()
                if tuple(s) not in outer
            ],
            dtype=np.int64,
        ).reshape(-1, 2)
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
    missing = {tuple(s) for s in want.tolist()} - {tuple(s) for s in have.tolist()}
    extra = {tuple(s) for s in have.tolist()} - {tuple(s) for s in want.tolist()}
    problems = []
    if missing:
        problems.append(f"{len(missing)} segments bounding {name} are not drawn so")
    if extra:
        problems.append(f"{len(extra)} segments drawn as bounding {name} do not")
    return problems


def _name(p: Mapping[str, Any]) -> str:
    return f"obec {p['id']}" if "id" in p else f"cell {dict(p)}"


def write(result: Result, directory: Path) -> dict[str, int]:
    """Replace *directory* with the files of *result*; return path → bytes.

    ``index.json`` is written last and lists the sizes of all other files.
    """
    with (
        progress.stage(f"writing {directory.name}/", len(result.files)) as s,
        output.replacing(directory) as tmp,
    ):
        sizes = {
            path: _write_json(tmp / path, content)
            for path, content in s.track(sorted(result.files.items()))
            if path != "index.json"
        }
        index = result.files["index.json"] | {"files": sizes}
        sizes["index.json"] = _write_json(tmp / "index.json", index)
    return sizes


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
    extra = [a for areas in result.council_pieces for a in areas[1:]]
    yield (
        f"  {len(result.council_pieces)} council obvody drawn in"
        f" {sum(map(len, result.council_pieces))} polygons at full detail:"
        f" {len(extra)} pieces besides their largest,"
        f" {sum(a < _HECTARE for a in extra)} of them under a hectare"
    )
    yield "coverage after rounding:     features   vertices  overlap m²  gaps m²"
    for c in result.coverage:
        yield (
            f"  {c.name:<26} {c.features:>7,} {c.vertices:>10,}"
            f" {c.overlap:>10.1f} {c.gaps:>8.1f}"
        )
    yield "files:                  count       total         max"
    groups: dict[str, list[int]] = {}
    for path, size in sizes.items():
        key = f"okres/*/{path.rsplit('/', 1)[1]}" if path.startswith("okres/") else path
        groups.setdefault(key, []).append(size)
    for key, group in groups.items():
        yield (
            f"  {key:<20} {len(group):>6} {format_size(sum(group)):>11}"
            f" {format_size(max(group)):>11}"
        )
    yield f"  {'all':<20} {len(sizes):>6} {format_size(sum(sizes.values())):>11}"


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


def preview(result: Result, okres: str, directory: Path) -> list[Path]:
    """Write SVG previews of the country, Bratislava and *okres*."""
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
            [
                (f["properties"]["label"], f["properties"]["name"])
                for f in shard["features"]
            ],
        ),
    }
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, sheet in sheets.items():
        path = directory / name
        path.write_text(_svg(sheet), encoding="utf-8")
        written.append(path)
    return written


def _svg(sheet: _Sheet) -> str:
    decoded = [(f, *decode(f)) for f in sheet.files]
    xy = np.concatenate([a / f["scale"] for f, arcs, _ in decoded for a in arcs])
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
    for f, _, geometries in decoded:
        for feature, g in zip(f["features"], geometries, strict=True):
            value = str(feature["properties"].get(sheet.fill, ""))
            hue = int.from_bytes(value.encode(), "little") * 137 % 360
            d = "".join(
                path(shapely.get_coordinates(ring) / f["scale"]) + "Z"
                for p in shapely.get_parts(g)
                for ring in (p.exterior, *p.interiors)
            )
            out.append(f'<path d="{d}" fill="hsl({hue},55%,75%)" fill-rule="evenodd"/>')
    for f, arcs, _ in decoded:
        for xy, code in zip(arcs, f["lines"], strict=True):
            style = None if code & FOREIGN else sheet.stroke(code)
            if style:
                out.append(
                    f'<path d="{path(xy / f["scale"])}" fill="none"'
                    f' stroke="{style[0]}" stroke-width="{style[1]}"/>'
                )
    for (lon, lat), text in sheet.labels:
        x, y = path(np.array([[lon, lat]]))[1:].split(",")
        out.append(
            f'<text x="{x}" y="{y}" font-size="11" font-family="sans-serif"'
            f' text-anchor="middle">{escape(text)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)
