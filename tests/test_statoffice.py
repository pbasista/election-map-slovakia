import datetime as dt
import zipfile
from pathlib import Path

import pytest

from election_map_slovakia import candidates, results, statoffice
from election_map_slovakia.candidates import Admin, Obec
from election_map_slovakia.config import Overrides
from election_map_slovakia.statoffice import Package, StatOfficeError

# A small country: Bratislava (582000) of three districts in two city council
# obvody, Nitra (500011) of two obvody, Krušovce (556149) without a result.
OSO = {
    "tab0dd": [
        "1|Bratislavský kraj|100|Bratislava mesto|100|Bratislava|582000|Bratislava|2|5|4|1",
        "1|Bratislavský kraj|101|Bratislava|101|Bratislava I|528595|Bratislava - Staré Mesto|1|2|3|1",
        "1|Bratislavský kraj|102|Bratislava|102|Bratislava II|529320|Bratislava - Ružinov|1|1|3|1",
        "1|Bratislavský kraj|102|Bratislava|102|Bratislava II|529494|Bratislava - Vrakuňa|1|1|3|1",
        "4|Nitriansky kraj|403|Nitra|403|Nitra|500011|Nitra|2|2|2|1",
        "4|Nitriansky kraj|406|Topoľčany|406|Topoľčany|556149|Krušovce|1|1|7|1",
    ],
    "tab0ad": [
        "582000|1|Matúš|Vallo|Ing. arch.|45|primátor|124,147|",
        "582000|2|Ján|Novák||50|úradník|001|X",
        "500011|1|Erik|Blaško||49|šofér|116|",
        "500011|2|Marek|Hattas|Mgr., PhD.|35|primátor|148|",
        "556149|1|Róbert|Lukačovič||51|dôchodca|001|",
    ],
    "tab0bd": [
        "582000|1|1|Anna|Malá||40|lekárka|001|",
        "582000|1|2|Peter|Veľký||41|učiteľ|124|",
        "582000|1|3|Eva|Stredná||42|právnička|147|",
        "500011|1|1|Juraj|Dunčič||30|podnikateľ|106,135|",
        "500011|1|2|Miroslav|Gut|Ing.|55|technik|001|",
        # An occupation broken over two lines, as in the real tables.
        "500011|1|3|Norbert|Fukáč||42|obsluha drevoobrábacích ",
        "strojov|145|X",
        "500011|2|1|Mária|Nová||60|dôchodkyňa|001|",
        "556149|1|1|Vladimír|Babinec||46|podnikateľ|001|",
    ],
    "tab0c": [
        "106|HLAS - sociálna demokracia|Hlas - sociálna demokracia",
        "116|NÁRODNÁ KOALÍCIA / NEZÁVISLÍ KANDIDÁTI|NK/NEKA",
        "124|Progresívne Slovensko|Progresívne Slovensko",
        "135|SME RODINA|SME RODINA",
        "145|SZÖVETSÉG - Magyarok. Nemzetiségek. Regiók. | ALIANCIA - Maďari. Národnosti. Regióny|SZÖVETSÉG - ALIANCIA",
        "147|Team Bratislava|Team Bratislava",
        "148|Tím Kraj Nitra - Združenie kandidátov Nitrianskeho kraja|Tím Kraj Nitra",
    ],
    "tab02ad": [
        "582000|1|2|2",
        "582000|2|2|2",
        "500011|1|1|1",
        "500011|2|1|1",
        "556149|1|7|0",
    ],
    "tab02bf": [
        "528595|1|1|1000|400|40,00|400|100,00|390|395",
        "528595|1|2|800|300|37,50|300|100,00|290|295",
        "529320|1|1|900|500|55,55|500|100,00|490|495",
        "529494|1|1|700|200|28,57|200|100,00|190|195",
        "500011|1|1|805|363|45,09|363|100,00|356|360",
        "500011|2|2|1116|376|33,69|376|100,00|362|374",
        # The city's okrsky: by its council obvod and the district's number.
        # 1/1 has the voters of Staré Mesto's 1; 1/2 voters other than
        # Staré Mesto's 2 (joined by number); 2/1 twice, Ružinov's and
        # Vrakuňa's; 2/9 none.
        "582000|1|1|1000|400|40,00|400|100,00|380|390",
        "582000|1|2|801|300|37,45|300|100,00|280|290",
        "582000|2|1|900|500|55,55|500|100,00|480|490",
        "582000|2|1|700|200|28,57|200|100,00|180|190",
        "582000|2|9|50|10|20,00|10|100,00|10|10",
    ],
    "tab05f": [
        "500011|1|1|1|100|27,77|",
        "500011|1|1|2|260|72,22|1",
        "500011|2|2|1|174|46,52|",
        "500011|2|2|2|200|53,47|1",
        "582000|1|1|1|300|76,92|1",
        "582000|1|1|2|90|23,07|X",
        "582000|1|2|1|200|68,96|1",
        "582000|1|2|2|90|31,03|X",
        # The rows of okrsky 2/1 come in no fixed order: told apart by shares.
        "582000|2|1|1|100|52,63|1",
        "582000|2|1|1|400|81,63|1",
        "582000|2|1|2|90|18,36|X",
        "582000|2|1|2|90|47,36|X",
        "582000|2|9|1|10|100,00|1",
        "582000|2|9|2|0|0,00|X",
    ],
    "tab08f": [
        "500011|1|1|1|200|56,17|1",
        "500011|1|1|2|150|42,13|0",
        "500011|1|1|3|6|1,68|X",
        "500011|2|2|1|300|100,00|1",
        "582000|1|1|1|200|44,44|1",
        "582000|1|1|2|150|33,33|1",
        "582000|1|1|3|100|22,22|0",
        "582000|1|2|1|150|50,00|1",
        "582000|1|2|2|100|33,33|1",
        "582000|1|2|3|50|16,66|0",
    ],
}
OSK = {
    "tab0dc": [
        "1|Bratislavský kraj|101|Volebný obvod č. 1|528595|Bratislava - Staré Mesto|2",
        "1|Bratislavský kraj|102|Volebný obvod č. 2|529320|Bratislava - Ružinov|1",
        "1|Bratislavský kraj|102|Volebný obvod č. 2|529494|Bratislava - Vrakuňa|1",
        "4|Nitriansky kraj|401|Volebný obvod č. 1|500011|Nitra|2",
        "4|Nitriansky kraj|405|Volebný obvod č. 5|556149|Krušovce|1",
    ],
    "tab0a": [
        "1|1|Juraj|Droba|Mgr., MBA, MA|51|predseda|Bratislava - Staré Mesto|128|",
        "1|2|Ivan|Bošňák|Ing.|53|manažér|Bratislava - Ružinov|128,147|X",
        "4|1|Branislav|Becík|Ing.|50|predseda|Nitra|001|",
    ],
    "tab0b": [
        "101|1|Zuzana|Aufrichtová|Ing. arch.|47|starostka, urbanistka|Bratislava - Staré Mesto|147|",
        "401|1|Marek|Hattas|Mgr., PhD.|35|primátor|Nitra|148|",
    ],
    "tab0c": [
        "128|Sloboda a Solidarita|SaS",
        "147|Team Bratislava|Team Bratislava",
        "148|Tím Kraj Nitra - Združenie kandidátov Nitrianskeho kraja|Tím Kraj Nitra",
    ],
    "tab02ab": ["101|3|3", "102|6|6", "401|5|5", "405|2|2"],
    "tab02bd": [
        "528595|1|1000|400|40,00|400|100,00|380|370",
        "528595|2|800|300|37,50|300|100,00|290|280",
        "500011|1|805|364|45,21|363|99,72|346|340",
        "500011|2|1116|376|33,69|374|99,46|356|346",
    ],
    "tab06d": [
        "528595|1|1|300|78,94|1",
        "528595|1|2|80|21,05|X",
        "528595|2|1|200|68,96|1",
        "528595|2|2|90|31,03|X",
        "500011|1|1|346|100,00|1",
        "500011|2|1|356|100,00|1",
    ],
    "tab09d": [
        "528595|1|1|370|100,00|1",
        "528595|2|1|280|100,00|1",
        "500011|1|1|340|100,00|1",
        "500011|2|1|346|100,00|1",
    ],
}


