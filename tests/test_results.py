import argparse
import csv
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

from election_map_slovakia import candidates, cli, config, results

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


@pytest.fixture(scope="module")
def ref() -> results.Reference:
    return results.reference(*make_data())


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
    assert results.live_path({"kind": "zsk", "area": "3"}, {}) == "kraj/3"
    assert results.live_path({"kind": "oz", "area": "KE"}, {}) == "city/KE"
    okres_of = {"508063": "106"}
    assert results.live_path({"kind": "starosta", "area": "508063"}, okres_of) == (
        "okres/106"
    )
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
    assert results.write(tmp_path, live, NOW) is not None
    assert results.check(tmp_path) == []


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
    status = results.write(tmp_path, live, NOW)
    assert status["phase"] == "none"
    assert status["files"] == {}
    assert results.check(tmp_path) == []


def test_status_versions_and_hashes(ref, tmp_path):
    live = results.night(night_files(ref), ref)
    first = results.write(tmp_path, live, NOW)
    assert first["version"].startswith("20261024T214012-")
    assert first["updated"] == "2026-10-24T21:40:12+02:00"
    for path, digest in first["files"].items():
        data = (tmp_path / f"{path}.json").read_bytes()
        assert hashlib.sha256(data).hexdigest()[:8] == digest
    assert {"kraj/1", "city/BA"} <= set(first["files"])
    # The same content again: nothing is written.
    later = NOW + dt.timedelta(minutes=1)
    assert results.write(tmp_path, live, later) is None
    assert results.read_status(tmp_path) == first
    # One contest changes: a new version, a new hash of its file only.
    live.files["kraj/1"]["zsk:1/1"].candidates[0] = (1, 5001, 1)
    second = results.write(tmp_path, live, later)
    assert second["version"] != first["version"]
    changed = {p for p in first["files"] if first["files"][p] != second["files"][p]}
    assert changed == {"kraj/1"}
    # Only the source time changes: a new version, the same files.
    live.source["oso"]["time"] = "2026-10-25T01:35:00+02:00"
    third = results.write(tmp_path, live, later)
    assert third["version"] != second["version"]
    assert third["files"] == second["files"]
    # A file edited behind the status breaks the contract.
    (tmp_path / "kraj/1.json").write_bytes(b'{"contests":{}}')
    assert any("hash" in p for p in results.check(tmp_path))


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
    return results.reference(*make_data(obce_per_obvod=12))


