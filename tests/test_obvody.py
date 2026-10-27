import datetime as dt
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from election_map_slovakia import config, obvodrules, obvody, okrsokrules
from election_map_slovakia.candidates import Obec
from election_map_slovakia.config import Obvod, ObvodList

ELECTION = config.load(Path(__file__).resolve().parent.parent / "config").election_dir
CURATED = ELECTION / obvody.DIRECTORY

AREA = {
    o.code: o
    for o in (
        Obec("500001", "Alfa", "101", "1"),
        Obec("500002", "Beta", "101", "1"),
        Obec("500003", "Gama", "102", "1"),
        Obec("500004", "Delta", "102", "1"),
    )
}


def listing(*obvody: Obvod) -> ObvodList:
    return ObvodList(
        Path("zsk-1.toml"), "https://example.sk/", dt.date(2026, 7, 1), obvody
    )


def ob(number: int, okresy: tuple[str, ...] = (), obce: tuple[str, ...] = ()) -> Obvod:
    return Obvod(number, 1, okresy, obce)


def test_okres_expands_to_its_obce():
    members = obvody.resolve(
        listing(ob(1, ("101",)), ob(2, obce=("500004", "500003"))), AREA, 2
    )
    assert members == {1: ("500001", "500002"), 2: ("500004", "500003")}


def test_obec_in_two_obvody():
    with pytest.raises(
        obvody.ObvodyError, match=r"500002 \(Beta\) is listed in obvod 1 and 2"
    ):
        obvody.resolve(listing(ob(1, ("101",)), ob(2, ("102",), ("500002",))), AREA, 2)


def test_missing_obec():
    with pytest.raises(obvody.ObvodyError, match=r"500003 \(Gama\) is in no obvod"):
        obvody.resolve(listing(ob(1, ("101",)), ob(2, obce=("500004",))), AREA, 2)


def test_wrong_obvod_count():
    with pytest.raises(
        obvody.ObvodyError, match="2 obvody, but the candidate lists have 3"
    ):
        obvody.resolve(listing(ob(1, ("101",)), ob(2, ("102",))), AREA, 3)


def test_member_outside_area():
    with pytest.raises(obvody.ObvodyError) as e:
        obvody.resolve(
            listing(ob(1, ("101", "103")), ob(2, ("102",), ("600001",))),
            AREA,
            2,
        )
    assert "obvod 1: okres 103 is not in the area" in str(e.value)
    assert "obvod 2: obec 600001 is not in the area" in str(e.value)


def write_toml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "BA.toml"
    path.write_text(
        f'source = "https://example.sk/"\ndate = 2026-07-01\n{body}', encoding="utf-8"
    )
    return path


def test_numbering_gap_rejected(tmp_path: Path):
    path = write_toml(
        tmp_path,
        '[obvod.1]\nseats = 2\nobce = ["500001"]\n[obvod.3]\nseats = 1\nobce = ["500002"]\n',
    )
    with pytest.raises(
        config.ConfigError, match=r"BA\.toml: obvod: must be numbered 1\.\.2"
    ):
        config.load_obvody(path)


@pytest.mark.parametrize(
    ("seats", "message"),
    [
        ("", "obvod.1.seats: missing"),
        ("seats = 0\n", "obvod.1.seats: must be a positive"),
    ],
)
def test_seats_required_and_positive(tmp_path: Path, seats: str, message: str):
    path = write_toml(tmp_path, f'[obvod.1]\n{seats}obce = ["500001"]\n')
    with pytest.raises(config.ConfigError, match=message):
        config.load_obvody(path)


def test_repository_files_are_well_formed():
    files = sorted(CURATED.glob("*.toml"))
    assert {f.stem for f in files} == {"BA", "KE", *(f"zsk-{k}" for k in range(1, 9))}
    for f in files:
        config.load_obvody(f)
    rule_sets = obvody.load_rule_sets(CURATED.parent)
    for path in sorted((CURATED / obvody.RULES_DIRECTORY).glob("*.toml")):
        assert rule_sets[path.stem].obec == path.stem
    okrsok_sets = obvody.okrsok_rule_sets(ELECTION)
    for path in sorted((ELECTION / obvody.OKRSKY_DIRECTORY).glob("*.toml")):
        assert okrsok_sets[path.stem].whole


