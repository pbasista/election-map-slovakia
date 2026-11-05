import csv
import datetime as dt
import io
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from election_map_slovakia import national, results, tables

NOW = dt.datetime(2024, 3, 24, 12, tzinfo=results.TIMEZONE)
NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
# A country of two obce: 500011 of kraj 4 with two okrsky, 528595 of kraj 1
# with one.
OBCE = [
    {"code": "500011", "name": "Nitra", "okres": "403", "kraj": "4"},
    {"code": "528595", "name": "Staré Mesto", "okres": "101", "kraj": "1"},
]
OKRSKY = {"500011": 2, "528595": 1}
DIVISIONS = results.Divisions.of({"contests": [], "obce": OBCE}, ())
ELIGIBLE = "Počet zapísaných voličov"
VOTERS = "Počet zúčastnených voličov"
VALID = "Počet platných hlasov spolu"
# The same columns as other tables word them.
ELIGIBLE_ALIAS = "Počet voličov zapísaných v zoznamoch voličov"
VOTERS_ALIAS = "Počet voličov, ktorí sa zúčastnili na hlasovaní"
VALID_ALIAS = "Počet platných hlasov pre všetkých kandidátov"
SUBJECT = "Číslo politického subjektu"
NUMBER = "Poradie na hlasovacom lístku"
VOTES = "Počet platných hlasov"
YES = 'Počet hlasov "ÁNO"'
NO = 'Počet hlasov "NIE"'


def person(contest: str, number: int, name: str) -> dict:
    first, surname = name.split()
    return {
        "id": f"{contest}#{number}",
        "contest": contest,
        "number": number,
        "first_name": first,
        "surname": surname,
        "parties": [],
    }


def reference(contests: list[dict], candidacies: list[dict]) -> results.Reference:
    data = {
        "kraje": [
            {"code": "1", "name": "Bratislavský"},
            {"code": "4", "name": "Nitriansky"},
        ],
        "okresy": [],
        "obce": OBCE,
        "contests": contests,
        "candidacies": candidacies,
    }
    props = {o["code"]: {"zsk": 0} for o in OBCE}
    return results.reference(data, props, {}, {"Koalícia": 2}, parts=())


def expect(contests: list[dict]) -> results.Expect:
    """Return what the results of *contests* are checked against, compared with none."""
    return results.Expect.of({"contests": contests, "obce": OBCE}, (), {})


NAMES = ["Ján Novák", "Mária Kováčová", "Peter Horváth", "Eva Tóthová", "Juraj Varga"]
PRESIDENTIAL = [
    {"id": "prezident:SK/1", "kind": "prezident", "area": "SK", "obvod": 1},
    {
        "id": "prezident:SK/2",
        "kind": "prezident",
        "area": "SK",
        "obvod": 2,
        "day": "2024-04-06",
    },
]
PRESIDENTIAL_PERSONS = [
    *(person("prezident:SK/1", n, name) for n, name in enumerate(NAMES[:4], 1)),
    person("prezident:SK/2", 1, NAMES[0]),
    person("prezident:SK/2", 2, NAMES[1]),
]
REFERENDUM = [
    {
        "id": f"referendum:SK/{q}",
        "kind": "referendum",
        "area": "SK",
        "obvod": q,
        "question": f"Otázka {q}?",
    }
    for q in (1, 2)
]
PARTY = {
    "id": "nrsr:SK",
    "kind": "nrsr",
    "area": "SK",
    "seats": 5,
    "subjects": [
        {"number": 1, "party": "Strana A", "candidates": 4},
        {"number": 2, "party": "Koalícia", "candidates": 3},
        {"number": 3, "party": "Strana C", "candidates": 2},
    ],
    "threshold": 5.0,
    "coalition_thresholds": [[2, 7.0], [4, 10.0]],
    "preferences": 4,
    "quota": 3.0,
}
LISTS = [
    {"id": f"nrsr:SK/{p}", "kind": "nrsr", "area": "SK", "obvod": p, "party": party}
    for p, party in ((1, "Strana A"), (2, "Koalícia"), (3, "Strana C"))
]
LIST_PERSONS = [
    person(f"nrsr:SK/{p}", n, NAMES[n - 1])
    for p, size in ((1, 4), (2, 3), (3, 2))
    for n in range(1, size + 1)
]


