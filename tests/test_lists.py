import csv
import datetime as dt
import zipfile
from pathlib import Path

import pytest
from test_candidates import write_xlsx

from election_map_slovakia import candidates as cand, config, lists, statoffice
from election_map_slovakia.candidates import Admin, Obec
from election_map_slovakia.config import CandidateLists, Overrides

TZ = dt.timezone(dt.timedelta(hours=1))
ADMIN = Admin(
    kraje={"1": "Bratislavský", "4": "Nitriansky", "5": "Žilinský"},
    okresy={
        "101": ("Bratislava I", "1"),
        "402": ("Levice", "4"),
        "403": ("Nitra", "4"),
        "511": ("Žilina", "5"),
    },
    obce={
        "BA": Obec("BA", "Bratislava", None, "1"),
        "528595": Obec("528595", "Bratislava-Staré Mesto", "101", "1", "BA"),
        "500011": Obec("500011", "Nitra", "403", "4"),
        "502341": Obec("502341", "Hronské Kosihy", "402", "4"),
        "502342": Obec("502342", "Lehota", "402", "4"),
        "517001": Obec("517001", "Lehota", "511", "5"),
        "517488": Obec("517488", "Divina", "511", "5"),
        "517755": Obec("517755", "Lietavská Svinná - Babkov", "511", "5"),
    },
)
NO_OVERRIDES = Overrides({}, {}, (), (), {})
TITLE = [["Tabuľka"], [""]]


def election(kind: str, candidates: CandidateLists | None, **fields) -> config.Election:
    day = dt.date(2024, 3, 23)
    return config.Election(
        day=day,
        slug="2024-x",
        kind=kind,
        polls_open=dt.datetime.combine(day, dt.time(7), TZ),
        polls_close=dt.datetime.combine(day, dt.time(22), TZ),
        live=False,
        live_window=None,
        candidates=candidates,
        incumbents=None,
        units=None,
        results=config.Results("volbysr", ()),
        addresses="addresses-2026",
        zbgis=("zbgis-0-2026", "zbgis-1-2026", "zbgis-2-2026"),
        osm="osm",
        records=(),
        **fields,
    )


def write_csv(path: Path, rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f, quoting=csv.QUOTE_ALL).writerows(rows)
    return path


def candidates_json(
    monkeypatch: pytest.MonkeyPatch, read: cand.Lists
) -> dict[str, list]:
    monkeypatch.setattr(cand, "load_admin", lambda _: ADMIN)
    result = cand.build(
        read, Path("zbgis.gpkg"), NO_OVERRIDES, None, dt.date(2024, 3, 23)
    )
    return cand.to_json(result)


PRESIDENT = [
    "Poradie na hlasovacom lístku", "Meno", "Priezvisko", "Titul", "Vek",
    "Zamestnanie", "Obec", "Poznámka",
]  # fmt: skip


def test_presidential_rounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Round 1 a CSV table, round 2 an XLSX one in a package; the residence
    # an obec name, unique in the country or not.
    round1 = write_csv(
        tmp_path / "PREZ2024_kolo1_SK_tab0a.csv",
        [
            PRESIDENT,
            ["1", "Ivan", "Korčok", "Ing.", "60", "diplomat", "Bratislava", ""],
            ["2", "Peter", "Pellegrini", "Ing.", "48", "predseda", "Nitra", ""],
            ["3", "Ján", "Novák", "", "50", "učiteľ", "Lehota", "X"],
        ],
    )
    table = write_xlsx(
        tmp_path / "PREZ2024_kolo2_SK_tab0a.xlsx",
        [
            *TITLE,
            PRESIDENT,
            ["1", "Ivan", "Korčok", "Ing.", "60", "diplomat", "Bratislava", ""],
            ["2", "Peter", "Pellegrini", "Ing.", "48", "predseda", "Nitra", ""],
        ],
    )
    round2 = tmp_path / "PREZ2024_kolo2.zip"
    with zipfile.ZipFile(round2, "w") as z:
        z.write(table, table.name)
    e = election(
        "presidential",
        CandidateLists("volbysr", {"round1": "r1", "round2": "r2"}),
        second_round=dt.date(2024, 4, 6),
    )
    read = lists.read(e, {"round1": round1, "round2": round2}, tmp_path)
    assert read.withdrawn == {"prezident:SK/1#3"}
    data = candidates_json(monkeypatch, read)
    assert data["contests"] == [
        {"id": "prezident:SK/1", "kind": "prezident", "area": "SK", "obvod": 1},
        {
            "id": "prezident:SK/2",
            "kind": "prezident",
            "area": "SK",
            "obvod": 2,
            "day": "2024-04-06",
        },
    ]
    by_id = {c["id"]: c for c in data["candidacies"]}
    assert by_id["prezident:SK/1#1"] | {"person": ""} == {
        "id": "prezident:SK/1#1",
        "contest": "prezident:SK/1",
        "number": 1,
        "person": "",
        "title_before": "Ing.",
        "title_after": "",
        "first_name": "Ivan",
        "surname": "Korčok",
        "age": 60,
        "occupation": "diplomat",
        "parties": [],
        "independent": False,
        "residence": "BA",
    }
    assert by_id["prezident:SK/2#2"]["residence"] == "500011"
    # Two obce are named Lehota: the name as written stands in.
    novak = by_id["prezident:SK/1#3"]
    assert "residence" not in novak
    assert (novak["residence_name"], novak["withdrawn"]) == ("Lehota", True)
    # One person stands in both rounds.
    persons = sorted((p["candidacies"], p["obec"]) for p in data["persons"])
    assert persons == [
        (["prezident:SK/1#1", "prezident:SK/2#1"], "BA"),
        (["prezident:SK/1#2", "prezident:SK/2#2"], "500011"),
        (["prezident:SK/1#3"], ""),
    ]
    assert by_id["prezident:SK/1#1"]["person"] == by_id["prezident:SK/2#1"]["person"]


