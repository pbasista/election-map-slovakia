import dataclasses
import datetime as dt
import math

import numpy as np
import pytest
import shapely

from election_map_slovakia import geo, obvody
from election_map_slovakia.candidates import Admin, Obec

# Two obce of kraj 1 (okres 101, in different regional council obvody)
# below one obec of kraj 2 (okres 201), on a grid of 1/scale degree. The
# kraj border has a vertex in the middle of each obec of kraj 1.
OBCE = [
    (
        {"id": "a", "okres": "101", "kraj": "1", "zsk": 1},
        [(0, 0), (10, 0), (10, 10), (5, 10), (0, 10)],
    ),
    (
        {"id": "b", "okres": "101", "kraj": "1", "zsk": 2},
        [(10, 0), (20, 0), (20, 10), (15, 10), (10, 10)],
    ),
    (
        {"id": "c", "okres": "201", "kraj": "2", "zsk": 1},
        [(0, 10), (5, 10), (10, 10), (15, 10), (20, 10), (20, 20), (0, 20)],
    ),
]


def shards(obce=OBCE):
    props = [p for p, _ in obce]
    polygons = shapely.orient_polygons(
        np.array([shapely.Polygon(xy) for _, xy in obce])
    )
    topo = geo.topology([geo.rings(g) for g in polygons], 1)
    return {
        okres: geo.topology_file(
            topo,
            1,
            [i for i, p in enumerate(props) if p["okres"] == okres],
            props,
            geo.unit_code(okres),
        )
        for okres in ("101", "201")
    }


def kraj_border(file):
    """Index of the arc on the kraj border at x 0–10 in *file*."""
    arcs, _ = geo.decode(file)
    return next(
        i
        for i, (xy, code) in enumerate(zip(arcs, file["lines"], strict=True))
        if code & geo.RANK == geo.KRAJ
        and set(map(tuple, xy.tolist())) == {(0, 10), (5, 10), (10, 10)}
    )


def test_shared_border_is_drawn_once_from_the_obce_vertices():
    files = shards()
    assert geo.verify(files.values()) == []
    # Both shards hold the kraj border, so both can fill their obce; the one
    # with the lower okres code draws it.
    low, high = files["101"], files["201"]
    assert not low["lines"][kraj_border(low)] & geo.FOREIGN
    assert high["lines"][kraj_border(high)] & geo.FOREIGN
    _, (a, b) = geo.decode(low)
    _, (c,) = geo.decode(high)
    # Kraj 1 merged from its obce has exactly kraj 2's vertices on the border.
    kraj_1 = shapely.coverage_union_all([a, b])
    on_border = {(x, y) for x, y in shapely.get_coordinates(kraj_1).tolist() if y == 10}
    assert on_border == {
        (x, y) for x, y in shapely.get_coordinates(c).tolist() if y == 10
    }


def test_border_off_the_obce_is_found():
    files = shards()
    # Kraj 2's copy of the border gets its middle vertex 1 unit into kraj 1.
    arc = files["201"]["arcs"][kraj_border(files["201"])]
    assert arc[2:4] in ([5, 0], [-5, 0])
    arc[3] -= 1
    arc[5] += 1
    problems = geo.verify(files.values())
    assert any("do not share their borders" in p for p in problems)
    assert any("every kraj" in p for p in problems)


def test_border_drawn_in_the_wrong_rank_is_found():
    files = shards()
    low = files["101"]
    low["lines"][kraj_border(low)] = geo.OBEC | geo.ZSK
    problems = geo.verify(files.values())
    assert problems == [
        "2 segments bounding every kraj are not drawn so",
        "2 segments bounding every okres are not drawn so",
    ]


def test_border_drawn_by_both_shards_is_found():
    files = shards()
    high = files["201"]
    high["lines"] = [c & ~geo.FOREIGN for c in high["lines"]]
    assert geo.verify(files.values()) == ["4 border segments drawn more than once"]


def test_spike_left_by_rounding_is_dropped_on_both_sides():
    # A sliver of a into b, folded flat onto the shared border by rounding.
    obce = [
        (
            OBCE[0][0],
            [(0, 0), (10, 0), (10, 5), (15, 5), (10, 5), (10, 10), (5, 10), (0, 10)],
        ),
        (
            OBCE[1][0],
            [(10, 0), (20, 0), (20, 10), (15, 10), (10, 10), (10, 5), (15, 5), (10, 5)],
        ),
        OBCE[2],
    ]
    files = shards(obce)
    assert geo.verify(files.values()) == []
    _, (a, b) = geo.decode(files["101"])
    assert [15, 5] not in shapely.get_coordinates(a).tolist()
    assert [15, 5] not in shapely.get_coordinates(b).tolist()


