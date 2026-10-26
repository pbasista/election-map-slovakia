import numpy as np
import shapely

from election_map_slovakia import basemap, geo


def test_line_class():
    # TagList answers get() and `in` like a dict.
    assert basemap._line_class({"highway": "primary_link"}) == (basemap.PRIMARY, True)
    assert basemap._line_class({"highway": "residential"}) == (basemap.MINOR, False)
    assert basemap._line_class({"highway": "track"}) == (None, False)
    assert basemap._line_class({"highway": "pedestrian", "area": "yes"}) == (
        None,
        False,
    )
    assert basemap._line_class({"railway": "rail"}) == (basemap.RAIL, False)
    assert basemap._line_class({"railway": "rail", "service": "siding"}) == (
        None,
        False,
    )
    assert basemap._line_class({"waterway": "stream"}) == (basemap.STREAM, False)
    assert basemap._line_class({"waterway": "stream", "tunnel": "culvert"}) == (
        None,
        False,
    )


def test_course_lengths():
    lines = np.array(
        [
            shapely.LineString([(0, 0), (1000, 0)]),
            shapely.LineString([(1000, 0), (3000, 0)]),
            shapely.LineString([(3000, 0), (4000, 0)]),  # another name
            shapely.LineString([(0, 10), (500, 10)]),  # unnamed
        ]
    )
    kind = np.full(4, basemap.STREAM, dtype=np.uint8)
    names = np.array(["Potok", "Potok", "Iný", ""], dtype=object)
    assert basemap._course_lengths(lines, kind, names).tolist() == [
        3000,
        3000,
        1000,
        500,
    ]


def test_areas_share_the_strip_once():
    west = shapely.box(0, 0, 10_000, 10_000)
    east = shapely.box(10_000, 0, 20_000, 10_000)
    by_okres, slovakia = basemap.areas({"1": west, "2": east})
    strip = [by_okres[o].waters.difference(by_okres[o].land) for o in "12"]
    assert abs(strip[0].intersection(strip[1]).area) < 1e-6
    total = strip[0].area + strip[1].area
    assert abs(total - slovakia.waters.difference(slovakia.land).area) < 1e-3
    assert by_okres["1"].land.equals(west)


def test_base_file_and_verify():
    to_wgs84 = geo.transformer()
    # Around Bratislava, in EPSG:5514.
    road = shapely.LineString([(-570_000, -1_276_000), (-569_000, -1_276_000)])
    pond = shapely.box(-570_000, -1_277_000, -569_900, -1_276_900)
    content = basemap.base_file(
        {basemap.PRIMARY: np.array([road])}, np.array([pond]), to_wgs84, 100_000
    )
    assert content["lines"] == [basemap.PRIMARY, basemap.WATER]
    assert content["features"] == [{"properties": {}, "arcs": [[[1]]]}]
    assert basemap.verify("okres/101/2.json", content) == []
    assert basemap.verify(basemap.COARSE_FILE, content) == [
        "line code 6 not drawn at level coarse"
    ]
    content["features"] = []
    assert basemap.verify("okres/101/0.json", content) == [
        "the rings of the water areas are not the arcs coded WATER"
    ]


def test_requested():
    index = {"bands": [{"lod": "2"}, {"lod": "0"}], "okresy": ["101"]}
    assert basemap.requested(index) == [
        "coarse.json",
        "okres/101/2.json",
        "okres/101/0.json",
    ]
