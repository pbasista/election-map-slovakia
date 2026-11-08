import argparse
import csv
import dataclasses
import datetime as dt
import hashlib
import io
import json
import math
import shutil
import zipfile
from collections import Counter
from pathlib import Path
from typing import cast

import pytest

from election_map_slovakia import addresses, candidates, cli, config, pages, results

REPO = Path(__file__).resolve().parent.parent

NOW = dt.datetime(2026, 10, 24, 21, 40, 12, tzinfo=results.TIMEZONE)


def candidacy(contest: str, number: int, first: str, surname: str, **extra) -> dict:
    return {
        "id": f"{contest}#{number}",
        "contest": contest,
        "number": number,
        "first_name": first,
        "surname": surname,
        "parties": [],
        "independent": True,
    } | extra


def make_data(obce_per_obvod: int = 1) -> tuple[dict, dict, dict]:
    """Return candidates.json data, geo props and seats of a small country.

    Bratislava with two districts, a kraj 1 of three regional obvody (the
    first being the districts) and a kraj 2 of one.
    """
    obce = [
        {"code": "BA", "name": "Bratislava", "kraj": "1"},
        {
            "code": "528595",
            "name": "Bratislava-Staré Mesto",
            "okres": "101",
            "kraj": "1",
            "city": "BA",
            "past": {"eligible": 30000, "voters": 12000},
        },
        {
            "code": "529320",
            "name": "Bratislava-Ružinov",
            "okres": "102",
            "kraj": "1",
            "city": "BA",
            "past": {"eligible": 60000, "voters": 21000},
        },
    ]
    props = {
        "528595": {"zsk": 1, "city_obvod": 1},
        "529320": {"zsk": 1, "city_obvod": 2},
    }
    regional = [("1", 2), ("1", 3), ("2", 1)]
    for i, (kraj, obvod) in enumerate(
        (k, o) for k, o in regional for _ in range(obce_per_obvod)
    ):
        code = f"5{kraj}{obvod}{i:03d}"
        obce.append(
            {
                "code": code,
                "name": f"Obec {code}",
                "okres": f"{kraj}06",
                "kraj": kraj,
                "past": {"eligible": 1000 + 37 * i, "voters": 400 + 11 * i},
            }
        )
        props[code] = {"zsk": obvod}
    contests = [
        {"id": "predseda:1", "kind": "predseda", "area": "1"},
        {"id": "predseda:2", "kind": "predseda", "area": "2"},
        {"id": "zsk:1/1", "kind": "zsk", "area": "1", "obvod": 1},
        {"id": "zsk:1/2", "kind": "zsk", "area": "1", "obvod": 2},
        {"id": "zsk:1/3", "kind": "zsk", "area": "1", "obvod": 3},
        {"id": "zsk:2/1", "kind": "zsk", "area": "2", "obvod": 1},
        {"id": "oz:BA/1", "kind": "oz", "area": "BA", "obvod": 1},
        {"id": "oz:BA/2", "kind": "oz", "area": "BA", "obvod": 2},
    ]
    contests.append(
        {
            "id": "starosta:BA",
            "kind": "starosta",
            "area": "BA",
            "past": {"eligible": 90000, "voters": 33000},
        }
    )
    for o in obce[1:]:
        past = {"eligible": o["past"]["eligible"], "voters": o["past"]["voters"]}
        contests.append(
            {
                "id": f"starosta:{o['code']}",
                "kind": "starosta",
                "area": o["code"],
                "past": past,
            }
        )
        contests.append(
            {
                "id": f"oz:{o['code']}/1",
                "kind": "oz",
                "area": o["code"],
                "obvod": 1,
                "past": past,
            }
        )
    # The presidents' past is their kraj's.
    for c in contests[:2]:
        kraj = c["area"]
        c["past"] = {
            "eligible": sum(
                o["past"]["eligible"] for o in obce[1:] if o["kraj"] == kraj
            ),
            "voters": sum(o["past"]["voters"] for o in obce[1:] if o["kraj"] == kraj),
        }
    names = [
        "Ján Novák",
        "Mária Kováčová",
        "Peter Horváth",
        "Eva Tóthová",
        "Juraj Varga",
    ]
    candidacies = []
    for c in contests:
        count = 5 if c["kind"] in ("predseda", "zsk", "oz") else 3
        for n in range(1, count + 1):
            first, surname = names[n - 1].split()
            candidacies.append(candidacy(c["id"], n, first, surname))
    data = {
        "kraje": [
            {"code": "1", "name": "Bratislavský"},
            {"code": "2", "name": "Trnavský"},
        ],
        "okresy": [],
        "obce": obce,
        "contests": contests,
        "candidacies": candidacies,
    }
    seats = {
        "zsk:1/1": 2,
        "zsk:1/2": 1,
        "zsk:1/3": 2,
        "zsk:2/1": 1,
        "oz:BA/1": 3,
        "oz:BA/2": 2,
    }
    return data, props, seats


DIVISIONS = results.Divisions.of(make_data()[0], ())
"""Where the obce of the results tested lie."""
EXPECT = results.Expect(
    frozenset({"oso", "osk"}),
    {},
    {},
    DIVISIONS,
    {"oso": "2022-10-29", "osk": "2022-10-29"},
)
"""What the municipal and regional results are checked against, each
half compared with that of 2022."""


@pytest.fixture(scope="module")
def ref() -> results.Reference:
    return results.reference(*make_data(), parts=())


def test_slovak_numbers():
    assert results.number("2 921") == 2921
    assert results.number("4\u00a0458\u00a0760") == 4458760
    assert results.number("45.0") == 45
    assert results.number(45.0) == 45
    assert results.number(7) == 7
    assert results.number("") is None
    assert results.number(" ") is None
    assert results.number("X") is None
    assert results.number(None) is None
    assert results.decimal("43,74 %") == pytest.approx(43.74)
    assert results.decimal("0,00 %") == 0
    assert results.decimal(" %") is None
    assert results.decimal(36.54) == pytest.approx(36.54)


def test_source_time_offsets():
    assert (
        results.source_time("24.10.2026 21:40:00 SELČ") == "2026-10-24T21:40:00+02:00"
    )
    assert results.source_time("25.10.2026 02:30:00 SEČ") == "2026-10-25T02:30:00+01:00"
    assert (
        results.source_time("20.10.2026 09:05 SEL\u010c") == "2026-10-20T09:05:00+02:00"
    )
    assert results.source_time("25.10.2026 04:10:00 CET") == "2026-10-25T04:10:00+01:00"
    # No zone (2022): Slovak local time, here already winter time.
    assert results.source_time("30.10.2022 07:20:00") == "2022-10-30T07:20:00+01:00"
    assert results.source_time("") is None
    assert results.source_time("Dátum") is None


def test_code_mapping(ref):
    assert results.vobvod("1", 5) == "105"
    assert results.vobvod("8", 12) == "812"
    assert results.CITY_OBCE == {"582000": "BA", "599981": "KE"}
    assert results.live_path("zsk:3/1", {}) == "kraj/3"
    assert results.live_path("oz:KE/2", {}) == "city/KE"
    okres_of = {"508063": "106"}
    assert results.live_path("starosta:508063", okres_of) == "okres/106"
    assert results.live_path("nrsr:SK", {}) == "country"
    assert results.live_path("nrsr:SK/12", {}) == "list/12"
    assert results.okrsok_file("country", "3") == "country/3"
    assert results.okrsok_file("list/12", "3") == "list/12/3"
    assert results.okrsok_file("kraj/3", "3") == "kraj/3"
    assert results.area_of_okrsok_file("country/3") == "country"
    assert results.area_of_okrsok_file("list/12/3") == "list/12"
    assert results.area_of_okrsok_file("kraj/3") == "kraj/3"
    assert ref.contests["zsk:1/2"].path == "kraj/1"
    assert ref.contests["oz:BA/2"].path == "city/BA"
    assert ref.contests["starosta:528595"].path == "okres/101"
    assert ref.contests["zsk:1/3"].seats == 2
    assert ref.contests["starosta:528595"].seats == 1
    assert ref.contests["oz:528595/1"].seats is None
    assert ref.municipal["BA"][0].id == "starosta:BA"
    assert [c.id for c in ref.municipal["BA"][1]] == ["oz:BA/1", "oz:BA/2"]
    assert ref.places["528595"].zsk == 1
    assert ref.places["528595"].city_obvod == 1


def person(number: int, name: str, parties=(), independent=False):
    return results.Candidate(
        number,
        candidates.search_key(name),
        tuple(candidates.search_key(p) for p in parties),
        independent,
    )


def test_match_winner_by_name():
    cands = [
        person(1, "Matúš Vallo", ["Progresívne Slovensko"]),
        person(2, "Ján Novák", ["Smer - sociálna demokracia"]),
        person(3, "Ján Novák", independent=True),
        person(4, "Anna Mária Kováčová"),
    ]
    assert results.match_winner(cands, "Matúš Vallo", "PS") == 1
    assert results.match_winner(cands, "Matus  VALLO", "") == 1
    assert results.match_winner(cands, "Ing. Matúš Vallo, PhD.", "") == 1
    assert results.match_winner(cands, "Vallo Matúš", "") == 1
    assert results.match_winner(cands, "Anna Mária Kováčová", "") == 4
    # Same name twice: the party decides.
    assert results.match_winner(cands, "Ján Novák", "SMER - sociálna demokracia") == 2
    assert results.match_winner(cands, "Ján Novák", "NEKA") == 3
    assert results.match_winner(cands, "Ján Novák", "") is None
    assert results.match_winner(cands, "Peter Pan", "NEKA") is None


def j(content) -> bytes:
    return json.dumps(content, ensure_ascii=False).encode()


def graph01(**values) -> bytes:
    row = {
        "C01": "Obec",
        "C02": "Obec",
        "C03": 100.0,
        "C04": "1 000",
        "C05": "450",
        "C06": 45.0,
        "C07": "449",
        "C08": 99.78,
        "C09": "440",
        "C10": "430",
        "C11": "",
        "C12": "",
        "C13": "",
        "C14": "",
        "C15": 7.0,
        "C16": "7",
        "C17": 1,
        "C18": "zvolených <br> poslancov",
    }
    return j([row | values])


def ballots(*rows) -> bytes:
    return j(
        [
            {
                "C01": n,
                "C02": "Meno",
                "C03": "Priezvisko",
                "C04": "NEKA",
                "C05": votes,
                "C06": "1,00",
                "C07": label,
                "C08": "",
            }
            for n, votes, label in rows
        ]
    )


def villages(ref: results.Reference) -> list[str]:
    """The codes of the municipalities outside Bratislava."""
    return [p.code for p in ref.places.values() if not p.city and p.code != "BA"]


def night_files(ref: results.Reference) -> dict[str, bytes]:
    first, second, third = villages(ref)[:3]
    return {
        "oso/json/tab01.json": j(
            [
                {
                    "C01": "25.10.2026 01:30:00 SELČ",
                    "C02": "25.10.2026 01:30:00 CEST",
                    "C03": "2 921",
                    "C04": "1 204",
                    "C05": "41,22 %",
                }
            ]
        ),
        "osk/json/tab01.json": j(
            [
                {
                    "C01": "25.10.2026 01:31:00 SELČ",
                    "C02": "25.10.2026 01:31:00 CEST",
                    "C03": "6 010",
                    "C04": "3 000",
                }
            ]
        ),
        results.CITY_LIST: j([{"C01": "582000", "C05": 388}]),
        f"oso/json/graph01/{first}.json": graph01(
            C11="Mária Kováčová", C12="NEKA", C13="250"
        ),
        f"oso/json/graph01/{second}.json": graph01(
            C11="Peter Pan", C12="NEKA", C13="250"
        ),
        f"oso/json/graph01/{third}.json": graph01(C04="", C05="", C06="", C07=""),
        "oso/json/graph01/582000.json": graph01(
            C03=50.0, C04="402 062", C05="80 000", C09="79 000", C11="Ján Novák"
        ),
        "oso/json/tab05/582000.json": ballots(
            (1, "30 000", ""), (2, "41 000", ""), (3, "8 000", "")
        ),
        "osk/json/tab02ba.json": j(
            [
                {
                    "C01": "Bratislavský kraj",
                    "C02": "Region of Bratislava",
                    "C03": "580",
                    "C04": "290",
                    "C05": "50,00 %",
                    "C06": "300 000",
                    "C07": "120 000",
                    "C08": "40,00 %",
                    "C09": "119 900",
                    "C10": "99,9 %",
                    "C11": "118 000",
                    "C12": "117 000",
                },
                {"C01": "Spolu", "C03": "6 010"},
            ]
        ),
        "osk/json/tab02bb/1.json": j(
            [
                {
                    "C01": "Volebný obvod č. 1",
                    "C03": "34",
                    "C04": "34",
                    "C06": "40 000",
                    "C07": "15 000",
                    "C11": "14 800",
                    "C12": "14 700",
                }
            ]
        ),
        "osk/json/tab06b/1.json": ballots((1, "60 000", ""), (2, "58 000", "")),
        "osk/json/tab06c/101.json": ballots((1, "8 000", ""), (2, "6 800", "")),
        "osk/json/tab09c/101.json": ballots(
            (1, "5 000", "zvolený"), (2, "4 000", ""), (3, "300", "X")
        ),
    }


def test_night_normalization(ref, tmp_path):
    files = night_files(ref)
    obce = villages(ref)
    logged: list[str] = []
    live = results.night(files, ref, logged.append)
    assert live.phase == "partial"
    assert live.source["oso"]["time"] == "2026-10-25T01:30:00+02:00"
    assert live.source["oso"]["counted"] == [1204, 2921]
    assert live.source["oso"]["unit"] == "obce"
    assert live.source["osk"]["counted"] == [3000, 6010]
    records = live.records()
    mayor = records[f"starosta:{obce[0]}"]
    assert mayor.status == "winner"
    assert mayor.candidates == [(2, 250, 1)]
    assert (mayor.eligible, mayor.voters, mayor.valid) == (1000, 450, 440)
    council = records[f"oz:{obce[0]}/1"]
    assert (council.status, council.seats, council.filled) == ("winner", 7, 7)
    assert council.valid == 430
    # An unknown winner is left out and logged; an unapproved record too.
    assert f"starosta:{obce[1]}" not in records
    assert any("Peter Pan" in line for line in logged)
    assert f"starosta:{obce[2]}" not in records
    ba = records["starosta:BA"]
    assert ba.status == "partial"
    assert ba.counted == (194, 388)
    assert ba.eligible == 402062
    assert sorted(ba.candidates) == [
        (1, 30000, None),
        (2, 41000, None),
        (3, 8000, None),
    ]
    # Bratislava's council is in only when the whole city is counted.
    assert "oz:BA/1" not in records
    president = records["predseda:1"]
    assert president.counted == (290, 580)
    assert (president.eligible, president.voters, president.valid) == (
        300000,
        120000,
        118000,
    )
    assert president.areas == {"obvod:1": (40000, 15000, 14800, {1: 8000, 2: 6800})}
    zsk = records["zsk:1/1"]
    assert zsk.counted == (34, 34)
    assert zsk.valid == 14700
    # A candidate who withdrew keeps their votes, flagged as such.
    assert zsk.candidates == [
        (1, 5000, 1),
        (2, 4000, None),
        (3, 300, results.WITHDRAWN),
    ]
    assert zsk.filled == 1
    assert "zsk:1/2" not in records
    assert results.write(tmp_path, live, DIVISIONS, NOW) is not None
    assert results.check(tmp_path, EXPECT) == []