def test_edges_snapped_through_the_same_pixels_keep_their_own_bends():
    # The tip (0, 0) of a narrow wedge of a neighbour: snap rounding bent
    # one edge of it through four points, the other through one of them.
    # The piece from that point to the tip is the second edge's own, not
    # to be bent through the first's points.
    one, other = ((0.0, 0.0), (-4.0, 9.0)), ((0.0, 0.0), (-99.0, 43.0))
    chains = geo._Chains(
        {
            geo._edge(*one): {(0.0, 1.0), (-1.0, 1.0), (-1.0, 2.0), (-1.0, 3.0)},
            geo._edge(*other): {(-1.0, 1.0)},
        }
    )
    piece = shapely.Polygon([(-1, 1), (0, 0), (0, -5)])
    wedge = shapely.Polygon([(0, 0), (-4, 9), (-99, 43)])
    bent = geo._bend(np.array([piece, wedge]), chains)
    assert shapely.equals_exact(bent[0], piece)
    assert shapely.get_coordinates(bent[1]).tolist()[:6] == [
        [0, 0],
        [0, 1],
        [-1, 1],
        [-1, 2],
        [-1, 3],
        [-4, 9],
    ]


def test_overlays_on_the_noding_grid_take_and_give_polygons_only():
    # A street block whose tip, between two nearly parallel lines, is a
    # centimetre wide (in Pata): an overlay on the noding grid collapses the
    # tip into a line, and an overlay of that collection failed. The reach
    # of a house, and the strips narrower than the pinch beside it (the
    # tip), as :func:`_block_faces` draws it.
    block = shapely.Polygon([(0, 0), (0, 0.01), (-7.33, 20), (-30, 20), (-1.54, 3.32)])
    house = shapely.Point(-15, 15).buffer(2)
    raw = shapely.difference(block, house, grid_size=geo._NODING_GRID)
    assert shapely.GeometryType.LINESTRING in shapely.get_type_id(
        shapely.get_parts(raw)
    )
    rest = geo._grid_overlay(shapely.difference, block, house)
    reach = geo._grid_overlay(shapely.difference, block, geo._opened(rest))
    for g in (rest, reach):
        assert shapely.get_type_id(g) == shapely.GeometryType.MULTIPOLYGON
    assert shapely.covers(reach.buffer(geo._NODING_GRID), house)
    assert reach.area < house.area + 5


def test_overlays_on_the_noding_grid_take_a_ring_crossed_by_a_rounding_error():
    # A mitred buffer returned a ring that comes back to a vertex of it
    # (where a loop of it meets a notch), 1e-15 m off: it crosses itself,
    # and an overlay failed on it.
    notched = [(-10, -10), (-1, -10), (0, 0), (1, -10), (10, -10), (10, 10), (-10, 10)]
    loop = [(4, 1), (1, 4), (-2e-15, -2e-15)]
    crossed = shapely.Polygon([*notched[:3], *loop, *notched[3:]])
    block = shapely.box(-20, -20, 20, 20)
    with pytest.raises(shapely.errors.GEOSException):
        shapely.difference(block, crossed, grid_size=geo._NODING_GRID)
    rest = geo._grid_overlay(shapely.difference, block, crossed)
    assert rest.area == pytest.approx(block.area - shapely.Polygon(notched).area)


def test_a_short_sliver_centimetres_wide_is_given_away():
    # A tooth of unit 2 into unit 1, 5 cm wide and 10 cm long: smaller than
    # what an opening's rounding errors take, but as narrow as a long one,
    # it would fold when rounded to the map's grid. It goes to unit 1.
    tooth = shapely.box(9.9, 5, 10, 5.05)
    areas = np.array(
        [
            shapely.difference(shapely.box(0, 0, 10, 10), tooth),
            shapely.union(shapely.box(10, 0, 20, 10), tooth),
        ]
    )
    out = geo._untailed(areas, np.array([[2.0, 2.0], [18.0, 8.0]]))
    assert shapely.equals(out[0], shapely.box(0, 0, 10, 10))
    assert shapely.equals(out[1], shapely.box(10, 0, 20, 10))


def test_doubled_obec_is_rejected():
    overlapping = [OBCE[0], (OBCE[2][0], OBCE[0][1])]
    with pytest.raises(geo.GeoError, match="not shared by exactly two neighbours"):
        shards(overlapping)