# --- rule sets -----------------------------------------------------------

DOCUMENT = {"url": "https://obec.sk/u.pdf", "sha256": "0" * 64, "title": "Uznesenie"}


def rule_set(*obvody_rules: list[dict], fill: bool = False) -> obvody.RuleSet:
    data = {
        "obec": "500001",
        "name": "Alfa",
        "date": dt.date(2026, 6, 1),
        "document": [DOCUMENT],
        "obvod": {
            str(n): {"seats": 3, "rules": rules}
            for n, rules in enumerate(obvody_rules, 1)
        },
    }
    if fill:
        data["fill"] = "nearest"
    return obvody.rule_set(data, "test")


def place(street: str, number: str, part: str = "Alfa") -> obvody.Place:
    supisne, _, orientacne = number.partition("/")
    return obvody.Place(street, part, supisne, orientacne)


def obvody_of(rules: obvody.RuleSet, places: list[obvody.Place]) -> list[int]:
    return obvody.assign(rules, places).units


def test_orientacne_ranges_with_letters_and_open_end():
    rules = rule_set(
        [{"street": "Hlavná", "numbers": "1-10, 15"}],
        [{"street": "Hlavná", "numbers": "11-14, 16-"}],
    )
    places = [
        place("Hlavná", "500/1"),
        place("Hlavná", "501/10B"),
        place("Hlavná", "502/11"),
        place("Hlavná", "503/15A"),
        place("Hlavná", "504/120"),
    ]
    assert obvody_of(rules, places) == [1, 1, 2, 1, 2]


def test_odd_and_even_sides_of_a_street():
    rules = rule_set(
        [{"street": "Nitrianska", "parity": "odd"}],
        [{"street": "Nitrianska", "numbers": "2-40", "parity": "even"}],
        [{"street": "Nitrianska", "numbers": "42-", "parity": "even"}],
    )
    places = [place("Nitrianska", f"9{n}/{n}") for n in ("7", "8", "40", "41", "42")]
    assert obvody_of(rules, places) == [1, 2, 2, 1, 3]


def test_letter_beats_range_and_numbers_beat_whole_street():
    rules = rule_set(
        [{"street": "Lipová"}, {"street": "Lipová", "numbers": "5A"}],
        [{"street": "Lipová", "numbers": "1-9"}],
    )
    places = [place("Lipová", "1/5"), place("Lipová", "2/5A"), place("Lipová", "3/12")]
    assert obvody_of(rules, places) == [2, 1, 1]


def test_supisne_count_where_there_is_no_street():
    rules = rule_set(
        [{"part": "Dolná Ves", "numbers": "1-200"}],
        [{"part": "Dolná Ves", "numbers": "201-"}, {"street": "Školská"}],
    )
    places = [
        place("", "12", "Dolná Ves"),
        place("", "350", "Dolná Ves"),
        # Numbers beat a whole street, and a part's numbers are súpisné.
        place("Školská", "150/2", "Dolná Ves"),
    ]
    assert obvody_of(rules, places) == [1, 2, 1]


def test_by_supisne_in_a_street_and_house_without_that_number():
    rules = rule_set(
        [{"street": "Poľná", "numbers": "1-99", "by": "supisne"}],
        [{"rest": True}],
    )
    places = [place("Poľná", "50/7"), place("Poľná", "150/7"), place("Poľná", "/7")]
    assert obvody_of(rules, places) == [1, 2, 2]


def test_except_and_names_compared_like_the_search():
    rules = rule_set(
        [{"street": "NÁMESTIE SNP", "except": "3, 5"}],
        [{"street": "Námestie SNP", "numbers": "3, 5"}],
    )
    places = [place("Námestie  SNP", "1/1"), place("Nám. SNP", "1/3")]
    assert obvody_of(rules, places)[0] == 1
    # "Nám. SNP" is no register name: the rules name streets as the register.
    assert obvody.assign(rules, places).unassigned == [1]


def test_part_rest_and_street_within_part():
    rules = rule_set(
        [{"part": "Horná"}, {"street": "Hlavná", "part": "Dolná"}],
        [{"rest": True}],
    )
    places = [
        place("Hlavná", "1/1", "Horná"),
        place("Hlavná", "2/1", "Dolná"),
        place("Krátka", "3/1", "Dolná"),
    ]
    assert obvody_of(rules, places) == [1, 1, 2]