def test_fake_stages_follow_the_contract_and_only_grow(big_ref, tmp_path):
    stages = {s: results.fake(big_ref, s, seed=7) for s in results.STAGES}
    for name, live in stages.items():
        assert results.write(tmp_path / name, live, NOW) is not None
        assert results.check(tmp_path / name) == [], name
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
    past = live.past
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
    assert results.write(tmp_path / "good", live, NOW) is not None
    assert results.check(tmp_path / "good") == []
    # The regional contests too: the regional okrsky are the municipal ones.
    okrsky_dir = tmp_path / "good" / results.OKRSKY_DIR
    written = {
        p.relative_to(okrsky_dir).as_posix(): json.loads(p.read_bytes())
        for p in okrsky_dir.rglob("*.json")
    }
    assert any(f["past"] for p, f in written.items() if p.startswith("kraj/"))
    assert results.read_live(tmp_path / "good").past == past
    e, v, valid, votes = district["oz:528595/1"]["528595/2"]
    district["oz:528595/1"]["528595/2"] = (e, v, valid, {**votes, 1: votes[1] + 1})
    assert results.write(tmp_path / "bad", live, NOW) is not None
    assert results.check(tmp_path / "bad") == [
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
        results.reference(data, props, seats), "final", okrsky={"529320": 4}
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


def test_final_written_and_merged(final_2026, tmp_path):
    live, elections = final_2026
    night = results.Live("partial")
    night.add(
        "kraj/9", "predseda:9", results.Record("partial", candidates=[(1, 5, None)])
    )
    only_oso = results.merge(night, live, ["oso"])
    assert only_oso.phase == "partial"
    assert "predseda:9" in only_oso.records()
    merged = results.merge(None, live, elections)
    assert merged.phase == "final"
    merged.past = results.Past(
        "2022-10-29",
        {"528595/1": results.SAME, "528595/2": results.UNKNOWN},
        {
            "starosta:BA": {
                "528595/1": (90, 40, 39, {1: 20}),
                "529320": (180, 70, 69, {1: 30, 3: 5}),
            }
        },
    )
    out = tmp_path / "results"
    assert results.write(out, merged, NOW) is not None
    assert results.check(out) == []
    again = results.read_live(out)
    assert {c: r.to_json() for c, r in again.records().items()} == {
        c: r.to_json() for c, r in merged.records().items()
    }
    assert again.okrsky == merged.okrsky
    assert again.past == merged.past
    # Figures of an okrsok of unknown method, of a number not on the
    # ballot, of an obec outside the contest are caught.
    merged.past.contests["starosta:BA"] |= {
        "528595/2": (1, 1, 1, {}),
        "529320": (1, 1, 1, {9: 1}),
        "500011": (1, 1, 1, {}),
    }
    assert results.write(tmp_path / "bad", merged, NOW) is not None
    assert results.check(tmp_path / "bad") == [
        "okrsky/city/BA: starosta:BA: past 500011 (no okrsok of known method or"
        " obec of the contest)",
        "okrsky/city/BA: starosta:BA: past 528595/2 (no okrsok of known method or"
        " obec of the contest)",
        "okrsky/city/BA: starosta:BA: past 529320 (malformed, or votes of no"
        " candidate)",
    ]


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
    assert results.write(tmp_path, live, NOW) is not None
    problems = results.check(tmp_path)
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


def test_make_writes_the_final_results_of_the_inputs(ref, tmp_path, monkeypatch):
    """The results step of `ems make` reads the election's pinned final
    results inputs (elections.toml `results`) into its results directory,
    the same files from the same packages; what `ems results` writes there
    makes it run again."""
    root = tmp_path / "project"
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / config.PARTY_LOGO_DIR, root / config.PARTY_LOGO_DIR)
    raw = root / "data" / "raw"
    for prefix, tables in (("OSO2026", oso_tables()), ("OSK2026", osk_tables())):
        name = f"results-{prefix.lower()}"
        (raw / name).mkdir(parents=True)
        package(raw / name / f"{prefix}_SK_csv.zip", prefix, tables)
    build_dir = root / "data" / "build" / "2026-10-24"
    (build_dir / "geo").mkdir(parents=True)
    (build_dir / "candidates.json").write_text(json.dumps({"obce": []}))
    monkeypatch.setattr(results, "load_reference", lambda *_: ref)
    # Without the 2022 addresses and results: no comparison (test_crosswalk).
    monkeypatch.setattr(cli, "_compare", lambda *_: None)
    monkeypatch.chdir(root)
    cfg = config.load()
    assert cfg.latest.results.inputs == ("results-oso2026", "results-osk2026")
    out = cfg.results_dir(cfg.latest)
    assert out == build_dir / "results"
    make = argparse.Namespace(force=False, election="2026")

    assert cli._run_results(make) == 0
    status = results.read_status(out)
    assert status is not None
    assert status["phase"] == "final"
    # Written as of the packages' data, not of the run.
    assert status["updated"] == max(s["time"] for s in status["source"].values())
    assert results.check(out) == []
    first = files_of(out)
    shutil.rmtree(out)
    assert cli._run_results(make) == 0
    assert files_of(out) == first

    tables = oso_tables()
    tables["tab02ex"][0][VOTERS] += 1
    other = package(tmp_path / "OSO2026_SK_csv.zip", "OSO2026", tables)
    assert cli.main(["results", "final", str(other)]) == 0
    assert files_of(out) != first
    assert cli._run_results(make) == 0
    assert files_of(out) == first

    # A package whose mayor's votes do not add up to the valid ballots is
    # not written.
    tables = oso_tables()
    tables["tab05d"][0]["Počet platných hlasov"] += 1
    broken = package(tmp_path / "broken.zip", "OSO2026", tables)
    assert cli.main(["results", "final", str(broken)]) == 1
    assert files_of(out) == first


def test_poll_and_fake_only_the_elections_they_serve(tmp_path, monkeypatch, capsys):
    """Polling reads volbysr.sk, which has the latest election's results
    only; faking makes a night of the latest election."""
    root = tmp_path / "project"
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / config.PARTY_LOGO_DIR, root / config.PARTY_LOGO_DIR)
    monkeypatch.chdir(root)
    assert cli.main(["results", "poll", "--once", "--election", "2022"]) == 1
    assert "not on volbysr.sk (susr)" in capsys.readouterr().err
    stage = next(iter(results.STAGES))
    assert cli.main(["results", "fake", stage, "--election", "2022"]) == 1
    assert "only the latest election (2026)" in capsys.readouterr().err
