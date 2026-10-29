import dataclasses
import datetime as dt
import html
import json
import re
import shutil
from pathlib import Path

import pytest

from election_map_slovakia import build, bundle, config, obvody, results

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


def write_geo(directory: Path) -> None:
    """The parts of the geo files that build reads (see geo.py)."""
    shards = {
        "101": [{"id": "528595", "zsk": 1, "city": "BA", "city_obvod": 1}],
        "106": [{"id": "508063", "zsk": 2}],
    }
    for okres, props in shards.items():
        (directory / "okres" / okres).mkdir(parents=True)
        (directory / "okres" / okres / "2.json").write_text(
            json.dumps({"features": [{"properties": p} for p in props]})
        )
    obvody = [
        {"id": "zsk:1/1", "seats": 3},
        {"id": "zsk:1/2", "seats": 2},
        {"id": "oz:BA/1", "seats": 5},
    ]
    (directory / "coarse.json").write_text(json.dumps({"obvody": obvody}))
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


def project(root: Path) -> config.Config:
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / "web", root / "web")
    # What the steps made of each election (config/elections.toml): the
    # same candidates for both, unlinked.
    for day in ("2026-10-24", "2022-10-29"):
        built = root / "data" / "build" / day
        write_geo(built / "geo")
        (built / "addr").mkdir(parents=True)
        (built / "addr" / "index.json").write_text("{}")
        (built / "base").mkdir()
        (built / "base" / "index.json").write_text('{"bands": [], "okresy": []}')
        (built / "candidates.json").write_text(json.dumps(DATA, ensure_ascii=False))
        (built / bundle.LINKS_DIR).mkdir()
    curated = root / "data" / "curated" / "elections" / "2022-10-29"
    curated.mkdir(parents=True)
    (curated / bundle.BOUNDARIES_FILE).write_text(BOUNDARIES)
    return config.load(root / "config")


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
        "okrsky_referendum": {"508063": "2023-01-21"},
        "okrsky_date_approximate": {"508063": {"by": "named"}},
        "okrsky_supplemented": {"508063": {"from": "document", "day": "2026-10-24"}},
    }
    # Obvody not drawn, okrsky not drawn: no flags.
    none = bundle.origin_flags({}, {"508063": rules}, {"508063": rules}, ["508063"])
    assert not any(none.values())


def test_adopted_flags_reach_the_index():
    """Units drawn with a later election's rules, unproven, say so by obec."""
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