def test_night_voters_counted(ref):
    """The count's progress is of the registered voters: a kraj partly
    counted with those of its okrsky counted, of at least as many as at the
    last election; one not counted yet with those of the last election."""
    live = results.night(night_files(ref), ref)
    past1 = ref.contests["predseda:1"].past[0]
    past2 = ref.contests["predseda:2"].past[0]
    assert live.source["osk"]["voters"] == [300000, max(past1, 300000) + past2]


def test_night_areas_of_counted_municipalities(ref):
    """A municipality fully counted brings its own regional votes at night,
    beside the president's obvody; one still counting does not, even if its
    file is there, and its votes are fetched only once it is counted."""
    files = night_files(ref)
    files["osk/json/tab02bc/101.json"] = j(
        [
            {
                "C01": "Bratislava-Staré Mesto",
                "C03": "10",
                "C04": "10",
                "C06": "30 000",
                "C07": "12 000",
                "C11": "11 800",
                "C12": "11 700",
            },
            {
                "C01": "Bratislava-Ružinov",
                "C03": "24",
                "C04": "12",
                "C06": "60 000",
                "C07": "9 000",
                "C11": "8 900",
                "C12": "8 800",
            },
        ]
    )
    paths = results.unit_paths(files, ref)
    assert "osk/json/tab02bc/101.json" in paths
    assert "osk/json/tab06d/528595.json" in paths
    assert "osk/json/tab09d/528595.json" in paths
    assert "osk/json/tab06d/529320.json" not in paths
    # Before its votes come, a municipality counted is in by its turnout
    # alone (valid unknown), and a council obvod also as a whole.
    records = results.night(files, ref).records()
    assert records["predseda:1"].areas == {
        "obvod:1": (40000, 15000, 14800, {1: 8000, 2: 6800}),
        "528595": (30000, 12000, None, {}),
    }
    assert records["zsk:1/1"].areas == {
        "obvod:1": (40000, 15000, 14700, {1: 5000, 2: 4000, 3: 300}),
        "528595": (30000, 12000, None, {}),
    }
    files["osk/json/tab06d/528595.json"] = ballots((1, "4 000", ""), (2, "3 500", ""))
    files["osk/json/tab09d/528595.json"] = ballots((1, "3 000", ""), (2, "2 000", ""))
    files["osk/json/tab06d/529320.json"] = ballots((1, "1 000", ""), (2, "900", ""))
    assert "osk/json/tab06d/528595.json" not in results.unit_paths(files, ref)
    records = results.night(files, ref).records()
    assert records["predseda:1"].areas == {
        "obvod:1": (40000, 15000, 14800, {1: 8000, 2: 6800}),
        "528595": (30000, 12000, 11800, {1: 4000, 2: 3500}),
    }
    assert records["zsk:1/1"].areas == {
        "528595": (30000, 12000, 11700, {1: 3000, 2: 2000})
    }


def test_night_tolerates_bad_files(ref):
    files = night_files(ref)
    obce = villages(ref)
    files[f"oso/json/graph01/{obce[0]}.json"] = b"<html>404</html>"
    files["osk/json/tab06b/1.json"] = j({"not": "a list"})
    files["oso/json/graph01/582000.json"] = graph01(C17=[1], C03="?")
    logged: list[str] = []
    live = results.night(files, ref, logged.append)
    records = live.records()
    assert f"starosta:{obce[0]}" not in records
    assert "predseda:1" not in records
    assert "zsk:1/1" in records


def council_ballots(contests, *rows) -> bytes:
    """tab06e* rows (ballot number, votes) in the obvod of each council contest."""
    return j(
        [
            {"C01": n, "C05": c.obvod or 1, "C06": votes}
            for c in contests
            for n, votes in rows
        ]
    )


def test_night_candidates_of_a_counted_municipality(ref):
    """A municipality fully counted brings every candidate's votes at night,
    asked for until they have come; one still counting is asked for none."""
    files = night_files(ref)
    first, second = villages(ref)[:2]
    councils = ref.municipal[first][1]
    files[f"oso/json/graph01/{second}.json"] = graph01(C03=40.0)
    paths = results.unit_paths(files, ref)
    assert f"oso/json/tab05/{first}.json" in paths
    assert f"oso/json/tab06e2/{first}.json" in paths
    assert f"oso/json/tab05/{second}.json" not in paths
    assert f"oso/json/graph01/{first}.json" not in paths
    files[f"oso/json/tab05/{first}.json"] = ballots(
        (2, "250", "zvolený"), (1, "190", "")
    )
    files[f"oso/json/tab06e1/{first}.json"] = council_ballots(councils, (3, "120"))
    files[f"oso/json/tab06e2/{first}.json"] = council_ballots(
        councils, (3, "120"), (4, "80")
    )
    paths = results.unit_paths(files, ref)
    assert f"oso/json/tab05/{first}.json" not in paths
    assert f"oso/json/tab06e2/{first}.json" not in paths
    records = results.night(files, ref).records()
    mayor = records[f"starosta:{first}"]
    assert (mayor.status, mayor.filled, mayor.counted) == ("final", 1, None)
    assert sorted(mayor.candidates) == [(1, 190, None), (2, 250, 1)]
    for c in councils:
        council = records[c.id]
        assert council.status == "final"
        assert sorted(council.candidates) == [(3, 120, 1), (4, 80, 0)]


class FakeClient:
    """A volbysr.sk serving *server* (path → content); a path absent is a 404."""

    def __init__(self, server: dict[str, bytes]) -> None:
        self.server = server
        self.copies: dict[str, bytes] = {}
        self.messages: list[str] = []

    def files(self) -> dict[str, bytes]:
        return dict(self.copies)

    def get_all(self, paths, stamp) -> Counter[str]:
        out: Counter[str] = Counter()
        for p in paths:
            if p in self.server:
                out["same" if self.copies.get(p) == self.server[p] else "changed"] += 1
                self.copies[p] = self.server[p]
            else:
                out["missing"] += 1
        return out


def test_poll_fetches_the_files_a_poll_makes_due(ref, tmp_path):
    """The candidates of a municipality found fully counted come in the same
    poll, not at the next change of the progress."""
    server = night_files(ref)
    first = villages(ref)[0]
    server[f"oso/json/tab05/{first}.json"] = ballots(
        (2, "250", "zvolený"), (1, "190", "")
    )
    client = FakeClient(server)
    poller = results.Poller(cast(results.Client, client), ref, tmp_path, [].append)
    assert poller.cycle() is not None
    live = results.read_live(tmp_path)
    assert live is not None
    mayor = live.records()[f"starosta:{first}"]
    assert mayor.status == "final"
    assert sorted(mayor.candidates) == [(1, 190, None), (2, 250, 1)]


def test_night_before_counting(ref, tmp_path):
    files = {
        "oso/json/tab01.json": j(
            [
                {
                    "C01": "20.10.2026 09:00:00 SELČ",
                    "C02": "20.10.2026 09:00:00 CEST",
                    "C03": "2 921",
                    "C04": "0",
                    "C05": "0,00 %",
                    "C06": "",
                    "C07": "",
                    "C08": " %",
                    "C09": "",
                    "C10": " %",
                }
            ]
        ),
        "osk/json/dateSK.json": j(["20.10.2026 09:04 SELČ"]),
    }
    live = results.night(files, ref)
    assert live.phase == "none"
    assert live.source["osk"] == {
        "time": "2026-10-20T09:04:00+02:00",
        "counted": None,
        "unit": "okrsky",
        "voters": None,
    }
    assert results.unit_paths(files, ref) == []
    status = results.write(tmp_path, live, DIVISIONS, NOW)
    assert status["phase"] == "none"
    assert status["files"] == {}
    assert results.check(tmp_path, EXPECT) == []


def test_status_versions_and_hashes(ref, tmp_path):
    live = results.night(night_files(ref), ref)
    first = results.write(tmp_path, live, DIVISIONS, NOW)
    assert first["version"].startswith("20261024T214012-")
    assert first["updated"] == "2026-10-24T21:40:12+02:00"
    for path, digest in first["files"].items():
        data = (tmp_path / f"{path}.json").read_bytes()
        assert hashlib.sha256(data).hexdigest()[:8] == digest
    assert {"kraj/1", "city/BA"} <= set(first["files"])
    # The same content again: nothing is written.
    later = NOW + dt.timedelta(minutes=1)
    assert results.write(tmp_path, live, DIVISIONS, later) is None
    assert results.read_status(tmp_path) == first
    # One contest changes: a new version, a new hash of its file only.
    live.files["kraj/1"]["zsk:1/1"].candidates[0] = (1, 5001, 1)
    second = results.write(tmp_path, live, DIVISIONS, later)
    assert second["version"] != first["version"]
    changed = {p for p in first["files"] if first["files"][p] != second["files"][p]}
    assert changed == {"kraj/1"}
    # Only the source time changes: a new version, the same files.
    live.source["oso"]["time"] = "2026-10-25T01:35:00+02:00"
    third = results.write(tmp_path, live, DIVISIONS, later)
    assert third["version"] != second["version"]
    assert third["files"] == second["files"]
    # A file edited behind the status breaks the contract.
    (tmp_path / "kraj/1.json").write_bytes(b'{"contests":{}}')
    assert any("hash" in p for p in results.check(tmp_path, EXPECT))


def decided(record: results.Record, eligible_2022: int) -> bool:
    """The app's call rule (web/js/live.js) for a partial contest."""
    remaining = max(math.ceil(1.1 * eligible_2022), record.eligible) - record.eligible
    seats = record.seats or 1
    votes = sorted((v for _, v, _ in record.candidates), reverse=True)
    return all(
        sum(1 for k, w in enumerate(votes) if k != i and w + remaining >= v) < seats
        for i, v in enumerate(votes[:seats])
    )


@pytest.fixture(scope="module")
def big_ref() -> results.Reference:
    return results.reference(*make_data(obce_per_obvod=12), parts=())


def test_fake_stages_follow_the_contract_and_only_grow(big_ref, tmp_path):
    stages = {s: results.fake(big_ref, s, seed=7) for s in results.STAGES}
    for name, live in stages.items():
        assert results.write(tmp_path / name, live, DIVISIONS, NOW) is not None
        assert results.check(tmp_path / name, EXPECT) == [], name
    assert stages["none"].phase == "none" and not stages["none"].files
    assert stages["final"].phase == "final"
    assert stages["late"].phase == stages["mid"].phase == "partial"
    order = list(results.STAGES)
    for before, after in zip(order, order[1:], strict=False):
        old, new = stages[before].records(), stages[after].records()
        assert set(old) <= set(new), (before, after)
        for contest, r in old.items():
            n = new[contest]
            for field in ("eligible", "voters", "valid"):
                if getattr(r, field) is not None and getattr(n, field) is not None:
                    assert getattr(n, field) >= getattr(r, field), (contest, field)
            if r.counted and n.counted:
                assert n.counted[0] >= r.counted[0]
            votes = {b[0]: b[1] for b in n.candidates}
            for number, v, _ in r.candidates:
                assert votes[number] >= v, (contest, number)
        for election in ("oso", "osk"):
            assert (
                stages[after].source[election]["counted"][0]
                >= stages[before].source[election]["counted"][0]
            )
    assert results.fake(big_ref, "mid", seed=7).records() == stages["mid"].records()


def test_fake_mid_has_a_landslide_and_a_close_race(big_ref):
    mid = results.fake(big_ref, "mid", seed=7).records()
    late = results.fake(big_ref, "late", seed=7).records()
    partial = {c: r for c, r in mid.items() if r.status == "partial"}
    called = [c for c, r in partial.items() if decided(r, big_ref.contests[c].past[0])]
    assert called, "no partial contest decided at mid"
    assert "predseda:1" in partial
    assert not decided(partial["predseda:1"], big_ref.contests["predseda:1"].past[0])
    assert not decided(late["predseda:1"], big_ref.contests["predseda:1"].past[0])
    # Municipal results at mid: winners only, for some municipalities.
    winners = [r for c, r in mid.items() if c.startswith("starosta:5")]
    assert winners and all(r.status == "winner" for r in winners)
    assert all(len(r.candidates) == 1 and r.candidates[0][2] == 1 for r in winners)
    assert mid["starosta:BA"].status == "partial"
    assert mid["starosta:BA"].counted[0] < mid["starosta:BA"].counted[1]


def test_fake_final_has_everything(big_ref):
    final = results.fake(big_ref, "final").records()
    assert set(final) == {
        c.id for c in big_ref.contests.values() if big_ref.candidates.get(c.id)
    }
    assert all(r.status == "final" for r in final.values())
    president = final["predseda:1"]
    assert sum(1 for b in president.candidates if b[2] == 1) == 1
    assert set(president.areas) == {
        p.code for p in big_ref.places.values() if p.kraj == "1" and p.zsk
    }
    assert set(final["starosta:BA"].areas) == {"528595", "529320"}
    council = final["zsk:1/3"]
    assert sorted(b[2] for b in council.candidates) == [0, 0, 0, 1, 1]


