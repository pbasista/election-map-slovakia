import dataclasses
import json
import re
import shutil
from pathlib import Path

import pytest
import shapely

from election_map_slovakia import build, check, config, geo

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


def write_json(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False))


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, config.Config]:
    """A complete site for one obec, built from the real web/ and config/."""
    monkeypatch.delenv(config.LIVE_URL_ENV, raising=False)
    root = tmp_path / "project"
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / "web", root / "web")
    built = root / "data" / "build"
    obec = {"id": "508063", "name": "Jakubov", "okres": "106", "kraj": "1", "zsk": 1}
    for lod in "210":
        write_json(built / f"geo/okres/106/{lod}.json", topology(obec))
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
            "shards": [
                {"lod": "2", "zoom": [9.5, 12]},
                {"lod": "1", "zoom": [12, 14]},
                {"lod": "0", "zoom": [14, None]},
            ],
            "okresy": {"106": [17.0, 48.4, 17.1, 48.5]},
            "neighbours": [
                {"lod": "0", "zoom": [0, None], "extent": [16.9, 48.3, 17.2, 48.6]}
            ],
        },
    )
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
                {"name": "Jakubov", "numbers": ["1"], "points": [1705000, 4845000]}
            ],
        },
    )
    write_json(built / "candidates.json", DATA)
    # Every UI string translated, as the deployed site must have them; the
    # English text stands in for the translations.
    en = json.loads((REPO / "web/i18n/en.json").read_bytes())
    ui = {k: {"src": v, "text": v} for k, v in en.items()}
    for code in ("cs", "hu", "pl", "uk", "de", "rue", "rmc"):
        write_json(root / f"data/curated/translations/{code}.json", {"ui": ui})
    cfg = config.load(root / "config")
    dist = tmp_path / "dist"
    build.write(build.assemble(cfg), dist)
    return dist, cfg


def problems(dist: Path, cfg: config.Config, site: config.Site | None = None) -> dict:
    checks = check.run(dist, site or cfg.site, cfg.languages, CONTESTS)
    return {c.name: c.problems for c in checks if c.problems}


def test_built_site_passes(site):
    # Also guards against false alarms on the real frontend and vendor code.
    assert problems(*site) == {}


def test_untranslated_ui_string(site):
    dist, cfg = site
    strings = json.loads((dist / "i18n/cs.json").read_bytes())
    strings["_missing"] = {"ui": 1, "occupations": 0}
    strings["_pending"] = "en"
    (dist / "i18n/cs.json").write_text(json.dumps(strings))
    assert problems(dist, cfg) == {
        "i18n": ["i18n/cs.json: 1 UI strings untranslated (shown in en)"]
    }


def test_over_budget(site):
    dist, cfg = site
    n = sum(1 for p in dist.rglob("*") if p.is_file())
    small = dataclasses.replace(cfg.site, file_budget=n - 1, max_file_bytes=1000)
    found = problems(dist, cfg, small)
    assert found["files"] == [f"{n:,} files, budget {n - 1:,}"]
    assert any(
        re.match(r"assets/vendor/\w+/leaflet/leaflet\.js:", p) for p in found["sizes"]
    )


def test_broken_json(site):
    dist, cfg = site
    (dist / "data/kraj/1.json").write_text('{"contests": {')
    found = problems(dist, cfg)
    assert [p.split(":")[0] for p in found["json"]] == ["data/kraj/1.json"]
    # Its contests are then in no file the frontend can read.
    assert "predseda:1: in no area file" in found["contests"]


def test_missing_files(site):
    dist, cfg = site
    (dist / "addr/508063.json").unlink()
    (dist / "geo/okres/106/1.json").unlink()
    shutil.rmtree(dist / "uk")
    (dist / "404.html").unlink()
    # Only the modules' rewritten imports name the libraries.
    [qrcode] = dist.glob("assets/vendor/*/qrcode-generator.module.js")
    qrcode.unlink()
    missing = {p.split()[0] for p in problems(dist, cfg)["links"]}
    assert missing == {
        "404.html",
        "addr/508063.json",
        "geo/okres/106/1.json",
        "uk/index.html",
        qrcode.relative_to(dist).as_posix(),
    }


def test_third_party_resource(site):
    dist, cfg = site
    shell = dist / "sk/index.html"
    html = shell.read_text()
    shell.write_text(
        html.replace(
            "</head>",
            '<link rel="stylesheet" href="https://fonts.example.com/a.css" />\n'
            '<a href="https://example.org/about">about</a>\n</head>',
        )
    )
    [css] = dist.glob("assets/*/app.css")
    css.write_text(
        css.read_text() + "\nbody { background: url(//cdn.example.net/x.png); }\n"
    )
    [js] = dist.glob("assets/*/js/data.js")
    js.write_text(js.read_text() + "\nfetch('https://api.example.com/v1');\n")
    found = [p.split(": ", 1)[1] for p in problems(dist, cfg)["origins"]]
    # The plain link is fine; the three fetched resources are not.
    assert found == [
        "//cdn.example.net/x.png",
        "https://api.example.com/v1",
        "https://fonts.example.com/a.css",
    ]


def test_live_origin_only_in_config_and_csp(site):
    dist, cfg = site
    live = cfg.site.live_url
    assert live is not None
    [js] = dist.glob("assets/*/js/data.js")
    js.write_text(js.read_text() + f"\nfetch('{live}/status.json');\n")
    found = problems(dist, cfg)["origins"]
    assert [p.split(": ", 1)[1] for p in found] == [f"{live}/status.json"]
    # A longer host is another origin.
    found = problems(dist, cfg, dataclasses.replace(cfg.site, live_url=live[:-3]))
    assert (
        f"_headers: CSP connect-src is 'self' {live}, expected 'self' {live[:-3]}"
        in (found["origins"])
    )
    assert any(p.startswith("sk/index.html:") for p in found["origins"])


def test_address_outside_its_obec(site):
    dist, cfg = site
    path = dist / "addr/508063.json"
    content = json.loads(path.read_text())
    content["parts"][0]["points"] = [1805000, 4845000]
    path.write_text(json.dumps(content))
    assert len(problems(dist, cfg)["addresses"]) == 1
