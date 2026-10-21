import dataclasses
import json
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
