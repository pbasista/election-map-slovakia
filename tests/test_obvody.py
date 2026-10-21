import datetime as dt
from pathlib import Path

import numpy as np
import pytest

from election_map_slovakia import config, obvodrules, obvody
from election_map_slovakia.candidates import Obec
from election_map_slovakia.config import Obvod, ObvodList

CURATED = Path(__file__).resolve().parent.parent / "data" / "curated" / "obvody"

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
    for path in sorted((CURATED / obvody.RULES_DIRECTORY).glob("*.toml")):
        assert obvody.load_rule_sets(CURATED.parent)[path.stem].obec == path.stem


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
    return obvody.assign(rules, places).obvody


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
    assert a.obvody == [0, 0, 1]
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
    assert a.obvody == [1, 2, 0]


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
    assert a.obvody == [1, 2, 2, 2, 2, 0]
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
    assert a.obvody == [1, 2, 3, 0]
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
    path = tmp_path / "data" / "curated" / "obvody" / "oz" / "500001.toml"
    path.parent.mkdir(parents=True)
    path.write_text(obvody.dump(rules, ["header"]), encoding="utf-8")
    assert obvody.load_rule_sets(tmp_path / "data" / "curated") == {"500001": rules}


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