def test_neighbours_reach_slovakia_where_natural_earth_falls_short():
    # ZBGIS's Slovakia, and Natural Earth's 2 km east of it: Austria reaches
    # under Slovakia in the west, Hungary (south) and Ukraine (north) stop
    # 2 km short of it in the east. In metres.
    km = 1000
    slovakia = shapely.box(0, 0, 100 * km, 100 * km)
    countries = {
        "SK": shapely.box(2 * km, 0, 102 * km, 100 * km),
        "AT": shapely.box(-50 * km, 0, 2 * km, 100 * km),
        "HU": shapely.box(102 * km, 0, 150 * km, 50 * km),
        "UA": shapely.box(102 * km, 50 * km, 150 * km, 100 * km),
    }
    areas = geo.neighbour_areas(countries, slovakia)
    land = shapely.box(-50 * km, 0, 150 * km, 100 * km)
    assert (
        shapely.difference(land, shapely.union_all([*areas.values(), slovakia])).area
        < 1
    )
    # The strip Natural Earth gives Slovakia goes to the neighbour beside it.
    strip = shapely.box(100 * km, 0, 102 * km, 100 * km)
    assert shapely.intersection(strip, areas["HU"]).area == pytest.approx(
        strip.area / 2, rel=0.05
    )
    assert shapely.intersection(strip, areas["UA"]).area == pytest.approx(
        strip.area / 2, rel=0.05
    )
    # Under Slovakia they reach no farther than UNDER.
    deep = shapely.buffer(slovakia, -geo.UNDER - 1)
    assert not any(shapely.intersects(deep, a) for a in areas.values())


def test_gap_between_neighbours_and_slovakia_is_found():
    # One neighbour around a hole of 0.02°, at 1/1000 degree.
    around = shapely.orient_polygons(
        shapely.Polygon(
            [(0, 0), (100, 0), (100, 100), (0, 100)],
            [[(40, 40), (60, 40), (60, 60), (40, 60)]],
        )
    )
    topo = geo.topology([geo.rings(around)], 1000)
    content = geo.topology_file(topo, 1000, [0], [{"id": "AT"}], geo.neighbour_code)
    covering = shapely.box(0.039, 0.039, 0.061, 0.061)
    assert geo.verify_neighbours(content, {"coarse.json": covering}) == []
    short = shapely.box(0.041, 0.041, 0.059, 0.059)
    (problem,) = geo.verify_neighbours(content, {"coarse.json": short})
    assert problem.endswith("m² between them and Slovakia at coarse.json")


def test_name_places_are_off_slovakia_with_their_room():
    # Near Bratislava, in EPSG:5514 metres: a country around a square
    # Slovakia.
    to_wgs84 = geo.transformer()
    slovakia = shapely.box(-580_000, -1_300_000, -560_000, -1_280_000)
    area = shapely.box(-660_000, -1_380_000, -480_000, -1_200_000)
    spots = geo.label_spots(area, slovakia, to_wgs84)
    lon, lat, room = np.array(spots).T
    x, y = to_wgs84.transform(lon, lat, direction="INVERSE")
    places = shapely.points(x, y)
    edge = shapely.boundary(shapely.difference(area, slovakia))
    # Each name's room around its place is in the country, out of Slovakia
    # (rounding: places to 1e-4°, about 10 m).
    assert not shapely.intersects(places, slovakia).any()
    assert (shapely.distance(places, edge) >= room - 15).all()
    # And the smallest squares put places close to the border.
    assert (shapely.distance(places, slovakia) < geo.SPOT_CELL / 4 + 15).any()


class _Identity:
    """A transformer that leaves coordinates as they are."""

    def transform(self, x, y, direction=None):
        return x, y


NO_LINES = np.array([], dtype=object)


def drawn_split(xy, units, area, lines=NO_LINES):
    """Return the cut of *area* by the address points *xy* of *units*."""
    points = geo._point_votes(np.array(xy, dtype=float), np.array(units), set(units))
    numbers = tuple(sorted(set(units)))
    areas = geo._block_cut(area, lines, points)
    return geo.Split(
        numbers, True, None, tuple(zip(numbers, geo._reaching(list(areas)))), points
    )


def block_cut(xy, units, area, lines=NO_LINES):
    """Return the areas of *area* cut by the points *xy* of *units*, by unit."""
    points = geo._point_votes(np.array(xy, dtype=float), np.array(units))
    areas = geo._block_cut(area, lines, points)
    assert abs(shapely.union_all(areas).area - area.area) < 1.0
    assert shapely.area(areas).sum() == pytest.approx(area.area, abs=1.0)
    return dict(zip(sorted(set(units)), areas, strict=True))