def test_fake_final_okrsky_add_up(big_ref, tmp_path):
    """Fake okrsky: the real counts, a council obvod's own okrsky, figures
    adding up to their contest; check catches okrsky that do not."""
    live = results.fake(
        big_ref,
        "final",
        okrsky={"528595": 3, "529320": 4},
        obvod_okrsky={"528595": {1: (2, 3)}},
        past=EXPECT.past,
    )
    ba = live.okrsky["city/BA"]
    assert set(ba["starosta:BA"]) == {f"528595/{n}" for n in (1, 2, 3)} | {
        f"529320/{n}" for n in (1, 2, 3, 4)
    }
    assert live.files["city/BA"]["starosta:BA"].counted == (7, 7)
    district = live.okrsky["okres/101"]
    assert set(district["oz:528595/1"]) == {"528595/2", "528595/3"}
    assert live.files["okres/101"]["oz:528595/1"].counted == (2, 2)
    assert "528595/1" in live.okrsky["kraj/1"]["predseda:1"]
    for path, contests in live.okrsky.items():
        for contest, okrsky in contests.items():
            record = live.files[path][contest]
            assert len(okrsky) == record.counted[1], contest
            assert sum(a[0] for a in okrsky.values()) == record.eligible, contest
            assert sum(a[2] for a in okrsky.values()) == record.valid, contest
    past = live.past["oso"]
    assert live.past == dict.fromkeys(live.source, past)
    assert past.day and past.methods and past.contests
    keys = {
        k for contests in live.okrsky.values() for c in contests.values() for k in c
    }
    several = {k.partition("/")[0] for k in keys if k.endswith("/2")}
    assert {k.partition("/")[0] for k in past.methods} <= several
    # An okrsok's figures only where its method is known; a whole obec's
    # wherever all its okrsky are in the contest.
    for units in past.contests.values():
        for unit in units:
            assert "/" not in unit or past.methods.get(unit, results.UNKNOWN)
    assert "528595" in past.contests["starosta:BA"]
    assert "528595" not in past.contests["oz:528595/1"]
    assert results.write(tmp_path / "good", live, DIVISIONS, NOW) is not None
    assert results.check(tmp_path / "good", EXPECT) == []
    # The regional contests too: the regional okrsky are the municipal ones.
    okrsky_dir = tmp_path / "good" / results.OKRSKY_DIR
    written = {
        p.relative_to(okrsky_dir).as_posix(): json.loads(p.read_bytes())
        for p in okrsky_dir.rglob("*.json")
    }
    assert any(f["past"] for p, f in written.items() if p.startswith("kraj/"))
    assert results.read_live(tmp_path / "good").past == live.past
    e, v, valid, votes = district["oz:528595/1"]["528595/2"]
    district["oz:528595/1"]["528595/2"] = (e, v, valid, {**votes, 1: votes[1] + 1})
    assert results.write(tmp_path / "bad", live, DIVISIONS, NOW) is not None
    assert results.check(tmp_path / "bad", EXPECT) == [
        "okrsky/okres/101: oz:528595/1: votes of the okrsky do not add up to the"
        " candidates'"
    ]


def test_fake_final_no_okrsky_of_unknown_obvody():
    """A council of several obvody whose rule set does not give their okrsky
    has none; its mayor still has all of the municipality's."""
    data, props, seats = make_data()
    data["contests"].append(
        {"id": "oz:529320/2", "kind": "oz", "area": "529320", "obvod": 2}
    )
    data["candidacies"].append(candidacy("oz:529320/2", 1, "Ján", "Novák"))
    live = results.fake(
        results.reference(data, props, seats, parts=()), "final", okrsky={"529320": 4}
    )
    okrsky = live.okrsky["okres/102"]
    assert "oz:529320/1" not in okrsky and "oz:529320/2" not in okrsky
    assert len(okrsky["starosta:529320"]) == 4
    assert live.files["okres/102"]["oz:529320/1"].status == "final"


# The 2026 packages' column names, as their header rows give them.
ELIGIBLE = "Počet zapísaných voličov"
VOTERS = "Počet zúčastnených voličov"
VALID = "Počet platných hlasovacích lístkov odovzdaných pre voľby "
MAYOR, COUNCIL, PRESIDENT = (
    VALID + "starostu",
    VALID + "do zastupiteľstva",
    VALID + "predsedu",
)


def test_city_okrsky_matched_only_when_unambiguous():
    """A city okrsok goes to the district okrsok with its registered voters
    and voters only when no other city okrsok or district okrsok has them."""

    def pair(eligible, voters):
        return {ELIGIBLE: str(eligible), VOTERS: str(voters)}

    def city(okrsok, eligible, voters):
        return {
            "Kód mesta": "582000",
            "Volebný obvod v obci": "1",
            "Okrsok": okrsok,
        } | pair(eligible, voters)

    def district(obec, okres, okrsok, eligible, voters):
        return {"Kód obce": obec, "Kód okresu": okres, "Okrsok": okrsok} | pair(
            eligible, voters
        )

    districts = [
        district("528595", "101", "1", 900, 400),  # 0
        district("528595", "101", "2", 800, 300),  # 1
        district("529320", "102", "1", 800, 300),  # 2: same pair as 1
        district("529320", "102", "2", 700, 200),  # 3
        district("500011", "403", "1", 500, 100),  # 4: not of the city
    ]
    turnout = [
        city("1", 900, 400),  # 0: unique → 0
        city("2", 800, 300),  # 1: two district rows
        city("3", 700, 200),  # 2: two city rows
        city("4", 700, 200),  # 3
        city("5", 500, 100),  # 4: no district row of the city
    ]
    matches = results.city_matches(turnout, districts)
    assert matches == {0: 0}
    # For the district totals every city okrsok still goes to a district.
    assert results.city_districts(turnout, districts, matches) == {
        i: "528595" for i in range(5)
    }


def package(path: Path, prefix: str, tables: dict[str, list[dict]]) -> Path:
    """Write a definitive results zip of 2026's form: CSV tables with headers."""
    with zipfile.ZipFile(path, "w") as z:
        for table, rows in tables.items():
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            z.writestr(f"{prefix}_SK_{table}.csv", "\ufeff" + out.getvalue())
    return path


def votes(flag: str, where: dict, *rows: tuple) -> list[dict]:
    """Vote rows of *where*: (ballot number, votes, the *flag* column's text)."""
    return [
        {
            **where,
            "Poradie na hlasovacom lístku": n,
            "Počet platných hlasov": v,
            flag: f,
        }
        for n, v, f in rows
    ]


def oso_tables() -> dict[str, list[dict]]:
    """A municipal package: Nitra with two council obvody, a village with one,
    and Bratislava, whose city okrsok 1 of obvod 1 has two copies (as
    Košice's numbers repeat), its districts each holding some okrsky.
    Candidate 3 of the mayors withdrew; their votes count all the same."""
    obec = {"Kód obce": "500011", "Kód okresu": "403"}
    village = {"Kód obce": "512311", "Kód okresu": "301"}
    ba = {"Kód mesta": "582000"}
    city_okrsky = [  # obvod, okrsok, eligible, voters, valid mayor, council
        ("1", "1", 200, 80, 78, 76),
        ("1", "1", 100, 50, 48, 47),
        ("1", "2", 300, 150, 140, 139),
    ]
    # The votes of each city okrsok: the mayor's add up to its valid
    # ballots; the council's of the two copies fit either copy.
    mayor_okrsky = [{1: 50, 2: 24, 3: 4}, {1: 30, 2: 16, 3: 2}, {1: 100, 2: 36, 3: 4}]
    council_okrsky = [{1: 40, 2: 40}, {1: 45, 2: 45}, {1: 70, 2: 69}]
    # Each candidate's rows of the okrsky come in an order of their own.
    orders = {1: (0, 1, 2), 2: (1, 2, 0), 3: (2, 0, 1)}

    def city_rows(flag: str, okrsky: list[dict[int, int]], withdrawn=()) -> list:
        """Vote rows of the city okrsky, with the shares of each one's total."""
        return [
            {
                **ba,
                "Volebný obvod v obci": city_okrsky[i][0],
                "Okrsok": city_okrsky[i][1],
                "Poradie na hlasovacom lístku": n,
                "Počet platných hlasov": okrsky[i][n],
                "Podiel platných hlasov v %": "{:.2f}".format(
                    math.floor(10000 * okrsky[i][n] / sum(okrsky[i].values())) / 100
                ),
                flag: "X" if n in withdrawn else "",
            }
            for n in sorted(okrsky[0])
            for i in orders[n]
        ]

    def district(code: str, okres: str) -> dict:
        return {"Kód obce": code, "Kód okresu": okres}

    return {
        "tab02d": [
            {**obec, "Počet okrskov": 3, "Počet volených poslancov": 3}
            | {ELIGIBLE: 1000, VOTERS: 420, MAYOR: 410},
            {**village, "Počet okrskov": 1, "Počet volených poslancov": 5}
            | {ELIGIBLE: 120, VOTERS: 60, MAYOR: 0},
        ],
        "tab02e": [
            {**obec, "Volebný obvod v obci": "1", "Počet okrskov": 2}
            | {ELIGIBLE: 600, VOTERS: 250, COUNCIL: 240},
            {**obec, "Volebný obvod v obci": "2", "Počet okrskov": 1}
            | {ELIGIBLE: 400, VOTERS: 170, COUNCIL: 160},
            {**village, "Volebný obvod v obci": "1", "Počet okrskov": 1}
            | {ELIGIBLE: 120, VOTERS: 60, COUNCIL: 58},
        ],
        "tab02f": [
            {**where, "Volebný obvod v obci": o, "Okrsok": k}
            | {ELIGIBLE: e, VOTERS: v, MAYOR: m, COUNCIL: c}
            for where, o, k, e, v, m, c in [
                (obec, "1", "1", 300, 130, 128, 125),
                (obec, "1", "2", 300, 120, 117, 115),
                (obec, "2", "3", 400, 170, 165, 160),
                (village, "1", "1", 120, 60, 0, 58),
                (district("528595", "101"), "1", "1", 100, 50, 48, 47),
                (district("528595", "101"), "1", "2", 300, 150, 140, 139),
                (district("529320", "102"), "1", "1", 200, 80, 78, 76),
            ]
        ],
        "tab05d": votes(
            "Poznámka", obec, (1, 150, ""), (2, 240, "zvolený"), (3, 20, "X")
        ),
        "tab05f": [
            row
            for k, counts in (
                ("1", (50, 70, 8)),
                ("2", (40, 70, 7)),
                ("3", (60, 100, 5)),
            )
            for row in votes(
                "Poznámka",
                {**obec, "Okrsok": k},
                (1, counts[0], ""),
                (2, counts[1], ""),
                (3, counts[2], "X"),
            )
        ],
        "tab08f": votes(
            "Kandidát",
            {**obec, "Volebný obvod v obci": "1", "Okrsok": "1"},
            (1, 80, ""),
            (2, 40, ""),
            # Withdrew: in the tables per okrsok, not in that per obvod.
            (3, 5, "X"),
        )
        + votes(
            "Kandidát",
            {**obec, "Volebný obvod v obci": "1", "Okrsok": "2"},
            (1, 60, ""),
            (2, 50, ""),
            (3, 3, "X"),
        )
        + votes(
            "Kandidát",
            {**obec, "Volebný obvod v obci": "2", "Okrsok": "3"},
            (3, 100, ""),
            (4, 90, ""),
            (5, 80, ""),
        )
        + votes(
            "Kandidát",
            {**village, "Volebný obvod v obci": "1", "Okrsok": "1"},
            (1, 50, ""),
            (2, 40, ""),
        ),
        "tab08e": votes(
            "Kandidát",
            {**obec, "Volebný obvod v obci": "1"},
            (1, 140, "zvolený"),
            (2, 90, "náhradník"),
        )
        + votes(
            "Kandidát",
            {**obec, "Volebný obvod v obci": "2"},
            (3, 100, "zvolený"),
            (4, 90, "zvolený"),
            (5, 80, "náhradník"),
        )
        + votes(
            "Kandidát",
            {**village, "Volebný obvod v obci": "1"},
            (1, 50, "zvolený"),
            (2, 40, "zvolený"),
        ),
        "tab02x": [{**ba, "Počet okrskov": 3, ELIGIBLE: 600, VOTERS: 280, MAYOR: 266}],
        "tab02ex": [
            {**ba, "Volebný obvod v obci": "1", "Počet okrskov": 3}
            | {ELIGIBLE: 600, VOTERS: 280, COUNCIL: 262}
        ],
        "tab02fx": [
            {**ba, "Volebný obvod v obci": o, "Okrsok": k}
            | {ELIGIBLE: e, VOTERS: v, MAYOR: m, COUNCIL: c}
            for o, k, e, v, m, c in city_okrsky
        ],
        "tab05x": votes("Poznámka", ba, (1, 180, "zvolený"), (2, 76, ""), (3, 10, "X")),
        "tab05fx": city_rows("Poznámka", mayor_okrsky, withdrawn=(3,)),
        "tab08ex": votes(
            "Kandidát",
            {**ba, "Volebný obvod v obci": "1"},
            (1, 155, "zvolený"),
            (2, 154, "náhradník"),
        ),
        "tab08fx": city_rows("Kandidát", council_okrsky),
    }


def osk_tables() -> dict[str, list[dict]]:
    """A regional package: kraj 1 with one obvod of two municipalities."""
    kraj = {"Kód kraja": "1"}
    obvod = {"Kód volebného obvodu": "101"}
    staré_mesto = {**kraj, **obvod, "Kód obce": "528595"}
    ružinov = {**kraj, **obvod, "Kód obce": "529320"}

    def regional_okrsky(*per_obec: tuple) -> list[tuple[dict, str, tuple]]:
        """Return (municipality, okrsok, votes) of Staré Mesto's and Ružinov's okrsky."""
        return [
            (where, str(k), counts)
            for where, okrsky in zip((staré_mesto, ružinov), per_obec, strict=True)
            for k, counts in enumerate(okrsky, 1)
        ]

    return {
        "tab02a": [
            {**kraj, "Počet volebných okrskov": 5}
            | {"Počet potvrdených okrskových zápisníc": 5}
            | {ELIGIBLE: 1000, VOTERS: 400, PRESIDENT: 390}
        ],
        "tab02b": [
            {**obvod, "Počet volebných okrskov": 5}
            | {"Počet potvrdených okrskových zápisníc": 5}
            | {"Počet volených poslancov": 2, ELIGIBLE: 1000, VOTERS: 400}
            | {COUNCIL: 380}
        ],
        "tab02c": [
            {**staré_mesto, ELIGIBLE: 600, VOTERS: 250, PRESIDENT: 245, COUNCIL: 240},
            {**ružinov, ELIGIBLE: 400, VOTERS: 150, PRESIDENT: 145, COUNCIL: 140},
        ],
        "tab02d": [
            {**where, "Volebný okrsok": k}
            | {ELIGIBLE: e, VOTERS: v, PRESIDENT: p, COUNCIL: c}
            for where, k, e, v, p, c in [
                (staré_mesto, "1", 350, 150, 147, 144),
                (staré_mesto, "2", 250, 100, 98, 96),
                (ružinov, "1", 150, 60, 58, 56),
                (ružinov, "2", 150, 50, 48, 47),
                (ružinov, "3", 100, 40, 39, 37),
            ]
        ],
        "tab06a": votes(
            "Kandidát", kraj, (1, 250, "zvolený"), (2, 140, ""), (3, 0, "X")
        ),
        "tab06c": votes("Kandidát", staré_mesto, (1, 160, "zvolený"), (2, 85, ""))
        + votes("Kandidát", ružinov, (1, 90, "zvolený"), (2, 55, "")),
        "tab06d": [
            row
            for where, k, counts in regional_okrsky(
                ((100, 47), (60, 38)), ((40, 18), (30, 18), (20, 19))
            )
            for row in votes(
                "Kandidát",
                {**where, "Volebný okrsok": k},
                *((n, c, "") for n, c in enumerate(counts, 1)),
            )
        ],
        "tab09b": votes(
            "Kandidát", obvod, (1, 200, "zvolený"), (2, 100, "zvolený"), (3, 80, "")
        ),
        "tab09c": votes("Kandidát", staré_mesto, (1, 120, ""), (2, 60, ""), (3, 60, ""))
        + votes("Kandidát", ružinov, (1, 80, ""), (2, 40, ""), (3, 20, "")),
        "tab09d": [
            row
            for where, k, counts in regional_okrsky(
                ((70, 35, 39), (50, 25, 21)),
                ((30, 15, 11), (30, 10, 8), (20, 15, 1)),
            )
            for row in votes(
                "Kandidát",
                {**where, "Volebný okrsok": k},
                *((n, c, "") for n, c in enumerate(counts, 1)),
            )
        ],
    }


