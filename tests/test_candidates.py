import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from election_map_slovakia import candidates as cand
from election_map_slovakia.candidates import Admin, Candidacy, Entry, Obec
from election_map_slovakia.config import Overrides

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
PARTY = (
    "Názov politickej strany, názvy politických strán tvoriacich koalíciu,"
    " nezávislý kandidát"
)


def write_xlsx(path: Path, rows: list[list[str]]) -> Path:
    xml_rows = "".join(
        f'<row r="{i}">'
        + "".join(f'<c t="inlineStr"><is><t>{escape(v)}</t></is></c>' for v in row)
        + "</row>"
        for i, row in enumerate(rows, 1)
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            f"<workbook {NS} xmlns:r="
            '"http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f"<worksheet {NS}><sheetData>{xml_rows}</sheetData></worksheet>",
        )
    return path


TITLE = [["Zoznam zaregistrovaných kandidátov"], ["Voľby  24. októbra 2026"]]


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Bratislava–Staré Mesto", "bratislava stare mesto"),
        ("Bratislava - Staré  Mesto", "bratislava stare mesto"),
        ("ĽUBOTÍN", "lubotin"),
        ("Nám. SNP", "nam snp"),
        ("Veľký Ďur", "velky dur"),
        ("Őrhalom", "orhalom"),
        ("Záhorie (vojenský obvod)", "zahorie vojensky obvod"),
    ],
)
def test_search_key(text: str, key: str):
    assert cand.search_key(text) == key


def test_municipal_layout_single_title_column(tmp_path: Path):
    path = write_xlsx(
        tmp_path / "oz.xlsx",
        [
            *TITLE,
            [
                "Okres",
                "Obec",
                "Volebný obvod",
                "Poradové      číslo kandidáta",
                "Meno",
                "Priezvisko",
                "Titul",
                "Vek",
                "Zamestnanie",
                PARTY,
                "Kod okresu",
            ],
            [
                "Košice okolie",
                "Bidovce",
                "2",
                "3",
                "Ján",
                "Novák",
                "Ing.  arch., PhD.",
                "41",
                "architekt",
                "Smer - sociálna demokracia; Zmena zdola, demokratická únia Slovenska",
                "806",
            ],
            [
                "Košice okolie",
                "Bidovce",
                "2",
                "4",
                "Eva",
                "Nová",
                "",
                "38",
                "učiteľka",
                "Nezávislý kandidát",
                "806",
            ],
            [],
            ["Poznámka: stav k 29. 9. 2026"],
        ],
    )
    first, second = cand.read_list("oz", path)
    assert (first.region, first.okres_code, first.obec) == (
        "Košice okolie",
        "806",
        "Bidovce",
    )
    assert (first.obvod, first.number, first.age) == (2, 3, 41)
    assert (first.title_before, first.title_after) == ("Ing. arch.", "PhD.")
    assert first.parties == [
        "Smer - sociálna demokracia",
        "Zmena zdola, demokratická únia Slovenska",
    ]
    assert not first.independent
    assert (second.title_before, second.title_after) == ("", "")
    assert second.parties == [] and second.independent


def test_regional_layout_split_title_columns(tmp_path: Path):
    path = write_xlsx(
        tmp_path / "zsk.xlsx",
        [
            *TITLE,
            [
                "Kraj",
                "Volebný obvod",
                "Poradové číslo kandidáta",
                "Meno",
                "Priezvisko",
                "Titul pred menom",
                "Titul za menom",
                "Vek",
                "Zamestnanie",
                "Obec TP kandidáta",
                PARTY,
            ],
            [
                "Bratislavský samosprávny kraj",
                "1",
                "8",
                "Katarína",
                "Holubová",
                "Ing.",
                "PhD., MBA",
                "69",
                "vodohospodár",
                "Bratislava - Staré Mesto",
                "Zmena zdola, demokratická únia Slovenska, Progresívne Slovensko",
            ],
        ],
    )
    known = {"Zmena zdola, demokratická únia Slovenska"}
    (entry,) = cand.read_list("zsk", path, known)
    assert (entry.title_before, entry.title_after) == ("Ing.", "PhD., MBA")
    assert entry.residence == "Bratislava - Staré Mesto"
    assert entry.parties == [
        "Zmena zdola, demokratická únia Slovenska",
        "Progresívne Slovensko",
    ]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Ing. PhD", ("Ing.", "PhD")),
        ("Mgr. MBA", ("Mgr.", "MBA")),
        ("Mgr., Bc.", ("Mgr. Bc.", "")),
        ("Ing., Mgr., MBA, LL.M.", ("Ing. Mgr.", "MBA, LL.M.")),
        ("Mgr. art., DiS. art.", ("Mgr. art.", "DiS. art.")),
        ("doc. PhDr., MPol., Ph. D.", ("doc. PhDr.", "MPol., Ph. D.")),
        ("Mgr., LL. M", ("Mgr.", "LL. M")),
        ("Bc., M. A.", ("Bc.", "M. A.")),
        ("PhDr.Ing. , MBA", ("PhDr. Ing.", "MBA")),
        ("Mgr., LL.M.Dr.h.c.", ("Mgr. Dr.h.c.", "LL.M.")),
        ("B.S.B.A.", ("", "B.S.B.A.")),
        ("Ing., PhD., ING-PAED IGIP", ("Ing.", "PhD., ING-PAED IGIP")),
        ("Dr. med. dent.", ("Dr. med. dent.", "")),
        ("", ("", "")),
    ],
)
def test_single_title_column_classified_per_title(
    title: str, expected: tuple[str, str]
):
    assert cand.split_title(title) == expected


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Bratislava - Staré Mesto", "Bratislava-Staré Mesto"),
        ("Košice okolie", "Košice - okolie"),
        ("Nová  Ves nad Žitavou", "Nová Ves nad Žitavou"),
        (" Kecerovce ", "Kecerovce"),
        ("Košice-Šaca", "Košice – Šaca"),
    ],
)
def test_name_key_equates_spacing_and_dashes(a: str, b: str):
    assert cand.name_key(a) == cand.name_key(b)


