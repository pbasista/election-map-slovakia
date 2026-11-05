import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from election_map_slovakia import addresses as addr, geo, obvody, output
from election_map_slovakia.addresses import STREETS, House
from election_map_slovakia.candidates import Admin, Obec

ADMIN = Admin(
    kraje={"1": "Bratislavský", "8": "Košický"},
    okresy={
        "101": ("Bratislava I", "1"),
        "106": ("Malacky", "1"),
        "806": ("Košice - okolie", "8"),
    },
    obce={
        "BA": Obec("BA", "Bratislava", None, "1"),
        "528595": Obec("528595", "Bratislava-Staré Mesto", "101", "1", "BA"),
        "529362": Obec("529362", "Bratislava-Vajnory", "103", "1", "BA"),
        "500267": Obec("500267", "Záhorie (vojenský obvod)", "106", "1"),
        "521001": Obec("521001", "Bidovce", "806", "8"),
    },
)
CONTESTS = [
    {"id": "oz:BA/1", "kind": "oz", "area": "BA", "obvod": 1},
    {"id": "oz:BA/2", "kind": "oz", "area": "BA", "obvod": 2},
    {"id": "oz:528595/1", "kind": "oz", "area": "528595", "obvod": 1},
    {"id": "oz:528595/2", "kind": "oz", "area": "528595", "obvod": 2},
    {"id": "oz:529362/1", "kind": "oz", "area": "529362", "obvod": 1},
    {"id": "oz:521001/1", "kind": "oz", "area": "521001", "obvod": 1},
    {"id": "starosta:521001", "kind": "starosta", "area": "521001"},
]


