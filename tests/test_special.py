"""Special okrsky: polling districts without territory (special.py)."""

import datetime as dt
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from election_map_slovakia import (
    bundle,
    config,
    crosswalk,
    obvody,
    okrsokrules,
    special,
)
from election_map_slovakia.results import UNKNOWN, Live

DOCUMENT = {"url": "https://alfa.sk/u.pdf", "sha256": "0" * 64, "title": "U"}
UNITS = config.Units("volbysr", "results-ref", "tab0b", "tab0c")
COVID = ("https://volby.example/specialne.html", "Špeciálne volebné okrsky")
DIVISION = """\
Kód kraja;Kód okresu;Názov okresu;Kód obce;Názov obce;Počet okrskov
1;101;Bratislava I;528595;Bratislava - Staré Mesto;35
1;102;Bratislava II;529320;Bratislava - Ružinov;71
1;102;Bratislava II;529338;Bratislava - Vrakuňa;13
2;201;Alfa;500001;Alfa;12
2;201;Alfa;500002;Beta;3
2;202;Gama;500003;Gama;9
2;202;Gama;500004;Delta;1
"""
DECLARED = """\
Kód okresu;Názov okresu;Konanie hlasovania
101;Bratislava I;Áno
102;Bratislava II;Áno
201;Alfa;Áno
202;Gama;Nie
"""
COUNTS = {
    "528595": 35,
    "529320": 71,
    "529338": 13,
    "500001": 12,
    "500002": 3,
    "500003": 9,
    "500004": 1,
}


def package(tmp_path: Path) -> Path:
    """Write a package with a territorial division and its special okrsky."""
    path = tmp_path / "REF_SK.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("REF_SK_tab0b.csv", DIVISION.encode("cp1250"))
        z.writestr("REF_SK_tab0c.csv", DECLARED.encode("cp1250"))
    return path


SEAT = config.Seat("102", "529320", "https://ruzinov.example/u.pdf", "Určenie", "71st")
PRISON = config.Prison(
    "500002", 3, "ÚVTOS Beta", "https://beta.example/u.pdf", "Určenie"
)


def test_package_declares_covid_okrsky_at_each_okres_seat(tmp_path):
    """The seat of an okres is its obec of its name, its only obec, or the
    curated seat; each takes its seat's highest number, voted or not, and
    every one counts out of the territorial okrsky."""
    curated = config.CuratedSpecial(COVID, (SEAT,), (PRISON,))
    found = special.read(package(tmp_path), UNITS, curated, COUNTS, "special.toml")
    assert {o: list(k) for o, k in found.items()} == {
        "500001": [12],
        "500002": [3],
        "500003": [9],
        "528595": [35],
        "529320": [71],
    }
    assert found["500001"][12].okresy == (("Alfa", True),)
    # Not held: still counted by the territorial division, without results.
    assert found["500003"][9].okresy == (("Gama", False),)
    assert found["500002"][3].kind == special.PRISON
    assert special.territorial(COUNTS, found) == COUNTS | {
        "500001": 11,
        "500002": 2,
        "500003": 8,
        "528595": 34,
        "529320": 70,
    }
    assert special.keys(found) >= {"500001/12", "529320/71"}


def test_seats_not_told_need_a_source(tmp_path):
    with pytest.raises(config.ConfigError, match="okres 102 Bratislava II"):
        special.read(
            package(tmp_path),
            UNITS,
            config.CuratedSpecial(COVID, (), ()),
            COUNTS,
            "special.toml",
        )
    lowest = config.Prison("500002", 1, "ÚVTOS Beta", "https://beta.example/", "U")
    with pytest.raises(config.ConfigError, match="highest-numbered"):
        special.read(
            None, None, config.CuratedSpecial(None, (), (lowest,)), COUNTS, "s"
        )


def okrsky(*numbers: int) -> obvody.RuleSet:
    rules: dict[str, Any] = {str(numbers[0]): {"rules": [{"street": "Hlavná"}]}}
    rules |= {str(n): {"rules": [{"street": f"Ulica {n}"}]} for n in numbers[1:-1]}
    rules[str(numbers[-1])] = {"rules": [{"rest": True}]}
    data = {"obec": "500001", "name": "Alfa", "document": [DOCUMENT], "okrsok": rules}
    return obvody.okrsky_set(data, "test")


