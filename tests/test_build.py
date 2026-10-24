import dataclasses
import html
import json
import re
import shutil
from pathlib import Path

import pytest

from election_map_slovakia import build, config

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


def project(root: Path) -> config.Config:
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / "web", root / "web")
    built = root / "data" / "build"
    write_geo(built / "geo")
    (built / "addr").mkdir(parents=True)
    (built / "addr" / "index.json").write_text("{}")
    (built / "candidates.json").write_text(json.dumps(DATA, ensure_ascii=False))
    return config.load(root / "config")


def test_every_contest_is_in_exactly_one_area_file():
    files = build.area_files(DATA, {"zsk:1/2": 2})
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
    files = build.area_files(DATA, {})
    everywhere = ["starosta:508063#1", "oz:508063/1#1", "zsk:1/2#1"]
    assert files["data/okres/106.json"]["persons"]["p3"] == everywhere
    assert files["data/kraj/1.json"]["persons"]["p3"] == everywhere
    assert "p4" not in files["data/kraj/1.json"]["persons"]


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
    assert build.regional_past(data, props) == {
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
    files = build.area_files(data, {}, regional={"zsk:1/2": past("osk2022", 500, 110)})
    row = ["oso2022", "2022-10-29", 1000, 400]
    okres = files["data/okres/101.json"]["contests"]
    assert okres["oz:528595/2"]["past"] == [*row, 1]
    assert okres["starosta:528595"]["past"] == row
    assert files["data/okres/106.json"]["contests"]["oz:508063/1"]["past"] == row
    kraj = files["data/kraj/1.json"]["contests"]
    assert kraj["zsk:1/2"]["past"] == ["osk2022", "2022-10-29", 500, 110]
    assert "past" not in kraj["zsk:1/1"]


def test_name_shards_find_a_person_by_each_name_word():
    data = {
        "candidacies": [
            candidacy("starosta:1", 1, "a", first_name="Ján", surname="Ďurica"),
            candidacy("starosta:1", 2, "b", first_name="Matúš", surname="Vӧrӧš"),
        ]
    }
    shards = build.name_shards(data)
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


def test_build_is_deterministic(tmp_path: Path):
    cfg = project(tmp_path / "project")
    first = build.write(build.assemble(cfg), tmp_path / "a")
    second = build.write(build.assemble(cfg), tmp_path / "b")
    assert first == second
    for path in first:
        assert (tmp_path / "a" / path).read_bytes() == (
            tmp_path / "b" / path
        ).read_bytes()
    index = json.loads((tmp_path / "a" / "data" / "index.json").read_bytes())
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
        assert f"{code}/index.html" in first
        assert f"i18n/{code}.json" in first
    pending = json.loads((tmp_path / "a" / "i18n" / "de.json").read_bytes())
    assert pending["_pending"] == pending["_locale"] == "en"
    assert pending["_missing"]["ui"] == len(
        json.loads((REPO / "web/i18n/en.json").read_bytes())
    )


def versions(site: build.Site) -> dict[str, str]:
    """The code, vendor, image and data versions of *site*, and its live URL."""
    shell = site.files["sk/index.html"].decode()
    match = re.search(r'<meta name="km-config" content="([^"]*)"', shell)
    assert match is not None
    app = json.loads(html.unescape(match[1]))
    code = re.search(r'<script type="module" src="/assets/(\w+)/js/app.js">', shell)
    vendor = re.search(r'src="/assets/vendor/(\w+)/leaflet/leaflet.js"', shell)
    assert code is not None and vendor is not None
    [images] = (t.split("/")[2] for t in site.copies if t.startswith("assets/img/"))
    return {
        "code": code[1],
        "vendor": vendor[1],
        "images": images,
        "data": app["dataVersion"],
        "live": app["live"],
    }


def test_versions_and_live_origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(config.LIVE_URL_ENV, "http://127.0.0.1:8766")
    cfg = project(tmp_path / "project")
    # A party with a logo, which data/index.json names under the images.
    data = json.loads((cfg.build_dir / "candidates.json").read_bytes())
    data["candidacies"][0]["parties"] = ["Demokrati"]
    (cfg.build_dir / "candidates.json").write_text(json.dumps(data))
    site = build.assemble(cfg)
    first = versions(site)
    code, vendor = first["code"], first["vendor"]
    assert first["live"] == "http://127.0.0.1:8766"
    shell = site.files["sk/index.html"].decode()
    # The preload is of the very URL the app fetches, or it goes unused.
    assert f'href="/i18n/sk.json?v={first["data"]}"' in shell
    assert f'src="/assets/{code}/js/picker.js"' in site.files["index.html"].decode()
    assert "assets/cache.css" in site.copies
    index = json.loads(site.files["data/index.json"])
    assert index["parties"]["Demokrati"][2] == (
        f"/assets/img/{first['images']}/parties/demokrati.svg"
    )
    # The modules import the libraries from their versioned directory.
    app_js = site.files[f"assets/{code}/js/app.js"].decode()
    assert f"from '/assets/vendor/{vendor}/preact-htm.module.js'" in app_js
    assert "../vendor/" not in app_js
    rules = build.header_rules(site.files[build.HEADERS].decode())
    csp = build.response_headers(rules, "/sk/")["Content-Security-Policy"]
    assert "; connect-src 'self' http://127.0.0.1:8766;" in csp
    immutable = "public, max-age=31536000, immutable"
    cache_control = {
        path: build.response_headers(rules, path)["Cache-Control"]
        for path in (
            f"/assets/{code}/js/app.js",
            f"/assets/vendor/{vendor}/leaflet/leaflet.js",
            f"/assets/img/{first['images']}/parties/demokrati.svg",
            "/assets/cache.css",
            "/geo/x.json",
        )
    }
    assert cache_control == {
        f"/assets/{code}/js/app.js": immutable,
        f"/assets/vendor/{vendor}/leaflet/leaflet.js": immutable,
        f"/assets/img/{first['images']}/parties/demokrati.svg": immutable,
        "/assets/cache.css": "public, max-age=86400",
        "/geo/x.json": "public, max-age=86400",
    }
    # Other code: new code URLs only; the libraries, images and data keep theirs.
    css = cfg.root / "web" / "app.css"
    css.write_text(css.read_text() + "\n/* changed */\n")
    second = versions(build.assemble(cfg))
    assert second["code"] != code
    assert {k: second[k] for k in ("vendor", "images", "data")} == {
        k: first[k] for k in ("vendor", "images", "data")
    }
    # Another library: new library and code URLs.
    lib = cfg.root / "web" / "vendor" / "preact-htm.module.js"
    lib.write_text(lib.read_text() + "\n")
    third = versions(build.assemble(cfg))
    assert third["vendor"] != second["vendor"]
    assert third["code"] != second["code"]
    assert third["images"] == second["images"]
    # Other data: a new data version.
    (cfg.build_dir / "addr" / "index.json").write_text('{"obce": []}')
    assert versions(build.assemble(cfg))["data"] != third["data"]
    monkeypatch.setenv(config.LIVE_URL_ENV, "")
    cfg = config.load(cfg.root / "config")
    site = build.assemble(cfg)
    assert versions(site)["live"] == ""
    csp = build.response_headers(
        build.header_rules(site.files[build.HEADERS].decode()), "/sk/"
    )["Content-Security-Policy"]
    assert "; connect-src 'self';" in csp