def package(tmp_path: Path, election: str, tables: dict[str, list[str]]) -> Package:
    """Write a 2022 package zip of *tables* (rows without header) and open it."""
    prefix = f"{election.upper()}2022_SK"
    path = tmp_path / f"{prefix}_csv.zip"
    with zipfile.ZipFile(path, "w") as z:
        for table, header in statoffice._TABLES[election].items():
            text = "\n".join(["|".join(header), *tables.get(table, [])]) + "\n"
            z.writestr(f"{prefix}_{table}.csv", text.encode("utf-8-sig"))
    return statoffice.open_package(path)


@pytest.fixture
def packages(tmp_path: Path) -> tuple[Package, Package]:
    return package(tmp_path, "oso", OSO), package(tmp_path, "osk", OSK)


def test_parse_table_mends_broken_lines_and_wide_columns():
    rows = statoffice.parse_table(
        "t", "A|B|C\n1|x \ny|2\n\n3|p|q|r\n", ("A", "B", "C"), wide="B"
    )
    assert rows == [{"A": "1", "B": "x  y", "C": "2"}, {"A": "3", "B": "p|q", "C": "r"}]
    with pytest.raises(StatOfficeError, match="4 fields"):
        statoffice.parse_table("t", "A|B|C\n3|p|q|r\n", ("A", "B", "C"))
    with pytest.raises(StatOfficeError, match="header"):
        statoffice.parse_table("t", "A|C\n", ("A", "B", "C"))
    with pytest.raises(StatOfficeError, match="incomplete"):
        statoffice.parse_table("t", "A|B|C\n1|2\n", ("A", "B", "C"))