def test_name_key_keeps_diacritics_and_case():
    assert cand.name_key("Šaca") != cand.name_key("Saca")
    assert cand.name_key("Nové Mesto") != cand.name_key("nové mesto")


def test_person_name_key():
    assert cand.person_name_key(" Nováková - Kováčová ") == "nováková-kováčová"
    assert cand.person_name_key("Monika  Sofiya") == "monika sofiya"
    assert cand.person_name_key("Tóth") != cand.person_name_key("Toth")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A; B ;C", (["A", "B", "C"], False)),
        ("nezávislá kandidátka", ([], True)),
        ("NEZÁVISLÝ KANDIDÁT", ([], True)),
        (
            "Starostovia a nezávislí kandidáti",
            (["Starostovia a nezávislí kandidáti"], False),
        ),
    ],
)
def test_parse_parties_semicolon(text: str, expected: tuple[list[str], bool]):
    assert cand.parse_parties(text, ";") == expected


def test_parse_parties_comma_splits_unknown_names():
    assert cand.parse_parties("Zmena zdola, demokratická únia Slovenska", ",") == (
        ["Zmena zdola", "demokratická únia Slovenska"],
        False,
    )


ADMIN = Admin(
    kraje={"1": "Bratislavský"},
    okresy={"101": ("Bratislava I", "1"), "108": ("Senec", "1")},
    obce={
        "BA": Obec("BA", "Bratislava", None, "1"),
        "528595": Obec("528595", "Bratislava-Staré Mesto", "101", "1", "BA"),
        "508063": Obec("508063", "Senec", "108", "1"),
    },
)


def candidacy(
    contest: str, number: int, obec: str, first="Ján", surname="Novák", age=50
) -> Candidacy:
    kind, _, rest = contest.partition(":")
    area, _, obvod = rest.partition("/")
    entry = Entry(
        kind=kind,
        source="test",
        region="",
        okres_code="",
        obec="",
        obvod=int(obvod) if obvod else None,
        number=number,
        first_name=first,
        surname=surname,
        title_before="",
        title_after="",
        age=age,
        occupation="",
        parties=[],
        independent=False,
        residence="",
    )
    return Candidacy(contest, kind, area, entry.obvod, entry, obec)


def overrides(merge=(), split=()) -> Overrides:
    return Overrides({}, {}, tuple(merge), tuple(split), {})


def people(cs: list[Candidacy]) -> set[frozenset[str]]:
    groups: dict[str, set[str]] = {}
    for c in cs:
        groups.setdefault(c.person, set()).add(c.id)
    return {frozenset(g) for g in groups.values()}


def test_merge_across_contests_and_city_districts():
    cs = [
        candidacy("starosta:528595", 1, "528595"),
        candidacy("oz:528595/2", 3, "528595"),
        candidacy("oz:BA/1", 7, "BA", first="JÁN "),
        candidacy("zsk:1/1", 5, "528595"),
        candidacy("oz:508063/1", 2, "508063"),  # namesake elsewhere
        candidacy("oz:528595/2", 4, "528595", age=51),
    ]
    persons, unmerged = cand.merge_persons(cs, ADMIN, overrides())
    assert unmerged == 0
    assert people(cs) == {
        frozenset({"starosta:528595#1", "oz:528595/2#3", "oz:BA/1#7", "zsk:1/1#5"}),
        frozenset({"oz:508063/1#2"}),
        frozenset({"oz:528595/2#4"}),
    }
    merged = next(p for p in persons if len(p.candidacies) == 4)
    assert merged.obec == "BA"


def test_namesakes_in_one_body_stay_apart():
    cs = [
        candidacy("oz:508063/1", 1, "508063"),
        candidacy("oz:508063/2", 1, "508063"),
        candidacy("starosta:508063", 2, "508063"),
    ]
    persons, unmerged = cand.merge_persons(cs, ADMIN, overrides())
    assert unmerged == 3
    assert len(persons) == 3
    assert len({p.id for p in persons}) == 3