def inside_own(cut, xy, units):
    """Return whether each point *xy* lies in the area of its unit of *cut*."""
    return [
        bool(shapely.covers(cut[u], shapely.Point(p)))
        for p, u in zip(xy, units, strict=True)
    ]


def test_council_cut_is_a_coverage_on_the_grid_with_its_neighbours():
    # Obec "a" is cut between its western and eastern address points; the
    # cut meets its borders with "b" and "c" between their vertices, at
    # points off the grid, which they must get too, rounded alike.
    a = shapely.Polygon([(0, 0), (100, 0), (100, 50), (0, 50)])
    b = shapely.Polygon([(0, 50), (100, 50), (100, 80), (0, 80)])
    c = shapely.Polygon([(0, -40), (100, -40), (100, 0), (0, 0)])
    points = [[20.0, 20.0], [30.3, 30.0], [70.3, 20.0], [80.0, 30.7]]
    split = drawn_split(points, [1, 1, 2, 2], a)
    units, grid = geo.cut_council(
        [("a", 0), ("b", 0), ("c", 0)],
        shapely.orient_polygons(np.array([a, b, c])),
        {"a": split},
        _Identity(),
        1,
    )
    assert units == [("a", 1), ("a", 2), ("b", 0), ("c", 0)]
    xy = shapely.get_coordinates(grid)
    assert (xy == np.rint(xy)).all()
    assert shapely.is_valid(grid).all()
    assert shapely.is_empty(shapely.coverage_invalid_edges(grid)).all()
    assert abs(shapely.area(grid[:2]).sum() - a.area) < 1.0
    # Every border is one arc shared by exactly two sides, or none.
    geo.topology([geo.rings(g) for g in grid], 1)


def test_okrsky_tile_the_shard_features_they_are_cut_from():
    # Obec "a" of the shards in council obvody 1 (west) and 2 (east); okrsok
    # 1 is obvod 1, okrsky 2 and 3 are drawn at full detail missing obvod
    # 2's border by a fraction of a unit. Cut from the shard's obvod 2, they
    # tile it, and every border between okrsky is drawn, the one on the
    # obvod border flagged so.
    a1, a2 = shapely.box(0, 0, 40, 50), shapely.box(40, 0, 100, 50)
    b = shapely.box(0, 50, 100, 80)
    okrsky = {
        "a": [
            geo.Okrsok(1, 1, a1, False),
            geo.Okrsok(2, 2, shapely.box(40.3, -0.4, 70.3, 50.3), True),
            geo.Okrsok(3, 2, shapely.box(70.3, -0.4, 100.4, 50.3), True),
        ]
    }
    units = [("a", 1), ("a", 2), ("b", 0)]
    shard = shapely.orient_polygons(np.array([a1, a2, b]))
    gridded = {lod.level: shard for lod in geo.SHARD_LODS}
    reaching = geo.okrsky_reaching(okrsky["a"], _Identity(), 1)
    features, levels = geo.okrsky_levels(
        okrsky, {("a", n): r for n, r in reaching.items()}, units, gridded
    )
    properties = geo.okrsok_properties(features, levels[0], 1)
    assert [(p["obec"], p["okrsok"], p["obvod"]) for p in properties] == [
        ("a", 1, 1),
        ("a", 2, 2),
        ("a", 3, 2),
    ]
    shard_topo = geo.topology([geo.rings(g) for g in shard], 1)
    shard_file = geo.topology_file(
        shard_topo, 1, [0, 1, 2], [{"id": c} for c, _ in units], lambda s: 0
    )
    for grid in levels.values():
        assert shapely.is_valid(grid).all()
        assert shapely.equals(shapely.union_all(grid), shapely.union(a1, a2))
        assert shapely.area(grid).tolist() == pytest.approx([2000, 1500, 1500], abs=60)
        topo = geo.topology([geo.rings(g) for g in grid], 1)
        file = geo.topology_file(topo, 1, [0, 1, 2], properties, geo.okrsok_code)
        drawn = sorted(c for c in file["lines"] if not c & geo.FOREIGN)
        okrsok = geo.OKRSOK | geo.APPROX
        assert drawn == [okrsok, okrsok | geo.COUNCIL]
        assert geo.verify_okrsky([file], [shard_file], {"a": [1, 2, 3]}) == []
        assert geo.verify_okrsky([file], [shard_file], {"a": [1, 2]}) == [
            "obec a: okrsky [1, 2, 3] drawn, the index says [1, 2]"
        ]