def test_conflicts_unassigned_and_unused_reported():
    rules = rule_set(
        [{"street": "Hlavná", "numbers": "1-10"}, {"street": "Zelená"}],
        [{"street": "Hlavná", "numbers": "10-20"}],
    )
    places = [place("Hlavná", "1/10"), place("Hlavná", "1/30"), place("Hlavná", "2/5")]
    a = obvody.assign(rules, places)
    assert a.units == [0, 0, 1]
    assert list(a.conflicts) == [0] and a.unassigned == [1]
    assert [r.street for r in a.unused] == ["Zelená"]
    problems = a.problems(places)
    assert problems[0].startswith("1 addresses in no obvod, in Hlavná (1)")
    assert "selected for two obvody" in problems[1]


def test_ku_rules_by_point():
    rules = rule_set([{"ku": "Alfa"}], [{"ku": "Beta"}])
    assert rules.by_ku
    places = [place("", "1"), place("", "2"), place("", "3")]
    a = obvody.assign(rules, places, kus=["Alfa", "Beta", None])
    assert a.units == [1, 2, 0]


def test_fill_from_nearest_then_street_then_part():
    rules = rule_set([{"street": "Hlavná"}], [{"street": "Horná"}], fill=True)
    places = [
        place("Hlavná", "1/1"),
        place("Horná", "2/1"),
        place("Nová", "3/1"),
        place("Horná", "4/9"),
        place("", "5", "Alfa"),
        place("Iná", "6/1", "Beta"),
    ]
    nan = float("nan")
    points = np.array([[0, 0], [100, 0], [90, 5], [nan, nan], [nan, nan], [nan, nan]])
    a = obvody.assign(rules, places, points=points)
    assert a.units == [1, 2, 2, 2, 2, 0]
    assert a.filled == [2, 4] and a.unassigned == [5]


def test_near_points_split_a_part_in_an_estimated_rule_set():
    data = {
        "obec": "500001",
        "name": "Alfa",
        "document": [DOCUMENT],
        "note": "the lower and upper end, by guess",
        "estimated": True,
        "obvod": {
            "1": {"seats": 3, "rules": [{"near": [18.0, 49.0], "part": "Alfa"}]},
            "2": {"seats": 4, "rules": [{"near": [18.1, 49.0], "part": "Alfa"}]},
            "3": {"seats": 2, "rules": [{"part": "Beta"}]},
        },
    }
    rules = obvody.rule_set(data, "test")
    places = [place("", "1"), place("", "2"), place("", "3", "Beta"), place("", "4")]
    nan = float("nan")
    points = obvody.ObecPlaces(
        places,
        np.array([[18.02, 49.01], [18.09, 49.0], [18.01, 49.0], [nan, nan]])
        * obvody.POINT_SCALE,
        [None] * 4,
        [],
    ).planar()
    a = obvody.assign(rules, places, points=points)
    # Beta is its part's, wherever its point; without a point, none.
    assert a.units == [1, 2, 3, 0]
    with pytest.raises(obvody.ObvodyError, match="only for an estimated"):
        obvody.rule_set({**data, "estimated": False}, "test")
    with pytest.raises(obvody.ObvodyError, match="needs a note"):
        obvody.rule_set({k: v for k, v in data.items() if k != "note"}, "test")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("1-", None),
        ("12A, 3 – 9", None),
        ("9-3", "runs backwards"),
        ("1A-5", "a range takes no letter"),
        ("č. 5", "is not a number"),
    ],
)
def test_number_syntax(text: str, message: str | None):
    if message is None:
        obvody.parse_numbers(text)
    else:
        with pytest.raises(ValueError, match=message):
            obvody.parse_numbers(text)


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ({"rest": True, "street": "Hlavná"}, "rest = true takes no"),
        ({"parity": "odd"}, "selects nothing"),
        ({"street": "Hlavná", "inferred": True}, "needs a note"),
        ({"part": "Horná", "written": "x"}, "written is for street rules"),
    ],
)
def test_rule_form(rule: dict, message: str):
    with pytest.raises(obvody.ObvodyError, match=message):
        rule_set([rule])