def test_overrides_merge_and_split():
    cs = [
        candidacy("oz:508063/1", 1, "508063"),
        candidacy("oz:508063/1", 2, "508063"),
        candidacy("starosta:508063", 2, "508063"),
        candidacy("zsk:1/3", 4, "508063", first="Peter"),
        candidacy("oz:528595/1", 9, "528595", first="Peter"),
    ]
    cand.merge_persons(
        cs,
        ADMIN,
        overrides(
            merge=[("starosta:508063#2", "oz:508063/1#2")],
            split=[("zsk:1/3#4",)],
        ),
    )
    assert people(cs) == {
        frozenset({"oz:508063/1#1"}),
        frozenset({"oz:508063/1#2", "starosta:508063#2"}),
        frozenset({"zsk:1/3#4"}),
        frozenset({"oz:528595/1#9"}),
    }


def test_override_naming_unknown_candidacy_fails():
    cs = [candidacy("oz:508063/1", 1, "508063")]
    with pytest.raises(cand.CandidatesError, match="no candidacy"):
        cand.merge_persons(cs, ADMIN, overrides(split=[("oz:508063/1#9",)]))


def test_person_ids_stable_across_unrelated_changes():
    a = [
        candidacy("oz:508063/1", 1, "508063"),
        candidacy("starosta:508063", 1, "508063"),
    ]
    b = [*a[:1], candidacy("oz:508063/1", 2, "508063", first="Eva")]
    cand.merge_persons(a, ADMIN, overrides())
    person = a[0].person
    cand.merge_persons(b, ADMIN, overrides())
    assert b[0].person == person


def entry(kind: str, region: str, number: int, **kw) -> Entry:
    fields = dict(
        kind=kind,
        source="test",
        region=region,
        okres_code="",
        obec="",
        obvod=None,
        number=number,
        first_name="Ján",
        surname="Novák",
        title_before="",
        title_after="",
        age=50,
        occupation="",
        parties=[],
        independent=False,
        residence="",
    )
    fields.update(kw)
    return Entry(**fields)


MATCH_ADMIN = Admin(
    kraje={"1": "Bratislavský", "8": "Košický"},
    okresy={"101": ("Bratislava I", "1"), "806": ("Košice - okolie", "8")},
    obce={
        "BA": Obec("BA", "Bratislava", None, "1"),
        "528595": Obec("528595", "Bratislava-Staré Mesto", "101", "1", "BA"),
        "521001": Obec("521001", "Selce", "806", "8"),
        "521002": Obec("521002", "Selce", "999", "8"),
    },
)


def test_match_names_cities_and_ambiguous_residence():
    entries = [
        entry("starosta", "Bratislava", 1, okres_code="100", obec="Bratislava"),
        entry(
            "oz",
            "Bratislava I",
            2,
            okres_code="101",
            obec="Bratislava - Staré  Mesto",
            obvod=1,
        ),
        entry("oz", "Košice okolie", 3, okres_code="806", obec="Selce", obvod=1),
        entry("zsk", "Košický samosprávny kraj", 4, obvod=1, residence="Selce"),
        entry(
            "zsk",
            "Bratislavský samosprávny kraj",
            5,
            obvod=1,
            residence="Bratislava - Staré Mesto",
        ),
    ]
    cs, how = cand.match(entries, MATCH_ADMIN, overrides())
    assert {c.id: c.obec for c in cs} == {
        "starosta:BA#1": "BA",
        "oz:528595/1#2": "528595",
        "oz:521001/1#3": "521001",
        "zsk:1/1#5": "528595",
        "zsk:8/1#4": "521001",
    }
    assert how == {"name": 1, "municipal candidacy": 1}


def test_unmatched_rows_are_all_listed():
    entries = [
        entry("oz", "Bratislava I", 1, okres_code="101", obec="Petržalka", obvod=1),
        entry("oz", "Košice okolie", 1, okres_code="806", obec="Selce", obvod=1),
        entry(
            "zsk",
            "Košický samosprávny kraj",
            2,
            obvod=1,
            residence="Selce",
            first_name="Eva",
        ),
    ]
    with pytest.raises(cand.CandidatesError) as e:
        cand.match(entries, MATCH_ADMIN, overrides())
    assert "2 unmatched" in str(e.value)
    assert "'Petržalka'" in str(e.value) and "zsk:8/1#2" in str(e.value)
    fixed = Overrides(
        {"Bratislava I/Petržalka": "528595"}, {"zsk:8/1#2": "521002"}, (), (), {}
    )
    _, how = cand.match(entries, MATCH_ADMIN, fixed)
    assert how == {"override": 1}


def test_obvody_must_be_numbered_from_one():
    cs = [candidacy("oz:508063/1", 1, "508063"), candidacy("oz:508063/3", 1, "508063")]
    with pytest.raises(cand.CandidatesError, match=r"obvody \[1, 3\]"):
        cand.check_numbers(cs)


def test_duplicate_ballot_number_rejected():
    cs = [candidacy("oz:508063/1", 1, "508063"), candidacy("oz:508063/1", 1, "508063")]
    with pytest.raises(cand.CandidatesError, match="repeats"):
        cand.check_numbers(cs)