def test_street_split_mid_block_keeps_each_house_in_its_unit():
    # A street (y = 100) with a block on either side; the rules split it by
    # house numbers: the north side at x = 200, the south side at x = 250.
    # The borders run along the street, and between the houses where a
    # block is split.
    area = shapely.box(0, 0, 400, 200)
    street = np.array([shapely.LineString([(0, 100), (400, 100)])])
    xs = np.arange(10, 400, 20)
    xy = [(x, 110) for x in xs] + [(x, 90) for x in xs]
    units = [1 if x < 200 else 2 for x in xs] + [1 if x < 250 else 2 for x in xs]
    cut = block_cut(xy, units, area, street)
    assert all(inside_own(cut, xy, units))
    border = shapely.intersection(cut[1].boundary, cut[2].boundary)
    north = shapely.intersection(border, shapely.box(0, 100.1, 400, 200))
    south = shapely.intersection(border, shapely.box(0, 0, 400, 99.9))
    assert 190 <= shapely.bounds(north)[0] <= shapely.bounds(north)[2] <= 210
    assert 240 <= shapely.bounds(south)[0] <= shapely.bounds(south)[2] <= 260
    # Along the street, between x = 200 and 250, where the two sides differ.
    along = shapely.intersection(border, shapely.box(0, 99.9, 400, 100.1))
    assert shapely.length(along) == pytest.approx(50, abs=12)


def test_a_cottage_in_a_forest_takes_its_reach_not_the_forest():
    # A village of unit 1 along the south side of a road (y = 300), a forest
    # block north of the road with one cottage of unit 2 far from the road:
    # sparse, so the cottage gets its reach and the forest goes by shared
    # border to the village's unit.
    area = shapely.box(0, 0, 2000, 2000)
    road = np.array([shapely.LineString([(0, 300), (2000, 300)])])
    village = [(x, y) for x in range(20, 2000, 40) for y in (200, 260)]
    xy = [*village, (1000, 1200)]
    units = [1] * len(village) + [2]
    cut = block_cut(xy, units, area, road)
    assert all(inside_own(cut, xy, units))
    # An island: only its plot, not the disc that decided the forest's unit.
    assert 1_000 < cut[2].area < math.pi * geo.ISLAND_REACH**2
    assert shapely.covers(cut[1], shapely.box(0, 1800, 2000, 2000))


def test_a_cottage_near_a_road_keeps_a_plot_along_the_road():
    # As above, the cottage 30 m from the road: its plot reaches the road.
    area = shapely.box(0, 0, 2000, 2000)
    road = np.array([shapely.LineString([(0, 300), (2000, 300)])])
    village = [(x, y) for x in range(20, 2000, 40) for y in (200, 260)]
    xy = [*village, (1000, 330)]
    units = [1] * len(village) + [2]
    cut = block_cut(xy, units, area, road)
    assert all(inside_own(cut, xy, units))
    assert shapely.distance(cut[2], road[0]) < 1.0
    assert cut[2].area < 2 * math.pi * geo.ISLAND_REACH**2
    assert shapely.covers(cut[1], shapely.box(0, 1800, 2000, 2000))


def test_a_corridor_beside_a_street_is_cut_where_the_land_beside_changes():
    # A street (y = 100) and a path beside it (y = 106): the strip between
    # them runs along both units' blocks (split by a lane at x = 200). It is
    # cut where the lane meets it, so neither unit reaches along it.
    area = shapely.box(0, 0, 400, 300)
    lines = np.array(
        [
            shapely.LineString([(0, 100), (400, 100)]),
            shapely.LineString([(0, 106), (400, 106)]),
            shapely.LineString([(200, 106), (200, 300)]),
            shapely.LineString([(200, 0), (200, 100)]),
        ]
    )
    xy = [(x, y) for x in range(20, 400, 40) for y in (50, 200)]
    units = [1 if x < 200 else 2 for x in range(20, 400, 40) for _ in (50, 200)]
    cut = block_cut(xy, units, area, lines)
    assert all(inside_own(cut, xy, units))
    assert shapely.covers(cut[1], shapely.box(0, 100, 190, 106))
    assert shapely.covers(cut[2], shapely.box(210, 100, 400, 106))


def test_empty_field_between_two_villages_goes_by_whole_blocks():
    # A road (y = 500) through two villages, x < 1000 and x > 2000, and the
    # fields between them cut by tracks at x = 1000, 1400 and 2000: each
    # field goes whole to the village it borders, so the border between
    # them is the track at x = 1400, not a line halfway between houses.
    area = shapely.box(0, 0, 3000, 1000)
    lines = np.array(
        [
            shapely.LineString([(0, 500), (3000, 500)]),
            *(shapely.LineString([(x, 0), (x, 1000)]) for x in (1000, 1400, 2000)),
        ]
    )
    xs = [*range(50, 1000, 100), *range(2050, 3000, 100)]
    xy = [(x, y) for x in xs for y in (480, 520)]
    units = [1 if x < 1500 else 2 for x, _ in xy]
    cut = block_cut(xy, units, area, lines)
    assert shapely.equals(cut[1], shapely.box(0, 0, 1400, 1000))
    assert shapely.equals(cut[2], shapely.box(1400, 0, 3000, 1000))