@pytest.mark.parametrize(
    ("written", "name", "same"),
    [
        ("M. R. Štefánika", "Milana Rastislava Štefánika", True),
        ("gen. Svobodu", "Generála Svobodu", True),
        ("Hollého", "Jána Hollého", True),
        ("Ulica Alfonza Šilhára", "Alfonza Šilhára", True),
        ("Štefánikova trieda", "Štefánikova", False),
        ("SNP", "Slovenského národného povstania", False),
        ("Hlavné nám.", "Hlavné námestie", True),
        ("Trojičné námestie", "Trojičné nám.", True),
        ("Čsl. armády", "Československej armády", True),
        ("Hlavné nám.", "Hlavná", False),
        ("Nová", "Novácka", False),
    ],
)
def test_same_name(written: str, name: str, same: bool):
    assert obvody.same_name(written, name) is same


def test_name_problems_and_dump_round_trip(tmp_path: Path):
    rules = rule_set(
        [
            {
                "street": "Hlavná",
                "numbers": "1-9",
                "parity": "odd",
                "written": "Hlavna",
            },
            {"street": "Nová", "inferred": True, "note": 'nová ulica "pri parku"'},
        ],
        [{"rest": True}],
    )
    assert obvody.name_problems(rules, ["Hlavná"], [], []) == [
        "obvod 1: Nová: the obec has no street 'Nová'"
    ]
    path = obvody.rules_path(tmp_path, "500001")
    path.parent.mkdir(parents=True)
    path.write_text(obvody.dump(rules, ["header"]), encoding="utf-8")
    assert obvody.load_rule_sets(tmp_path) == {"500001": rules}


def okrsky_set(okrsky: dict[str, list[int]], tables: dict, **extra) -> dict:
    """Return a rule set of obvod 1 (Hlavná, Krátka) and 2 (the rest), with okrsky."""
    obvod: dict[str, dict[str, Any]] = {
        "1": {"seats": 3, "rules": [{"street": "Hlavná"}, {"street": "Krátka"}]},
        "2": {"seats": 2, "rules": [{"rest": True}]},
    }
    for n, numbers in okrsky.items():
        obvod[n]["okrsky"] = numbers
    return {
        "obec": "500001",
        "name": "Alfa",
        "document": [DOCUMENT],
        "obvod": obvod,
        "okrsok": tables,
        **extra,
    }


def test_okrsky_share_the_addresses_of_their_obvod(tmp_path: Path):
    tables = {
        "1": {"rules": [{"street": "Hlavná", "numbers": "1-10"}, {"street": "Lúčna"}]},
        "2": {"rules": [{"rest": True}]},
    }
    data = okrsky_set({"1": [1, 2], "2": [3]}, tables, okrsky_date=dt.date(2026, 7, 1))
    rules = obvody.rule_set(data, "test")
    assert rules.okrsok_areas and rules.okrsok_obvod == {1: 1, 2: 1, 3: 2}
    places = [
        place("Hlavná", "1/5"),
        place("Hlavná", "2/50"),
        place("Krátka", "3/1"),
        place("Lúčna", "4/1"),
    ]
    a = obvody.assign(rules, places)
    assert a.units == [1, 1, 1, 2]
    k = obvody.assign_okrsky(rules, places, a.units)
    # The rest is obvod 1's, and Lúčna, of obvod 2, is okrsok 3 whatever
    # the rules of okrsok 1 say: but they name it only for addresses of
    # another obvod, which the check reports.
    assert k.units == [1, 2, 2, 3]
    assert k.problems(places) == [
        "okrsok 1: Lúčna: selects addresses only of obvod 2, not of its okrsok's"
    ]
    path = obvody.rules_path(tmp_path, "500001")
    path.parent.mkdir(parents=True)
    path.write_text(obvody.dump(rules), encoding="utf-8")
    assert obvody.load_rule_sets(tmp_path) == {"500001": rules}


def test_okrsky_known_only_by_obvod():
    rules = obvody.rule_set(okrsky_set({"1": [1, 2], "2": [3]}, {}), "test")
    assert rules.okrsky == {1: (1, 2), 2: (3,)} and not rules.okrsok_areas