def test_open_package_needs_every_table(tmp_path: Path):
    path = tmp_path / "OSK2022_SK_csv.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("OSK2022_SK_tab0a.csv", "|".join(statoffice._TABLES["osk"]["tab0a"]))
    with pytest.raises(StatOfficeError, match="no table"):
        statoffice.open_package(path)


def test_package_rows(packages: tuple[Package, Package]):
    oso, osk = packages
    assert (oso.election, osk.election) == ("oso", "osk")
    party = next(r for r in oso.rows("tab0c") if r["PS"] == "145")
    assert party["NPS"].endswith("Regiók. | ALIANCIA - Maďari. Národnosti. Regióny")
    assert party["SNPS"] == "SZÖVETSÉG - ALIANCIA"


def test_candidates_as_the_mv_sr_lists(packages: tuple[Package, Package]):
    lists = statoffice.read_candidates(*packages)
    by_name = {(e.kind, e.surname): e for e in lists.entries}
    vallo = by_name[("starosta", "Vallo")]
    assert (vallo.region, vallo.okres_code, vallo.obec, vallo.obvod) == (
        "Bratislava",
        "100",
        "Bratislava",
        None,
    )
    assert vallo.parties == ["Progresívne Slovensko", "Team Bratislava"]
    assert (vallo.title_before, vallo.title_after, vallo.residence) == (
        "Ing. arch.",
        "",
        "",
    )
    assert by_name[("starosta", "Novák")].independent
    assert by_name[("starosta", "Novák")].parties == []
    hattas = by_name[("starosta", "Hattas")]
    assert (hattas.title_before, hattas.title_after) == ("Mgr.", "PhD.")
    fukac = by_name[("oz", "Fukáč")]
    assert (fukac.obvod, fukac.number) == (1, 3)
    assert fukac.occupation == "obsluha drevoobrábacích strojov"
    assert fukac.parties == [
        "SZÖVETSÉG - Magyarok. Nemzetiségek. Regiók. | ALIANCIA - Maďari."
        " Národnosti. Regióny"
    ]
    droba = by_name[("predseda", "Droba")]
    assert (droba.region, droba.title_before, droba.title_after) == (
        "Bratislavský samosprávny kraj",
        "Mgr.",
        "MBA, MA",
    )
    assert droba.residence == "Bratislava - Staré Mesto"
    assert by_name[("zsk", "Aufrichtová")].obvod == 1
    assert lists.withdrawn == {
        "starosta:BA#2",
        "oz:500011/1#3",
        "predseda:1#2",
    }
    assert lists.seats == {
        "oz:BA/1": 2,
        "oz:BA/2": 2,
        "oz:500011/1": 1,
        "oz:500011/2": 1,
        "oz:556149/1": 7,
        "zsk:1/1": 3,
        "zsk:1/2": 6,
        "zsk:4/1": 5,
        "zsk:4/5": 2,
    }
    assert lists.zsk == {
        "528595": 1,
        "529320": 2,
        "529494": 2,
        "500011": 1,
        "556149": 5,
    }