@pytest.fixture
def final_2026(tmp_path) -> tuple[results.Live, list[str]]:
    oso = package(tmp_path / "OSO2026_SK_csv.zip", "OSO2026", oso_tables())
    osk = package(tmp_path / "OSK2026_SK_csv.zip", "OSK2026", osk_tables())
    contests = {
        f"oz:500011/{n}": results.Contest(
            f"oz:500011/{n}", "oz", "500011", n, "okres/403", seats, None
        )
        for n, seats in ((1, 1), (2, 2))
    }
    return results.read_final([oso, osk], contests)


def test_final_municipal(final_2026):
    live, elections = final_2026
    assert elections == ["oso", "osk"]
    assert live.source["oso"]["counted"] == [2, 2]
    records = live.records()
    mayor = records["starosta:500011"]
    assert mayor.status == "final"
    assert (mayor.counted, mayor.eligible, mayor.voters, mayor.valid) == (
        (3, 3),
        1000,
        420,
        410,
    )
    # The withdrawn candidate (X) keeps the votes, flagged; the elected one 1.
    assert mayor.candidates == [(1, 150, None), (2, 240, 1), (3, 20, results.WITHDRAWN)]
    assert (mayor.seats, mayor.filled) == (1, 1)
    # A council obvod: substitutes flagged 0; seats from the candidate lists
    # where the municipality has several obvody, else from the tables.
    first = records["oz:500011/1"]
    assert (first.eligible, first.voters, first.valid) == (600, 250, 240)
    # A candidate who withdrew, missing from the table per obvod, comes with
    # their votes from those per okrsok.
    assert first.candidates == [(1, 140, 1), (2, 90, 0), (3, 8, results.WITHDRAWN)]
    assert (first.seats, first.filled) == (1, 1)
    assert (records["oz:500011/2"].seats, records["oz:500011/2"].filled) == (2, 2)
    assert (records["oz:512311/1"].seats, records["oz:512311/1"].filled) == (5, 2)
    assert "oz:500011/1" in live.files["okres/403"]


def test_final_city_contests_by_district(final_2026):
    """Bratislava's own contests are put by district through its okrsky,
    copies of an okrsok number told apart by the shares of their votes, each
    candidate's rows of them in an order of its own; where the council's
    copies fit either way, the districts they lie in are left out."""
    live, _ = final_2026
    mayor = live.files["city/BA"]["starosta:BA"]
    assert (mayor.eligible, mayor.voters, mayor.valid) == (600, 280, 266)
    assert mayor.candidates == [(1, 180, 1), (2, 76, None), (3, 10, results.WITHDRAWN)]
    assert mayor.areas == {
        "528595": (400, 200, 188, {1: 130, 2: 52, 3: 6}),
        "529320": (200, 80, 78, {1: 50, 2: 24, 3: 4}),
    }
    council = live.files["city/BA"]["oz:BA/1"]
    assert council.candidates == [(1, 155, 1), (2, 154, 0)]
    assert council.areas == {}


def test_final_city_okrsky_not_told_apart_are_logged(tmp_path):
    logged: list[str] = []
    oso = package(tmp_path / "OSO2026_SK_csv.zip", "OSO2026", oso_tables())
    results.read_final([oso], log=logged.append)
    assert (
        "oz:BA/1: okrsky of a number not told apart (council obvod/number"
        " ×okrsky: 1/1 ×2); left out of the okrsok file and of the areas of"
        " 528595, 529320"
    ) in logged
    assert not any(line.startswith("starosta:BA") for line in logged)


def city_okrsok(obvod: str, okrsok: str, mayor: int, council: int) -> dict:
    return {"Volebný obvod v obci": obvod, "Okrsok": okrsok, MAYOR: mayor} | {
        COUNCIL: council
    }


def share_rows(obvod: str, okrsok: str, *copies: dict[int, int]) -> list[dict]:
    """The vote rows of okrsky of one number, each share of its copy's total,
    rounded as ŠÚ SR may: each candidate's rows in the copies' reverse order."""
    return [
        {
            "Volebný obvod v obci": obvod,
            "Okrsok": okrsok,
            "Poradie na hlasovacom lístku": str(n),
            "Počet platných hlasov": str(votes[n]),
            "Podiel platných hlasov v %": f"{100 * votes[n] / sum(votes.values()):.2f}",
        }
        for n in sorted(copies[0])
        for votes in reversed(copies)
    ]


def test_city_votes_by_shares_and_seats():
    """Two council okrsky of a number fit either way but for the seats: at
    most seats times the valid ballots of votes in all; a mayor's always fit
    one way, their votes adding up to the valid ballots."""
    turnout = [city_okrsok("1", "1", 31, 10), city_okrsok("1", "1", 40, 30)]
    small, large = {1: 8, 2: 8, 3: 7, 4: 7}, {1: 10, 2: 10, 3: 10, 4: 10}
    council = share_rows("1", "1", small, large)
    told = results.city_votes(turnout, [0, 1], council, "oz", 3)
    assert told.rows == {0: small, 1: large}
    assert not told.unresolved
    either = results.city_votes(turnout, [0, 1], council, "oz", None)
    assert either.rows == {}
    (unresolved,) = either.unresolved
    assert unresolved.okrsky == [0, 1]
    assert len(unresolved.ways) == 2
    assert unresolved.votes == {1: 18, 2: 18, 3: 17, 4: 17}
    mayor = share_rows("1", "1", {1: 20, 2: 11}, {1: 20, 2: 20})
    by_mayor = results.city_votes(turnout, [0, 1], mayor, "starosta", 1)
    assert by_mayor.rows == {0: {1: 20, 2: 11}, 1: {1: 20, 2: 20}}


def test_final_regional(final_2026):
    live, _ = final_2026
    assert live.source["osk"]["counted"] == [5, 5]
    president = live.files["kraj/1"]["predseda:1"]
    assert (president.eligible, president.voters, president.valid) == (1000, 400, 390)
    assert president.candidates == [
        (1, 250, 1),
        (2, 140, None),
        (3, 0, results.WITHDRAWN),
    ]
    assert president.areas == {
        "528595": (600, 250, 245, {1: 160, 2: 85}),
        "529320": (400, 150, 145, {1: 90, 2: 55}),
    }
    council = live.files["kraj/1"]["zsk:1/1"]
    assert council.valid == 380
    assert council.candidates == [(1, 200, 1), (2, 100, 1), (3, 80, 0)]
    assert (council.seats, council.filled) == (2, 2)
    assert council.areas["529320"] == (400, 150, 140, {1: 80, 2: 40, 3: 20})


def test_final_okrsky(final_2026):
    """Each contest's okrsky from the per-okrsok tables, withdrawn candidates'
    votes too; Bratislava's own in its districts' numbering, an okrsok copy
    found by the shares of its votes, the council's copies that fit either
    way left out."""
    live, _ = final_2026
    nitra = live.okrsky["okres/403"]
    assert nitra["starosta:500011"] == {
        "500011/1": (300, 130, 128, {1: 50, 2: 70, 3: 8}),
        "500011/2": (300, 120, 117, {1: 40, 2: 70, 3: 7}),
        "500011/3": (400, 170, 165, {1: 60, 2: 100, 3: 5}),
    }
    assert set(nitra["oz:500011/1"]) == {"500011/1", "500011/2"}
    assert nitra["oz:500011/2"] == {"500011/3": (400, 170, 160, {3: 100, 4: 90, 5: 80})}
    assert live.okrsky["city/BA"]["starosta:BA"] == {
        "528595/1": (100, 50, 48, {1: 30, 2: 16, 3: 2}),
        "529320/1": (200, 80, 78, {1: 50, 2: 24, 3: 4}),
        "528595/2": (300, 150, 140, {1: 100, 2: 36, 3: 4}),
    }
    assert live.okrsky["city/BA"]["oz:BA/1"] == {
        "528595/2": (300, 150, 139, {1: 70, 2: 69})
    }
    regional = live.okrsky["kraj/1"]
    assert regional["predseda:1"]["529320/3"] == (100, 40, 39, {1: 20, 2: 19})
    assert len(regional["zsk:1/1"]) == 5


def test_final_written(final_2026, tmp_path):
    live, elections = final_2026
    only_oso = results.finalize(live, ["oso"], {"oso", "osk"})
    assert only_oso.phase == "partial"
    assert only_oso.source["osk"]["counted"] is None
    merged = results.finalize(live, elections, {"oso", "osk"})
    assert merged.phase == "final"
    # The municipal contests alone compared with an election before.
    merged.past = {
        "oso": results.Past(
            "2022-10-29",
            {"528595/1": results.SAME, "528595/2": results.UNKNOWN},
            {
                "starosta:BA": {
                    "528595/1": (90, 40, 39, {1: 20}),
                    "529320": (180, 70, 69, {1: 30, 3: 5}),
                }
            },
        )
    }
    out = tmp_path / "results"
    assert results.write(out, merged, DIVISIONS, NOW) is not None
    assert results.check(out, EXPECT) == []
    again = results.read_live(out)
    assert {c: r.to_json() for c, r in again.records().items()} == {
        c: r.to_json() for c, r in merged.records().items()
    }
    assert again.okrsky == merged.okrsky
    assert again.past == merged.past
    # Figures of an okrsok of unknown method, of a number not on the
    # ballot, of an obec outside the contest are caught.
    merged.past["oso"].contests["starosta:BA"] |= {
        "528595/2": (1, 1, 1, {}),
        "529320": (1, 1, 1, {9: 1}),
        "500011": (1, 1, 1, {}),
    }
    assert results.write(tmp_path / "bad", merged, DIVISIONS, NOW) is not None
    assert results.check(tmp_path / "bad", EXPECT) == [
        "okrsky/city/BA: starosta:BA: past 500011 (no okrsok of known method or"
        " obec of the contest)",
        "okrsky/city/BA: starosta:BA: past 528595/2 (no okrsok of known method or"
        " obec of the contest)",
        "okrsky/city/BA: starosta:BA: past 529320 (malformed, or votes of no"
        " candidate)",
    ]


def test_country_wide_past_split_by_okrsok_file():
    """A country-wide contest's okrsky span one okrsok file per kraj: each
    file's past has only its own units of it, else every file would carry
    units of no okrsok of its own. A municipal contest's past, in one file,
    stays whole, so that the check sees a unit outside the file."""
    past = results.Past(
        "2019-03-16",
        {"528595/1": results.SAME, "500011/1": results.SAME},
        {
            "prezident:SK/1": {
                "528595/1": (90, 40, 39, {1: 20}),
                "529320": (180, 70, 69, {1: 30}),
                "500011/1": (50, 20, 19, {1: 10}),
                "500020": (60, 30, 29, {1: 15}),
            },
            "starosta:BA": {
                "528595/1": (90, 40, 39, {1: 20}),
                "500011": (1, 1, 1, {}),
            },
        },
    )
    contests = ["prezident:SK/1", "starosta:BA"]
    ba = results._past_json(past, contests, ["528595/1", "529320/1"])
    assert ba["okrsky"] == {"528595/1": results.SAME}
    assert set(ba["contests"]["prezident:SK/1"]) == {"528595/1", "529320"}
    assert set(ba["contests"]["starosta:BA"]) == {"528595/1", "500011"}
    nitra = results._past_json(past, ["prezident:SK/1"], ["500011/1", "500020/1"])
    assert set(nitra["contests"]["prezident:SK/1"]) == {"500011/1", "500020"}
    # A file with no unit of the contest gets no past of it at all.
    assert results._past_json(past, ["prezident:SK/1"], ["503011/1"]) == {}


def test_each_half_compared_with_the_newest_election_that_held_it():
    """Before 2022 the municipal and the regional elections were held apart:
    2022's municipal contests are compared with 2018's, its regional ones
    with 2017's, and 2026's both with 2022's; another kind's with the newest
    of its kind, a by-election's with none."""
    cfg = config.load()

    def earlier(slug: str) -> list[tuple[str, tuple[str, ...]]]:
        compared = cli._earlier(cfg, cfg.election(slug))
        return [(e.slug, halves) for e, halves in compared]

    assert earlier("2022") == [("2017", ("osk",)), ("2018", ("oso",))]
    assert earlier("2026") == [("2022", ("oso", "osk"))]
    assert earlier("2018") == []
    assert earlier("2017") == []
    assert earlier("2024-prezident") == [("2019-prezident", ())]
    assert earlier("2026-03") == []
    assert cli._past_days(cfg, cfg.election("2022"), ["oso", "osk"]) == {
        "oso": "2018-11-10",
        "osk": "2017-11-04",
    }
    assert cli._past_days(cfg, cfg.election("2024-prezident"), ["prez1", "prez2"]) == {
        "prez1": "2019-03-16",
        "prez2": "2019-03-16",
    }