SUBJECTS = [
    "Číslo politického subjektu", "Názov politického subjektu",
    "Skratka politického subjektu", "Počet kandidátov", "Poznámka",
]  # fmt: skip
LIST = [
    "Číslo politického subjektu", "Názov politického subjektu",
    "Poradie na hlasovacom lístku", "Meno", "Priezvisko", "Titul", "Vek",
    "Zamestnanie", "Obec trvalého pobytu", "Poznámka",
]  # fmt: skip
NRSR = {
    "seats": 150,
    "threshold": 5.0,
    "coalition_thresholds": ((2, 7.0), (4, 10.0)),
    "preferences": 4,
    "preference_quota": 3.0,
}


def party_tables(tmp_path: Path, stated: str = "2") -> dict[str, Path]:
    subjects = write_xlsx(
        tmp_path / "NRSR2023_SK_tab0a.xlsx",
        [
            *TITLE,
            SUBJECTS,
            ["1", "Progresívne Slovensko", "PS", stated, ""],
            ["2", "SMER", "SMER", "1", ""],
            ["3", "Spolu A B", "AB", "", "X"],
            [],
            ["Vysvetlivky: X – subjekt sa vzdal"],
        ],
    )
    candidates = write_csv(
        tmp_path / "NRSR2023_SK_tab0b.csv",
        [
            LIST,
            ["1", "Progresívne Slovensko", "1", "Michal", "Šimečka", "Mgr.", "39",
             "poslanec", "Bratislava", ""],
            ["1", "Progresívne Slovensko", "2", "Jana", "Nová", "", "48",
             "učiteľka", "Nitra", "X"],
            ["2", "SMER", "1", "Robert", "Fico", "JUDr. CSc.", "59", "poslanec",
             "Bratislava", ""],
        ],
    )  # fmt: skip
    return {"subjects": subjects, "candidates": candidates}


def test_party_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = party_tables(tmp_path)
    e = election("parliament", CandidateLists("volbysr", {"subjects": "s"}), **NRSR)
    read = lists.read(e, paths, tmp_path)
    assert read.withdrawn == {"nrsr:SK/1#2"}
    data = candidates_json(monkeypatch, read)
    assert data["contests"] == [
        {
            "id": "nrsr:SK",
            "kind": "nrsr",
            "area": "SK",
            "seats": 150,
            "subjects": [
                {"number": 1, "party": "Progresívne Slovensko", "candidates": 2},
                {"number": 2, "party": "SMER", "candidates": 1},
                {"number": 3, "party": "Spolu A B", "withdrawn": True},
            ],
            "threshold": 5.0,
            "coalition_thresholds": [[2, 7.0], [4, 10.0]],
            "preferences": 4,
            "quota": 3.0,
        },
        {"id": "nrsr:SK/1", "kind": "nrsr", "area": "SK", "obvod": 1,
         "party": "Progresívne Slovensko"},
        {"id": "nrsr:SK/2", "kind": "nrsr", "area": "SK", "obvod": 2,
         "party": "SMER"},
        {"id": "nrsr:SK/3", "kind": "nrsr", "area": "SK", "obvod": 3,
         "party": "Spolu A B"},
    ]  # fmt: skip
    fico = next(c for c in data["candidacies"] if c["id"] == "nrsr:SK/2#1")
    assert (fico["parties"], fico["independent"]) == (["SMER"], False)
    assert (fico["title_before"], fico["title_after"]) == ("JUDr.", "CSc.")
    assert fico["residence"] == "BA"


def test_party_list_size_must_match_its_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = party_tables(tmp_path, stated="3")
    e = election("parliament", CandidateLists("volbysr", {}), **NRSR)
    read = lists.read(e, paths, tmp_path)
    with pytest.raises(cand.CandidatesError, match="nrsr:SK/1: 2 candidates, the list"):
        candidates_json(monkeypatch, read)


def test_party_list_of_no_subject(tmp_path: Path):
    paths = party_tables(tmp_path)
    rows = list(csv.reader(paths["candidates"].open(encoding="utf-8")))
    rows[3][0] = "9"
    write_csv(paths["candidates"], rows)
    e = election("parliament", CandidateLists("volbysr", {}), **NRSR)
    with pytest.raises(cand.CandidatesError, match="data row 3: no subject 9"):
        lists.read(e, paths, tmp_path)