def test_addressless_okrsok_takes_no_address():
    tables = {
        "1": {"rules": [{"street": "Hlavná"}]},
        "2": {"rules": [{"rest": True}]},
        "3": {"addressless": True},
        # Obvod 2's other okrsok has every address: it needs no rules.
        "5": {"addressless": True},
    }
    rules = obvody.rule_set(okrsky_set({"1": [1, 2, 3], "2": [4, 5]}, tables), "test")
    assert rules.addressless == (3, 5) and rules.okrsok_areas
    places = [place("Hlavná", "1/5"), place("Krátka", "3/1"), place("Lúčna", "4/1")]
    a = obvody.assign(rules, places)
    assert obvody.assign_okrsky(rules, places, a.units).units == [1, 2, 4]
    assert obvody.rule_set(tomllib.loads(obvody.dump(rules)), "test") == rules


@pytest.mark.parametrize(
    ("okrsky", "tables", "message"),
    [
        ({"1": [1, 2]}, {}, "in every obvod or in none"),
        ({"1": [1, 2], "2": [4]}, {}, "numbered 1..3"),
        ({"1": [1, 2], "2": [2]}, {}, "numbered 1..3"),
        (
            {"1": [1], "2": [2]},
            {"2": {"rules": [{"rest": True}]}},
            "alone in its obvod",
        ),
        (
            {"1": [1, 2], "2": [3]},
            {"1": {"rules": [{"rest": True}]}},
            "2 share an obvod",
        ),
        (
            {"1": [1, 2], "2": [3]},
            {"1": {"rules": [{"rest": True}]}, "2": {"rules": [{"rest": True}]}},
            "more than one rule is the rest",
        ),
    ],
)
def test_okrsky_form(okrsky: dict, tables: dict, message: str):
    with pytest.raises(obvody.ObvodyError, match=message):
        obvody.rule_set(okrsky_set(okrsky, tables), "test")


def whole_set(tables: dict, **extra) -> dict:
    """Return ``okrsky/500001.toml`` of an obec with one council obvod."""
    return {
        "obec": "500001",
        "name": "Alfa",
        "document": [DOCUMENT],
        "okrsok": tables,
        **extra,
    }


def test_okrsky_of_an_obec_with_one_obvod(tmp_path: Path):
    tables = {
        "1": {"rules": [{"part": "Beta"}, {"street": "Hlavná", "numbers": "1-9"}]},
        "2": {"rules": [{"rest": True}]},
        "3": {"addressless": True},
    }
    rules = obvody.okrsky_set(whole_set(tables, okrsky_fill="nearest"), "test")
    assert rules.whole and rules.okrsok_areas and rules.okrsky == {1: (1, 2, 3)}
    places = [
        place("Hlavná", "1/5"),
        place("Hlavná", "2/50"),
        place("", "7", "Beta"),
        place("Krátka", "3/1", "Beta"),
    ]
    a = obvody.assign(rules, places)
    assert a.units == [1, 1, 1, 1]
    assert obvody.assign_okrsky(rules, places, a.units).units == [1, 2, 1, 1]
    path = obvody.okrsky_path(tmp_path, "500001")
    path.parent.mkdir(parents=True)
    path.write_text(obvody.dump(rules, ["header"]), encoding="utf-8")
    assert obvody.okrsok_rule_sets(tmp_path) == {"500001": rules}
    # An obec with council obvody keeps its okrsky in its rule set.
    council = obvody.rules_path(tmp_path, "500001")
    council.parent.mkdir(parents=True)
    council.write_text(obvody.dump(rule_set([{"rest": True}])), encoding="utf-8")
    with pytest.raises(obvody.ObvodyError, match="the obec has council obvody"):
        obvody.okrsok_rule_sets(tmp_path)


def test_okrsky_file_with_one_okrsok_of_addresses():
    # The others hold only residents without an address: the one with the
    # addresses is the whole obec, its table empty, and stays so in its file.
    tables = {"1": {}, "2": {"addressless": True}, "3": {"addressless": True}}
    rules = obvody.okrsky_set(whole_set(tables), "test")
    assert rules.okrsok_areas and rules.okrsky == {1: (1, 2, 3)}
    places = [place("Hlavná", "1/5"), place("", "7", "Beta")]
    assert obvody.assign_okrsky(rules, places, [1, 1]).units == [1, 1]
    again = obvody.okrsky_set(tomllib.loads(obvody.dump(rules)), "test")
    assert again == rules
    tables["1"] = {"rules": [{"rest": True}]}
    with pytest.raises(obvody.ObvodyError, match="alone in its obvod"):
        obvody.okrsky_set(whole_set(tables), "test")


