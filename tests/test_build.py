import dataclasses
import datetime as dt
import html
import json
import re
import shutil
from pathlib import Path

import pytest

from election_map_slovakia import (
    addresses,
    build,
    bundle,
    check,
    config,
    obvody,
    results,
)

REPO = Path(__file__).resolve().parent.parent


def candidacy(contest: str, number: int, person: str, **extra: object) -> dict:
    return {
        "id": f"{contest}#{number}",
        "contest": contest,
        "number": number,
        "person": person,
        "title_before": "",
        "title_after": "",
        "first_name": "Ján",
        "surname": f"Novák{number}",
        "age": 40,
        "occupation": "učiteľ",
        "parties": [],
        "independent": True,
    } | extra


CONTESTS = [
    "starosta:BA",
    "oz:BA/1",
    "starosta:528595",
    "oz:528595/1",
    "oz:528595/2",
    "starosta:508063",
    "oz:508063/1",
    "predseda:1",
    "zsk:1/1",
    "zsk:1/2",
]

DATA = {
    "kraje": [{"code": "1", "name": "Bratislavský"}],
    "okresy": [
        {"code": "101", "name": "Bratislava I", "kraj": "1"},
        {"code": "106", "name": "Malacky", "kraj": "1"},
    ],
    "obce": [
        {"code": "BA", "name": "Bratislava", "kraj": "1"},
        {
            "code": "528595",
            "name": "Bratislava-Staré Mesto",
            "okres": "101",
            "kraj": "1",
            "city": "BA",
        },
        {"code": "508063", "name": "Jakubov", "okres": "106", "kraj": "1"},
    ],
    "contests": [
        {"id": c, "kind": c.split(":")[0], "area": c.split(":")[1].split("/")[0]}
        | ({"obvod": int(c.split("/")[1])} if "/" in c else {})
        for c in CONTESTS
    ],
    "candidacies": [
        candidacy("starosta:BA", 1, "p1"),
        candidacy("oz:BA/1", 1, "p2"),
        candidacy("oz:528595/2", 1, "p2"),
        candidacy("starosta:508063", 1, "p3"),
        candidacy("oz:508063/1", 1, "p3"),
        candidacy("zsk:1/2", 1, "p3", residence="508063"),
        candidacy("predseda:1", 1, "p4", residence="528595"),
    ],
    "persons": [],
}


def write_geo(directory: Path, regional: bool = True) -> None:
    """The parts of the geo files that build reads (see geo.py); without
    *regional*, of an election without regional council obvody."""
    shards = {
        "101": [{"id": "528595", "zsk": 1, "city": "BA", "city_obvod": 1}],
        "106": [{"id": "508063", "zsk": 2}],
    }
    for okres, props in shards.items():
        (directory / "okres" / okres).mkdir(parents=True)
        features = [{"properties": p | ({} if regional else {"zsk": 0})} for p in props]
        (directory / "okres" / okres / "2.json").write_text(
            json.dumps({"features": features})
        )
    obvody = [
        {"id": "zsk:1/1", "seats": 3},
        {"id": "zsk:1/2", "seats": 2},
        {"id": "oz:BA/1", "seats": 5},
    ]
    (directory / "coarse.json").write_text(
        json.dumps({"obvody": obvody if regional else []})
    )
    (directory / "index.json").write_text(json.dumps({"okrsky": {"drawn": {}}}))


# The 2022 election is drawn on the 2026 boundaries (config/elections.toml):
# land swapped between two obce.
BOUNDARIES = """
compared = 2022-01-18
[[change]]
obce = ["528595", "508063"]
"""


def test_boundary_changes(tmp_path: Path):
    (tmp_path / bundle.BOUNDARIES_FILE).write_text(
        BOUNDARIES + '[[change]]\nobce = ["529397"]\nstate_border = true\n'
    )
    assert bundle.boundary_changes(tmp_path) == {
        "day": "2022-01-18",
        # Along the state border, no neighbour is named.
        "obce": {"508063": ["528595"], "528595": ["508063"], "529397": []},
    }
    assert bundle.boundary_changes(tmp_path / "elsewhere") is None


def write_built(built: Path, data: dict, regional: bool = True) -> None:
    """What the steps made of an election whose candidates.json is *data*."""
    write_geo(built / "geo", regional)
    (built / "addr").mkdir(parents=True)
    (built / "addr" / "index.json").write_text("{}")
    (built / "candidates.json").write_text(json.dumps(data, ensure_ascii=False))
    (built / bundle.LINKS_DIR).mkdir()


def write_base(directory: Path) -> None:
    """What `basemap` made of an extract, *directory* its build directory."""
    (directory / "base").mkdir(parents=True, exist_ok=True)
    (directory / "base" / "index.json").write_text('{"bands": [], "okresy": []}')


# A presidential election's candidates.json (config/elections.toml has two):
# the same places, both rounds.
PRESIDENTIAL = {
    **{k: DATA[k] for k in ("kraje", "okresy", "obce")},
    "contests": [
        {"id": "prezident:SK/1", "kind": "prezident", "area": "SK", "obvod": 1},
        {"id": "prezident:SK/2", "kind": "prezident", "area": "SK", "obvod": 2},
    ],
    "candidacies": [
        candidacy("prezident:SK/1", 1, "q1", residence="528595"),
        candidacy("prezident:SK/1", 2, "q2", residence="508063"),
        candidacy("prezident:SK/2", 1, "q2", residence="508063"),
    ],
    "persons": [],
}


def project(root: Path) -> config.Config:
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / "web", root / "web")
    cfg = config.load(root / "config")
    # What the steps made of each election (config/elections.toml): the
    # same candidates for those of a kind, unlinked; every one but the
    # newest drawn on its boundaries.
    for e in cfg.elections:
        presidential = e.kind == "presidential"
        data = PRESIDENTIAL if presidential else DATA
        write_built(cfg.election_build_dir(e), data, regional=not presidential)
        if e != cfg.elections[0]:
            cfg.election_dir(e).mkdir(parents=True)
            (cfg.election_dir(e) / bundle.BOUNDARIES_FILE).write_text(BOUNDARIES)
    for osm in cfg.bases:
        write_base(cfg.base_build_dir(osm))
    return cfg


def test_every_contest_is_in_exactly_one_area_file():
    files = bundle.area_files(DATA, {"zsk:1/2": 2})
    placed = [c for f in files.values() for c in f["contests"]]
    assert sorted(placed) == sorted(CONTESTS)
    assert set(files["data/okres/101.json"]["contests"]) == {
        "starosta:528595",
        "oz:528595/1",
        "oz:528595/2",
    }
    assert set(files["data/city/BA.json"]["contests"]) == {"starosta:BA", "oz:BA/1"}
    assert files["data/kraj/1.json"]["contests"]["zsk:1/2"]["seats"] == 2
    # A contest without candidates is still listed, so the ballot shows it.
    assert files["data/okres/101.json"]["contests"]["oz:528595/1"]["candidates"] == []


def test_person_lists_candidacies_in_other_files():
    files = bundle.area_files(DATA, {})
    everywhere = ["starosta:508063#1", "oz:508063/1#1", "zsk:1/2#1"]
    assert files["data/okres/106.json"]["persons"]["p3"] == everywhere
    assert files["data/kraj/1.json"]["persons"]["p3"] == everywhere
    assert "p4" not in files["data/kraj/1.json"]["persons"]