def test_european_party_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The header rows of EP 2019's tab0a (no notes) and EP 2024's tab0b."""
    subjects = write_xlsx(
        tmp_path / "EP_2019_SK_tab0a.xlsx",
        [
            *TITLE,
            ["Číslo politického subjektu", "Názov politického subjektu",
             "Oficiálna skratka politického subjektu", "Počet kandidátov"],
            ["1", "SMER - sociálna demokracia", "SMER-SD", "1"],
            ["29", "Koalícia Progresívne Slovensko a SPOLU - občianska demokracia",
             "Koalícia PS a SPOLU", "1"],
        ],
    )  # fmt: skip
    candidates = write_csv(
        tmp_path / "EP2024_SK_tab0b.csv",
        [
            [*LIST[:8], "Obec", "Poznámka"],
            ["1", "SMER - sociálna demokracia", "1", "Monika", "Beňová", "PhDr.",
             "50", "poslankyňa EP", "Bratislava", ""],
            ["29", "Koalícia Progresívne Slovensko a SPOLU - občianska demokracia",
             "1", "Michal", "Šimečka", "Mgr.", "35", "politológ", "Bratislava", ""],
        ],
    )  # fmt: skip
    fields = {"seats": 14, "threshold": 5.0, "preferences": 2, "preference_quota": 3.0}
    e = election("european", CandidateLists("volbysr", {}), **fields)
    read = lists.read(e, {"subjects": subjects, "candidates": candidates}, tmp_path)
    data = candidates_json(monkeypatch, read)
    party = data["contests"][0]
    assert (party["id"], party["preferences"], party["quota"]) == ("ep:SK", 2, 3.0)
    assert "coalition_thresholds" not in party
    assert [s["number"] for s in party["subjects"]] == [1, 29]
    simecka = next(c for c in data["candidacies"] if c["id"] == "ep:SK/29#1")
    assert simecka["parties"] == [
        "Koalícia Progresívne Slovensko a SPOLU - občianska demokracia"
    ]


BY_UNITS = [
    "Kód kraja", "Názov kraja", "Kód územného obvodu", "Názov územného obvodu",
    "Kód okresu", "Názov okresu", "Kód obce", "Názov obce",
    "Počet volebných obvodov", "Počet okrskov", "Počet volených poslancov",
    "Typ volieb",
]  # fmt: skip
BY_MAYORS = [
    "Kód kraja", "Názov kraja", "Kód územného obvodu", "Názov územného obvodu",
    "Kód okresu", "Názov okresu", "Kód obce", "Názov obce",
    "Poradie na hlasovacom lístku", "Meno", "Priezvisko", "Titul", "Vek",
    "Zamestnanie", "Politický subjekt", "Poznámka",
]  # fmt: skip
BY_MEMBERS = [*BY_MAYORS[:8], "Volebný obvod v obci", *BY_MAYORS[8:]]
BY_PARTIES = [
    "Kód politickej strany",
    "Názov politickej strany",
    "Skratka politickej strany",
]
LEVICE = ["4", "Nitriansky kraj", "402", "Levice", "402", "Levice"]
ZILINA = ["5", "Žilinský kraj", "507", "Žilina", "511", "Žilina"]


def by_election_package(tmp_path: Path) -> Path:
    """Return a package shaped like ŠÚ SR's of a by-election (OSO202603)."""
    kosihy = [*LEVICE, "502341", "Hronské Kosihy"]
    divina = [*ZILINA, "517488", "Divina"]
    svinna = [*ZILINA, "517755", "Lietavská Svinná - Babkov"]
    tables = {
        "tab0c": [
            BY_PARTIES,
            ["101", "Demokrati", "Demokrati"],
            ["152", "Zmena zdola, Demokratická únia Slovenska", "Zmena zdola, DÚ"],
        ],
        "tab0dd": [
            BY_UNITS,
            [*kosihy, "1", "1", "1", "Starosta a zastupiteľstvo"],
            [*divina, "3", "3", "1", "Len zastupiteľstvo"],
            [*svinna, "2", "2", "6", "Len zastupiteľstvo"],
            [*ZILINA, "517001", "Lehota", "1", "1", "1", "Nekonajú sa"],
        ],
        "tab0ad": [
            BY_MAYORS,
            [*kosihy, "1", "Anton", "Horváth", "", "71", "roľník", "Demokrati", ""],
            [*kosihy, "2", "Michaela", "Slováková", "Mgr.", "40", "učiteľka", "NEKA",
             "X"],
        ],
        "tab0bd": [
            BY_MEMBERS,
            [*kosihy, "1", "1", "Adriana", "Benčaťová", "Mgr.", "31", "učiteľka",
             "Zmena zdola, DÚ, Demokrati", ""],
            [*divina, "3", "1", "Norbert", "Varga", "", "45", "technik", "NEKA", ""],
            [*svinna, "1", "1", "Eva", "Malá", "", "52", "účtovníčka", "NEKA", ""],
            [*svinna, "2", "1", "Ivan", "Veľký", "", "33", "kuchár", "NEKA", ""],
        ],
    }  # fmt: skip
    path = tmp_path / "OSO202603_SK_xlsx.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, rows in tables.items():
            table = write_xlsx(
                tmp_path / f"OSO202603_SK_{name}.xlsx",
                [*TITLE, *rows, [], ["Vysvetlivky"]],
            )
            z.write(table, table.name)
    return path


PACKAGE_URL = "https://volby.example.sk/p.zip"
TERM = lists.Term(
    {"502341": [1], "517488": [1, 2, 3], "517755": [1, 2], "517001": [1]},
    {"502341": 7, "517488": 9, "517755": 9, "517001": 5},
)
"""What the term's candidates say of the councils of the packages below:
each by-election fills some seats (a by-election proper, ``vote`` ``"by"``)."""


def not_held(table: str) -> dict[str, str]:
    """Return the ``uncontested`` of a contest the by-election package's *table* says was held nowhere."""
    return {"source": PACKAGE_URL, "title": f"ŠÚ SR, {table}: Typ volieb „nekonajú sa“"}


