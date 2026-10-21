from pathlib import Path

import pytest

from election_map_slovakia import addresses as addr
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
    content = addr.obec_file({(STREETS, "Hlavná"): [house]}, council["529362"])
    assert (content["council"], content["obvod"]) == ("single", 1)


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
    content = addr.obec_file(
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