def test_origin_flags_are_of_the_units_drawn():
    """The flags of where obvody and okrsky come from reach data/index.json
    only for the obvody and okrsky the map draws."""
    dated = obvody.Dating("archived", dt.date(2022, 9, 28), "captured")
    later = obvody.Supplement(dt.date(2026, 10, 24), "election", "its hamlets")
    rules = obvody.RuleSet(
        obec="508063",
        name="Jakubov",
        date=None,
        documents=(),
        seats={1: 3, 2: 2},
        rules=(),
        dating=dated,
        supplement=later,
        okrsky={1: (1,), 2: (2,)},
        okrsky_referendum=dt.date(2023, 1, 21),
        okrsky_dating=dataclasses.replace(dated, by="named", seen=None),
        okrsky_supplement=dataclasses.replace(later, source="document"),
    )
    props = {"508063": {"oz": 1}, "528595": {}}
    flags = bundle.origin_flags(props, {"508063": rules}, {"508063": rules}, [])
    assert flags == {
        "reused": {},
        "adopted": {},
        "date_approximate": {"508063": {"by": "archived", "seen": "2022-09-28"}},
        "supplemented": {"508063": {"from": "election", "day": "2026-10-24"}},
        "okrsky_reused": {},
        "okrsky_adopted": {},
        "okrsky_outliers": {},
        "okrsky_referendum": {"508063": "2023-01-21"},
        "okrsky_date_approximate": {"508063": {"by": "named"}},
        "okrsky_supplemented": {"508063": {"from": "document", "day": "2026-10-24"}},
    }
    # Obvody not drawn, okrsky not drawn: no flags.
    none = bundle.origin_flags({}, {"508063": rules}, {"508063": rules}, ["508063"])
    assert not any(none.values())


def test_adopted_flags_reach_the_index():
    """Units drawn with another vote's rules, unproven, say so by obec."""
    later = obvody.Adoption(dt.date(2026, 10, 24), "no usable 2022 document")
    rules = obvody.RuleSet(
        obec="508063",
        name="Jakubov",
        date=dt.date(2026, 6, 1),
        documents=(),
        seats={1: 3, 2: 2},
        rules=(),
        adoption=later,
        okrsky={1: (1,), 2: (2,)},
        okrsky_adoption=later,
    )
    flags = bundle.origin_flags(
        {"508063": {"oz": 1}}, {"508063": rules}, {"508063": rules}, []
    )
    assert flags["adopted"] == flags["okrsky_adopted"] == {"508063": "2026-10-24"}
    assert not flags["reused"] and not flags["okrsky_reused"]
    # Okrsky not drawn: only the obvody's flag.
    obvody_only = bundle.origin_flags(
        {"508063": {"oz": 1}}, {"508063": rules}, {"508063": rules}, ["508063"]
    )
    assert obvody_only["adopted"] and not obvody_only["okrsky_adopted"]


def test_stand_ins_listed_by_their_source_vote():
    """About lists the obce whose units stand in, by the vote whose they
    are, earlier or later; two votes of one year stay apart."""
    index = {
        "obce": {"1": ["Žilina"], "2": ["Alekšince"], "3": ["Divina"]},
        "adopted": {"3": "2018-11-10"},
        "okrsky_adopted": {"1": "2026-10-24", "2": "2026-07-04", "3": "2018-11-10"},
    }
    assert bundle.stand_ins(index) == {
        "obvody": [["2018-11-10", ["Divina"]]],
        "okrsky": [
            ["2018-11-10", ["Divina"]],
            ["2026-07-04", ["Alekšince"]],
            ["2026-10-24", ["Žilina"]],
        ],
    }


def candidacies(*ids: str) -> dict[str, list[dict[str, str]]]:
    return {"candidacies": [{"id": i, "contest": i.split("#")[0]} for i in ids]}


def test_candidacy_results_rank_equal_votes_alike():
    final = {
        "oz:1/1": {
            "valid": 100,
            "candidates": [[3, 50, 1], [1, 30, 0], [2, 30, 0], [4, 5, -1]],
        }
    }
    data = candidacies("oz:1/1#1", "oz:1/1#2", "oz:1/1#3", "oz:1/1#4")
    assert bundle.candidacy_results(final, data) == {
        "oz:1/1#3": [50, 100, 1, 4, 1],
        "oz:1/1#1": [30, 100, 2, 4, 0],
        "oz:1/1#2": [30, 100, 2, 4, 0],
        "oz:1/1#4": [5, 100, 4, 4, -1],
    }


def test_candidacy_results_of_the_elected_only():
    # A by-election of 2019–2022 published the elected councillors' votes
    # only: the others stood, were not elected, their votes unknown.
    final = {"oz:1/1": {"valid": 80, "candidates": [[2, 50, 1], [4, 40, 1]]}}
    data = candidacies("oz:1/1#1", "oz:1/1#2", "oz:1/1#3", "oz:1/1#4")
    assert bundle.candidacy_results(final, data) == {
        "oz:1/1#2": [50, 80, 1, 4, 1],
        "oz:1/1#4": [40, 80, 2, 4, 1],
        "oz:1/1#1": [None, 80, None, 4, 0],
        "oz:1/1#3": [None, 80, None, 4, 0],
    }


def test_elsewhere_lists_every_candidacy_both_ways():
    later = {
        "persons": [{"id": "a", "candidacies": ["starosta:1#2"]}],
        "candidacies": [],
    }
    earlier = {
        "persons": [{"id": "x", "candidacies": ["oz:1/2#7", "starosta:1#1"]}],
        "candidacies": [],
    }
    persons = bundle.linked_persons(
        {("2026", "2022"): {"persons": {"a": "x"}, "candidacies": {}}}
    )
    assert persons == {"2026": {"2022": {"a": "x"}}, "2022": {"2026": {"x": "a"}}}
    # Final results of the earlier election only: the later's are bare ids.
    results = {"2022": {"starosta:1#1": [40, 90, 1, 2, 1]}}
    out = bundle.elsewhere({"2026": later, "2022": earlier}, persons, results)
    assert out["2026"] == {
        "a": {"2022": [["oz:1/2#7"], ["starosta:1#1", 40, 90, 1, 2, 1]]}
    }
    assert out["2022"] == {"x": {"2026": [["starosta:1#2"]]}}
    files = bundle.area_files(DATA, {}, other={"p3": {"2022": [["oz:9/1#1"]]}})
    assert files["data/okres/106.json"]["elsewhere"] == {"p3": {"2022": [["oz:9/1#1"]]}}
    assert "elsewhere" not in files["data/city/BA.json"]


def finding(published: str, kind: str = "cv") -> dict:
    return {"published": published, "kind": kind}


def test_reused_research_keeps_findings_dated_before_the_day(tmp_path: Path):
    cfg = project(tmp_path)
    researched = {
        category: {"date": "2026-10-20", "job": "research-1"}
        for categories in cfg.sources.research.values()
        for category in categories
    }
    records = {
        "a": {
            "researched": researched,
            "findings": [
                finding("2021-05-01", "affair"),
                # The eve of the election day is before it; the day itself not.
                finding("2022-10-28"),
                finding("2022-10-29"),
                finding(""),
                finding("2024-01-01", "dispute"),
            ],
        },
        "b": {"researched": researched, "findings": []},
    }
    reused = bundle.reused_research(records, {"a": "x", "c": "z"}, "2022-10-29")
    assert list(reused) == ["x"]
    assert reused["x"]["findings"] == [
        finding("2021-05-01", "affair"),
        finding("2022-10-28"),
    ]
    assert reused["x"]["undated"] == 1
    date, n, _, affairs, disputes, undated = bundle.research_summary(cfg, reused)["x"]
    assert (date, n, affairs, disputes, undated) == ("2026-10-20", 2, 1, 0, 1)
    # The latest election's own summary has no `undated`.
    assert len(bundle.research_summary(cfg, records)["a"]) == 5


def past(election: str, eligible: int, voters: int) -> dict:
    return {
        "election": election,
        "day": "2022-10-29",
        "eligible": eligible,
        "voters": voters,
    }