def test_by_election_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    e = election("by-election", CandidateLists("susr-by", {"package": "p"}))
    package = by_election_package(tmp_path)
    read = lists.read(
        e, {"package": package}, tmp_path, urls={"package": PACKAGE_URL}, term=TERM
    )
    assert read.partial
    assert read.withdrawn == {"starosta:502341#2"}
    # Seats only where the obec's candidates stand in one obvod; Lehota's
    # seat, called but held nowhere, in its one obvod.
    assert read.seats == {"oz:502341/1": 1, "oz:517488/3": 1, "oz:517001/1": 1}
    adriana = next(e for e in read.entries if e.first_name == "Adriana")
    assert adriana.parties == ["Zmena zdola, Demokratická únia Slovenska", "Demokrati"]
    assert not adriana.independent
    data = candidates_json(monkeypatch, read)
    # Contests only where held; Divina's obvod 3 of 3 alone. A mayor is
    # elected anew; the councils' seats are some of their term's.
    assert data["contests"] == [
        {"id": "starosta:502341", "kind": "starosta", "area": "502341", "vote": "new"},
        {"id": "oz:502341/1", "kind": "oz", "area": "502341", "obvod": 1, "seats": 1,
         "vote": "by"},
        {"id": "oz:517001/1", "kind": "oz", "area": "517001", "obvod": 1, "seats": 1,
         "uncontested": not_held("OSO202603_SK_tab0dd.xlsx"), "vote": "by"},
        {"id": "oz:517488/3", "kind": "oz", "area": "517488", "obvod": 3, "seats": 1,
         "vote": "by"},
        {"id": "oz:517755/1", "kind": "oz", "area": "517755", "obvod": 1,
         "vote": "by"},
        {"id": "oz:517755/2", "kind": "oz", "area": "517755", "obvod": 2,
         "vote": "by"},
    ]  # fmt: skip
    # Without its source, a contest held nowhere is refused.
    with pytest.raises(
        cand.CandidatesError, match="no source says it was held nowhere"
    ):
        lists.read(e, {"package": package}, tmp_path)
    slovakova = next(c for c in data["candidacies"] if c["id"] == "starosta:502341#2")
    assert (slovakova["parties"], slovakova["independent"]) == ([], True)
    assert "residence" not in slovakova