def obec_file(groups: addr.Groups, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Return the content of the obec file of *groups*."""
    return json.loads(addr.obec_file(addr.obec_body(groups), *args, **kwargs))


@pytest.mark.parametrize(
    ("supisne", "orientacne", "shown"),
    [
        ("150", "2", "150/2"),
        ("1234", "5A", "1234/5A"),
        ("586", "", "586"),
        ("", "7", "7"),
    ],
)
def test_house_number(supisne: str, orientacne: str, shown: str):
    assert addr.house_number(supisne, orientacne) == shown


def test_house_numbers_sort_by_number_on_building():
    numbers = [("900", "10"), ("901", "2A"), ("50", ""), ("902", "2"), ("903", "1")]
    ordered = sorted(numbers, key=lambda n: addr.number_order(*n))
    assert [addr.house_number(*n) for n in ordered] == [
        "903/1",
        "902/2",
        "901/2A",
        "900/10",
        "50",
    ]


def test_council_status_single_and_several_incl_city_districts():
    council = addr.council_obvody(CONTESTS)
    # Staré Mesto elects its district council in two obvody, Vajnory in one;
    # the city council's obvody belong to BA, not to a district.
    assert addr.council_fields(council["528595"]) == {"council": "pending"}
    assert addr.council_fields(council["529362"]) == {"council": "single", "obvod": 1}
    assert addr.council_fields(council["521001"]) == {"council": "single", "obvod": 1}
    assert addr.council_fields(council.get("500267", [])) == {"council": "none"}
    house = House("1/1", (1, "", 1, ""), (1, 2))
    content = obec_file({(STREETS, "Hlavná"): [house]}, council["529362"])
    assert (content["council"], content["obvod"]) == ("single", 1)


def test_okrsok_per_address_in_each_group_of_an_obec_with_one_obvod(tmp_path: Path):
    document = {"url": "https://obec.sk/u.pdf", "sha256": "0" * 64, "title": "U"}
    tables = {
        "1": {"rules": [{"street": "Hlavná", "numbers": "1-9"}]},
        "2": {"rules": [{"rest": True}]},
    }
    data = {"obec": "521001", "name": "Bidovce", "document": [document]}
    rules = obvody.okrsky_set(data | {"okrsok": tables}, "test")
    hlavna = [House(n, (int(n), "", -1, ""), None, "", "", n) for n in ("5", "20")]
    kratka = [House("1", (1, "", -1, ""), None, "", "", "1")]
    groups = {(STREETS, "Hlavná"): hlavna, (STREETS, "Krátka"): kratka}
    places = unlocated_places(groups)
    reg = register(tmp_path, {"521001": groups})
    result = addr.Result(reg, {}, {"521001": [1]})
    result.places = {"521001": places.to_json()}
    addr.assign(result, {}, {"521001": rules})
    content = obec_file(groups, [1], None, result.okrsky["521001"])
    assert content["council"] == "single"
    assert [
        (g["name"], g.get("okrsok"), g.get("okrsky")) for g in content[STREETS]
    ] == [
        ("Hlavná", None, [1, 2]),
        ("Krátka", 2, None),
    ]
    assert "obvod" not in content[STREETS][0]
    # The file keeps them for geo, which takes them by those rules, and
    # assigns anew by other ones.
    stored = obvody.parse_places(result.places["521001"])
    assert stored.okrsky is not None and stored.okrsky.units == [1, 2, 2]
    assert stored.obvody is not None and stored.obvody.units == [1, 1, 1]
    assert geo._assigned(rules, rules, stored) == ([1, 1, 1], [], [1, 2, 2])
    moved = {
        "1": {"rules": [{"rest": True}]},
        "2": {"rules": [{"street": "Krátka"}]},
    }
    other = obvody.okrsky_set(data | {"okrsok": moved}, "test")
    assert geo._assigned(other, other, stored) == ([1, 1, 1], [], [1, 1, 2])


def unlocated_places(groups: addr.Groups) -> obvody.ObecPlaces:
    """Return the places of *groups*, houses without points."""
    houses = sum(map(len, groups.values()))
    return addr.obec_places(groups, [], np.full((houses, 2), np.nan))


def register(directory: Path, obce: dict[str, addr.Groups]) -> addr.Register:
    """Return a register of the groups of *obce*, without points."""
    return addr.Register(
        directory,
        ADMIN,
        {
            code: addr.RegisterObec(
                sum(map(len, groups.values())),
                [(g, len(h)) for g, h in groups.items()],
                addr.obec_body(groups),
                unlocated_places(groups).to_json(),
            )
            for code, groups in obce.items()
        },
        b"",
        b"",
        [],
        [],
        [],
        [],
    )


def test_obec_file_is_the_json_of_its_content():
    a = House("1", (1, "", -1, ""), (1_912_150, 4_866_615))
    b = House("2", (2, "", -1, ""), None)
    groups = {(addr.PARTS, "Dolná"): [b], (STREETS, "Hlavná"): [a, b]}
    body = addr.obec_body(groups)
    units = {(addr.PARTS, "Dolná"): [3], (STREETS, "Hlavná"): [1, 2]}
    data = addr.obec_file(body, [1, 2, 3], units, units)
    content = json.loads(data)
    assert output.to_json(content) == data
    assert content == {
        "council": "address",
        "streets": [
            {
                "name": "Hlavná",
                "numbers": ["1", "2"],
                "points": [1_912_150, 4_866_615, None, None],
                "obvody": [1, 2],
                "okrsky": [1, 2],
            }
        ],
        "parts": [
            {
                "name": "Dolná",
                "numbers": ["2"],
                "points": [None, None],
                "obvod": 3,
                "okrsok": 3,
            }
        ],
    }
    for group in (*content["streets"], *content["parts"]):
        for unit in ("obvod", "obvody", "okrsok", "okrsky"):
            group.pop(unit, None)
    assert addr.obec_file(body, [1]) == output.to_json(
        {"council": "single", "obvod": 1}
        | {k: content[k] for k in ("streets", "parts")}
    )


def test_register_cached_while_its_key_holds(tmp_path: Path, monkeypatch):
    made = []
    groups = {(STREETS, "Hlavná"): [House("1", (1, "", -1, ""), None)]}

    def make(path, gpkg, overrides, skip):
        made.append(path)
        fields = {
            k: v
            for k, v in vars(register(tmp_path, {"521001": groups})).items()
            if k != "directory"
        }
        ids = [("7", (STREETS, "Hlavná"), "1"), ("7", (STREETS, "Hlavná"), "2")]
        rows = {
            "numbers": ["1", "2"],
            "obce": {
                "521001": (
                    [(STREETS, "Hlavná")],
                    [i for i, _, _ in ids],
                    np.array([0, 0], dtype=np.int32),
                    np.array([0, 1], dtype=np.int32),
                )
            },
        }
        return fields, rows

    monkeypatch.setattr(addr, "_make_register", make)
    cache = tmp_path / "cache"
    first = addr.register(cache, "key 1", Path("a.csv"), Path("g"), {})
    again = addr.register(cache, "key 1", Path("b.csv"), Path("g"), {})
    assert made == [Path("a.csv")]
    assert again.obce == first.obce and again.directory == cache
    addr.register(cache, "key 2", Path("c.csv"), Path("g"), {})
    assert made == [Path("a.csv"), Path("c.csv")]
    # A later row of an identifikator replaces the earlier, as a dict does.
    assert again.houses(["521001", "500267"]) == {
        "521001": {"7": (STREETS, "Hlavná", "2")}
    }


def test_far_points_dropped_but_address_kept():
    near = House("1", (1, "", -1, ""), (1_912_150, 4_866_615))
    far = House("2", (2, "", -1, ""), (1_800_000, 4_800_000))
    a = addr.Addresses({"521001": {(STREETS, "Hlavná"): [near, far]}}, 2, 0)
    outside = [
        addr.Outside(addr.Ref("521001", (STREETS, "Hlavná"), near), 40.0, None),
        addr.Outside(addr.Ref("521001", (STREETS, "Hlavná"), far), 5000.0, "500267"),
    ]
    assert addr.drop_far(a, outside) == 1
    assert a.obce["521001"][(STREETS, "Hlavná")] == [near, far._replace(point=None)]


def test_contests_of_a_city_district():
    obec = ADMIN.obce["528595"]
    props = {"zsk": 3, "city_obvod": 1}
    assert addr.contests(obec, [1, 2], props) == [
        "starosta:528595",
        "oz:528595/?",
        "starosta:BA",
        "oz:BA/1",
        "predseda:1",
        "zsk:1/3",
    ]


def test_points_delta_encoded_across_groups_and_gaps():
    a = House("1", (1, "", -1, ""), (1_912_150, 4_866_615))
    b = House("2", (2, "", -1, ""), None)
    c = House("3", (3, "", -1, ""), (1_912_100, 4_866_700))
    d = House("4", (4, "", -1, ""), (1_800_000, 4_800_000))
    content = obec_file(
        {(addr.PARTS, "Dolná"): [d], (STREETS, "Hlavná"): [a, b, c]}, []
    )
    flat = [
        p for kind in (STREETS, addr.PARTS) for g in content[kind] for p in g["points"]
    ]
    decoded, x, y = [], 0, 0
    for dx, dy in zip(flat[::2], flat[1::2]):
        if dx is None:
            decoded.append(None)
        else:
            x, y = x + dx, y + dy
            decoded.append((x, y))
    assert decoded == [a.point, None, c.point, d.point]


HEADER = ";".join(addr.COLUMNS)


def write_csv(path: Path, *rows: str) -> Path:
    path.write_bytes(("\r\n".join([HEADER, *rows]) + "\r\n").encode())
    return path


def test_read_matches_districts_okolie_and_overrides(tmp_path: Path):
    csv = write_csv(
        tmp_path / "a.csv",
        "1;Bratislavský;Bratislava I;Bratislava-Staré Mesto;;Obchodná;512;7;81106;17,1;48,1",
        "2;Košický;Košice - okolie;Bidovce;Bidovce;;5;;04445;21,4;48,7",
        "3;Košický;Košice - okolie;Bidovce;;;6;;04445;;",
        "4;Bratislavský;Malacky;Záhorie;;;1;;90101;17,2;48,5",
    )
    a = addr.read(csv, ADMIN, {"Malacky/Záhorie": "500267"})
    assert a.obce["528595"] == {
        (STREETS, "Obchodná"): [
            House(
                "512/7",
                (7, "", 512, ""),
                (1_710_000, 4_810_000),
                "Bratislava-Staré Mesto",
                "512",
                "7",
            )
        ]
    }
    assert [h.number for h in a.obce["521001"][(addr.PARTS, "Bidovce")]] == ["5", "6"]
    assert a.obce["521001"][(addr.PARTS, "Bidovce")][1].point is None
    assert list(a.obce["500267"]) == [(addr.PARTS, "Záhorie")]


def test_read_lists_unmatched_and_rejects_other_coordinates(tmp_path: Path):
    csv = write_csv(
        tmp_path / "a.csv",
        "1;Košický;Košice - okolie;Bidovce;;;5;;04445;21,4;48,7",
        "2;Košický;Košice - okolie;Nikde;;;5;;04445;21,4;48,7",
    )
    with pytest.raises(addr.AddressesError, match="'Nikde'"):
        addr.read(csv, ADMIN, {})
    csv = write_csv(
        tmp_path / "b.csv",
        "1;Košický;Košice - okolie;Bidovce;;;5;;04445;-261000,5;-1231000,2",
    )
    with pytest.raises(addr.AddressesError, match="coordinate system"):
        addr.read(csv, ADMIN, {})


def test_contests_of_other_kinds_of_election():
    obec = ADMIN.obce["528595"]
    # Country-wide: every voter's contests, none of the self-governments'.
    national = ["prezident:SK/1", "prezident:SK/2"]
    props = {"zsk": 0}
    assert addr.contests(obec, [], props, None, {"prezident"}, national) == national
    # A by-election of mayors only: no council, no regional contests.
    assert addr.contests(obec, [], props, None, {"starosta"}) == [
        "starosta:528595",
        "starosta:BA",
    ]


def test_by_election_council_of_part_of_an_obec():
    contests = [
        # The obec's one obvod, seats known: the whole council.
        {"id": "oz:521001/1", "kind": "oz", "area": "521001", "obvod": 1, "seats": 5},
        # Obvod 2 of more: part of a council.
        {"id": "oz:529362/2", "kind": "oz", "area": "529362", "obvod": 2, "seats": 1},
        # Candidates in several obvody, seats per obvod unknown.
        {"id": "oz:528595/1", "kind": "oz", "area": "528595", "obvod": 1},
        {"id": "oz:528595/2", "kind": "oz", "area": "528595", "obvod": 2},
    ]
    assert addr.part_councils(contests, ()) == {"529362", "528595"}
    # Obvod 1 with seats of a council its term elected in several obvody
    # (Divina, 2026-03: obvod 1 of 3): one obvod of a larger council.
    term = [
        {"id": f"oz:521001/{n}", "kind": "oz", "area": "521001", "obvod": n}
        for n in (1, 2, 3)
    ]
    split = addr.split_councils(term)
    assert split == {"521001"}
    everywhere = {"521001", "529362", "528595"}
    assert addr.part_councils(contests, split) == everywhere
    council = addr.council_obvody(contests)
    house = House("1/1", (1, "", 1, ""), (1, 2))
    groups = {(STREETS, "Hlavná"): [house]}
    whole = obec_file(groups, council["521001"])
    assert (whole["council"], whole["obvod"]) == ("single", 1)
    # Without a rule set the addresses are in no known obvod; with one, each
    # has its obvod, those electing no one as well.
    pending = obec_file(groups, council["529362"], whole=False)
    assert pending["council"] == "pending" and "obvod" not in pending
    assigned = {(STREETS, "Hlavná"): [4]}
    by_rules = obec_file(groups, council["529362"], assigned, whole=False)
    assert (by_rules["council"], by_rules[STREETS][0]["obvod"]) == ("address", 4)
    obec = ADMIN.obce["529362"]
    props = {"zsk": 0}
    kinds = {"oz"}
    assert addr.contests(obec, [2], props, None, kinds, whole=False) == ["oz:529362/?"]
    assert addr.contests(obec, [2], props, 4, kinds, whole=False) == []
    assert addr.contests(obec, [2], props, 2, kinds, whole=False) == ["oz:529362/2"]


def test_an_uncontested_obvod_comes_from_the_election_s_own_decision():
    """Ilava's obvod 6 of 2018, held nowhere: its rule set of that election
    lists it with its seat and the document it is sourced to; another
    vote's rule set standing in does not."""
    doc = "https://www.ilava.sk/obvody5a6.pdf"
    data = {
        "obec": "513156",
        "name": "Ilava",
        "date": dt.date(2018, 8, 14),
        "document": [{"url": doc, "sha256": "0" * 64, "title": "Oznámenie"}],
        "obvod": {
            "1": {"seats": 3, "rules": [{"part": "Ilava"}]},
            "2": {"seats": 1, "rules": [{"part": "Iliavka"}]},
        },
    }
    rules = obvody.rule_set(data, "test")
    why = {"source": doc, "title": "Oznámenie: celá Iliavka"}
    contests = [
        {"id": "oz:513156/1", "kind": "oz", "area": "513156", "obvod": 1},
        {"id": "oz:513156/2", "kind": "oz", "area": "513156", "obvod": 2, "seats": 1,
         "uncontested": why},
    ]  # fmt: skip
    assert addr.uncontested_problems(contests, {"513156": rules}) == []
    assert addr.uncontested_problems(contests, {}) == [
        "oz:513156/2: no rule set of the election's own decision"
    ]
    adopted = obvody.rule_set(
        data | {"adopted": dt.date(2026, 10, 24), "adopted_basis": "No 2018 document."},
        "test",
    )
    assert addr.uncontested_problems(contests, {"513156": adopted}) == [
        "oz:513156/2: no rule set of the election's own decision"
    ]
    elsewhere = [
        *contests[:1],
        {**contests[1], "uncontested": {**why, "source": "https://x.sk/y"}},
    ]
    assert addr.uncontested_problems(elsewhere, {"513156": rules}) == [
        "oz:513156/2: https://x.sk/y is none of its rule set's documents"
    ]
    two = [*contests[:1], {**contests[1], "seats": 2}]
    assert addr.uncontested_problems(two, {"513156": rules}) == [
        "oz:513156/2: 2 seats, its rule set 1"
    ]