def test_halves_compared_with_elections_of_their_own(big_ref, tmp_path):
    """Each half's okrsok files get the past of the election it is compared
    with, read back apart, and the check holds each file to its own."""
    days = {"oso": "2018-11-10", "osk": "2017-11-04"}
    live = results.fake(big_ref, "final", past=days)
    assert live.past["oso"].day == "2018-11-10"
    assert live.past["osk"].day == "2017-11-04"
    assert set(live.part({"osk"}).okrsky) == {p for p in live.okrsky if "kraj/" in p}
    out = tmp_path / "out"
    expect = dataclasses.replace(EXPECT, past=days)
    assert results.write(out, live, DIVISIONS, NOW, expect=expect) is not None
    okrsky_dir = out / results.OKRSKY_DIR
    written = {
        p.relative_to(okrsky_dir).as_posix(): past
        for p in okrsky_dir.rglob("*.json")
        if (past := json.loads(p.read_bytes())["past"])
    }
    assert {p["day"] for f, p in written.items() if f.startswith("kraj/")} == {
        "2017-11-04"
    }
    assert {p["day"] for f, p in written.items() if not f.startswith("kraj/")} == {
        "2018-11-10"
    }
    assert results.read_live(out).past == live.past
    # Held to 2026's days (both 2022's), every file with a past is refused;
    # with no regional election before, every kraj's.
    wrong = results.check(out, EXPECT)
    assert len(wrong) == len(written)
    assert all("past day" in p for p in wrong)
    halved = dataclasses.replace(EXPECT, past={"oso": "2018-11-10"})
    refused = results.check(out, halved)
    assert refused and all(p.startswith("okrsky/kraj/") for p in refused)
    assert all(p.endswith("compared with (none)") for p in refused)


# Two kraje of four obce; Nitra (500011) split into two council obvody.
UNITS = results.Divisions(
    {"500011": "403", "500020": "403", "500038": "404", "528595": "101"},
    {"500011": "4", "500020": "4", "500038": "4", "528595": "1"},
    frozenset({"500011"}),
)


def tamper(directory: Path, path: str, change) -> None:
    """Change results file *path* in *directory* by *change*, and its hash too."""
    file = directory / f"{path}.json"
    content = json.loads(file.read_bytes())
    change(content)
    body = json.dumps(content).encode()
    file.write_bytes(body)
    status = json.loads((directory / results.STATUS_FILE).read_bytes())
    status["files"][path] = hashlib.sha256(body).hexdigest()[:8]
    (directory / results.STATUS_FILE).write_text(json.dumps(status))


def test_country_wide_units_are_their_obce_summed(tmp_path):
    """A country-wide contest's kraje and okresy are written with it, each its
    obce's areas summed; the check refuses a sum that is not."""
    areas = {
        "500011": (100, 50, 48, {1: 30, 2: 18}),
        "500020": (60, 30, 29, {1: 9, 2: 20}),
        "500038": (40, 20, 20, {1: 5, 2: 15}),
        "528595": (80, 40, 40, {1: 25, 2: 15}),
    }
    record = results.Record(
        "final", None, 280, 140, 137, 1, 1, [(1, 69, 1), (2, 68, None)], areas
    )
    live = results.Live("final", results.no_sources({"prez1"}))
    live.add("country", "prezident:SK/1", record)
    out = tmp_path / "out"
    expect = results.Expect(frozenset({"prez1"}), {}, {}, UNITS)
    assert results.write(out, live, UNITS, NOW, expect=expect) is not None
    written = json.loads((out / "country.json").read_bytes())
    assert written["contests"]["prezident:SK/1"]["units"] == {
        "kraj": {
            "1": [80, 40, 40, {"1": 25, "2": 15}],
            "4": [200, 100, 97, {"1": 44, "2": 53}],
        },
        "okres": {
            "101": [80, 40, 40, {"1": 25, "2": 15}],
            "403": [160, 80, 77, {"1": 39, "2": 38}],
            "404": [40, 20, 20, {"1": 5, "2": 15}],
        },
    }
    assert results.read_live(out).records()["prezident:SK/1"] == record

    def wrong(content: dict) -> None:
        content["contests"]["prezident:SK/1"]["units"]["okres"]["403"][0] += 1

    tamper(out, "country", wrong)
    assert results.check(out, expect) == [
        "country: prezident:SK/1: units not the areas summed: okres 403"
    ]


def test_country_wide_origins_are_their_okrsky_ranked(tmp_path):
    """A country-wide contest of persons has, per candidate, the okrsky of
    all its kraj files with the most of their votes and with the highest
    share (of the okrsky of 30 valid ballots or more, there being two),
    only where they got votes; the check refuses others."""
    okrsky = {
        "country/4": {
            "500011/1": (100, 60, 60, {1: 40, 2: 20}),
            "500011/2": (50, 25, 25, {1: 5, 2: 20}),
            "500038/1": (20, 10, 10, {1: 10}),
        },
        "country/1": {"528595/1": (90, 45, 45, {1: 15, 2: 30})},
    }
    record = results.Record(
        "final", None, 260, 140, 140, 1, 1, [(1, 70, 1), (2, 70, None)]
    )
    live = results.Live("final", results.no_sources({"prez1"}))
    live.add("country", "prezident:SK/1", record)
    for path, areas in okrsky.items():
        live.add_okrsky(path, "prezident:SK/1", areas)
    out = tmp_path / "out"
    expect = results.Expect(frozenset({"prez1"}), {}, {}, UNITS)
    assert results.write(out, live, UNITS, NOW, expect=expect) is not None
    written = json.loads((out / "country.json").read_bytes())
    assert written["contests"]["prezident:SK/1"]["origins"] == {
        "1": [
            [
                ["500011/1", 40, 60],
                ["528595/1", 15, 45],
                ["500038/1", 10, 10],
                ["500011/2", 5, 25],
            ],
            [["500011/1", 40, 60], ["528595/1", 15, 45]],
        ],
        "2": [
            [["528595/1", 30, 45], ["500011/1", 20, 60], ["500011/2", 20, 25]],
            [["528595/1", 30, 45], ["500011/1", 20, 60]],
        ],
    }

    def wrong(content: dict) -> None:
        content["contests"]["prezident:SK/1"]["origins"]["1"][0][0][1] = 41

    tamper(out, "country", wrong)
    assert results.check(out, expect) == [
        "country: prezident:SK/1: origins not those of its okrsky"
    ]


def test_bratislava_and_kosice_as_wholes_are_in_no_okres():
    divisions = results.Divisions.of(
        {
            "contests": [],
            "obce": [
                {"code": "BA", "name": "Bratislava", "kraj": "1"},
                {"code": "528595", "name": "Staré Mesto", "okres": "101", "kraj": "1"},
            ],
        },
        (),
    )
    units = results.area_units(
        {"BA": (10, 5, 5, {1: 5}), "528595": (8, 4, 4, {1: 4})}, divisions
    )
    assert units == {
        "kraj": {"1": (18, 9, 9, {1: 9})},
        "okres": {"101": (8, 4, 4, {1: 4})},
    }


def test_split_obce_of_several_council_contests_or_part_of_a_larger_council():
    """An obec is split into several council obvody where it has several
    council contests, or a by-election's are part of a larger council
    (`addresses.council_parts`: obvod 3, or obvod 1 of a council its term
    elected in several); one of obvod 1 alone of a council elected in one
    is taken for the whole."""
    contests = [
        {"id": "oz:500011/1", "kind": "oz", "area": "500011", "obvod": 1},
        {"id": "oz:500011/2", "kind": "oz", "area": "500011", "obvod": 2},
        {"id": "oz:500020/3", "kind": "oz", "area": "500020", "obvod": 3, "seats": 1},
        {"id": "oz:500038/1", "kind": "oz", "area": "500038", "obvod": 1, "seats": 1},
        {"id": "oz:500046/1", "kind": "oz", "area": "500046", "obvod": 1, "seats": 5},
        {"id": "starosta:500038", "kind": "starosta", "area": "500038"},
    ]
    parts = addresses.part_councils(contests, {"500038"})
    divisions = results.Divisions.of({"contests": contests, "obce": []}, parts)
    assert divisions.split == {"500011", "500020", "500038"}


def test_lone_obvod_1_of_a_split_council_has_its_turnout(tmp_path):
    """Divina's by-election of 2026-03 elects obvod 1 of the three of 2022:
    its turnout is that obvod's (``councils``), as the app draws it, and the
    check refuses results without it."""
    live = results.Live("final", results.no_sources({"oso"}))
    live.add("okres/404", "oz:500038/1", council({1: 10}, 40, 20))
    split = dataclasses.replace(UNITS, split=frozenset({"500038"}))
    expect = results.Expect(frozenset({"oso"}), {}, {}, split)
    out = rewritten(tmp_path, "split", live, expect)
    turnout = json.loads((out / "turnout.json").read_bytes())["municipal"]
    assert turnout["councils"] == {"500038/1": [40, 20]}
    whole = tmp_path / "whole"
    results.write(whole, live, UNITS, NOW)
    assert results.check(whole, expect) == [
        "turnout: municipal not the turnout of the area files"
    ]


def regional_live(phase: str, president: dict) -> results.Live:
    """Return results of kraj 4 of obvod 1 (500011, 500020) and 2 (500038)."""
    live = results.Live(phase, results.no_sources({"osk"}))
    status = "final" if phase == "final" else "partial"
    for n, areas in ((1, ("500011", "500020")), (2, ("500038",))):
        council = {code: (50, 25, 20, {1: 20}) for code in areas}
        record = results.Record(
            status, None, None, None, None, 1, 1, [(1, 20 * len(areas), 1)], council
        )
        live.add("kraj/4", f"zsk:4/{n}", record)
    record = results.Record(
        status, None, 200, 100, 97, 1, 1, [(1, 44, 1), (2, 53, None)], president
    )
    live.add("kraj/4", "predseda:4", record)
    return live


def test_regional_president_units_are_its_obvody(tmp_path):
    """A regional president is written with its regional obvody too: final,
    each the obce of its council contest's areas summed; at night, the
    obvody counted as wholes. The check refuses a sum that is not."""
    final = {
        "500011": (100, 50, 48, {1: 30, 2: 18}),
        "500020": (60, 30, 29, {1: 9, 2: 20}),
        "500038": (40, 20, 20, {1: 5, 2: 15}),
    }
    out = tmp_path / "final"
    expect = results.Expect(frozenset({"osk"}), {}, {}, UNITS)
    live = regional_live("final", final)
    assert results.write(out, live, UNITS, NOW, expect=expect) is not None
    written = json.loads((out / "kraj/4.json").read_bytes())["contests"]
    assert written["predseda:4"]["units"] == {
        "zsk": {
            "1": [160, 80, 77, {"1": 39, "2": 38}],
            "2": [40, 20, 20, {"1": 5, "2": 15}],
        }
    }
    assert "units" not in written["zsk:4/1"]

    def wrong(content: dict) -> None:
        content["contests"]["predseda:4"]["units"]["zsk"]["2"][1] += 1

    tamper(out, "kraj/4", wrong)
    assert results.check(out, expect) == [
        "kraj/4: predseda:4: units not the areas summed: zsk 2"
    ]
    # An obvod with an obec missing from the areas is not summed short.
    short = results.obvod_units(
        {"500011": final["500011"], "500038": final["500038"]},
        {"500011": "1", "500020": "1", "500038": "2"},
        final=True,
    )
    assert short == {"2": final["500038"]}
    night = {"obvod:2": (40, 20, 20, {1: 5, 2: 15}), "500038": final["500038"]}
    out = tmp_path / "night"
    assert results.write(out, regional_live("partial", night), UNITS, NOW) is not None
    written = json.loads((out / "kraj/4.json").read_bytes())["contests"]
    assert written["predseda:4"]["units"] == {
        "zsk": {"2": [40, 20, 20, {"1": 5, "2": 15}]}
    }
    assert results.check(out, expect) == []


def test_regional_president_past_by_obvod():
    """A regional president's past is summed by regional obvod too: each of
    its obce by its own figures then, else its okrsky's, and an obvod only
    where all are known."""
    past = {
        "day": "2022-10-29",
        "okrsky": {},
        "contests": {
            "predseda:4": {
                "500011": [100, 50, 48, {"1": 30, "2": 18}],
                "500020/1": [30, 15, 15, {"1": 5, "2": 10}],
                "500020/2": [30, 15, 14, {"1": 4, "2": 10}],
            }
        },
        "totals": {"predseda:4": [300, 150, 145, {"1": 60, "2": 85}]},
    }
    okrsky = {"predseda:4": ["500011/1", "500020/1", "500020/2", "500038/1"]}
    obvody = {"500011": "1", "500020": "1", "500038": "2"}
    units = results.past_units(past, okrsky, {}, {}, UNITS, obvody)
    assert units == {
        "predseda:4": {
            "obec": {"500020": [1, [60, 30, 29, {"1": 9, "2": 20}]]},
            "zsk": {"1": [1, [160, 80, 77, {"1": 39, "2": 38}]]},
        }
    }


def test_preference_order():
    """Those whose preference votes reach the quota of the party's votes go
    first, by their votes, a tie by list position; then the rest by
    position. Exactly the quota reaches it; one vote short does not."""
    votes = {1: 10, 2: 30, 3: 29, 4: 30, 5: 2}
    assert results.preference_order(votes, 1000, 3.0) == [2, 4, 1, 3, 5]
    assert results.preference_order(votes, 1000, 10.0) == [1, 2, 3, 4, 5]
    assert results.preference_order(votes, 900, 3.0) == [2, 4, 3, 1, 5]


def test_list_elected_follow_the_preference_rule(tmp_path):
    """A final party list's elected are the first by the preference rule on
    the whole list's votes; the check refuses others."""
    candidates = [(1, 10, 0), (2, 30, 1), (3, 29, 0), (4, 30, 1), (5, 2, 0)]
    record = results.Record("final", None, None, None, 1000, 2, 2, candidates)
    live = results.Live("final", results.no_sources({"nrsr"}))
    live.add("list/1", "nrsr:SK/1", record)
    out = tmp_path / "out"
    expect = results.Expect(frozenset({"nrsr"}), {}, {"nrsr:SK": 3.0}, UNITS)
    assert results.write(out, live, UNITS, NOW, expect=expect) is not None

    def wrong(content: dict) -> None:
        rows = content["contests"]["nrsr:SK/1"]["candidates"]
        for row in rows:
            row[2] = 1 if row[0] in (1, 2) else 0

    tamper(out, "list/1", wrong)
    assert results.check(out, expect) == [
        "list/1: nrsr:SK/1: the elected are not the first by the preference rule"
    ]