def test_mixed_block_of_interleaved_houses_keeps_each_in_its_unit():
    # One block, two rows of houses whose units interleave (odd and even
    # numbers, entrances of two okrsky): every house stays in its own unit,
    # each unit's area holding all of its houses.
    area = shapely.box(0, 0, 300, 200)
    xy = [(x, y) for y in (80, 120) for x in range(15, 300, 15)]
    units = [1 + (i // 2 + j) % 2 for j in range(2) for i in range(19)]
    cut = block_cut(xy, units, area)
    assert all(inside_own(cut, xy, units))


def test_address_less_sliver_goes_to_the_unit_around_it():
    # Faces in a row: unit 1 with addresses, a sliver of unit 2 without
    # any, an empty face of unit 1, unit 2's houses. The sliver goes to
    # unit 1, which holds it on both sides; unit 2 keeps its houses.
    faces = np.array(
        [
            shapely.box(0, 0, 10, 10),
            shapely.box(10, 0, 10.5, 10),
            shapely.box(10.5, 0, 20, 10),
            shapely.box(20, 0, 30, 10),
        ]
    )
    borders = geo._borders(faces)
    drawn = geo._unstrayed(borders, np.array([1, 2, 1, 2]), np.array([3, 0, 0, 2]))
    assert drawn.tolist() == [1, 1, 1, 2]


def test_bending_many_features_at_once_bends_each_alike():
    # A square and its neighbour; the shared edge is bent through two
    # points, and the neighbour already has the first of them (a piece of
    # a cut): both end up with the same vertices along it.
    left = shapely.Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    right = shapely.Polygon([(10, 0), (20, 0), (20, 10), (10, 10), (10, 4)])
    chains = geo._Chains({geo._edge((10, 0), (10, 10)): {(10, 4), (10, 7)}})
    bent = geo._bend(np.array([left, right, shapely.box(30, 0, 40, 10)]), chains)
    assert shapely.coverage_is_valid(bent[:2])
    for g in bent[:2]:
        xy = shapely.get_coordinates(g).tolist()
        assert [10, 4] in xy and [10, 7] in xy
    assert bent[2] is not None and shapely.equals_exact(
        bent[2], shapely.box(30, 0, 40, 10)
    )


def test_simplified_borders_within_a_block_keep_every_point_in_its_unit():
    # One block of two units whose border zigzags 3 m either way between
    # houses: simplified, the zigzags go, but a house just below a peak of
    # it stays in its unit, at least as far from the border as it was.
    xs = np.arange(0, 101, 5.0)
    zigzag = [(float(x), 50 + (3 if i % 2 else -3)) for i, x in enumerate(xs)]
    south = shapely.Polygon([(0, 0), (100, 0), *zigzag[::-1]])
    north = shapely.Polygon([(0, 100), *zigzag, (100, 100)])
    areas = np.array([south, north])
    point = shapely.Point(5.0, 52.5)
    xy = np.array([[50.0, 20.0], [50.0, 80.0], [5.0, 52.5]])
    inner = geo._inner_segments(areas, np.array([0, 0]))
    simple = geo._safely_simplified(areas, xy, inner)
    assert shapely.coverage_is_valid(simple)
    assert (
        shapely.get_num_coordinates(simple).sum()
        < shapely.get_num_coordinates(areas).sum()
    )
    assert shapely.covers(simple[0], point)
    before = shapely.distance(north, point)
    assert shapely.distance(simple[1], point) >= before - geo._NODING_GRID
    # The outline stays as it was.
    assert shapely.equals(shapely.union_all(simple), shapely.box(0, 0, 100, 100))


MEMBER_ADMIN = Admin(
    kraje={"1": "Bratislavský", "8": "Košický"},
    okresy={"101": ("Bratislava I", "1"), "806": ("Košice - okolie", "8")},
    obce={
        "BA": Obec("BA", "Bratislava", None, "1"),
        "528595": Obec("528595", "Bratislava-Staré Mesto", "101", "1", "BA"),
        "521001": Obec("521001", "Bidovce", "806", "8"),
        "521002": Obec("521002", "Blažice", "806", "8"),
    },
)


def zsk_file(directory, kraj: str, obvody: dict[int, list[str]]) -> None:
    path = directory / "obvody" / f"zsk-{kraj}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['source = "https://example.sk"', 'title = "Obvody"', "date = 2026-07-01"]
    for n, obce in obvody.items():
        lines += [f"[obvod.{n}]", "seats = 2", f"obce = {obce!r}".replace("'", '"')]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_memberships_of_an_election_without_regional_or_city_councils(tmp_path):
    # A country-wide election: nothing to load (the directory has nothing),
    # every obec in regional obvod 0, the districts in no city obvod.
    contests = [
        {"id": "prezident:SK/1", "kind": "prezident", "area": "SK", "obvod": 1},
        {"id": "starosta:521001", "kind": "starosta", "area": "521001"},
        {"id": "oz:521001/1", "kind": "oz", "area": "521001", "obvod": 1},
    ]
    members = geo.memberships(tmp_path, MEMBER_ADMIN, contests)
    assert members == {}
    props = geo.obec_properties(MEMBER_ADMIN, geo.obec_codes(MEMBER_ADMIN), members)
    assert props["528595"] == {
        "id": "528595",
        "name": "Bratislava-Staré Mesto",
        "okres": "101",
        "kraj": "1",
        "zsk": 0,
    }
    assert props["521001"]["zsk"] == 0


def test_memberships_of_a_by_election_in_one_regional_obvod(tmp_path):
    # Only the kraj with a regional contest is loaded; held in one of its
    # obvody, the file needs to have that one, not as many as the contests.
    zsk_file(tmp_path, "8", {1: ["521001"], 2: ["521002"]})
    contests = [{"id": "zsk:8/2", "kind": "zsk", "area": "8", "obvod": 2}]
    with pytest.raises(obvody.ObvodyError, match="2 obvody, but the candidate lists"):
        geo.memberships(tmp_path, MEMBER_ADMIN, contests)
    members = geo.memberships(tmp_path, MEMBER_ADMIN, contests, partial=True)
    assert list(members) == ["zsk-8"]
    assert members["zsk-8"][1] == {1: ("521001",), 2: ("521002",)}
    props = geo.obec_properties(MEMBER_ADMIN, geo.obec_codes(MEMBER_ADMIN), members)
    assert [props[c]["zsk"] for c in ("528595", "521001", "521002")] == [0, 1, 2]
    missing = [{"id": "zsk:8/3", "kind": "zsk", "area": "8", "obvod": 3}]
    with pytest.raises(obvody.ObvodyError, match="no obvod 3 of the candidate lists"):
        geo.memberships(tmp_path, MEMBER_ADMIN, missing, partial=True)


def test_rules_key_ignores_where_the_rules_come_from_only():
    # A rule set reused by a later election differs in its documents, dates
    # and notes: its cuts are the same. Any rule or seat makes another.
    rules = obvody.RuleSet(
        obec="508063",
        name="Jakubov",
        date=dt.date(2022, 8, 1),
        documents=(obvody.Document("https://example.sk/a.pdf", "0" * 64, "a"),),
        seats={1: 3, 2: 2},
        rules=(obvody.Rule(1, street="Hlavná"), obvody.Rule(2, rest=True)),
    )
    reused = dataclasses.replace(
        rules,
        date=None,
        documents=(),
        note="as in 2022",
        reused=dt.date(2022, 10, 29),
        rules=(
            obvody.Rule(1, street="Hlavná", written="Hlavna", note="sic"),
            obvody.Rule(2, rest=True, inferred=True, note="the rest"),
        ),
    )
    assert geo.rules_key(reused) == geo.rules_key(rules)
    for other in (
        dataclasses.replace(rules, seats={1: 3, 2: 3}),
        dataclasses.replace(rules, estimated=True),
        dataclasses.replace(
            rules, rules=(obvody.Rule(1, street="Dolná"), obvody.Rule(2, rest=True))
        ),
        dataclasses.replace(rules, okrsky={1: (1,), 2: (2, 3)}),
    ):
        assert geo.rules_key(other) != geo.rules_key(rules)
    assert geo.rules_key(None) != geo.rules_key(rules)


def test_cache_keeps_entries_of_its_code_and_inputs_only(tmp_path):
    cache = geo.Cache(tmp_path, "code1", "inputs1")
    entry = cache.entry("cut", "a", "b")
    assert cache.get(entry) is None
    value = (np.arange(3), shapely.box(0, 0, 1, 1), {"x": [1.5]})
    cache.put(entry, value)
    got = cache.get(entry)
    assert got[0].tolist() == [0, 1, 2]
    assert shapely.to_wkb(got[1]) == shapely.to_wkb(value[1])
    assert got[2] == value[2]
    # The key, the kind and the input files each make another entry.
    assert cache.entry("cut", "ab") != entry
    assert cache.entry("base", "a", "b") != entry
    assert geo.Cache(tmp_path, "code1", "inputs2").entry("cut", "a", "b") != entry
    assert geo.Cache(tmp_path, "code1", "inputs1").get(entry) is not None
    # Another version of the code reads none of it, and removes it.
    assert geo.Cache(tmp_path, "code2", "inputs1").entry("cut", "a", "b") != entry
    assert not entry.exists()


def test_cached_cuts_are_taken_by_their_task(tmp_path):
    cache = geo.Cache(tmp_path, "code1", "inputs1")
    task = ("a", shapely.box(0, 0, 1, 1))
    assert geo._cached_each(cache, "council", lambda c, g: (c, g.area), [task]) == [
        ("a", 1.0)
    ]
    # The same task again is not run; another one is.
    assert geo._cached_each(cache, "council", lambda c, g: None, [task]) == [("a", 1.0)]
    other = ("a", shapely.box(0, 0, 2, 1))
    assert geo._cached_each(cache, "council", lambda c, g: (c, g.area), [other]) == [
        ("a", 2.0)
    ]


def test_pieces_are_keyed_by_the_roots_of_the_borders_in_order():
    # Faces 0-1-2 and 5 of unit 1, 3-4 of unit 2. Joined in the order of
    # their borders, each under the root of the later face: the roots, which
    # settle ties, are 2, 4 and 5, the pieces in the order of their faces.
    borders = [(0, 1, 1.0), (1, 2, 2.0), (2, 3, 0.5), (3, 4, 1.0), (4, 5, 3.0)]
    pieces = geo._pieces(
        borders, np.array([1, 1, 1, 2, 2, 1]), np.array([1, 0, 2, 0, 1, 0])
    )
    assert list(pieces) == [2, 4, 5]
    assert [(p.unit, p.faces, p.addresses) for p in pieces.values()] == [
        (1, [0, 1, 2], 3),
        (2, [3, 4], 1),
        (1, [5], 0),
    ]
    assert dict(pieces[4].borders) == {2: 0.5, 5: 3.0}


def test_polygons_of_many_overlays_are_those_of_each():
    line = shapely.LineString([(0, 0), (1, 1)])
    geometries = np.array(
        [
            shapely.box(0, 0, 1, 1),
            shapely.GeometryCollection(
                [shapely.box(0, 0, 1, 1), line, shapely.box(2, 2, 3, 3)]
            ),
            line,
            shapely.Polygon(),
            shapely.GeometryCollection(),
        ]
    )
    assert shapely.to_wkb(geo._polygonals(geometries)).tolist() == [
        shapely.to_wkb(geo.polygonal(g)) for g in geometries
    ]


def reference_rings(geometry):
    """The rings of *geometry* cleaned ring by ring, as the module doc says."""
    out = []
    for part in shapely.get_parts(geometry):
        kept = []
        for ring in (part.exterior, *part.interiors):
            xy = shapely.get_coordinates(ring)[:-1].astype(np.int64)
            while len(xy) >= 3:
                xy = xy[np.any(xy != np.roll(xy, 1, axis=0), axis=1)]
                spike = np.all(
                    np.roll(xy, 1, axis=0) == np.roll(xy, -1, axis=0), axis=1
                )
                if not spike.any():
                    break
                xy = xy[~spike]
            if len(xy) >= 3:
                kept.append(xy.tolist())
            elif not kept:
                break
        if kept:
            out.append(kept)
    return out


def test_rings_of_many_features_drop_repeats_and_spikes_ring_by_ring():
    # Rings of a few vertices on a small grid repeat vertices and fold
    # spikes flat, some collapse, exteriors with their holes.
    rng = np.random.default_rng(0)

    def ring():
        xy = rng.integers(0, 4, size=(rng.integers(3, 9), 2))
        return [*xy.tolist(), xy[0].tolist()]

    features = [shapely.Polygon()]
    for _ in range(300):
        parts = [
            shapely.Polygon(ring(), [ring() for _ in range(rng.integers(0, 3))])
            for _ in range(rng.integers(1, 4))
        ]
        features.append(shapely.MultiPolygon(parts) if len(parts) > 1 else parts[0])
    got = geo.feature_rings(features)
    assert [[[r.tolist() for r in p] for p in f] for f in got] == [
        reference_rings(g) for g in features
    ]
    assert any(not f for f in got[1:])