def test_regional_past_sums_the_obce_of_each_2026_obvod():
    data = {
        "obce": [
            # The cities have no regional figures: their districts do.
            {"code": "BA", "kraj": "1"},
            {"code": "528595", "kraj": "1", "past": past("osk2022", 100, 30)},
            {"code": "508063", "kraj": "1", "past": past("osk2022", 200, 50)},
            {"code": "508071", "kraj": "1", "past": past("osk2022", 300, 60)},
        ]
    }
    props = {"528595": {"zsk": 1}, "508063": {"zsk": 2}, "508071": {"zsk": 2}}
    assert bundle.regional_past(data, props) == {
        "zsk:1/1": past("osk2022", 100, 30),
        "zsk:1/2": past("osk2022", 500, 110),
    }


def test_past_of_a_council_of_several_obvody_is_marked_whole():
    data = DATA | {
        "contests": [
            c if c["kind"] == "zsk" else c | {"past": past("oso2022", 1000, 400)}
            for c in DATA["contests"]
        ]
    }
    files = bundle.area_files(data, {}, pasts={"zsk:1/2": past("osk2022", 500, 110)})
    row = ["oso2022", "2022-10-29", 1000, 400]
    okres = files["data/okres/101.json"]["contests"]
    assert okres["oz:528595/2"]["past"] == [*row, 1]
    assert okres["starosta:528595"]["past"] == row
    assert files["data/okres/106.json"]["contests"]["oz:508063/1"]["past"] == row
    kraj = files["data/kraj/1.json"]["contests"]
    assert kraj["zsk:1/2"]["past"] == ["osk2022", "2022-10-29", 500, 110]
    assert "past" not in kraj["zsk:1/1"]


def oz(obec: str, k: int, then: dict) -> dict:
    return {"id": f"oz:{obec}/{k}", "kind": "oz", "area": obec, "past": then}


def test_council_past_adds_up_the_figures_of_its_okrsky_then():
    """A council obvod of an obec of several gets the 2022 figures of its
    okrsky (the results' `past`, by the crosswalk) with the least certain
    method among them, where all are known and the council was last
    elected in 2022; else it keeps the whole municipality's."""
    live = results.Live("final")
    councils = {
        "oz:500001/1": ["500001/1", "500001/3"],
        "oz:500001/2": ["500001/2"],
        "oz:500002/1": ["500002/1"],
        "oz:500002/2": ["500002/2"],
        "oz:500003/1": ["500003/1"],
        "oz:500003/2": ["500003/2"],
    }
    for contest, keys in councils.items():
        live.add_okrsky("okres/101", contest, {k: (1, 1, 1, {}) for k in keys})
    figure = (100, 30, 29, {1: 10})
    then = results.Past(
        "2022-10-29",
        {
            "500001/1": results.SAME,
            "500001/2": results.IDENTITY,
            "500001/3": results.APPROXIMATE,
            "500002/1": results.SAME,
            "500002/2": results.UNKNOWN,
            "500003/1": results.SAME,
            "500003/2": results.SAME,
        },
        {
            "oz:500001/1": {"500001/1": figure, "500001/3": (300, 90, 88, {1: 20})},
            "oz:500001/2": {"500001/2": (200, 50, 49, {})},
            "oz:500002/1": {"500002/1": figure},
            "oz:500003/1": {"500003/1": figure},
            "oz:500003/2": {"500003/2": figure},
        },
    )
    # The councils' own election before; the regional one's is no matter.
    live.past = {"oso": then, "osk": results.Past("2017-11-04")}
    whole = past("oso2022", 600, 170)
    # The whole council elected again in a by-election since.
    again = past("oso202303", 610, 150) | {"day": "2023-03-25"}
    data = {
        "contests": [
            oz("500001", 1, whole),
            oz("500001", 2, whole),
            oz("500002", 1, whole),
            oz("500002", 2, whole),
            oz("500003", 1, again),
            oz("500003", 2, again),
        ]
    }
    assert bundle.council_past(data, live) == {
        "oz:500001/1": past("oso2022", 400, 120) | {"scope": [results.APPROXIMATE]},
        "oz:500001/2": past("oso2022", 200, 50) | {"scope": [results.IDENTITY]},
        # Its other obvod's okrsok is not known.
        "oz:500002/1": past("oso2022", 100, 30) | {"scope": [results.SAME]},
    }
    assert bundle.council_past(data, None) == {}
    scope = [results.APPROXIMATE]
    files = bundle.area_files(
        DATA, {}, pasts={"oz:528595/2": past("oso2022", 400, 120) | {"scope": scope}}
    )
    contest = files["data/okres/101.json"]["contests"]["oz:528595/2"]
    assert contest["past"] == ["oso2022", "2022-10-29", 400, 120, scope]


def test_name_shards_find_a_person_by_each_name_word():
    data = {
        "candidacies": [
            candidacy("starosta:1", 1, "a", first_name="Ján", surname="Ďurica"),
            candidacy("starosta:1", 2, "b", first_name="Matúš", surname="Vӧrӧš"),
        ]
    }
    shards = bundle.name_shards(data)
    assert [row[0] for row in shards["ja"]] == ["Ján Ďurica"]
    assert [row[0] for row in shards["du"]] == ["Ján Ďurica"]
    # The Cyrillic ӧ cannot be typed as "o"; the first name still finds him.
    assert [row[0] for row in shards["ma"]] == ["Matúš Vӧrӧš"]
    assert all(prefix.isascii() for prefix in shards)


@pytest.mark.parametrize(
    ("base_url", "noindexed"),
    [
        (None, False),
        ("https://election-map-slovakia.pages.dev", False),
        ("https://volby.example.sk", True),
    ],
)
def test_pages_dev_is_noindexed_only_beside_an_own_domain(
    tmp_path: Path, base_url: str | None, noindexed: bool
):
    cfg = project(tmp_path)
    cfg = dataclasses.replace(
        cfg, site=dataclasses.replace(cfg.site, base_url=base_url)
    )
    rules = build.header_rules(build.headers(cfg, tmp_path / "web").decode())
    for url in (
        "https://election-map-slovakia.pages.dev/sk/",
        "https://0a1b2c3d.election-map-slovakia.pages.dev/sk/",
    ):
        matching = [r for r in rules if r.pattern.fullmatch(url)]
        assert (
            ("X-Robots-Tag", "noindex") in (h for r in matching for h in r.headers)
        ) is noindexed
    # The site's own domain is indexed: no rule names it.
    assert not any(r.pattern.fullmatch("https://volby.example.sk/sk/") for r in rules)


def test_writing_over_a_build_leaves_what_writing_afresh_does(tmp_path: Path):
    """The site is written in place: what is there already stays, what is
    not wanted goes, and a file linked to the build directory is replaced,
    never written into."""
    built = tmp_path / "build"
    (built / "geo" / "okres").mkdir(parents=True)
    (built / "geo" / "index.json").write_text("{}")
    (built / "geo" / "okres" / "1.json").write_text("[1]")
    css = tmp_path / "web.css"
    css.write_text("a {}")
    dist = tmp_path / "dist"
    first = build.Site(
        {"app/x.json": b"1", "app/old/y.json": b"2"},
        {"map/geo": built / "geo", "app/style.css": css},
        [],
    )
    build.write(first, dist, link_below=built)
    linked = dist / "map" / "geo" / "okres" / "1.json"
    assert linked.stat().st_ino == (built / "geo" / "okres" / "1.json").stat().st_ino
    assert (dist / "app" / "style.css").stat().st_ino != css.stat().st_ino
    kept = (dist / "app" / "x.json").stat().st_ino
    second = build.Site(
        {"app/x.json": b"1", "map/geo/okres/1.json": b"[2]"},
        {"map/geo/index.json": built / "geo" / "index.json"},
        [],
    )
    sizes = build.write(second, dist, link_below=built)
    assert sizes == build.write(second, tmp_path / "fresh")
    assert {
        p.relative_to(dist).as_posix(): p.read_bytes()
        for p in dist.rglob("*")
        if p.is_file()
    } == {
        "app/x.json": b"1",
        "map/geo/okres/1.json": b"[2]",
        "map/geo/index.json": b"{}",
    }
    assert not (dist / "app" / "old").exists()
    assert (dist / "app" / "x.json").stat().st_ino == kept
    assert (built / "geo" / "okres" / "1.json").read_text() == "[1]"


