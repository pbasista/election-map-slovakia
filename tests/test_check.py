import dataclasses
import datetime as dt
import json
import re
import shutil
from pathlib import Path

import numpy as np
import pytest
import shapely

from election_map_slovakia import basemap, build, bundle, check, config, geo, results

REPO = Path(__file__).resolve().parent.parent

# Jakubov (okres Malacky) as a square of 0.1°, one address inside it: one
# arc, the country border, around it.
SQUARE = [1_700_000, 4_840_000, 10_000, 0, 0, 10_000, -10_000, 0, 0, -10_000]
CONTESTS = ["starosta:508063", "oz:508063/1", "predseda:1", "zsk:1/1"]
DATA = {
    "kraje": [{"code": "1", "name": "Bratislavský"}],
    "okresy": [{"code": "106", "name": "Malacky", "kraj": "1"}],
    "obce": [{"code": "508063", "name": "Jakubov", "okres": "106", "kraj": "1"}],
    "contests": [
        {"id": c, "kind": c.split(":")[0], "area": c.split(":")[1].split("/")[0]}
        | ({"obvod": int(c.split("/")[1])} if "/" in c else {})
        for c in CONTESTS
    ],
    "candidacies": [
        {
            "id": "starosta:508063#1",
            "contest": "starosta:508063",
            "number": 1,
            "person": "p1",
            "title_before": "",
            "title_after": "",
            "first_name": "Ján",
            "surname": "Novák",
            "age": 40,
            "occupation": "učiteľ",
            "parties": [],
            "independent": True,
        }
    ],
    "persons": [],
}


def topology(properties: dict) -> dict:
    return {
        "scale": 100_000,
        "arcs": [SQUARE],
        "lines": [geo.COUNTRY | geo.ZSK],
        "features": [{"properties": properties, "arcs": [[[0]]]}],
    }


def neighbours() -> dict:
    """Austria all around Jakubov, at 1/1000 degree, its hole Jakubov's square."""
    around = shapely.orient_polygons(
        shapely.Polygon(
            [(16_900, 48_300), (17_200, 48_300), (17_200, 48_600), (16_900, 48_600)],
            [[(17_000, 48_400), (17_100, 48_400), (17_100, 48_500), (17_000, 48_500)]],
        )
    )
    topo = geo.topology([geo.rings(around)], 1000)
    return geo.topology_file(topo, 1000, [0], [{"id": "AT"}], geo.neighbour_code)


def okrsky(numbers: tuple[int, ...] = (1, 2)) -> dict:
    """Jakubov's okrsky *numbers*: 1 its western half, 2 the eastern."""
    halves = {
        n: shapely.box(
            1_700_000 + 5_000 * (n - 1),
            4_840_000,
            1_705_000 + 5_000 * (n - 1),
            4_850_000,
        )
        for n in numbers
    }
    g = shapely.orient_polygons(np.array(list(halves.values())))
    properties = [
        {"obec": "508063", "okrsok": n, "obvod": 1, "label": [17.0 + 0.05 * n, 48.45]}
        for n in halves
    ]
    topo = geo.topology([geo.rings(x) for x in g], 100_000)
    return geo.topology_file(
        topo, 100_000, range(len(halves)), properties, geo.okrsok_code
    )


def base_map() -> dict:
    """A motorway across Jakubov and a pond in it."""
    return {
        "scale": 100_000,
        "arcs": [
            [1_700_000, 4_845_000, 10_000, 0],
            [1_702_000, 4_842_000, 1_000, 0, 0, 1_000, -1_000, 0],
        ],
        "lines": [basemap.MOTORWAY, basemap.WATER],
        "features": [{"properties": {}, "arcs": [[[1]]]}],
    }


SHARD_BANDS = [
    {"lod": "2", "zoom": [9.5, 12]},
    {"lod": "1", "zoom": [12, 14]},
    {"lod": "0", "zoom": [14, None]},
]