def test_ingest_counts_the_territorial_okrsky_alone():
    """A document numbers its own okrsky; the special one, counted after
    them, need not be in it, but every territorial one must."""
    cfg = config.load()
    e = cfg.election("2023-referendum")
    what = "the COVID-19 special okrsok of okres Alfa"
    item = {
        "id": "500001",
        "okrsky": 3,
        "special": [{"number": 4, "kind": "covid", "what": what}],
    }
    assert okrsokrules._count_problems(cfg, e, item, okrsky(1, 2, 3))[1] == []
    assert okrsokrules._count_problems(cfg, e, item, okrsky(1, 2))[1] == [
        f"2 okrsky given, the territorial division has 3 besides its special"
        f" okrsky 4, {what}"
    ]
    assert okrsokrules._count_problems(cfg, e, item, okrsky(1, 2, 3, 4))[1]


def live(okrsky: dict[str, list[Any]]) -> Live:
    return cast(
        Live, SimpleNamespace(okrsky={"okrsky/okres/201": {"referendum:SK/1": okrsky}})
    )


def test_index_names_the_special_okrsky_that_voted_and_keeps_totals():
    specials = {
        "500001": {
            3: special.Special("covid", *COVID, (("Alfa", True),)),
        },
        "500003": {9: special.Special("covid", *COVID, (("Gama", False),))},
    }
    figures = {
        "500001/1": [900, 450, 440, {}],
        "500001/2": [800, 400, 390, {}],
        "500001/3": [2, 2, 2, {}],
        "500003/1": [700, 300, 290, {}],
    }
    results = live(figures)
    index = bundle.special_okrsky(specials, results)
    assert index == {
        "500001": {
            "3": {
                "kind": "covid",
                "voters": 2,
                "title": COVID[1],
                "url": COVID[0],
                "okresy": ["Alfa"],
            }
        }
    }
    # The figures stay as they are: the obec's totals keep the okrsok.
    assert results.okrsky["okrsky/okres/201"]["referendum:SK/1"] == figures
    # Never drawn, it makes no obec one of several okrsky.
    assert bundle.several_okrsky(results, special.keys(specials)) == {"500001"}
    one = live({"500001/1": [900, 450, 440, {}], "500001/3": [2, 2, 2, {}]})
    assert bundle.several_okrsky(one, special.keys(specials)) == set()
    # A special okrsok that voted needs results.
    with pytest.raises(bundle.BuildError, match="1 voted"):
        bundle.special_okrsky(specials, live({"500001/1": [900, 450, 440, {}]}))


def test_several_okrsky_counts_a_regional_only_election():
    """A regional-only election has no mayor's or country-wide contest: its
    kraj president's covers each obec whole and counts; the council's,
    split into obvody, do not."""
    figures = {"500001/1": [900, 450, 440, {}], "500001/2": [800, 400, 390, {}]}
    regional = cast(
        Live,
        SimpleNamespace(
            okrsky={
                "okrsky/kraj/2": {
                    "predseda:2": figures,
                    "zsk:2/1": {"500003/1": [700, 300, 290, {}]},
                    "zsk:2/2": {"500003/2": [600, 300, 290, {}]},
                }
            }
        ),
    )
    assert bundle.several_okrsky(regional) == {"500001"}


def test_crosswalk_never_matches_a_special_okrsok():
    """Okrsok 3 now is special, okrsok 3 then an ordinary one: neither is
    matched, the others still by number."""
    walk = crosswalk.build(
        {"500001": {1: 100, 2: 100}},
        {"500001": {1: 100, 2: 100}},
        {},
        dt.date(2022, 10, 29),
        {"500001": [3]},
    )
    okrsky = walk.obce["500001"].okrsky
    assert okrsky[3] == (UNKNOWN, {})
    assert okrsky[1] == (crosswalk.IDENTITY, {1: 1.0})
    assert all(3 not in sources for _, sources in okrsky.values())