def test_past_by_unit(tmp_path):
    """The okrsok files' past has the election before summed in the units
    the app shows that are made of okrsky: an obec without figures of its
    own, a country-wide contest's okres and kraj, a council obvod (grouped by
    the council contests' okrsky), a council's whole. Each sum has the least
    certain method of its parts and is left out unless all are known."""
    now = {
        "500011/1": (100, 50, 50, {1: 30, 2: 20}),
        "500011/2": (100, 60, 60, {1: 20, 2: 40}),
        "500011/3": (100, 40, 40, {1: 10, 2: 30}),
    }
    live = results.Live("final", results.no_sources({"prez1", "oso"}))
    live.add(
        "country",
        "prezident:SK/1",
        results.Record(
            "final",
            None,
            450,
            225,
            225,
            1,
            1,
            [(2, 125, 1), (1, 100, None)],
            {
                "500011": (300, 150, 150, {1: 60, 2: 90}),
                "500020": (50, 25, 25, {1: 15, 2: 10}),
                "500038": (100, 50, 50, {1: 25, 2: 25}),
            },
        ),
    )
    live.add_okrsky(
        "country/4",
        "prezident:SK/1",
        now
        | {
            "500020/1": (50, 25, 25, {1: 15, 2: 10}),
            "500038/1": (60, 30, 30, {1: 20, 2: 10}),
            "500038/2": (40, 20, 20, {1: 5, 2: 15}),
        },
    )
    mayor = results.Record(
        "final", None, 300, 150, 150, 1, 1, [(1, 60, None), (2, 90, 1)]
    )
    live.add("okres/403", "starosta:500011", mayor)
    live.add_okrsky("okres/403", "starosta:500011", dict(now))
    for obvod, keys, seats in ((1, ["500011/1", "500011/2"], 2), (2, ["500011/3"], 1)):
        okrsky = {k: now[k] for k in keys}
        total = results.sum_areas(okrsky.values())
        council = f"oz:500011/{obvod}"
        votes = [(n, x, 1) for n, x in total[3].items()]
        live.add(
            "okres/403",
            council,
            results.Record("final", None, *total[:3], seats, seats, votes),
        )
        live.add_okrsky("okres/403", council, okrsky)
    then = {
        "500011/1": (90, 40, 40, {1: 25, 2: 15}),
        "500011/2": (110, 50, 50, {1: 20, 2: 30}),
        "500011/3": (95, 45, 45, {1: 15, 2: 30}),
    }
    nitra = (295, 135, 135, {1: 60, 2: 75})
    # One election before of both kinds, made up to compare them alike.
    past = results.Past(
        "2019-03-16",
        {
            "500011/1": results.SAME,
            "500011/2": results.APPROXIMATE,
            "500011/3": results.IDENTITY,
            "500038/1": results.SAME,
            "500038/2": results.UNKNOWN,
        },
        {
            "prezident:SK/1": then
            | {
                "500020": (48, 20, 20, {1: 12, 2: 8}),
                "500038/1": (55, 25, 25, {1: 10, 2: 15}),
            },
            "starosta:500011": then | {"500011": nitra},
            "oz:500011/1": {k: then[k] for k in ("500011/1", "500011/2")},
            "oz:500011/2": {"500011/3": then["500011/3"]},
        },
        {
            "prezident:SK/1": (500, 230, 230, {1: 100, 2: 130}),
            "starosta:500011": nitra,
        },
    )
    live.past = {"prez1": past, "oso": past}
    out = tmp_path / "out"
    compared = {"prez1": "2019-03-16", "oso": "2019-03-16"}
    expect = results.Expect(frozenset({"prez1", "oso"}), {}, {}, UNITS, compared)
    assert results.write(out, live, UNITS, NOW, expect=expect) is not None

    def units(path: str) -> dict:
        file = out / results.OKRSKY_DIR / f"{path}.json"
        return json.loads(file.read_bytes())["past"]["units"]

    approximate, identity = results.APPROXIMATE, results.IDENTITY
    obvody = {
        "500011/1": [approximate, [200, 90, 90, {"1": 45, "2": 45}]],
        "500011/2": [identity, [95, 45, 45, {"1": 15, "2": 30}]],
    }
    # Nitra by its okrsky, its okres with 500020's own figures; not 500038,
    # one of whose okrsky is not known, nor its okres and kraj.
    assert units("country/4") == {
        "prezident:SK/1": {
            "obec": {"500011": [approximate, [295, 135, 135, {"1": 60, "2": 75}]]},
            "okres": {"403": [approximate, [343, 155, 155, {"1": 72, "2": 83}]]},
            "obvod": obvody,
        }
    }
    # The mayor's obvody; a council's whole, but no obvod of its own obec.
    assert units("okres/403") == {
        "starosta:500011": {"obvod": obvody},
        "oz:500011/1": {"all": obvody["500011/1"]},
        "oz:500011/2": {"all": obvody["500011/2"]},
    }

    def wrong(content: dict) -> None:
        content["past"]["units"]["prezident:SK/1"]["obvod"]["500011/2"][0] = 1

    tamper(out, f"{results.OKRSKY_DIR}/country/4", wrong)
    assert results.check(out, expect) == [
        "okrsky/country/4: prezident:SK/1: past units not those of its okrsky then"
    ]


def rewritten(tmp_path: Path, name: str, live: results.Live, expect) -> Path:
    """Write *live* to a directory of its own, *name*, keeping the contract."""
    out = tmp_path / name
    assert results.write(out, live, expect.divisions, NOW, expect=expect) is not None
    return out


def council(votes: dict[int, int], eligible: int, voters: int) -> results.Record:
    """A final council record of one seat, its candidates' *votes* the valid."""
    valid = sum(votes.values())
    rows = [(n, x, 1) for n, x in votes.items()]
    return results.Record("final", None, eligible, voters, valid, 1, 1, rows)


def test_okrsok_units_are_their_okrsky_summed(tmp_path):
    """An okrsok file has the units the app narrows a contest to that are
    made of its okrsky: each council obvod of an obec split into several
    (not for that obec's own councils), and of a regional, a city or a
    country-wide contest without areas each obec. The check refuses a sum
    that is not."""
    okrsky = {
        "500011/1": (100, 50, 50, {1: 30, 2: 20}),
        "500011/2": (100, 60, 60, {1: 20, 2: 40}),
        "500011/3": (100, 40, 40, {1: 10, 2: 30}),
    }
    live = results.Live("final", results.no_sources({"oso", "osk"}))
    mayor = results.Record(
        "final", None, 300, 150, 150, 1, 1, [(1, 60, None), (2, 90, 1)]
    )
    live.add("okres/403", "starosta:500011", mayor)
    live.add_okrsky("okres/403", "starosta:500011", dict(okrsky))
    for obvod, keys in ((1, ["500011/1", "500011/2"]), (2, ["500011/3"])):
        part = {k: okrsky[k] for k in keys}
        total = results.sum_areas(part.values())
        live.add("okres/403", f"oz:500011/{obvod}", council(total[3], *total[:2]))
        live.add_okrsky("okres/403", f"oz:500011/{obvod}", part)
    president = results.Record(
        "final", None, 350, 175, 175, 1, 1, [(1, 75, 1), (2, 100, None)]
    )
    live.add("kraj/4", "predseda:4", president)
    live.add_okrsky(
        "kraj/4", "predseda:4", okrsky | {"500020/1": (50, 25, 25, {1: 15, 2: 10})}
    )
    expect = results.Expect(frozenset({"oso", "osk"}), {}, {}, UNITS)
    out = rewritten(tmp_path, "out", live, expect)

    def units(path: str) -> dict:
        file = out / results.OKRSKY_DIR / f"{path}.json"
        return json.loads(file.read_bytes())["units"]

    obvody = {
        "500011/1": [200, 110, 110, {"1": 50, "2": 60}],
        "500011/2": [100, 40, 40, {"1": 10, "2": 30}],
    }
    # The mayor's obvody; none of a council of its own obec.
    assert units("okres/403") == {"starosta:500011": {"obvod": obvody}}
    assert units("kraj/4") == {
        "predseda:4": {
            "obvod": obvody,
            "obec": {
                "500011": [300, 150, 150, {"1": 60, "2": 90}],
                "500020": [50, 25, 25, {"1": 15, "2": 10}],
            },
        }
    }
    # With areas, an obec's figures are its own there: none summed.
    figures = {"predseda:4": dict(okrsky)}
    councils = {"500011/1": "500011/1", "500011/3": "500011/2"}
    assert results.okrsok_units(figures, {"predseda:4": True}, councils) == {
        "predseda:4": {
            "obvod": {
                "500011/1": okrsky["500011/1"],
                "500011/2": okrsky["500011/3"],
            }
        }
    }

    def wrong(content: dict) -> None:
        content["units"]["predseda:4"]["obec"]["500020"][1] += 1

    tamper(out, f"{results.OKRSKY_DIR}/kraj/4", wrong)
    assert results.check(out, expect) == [
        "okrsky/kraj/4: predseda:4: units not those of its okrsky"
    ]


def test_party_list_preference_votes_summed(tmp_path):
    """A party's list has its persons' preference votes summed beside the
    party's votes: the record's ``preferences``, and a fifth figure of each
    of its areas, units and okrsky. The check refuses one that is not."""
    areas = {
        "500011": (100, 50, 30, {1: 20, 2: 8}),
        "528595": (80, 40, 20, {1: 10, 2: 4}),
    }
    record = results.Record(
        "final", None, 180, 90, 50, 1, 1, [(1, 30, 1), (2, 12, 0)], areas
    )
    live = results.Live("final", results.no_sources({"nrsr"}))
    live.add("list/1", "nrsr:SK/1", record)
    live.add_okrsky("list/1/4", "nrsr:SK/1", {"500011/1": areas["500011"]})
    expect = results.Expect(frozenset({"nrsr"}), {"nrsr:SK": 4}, {}, UNITS)
    out = rewritten(tmp_path, "out", live, expect)
    written = json.loads((out / "list/1.json").read_bytes())["contests"]["nrsr:SK/1"]
    assert written["preferences"] == 42
    assert written["areas"] == {
        "500011": [100, 50, 30, {"1": 20, "2": 8}, 28],
        "528595": [80, 40, 20, {"1": 10, "2": 4}, 14],
    }
    assert written["units"]["kraj"] == {
        "1": [80, 40, 20, {"1": 10, "2": 4}, 14],
        "4": [100, 50, 30, {"1": 20, "2": 8}, 28],
    }
    okrsok = out / results.OKRSKY_DIR / "list/1/4.json"
    assert json.loads(okrsok.read_bytes())["contests"]["nrsr:SK/1"] == {
        "500011/1": [100, 50, 30, {"1": 20, "2": 8}, 28]
    }
    # Read back without them, as they are made again when written.
    assert results.read_live(out).records()["nrsr:SK/1"] == record

    def whole(content: dict) -> None:
        content["contests"]["nrsr:SK/1"]["preferences"] = 41

    def area(content: dict) -> None:
        content["contests"]["nrsr:SK/1"]["areas"]["528595"][4] = 15

    def unit(content: dict) -> None:
        content["contests"]["nrsr:SK/1"]["units"]["okres"]["101"][4] = 15

    def okrsok_sum(content: dict) -> None:
        content["contests"]["nrsr:SK/1"]["500011/1"][4] = 27

    def missing(content: dict) -> None:
        del content["contests"]["nrsr:SK/1"]["preferences"]

    prefix = "list/1: nrsr:SK/1: "
    for name, path, change, problem in (
        (
            "whole",
            "list/1",
            whole,
            "preference votes not its persons' summed: the list",
        ),
        ("area", "list/1", area, "preference votes not its persons' summed: 528595"),
        ("unit", "list/1", unit, "units not the areas summed: okres 101"),
        ("missing", "list/1", missing, "preferences None"),
    ):
        out = rewritten(tmp_path, name, live, expect)
        tamper(out, path, change)
        assert results.check(out, expect) == [prefix + problem], name
    out = rewritten(tmp_path, "okrsok", live, expect)
    tamper(out, f"{results.OKRSKY_DIR}/list/1/4", okrsok_sum)
    assert results.check(out, expect) == [
        "okrsky/list/1/4: nrsr:SK/1: preference votes not its persons' summed: 500011/1"
    ]


# Bratislava and two of its districts, in kraj 1; Nitra in kraj 4.
CITY = results.Divisions(
    {"BA": "", "528595": "101", "529320": "102", "500011": "403"},
    {"BA": "1", "528595": "1", "529320": "1", "500011": "4"},
    frozenset(),
)


def city_live(regional: bool) -> results.Live:
    """Bratislava's mayor by district; with the *regional* contests, the
    districts' regional obvody (1 and 2)."""
    live = results.Live("final", results.no_sources({"oso", "osk"}))
    districts = {
        "528595": (100, 50, 50, {1: 30, 2: 20}),
        "529320": (200, 80, 80, {1: 50, 2: 30}),
    }
    mayor = results.Record(
        "final", None, 300, 130, 130, 1, 1, [(1, 80, 1), (2, 50, None)], districts
    )
    live.add("city/BA", "starosta:BA", mayor)
    if regional:
        for n, code in enumerate(districts, 1):
            record = council({1: 30}, 0, 0)
            record.eligible = record.voters = None
            record.areas = {code: (None, None, 30, {1: 30})}
            live.add("kraj/1", f"zsk:1/{n}", record)
    return live


def test_city_contest_coarse_units(tmp_path):
    """A contest of Bratislava or Košice with areas is summed by the coarsest
    units the map colours: its districts' regional obvody, or the okresy
    where the election has none. The check refuses a sum that is not."""
    expect = results.Expect(frozenset({"oso", "osk"}), {}, {}, CITY)
    out = rewritten(tmp_path, "regional", city_live(regional=True), expect)

    def units(directory: Path) -> dict:
        content = json.loads((directory / "city/BA.json").read_bytes())
        return content["contests"]["starosta:BA"]["units"]

    assert units(out) == {
        "zsk": {
            "1": [100, 50, 50, {"1": 30, "2": 20}],
            "2": [200, 80, 80, {"1": 50, "2": 30}],
        }
    }
    alone = rewritten(tmp_path, "alone", city_live(regional=False), expect)
    assert units(alone) == {
        "okres": {
            "101": [100, 50, 50, {"1": 30, "2": 20}],
            "102": [200, 80, 80, {"1": 50, "2": 30}],
        }
    }

    def wrong(content: dict) -> None:
        content["contests"]["starosta:BA"]["units"]["zsk"]["2"][0] += 1

    tamper(out, "city/BA", wrong)
    assert results.check(out, expect) == [
        "city/BA: starosta:BA: units not the areas summed: zsk 2"
    ]


def mayor(eligible: int | None, voters: int | None) -> results.Record:
    return results.Record("final", None, eligible, voters, 20, 1, 1, [(1, 20, 1)])