def csv_bytes(rows: list[dict]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, list(rows[0]), quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


def xlsx_bytes(rows: list[dict] | dict[str, list[dict]]) -> bytes:
    """Return an XLSX table as ŠÚ SR's: a title and an empty row above it.

    *rows* a sheet's, or sheet name → its rows (NR SR 2020's sheets per
    subject).
    """
    sheets = rows if isinstance(rows, dict) else {"1": rows}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            f"<workbook {NS} xmlns:r="
            '"http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets>"
            + "".join(
                f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
                for i, name in enumerate(sheets, 1)
            )
            + "</sheets></workbook>",
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + "</Relationships>",
        )
        for i, sheet in enumerate(sheets.values(), 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheet))
    return out.getvalue()


def _sheet_xml(rows: list[dict]) -> str:
    header = list(rows[0])
    lines = [
        ["Tabuľka"],
        [],
        header,
        *([str(r.get(h, "")) for h in header] for r in rows),
    ]
    xml_rows = "".join(
        f'<row r="{i}">'
        + "".join(f'<c t="inlineStr"><is><t>{escape(v)}</t></is></c>' for v in line)
        + "</row>"
        for i, line in enumerate(lines, 1)
    )
    return f"<worksheet {NS}><sheetData>{xml_rows}</sheetData></worksheet>"