def test_by_election_unknown_party(tmp_path: Path):
    package = by_election_package(tmp_path)
    with zipfile.ZipFile(package) as z:
        members = {n: z.read(n) for n in z.namelist() if not n.endswith("tab0c.xlsx")}
    parties = [*TITLE, BY_PARTIES, ["152", "Zmena zdola", "Zmena zdola, DÚ"]]
    with zipfile.ZipFile(package, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
        z.write(write_xlsx(tmp_path / "t.xlsx", parties), "OSO202603_SK_tab0c.xlsx")
    e = election("by-election", CandidateLists("susr-by", {"package": "p"}))
    with pytest.raises(
        cand.CandidatesError, match=r"tab0ad.xlsx: data row 1: unknown parties"
    ):
        lists.read(e, {"package": package}, tmp_path)


OLDER_UNITS = [*BY_UNITS[:8], "Počet volených poslancov", "Typ volieb"]
OLDER_MAYORS = [
    *BY_MAYORS[:8], "Poradie na hlasovacom lístku", "Meno", "Priezvisko",
    "Politický subjekt", "Poznámka",
]  # fmt: skip
OLDER_ELECTED = [
    *BY_MAYORS[:8], "Volebný obvod v obci", "Poradie zvolenia v obci",
    "Meno a priezvisko", "Politický subjekt", "Počet platných hlasov",
]  # fmt: skip


def older_by_election_package(tmp_path: Path) -> Path:
    """Return a package shaped like ŠÚ SR's of a by-election of 2019–2022
    (OSO_201904): mayors without title, age or occupation, of the councils
    the elected only, a name with its titles in one column."""
    kosihy = [*LEVICE, "502341", "Hronské Kosihy"]
    svinna = [*ZILINA, "517755", "Lietavská Svinná - Babkov"]
    tables = {
        "tab0b": [BY_PARTIES, ["101", "Demokrati", "Demokrati"]],
        "tab0c": [
            OLDER_UNITS,
            [*kosihy, "2", "starosta a zastupiteľstvo"],
            [*svinna, "3", "len zastupiteľstvo"],
            [*ZILINA, "517001", "Lehota", "1", "nekonajú sa"],
        ],
        "tab0a": [
            OLDER_MAYORS,
            [*kosihy, "1", "Anton", "Horváth", "Demokrati", ""],
            [*kosihy, "2", "Michaela", "Slováková", "NEKA", "X"],
        ],
        "tab06": [
            OLDER_ELECTED,
            [*kosihy, "1", "1", "Anton Horváth", "Demokrati", "120"],
            [*kosihy, "1", "2", "Adriana Benčaťová, Mgr.", "NEKA", "98"],
            [*svinna, "1", "1", "Eva Malá", "NEKA", "66"],
            [*svinna, "2", "2", "Ing. Veľký Ivan", "NEKA", "22"],
        ],
    }  # fmt: skip
    path = tmp_path / "OSO_201904_xlsx.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, rows in tables.items():
            table = write_xlsx(
                tmp_path / f"OSO_201904_{name}.xlsx",
                [*TITLE, *rows, [], ["Vysvetlivky"]],
            )
            z.write(table, table.name)
    return path


BY_PACKAGE = CandidateLists("susr-by", {"package": "p"})


def test_older_by_election_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    e = election("by-election", BY_PACKAGE)
    package = older_by_election_package(tmp_path)
    urls = {"package": PACKAGE_URL}
    read = lists.read(e, {"package": package}, tmp_path, urls=urls, term=TERM)
    assert read.partial
    assert read.withdrawn == {"starosta:502341#2"}
    # Seats where the obec's councillors are of one obvod; Lehota's, held
    # nowhere, in the one obvod of its council.
    assert read.seats == {"oz:502341/1": 2, "oz:517001/1": 1}
    data = candidates_json(monkeypatch, read)
    assert data["contests"] == [
        {"id": "starosta:502341", "kind": "starosta", "area": "502341", "vote": "new"},
        {"id": "oz:502341/1", "kind": "oz", "area": "502341", "obvod": 1,
         "seats": 2, "elected_only": True, "vote": "by"},
        {"id": "oz:517001/1", "kind": "oz", "area": "517001", "obvod": 1,
         "seats": 1, "uncontested": not_held("OSO_201904_tab0c.xlsx"), "vote": "by"},
        {"id": "oz:517755/1", "kind": "oz", "area": "517755", "obvod": 1,
         "elected_only": True, "vote": "by"},
        {"id": "oz:517755/2", "kind": "oz", "area": "517755", "obvod": 2,
         "elected_only": True, "vote": "by"},
    ]  # fmt: skip
    # Of a council its term elected in two obvody, the seat's is not known.
    split = lists.read(
        e, {"package": package}, tmp_path, urls=urls,
        term=lists.Term({"517001": [1, 2]}, {"517001": 5}),
    )  # fmt: skip
    assert "oz:517001/1" not in split.contests
    assert split.unplaced == ["517001: 1 seat(s) in one of the term council's 2 obvody"]
    # A council elected anew is not its term's: the packages of 2019–2022
    # do not count its obvody, so its seat is not placed.
    anew = lists.read(
        e, {"package": package}, tmp_path, urls=urls,
        term=lists.Term({"517001": [1]}, {"517001": 1}),
    )  # fmt: skip
    assert "oz:517001/1" not in anew.contests
    assert anew.unplaced == [
        "517001: 1 seat(s) of a new council, its obvody not counted"
    ]
    by_id = {c["id"]: c for c in data["candidacies"]}
    horvath = by_id["starosta:502341#1"]
    assert (horvath["age"], horvath["occupation"], horvath["title_before"]) == (
        None,
        "",
        "",
    )
    assert horvath["parties"] == ["Demokrati"]
    # The elected numbered in the order elected, the titles told apart.
    adriana = by_id["oz:502341/1#2"]
    assert (adriana["title_before"], adriana["first_name"], adriana["surname"]) == (
        "Mgr.",
        "Adriana",
        "Benčaťová",
    )
    assert (adriana["parties"], adriana["independent"]) == ([], True)
    assert by_id["oz:517755/2#2"]["title_before"] == "Ing."
    # A mayoral candidate elected to the council is one person.
    assert by_id["oz:502341/1#1"]["person"] == horvath["person"]


def write_package(
    tmp_path: Path, prefix: str, tables: dict[str, list[list[str]]]
) -> Path:
    """Return a zip of ŠÚ SR's XLSX tables *tables*, named ``<prefix>_<id>``."""
    path = tmp_path / f"{prefix}_xlsx.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, rows in tables.items():
            table = write_xlsx(
                tmp_path / f"{prefix}_{name}.xlsx", [*TITLE, *rows, [], ["Vysvetlivky"]]
            )
            z.write(table, table.name)
    return path


TOPOLCANY = ["4", "Nitriansky kraj", "406", "Topoľčany", "406", "Topoľčany"]
ZVOLEN = ["6", "Banskobystrický kraj", "606", "Zvolen", "611", "Zvolen"]
R_SOBOTA = [
    "6",
    "Banskobystrický kraj",
    "604",
    "Rimavská Sobota",
    "609",
    "Rimavská Sobota",
]
BARDEJOV = ["7", "Prešovský kraj", "701", "Bardejov", "701", "Bardejov"]


def test_by_election_votes_of_real_packages(tmp_path: Path):
    """``Typ volieb`` names only the offices held, so a council elected anew
    is told by its seats: those of OSO202303 against the 2022 territorial
    division's (``council_seats``), of OSO_201904 against 2018's."""
    e = election("by-election", BY_PACKAGE)
    krusovce = [*TOPOLCANY, "556149", "Krušovce"]
    svinna = [*ZILINA, "517755", "Lietavská Svinná - Babkov"]
    package = write_package(tmp_path, "OSO202303_SK", {
        "tab0c": [BY_PARTIES, ["101", "Demokrati", "Demokrati"]],
        "tab0dd": [
            BY_UNITS,
            [*krusovce, "1", "1", "7", "Starosta a zastupiteľstvo"],
            [*svinna, "2", "2", "6", "Len zastupiteľstvo"],
            [*ZVOLEN, "518654", "Michalková", "1", "1", "3", "Nekonajú sa"],
        ],
        "tab0ad": [
            BY_MAYORS,
            [*krusovce, "1", "Ján", "Kováč", "", "50", "murár", "NEKA", ""],
        ],
        "tab0bd": [
            BY_MEMBERS,
            [*krusovce, "1", "1", "Eva", "Malá", "", "52", "účtovníčka", "NEKA", ""],
            [*svinna, "1", "2", "Kamil", "Barčiak", "", "42", "vodič", "NEKA", ""],
            [*svinna, "2", "1", "Ján", "Chobot", "Ing.", "40", "riaditeľ", "NEKA", ""],
        ],
    })  # fmt: skip
    # 2022: Krušovce 7 seats (all elected again in 2023), Lietavská
    # Svinná-Babkov 9 in two obvody (3 filled, the other 6 in 2023),
    # Michalková 3 (held nowhere, again in 2023).
    term = lists.Term(
        {"556149": [1], "517755": [1, 2], "518654": [1]},
        {"556149": 7, "517755": 9, "518654": 3},
    )
    urls = {"package": PACKAGE_URL}
    read = lists.read(e, {"package": package}, tmp_path, urls=urls, term=term)
    votes = {c: f.get("vote") for c, f in read.contests.items()}
    assert votes == {
        "starosta:556149": "new",
        "oz:556149/1": "new",
        "oz:517755/1": "by",
        "oz:517755/2": "by",
        # Its own one obvod, as the territorial division of 2023 counts it.
        "oz:518654/1": "new",
    }
    assert read.seats["oz:518654/1"] == 3
    hob = [*TOPOLCANY, "542938", "Horné Obdokovce"]
    older = write_package(tmp_path, "OSO_201904", {
        "tab0b": [BY_PARTIES, ["101", "Demokrati", "Demokrati"]],
        "tab0c": [
            OLDER_UNITS,
            [*hob, "2", "len zastupiteľstvo"],
            [*R_SOBOTA, "514683", "Dubno", "5", "starosta a zastupiteľstvo"],
            [*BARDEJOV, "519685", "Ondavka", "3", "nekonajú sa"],
        ],
        "tab0a": [
            OLDER_MAYORS,
            [*R_SOBOTA, "514683", "Dubno", "1", "Anton", "Horváth", "NEKA", ""],
        ],
        "tab06": [
            OLDER_ELECTED,
            [*hob, "1", "1", "Ivan Svoboda", "NEKA", "66"],
            [*hob, "2", "2", "Marián Kováčik", "NEKA", "22"],
            [*R_SOBOTA, "514683", "Dubno", "1", "1", "Peter Novák", "NEKA", "40"],
        ],
    })  # fmt: skip
    # 2018: Horné Obdokovce 9 seats in two obvody (7 filled, the other 2 in
    # 2019), Dubno and Ondavka 5 and 3, held nowhere.
    term = lists.Term(
        {"542938": [1, 2], "514683": [1], "519685": [1]},
        {"542938": 9, "514683": 5, "519685": 3},
    )
    read = lists.read(e, {"package": older}, tmp_path, urls=urls, term=term)
    votes = {c: f.get("vote") for c, f in read.contests.items()}
    assert votes == {
        "oz:542938/1": "by",
        "oz:542938/2": "by",
        "starosta:514683": "new",
        "oz:514683/1": "new",
    }
    # Ondavka's new council: the package does not count its obvody.
    assert read.unplaced == [
        "519685: 3 seat(s) of a new council, its obvody not counted"
    ]


SUPPLEMENT = """
[[contest]]
id = "starosta:502341"
source = "https://example.sk/kandidati-starosta.pdf"
date = 2019-03-14
[[contest.candidate]]
number = 1
first_name = "Anton"
surname = "Horváth"
age = 71
occupation = "roľník"
parties = ["Demokrati"]
[[contest.candidate]]
number = 2
title_before = "Mgr."
first_name = "Michaela"
surname = "Slováková"
age = 40
occupation = "učiteľka"
parties = []

[[contest]]
id = "oz:502341/1"
seats = 2
source = "https://example.sk/kandidati-oz.pdf"
date = 2019-03-14
[[contest.candidate]]
number = 1
title_before = "Mgr."
first_name = "Adriana"
surname = "Benčaťová"
age = 31
occupation = "učiteľka"
parties = []
[[contest.candidate]]
number = 2
first_name = "Anton"
surname = "Horváth"
age = 71
occupation = "roľník"
parties = ["Demokrati"]
[[contest.candidate]]
number = 3
first_name = "Peter"
surname = "Kováč"
age = 50
occupation = "murár"
parties = []
"""


def test_older_by_election_supplement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / lists.CURATED_FILE).write_text(SUPPLEMENT, encoding="utf-8")
    e = election("by-election", BY_PACKAGE)
    package = {"package": older_by_election_package(tmp_path)}
    read = lists.read(e, package, tmp_path, urls={"package": PACKAGE_URL}, term=TERM)
    # The package's withdrawal stays; the replaced council is listed whole.
    assert read.withdrawn == {"starosta:502341#2"}
    assert "elected_only" not in read.contests["oz:502341/1"]
    assert read.contests["oz:517755/1"] == {"elected_only": True, "vote": "by"}
    data = candidates_json(monkeypatch, read)
    by_id = {c["id"]: c for c in data["candidacies"]}
    assert [c for c in by_id if c.startswith("oz:502341/1")] == [
        "oz:502341/1#1",
        "oz:502341/1#2",
        "oz:502341/1#3",
    ]
    assert (by_id["oz:502341/1#3"]["age"], by_id["starosta:502341#2"]["age"]) == (
        50,
        40,
    )
    # Persons merge on the ages now known.
    assert by_id["oz:502341/1#2"]["person"] == by_id["starosta:502341#1"]["person"]
    # The contests the file does not have keep the package's lists.
    assert by_id["oz:517755/1#1"]["age"] is None