def write_json(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False))


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, config.Config]:
    """A complete site for one obec, built from the real web/ and config/."""
    monkeypatch.delenv(config.RESULTS_ANYTIME_ENV, raising=False)
    root = tmp_path / "project"
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / "web", root / "web")
    # A site of the latest election alone.
    for name, start in (
        ("elections.toml", "\n# Without incumbents"),
        ("overrides.toml", "\n[election.2022]"),
    ):
        path = root / "config" / name
        text = path.read_text(encoding="utf-8")
        path.write_text(text[: text.index(start)], encoding="utf-8")
    # Its parties' logos of 2022 with it.
    parties = root / "config" / "parties.toml"
    parties.write_text(
        re.sub(
            r'\[party\."[^\n]*"\.logo\.2022\]\n(?:[a-z]+ = [^\n]*\n)*',
            "",
            parties.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )
    cfg = config.load(root / "config")
    built = cfg.election_build_dir(cfg.latest)
    obec = {"id": "508063", "name": "Jakubov", "okres": "106", "kraj": "1", "zsk": 1}
    for lod in "210":
        write_json(built / f"geo/okres/106/{lod}.json", topology(obec))
        write_json(built / f"geo/okrsky/106/{lod}.json", okrsky())
    write_json(
        built / "geo/coarse.json",
        topology({"kraj": "1", "okres": "106", "zsk": 1})
        | {
            "land": [[[0]]],
            "kraje": [],
            "okresy": [],
            "obvody": [{"id": "zsk:1/1", "seats": 5, "label": [17.05, 48.45]}],
        },
    )
    write_json(built / "geo/neighbours/0.json", neighbours())
    write_json(
        built / "geo/index.json",
        {
            "shards": SHARD_BANDS,
            "okresy": {"106": [17.0, 48.4, 17.1, 48.5]},
            "neighbours": [
                {"lod": "0", "zoom": [0, None], "extent": [16.9, 48.3, 17.2, 48.6]}
            ],
            "okrsky": {
                "bands": SHARD_BANDS,
                "okresy": {"106": [17.0, 48.4, 17.1, 48.5]},
                "drawn": {"508063": [1, 2]},
            },
        },
    )
    base = {basemap.okres_path("106", lod): base_map() for lod in "210"}
    base[basemap.COARSE_FILE] = base_map()
    base[basemap.buildings_path("508063")] = {
        "scale": basemap.BUILDINGS_SCALE,
        "counts": [3],
        "xy": [1705000, 4845000, 4, 0, 0, 3],
    }
    base[basemap.INDEX_FILE] = {
        "bands": SHARD_BANDS,
        "okresy": ["106"],
        "buildings": {"zoom": basemap.BUILDINGS_ZOOM, "obce": ["508063"]},
    }
    basemap.write(base, built / basemap.OUTPUT_DIR)
    write_json(
        built / "addr/index.json", {"obce": [["508063", "Jakubov", "106", "jakubov"]]}
    )
    write_json(
        built / "addr/508063.json",
        {
            "council": "single",
            "obvod": 1,
            "streets": [],
            "parts": [
                {
                    "name": "Jakubov",
                    "numbers": ["1"],
                    "points": [1705000, 4845000],
                    "okrsok": 2,
                }
            ],
        },
    )
    write_json(built / "candidates.json", DATA)
    (built / bundle.LINKS_DIR).mkdir()
    # Every UI string translated, as the deployed site must have them; the
    # English text stands in for the translations.
    en = json.loads((REPO / "web/i18n/en.json").read_bytes())
    ui = {k: {"src": v, "text": v} for k, v in en.items()}
    for code in ("cs", "hu", "pl", "uk", "de", "rue", "rmc"):
        write_json(root / f"data/curated/translations/{code}.json", {"ui": ui})
    cfg = config.load(root / "config")
    # The final results of Jakubov's mayor.
    final = results.Live("final")
    final.add(
        "okres/106",
        "starosta:508063",
        results.Record("final", (1, 1), 500, 200, 195, 1, 1, [(1, 195, 1)]),
    )
    results.write(
        cfg.results_dir(cfg.latest), final, dt.datetime(2026, 10, 25, tzinfo=dt.UTC)
    )
    dist = tmp_path / "dist"
    build.write(build.assemble(cfg, None), dist)
    return dist, cfg


def problems(dist: Path, cfg: config.Config, site: config.Site | None = None) -> dict:
    if site is not None:
        cfg = dataclasses.replace(cfg, site=site)
    checks = check.run(dist, cfg, {cfg.latest.slug: CONTESTS})
    return {c.name: c.problems for c in checks if c.problems}


def test_built_site_passes(site):
    # Also guards against false alarms on the real frontend and vendor code.
    assert problems(*site) == {}


def test_untranslated_ui_string(site):
    dist, cfg = site
    strings = json.loads((dist / "app/i18n/cs.json").read_bytes())
    strings["_missing"] = 1
    strings["_pending"] = "en"
    (dist / "app/i18n/cs.json").write_text(json.dumps(strings))
    assert problems(dist, cfg) == {
        "i18n": ["app/i18n/cs.json: 1 UI strings untranslated (shown in en)"]
    }


def test_over_budget(site):
    """Each part is a Pages project of its own: the budget is per part."""
    dist, cfg = site
    n = sum(1 for p in (dist / "app").rglob("*") if p.is_file())
    assert n > sum(1 for p in (dist / "data/2026").rglob("*") if p.is_file())
    small = dataclasses.replace(cfg.site, file_budget=n - 1, max_file_bytes=1000)
    found = problems(dist, cfg, small)
    assert found["files"] == [f"app/: {n:,} files, budget {n - 1:,}"]
    assert any(
        re.match(r"app/assets/vendor/\w+/leaflet/leaflet\.js:", p)
        for p in found["sizes"]
    )


def test_broken_json(site):
    dist, cfg = site
    (dist / "data/2026/data/kraj/1.json").write_text('{"contests": {')
    found = problems(dist, cfg)
    assert [p.split(":")[0] for p in found["json"]] == ["data/2026/data/kraj/1.json"]
    # Its contests are then in no file the frontend can read.
    assert "data/2026 predseda:1: in no area file" in found["contests"]


def test_missing_files(site):
    dist, cfg = site
    (dist / "map/2026/addr/508063.json").unlink()
    (dist / "map/2026/geo/okres/106/1.json").unlink()
    (dist / "data/2026/i18n/de.json").unlink()
    shutil.rmtree(dist / "app/uk")
    (dist / "app/404.html").unlink()
    # Only the modules' rewritten imports name the libraries.
    [qrcode] = dist.glob("app/assets/vendor/*/qrcode-generator.module.js")
    qrcode.unlink()
    missing = {p.split()[0] for p in problems(dist, cfg)["links"]}
    assert missing == {
        "app/404.html",
        "map/2026/addr/508063.json",
        "map/2026/geo/okres/106/1.json",
        "data/2026/i18n/de.json",
        "app/uk/index.html",
        "app/uk/2026/index.html",
        qrcode.relative_to(dist).as_posix(),
    }


def test_a_bundle_lists_its_files(site):
    dist, cfg = site
    (dist / "data/2026/data/stray.json").write_text("{}")
    (dist / "map/2026/geo/stray.json").write_text("{}")
    (dist / "sources/404.html").unlink()
    assert problems(dist, cfg)["headers"] == [
        "data/2026/manifest.json: lists not exactly the bundle's files",
        "map/2026/manifest.json: lists not exactly the bundle's files",
        "sources/404.html missing",
    ]


def test_the_app_for_deployed_bundles(site, tmp_path: Path):
    """An app built for deployed bundles is checked against their manifests."""
    dist, cfg = site
    manifest = json.loads((dist / "data/2026/manifest.json").read_bytes())
    manifest["files"].remove("data/about.json")
    map_manifest = json.loads((dist / "map/2026/manifest.json").read_bytes())
    map_manifest["files"].remove("geo/coarse.json")
    locations = build.Locations(
        {"2026": build.Located("https://0a1b.ems-map-2026.pages.dev", map_manifest)},
        {"2026": build.Located("https://0a1b.ems-data-2026.pages.dev", manifest)},
        cfg.site.results_url,
        cfg.site.sources_url,
    )
    deployed = tmp_path / "deployed"
    build.write(build.assemble_deployed(cfg, locations), deployed)
    found = problems(deployed, cfg)
    # Its shells name the data parts' origins, which the CSP lets it
    # fetch from; the bundles' own checks passed where they were built.
    assert list(found) == ["links"]
    assert [re.sub(r"assets/\w+/", "assets/<v>/", p) for p in found["links"]] == [
        "data/2026/data/about.json missing (needed by app/assets/<v>/js/about.js)",
        "map/2026/geo/coarse.json missing (needed by app/assets/<v>/js/map.js)",
    ]


def test_third_party_resource(site):
    dist, cfg = site
    shell = dist / "app/sk/index.html"
    html = shell.read_text()
    shell.write_text(
        html.replace(
            "</head>",
            '<link rel="stylesheet" href="https://fonts.example.com/a.css" />\n'
            '<a href="https://example.org/about">about</a>\n</head>',
        )
    )
    [css] = dist.glob("app/assets/*/app.css")
    css.write_text(
        css.read_text() + "\nbody { background: url(//cdn.example.net/x.png); }\n"
    )
    [js] = dist.glob("app/assets/*/js/data.js")
    js.write_text(js.read_text() + "\nfetch('https://api.example.com/v1');\n")
    found = [p.split(": ", 1)[1] for p in problems(dist, cfg)["origins"]]
    # The plain link is fine; the three fetched resources are not.
    assert found == [
        "//cdn.example.net/x.png",
        "https://api.example.com/v1",
        "https://fonts.example.com/a.css",
    ]


def test_connect_src_only_the_data_parts(site):
    dist, cfg = site
    headers = dist / "app" / bundle.HEADERS
    headers.write_text(
        headers.read_text().replace(
            "connect-src 'self';", "connect-src 'self' https://live.example.sk;"
        )
    )
    assert problems(dist, cfg)["origins"] == [
        "app/_headers: CSP connect-src is 'self' https://live.example.sk,"
        " expected 'self'"
    ]


def test_results(site):
    dist, cfg = site
    day = dist / "results/2026-10-24"
    area = day / "okres/106.json"
    area.write_text(area.read_text().replace('"final"', '"partial"', 1))
    (day / "okres/107.json").write_text("{}")
    shutil.copytree(day, dist / "results/latest")
    found = problems(dist, cfg)["results"]
    assert found == [
        "results/2026-10-24/okres/107.json is not in status.json",
        "results/2026-10-24/okres/106: hash differs from status.json",
        "results/latest: not an election day (YYYY-MM-DD)",
    ]


def test_address_outside_its_obec(site):
    dist, cfg = site
    path = dist / "map/2026/addr/508063.json"
    content = json.loads(path.read_text())
    content["parts"][0]["points"] = [1805000, 4845000]
    path.write_text(json.dumps(content))
    assert len(problems(dist, cfg)["addresses"]) == 1


def test_okrsok_missing_from_the_map_and_from_an_address(site):
    dist, cfg = site
    write_json(dist / "map/2026/geo/okrsky/106/1.json", okrsky((1,)))
    path = dist / "map/2026/addr/508063.json"
    content = json.loads(path.read_text())
    del content["parts"][0]["okrsok"]
    path.write_text(json.dumps(content))
    found = problems(dist, cfg)
    assert [p.split(": ", 1)[1] for p in found["geometry"]] == [
        "obec 508063: okrsky [1] drawn, the index says [1, 2]",
        "obec 508063: the okrsky overlap by 0.0 m² and lie 1130.46 m off the obec"
        " on average",
    ]
    assert found["addresses"] == [
        "map/2026/addr/508063.json: Jakubov: okrsky missing, but the map draws them"
    ]


def test_base_map(site):
    dist, cfg = site
    base = dist / "map/2026/base"
    (base / "okres/106/1.json").unlink()
    stray = base / "okres/108/0.json"
    stray.parent.mkdir()
    stray.write_bytes((base / "okres/106/0.json").read_bytes())
    index = json.loads((base / "index.json").read_bytes())
    index["okresy"].append("107")
    (base / "index.json").write_text(json.dumps(index))
    buildings = base / "obec/508063.json"
    buildings.write_text(buildings.read_text().replace("100000", "100001"))
    found = problems(dist, cfg)
    by = "map/2026/base/index.json"
    assert found["links"] == [
        f"map/2026/base/okres/106/1.json missing (needed by {by})",
        *(
            f"map/2026/base/okres/107/{lod}.json missing (needed by {by})"
            for lod in "012"
        ),
    ]
    assert found["base"] == [
        f"{by}: okresy differ from the geo shards'",
        f"{by}: 1 files in map/2026/base/ the app never requests,"
        " such as map/2026/base/okres/108/0.json",
        "map/2026/base/obec/508063.json: scale 100001, not 100000",
    ]