def test_candidates_match_their_codes(packages: tuple[Package, Package]):
    admin = Admin(
        kraje={"1": "Bratislavský", "4": "Nitriansky"},
        okresy={
            "101": ("Bratislava I", "1"),
            "102": ("Bratislava II", "1"),
            "403": ("Nitra", "4"),
            "406": ("Topoľčany", "4"),
        },
        obce={
            "BA": Obec("BA", "Bratislava", None, "1"),
            "KE": Obec("KE", "Košice", None, "8"),
            "528595": Obec("528595", "Bratislava-Staré Mesto", "101", "1", "BA"),
            "529320": Obec("529320", "Bratislava-Ružinov", "102", "1", "BA"),
            "529494": Obec("529494", "Bratislava-Vrakuňa", "102", "1", "BA"),
            "500011": Obec("500011", "Nitra", "403", "4"),
            "556149": Obec("556149", "Krušovce", "406", "4"),
        },
    )
    lists = statoffice.read_candidates(*packages)
    overrides = Overrides({}, {}, (), (), {})
    cs, _ = candidates.match(lists.entries, admin, overrides)
    assert {c.id for c in cs} >= lists.withdrawn
    by_id = {c.id: c for c in cs}
    assert by_id["oz:BA/1#2"].area == "BA"
    assert by_id["oz:556149/1#1"].area == "556149"
    assert by_id["predseda:1#2"].obec == "529320"
    assert by_id["zsk:4/1#1"].obec == "500011"
    persons, _ = candidates.merge_persons(cs, admin, overrides)
    hattas = by_id["starosta:500011#2"].person
    assert by_id["zsk:4/1#1"].person == hattas
    assert len(persons) == len(cs) - 1


def test_unknown_party_code_fails():
    with pytest.raises(StatOfficeError, match="unknown"):
        statoffice.nomination("001,124", {"124": "PS"})
    assert statoffice.nomination("001", {}) == ([], True)


def records(final: statoffice.FinalResults) -> dict[str, results.Record]:
    return final.live.records()


def test_municipal_results_and_withdrawn_flags(packages: tuple[Package, Package]):
    final = statoffice.read_results(*packages, log=lambda _: None)
    mayor = records(final)["starosta:500011"]
    assert (mayor.status, mayor.counted, mayor.seats, mayor.filled) == (
        "final",
        (2, 2),
        1,
        1,
    )
    assert (mayor.eligible, mayor.voters, mayor.valid) == (1921, 739, 734)
    assert sorted(mayor.candidates) == [(1, 274, None), (2, 460, 1)]
    council = records(final)["oz:500011/1"]
    assert (council.valid, council.seats, council.filled) == (356, 1, 1)
    assert sorted(council.candidates) == [(1, 200, 1), (2, 150, 0), (3, 6, -1)]
    assert "oz:500011/2" in final.live.files["okres/403"]
    okrsky = final.live.okrsky["okres/403"]
    assert okrsky["starosta:500011"] == {
        "500011/1": (805, 363, 360, {1: 100, 2: 260}),
        "500011/2": (1116, 376, 374, {1: 174, 2: 200}),
    }
    assert okrsky["oz:500011/2"] == {"500011/2": (1116, 376, 362, {1: 300})}
    assert final.no_result == ["oz:556149/1", "starosta:556149"]
    assert final.live.source["oso"]["counted"] == [4, 5]