@pytest.mark.parametrize(
    ("tables", "extra", "message"),
    [
        ({"1": {"rules": [{"rest": True}]}}, {}, "numbered 1..N, N at least 2"),
        (
            {"1": {"rules": [{"part": "Beta"}]}, "3": {"rules": [{"rest": True}]}},
            {},
            "numbered 1..N",
        ),
        (
            {"1": {"rules": [{"part": "Beta"}]}, "2": {"rules": []}},
            {},
            "okrsok.2.rules: must not be empty",
        ),
        (
            {"1": {"rules": [{"part": "Beta"}]}, "2": {"rules": [{"rest": True}]}},
            {"obvod": {}},
            "obvod: unknown key",
        ),
        (
            {
                "1": {"rules": [{"near": [17.1, 48.1]}]},
                "2": {"rules": [{"rest": True}]},
            },
            {},
            "near rules are only for an estimated rule set",
        ),
    ],
)
def test_okrsky_file_form(tables: dict, extra: dict, message: str):
    with pytest.raises(obvody.ObvodyError, match=message):
        obvody.okrsky_set(whole_set(tables, **extra), "test")


@pytest.mark.parametrize(
    ("name", "website", "url", "ok"),
    [
        (
            "Pezinok",
            "https://www.pezinok.sk/",
            "https://www.pezinok.sk/content/u.pdf",
            True,
        ),
        (
            "Veľké Držkovce",
            "https://www.velkedrzkovce.sk/",
            "https://velkedrzkovce.sk/f.pdf",
            True,
        ),
        (
            "Holumnica",
            "https://www.obecholumnica.sk/",
            "https://www.obecholumnica.sk/a.pdf",
            True,
        ),
        (
            "Bratislava-Ružinov",
            "https://www.ruzinov.sk/",
            "https://cuet.slovensko.sk/sk/priloha/1",
            True,
        ),
        (
            "Bratislava-Staré Mesto",
            "https://www.staremesto.sk/",
            "https://data.moderneobce.sk/data/uploads/staremesto.sk/a.pdf",
            True,
        ),
        (
            "Bratislava-Staré Mesto",
            "https://www.staremesto.sk/",
            "https://data.moderneobce.sk/data/uploads/other.sk/a.pdf",
            False,
        ),
        ("Pezinok", "https://www.pezinok.sk/", "https://www.sme.sk/pezinok.pdf", False),
        ("Pezinok", "https://www.mojeobec.sk/", "https://www.mojeobec.sk/a.pdf", False),
        ("Pezinok", "https://www.pezinok.com/", "https://www.pezinok.com/a.pdf", False),
        (
            "Dubnica nad Váhom",
            "https://www.dubnica.eu/",
            "https://www.dubnica.eu/a.pdf",
            True,
        ),
        ("Vígľaš", "https://www.viglas.net/", "https://www.viglas.net/a.pdf", True),
        (
            "Bratislava-Nové Mesto",
            "https://banm.sk/",
            "https://data.moderneobce.sk/data/uploads/banm.sk/a.pdf",
            True,
        ),
        ("Pezinok", "https://banm.sk/", "https://banm.sk/a.pdf", False),
    ],
)
def test_official_domain(name: str, website: str, url: str, ok: bool):
    assert (obvodrules.official_problems(name, website, [url]) == []) is ok


def test_okrsok_item_names_the_city_of_a_district():
    obce = {
        "BA": {"code": "BA", "name": "Bratislava", "okres": "", "kraj": "1"},
        "528595": {
            "code": "528595",
            "name": "Bratislava-Petržalka",
            "okres": "105",
            "kraj": "1",
            "city": "BA",
        },
    }
    item = okrsokrules._identity(obce["528595"], {}, {"1": "Bratislavský"}, 3, obce)
    assert item["city"] == "Bratislava" and item["kraj"] == "Bratislavský"
    assert "city" not in okrsokrules._identity(obce["BA"], {}, {}, 3, obce)