def test_candidacy_results_rank_equal_votes_alike():
    final = {
        "oz:1/1": {
            "valid": 100,
            "candidates": [[3, 50, 1], [1, 30, 0], [2, 30, 0], [4, 5, -1]],
        }
    }
    assert bundle.candidacy_results(final) == {
        "oz:1/1#3": [50, 100, 1, 4, 1],
        "oz:1/1#1": [30, 100, 2, 4, 0],
        "oz:1/1#2": [30, 100, 2, 4, 0],
        "oz:1/1#4": [5, 100, 4, 4, -1],
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
    live.past = results.Past(
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


LOCAL = build.Locations({}, {}, "/results", "")


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
    rules = build.header_rules(build.headers(cfg, tmp_path / "web", LOCAL).decode())
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
    for part in ("map/2026/", "data/2026/"):
        manifest = json.loads((tmp_path / "a" / part / bundle.MANIFEST).read_bytes())
        assert (
            set(manifest["files"])
            == {p.removeprefix(part) for p in first if p.startswith(part)} - own
        )


def app_config(site: build.Site, page: str = "sk/index.html") -> dict:
    shell = site.files[f"app/{page}"].decode()
    match = re.search(r'<meta name="km-config" content="([^"]*)"', shell)
    assert match is not None
    return json.loads(html.unescape(match[1]))


def versions(site: build.Site) -> dict[str, str]:
    """The code, vendor, image, map and data versions of *site*, and its paths."""
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
        "strings": app["stringsVersion"],
        "results": app["results"],
        "map prefix": app["map"],
        "prefix": app["data"],
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
    assert site.copies["map/2026/geo"] == built / "geo"
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
    assert not names.keys() & {"addresses", "osm-slovakia", "candidates-oz"}
    assert names["osm-slovakia-2022"]["retrieved"] == "2026-10-28"
    assert about["candidates"] == "susr"
    assert about["substitutes"]["latest"] == "2026"
    assert about["substitutes"]["osm"] == "2022-01-01"
    assert json.loads(site.files["data/2026/data/about.json"])["substitutes"] is None
    # The modules import the libraries from their versioned directory.
    app_js = site.files[f"app/assets/{code}/js/app.js"].decode()
    assert f"from '/assets/vendor/{vendor}/preact-htm.module.js'" in app_js
    assert "../vendor/" not in app_js
    rules = build.header_rules(site.files[f"app/{bundle.HEADERS}"].decode())
    csp = build.response_headers(rules, "/sk/")["Content-Security-Policy"]
    # The data parts are served from the app's origin.
    assert "; connect-src 'self';" in csp
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
    assert {k: second[k] for k in ("vendor", "images", "map", "data")} == {
        k: first[k] for k in ("vendor", "images", "map", "data")
    }
    # Another library: new library and code URLs.
    lib = cfg.root / "web" / "vendor" / "preact-htm.module.js"
    lib.write_text(lib.read_text() + "\n")
    third = versions(build.assemble(cfg, None))
    assert third["vendor"] != second["vendor"]
    assert third["code"] != second["code"]
    assert third["images"] == second["images"]
    # Another map: a new map version; the data's and the strings' the same,
    # so browsers keep the candidates, and the other way round.
    (built / "addr" / "index.json").write_text('{"obce": []}')
    fourth = versions(build.assemble(cfg, None))
    assert fourth["map"] != third["map"]
    assert fourth["data"] == third["data"]
    assert fourth["strings"] == third["strings"]
    data["candidacies"][0]["parties"] = []
    (built / "candidates.json").write_text(json.dumps(data))
    fifth = versions(build.assemble(cfg, None))
    assert fifth["data"] != fourth["data"]
    assert fifth["map"] == fourth["map"]
    # The election's results: copied into their own part; the bundle stays.
    results = cfg.results_dir(cfg.latest)
    results.mkdir(parents=True)
    (results / "status.json").write_text('{"phase": "none"}')
    site = build.assemble(cfg, None)
    assert site.copies["results/2026-10-24"] == results
    assert versions(site)["data"] == fifth["data"]
    assert versions(site)["results"] == "/results/2026-10-24"


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

    deployed = build.Locations(
        {slug: located("map", slug) for slug in ("2026", "2022")},
        {slug: located("data", slug) for slug in ("2026", "2022")},
        "https://results.example.sk",
        "https://sources.example.sk",
    )
    site = build.assemble_deployed(cfg, deployed)
    assert all(t.startswith("app/assets/") for t in site.copies)
    assert {p for p in site.files if not p.startswith("app/")} == {
        "map/2026/manifest.json",
        "map/2022/manifest.json",
        "data/2026/manifest.json",
        "data/2022/manifest.json",
    }
    manifest = json.loads(site.files["map/2022/manifest.json"])
    assert manifest["url"] == "https://0a1b2c3d.ems-map-2022.pages.dev"
    app = app_config(site, "sk/2022/index.html")
    assert app["map"] == "https://0a1b2c3d.ems-map-2022.pages.dev"
    assert app["data"] == "https://0a1b2c3d.ems-data-2022.pages.dev"
    assert app["results"] == "https://results.example.sk/2022-10-29"
    assert app["sources"] == "https://sources.example.sk"
    shell = site.files["app/sk/2022/index.html"].decode()
    assert (
        'href="https://0a1b2c3d.ems-map-2022.pages.dev/geo/index.json?v='
        f'{manifest["version"]}"'
    ) in shell
    # The map's server is connected to as the page loads.
    assert (
        '<link rel="preconnect" href="https://0a1b2c3d.ems-map-2022.pages.dev"'
    ) in shell
    rules = build.header_rules(site.files[f"app/{bundle.HEADERS}"].decode())
    csp = build.response_headers(rules, "/sk/")["Content-Security-Policy"]
    assert (
        "; connect-src 'self' https://0a1b2c3d.ems-data-2022.pages.dev"
        " https://0a1b2c3d.ems-data-2026.pages.dev"
        " https://0a1b2c3d.ems-map-2022.pages.dev"
        " https://0a1b2c3d.ems-map-2026.pages.dev https://results.example.sk;"
    ) in csp