def test_city_okrsky_joined_to_the_districts(packages: tuple[Package, Package]):
    said: list[str] = []
    final = statoffice.read_results(*packages, log=said.append)
    assert final.city_by_number == ["BA 1/2 → 528595/2"]
    assert final.city_unmatched == ["BA 2/9"]
    assert any("1 by number alone" in s for s in said)
    mayor = records(final)["starosta:BA"]
    assert (mayor.eligible, mayor.voters, mayor.valid) == (3451, 1410, 1370)
    assert sorted(mayor.candidates) == [(1, 1010, 1), (2, 360, -1)]
    assert mayor.areas is not None
    assert mayor.areas["528595"] == (1801, 700, 680, {1: 500, 2: 180})
    assert mayor.areas["529494"] == (700, 200, 190, {1: 100, 2: 90})
    # The two okrsky 2/1 are told apart by the shares of their rows.
    assert final.live.okrsky["city/BA"]["starosta:BA"] == {
        "528595/1": (1000, 400, 390, {1: 300, 2: 90}),
        "528595/2": (801, 300, 290, {1: 200, 2: 90}),
        "529320/1": (900, 500, 490, {1: 400, 2: 90}),
        "529494/1": (700, 200, 190, {1: 100, 2: 90}),
    }
    council = records(final)["oz:BA/1"]
    assert (council.seats, council.filled, council.valid) == (2, 2, 660)
    assert sorted(council.candidates) == [(1, 350, 1), (2, 250, 1), (3, 150, 0)]
    assert set(final.live.okrsky["city/BA"]["oz:BA/1"]) == {"528595/1", "528595/2"}


def test_join_by_number_joins_only_an_okrsok_one_city_okrsok_claims():
    """A city okrsok left unmatched by its voters joins the okrsok of its
    number in its council obvod's districts, unless another city okrsok
    claims the same one, or the number is in two of those districts."""

    def city(obvod: str, okrsok: str) -> dict[str, str]:
        return {"Kód mesta": "599981", "Volebný obvod v obci": obvod, "Okrsok": okrsok}

    def district(obec: str, okrsok: str) -> dict[str, str]:
        return {"Kód obce": obec, "Okrsok": okrsok}

    turnout = [
        city("2", "1"),  # matched: 598127/1
        city("2", "2"),  # both claim 598127/2
        city("2", "2"),
        city("3", "1"),  # matched: 599875/1
        city("3", "4"),  # alone: 599875/4
        city("4", "1"),  # matched: 599891/1
        city("4", "1"),  # matched: 599905/1
        city("4", "5"),  # 599891/5 or 599905/5
    ]
    districts = [
        district("598127", "1"),
        district("598127", "2"),
        district("599875", "1"),
        district("599875", "4"),
        district("599891", "1"),
        district("599905", "1"),
        district("599891", "5"),
        district("599905", "5"),
    ]
    matches = {0: 0, 3: 2, 5: 4, 6: 5}
    assert statoffice.join_by_number(turnout, districts, matches) == {4: 3}


def test_regional_results(packages: tuple[Package, Package]):
    final = statoffice.read_results(*packages, log=lambda _: None)
    president = final.live.files["kraj/1"]["predseda:1"]
    assert (president.eligible, president.voters, president.valid) == (1800, 700, 670)
    assert sorted(president.candidates) == [(1, 500, 1), (2, 170, -1)]
    assert president.areas == {"528595": (1800, 700, 670, {1: 500, 2: 170})}
    council = final.live.files["kraj/4"]["zsk:4/1"]
    assert (council.seats, council.filled, council.valid) == (5, 1, 686)
    assert set(final.live.okrsky["kraj/4"]["zsk:4/1"]) == {"500011/1", "500011/2"}
    assert final.live.source["osk"]["counted"] == [4, 4]


def test_results_keep_the_contract(tmp_path: Path, packages: tuple[Package, Package]):
    final = statoffice.read_results(*packages, log=lambda _: None)
    now = dt.datetime(2022, 10, 30, 12, tzinfo=results.TIMEZONE)
    assert results.write(tmp_path / "out", final.live, now, checked=True)