def package(path: Path, prefix: str, tables: dict, fmt: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for table, rows in tables.items():
            content = csv_bytes(rows) if fmt == "csv" else xlsx_bytes(rows)
            z.writestr(f"{prefix}_SK_{table}.{fmt}", content)
    return path


def turnout(
    rows: list[tuple[tuple[str, ...], int, int, int]], level: str, aliases: bool
) -> list[dict]:
    """Return turnout rows: unit, eligible, voters, valid."""
    eligible, voters, valid = (
        (ELIGIBLE_ALIAS, VOTERS_ALIAS, VALID_ALIAS)
        if aliases
        else (ELIGIBLE, VOTERS, VALID)
    )
    out = []
    for key, e, v, b in rows:
        row = unit(key, level)
        out.append(row | {eligible: e, voters: v, valid: b})
    return out


def unit(key: tuple[str, ...], level: str) -> dict:
    if level == "country":
        return {
            "Počet volebných okrskov": 3,
            "Počet potvrdených okrskových zápisníc": 3,
        }
    row = {"Kód obce": key[0]}
    if level == "okrsok":
        kraj = next(o["kraj"] for o in OBCE if o["code"] == key[0])
        row = {"Kód kraja": kraj} | row | {"Okrsok": key[1]}
    return row


TURNOUT = {
    "country": [((), 3000, 1800, 1750)],
    "obec": [(("500011",), 2000, 1200, 1170), (("528595",), 1000, 600, 580)],
    "okrsok": [
        (("500011", "1"), 1000, 600, 585),
        (("500011", "2"), 1000, 600, 585),
        (("528595", "1"), 1000, 600, 580),
    ],
}
TABLES = {"country": "tab01", "obec": "tab02d", "okrsok": "tab02e"}
VOTE_TABLES = {"country": "tab03a", "obec": "tab03e", "okrsok": "tab03f"}
# Votes of three candidates (parties) per unit, adding up to the valid.
VOTES_OF = {
    (): (1000, 700, 50),
    ("500011",): (700, 440, 30),
    ("528595",): (300, 260, 20),
    ("500011", "1"): (350, 220, 15),
    ("500011", "2"): (350, 220, 15),
    ("528595", "1"): (300, 260, 20),
}


def vote_tables(
    number: str, aliases: bool, extra: dict[int, dict] | None = None
) -> dict:
    tables = {}
    for level, rows in TURNOUT.items():
        tables[TABLES[level]] = turnout(rows, level, aliases)
        tables[VOTE_TABLES[level]] = [
            unit(key, level)
            | {number: n, VOTES: x}
            | ((extra or {}).get(n, {}) if not key else {})
            for key, *_ in rows
            for n, x in enumerate(VOTES_OF[key], 1)
        ]
    return tables


def written(
    tmp_path: Path, live: results.Live, contests: list[dict]
) -> dict[str, dict]:
    """Write *live*, check it and return its files."""
    out = tmp_path / "out"
    assert results.write(out, live, DIVISIONS, NOW, expect=expect(contests)) is not None
    return {
        p.relative_to(out).as_posix(): json.loads(p.read_bytes())
        for p in sorted(out.rglob("*.json"))
    }


def test_table_data_below_an_empty_row():
    """The XLSX tables of 2019 leave an empty row below the header; the data
    start after it and still end at the empty row above the notes."""
    rows = [
        ["Tabuľka 0c", ""],
        ["", ""],
        ["Kód obce", "Počet okrskov"],
        ["", ""],
        ["500011", "2"],
        ["528595", "1"],
        ["", ""],
        ["Poznámka: stav k 16. 3. 2019", ""],
    ]
    table = tables._table("t", rows)
    assert table.header == ("Kód obce", "Počet okrskov")
    assert table.rows == [
        {"Kód obce": "500011", "Počet okrskov": "2"},
        {"Kód obce": "528595", "Počet okrskov": "1"},
    ]


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_presidential_rounds(tmp_path: Path, fmt: str):
    ref = reference(PRESIDENTIAL, PRESIDENTIAL_PERSONS)
    # Round 1: no one elected, candidate 2 withdrew yet has the second most
    # votes; round 2: ŠÚ SR names the elected.
    round1 = vote_tables(
        NUMBER,
        fmt == "xlsx",
        {2: {"Poznámka": "X"}, 1: {"Poznámka": ""}, 3: {"Poznámka": ""}},
    )
    round2 = vote_tables(
        NUMBER,
        fmt == "xlsx",
        {1: {"Poznámka": "zvolený"}, 2: {"Poznámka": ""}, 3: {"Poznámka": ""}},
    )
    paths = [
        package(tmp_path / f"r{n}.zip", f"PREZ2024_kolo{n}", tables, fmt)
        for n, tables in ((1, round1), (2, round2))
    ]
    live, done = national.read_final(paths, ref)
    assert done == ["prez1", "prez2"]
    first = live.files["country"]["prezident:SK/1"]
    assert (first.eligible, first.voters, first.valid, first.counted) == (
        3000,
        1800,
        1750,
        (3, 3),
    )
    assert first.candidates == [
        (1, 1000, results.ADVANCED),
        (2, 700, results.WITHDRAWN),
        (3, 50, results.ADVANCED),
    ]
    assert first.areas == {
        "500011": (2000, 1200, 1170, {1: 700, 2: 440, 3: 30}),
        "528595": (1000, 600, 580, {1: 300, 2: 260, 3: 20}),
    }
    second = live.files["country"]["prezident:SK/2"]
    assert [b[2] for b in second.candidates] == [1, None, None]
    assert second.filled == 1
    assert set(live.okrsky) == {"country/1", "country/4"}
    assert live.okrsky["country/4"]["prezident:SK/1"]["500011/2"] == (
        1000,
        600,
        585,
        {1: 350, 2: 220, 3: 15},
    )
    merged = results.finalize(live, done, ref.sources)
    assert merged.phase == "final"
    files = written(tmp_path, merged, PRESIDENTIAL)
    assert set(files) == {
        "status.json",
        "country.json",
        "okrsky/country/1.json",
        "okrsky/country/4.json",
    }
    assert set(files["status.json"]["source"]) == {"prez1", "prez2"}


def test_round_one_alone_leaves_the_election_partial(tmp_path: Path):
    ref = reference(PRESIDENTIAL, PRESIDENTIAL_PERSONS)
    path = package(
        tmp_path / "r1.zip", "PREZ2024_kolo1", vote_tables(NUMBER, False), "csv"
    )
    live, done = national.read_final([path], ref)
    merged = results.finalize(live, done, ref.sources)
    assert merged.phase == "partial"
    assert merged.source["prez2"]["counted"] is None
    written(tmp_path, merged, PRESIDENTIAL)


def referendum_tables(voters: int, aliases: bool) -> dict:
    """Two questions; the obce and okrsky answer as the country, scaled."""
    answers = {1: (1200, 500), 2: (700, 900)}
    tables = {}
    for level, rows in TURNOUT.items():
        tables[TABLES[level]] = [
            r | {VOTERS if not aliases else VOTERS_ALIAS: voters * e // 3000}
            for r, (_, e, _, _) in zip(turnout(rows, level, aliases), rows, strict=True)
        ]
        tables[VOTE_TABLES[level]] = [
            unit(key, level)
            | {"Číslo otázky": q, YES: yes * e // 3000, NO: no * e // 3000}
            for key, e, *_ in rows
            for q, (yes, no) in answers.items()
        ]
    return tables


def test_referendum_valid_and_its_winners(tmp_path: Path):
    ref = reference(REFERENDUM, [])
    path = package(
        tmp_path / "ref.zip", "REF2023", referendum_tables(1800, False), "csv"
    )
    live, done = national.read_final([path], ref)
    assert done == ["ref"]
    q1 = live.files["country"]["referendum:SK/1"]
    assert (q1.eligible, q1.voters, q1.valid) == (3000, 1800, 1700)
    assert q1.candidates == [(1, 1200, 1), (2, 500, None)]
    q2 = live.files["country"]["referendum:SK/2"]
    assert q2.candidates == [(1, 700, None), (2, 900, 1)]
    assert q2.areas["528595"] == (1000, 600, 533, {1: 233, 2: 300})
    assert live.okrsky["country/1"]["referendum:SK/1"]["528595/1"] == (
        1000,
        600,
        566,
        {1: 400, 2: 166},
    )
    written(tmp_path, results.finalize(live, done, ref.sources), REFERENDUM)


def test_referendum_without_quorum_has_no_winner(tmp_path: Path):
    ref = reference(REFERENDUM, [])
    path = package(
        tmp_path / "ref.zip", "REF2023", referendum_tables(1400, True), "xlsx"
    )
    live, _ = national.read_final([path], ref)
    for q in (1, 2):
        record = live.files["country"][f"referendum:SK/{q}"]
        assert record.voters == 1400
        assert all(b[2] is None for b in record.candidates)


def party_tables(fmt: str) -> dict:
    xlsx = fmt == "xlsx"
    seats = {1: 3, 2: 2, 3: 0}
    # As in 2023 and 2024, a party without seats has no figure of seats, nor
    # its persons a place after the preference votes.
    tables = vote_tables(
        SUBJECT,
        xlsx,
        None
        if xlsx
        else {n: {"Počet získaných mandátov": s or ""} for n, s in seats.items()},
    )
    # Persons: party → (position, preference votes, place after them).
    lists = {
        1: [(1, 300, 2), (2, 50, 3), (3, 400, 1), (4, 10, 4)],
        2: [(1, 100, 1), (2, 20, 3), (3, 30, 2)],
        3: [(1, 5, None), (2, 3, None)],
    }
    tables["tab07a"] = [
        {SUBJECT: p, NUMBER: n, "Počet platných prednostných hlasov": x}
        | (
            {}
            if xlsx
            else {"Poradie po zohľadnení prednostného hlasovania": rank or ""}
        )
        for p, persons in lists.items()
        for n, x, rank in persons
    ]
    tables["tab07e"] = [
        {
            "Kód obce": code,
            SUBJECT: 1,
            NUMBER: n,
            "Počet platných prednostných hlasov": x,
        }
        for code, prefs in (
            ("500011", (200, 30, 300, 5)),
            ("528595", (100, 20, 100, 5)),
        )
        for n, x in enumerate(prefs, 1)
    ]
    # Per okrsok: party 1's in every okrsok, adding up to its obce's above;
    # party 2's only in 528595's, though it has votes in 500011's too.
    tables["tab07f"] = [
        {
            "Kód kraja": kraj,
            "Kód obce": code,
            "Okrsok": okrsok,
            SUBJECT: party,
            NUMBER: n,
            "Počet platných prednostných hlasov": x,
        }
        for kraj, code, okrsok, party, prefs in (
            ("4", "500011", "1", 1, (100, 0, 150, 5)),
            ("4", "500011", "2", 1, (100, 30, 150, 0)),
            ("1", "528595", "1", 1, (100, 20, 100, 5)),
            ("1", "528595", "1", 2, (7, 1, 0)),
        )
        for n, x in enumerate(prefs, 1)
    ]
    if xlsx:
        # Seats and the elected of their own tables.
        tables["tab04"] = [
            {SUBJECT: n, "Pridelené mandáty spolu": s} for n, s in seats.items()
        ]
        tables["tab06"] = [
            {SUBJECT: p, NUMBER: n}
            for p, ns in ((1, (1, 2, 3)), (2, (1, 3)))
            for n in ns
        ]
    return tables


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_party_lists(tmp_path: Path, fmt: str):
    contests = [PARTY, *LISTS]
    ref = reference(contests, LIST_PERSONS)
    path = package(tmp_path / "nrsr.zip", "NRSR2023", party_tables(fmt), fmt)
    live, done = national.read_final([path], ref, log=lambda _: None)
    assert done == ["nrsr"]
    party = live.files["country"]["nrsr:SK"]
    assert (party.seats, party.filled, party.valid) == (5, 5, 1750)
    assert party.won == {1: 3, 2: 2}
    assert party.candidates == [(1, 1000, 1), (2, 700, 1), (3, 50, None)]
    assert party.areas["528595"] == (1000, 600, 580, {1: 300, 2: 260, 3: 20})
    first = live.files["list/1"]["nrsr:SK/1"]
    assert (first.valid, first.seats, first.filled) == (1000, 3, 3)
    assert first.candidates == [(1, 300, 1), (2, 50, 1), (3, 400, 1), (4, 10, 0)]
    assert first.areas == {
        "500011": (2000, 1200, 700, {1: 200, 2: 30, 3: 300, 4: 5}),
        "528595": (1000, 600, 300, {1: 100, 2: 20, 3: 100, 4: 5}),
    }
    second = live.files["list/2"]["nrsr:SK/2"]
    assert second.candidates == [(1, 100, 1), (2, 20, 0), (3, 30, 1)]
    assert second.areas is None
    third = live.files["list/3"]["nrsr:SK/3"]
    assert [b[2] for b in third.candidates] == [None, None]
    assert "nrsr:SK/1" not in live.okrsky["country/4"]
    # An okrsok's list has the persons with votes only; party 2's okrsky of
    # 500011, where it has votes but the table none of its persons, none.
    assert live.okrsky["list/1/4"]["nrsr:SK/1"] == {
        "500011/1": (1000, 600, 350, {1: 100, 3: 150, 4: 5}),
        "500011/2": (1000, 600, 350, {1: 100, 2: 30, 3: 150}),
    }
    assert live.okrsky["list/1/1"]["nrsr:SK/1"] == {
        "528595/1": (1000, 600, 300, {1: 100, 2: 20, 3: 100, 4: 5})
    }
    assert live.okrsky["list/2/1"]["nrsr:SK/2"] == {
        "528595/1": (1000, 600, 260, {1: 7, 2: 1})
    }
    assert "list/2/4" not in live.okrsky
    assert not any(path.startswith("list/3/") for path in live.okrsky)
    files = written(tmp_path, results.finalize(live, done, ref.sources), contests)
    assert files["country.json"]["contests"]["nrsr:SK"]["won"] == {"1": 3, "2": 2}
    # A list's figures carry its persons' preference votes summed.
    assert files["okrsky/list/1/1.json"] == {
        "contests": {"nrsr:SK/1": {"528595/1": [1000, 600, 300, {"1": 100, "2": 20, "3": 100, "4": 5}, 225]}},
        "units": {},
        "past": {},
    }  # fmt: skip
    first_written = files["list/1.json"]["contests"]["nrsr:SK/1"]
    assert first_written["preferences"] == 760
    assert first_written["areas"]["500011"] == [2000, 1200, 700, {"1": 200, "2": 30, "3": 300, "4": 5}, 535]  # fmt: skip
    assert first_written["units"]["kraj"]["1"][4] == 225
    assert set(files) == {
        "status.json",
        "country.json",
        "list/1.json",
        "list/2.json",
        "list/3.json",
        "okrsky/country/1.json",
        "okrsky/country/4.json",
        "okrsky/list/1/1.json",
        "okrsky/list/1/4.json",
        "okrsky/list/2/1.json",
    }


def test_party_lists_of_the_older_xlsx_layout(tmp_path: Path):
    """EP 2019's turnout columns per obec and okrsok, and NR SR 2020's wide
    preference tables: a sheet per subject, of the obce (okrsky) where it
    has votes, with a column per person."""
    contests = [PARTY, *LISTS]
    ref = reference(contests, LIST_PERSONS)
    tables = party_tables("xlsx")
    for table in ("tab02d", "tab02e"):
        for row in tables[table]:
            row["Počet vydaných obálok"] = row.pop(VOTERS_ALIAS)
            row["Počet platných hlasov"] = row.pop(VALID_ALIAS)
    units = {
        "Kód kraja": "1",
        "Názov kraja": "Bratislavský kraj",
        "Kód obce": "528595",
        "Názov obce": "Bratislava - Staré Mesto",
    }
    tables["tab07e"] = {
        "NRSR_2020_SK_tab07e_PS1": [
            {"Kód obce": "500011", "1. Ján Novák": 200, "2. Mária Kováčová": 30,
             "3. Peter Horváth": 300, "4. Eva Tóthová": 5},
            units | {"1. Ján Novák": 100, "2. Mária Kováčová": 20,
                     "3. Peter Horváth": 100, "4. Eva Tóthová": 5},
        ],
        "NRSR_2020_SK_tab07e_PS2": [
            units | {"1. Ján Novák": 7, "2. Mária Kováčová": 1,
                     "3. Peter Horváth": 0},
        ],
    }  # fmt: skip
    person = ("1. Ján Novák", "2. Mária Kováčová", "3. Peter Horváth", "4. Eva Tóthová")
    tables["tab07f"] = {
        "NRSR_2020_SK_tab07f_PS1": [
            {"Kód obce": code, "Okrsok": okrsok} | dict(zip(person, prefs))
            for code, okrsok, prefs in (
                ("500011", "1", (100, 0, 150, 5)),
                ("500011", "2", (100, 30, 150, 0)),
                ("528595", "1", (100, 20, 100, 5)),
            )
        ],
        "NRSR_2020_SK_tab07f_PS2": [
            units | {"Okrsok": "1"} | dict(zip(person, (7, 1, 0)))
        ],
    }
    path = package(tmp_path / "nrsr.zip", "NRSR_2020", tables, "xlsx")
    live, done = national.read_final([path], ref, log=lambda _: None)
    party = live.files["country"]["nrsr:SK"]
    assert party.areas["528595"] == (1000, 600, 580, {1: 300, 2: 260, 3: 20})
    assert live.files["list/1"]["nrsr:SK/1"].areas == {
        "500011": (2000, 1200, 700, {1: 200, 2: 30, 3: 300, 4: 5}),
        "528595": (1000, 600, 300, {1: 100, 2: 20, 3: 100, 4: 5}),
    }
    assert live.files["list/2"]["nrsr:SK/2"].areas == {
        "528595": (1000, 600, 260, {1: 7, 2: 1, 3: 0})
    }
    assert live.files["list/3"]["nrsr:SK/3"].areas is None
    assert live.okrsky["list/1/4"]["nrsr:SK/1"] == {
        "500011/1": (1000, 600, 350, {1: 100, 3: 150, 4: 5}),
        "500011/2": (1000, 600, 350, {1: 100, 2: 30, 3: 150}),
    }
    assert live.okrsky["list/2/1"]["nrsr:SK/2"] == {
        "528595/1": (1000, 600, 260, {1: 7, 2: 1})
    }
    assert "list/2/4" not in live.okrsky
    written(tmp_path, results.finalize(live, done, ref.sources), contests)


def test_a_table_streams_row_by_row(tmp_path: Path):
    """A CSV file in the Windows code page; an XLSX file's every sheet."""
    path = tmp_path / "t.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "EP2024_SK_tab07f.csv",
            '"Kód obce";"Názov obce"\r\n"528595";"Staré Mesto"\r\n\r\n"x";"y"\r\n'.encode(
                "cp1250"
            ),
        )
        z.writestr(
            "NRSR_2020_SK_tab07e.xlsx",
            xlsx_bytes(
                {
                    "PS1": [{"Kód obce": "500011", "1. Ján Novák": "4"}],
                    "PS2": [{"Kód obce": "528595", "1. Eva Tóthová": "2"}],
                }
            ),
        )
    package = tables.open_package([path], results.TIMEZONE)
    # A stream's rows are read before the next stream is asked for.
    streams = package.stream("tab07f")
    csv_stream = next(streams)
    assert (csv_stream.header, csv_stream.sheet) == (("Kód obce", "Názov obce"), "")
    assert list(csv_stream.rows()) == [["528595", "Staré Mesto"]]
    assert next(streams, None) is None
    sheets = [
        (s.sheet, s.header[1], list(s.cells(1, 0))) for s in package.stream("tab07e")
    ]
    assert sheets == [
        ("PS1", "1. Ján Novák", [["4", "500011"]]),
        ("PS2", "1. Eva Tóthová", [["2", "528595"]]),
    ]


def test_a_missing_column_names_the_table_and_its_columns(tmp_path: Path):
    ref = reference([PARTY, *LISTS], LIST_PERSONS)
    tables = party_tables("csv")
    for row in tables["tab02d"]:
        row["Počet obyvateľov"] = row.pop(VOTERS)
    path = package(tmp_path / "nrsr.zip", "NRSR2023", tables, "csv")
    with pytest.raises(
        results.ResultsError,
        match="tab02d.csv: no column .*Počet zúčastnených voličov.* it has Kód obce",
    ):
        national.read_final([path], ref)


def test_check_holds_a_list_to_its_preferences(tmp_path: Path):
    contests = [PARTY, *LISTS]
    live = results.Live("final", results.no_sources({"nrsr"}))
    record = results.Record(
        "final",
        (3, 3),
        3000,
        1800,
        100,
        1,
        1,
        [(1, 100, 1), (2, 100, 0), (3, 100, 0), (4, 100, 0), (5, 1, 0)],
    )
    live.add("list/1", "nrsr:SK/1", record)
    out = tmp_path / "out"
    results.write(out, live, DIVISIONS, NOW)
    assert results.check(out, expect(contests)) == [
        "list/1: nrsr:SK/1: votes beyond the valid ballots and 4 preferences:"
        " the contest (100 votes at most, 401 in all, 100 valid)"
    ]
    record.candidates[-1] = (5, 0, 0)
    results.write(out, live, DIVISIONS, NOW)
    assert results.check(out, expect(contests)) == []


FAKES = {
    "presidential": (PRESIDENTIAL, PRESIDENTIAL_PERSONS),
    "referendum": (REFERENDUM, []),
    "parliament": ([PARTY, *LISTS], LIST_PERSONS),
}


@pytest.mark.parametrize("kind", sorted(FAKES))
def test_fakes_keep_the_contract_at_every_stage(tmp_path: Path, kind: str):
    contests, persons = FAKES[kind]
    ref = reference(contests, persons)
    day = dt.date(2024, 3, 23)
    for stage in results.STAGES:
        live = national.fake(ref, stage, day, 0, OKRSKY)
        out = tmp_path / stage
        assert results.write(out, live, DIVISIONS, NOW) is not None
        assert results.check(out, expect(contests)) == [], stage
        assert live.phase == {"none": "none", "final": "final"}.get(stage, "partial")
        assert set(live.source) == ref.sources
    final = national.fake(ref, "final", day, 0, OKRSKY)
    records = final.records()
    assert all(r.status == "final" and r.areas for r in records.values())
    lists = {f"list/{p}/{k}" for p in (1, 2, 3) for k in (1, 4)}
    country = {"country/1", "country/4"}
    assert set(final.okrsky) == country | (lists if kind == "parliament" else set())
    if kind == "presidential":
        assert [b[2] for b in records["prezident:SK/1"].candidates].count(
            results.ADVANCED
        ) == 2
        assert [b[2] for b in records["prezident:SK/2"].candidates].count(1) == 1
        # Round 2's candidates are round 1's two best.
        advanced = {
            b[0]
            for b in records["prezident:SK/1"].candidates
            if b[2] == results.ADVANCED
        }
        assert advanced == {1, 2}
        assert final.source["prez1"]["time"].startswith("2024-03-24")
        assert final.source["prez2"]["time"].startswith("2024-04-07")
    if kind == "referendum":
        last = records["referendum:SK/2"]
        assert 2 * (last.voters or 0) < (last.eligible or 0)
        assert all(b[2] is None for b in last.candidates)
    if kind == "parliament":
        party = records["nrsr:SK"]
        assert sum((party.won or {}).values()) == party.filled == 5
        for p, seats in (party.won or {}).items():
            listed = records[f"nrsr:SK/{p}"]
            assert listed.seats == seats == listed.filled
            assert sum(1 for b in listed.candidates if b[2] == 1) == seats
        # A list's okrsky add up to its obec's figures and have the party's
        # votes there as their valid ones.
        for p in (1, 2, 3):
            contest = f"nrsr:SK/{p}"
            okrsky = {
                key: a
                for k in (1, 4)
                for key, a in final.okrsky[f"list/{p}/{k}"][contest].items()
            }
            party_okrsky = {
                key: a
                for k in (1, 4)
                for key, a in final.okrsky[f"country/{k}"]["nrsr:SK"].items()
            }
            assert {k: a[2] for k, a in okrsky.items()} == {
                k: a[3].get(p, 0) for k, a in party_okrsky.items()
            }
            obec = records[contest].areas["500011"]
            summed = results.sum_areas(
                a for k, a in okrsky.items() if k.startswith("500011/")
            )
            assert summed[:3] == obec[:3]
            assert {n: x for n, x in obec[3].items() if x} == summed[3]