def test_build_is_deterministic(tmp_path: Path):
    cfg = project(tmp_path / "project")
    first = build.write(build.assemble(cfg, None), tmp_path / "a")
    second = build.write(build.assemble(cfg, None), tmp_path / "b")
    assert first == second
    for path in first:
        assert (tmp_path / "a" / path).read_bytes() == (
            tmp_path / "b" / path
        ).read_bytes()
    bundle_dir = tmp_path / "a" / "data" / "2026"
    index = json.loads((bundle_dir / "data" / "index.json").read_bytes())
    assert index["obce"]["528595"] == [
        "Bratislava-Staré Mesto",
        "101",
        "1",
        1,
        2,
        "BA",
        1,
    ]
    assert index["obce"]["BA"] == ["Bratislava", "", "1", 0, 1]
    for code in cfg.languages.codes:
        # The latest election's page, also at the language's own.
        assert first[f"app/{code}/index.html"] == first[f"app/{code}/2026/index.html"]
        assert (tmp_path / "a" / "app" / code / "index.html").read_bytes() == (
            tmp_path / "a" / "app" / code / "2026" / "index.html"
        ).read_bytes()
        assert f"app/i18n/{code}.json" in first
    # The app holds none of an election's data, and a bundle no app code.
    assert not any(
        p.startswith(("app/data/", "app/geo/", "app/addr/", "app/base/")) for p in first
    )
    assert not any(
        p.startswith(("data/2026/assets/", "map/2026/assets/")) for p in first
    )
    # The map's files are in the map bundle, the rest in the data bundle.
    assert (
        "map/2026/geo/index.json" in first and "data/2026/geo/index.json" not in first
    )
    assert (
        "data/2026/data/index.json" in first and "map/2026/data/index.json" not in first
    )
    pending = json.loads((tmp_path / "a" / "app" / "i18n" / "de.json").read_bytes())
    assert pending["_pending"] == pending["_locale"] == "en"
    assert pending["_missing"] == len(
        json.loads((REPO / "web/i18n/en.json").read_bytes())
    )
    # Each manifest lists exactly its bundle's files but its own.
    own = {bundle.MANIFEST, bundle.HEADERS, bundle.NOT_FOUND}
    for part in ("map/2026/", "data/2026/", "base/osm-slovakia-2026/"):
        manifest = json.loads((tmp_path / "a" / part / bundle.MANIFEST).read_bytes())
        assert (
            set(manifest["files"])
            == {p.removeprefix(part) for p in first if p.startswith(part)} - own
        )
    # The base map is a part of its own, one per extract, not the map's.
    assert not any(p.startswith("map/2026/base/") for p in first)
    bases = {p.split("/")[1] for p in first if p.startswith("base/")}
    assert bases == set(cfg.bases)
    base = json.loads(
        (tmp_path / "a/base/osm-slovakia-2026/manifest.json").read_bytes()
    )
    assert (base["base"], base["files"]) == ("osm-slovakia-2026", ["index.json"])
    # Linked to what `basemap` made, as the map bundles are.
    linked = tmp_path / "c"
    build.write(build.assemble(cfg, None), linked, link_below=cfg.build_dir)
    built = cfg.base_build_dir("osm-slovakia-2026") / "base" / "index.json"
    assert (linked / "base/osm-slovakia-2026/index.json").samefile(built)


def app_config(site: build.Site, page: str = "sk/index.html") -> dict:
    shell = site.files[f"app/{page}"].decode()
    match = re.search(r'<meta name="km-config" content="([^"]*)"', shell)
    assert match is not None
    return json.loads(html.unescape(match[1]))


def page_policy(site: build.Site, page: str) -> str:
    """The Content-Security-Policy of the <meta> of app page *page*, which
    comes before anything that loads, as it covers only what follows it."""
    text = site.files[f"app/{page}"].decode()
    match = re.search(
        r'<meta http-equiv="Content-Security-Policy" content="([^"]*)"', text
    )
    assert match is not None
    assert not re.search(r"<(script|link|style)\b", text[: match.start()])
    return html.unescape(match[1])


def policy(*origins: str) -> str:
    """The <meta> policy of a page that fetches from its own and *origins*."""
    connect = " ".join(["'self'", *origins])
    return f"default-src 'self'; connect-src {connect}; img-src 'self' data:"


def versions(site: build.Site) -> dict[str, str]:
    """The code, vendor, image, map, data and base versions of *site*, and its paths."""
    shell = site.files["app/sk/index.html"].decode()
    app = app_config(site)
    code = re.search(r'<script type="module" src="/assets/(\w+)/js/app.js">', shell)
    vendor = re.search(r'src="/assets/vendor/(\w+)/leaflet/leaflet.js"', shell)
    assert code is not None and vendor is not None
    [images] = (t.split("/")[3] for t in site.copies if t.startswith("app/assets/img/"))
    return {
        "code": code[1],
        "vendor": vendor[1],
        "images": images,
        "map": app["mapVersion"],
        "data": app["dataVersion"],
        "base": app["baseVersion"],
        "strings": app["stringsVersion"],
        "results": app["results"],
        "map prefix": app["map"],
        "prefix": app["data"],
        "base prefix": app["base"],
    }


def cache_control(site: build.Site, part: str, path: str) -> str:
    """The Cache-Control of *path* of *part*, by the part's own _headers."""
    rules = build.header_rules(site.files[f"{part}/{bundle.HEADERS}"].decode())
    return build.response_headers(rules, path)["Cache-Control"]