@pytest.mark.parametrize(
    ("old", "new", "error"),
    [
        ('first_name = "Adriana"', 'first_name = "Andrea"',
         r"oz:502341/1: elected councillor Adriana Benčaťová: not on the list"),
        ('first_name = "Peter"\nsurname = "Kováč"',
         'first_name = "Anton"\nsurname = "Horváth"',
         r"elected councillor Anton Horváth: on the list twice"),
        ('first_name = "Michaela"', 'first_name = "Mária"',
         r"starosta:502341: ballot number 2: Michaela Slováková in the package,"
         r" Mária Slováková on the list"),
        ("number = 2\ntitle_before", "number = 3\ntitle_before",
         r"ballot number 2 \(Michaela Slováková\): not on the list\n"
         r"  starosta:502341: ballot number 3 \(Michaela Slováková\): not in"),
        ('id = "oz:502341/1"', 'id = "oz:502342/1"',
         r"oz:502342/1: not a contest of the package"),
        ("seats = 2", "seats = 3", r"oz:502341/1: seats 3, the package's 2"),
    ],
)  # fmt: skip
def test_older_by_election_supplement_must_fit(
    tmp_path: Path, old: str, new: str, error: str
):
    text = SUPPLEMENT.replace(old, new, 1)
    (tmp_path / lists.CURATED_FILE).write_text(text, encoding="utf-8")
    e = election("by-election", BY_PACKAGE)
    package = older_by_election_package(tmp_path)
    with pytest.raises(cand.CandidatesError, match=r"does not fit the package"):
        lists.read(e, {"package": package}, tmp_path)
    with pytest.raises(cand.CandidatesError, match=error):
        lists.read(e, {"package": package}, tmp_path)