def test_turnout_file(tmp_path):
    """The turnout of the elections of many contests is summed once: each
    municipality's (its mayor's, else its council obvody's summed), each
    council obvod of one split into several, the whole and the coarsest
    units; Bratislava's and Košice's likewise, by their districts; the
    regional presidents' whole. The check refuses a sum that is not, and
    the file missing."""
    live = results.Live("final", results.no_sources({"oso", "osk"}))
    # Nitra (split) elects no mayor: its obvody summed. 500020's mayor
    # counts, not its council; 500038's mayor has no figures: its council.
    live.add("okres/403", "oz:500011/1", council({1: 10}, 100, 50))
    live.add("okres/403", "oz:500011/2", council({1: 10}, 60, 30))
    live.add("okres/403", "starosta:500020", mayor(50, 25))
    live.add("okres/403", "oz:500020/1", council({1: 10}, 51, 26))
    live.add("okres/404", "starosta:500038", mayor(None, None))
    live.add("okres/404", "oz:500038/1", council({1: 10}, 40, 20))
    expect = results.Expect(frozenset({"oso", "osk"}), {}, {}, UNITS)
    municipal = {
        "total": [250, 125],
        "obce": {"500011": [160, 80], "500020": [50, 25], "500038": [40, 20]},
        "councils": {"500011/1": [100, 50], "500011/2": [60, 30]},
    }
    out = rewritten(tmp_path, "municipal", live, expect)
    assert json.loads((out / "turnout.json").read_bytes()) == {
        "municipal": municipal | {"okres": {"403": [210, 105], "404": [40, 20]}}
    }
    # With the regional contests, by regional obvod.
    for n, codes in ((1, ("500011", "500020")), (2, ("500038",))):
        record = council({1: 10}, 0, 0)
        record.eligible = record.voters = None
        record.areas = {code: (None, None, 10, {1: 10}) for code in codes}
        live.add("kraj/4", f"zsk:4/{n}", record)
    live.add("kraj/4", "predseda:4", mayor(250, 125))
    out = rewritten(tmp_path, "both", live, expect)
    assert json.loads((out / "turnout.json").read_bytes()) == {
        "municipal": municipal | {"zsk": {"4/1": [210, 105], "4/2": [40, 20]}},
        "regional": {"total": [250, 125]},
    }
    city = rewritten(
        tmp_path,
        "city",
        city_live(regional=True),
        results.Expect(frozenset({"oso", "osk"}), {}, {}, CITY),
    )
    assert json.loads((city / "turnout.json").read_bytes()) == {
        "city": {
            "total": [300, 130],
            "obce": {"BA": [300, 130]},
            "zsk": {"1/1": [100, 50], "1/2": [200, 80]},
        }
    }

    def wrong(content: dict) -> None:
        content["municipal"]["zsk"]["4/2"][1] += 1

    tamper(out, results.TURNOUT_FILE, wrong)
    assert results.check(out, expect) == [
        "turnout: municipal not the turnout of the area files"
    ]
    (out / "turnout.json").unlink()
    status = json.loads((out / results.STATUS_FILE).read_bytes())
    del status["files"][results.TURNOUT_FILE]
    (out / results.STATUS_FILE).write_text(json.dumps(status))
    assert results.check(out, expect) == [
        "turnout: missing, though the area files have turnouts"
    ]


def test_past_of_the_coarse_units(tmp_path):
    """The election before of a contest of several obce without totals is,
    for the map, its obce's own figures then summed (``obce``, beside
    ``all``, its okrsky's); a city contest's, by its districts' regional
    obvody or else okresy. The check refuses a sum that is not."""
    then = {
        "500011/1": (60, 30, 30, {1: 20}),
        "500011/2": (40, 20, 20, {1: 5}),
        "500011": (100, 50, 50, {1: 25}),
        "500020": (50, 20, 20, {1: 10}),
    }
    live = results.Live("final", results.no_sources({"osk"}))
    okrsky = {
        "500011/1": (60, 30, 30, {1: 20}),
        "500011/2": (40, 20, 20, {1: 10}),
        "500020/1": (50, 25, 25, {1: 15}),
    }
    record = council({1: 45}, 150, 75)
    record.areas = {"500011": (100, 50, 30, {1: 30}), "500020": (50, 25, 15, {1: 15})}
    live.add("kraj/4", "zsk:4/1", record)
    live.add_okrsky("kraj/4", "zsk:4/1", okrsky)
    live.past = {
        "osk": results.Past(
            "2022-10-29",
            {"500011/1": results.SAME, "500011/2": results.APPROXIMATE},
            {"zsk:4/1": then},
        )
    }
    expect = results.Expect(frozenset({"osk"}), {}, {}, UNITS, {"osk": "2022-10-29"})
    out = rewritten(tmp_path, "out", live, expect)
    file = out / results.OKRSKY_DIR / "kraj/4.json"
    assert json.loads(file.read_bytes())["past"]["units"] == {
        "zsk:4/1": {
            "all": [results.APPROXIMATE, [150, 70, 70, {"1": 35}]],
            "obce": [results.SAME, [150, 70, 70, {"1": 35}]],
        }
    }

    def wrong(content: dict) -> None:
        content["past"]["units"]["zsk:4/1"]["obce"][1][1] += 1

    tamper(out, f"{results.OKRSKY_DIR}/kraj/4", wrong)
    assert results.check(out, expect) == [
        "okrsky/kraj/4: zsk:4/1: past units not those of its okrsky then"
    ]
    # A city contest's districts by regional obvod, each its own figures
    # then, else its okrsky's; else by okres.
    past = {
        "day": "2022-10-29",
        "okrsky": {"529320/1": results.SAME, "529320/2": results.IDENTITY},
        "contests": {
            "starosta:BA": {
                "528595": [100, 50, 50, {"1": 30}],
                "529320/1": [80, 40, 40, {"1": 20}],
                "529320/2": [70, 30, 30, {"1": 10}],
            }
        },
        "totals": {"starosta:BA": [250, 120, 120, {"1": 60}]},
    }
    keys = {"starosta:BA": ["528595/1", "529320/1", "529320/2"]}
    district = [results.IDENTITY, [150, 70, 70, {"1": 30}]]
    by = {"528595": "1", "529320": "2"}
    assert results.past_units(past, keys, {}, {}, CITY, by) == {
        "starosta:BA": {
            "obec": {"529320": district},
            "zsk": {"1": [results.SAME, [100, 50, 50, {"1": 30}]], "2": district},
        }
    }
    assert results.past_units(past, keys, {}, {}, CITY, {})["starosta:BA"]["okres"] == {
        "101": [results.SAME, [100, 50, 50, {"1": 30}]],
        "102": district,
    }


def test_check_catches_votes_beyond_the_valid_ballots(final_2026, tmp_path):
    """In a mayor's or president's unit counted the votes are the valid
    ballots; in a council's a candidate has no more votes than those, nor all
    together more than seats times as many: in the contest, its areas and its
    okrsky."""
    live, _ = final_2026
    mayor = live.files["city/BA"]["starosta:BA"]
    assert mayor.areas is not None
    e, v, valid, votes = mayor.areas["529320"]
    mayor.areas["529320"] = (e, v, valid, {**votes, 1: votes[1] + 1})
    nitra = live.okrsky["okres/403"]["starosta:500011"]
    e, v, valid, votes = nitra["500011/3"]
    nitra["500011/3"] = (e, v, valid - 1, votes)
    council = live.files["kraj/1"]["zsk:1/1"]
    council.valid = 150
    assert results.write(tmp_path, live, DIVISIONS, NOW) is not None
    problems = results.check(tmp_path, EXPECT)
    assert (
        "city/BA: starosta:BA: votes other than the valid ballots:"
        " 529320 (79 votes, 78 valid)"
    ) in problems
    assert (
        "okrsky/okres/403: starosta:500011: votes other than the valid ballots:"
        " 500011/3 (165 votes, 164 valid)"
    ) in problems
    assert (
        "kraj/1: zsk:1/1: votes beyond the valid ballots and 2 seats:"
        " the contest (200 votes at most, 380 in all, 150 valid)"
    ) in problems


def test_final_refuses_a_package_without_what_it_reads(tmp_path):
    tables = oso_tables()
    del tables["tab08e"]
    lacking = package(tmp_path / "a.zip", "OSO2026", tables)
    with pytest.raises(results.ResultsError, match="no table tab08e"):
        results.read_final([lacking])
    tables = oso_tables()
    tables["tab05d"] = [
        {k: v for k, v in r.items() if k != "Poznámka"} for r in tables["tab05d"]
    ]
    renamed = package(tmp_path / "b.zip", "OSO2026", tables)
    with pytest.raises(results.ResultsError, match="tab05d lacks"):
        results.read_final([renamed])


def files_of(directory: Path) -> dict[str, bytes]:
    return {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def results_project(tmp_path: Path, ref, monkeypatch) -> config.Config:
    """A project of the repository's configuration, the 2026 election built.

    Its final results packages pinned (``data/raw/``), its reference *ref*,
    and volbysr.sk on the night serving :func:`night_files`.
    """
    root = tmp_path / "project"
    shutil.copytree(REPO / "config", root / "config")
    # The web/ of the live part, the party logos among it.
    shutil.copytree(REPO / "web", root / "web")
    # The step's inputs name the libraries of uv.lock.
    shutil.copy(REPO / "uv.lock", root / "uv.lock")
    raw = root / "data" / "raw"
    for prefix, tables in (("OSO2026", oso_tables()), ("OSK2026", osk_tables())):
        name = f"results-{prefix.lower()}"
        (raw / name).mkdir(parents=True)
        package(raw / name / f"{prefix}_SK_csv.zip", prefix, tables)
    build_dir = root / "data" / "build" / "2026-10-24"
    (build_dir / "geo").mkdir(parents=True)
    (build_dir / "candidates.json").write_text(
        json.dumps(
            {"obce": make_data()[0]["obce"], "contests": make_data()[0]["contests"]}
        )
    )
    monkeypatch.setattr(results, "load_reference", lambda *_: ref)
    # Without the 2022 addresses and results: no comparison (test_crosswalk).
    monkeypatch.setattr(cli, "_earlier", lambda *_: [])
    monkeypatch.setattr(cli, "_client", lambda _cfg: FakeClient(night_files(ref)))
    # Without the okrsky of units-oso2026 and the rule sets: fakes of none.
    monkeypatch.setattr(cli.division, "okrsok_counts", lambda *_: {})
    monkeypatch.setattr(cli.obvody, "okrsok_rule_sets", lambda *_: {})
    monkeypatch.chdir(root)
    return config.load()


def test_make_writes_the_final_results_of_the_inputs(ref, tmp_path, monkeypatch):
    """The results step of `ems make` reads the election's pinned final
    results inputs (elections.toml `results`) into its results directory,
    the same files from the same packages; the night's commands write the
    live results apart and leave the step, its output and stamp alone."""
    cfg = results_project(tmp_path, ref, monkeypatch)
    assert cfg.latest.results.inputs == ("results-oso2026", "results-osk2026")
    build_dir = cfg.election_build_dir(cfg.latest)
    out = cfg.results_dir(cfg.latest)
    assert out == build_dir / "results"
    make = argparse.Namespace(force=False, election="2026")

    assert cli._run_results(make) == 0
    status = results.read_status(out)
    assert status is not None
    assert status["phase"] == "final"
    # Written as of the packages' data, not of the run.
    assert status["updated"] == max(s["time"] for s in status["source"].values())
    assert results.check(out, EXPECT) == []
    first = files_of(out)
    shutil.rmtree(out)
    assert cli._run_results(make) == 0
    assert files_of(out) == first

    stamp = cli._stamp_path(build_dir, "results")
    stamped = stamp.read_bytes()
    live = cfg.live_dir(cfg.latest)
    assert cli.main(["results", "poll", "--once"]) == 0
    polled = results.read_status(live)
    assert polled is not None and polled["phase"] == "partial"
    assert cli.main(["results", "fake", "mid"]) == 0
    assert results.read_status(live) != polled
    assert files_of(out) == first
    assert stamp.read_bytes() == stamped

    # Up to date: the step runs nothing.
    def unexpected(*_args, **_kwargs):
        raise AssertionError("the results step ran")

    monkeypatch.setattr(cli, "_write_final", unexpected)
    assert cli._run_results(make) == 0
    assert files_of(out) == first


def test_a_broken_package_is_not_written(ref, tmp_path, monkeypatch):
    """A package whose mayor's votes do not add up to the valid ballots
    leaves the final results as they were."""
    cfg = results_project(tmp_path, ref, monkeypatch)
    out = cfg.results_dir(cfg.latest)
    make = argparse.Namespace(force=False, election="2026")
    assert cli._run_results(make) == 0
    first = files_of(out)
    tables = oso_tables()
    tables["tab05d"][0]["Počet platných hlasov"] += 1
    package(cfg.raw_dir / "results-oso2026" / "OSO2026_SK_csv.zip", "OSO2026", tables)
    assert cli._run_results(argparse.Namespace(force=True, election="2026")) == 1
    assert files_of(out) == first


def test_the_live_results_are_checked_and_deployed_alone(ref, tmp_path, monkeypatch):
    """`results deploy` and `poll --deploy` write the live part, the live
    results alone, check them every time and deploy them to the live
    project only if they keep the contract."""
    cfg = results_project(tmp_path, ref, monkeypatch)
    deployed: list[tuple[Path, str, str]] = []

    def deploy(directory: Path, project: str, message: str) -> int:
        deployed.append((directory, project, message))
        return 0

    monkeypatch.setattr(pages, "deploy", deploy)
    checked: list[Path] = []
    check = results.check

    def recording(directory: Path, expect: results.Expect) -> list[str]:
        checked.append(directory)
        return check(directory, expect)

    monkeypatch.setattr(results, "check", recording)
    dist = cfg.root / "dist"
    # Nothing to deploy before the night.
    assert cli.main(["results", "deploy", "--yes"]) == 1
    assert deployed == []

    assert cli.main(["results", "poll", "--once", "--deploy"]) == 0
    status = results.read_status(cfg.live_dir(cfg.latest))
    assert status is not None
    version = status["version"]
    assert checked == [dist / "live/2026-10-24"]
    assert deployed == [(dist / "live", "ems-live", f"live 2026-10-24@{version}")]
    assert sorted(p.name for p in (dist / "live").iterdir()) == [
        "2026-10-24",
        "404.html",
        "_headers",
        "manifest.json",
    ]
    assert not (dist / "results").exists()

    # Live results that break the contract are not deployed.
    area = next(cfg.live_dir(cfg.latest).glob("kraj/*.json"))
    area.write_text(area.read_text().replace('"partial"', '"final"', 1))
    assert cli.main(["results", "deploy", "--yes"]) == 1
    assert len(checked) == 2
    assert len(deployed) == 1


def test_poll_only_the_elections_it_serves(tmp_path, monkeypatch, capsys):
    """Polling reads the night of a municipal and regional election on
    volbysr.sk."""
    root = tmp_path / "project"
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / config.PARTY_LOGO_DIR, root / config.PARTY_LOGO_DIR)
    monkeypatch.chdir(root)
    assert cli.main(["results", "poll", "--once", "--election", "2022"]) == 1
    assert "only the night of a municipal and regional" in capsys.readouterr().err


