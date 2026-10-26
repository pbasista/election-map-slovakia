import numpy as np
import pytest
import shapely

from election_map_slovakia import geo

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


def test_council_cut_is_a_coverage_on_the_grid_with_its_neighbours():
    # Obec "a" is cut between its western and eastern address points; the
    # cut meets its borders with "b" and "c" between their vertices, at
    # points off the grid, which they must get too, rounded alike.
    a = shapely.Polygon([(0, 0), (100, 0), (100, 50), (0, 50)])
    b = shapely.Polygon([(0, 50), (100, 50), (100, 80), (0, 80)])
    c = shapely.Polygon([(0, -40), (100, -40), (100, 0), (0, 0)])
    points = np.array([[20.0, 20.0], [30.3, 30.0], [70.3, 20.0], [80.0, 30.7]])
    homes = [[(str(i), "a")] for i in range(len(points))]
    split = geo._voronoi_split((1, 2), points, np.array([1, 1, 2, 2]), homes, a)
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
    features, levels = geo.okrsky_levels(okrsky, units, gridded, _Identity(), 1)
    properties = geo.okrsok_properties(features, _Identity())
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


def test_lone_houses_draw_no_island_but_a_large_cluster_stays():
    # Houses every 50 m, obvod 1 in the west, 2 in the east, but for one
    # house of obvod 2 in the west (a wrong point, say), a block of four of
    # obvod 1 in the east and a cluster of twenty of obvod 1 in the far
    # east, a sixth of the obvod, which the rules put there.
    a = shapely.Polygon([(0, 0), (2000, 0), (2000, 500), (0, 500)])
    x, y = np.meshgrid(np.arange(25, 2000, 50), np.arange(25, 500, 50))
    points = np.column_stack([x.ravel(), y.ravel()]).astype(float)
    obvod = np.where(points[:, 0] < 500, 1, 2)
    obvod[(points == [225, 225]).all(axis=1)] = 2
    obvod[np.isin(points[:, 0], [925, 975]) & np.isin(points[:, 1], [225, 275])] = 1
    obvod[(points[:, 0] > 1750) & (points[:, 1] > 300)] = 1
    homes = [[(str(i), "Obec")] for i in range(len(points))]
    split = geo._voronoi_split((1, 2), points, obvod, homes, a)
    units, grid = geo.cut_council(
        [("a", 0)], shapely.orient_polygons(np.array([a])), {"a": split}, _Identity(), 1
    )
    assert units == [("a", 1), ("a", 2)]
    assert shapely.get_num_geometries(grid).tolist() == [2, 1]
    assert shapely.get_num_interior_rings(shapely.get_parts(grid[1])).tolist() == [0]