@pytest.mark.parametrize(
    ("old", "new", "error"),
    [
        ('source = "https://example.sk/kandidati-starosta.pdf"\n', "",
         r"contest\[0\]\.source: missing"),
        ("date = 2019-03-14\n", "", r"contest\[0\]\.date: missing"),
        ("date = 2019-03-14", "date = 2024-03-30",
         r"contest\[0\]\.date: 2024-03-30 is after the election"),
        ("https://example.sk/kandidati-starosta.pdf", "kandidati.pdf",
         r"contest\[0\]\.source: must be an absolute http"),
    ],
)  # fmt: skip
def test_supplement_names_its_sources(tmp_path: Path, old: str, new: str, error: str):
    text = SUPPLEMENT.replace(old, new, 1)
    (tmp_path / lists.CURATED_FILE).write_text(text, encoding="utf-8")
    e = election("by-election", BY_PACKAGE)
    with pytest.raises(config.ConfigError, match=error):
        lists.read(e, {"package": older_by_election_package(tmp_path)}, tmp_path)


def test_full_package_has_no_supplement(tmp_path: Path):
    (tmp_path / lists.CURATED_FILE).write_text(SUPPLEMENT, encoding="utf-8")
    e = election("by-election", BY_PACKAGE)
    with pytest.raises(cand.CandidatesError, match="lists every candidate in full"):
        lists.read(e, {"package": by_election_package(tmp_path)}, tmp_path)


def test_referendum_questions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    e = election("referendum", None, questions=("Prvá?", "Druhá?"))
    data = candidates_json(monkeypatch, lists.read(e, {}, tmp_path))
    assert data["contests"] == [
        {"id": "referendum:SK/1", "kind": "referendum", "area": "SK", "obvod": 1,
         "question": "Prvá?"},
        {"id": "referendum:SK/2", "kind": "referendum", "area": "SK", "obvod": 2,
         "question": "Druhá?"},
    ]  # fmt: skip
    assert data["candidacies"] == data["persons"] == []


EP = """
[[subject]]
number = 1
party = "Progresívne Slovensko"
[[subject]]
number = 2
party = "SMER"

[[contest]]
id = "ep:SK/1"
party = "Progresívne Slovensko"
[[contest.candidate]]
number = 1
first_name = "Ľudovít"
surname = "Ódor"
title_before = "Ing."
age = 47
occupation = "ekonóm"
residence = "Bratislava"
[[contest.candidate]]
number = 2
first_name = "Jana"
surname = "Nová"
age = 30
occupation = "právnička"
withdrawn = true
"""


def test_curated_european(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / lists.CURATED_FILE).write_text(EP, encoding="utf-8")
    fields = NRSR | {"seats": 15, "coalition_thresholds": (), "preferences": 2}
    e = election("european", CandidateLists("curated", {}), **fields)
    data = candidates_json(monkeypatch, lists.read(e, {}, tmp_path))
    party, first, second = data["contests"]
    assert party == {
        "id": "ep:SK",
        "kind": "ep",
        "area": "SK",
        "seats": 15,
        "subjects": [
            {"number": 1, "party": "Progresívne Slovensko", "candidates": 2},
            {"number": 2, "party": "SMER"},
        ],
        "threshold": 5.0,
        "preferences": 2,
        "quota": 3.0,
    }
    assert first["party"] == "Progresívne Slovensko"
    # A subject's list is a contest even before its candidates are known.
    assert second == {
        "id": "ep:SK/2", "kind": "ep", "area": "SK", "obvod": 2, "party": "SMER"
    }  # fmt: skip
    odor, nova = data["candidacies"]
    assert (odor["parties"], odor["residence"]) == (["Progresívne Slovensko"], "BA")
    assert "residence" not in nova and "residence_name" not in nova
    assert nova["withdrawn"]


BY_CURATED = """
[[contest]]
id = "oz:500011/2"
seats = 3
[[contest.candidate]]
number = 1
first_name = "Jana"
surname = "Nová"
age = 48
occupation = "učiteľka"
parties = []
[[contest]]
id = "zsk:4/7"
[[contest.candidate]]
number = 1
first_name = "Peter"
surname = "Malý"
age = 50
occupation = "lekár"
parties = ["Demokrati"]
residence = "Nitra"
"""


def test_curated_by_election(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / lists.CURATED_FILE).write_text(BY_CURATED, encoding="utf-8")
    e = election("by-election", CandidateLists("curated", {}))
    read = lists.read(e, {}, tmp_path)
    assert read.partial and read.seats == {"oz:500011/2": 3}
    data = candidates_json(monkeypatch, read)
    assert [c["id"] for c in data["contests"]] == ["oz:500011/2", "zsk:4/7"]
    nova, maly = data["candidacies"]
    assert (nova["parties"], nova["independent"]) == ([], True)
    assert "residence" not in nova
    assert (maly["parties"], maly["residence"]) == (["Demokrati"], "500011")