def test_versions_and_results(tmp_path: Path):
    cfg = project(tmp_path / "project")
    built = cfg.election_build_dir(cfg.latest)
    # A party with a logo, which data/index.json names by its file.
    data = json.loads((built / "candidates.json").read_bytes())
    data["candidacies"][0]["parties"] = ["Demokrati"]
    (built / "candidates.json").write_text(json.dumps(data))
    site = build.assemble(cfg, None)
    first = versions(site)
    code, vendor = first["code"], first["vendor"]
    # The results' path is named before there are any.
    assert first["results"] == "/results/2026-10-24"
    assert not any(t.startswith("results/2") for t in site.copies)
    # The election's files are in its bundles, where `serve` serves them.
    assert first["map prefix"] == "/map/2026"
    assert first["prefix"] == "/data/2026"
    assert first["base prefix"] == "/base/osm-slovakia-2026"
    assert site.copies["map/2026/geo"] == built / "geo"
    base_dir = cfg.base_build_dir("osm-slovakia-2026") / "base"
    assert site.copies["base/osm-slovakia-2026/index.json"] == base_dir / "index.json"
    base = json.loads(site.files["base/osm-slovakia-2026/manifest.json"])
    assert first["base"] == base["version"]
    # The elections on one extract name one base map, by one version.
    referendum = app_config(site, "sk/2026-referendum/index.html")
    assert (referendum["base"], referendum["baseVersion"]) == (
        first["base prefix"],
        first["base"],
    )
    shell = site.files["app/sk/index.html"].decode()
    # The preload is of the very URL the app fetches, or it goes unused.
    assert f'href="/i18n/sk.json?v={first["strings"]}"' in shell
    assert f'href="/map/2026/geo/index.json?v={first["map"]}"' in shell
    # Served from the page's own origin: nothing to preconnect to.
    assert 'rel="preconnect"' not in shell
    assert first["map"] == json.loads(site.files["map/2026/manifest.json"])["version"]
    manifest = json.loads(site.files["data/2026/manifest.json"])
    assert first["data"] == manifest["version"]
    # The UI strings are the same file for every election, by one version.
    old_shell = site.files["app/sk/2022/index.html"].decode()
    assert f'href="/i18n/sk.json?v={first["strings"]}"' in old_shell
    assert first["data"] not in old_shell
    assert f'src="/assets/{code}/js/picker.js"' in site.files["app/index.html"].decode()
    assert "sources/assets/cache.css" in site.copies
    index = json.loads(site.files["data/2026/data/index.json"])
    assert index["parties"]["Demokrati"][2] == "demokrati.svg"
    assert app_config(site)["logos"] == f"/assets/img/{first['images']}/parties"
    # Every language but Slovak has the occupations translated in the bundle.
    assert app_config(site)["occupations"] == manifest["occupations"]
    assert set(manifest["occupations"]) == set(cfg.languages.codes) - {"sk"}
    # The 2022 pages: the credits name the dates of their data and the
    # boundaries they are drawn on; About lists only their own inputs and
    # what comes from 2026, with the day each was retrieved; the ballots
    # name the obce whose boundary moved.
    assert app_config(site, "sk/2022/index.html")["credits"] == {
        "boundaries": ["2026", 2],
        "osm": "2022-01-01",
        "addresses": "2022-09",
    }
    old = json.loads(site.files["data/2022/data/index.json"])
    assert old["boundaries"] == {
        "day": "2022-01-18",
        "on": "2026",
        "obce": {"508063": ["528595"], "528595": ["508063"]},
    }
    about = json.loads(site.files["data/2022/data/about.json"])
    names = {i["name"]: i for i in about["inputs"]}
    assert {"addresses-2022", "osm-slovakia-2022", "natural-earth-countries"} <= set(
        names
    )
    assert not names.keys() & {
        "addresses-2026",
        "osm-slovakia-2026",
        "candidates-oz-2026",
    }
    assert names["osm-slovakia-2022"]["retrieved"] == "2026-10-28"
    assert about["candidates"] == "susr"
    assert about["substitutes"]["latest"] == "2026"
    assert about["substitutes"]["osm"] == "2022-01-01"
    assert json.loads(site.files["data/2026/data/about.json"])["substitutes"] is None
    # The modules import the libraries from their versioned directory.
    app_js = site.files[f"app/assets/{code}/js/app.js"].decode()
    assert f"from '/assets/vendor/{vendor}/preact-htm.module.js'" in app_js
    assert "../vendor/" not in app_js
    # The data parts are served from the app's origin: every page fetches
    # from its own alone.
    for page in ("sk/index.html", "sk/2022/index.html", "index.html", "404.html"):
        assert page_policy(site, page) == policy()
    # What a <meta> cannot carry is a header of every response.
    rules = build.header_rules(site.files[f"app/{bundle.HEADERS}"].decode())
    assert build.response_headers(rules, "/sk/")["Content-Security-Policy"] == (
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    immutable = "public, max-age=31536000, immutable"
    day = "public, max-age=86400"
    assert {
        (part, path): cache_control(site, part, path)
        for part, path in (
            ("app", f"/assets/{code}/js/app.js"),
            ("app", f"/assets/vendor/{vendor}/leaflet/leaflet.js"),
            ("app", f"/assets/img/{first['images']}/parties/demokrati.svg"),
            ("app", "/i18n/sk.json"),
            ("sources", "/assets/cache.css"),
            ("sources", "/cache/0a.html"),
            ("map/2026", "/geo/x.json"),
            ("data/2026", "/data/index.json"),
            ("base/osm-slovakia-2026", "/okres/101/0.json"),
            ("results", "/2026-10-24/status.json"),
            ("results", "/2026-10-24/okres/101.json"),
            ("results", "/2026-10-24/okrsky/okres/101.json"),
        )
    } == {
        ("app", f"/assets/{code}/js/app.js"): immutable,
        ("app", f"/assets/vendor/{vendor}/leaflet/leaflet.js"): immutable,
        ("app", f"/assets/img/{first['images']}/parties/demokrati.svg"): immutable,
        ("app", "/i18n/sk.json"): day,
        ("sources", "/assets/cache.css"): day,
        ("sources", "/cache/0a.html"): day,
        # A deployment's address always serves the same bundle.
        ("map/2026", "/geo/x.json"): immutable,
        ("data/2026", "/data/index.json"): immutable,
        ("base/osm-slovakia-2026", "/okres/101/0.json"): immutable,
        # Revalidated on every load: it names the current results files.
        ("results", "/2026-10-24/status.json"): "no-cache",
        ("results", "/2026-10-24/okres/101.json"): day,
        ("results", "/2026-10-24/okrsky/okres/101.json"): day,
    }
    # Other code: new code URLs only; the libraries, images and data keep theirs.
    css = cfg.root / "web" / "app.css"
    css.write_text(css.read_text() + "\n/* changed */\n")
    second = versions(build.assemble(cfg, None))
    assert second["code"] != code
    assert {k: second[k] for k in ("vendor", "images", "map", "data", "base")} == {
        k: first[k] for k in ("vendor", "images", "map", "data", "base")
    }
    # Another library: new library and code URLs.
    lib = cfg.root / "web" / "vendor" / "preact-htm.module.js"
    lib.write_text(lib.read_text() + "\n")
    third = versions(build.assemble(cfg, None))
    assert third["vendor"] != second["vendor"]
    assert third["code"] != second["code"]
    assert third["images"] == second["images"]
    # Another map: a new map version; the data's, the base map's and the
    # strings' the same, so browsers keep the candidates and the base map,
    # and the other way round.
    (built / "addr" / "index.json").write_text('{"obce": []}')
    fourth = versions(build.assemble(cfg, None))
    assert fourth["map"] != third["map"]
    assert fourth["data"] == third["data"]
    assert fourth["base"] == third["base"]
    assert fourth["strings"] == third["strings"]
    data["candidacies"][0]["parties"] = []
    (built / "candidates.json").write_text(json.dumps(data))
    fifth = versions(build.assemble(cfg, None))
    assert fifth["data"] != fourth["data"]
    assert fifth["map"] == fourth["map"]
    assert fifth["base"] == fourth["base"]
    # Another base map: its version alone.
    (base_dir / "index.json").write_text('{"bands": [], "okresy": ["101"]}')
    sixth = versions(build.assemble(cfg, None))
    assert sixth["base"] != fifth["base"]
    assert {k: sixth[k] for k in ("map", "data", "strings")} == {
        k: fifth[k] for k in ("map", "data", "strings")
    }
    # The election's results: copied into their own part; the bundle stays.
    results = cfg.results_dir(cfg.latest)
    results.mkdir(parents=True)
    (results / "status.json").write_text('{"phase": "none"}')
    site = build.assemble(cfg, None)
    assert site.copies["results/2026-10-24"] == results
    assert versions(site)["data"] == fifth["data"]
    assert versions(site)["results"] == "/results/2026-10-24"
    # Its live results: in the live part alone, beside the final ones,
    # which the app of an election without `live` does not read.
    live = cfg.live_dir(cfg.latest)
    live.mkdir(parents=True)
    (live / "status.json").write_text('{"phase": "none", "version": "v1"}')
    site = build.assemble(cfg, None)
    assert site.copies["live/2026-10-24"] == live
    assert site.copies["results/2026-10-24"] == results
    assert json.loads(site.files["live/manifest.json"]) == {
        "versions": {"2026-10-24": "v1"}
    }
    assert site.files["live/_headers"] == (cfg.root / "web/_headers-live").read_bytes()
    assert cache_control(site, "live", "/2026-10-24/status.json") == "no-cache"
    assert versions(site)["data"] == fifth["data"]
    assert app_config(site)["live"] is None
    shutil.rmtree(results)
    site = build.assemble(cfg, None)
    assert not any(t.startswith("results/2") for t in site.copies)
    assert site.copies["live/2026-10-24"] == live


def test_each_election_names_its_own_logos(tmp_path: Path):
    """A party whose logo changed between elections shows each election's."""
    root = tmp_path / "project"
    project(root)
    parties = root / "config" / "parties.toml"
    parties.write_text(
        parties.read_text(encoding="utf-8")
        + '\n[party."Demokrati".logo.2022]\nfile = "oks.webp"\n'
        'source = "https://example.org/old"\nlicense = "CC0"\n',
        encoding="utf-8",
    )
    cfg = config.load(root / "config")
    for election in cfg.elections:
        built = cfg.election_build_dir(election) / "candidates.json"
        data = json.loads(built.read_bytes())
        data["candidacies"][0]["parties"] = ["Demokrati"]
        built.write_text(json.dumps(data))
    site = build.assemble(cfg, None)
    logos = {}
    for slug in ("2026", "2022"):
        index = json.loads(site.files[f"data/{slug}/data/index.json"])
        about = json.loads(site.files[f"data/{slug}/data/about.json"])
        logos[slug] = (index["parties"]["Demokrati"][2], about["logos"])
    assert logos["2022"] == (
        "oks.webp",
        [{"name": "Demokrati", "source": "https://example.org/old", "license": "CC0"}],
    )
    assert logos["2026"][0] == "demokrati.svg"
    # About credits the logos its election shows, and no other.
    assert [entry["name"] for entry in logos["2026"][1]] == ["Demokrati"]


def test_the_app_for_deployed_data(tmp_path: Path):
    """Built for deployed data parts, the app alone names them by address."""
    cfg = project(tmp_path / "project")
    local = build.assemble(cfg, None)

    def located(part: str, slug: str) -> build.Located:
        return build.Located(
            f"https://0a1b2c3d.ems-{part}-{slug}.pages.dev",
            json.loads(local.files[f"{part}/{slug}/manifest.json"]),
        )

    def based(osm: str) -> build.Located:
        # Every base map in one project, each its own deployment.
        return build.Located(
            f"https://{osm[-4:]}abcd.ems-base.pages.dev",
            json.loads(local.files[f"base/{osm}/manifest.json"]),
        )

    slugs = [e.slug for e in cfg.elections]
    deployed = build.Locations(
        {slug: located("map", slug) for slug in slugs},
        {slug: located("data", slug) for slug in slugs},
        {osm: based(osm) for osm in cfg.bases},
        "https://results.example.sk",
        "https://live.example.sk",
        "https://sources.example.sk",
    )
    site = build.assemble_deployed(cfg, deployed)
    assert all(t.startswith("app/assets/") for t in site.copies)
    assert {p for p in site.files if not p.startswith("app/")} == {
        *(f"{part}/{slug}/manifest.json" for part in ("map", "data") for slug in slugs),
        *(f"base/{osm}/manifest.json" for osm in cfg.bases),
    }
    manifest = json.loads(site.files["map/2022/manifest.json"])
    assert manifest["url"] == "https://0a1b2c3d.ems-map-2022.pages.dev"
    base = json.loads(site.files["base/osm-slovakia-2022/manifest.json"])
    assert base["url"] == "https://2022abcd.ems-base.pages.dev"
    app = app_config(site, "sk/2022/index.html")
    assert app["map"] == "https://0a1b2c3d.ems-map-2022.pages.dev"
    assert app["data"] == "https://0a1b2c3d.ems-data-2022.pages.dev"
    assert app["base"] == "https://2022abcd.ems-base.pages.dev"
    assert app["baseVersion"] == base["version"]
    assert app["results"] == "https://results.example.sk/2022-10-29"
    assert app["live"] is None
    assert app["sources"] == "https://sources.example.sk"
    shell = site.files["app/sk/2022/index.html"].decode()
    assert (
        'href="https://0a1b2c3d.ems-map-2022.pages.dev/geo/index.json?v='
        f'{manifest["version"]}"'
    ) in shell
    # The map's and the base map's servers are connected to as the page
    # loads.
    for url in (
        "https://0a1b2c3d.ems-map-2022.pages.dev",
        "https://2022abcd.ems-base.pages.dev",
    ):
        assert f'<link rel="preconnect" href="{url}"' in shell
    origins = sorted(
        [
            *(
                f"https://0a1b2c3d.ems-{part}-{slug}.pages.dev"
                for part in ("data", "map")
                for slug in slugs
            ),
            *(based(osm).url for osm in cfg.bases),
        ]
    )
    # Every shell may fetch from every election's data parts; the picker
    # and the 404 page from their own origin alone.
    for page in ("sk/2022/index.html", "en/index.html"):
        assert page_policy(site, page) == policy(*origins, "https://results.example.sk")
    assert page_policy(site, "index.html") == policy()
    assert page_policy(site, "404.html") == policy()
    # An election with `live` reads the live results too, which the CSP lets
    # it fetch.
    live = dataclasses.replace(
        cfg,
        elections=tuple(
            dataclasses.replace(e, live=e.slug == "2022") for e in cfg.elections
        ),
    )
    site = build.assemble_deployed(live, deployed)
    assert app_config(site, "sk/2022/index.html")["live"] == (
        "https://live.example.sk/2022-10-29"
    )
    assert app_config(site, "sk/2026/index.html")["live"] is None
    assert page_policy(site, "sk/2026/index.html") == policy(
        *origins, "https://live.example.sk", "https://results.example.sk"
    )


def test_a_release_s_many_origins_stay_out_of_the_headers(tmp_path: Path):
    """A release names each bundle by its deployment's origin, dozens of
    them: they are in each shell's <meta>, and the app's _headers stays
    within the Pages limits (2,000 characters a line)."""
    cfg = project(tmp_path / "project")
    manifest = {"version": "0a1b2c3d", "occupations": {}}
    # The project's elections and 30 more, as many as a release has.
    slugs = [e.slug for e in cfg.elections] + [f"{n:02}" for n in range(30)]

    def located(part: str, name: str) -> build.Located:
        return build.Located(f"https://0a1b2c3d.ems-{part}-{name}.pages.dev", manifest)

    locations = build.Locations(
        {slug: located("map", slug) for slug in slugs},
        {slug: located("data", slug) for slug in slugs},
        {osm: located("base", osm) for osm in [*cfg.bases, *map(str, range(10))]},
        "https://results.example.sk",
        "https://live.example.sk",
        "https://sources.example.sk",
    )
    site = build.assemble_deployed(cfg, locations)
    dist = tmp_path / "dist"
    (dist / build.APP_PART).mkdir(parents=True)
    (dist / build.APP_PART / bundle.HEADERS).write_bytes(
        site.files[f"app/{bundle.HEADERS}"]
    )
    assert check._headers_problems(dist, build.APP_PART) == []
    origins = locations.origins(live=False)
    assert len(origins) == 2 * len(slugs) + len(cfg.bases) + 10 + 1
    assert page_policy(site, "sk/2026/index.html") == policy(*origins)


def common(zbgis: tuple[str, ...], osm: str) -> str:
    """The fields every election has, its ZBGIS inputs its own, so that
    each is drawn on its own boundaries, and so its extract *osm*, whose
    base map is cut by them."""
    return (
        "polls_open = 07:00:00\npolls_close = 22:00:00\nlive = false\n"
        f'live_days = 7\naddresses = "addresses-2026"\nosm = "{osm}"\nrecords = []\n'
        f"zbgis = {json.dumps(list(zbgis))}\n"
    )


def extract(n: int) -> str:
    """An input of config/inputs.toml standing in for extract ``osm-new-<n>``."""
    return f"""
[input.osm-new-{n}]
url = "https://download.geofabrik.de/europe/slovakia-new-{n}.osm.pbf"
file = "slovakia-new-{n}.osm.pbf"
kind = "pbf"
sha256 = "{n:064x}"
retrieved = 2026-10-25
as_of = "2026-01-01"
"""


# One election of each new kind, with existing inputs standing in.
NEW_ELECTIONS = f"""
[election.2027-nrsr]
day = 2027-02-27
kind = "parliament"
{common(("zbgis-1-2026", "zbgis-0-2026", "zbgis-2-2026"), "osm-new-1")}
seats = 150
threshold = 5.0
coalition_thresholds = [[2, 7.0], [4, 10.0]]
preferences = 4
preference_quota = 3.0
candidates = {{ format = "curated" }}

[election.2027-01]
day = 2027-01-16
kind = "by-election"
{common(("zbgis-0-2026", "zbgis-2-2026", "zbgis-1-2026"), "osm-new-2")}
candidates = {{ format = "susr-by", package = "results-oso202303" }}

[election.2025-prezident]
day = 2025-03-22
kind = "presidential"
second_round = 2025-04-05
{common(("zbgis-2-2026", "zbgis-1-2026", "zbgis-0-2026"), "osm-new-3")}
candidates = {{ format = "curated" }}

[election.2025-referendum]
day = 2025-01-18
kind = "referendum"
questions = ["Súhlasíte s A?", "Súhlasíte s B?"]
{common(("zbgis-1-2026", "zbgis-2-2026", "zbgis-0-2026"), "osm-new-4")}

[election.2009-ep]
day = 2009-06-06
kind = "european"
{common(("zbgis-2-2026", "zbgis-0-2026", "zbgis-1-2026"), "osm-new-5")}
seats = 15
threshold = 5.0
preferences = 2
preference_quota = 10.0
candidates = {{ format = "curated" }}
"""

# A coalition of two parties, which needs the threshold of two.
COALITION = """
[party."Spolu"]
short = "Spolu"
name = "Spolu – koalícia"
members = ["Demokrati", "Alternatíva pre Slovensko"]
"""


def country(contests: list[dict], candidacies: list[dict]) -> dict:
    """``candidates.json`` of a country-wide election (contract §4)."""
    return {key: DATA[key] for key in ("kraje", "okresy", "obce")} | {
        "contests": contests,
        "candidacies": candidacies,
        "persons": [],
    }


def party_list(kind: str, subjects: list[dict], **facts: object) -> list[dict]:
    """The party contest of *kind* and the list contest of each subject."""
    contest = {"id": f"{kind}:SK", "kind": kind, "area": "SK", "subjects": subjects}
    lists = [
        {
            "id": f"{kind}:SK/{s['number']}",
            "kind": kind,
            "area": "SK",
            "obvod": s["number"],
            "party": s["party"],
        }
        for s in subjects
    ]
    return [contest | facts, *lists]


NATIONAL = {
    "2027-02-27": country(
        party_list(
            "nrsr",
            [
                {"number": 1, "party": "Demokrati", "candidates": 2},
                {"number": 2, "party": "Spolu", "candidates": 1, "withdrawn": True},
            ],
            seats=150,
            threshold=5.0,
            coalition_thresholds=[[2, 7.0], [4, 10.0]],
            preferences=4,
            quota=3.0,
        ),
        [
            candidacy("nrsr:SK/1", 1, "n1", parties=["Demokrati"], residence="508063"),
            candidacy(
                "nrsr:SK/1", 2, "n2", parties=["Demokrati"], residence_name="Viedeň"
            ),
        ],
    ),
    "2025-03-22": country(
        [
            {"id": "prezident:SK/1", "kind": "prezident", "area": "SK", "obvod": 1},
            {
                "id": "prezident:SK/2",
                "kind": "prezident",
                "area": "SK",
                "obvod": 2,
                "day": "2025-04-05",
            },
        ],
        [
            candidacy("prezident:SK/1", 1, "q1", residence="528595"),
            candidacy("prezident:SK/1", 2, "q2", residence="508063"),
            candidacy("prezident:SK/2", 1, "q1", residence="528595"),
        ],
    ),
    "2025-01-18": country(
        [
            {
                "id": f"referendum:SK/{n}",
                "kind": "referendum",
                "area": "SK",
                "obvod": n,
                "question": question,
            }
            for n, question in ((1, "Súhlasíte s A?"), (2, "Súhlasíte s B?"))
        ],
        [],
    ),
    "2009-06-06": country(
        party_list(
            "ep",
            [{"number": 1, "party": "Demokrati", "candidates": 1}],
            seats=15,
            threshold=5.0,
            preferences=2,
            quota=10.0,
        ),
        [candidacy("ep:SK/1", 1, "e1", parties=["Demokrati"], residence="508063")],
    ),
}

# A by-election: a mayor and a whole council of one obvod (its seats given)
# in Jakubov, the president of kraj 1.
HELD = ("starosta:508063", "oz:508063/1", "predseda:1")
BY_ELECTION = DATA | {
    "contests": [
        c | ({"seats": 7} if c["kind"] == "oz" else {})
        for c in DATA["contests"]
        if c["id"] in HELD
    ],
    "candidacies": [c for c in DATA["candidacies"] if c["contest"] in HELD],
}


def new_kinds_project(root: Path) -> config.Config:
    """:func:`project` with an election of each new kind besides 2026 and 2022."""
    project(root)
    for name, extra in (
        ("elections.toml", NEW_ELECTIONS),
        ("parties.toml", COALITION),
        ("inputs.toml", "".join(extract(n) for n in range(1, 6))),
    ):
        path = root / "config" / name
        path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")
    for day, data in NATIONAL.items():
        write_built(root / "data" / "build" / day, data, regional=False)
    write_built(root / "data" / "build" / "2027-01-16", BY_ELECTION)
    cfg = config.load(root / "config")
    for osm in cfg.bases:
        write_base(cfg.base_build_dir(osm))
    return cfg


def area(site: build.Site, slug: str, name: str) -> dict:
    return json.loads(site.files[f"data/{slug}/data/{name}.json"])


def row(c: dict, residence: str) -> list:
    """A candidate row of an area file of a candidacy made by :func:`candidacy`."""
    fields = ("title_before", "first_name", "surname", "title_after", "age")
    return [
        c["number"],
        *(c[f] for f in fields),
        c["occupation"],
        c["parties"],
        c["person"],
        residence,
    ]


def test_party_research_totals():
    subjects = [
        {"number": n, "party": p, "candidates": 2}
        for n, p in ((1, "Demokrati"), (2, "Spolu"))
    ]
    contests = party_list("nrsr", subjects, threshold=5.0, preferences=4, quota=3.0)
    data = country(
        contests,
        [
            candidacy("nrsr:SK/1", 1, "a", parties=["Demokrati"]),
            candidacy("nrsr:SK/1", 2, "b", parties=["Demokrati"]),
            candidacy("nrsr:SK/2", 1, "c", parties=["Spolu"]),
        ],
    )
    researched = {
        "a": ["2026-01-01", 5, ["sk"], 1, 2],
        "b": ["2026-02-01", 3, ["sk", "en"], 2, 0, 1],
        # Researched, but on no list of this election.
        "x": ["2026-01-01", 9, ["sk"], 9, 9],
    }
    files = bundle.area_files(data, {}, researched=researched)
    party = files["data/country.json"]["contests"]["nrsr:SK"]
    # Spolu's list has nobody researched: no entry.
    assert party["research"] == {"1": [2, 8, 3, 2]}


def test_elections_of_the_new_kinds(tmp_path: Path):
    cfg = new_kinds_project(tmp_path / "project")
    assert cfg.home.slug == "2027-nrsr" and cfg.latest.slug == "2026"
    site = build.assemble(cfg, None)

    # Parliament: the parties in the country file, coalition thresholds
    # applied; each party's list a file of its own.
    nrsr = area(site, "2027-nrsr", "country")["contests"]
    assert nrsr == {
        "nrsr:SK": {
            "seats": 150,
            "preferences": 4,
            "quota": 3.0,
            "threshold": 5.0,
            "coalitions": [[2, 7.0], [4, 10.0]],
            "subjects": [[1, "Demokrati", 2, 5.0], [2, "Spolu", 1, 7.0, 1]],
        }
    }
    n1, n2 = NATIONAL["2027-02-27"]["candidacies"]
    lists = area(site, "2027-nrsr", "list/1")
    # A residence matching no obec is shown as written.
    assert lists["contests"] == {
        "nrsr:SK/1": {
            "party": "Demokrati",
            "candidates": [row(n1, "508063"), row(n2, "Viedeň")],
        }
    }
    assert area(site, "2027-nrsr", "list/2")["contests"]["nrsr:SK/2"] == {
        "party": "Spolu",
        "candidates": [],
    }
    index = json.loads(site.files["data/2027-nrsr/data/index.json"])
    # A subject's party is named though no candidacy names it.
    assert set(index["parties"]) == {"Demokrati", "Spolu"}
    # No regional council obvody, no council: 0 and 0.
    assert index["obce"]["508063"] == ["Jakubov", "106", "1", 0, 0]
    assert "held" not in index
    shards = [
        json.loads(content)
        for path, content in site.files.items()
        if path.startswith("data/2027-nrsr/data/names/")
    ]
    assert any(entry[2] == ["nrsr:SK/1#2"] for rows in shards for entry in rows)
    # Coalitions need what a party does: no coalitions.
    ep = area(site, "2009-ep", "country")["contests"]["ep:SK"]
    assert ep["threshold"] == 5.0 and "coalitions" not in ep
    assert ep["subjects"] == [[1, "Demokrati", 1, 5.0]]

    # Presidential: a contest per round, with its day; km-config's rounds
    # have each round's polling hours (round 2 after the clocks change).
    prezident = area(site, "2025-prezident", "country")
    assert {c: (e["round"], e["day"]) for c, e in prezident["contests"].items()} == {
        "prezident:SK/1": (1, "2025-03-22"),
        "prezident:SK/2": (2, "2025-04-05"),
    }
    assert prezident["persons"] == {"q1": ["prezident:SK/1#1", "prezident:SK/2#1"]}
    assert app_config(site, "sk/2025-prezident/index.html")["rounds"] == [
        ["2025-03-22", "2025-03-22T07:00:00+01:00", "2025-03-22T22:00:00+01:00"],
        ["2025-04-05", "2025-04-05T07:00:00+02:00", "2025-04-05T22:00:00+02:00"],
    ]
    assert "rounds" not in app_config(site, "sk/2026/index.html")

    # Referendum: a contest per question, without candidates or lists.
    referendum = area(site, "2025-referendum", "country")["contests"]
    assert referendum["referendum:SK/2"] == {
        "question": "Súhlasíte s B?",
        "candidates": [],
    }
    about = json.loads(site.files["data/2025-referendum/data/about.json"])
    assert about["candidates"] is None

    # By-election: where something is elected, by obec and kraj.
    index = json.loads(site.files["data/2027-01/data/index.json"])
    assert index["held"] == {
        "1": ["predseda:1"],
        "508063": ["oz:508063/1", "starosta:508063"],
    }
    assert set(area(site, "2027-01", "okres/106")["contests"]) == {
        "starosta:508063",
        "oz:508063/1",
    }
    # Its council is whole, of one obvod.
    assert index["obce"]["508063"][4] == 1

    # The home page is the newest election but a by-election; each page's
    # title and description are of its kind.
    assert site.files["app/sk/index.html"] == site.files["app/sk/2027-nrsr/index.html"]
    titles = {
        slug: re.search(
            r"<title>([^<]*)</title>", site.files[f"app/en/{slug}/index.html"].decode()
        )
        for slug in ("2027-nrsr", "2025-prezident", "2026")
    }
    assert "results of the 2027 parliamentary election" in titles["2027-nrsr"][1]
    assert "presidential candidates and results 2025" in titles["2025-prezident"][1]
    assert "municipal and regional elections 2026" in titles["2026"][1]
    # So is what the page offers, in its noscript and on the root page.
    shell = site.files["app/en/2027-nrsr/index.html"].decode()
    assert "election to the National Council of the Slovak Republic" in shell
    assert "volieb do Národnej rady SR 2027" in site.files["app/index.html"].decode()
    # The home page is the site's front page, as is the root page: their
    # texts first name every kind of election since the oldest's year.
    description = re.compile(r'<meta name="description" content="([^"]*)"')
    oldest = cfg.elections[-1].day.year
    since = {"en": f"elections since {oldest}", "sk": f"Slovensku od roku {oldest}"}
    for lang, text in since.items():
        home = site.files[f"app/{lang}/index.html"].decode()
        head, offers = description.search(home)[1], home.split("<noscript>")[1]
        assert text in head and "2027" in head.split(text)[1]
        assert text in offers and "2027" in offers.split(text)[1]
        assert text not in site.files[f"app/{lang}/2026/index.html"].decode()
    root = site.files["app/index.html"].decode()
    assert since["en"] in description.search(root)[1]
    assert since["en"] in root.split("<body>")[1] and since["sk"] in root
    base = "https://volby.example.sk"
    sitemap = build.sitemap(
        dataclasses.replace(cfg, site=dataclasses.replace(cfg.site, base_url=base))
    )
    assert sitemap is not None
    urls = re.findall(r"<loc>([^<]*)</loc>", sitemap.decode())
    assert f"{base}/sk/" in urls and f"{base}/sk/2026/" in urls
    assert f"{base}/sk/2027-01/" in urls and f"{base}/sk/2027-nrsr/" not in urls


def test_by_election_council_part_of_a_larger_one():
    """A by-election's council contest that is only some obvody of its
    council (no seats given, or an obvod above 1) is never one of a single
    obvod: no 2022 seats, its past of the whole obec, its obvody counted as
    the whole council's."""
    then = past("oso2022", 1000, 400)
    contests = [
        oz("508063", 3, then) | {"obvod": 3, "seats_2022": 9},
        oz("528595", 1, then) | {"obvod": 1, "seats": 7, "seats_2022": 7},
    ]
    part = addresses.part_councils(contests, ())
    assert part == {"508063"}
    files = bundle.area_files(
        DATA | {"contests": contests, "candidacies": []}, {}, part=part
    )
    row = ["oso2022", "2022-10-29", 1000, 400]
    assert files["data/okres/106.json"]["contests"]["oz:508063/3"] == {
        "candidates": [],
        "past": [*row, 1],
    }
    assert files["data/okres/101.json"]["contests"]["oz:528595/1"] == {
        "candidates": [],
        "seats": 7,
        "past": row,
    }
    # Without a rule set, at least two obvody: its addresses are pending.
    assert bundle.council_count([3], None, part=True) == 3
    assert bundle.council_count([1], None, part=True) == 2
    assert bundle.council_count([1], None, part=False) == 1


def test_an_uncontested_contest_is_listed_but_not_held():
    """A by-election's mayor called but held nowhere (Brezovec, 2026-03):
    its area file says what says so, the data index lists it, and neither
    the places where the vote is held nor the contests without a result
    take it."""
    why = {
        "source": "https://static.slov-lex.sk/a.pdf",
        "title": "Rozhodnutie č. 262/2025",
    }
    data = {
        "contests": [
            {"id": "starosta:520080", "kind": "starosta", "area": "520080",
             "uncontested": why},
            {"id": "oz:520080/1", "kind": "oz", "area": "520080", "obvod": 1,
             "seats": 3, "uncontested": why},
            {"id": "starosta:522198", "kind": "starosta", "area": "522198"},
        ],
    }  # fmt: skip
    assert bundle.held_areas(data) == {"522198": ["starosta:522198"]}
    assert bundle.no_result({"starosta:522198": {}}, data) == set()
    entry = bundle._contest_entry(data["contests"][1], {}, {}, None, single=True)
    assert entry == {
        "candidates": [],
        "seats": 3,
        "uncontested": [why["title"], why["source"]],
    }