def test_check_wants_exactly_the_sources_of_the_election(ref, tmp_path):
    live = results.fake(ref, "mid")
    assert results.write(tmp_path, live, DIVISIONS, NOW) is not None
    assert results.check(tmp_path, EXPECT) == []
    problems = results.check(
        tmp_path, results.Expect(frozenset({"oso"}), {}, {}, DIVISIONS)
    )
    assert len(problems) == 1
    assert problems[0].startswith("status.json: source {")
    assert problems[0].endswith("not of ['oso']")


NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def xlsx_package(path: Path, prefix: str, tables: dict[str, list[dict]]) -> Path:
    """Write a by-election's package: XLSX tables, a title above the header."""
    with zipfile.ZipFile(path, "w") as z:
        for table, rows in tables.items():
            header = list(rows[0])
            lines = [["Tabuľka"], [], header]
            lines += [[str(r.get(h, "")) for h in header] for r in rows]
            sheet = "".join(
                f'<row r="{i}">'
                + "".join(f'<c t="inlineStr"><is><t>{v}</t></is></c>' for v in line)
                + "</row>"
                for i, line in enumerate(lines, 1)
            )
            book = io.BytesIO()
            with zipfile.ZipFile(book, "w") as x:
                x.writestr(
                    "xl/workbook.xml",
                    f"<workbook {NS} xmlns:r="
                    '"http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<sheets><sheet name="1" sheetId="1" r:id="rId1"/></sheets></workbook>',
                )
                x.writestr(
                    "xl/_rels/workbook.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
                )
                x.writestr(
                    "xl/worksheets/sheet1.xml",
                    f"<worksheet {NS}><sheetData>{sheet}</sheetData></worksheet>",
                )
            z.writestr(f"{prefix}_SK_{table}.xlsx", book.getvalue())
    return path


def by_election_tables() -> dict[str, list[dict]]:
    """A by-election's package as ŠÚ SR's of 2023–2026: a mayor and a council
    in 502341, a mayor of two okrsky in 505498, a council in 500411 whose
    candidate 2 withdrew (in the okrsok table only, marked in its note), and
    512885 where the by-election did not take place."""
    obce = {
        "502341": ("402", "Starosta a zastupiteľstvo", 1),
        "505498": ("406", "Len starosta", 0),
        "500411": ("403", "Len zastupiteľstvo", 1),
        "512885": ("302", "Nekonajú sa", 1),
    }

    def where(obec: str, **more: str) -> dict:
        return {"Kód okresu": obce[obec][0], "Kód obce": obec} | more

    def turnout(e: int, v: int, council: int, mayor: int) -> dict:
        return {ELIGIBLE: e, VOTERS: v, COUNCIL: council, MAYOR: mayor}

    obvod = {"Volebný obvod v obci": "1"}
    return {
        "tab0dd": [
            where(o, **{"Počet okrskov": "1", "Typ volieb": typ})
            for o, (_, typ, _) in obce.items()
        ],
        "tab02ad": [
            where(o, **{"Počet volených poslancov": str(s)})
            for o, (_, _, s) in obce.items()
            if o != "512885"
        ],
        "tab02bd": [
            where("502341", **{"Počet okrskov": "1"}) | turnout(660, 379, 357, 369),
            where("505498", **{"Počet okrskov": "2"}) | turnout(2066, 1313, 0, 1299),
            where("500411", **{"Počet okrskov": "1"}) | turnout(1269, 37, 33, 0),
        ],
        "tab02be": [
            where("502341", **obvod, **{"Počet okrskov": "1"})
            | turnout(660, 379, 357, 369),
            where("505498", **obvod, **{"Počet okrskov": "2"})
            | turnout(2066, 1313, 0, 1299),
            where("500411", **obvod, **{"Počet okrskov": "1"})
            | turnout(1269, 37, 33, 0),
        ],
        "tab02bf": [
            where("502341", **obvod, Okrsok="1") | turnout(660, 379, 357, 369),
            where("505498", **obvod, Okrsok="1") | turnout(1005, 630, 0, 626),
            where("505498", **obvod, Okrsok="2") | turnout(1061, 683, 0, 673),
            where("500411", **obvod, Okrsok="1") | turnout(1269, 37, 33, 0),
        ],
        "tab05d": [
            *votes("Poznámka", where("502341"), (1, 240, "zvolený"), (2, 129, "")),
            *votes(
                "Poznámka",
                where("505498"),
                (1, 318, ""),
                (2, 484, ""),
                (3, 497, "zvolený"),
            ),
        ],
        "tab05f": [
            *votes(
                "Poznámka",
                where("502341", **obvod, Okrsok="1"),
                (1, 240, ""),
                (2, 129, ""),
            ),
            *votes(
                "Poznámka",
                where("505498", **obvod, Okrsok="1"),
                (1, 148, ""),
                (2, 228, ""),
                (3, 250, ""),
            ),
            *votes(
                "Poznámka",
                where("505498", **obvod, Okrsok="2"),
                (1, 170, ""),
                (2, 256, ""),
                (3, 247, ""),
            ),
        ],
        "tab08e": [
            *votes(
                "Kandidát",
                where("502341", **obvod),
                (1, 112, "zvolený"),
                (2, 107, "náhradník"),
            ),
            *votes("Kandidát", where("500411", **obvod), (1, 20, "zvolený")),
        ],
        "tab08f": [
            *votes(
                "Poznámka",
                where("502341", **obvod, Okrsok="1"),
                (1, 112, ""),
                (2, 107, ""),
            ),
            *votes(
                "Poznámka",
                where("500411", **obvod, Okrsok="1"),
                (1, 20, ""),
                (2, 13, "X"),
            ),
        ],
    }


def by_election_reference() -> results.Reference:
    okresy = {"502341": "402", "505498": "406", "500411": "403", "512885": "302"}
    contests = [
        {"id": "starosta:502341", "kind": "starosta", "area": "502341"},
        {"id": "oz:502341/1", "kind": "oz", "area": "502341", "obvod": 1, "seats": 1},
        {"id": "starosta:505498", "kind": "starosta", "area": "505498"},
        {"id": "oz:500411/1", "kind": "oz", "area": "500411", "obvod": 1, "seats": 1},
        {"id": "starosta:512885", "kind": "starosta", "area": "512885"},
    ]
    data = {
        "kraje": [],
        "okresy": [],
        "obce": [
            {"code": o, "name": o, "okres": okres, "kraj": okres[0]}
            for o, okres in okresy.items()
        ],
        "contests": contests,
        "candidacies": [
            candidacy(c["id"], n, *name.split())
            for c in contests
            for n, name in enumerate(("Ján Novák", "Eva Tóthová", "Juraj Varga"), 1)
        ],
    }
    return results.reference(data, {o: {"zsk": 0} for o in okresy}, {}, parts=())


def test_by_election_package(tmp_path):
    ref = by_election_reference()
    path = xlsx_package(
        tmp_path / "OSO202603_SK_xlsx.zip", "OSO202603", by_election_tables()
    )
    logged: list[str] = []
    live, done = results.read_by_election([path], ref, logged.append)
    assert done == ["oso"]
    assert logged == ["no results of 1 contests: starosta:512885"]
    assert live.source["oso"]["counted"] == [3, 3]
    assert live.source["oso"]["unit"] == "obce"
    mayor = live.files["okres/402"]["starosta:502341"]
    assert (mayor.eligible, mayor.voters, mayor.valid, mayor.seats) == (
        660,
        379,
        369,
        1,
    )
    assert mayor.candidates == [(1, 240, 1), (2, 129, None)]
    council = live.files["okres/402"]["oz:502341/1"]
    assert (council.valid, council.seats, council.filled) == (357, 1, 1)
    assert council.candidates == [(1, 112, 1), (2, 107, 0)]
    other = live.files["okres/403"]["oz:500411/1"]
    assert other.candidates == [(1, 20, 1), (2, 13, results.WITHDRAWN)]
    assert live.okrsky["okres/406"]["starosta:505498"] == {
        "505498/1": (1005, 630, 626, {1: 148, 2: 228, 3: 250}),
        "505498/2": (1061, 683, 673, {1: 170, 2: 256, 3: 247}),
    }
    merged = results.finalize(live, done, ref.sources)
    assert merged.phase == "final"
    expect = results.Expect(ref.sources, {}, {}, ref.divisions)
    assert (
        results.write(tmp_path / "out", merged, ref.divisions, NOW, expect=expect)
        is not None
    )


def older_by_election_tables() -> dict[str, list[dict]]:
    """A by-election's package as ŠÚ SR's of 2019–2022 (OSO_201904): a mayor
    in 506311 (candidate 3 withdrew), a council of one obvod in 507415, one
    of two obvody in 542938, and 512885 where it did not take place."""
    obce = {
        "506311": ("304", "len starosta", 0),
        "507415": ("203", "len zastupiteľstvo", 2),
        "542938": ("406", "len zastupiteľstvo", 2),
        "512885": ("302", "nekonajú sa", 1),
    }

    def where(obec: str, **more: str) -> dict:
        return {"Kód okresu": obce[obec][0], "Kód obce": obec} | more

    def turnout(okrsky: int, e: int, v: int, council: int, mayor: int) -> dict:
        return {
            "Počet okrskov": okrsky,
            ELIGIBLE: e,
            "Počet vydaných obálok": v,
            COUNCIL: council,
            MAYOR: mayor,
        }

    def elected(obec: str, obvod: int, order: int, name: str, votes: int) -> dict:
        return where(
            obec,
            **{
                "Volebný obvod v obci": str(obvod),
                "Poradie zvolenia v obci": str(order),
                "Meno a priezvisko": name,
                "Politický subjekt": "NEKA",
                "Počet platných hlasov": str(votes),
            },
        )

    return {
        "tab0c": [
            where(o, **{"Počet volených poslancov": str(s), "Typ volieb": typ})
            for o, (_, typ, s) in obce.items()
        ],
        "tab02bd": [
            where("506311") | turnout(1, 243, 141, 0, 139),
            where("507415") | turnout(1, 768, 35, 32, 0),
            where("542938") | turnout(2, 1314, 181, 178, 0),
        ],
        "tab05": votes(
            "Kandidát",
            where("506311"),
            (2, 74, "zvolený"),
            (1, 60, ""),
            (3, 5, "X"),
        ),
        "tab06": [
            # Titles anywhere, the surname first at times.
            elected("507415", 1, 1, "Ing. Novák Ján", 31),
            elected("507415", 1, 2, "Eva Tóthová, Mgr.", 22),
            elected("542938", 1, 1, "Juraj Varga", 66),
            elected("542938", 2, 2, "Ján Novák", 22),
        ],
    }


def older_by_election_reference() -> results.Reference:
    okresy = {"506311": "304", "507415": "203", "542938": "406", "512885": "302"}
    names = {
        "starosta:506311": ("Ján Novák", "Eva Tóthová", "Juraj Varga"),
        # A curated list in place of the package's: the elected and others.
        "oz:507415/1": ("Peter Malý", "Eva Tóthová", "Ján Novák"),
        "oz:542938/1": ("Juraj Varga",),
        "oz:542938/2": ("Ján Novák",),
    }
    data = {
        "kraje": [],
        "okresy": [],
        "obce": [
            {"code": o, "name": o, "okres": okres, "kraj": okres[0]}
            for o, okres in okresy.items()
        ],
        "contests": [
            {"id": "starosta:506311", "kind": "starosta", "area": "506311"},
            {"id": "oz:507415/1", "kind": "oz", "area": "507415", "obvod": 1},
            {"id": "oz:542938/1", "kind": "oz", "area": "542938", "obvod": 1},
            {"id": "oz:542938/2", "kind": "oz", "area": "542938", "obvod": 2},
        ],
        "candidacies": [
            candidacy(c, n, *name.split())
            for c, ns in names.items()
            for n, name in enumerate(ns, 1)
        ],
    }
    return results.reference(data, {o: {"zsk": 0} for o in okresy}, {}, parts=())


def test_older_by_election_package(tmp_path):
    ref = older_by_election_reference()
    path = xlsx_package(
        tmp_path / "OSO_201904_xlsx.zip", "OSO_201904", older_by_election_tables()
    )
    live, done = results.read_by_election([path], ref, lambda _: None)
    assert done == ["oso"]
    # Held in three obce: 512885 did not vote.
    assert live.source["oso"]["counted"] == [3, 3]
    mayor = live.files["okres/304"]["starosta:506311"]
    assert (mayor.counted, mayor.eligible, mayor.voters, mayor.valid) == (
        (1, 1),
        243,
        141,
        139,
    )
    assert mayor.candidates == [(2, 74, 1), (1, 60, None), (3, 5, results.WITHDRAWN)]
    # The elected numbered as the candidate lists have them, by name.
    council = live.files["okres/203"]["oz:507415/1"]
    assert (council.valid, council.seats, council.filled) == (32, 2, 2)
    assert council.candidates == [(3, 31, 1), (2, 22, 1)]
    # One obvod of two: the obec's turnout and seats are neither's.
    part = live.files["okres/406"]["oz:542938/2"]
    assert (part.counted, part.eligible, part.voters, part.valid, part.seats) == (
        None,
        None,
        None,
        None,
        None,
    )
    assert (part.filled, part.candidates) == (1, [(1, 22, 1)])
    assert live.okrsky == {}
    merged = results.finalize(live, done, ref.sources)
    expect = results.Expect(ref.sources, {}, {}, ref.divisions)
    assert (
        results.write(tmp_path / "out", merged, ref.divisions, NOW, expect=expect)
        is not None
    )


def test_older_by_election_councillor_not_in_the_lists(tmp_path):
    tables = older_by_election_tables()
    tables["tab06"][1]["Meno a priezvisko"] = "Eva Tóthová-Nagyová"
    path = xlsx_package(tmp_path / "OSO_201904_xlsx.zip", "OSO_201904", tables)
    with pytest.raises(
        results.ResultsError,
        match=r"oz:507415/1: no candidate named 'Eva Tóthová-Nagyová'",
    ):
        results.read_by_election([path], older_by_election_reference())


def test_by_election_fakes_keep_the_contract(tmp_path):
    ref = by_election_reference()
    assert ref.sources == {"oso"}
    for stage in results.STAGES:
        live = results.fake(ref, stage, okrsky={"505498": 2})
        assert set(live.source) == {"oso"}
        assert results.write(tmp_path / stage, live, ref.divisions, NOW) is not None
        expect = results.Expect(ref.sources, {}, {}, ref.divisions)
        assert results.check(tmp_path / stage, expect) == []