ROUND2 = """
[[contest]]
id = "prezident:SK/2"
[[contest.candidate]]
number = 1
first_name = "Ivan"
surname = "Korčok"
age = 60
occupation = "diplomat"
"""


@pytest.mark.parametrize(
    ("kind", "text", "error"),
    [
        ("by-election", BY_CURATED.replace("oz:500011/2", "prezident:SK/1"),
         r"contest\[0\]\.id: prezident:SK/1: no \[\[contest\]\] of a by-election"),
        ("by-election", BY_CURATED.replace("oz:500011/2", "oz:5000"),
         r"contest\[0\]\.id: not a contest id"),
        ("by-election", BY_CURATED.replace("seats = 3", 'party = "X"'),
         r"contest\[0\]\.party: unknown key"),
        ("by-election", BY_CURATED.replace("parties = []\n", ""),
         r"candidate\[0\]\.parties: missing"),
        ("by-election", BY_CURATED + '[[subject]]\nnumber = 1\nparty = "X"\n',
         "only a party-list election has subjects"),
        ("european", EP.replace('party = "Progresívne Slovensko"\n[[contest.candidate]]',
                                'party = "SMER"\n[[contest.candidate]]'),
         r"contest\[0\]\.party: must be that of \[\[subject\]\] number 1"),
        ("european", EP.replace('id = "ep:SK/1"', 'id = "ep:SK/3"'),
         r"must be that of \[\[subject\]\] number 3"),
        ("european", EP.replace('id = "ep:SK/1"', 'id = "ep:SK"'),
         r"ep:SK: no \[\[contest\]\] of a european election"),
        ("european", EP.replace("residence =", "parties = []\nresidence ="),
         r"candidate\[0\]\.parties: unknown key"),
        ("european", EP.replace('number = 2\nparty = "SMER"', 'number = 1\nparty = "SMER"'),
         r"subject\[1\]\.number: 1 is listed twice"),
        ("presidential", ROUND2, "prezident:SK/2: the election has no second_round"),
    ],
)  # fmt: skip
def test_curated_rejects(tmp_path: Path, kind: str, text: str, error: str):
    path = tmp_path / lists.CURATED_FILE
    path.write_text(text, encoding="utf-8")
    with pytest.raises(config.ConfigError, match=error):
        config.load_candidates(path, election(kind, CandidateLists("curated", {})))


def test_regular_election_contests_held_nowhere():
    """ŠÚ SR's territorial division of a regular election: an obec where
    nothing is held has its mayor and council (in each obvod, the seats of
    one) uncontested, one of the council only its mayor."""
    out = cand.Lists([])
    rows = [
        ("514683", "Nekonajú sa", "1", "5"),
        ("505277", "Len zastupiteľstvo", "1", "7"),
        ("518654", "Starosta a zastupiteľstvo", "1", "3"),
        ("500011", "nekonajú sa", "2", "9"),
    ]
    statoffice.not_held(out, rows, "tab0c")
    why = cand.Uncontested("ŠÚ SR, tab0c: Typ volieb „nekonajú sa“", part="oso")
    assert out.not_held == {
        "starosta:514683": why,
        "oz:514683/1": why,
        "starosta:505277": cand.Uncontested(
            "ŠÚ SR, tab0c: Typ volieb „len zastupiteľstvo“", part="oso"
        ),
        "starosta:500011": why,
        "oz:500011/1": why,
        "oz:500011/2": why,
    }
    # Seats per obvod only where there is one; each council's in all.
    assert out.seats == {"oz:514683/1": 5}
    assert out.council_seats == {"514683": 5, "505277": 7, "518654": 3, "500011": 9}


UNCONTESTED = """\
[[contest]]
id = "starosta:520080"
source = "https://static.slov-lex.sk/pdf/prilohy/SK/ZZ/2025/262/annex.pdf"
title = "Rozhodnutie predsedu NR SR č. 262/2025 Z. z., príloha č. 1: Brezovec – starosta, poslanci"
"""


def test_uncontested_file_adds_what_the_package_does_not_tell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A by-election's mayor called beside council seats, both held
    nowhere (Brezovec 2026-03): the package tells the seats, the Speaker's
    decision the mayor; a contest that has candidates may not be one."""
    e = election("by-election", CandidateLists("susr-by", {"package": "p"}))
    package = {"package": by_election_package(tmp_path)}
    (tmp_path / lists.UNCONTESTED_FILE).write_text(UNCONTESTED, encoding="utf-8")
    read = lists.read(e, package, tmp_path, urls={"package": PACKAGE_URL})
    assert read.contests["starosta:520080"]["uncontested"] == {
        "source": "https://static.slov-lex.sk/pdf/prilohy/SK/ZZ/2025/262/annex.pdf",
        "title": "Rozhodnutie predsedu NR SR č. 262/2025 Z. z., príloha č. 1:"
        " Brezovec – starosta, poslanci",
    }
    held = UNCONTESTED.replace("520080", "502341")
    (tmp_path / lists.UNCONTESTED_FILE).write_text(held, encoding="utf-8")
    read = lists.read(e, package, tmp_path, urls={"package": PACKAGE_URL})
    with pytest.raises(cand.CandidatesError, match="starosta:502341: held nowhere"):
        candidates_json(monkeypatch, read)
    (tmp_path / lists.UNCONTESTED_FILE).write_text(
        UNCONTESTED.replace("starosta:520080", "zsk:4/1"), encoding="utf-8"
    )
    with pytest.raises(config.ConfigError, match="no mayor or council"):
        lists.read(e, package, tmp_path, urls={"package": PACKAGE_URL})
