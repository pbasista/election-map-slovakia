import csv
import datetime as dt
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path

import pytest

from election_map_slovakia import results

REPO = Path(__file__).resolve().parent.parent
OSO_2022 = REPO / "data/fallback/results-oso2022/OSO2022_SK_csv.zip"
OSK_2022 = REPO / "data/fallback/results-osk2022/OSK2022_SK_csv.zip"
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
    from election_map_slovakia import candidates

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


def night_files(ref: results.Reference) -> dict[str, bytes]:
    obce = [p.code for p in ref.places.values() if not p.city and p.code != "BA"]
    first, second, third = obce[0], obce[1], obce[2]
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
            (1, "5 000", "zvolený"), (2, "4 000", ""), (3, "X", "X")
        ),
    }


def test_night_normalization(ref, tmp_path):
    files = night_files(ref)
    obce = [p.code for p in ref.places.values() if not p.city and p.code != "BA"]
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
    assert zsk.candidates == [(1, 5000, 1), (2, 4000, None)]
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
    obce = [p.code for p in ref.places.values() if not p.city and p.code != "BA"]
    files[f"oso/json/graph01/{obce[0]}.json"] = b"<html>404</html>"
    files["osk/json/tab06b/1.json"] = j({"not": "a list"})
    files["oso/json/graph01/582000.json"] = graph01(C17=[1], C03="?")
    logged: list[str] = []
    live = results.night(files, ref, logged.append)
    records = live.records()
    assert f"starosta:{obce[0]}" not in records
    assert "predseda:1" not in records
    assert "zsk:1/1" in records


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
    assert (tmp_path / "_headers").read_text().count("Access-Control-Allow-Origin: *")


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


@pytest.fixture(scope="module")
def final_2022() -> tuple[results.Live, list[str]]:
    return results.read_final([OSO_2022, OSK_2022])


def test_final_csv_municipal(final_2022):
    live, elections = final_2022
    assert elections == ["oso", "osk"]
    records = live.records()
    ba = live.files["city/BA"]["starosta:BA"]
    assert ba.status == "final"
    assert (ba.eligible, ba.voters, ba.valid) == (407992, 150477, 144486)
    assert ba.counted == (394, 394)
    assert (8, 86981, 1) in ba.candidates  # Matúš Vallo
    assert all(flag is None for n, _, flag in ba.candidates if n != 8)
    assert (ba.seats, ba.filled) == (1, 1)
    for city, districts in (("BA", 17), ("KE", 22)):
        for contest, r in live.files[f"city/{city}"].items():
            assert r.areas is not None, contest
            assert sum(a[0] for a in r.areas.values()) == r.eligible, contest
            assert sum(a[2] for a in r.areas.values()) == r.valid, contest
            assert sum(sum(a[3].values()) for a in r.areas.values()) == sum(
                b[1] for b in r.candidates
            ), contest
        assert len(live.files[f"city/{city}"][f"starosta:{city}"].areas) == districts
    council = records["oz:500011/1"]
    assert council.status == "final"
    assert {b[2] for b in council.candidates} <= {0, 1}
    assert sum(1 for b in council.candidates if b[2] == 1) == council.filled
    assert live.source["oso"]["counted"] == [2921, 2921]
    # Withdrawn candidates (KANDIDAT X) are left out.
    with zipfile.ZipFile(OSO_2022) as z:
        rows = csv.DictReader(
            io.StringIO(z.read("OSO2022_SK_tab05f.csv").decode("utf-8-sig")),
            delimiter="|",
        )
        withdrawn = next(r for r in rows if r["KANDIDAT"] == "X")
    area = results.CITY_OBCE.get(withdrawn["OBEC"], withdrawn["OBEC"])
    numbers = {b[0] for b in records[f"starosta:{area}"].candidates}
    assert int(withdrawn["PC_HL"]) not in numbers


def test_final_csv_regional(final_2022):
    live, _ = final_2022
    president = live.files["kraj/1"]["predseda:1"]
    assert (president.eligible, president.voters, president.valid) == (
        604207,
        233255,
        215351,
    )
    assert (2, 136983, 1) in president.candidates  # Juraj Droba
    assert sum(a[0] for a in president.areas.values()) == president.eligible
    assert all(len(code) == 6 for code in president.areas)
    council = live.files["kraj/1"]["zsk:1/1"]
    assert (council.seats, council.filled) == (3, 3)
    assert sorted(b[2] for b in council.candidates).count(1) == 3
    assert live.source["osk"]["counted"] == [6010, 6010]


def test_final_written_and_merged(final_2022, tmp_path):
    live, elections = final_2022
    night = results.Live("partial")
    night.add(
        "kraj/9", "predseda:9", results.Record("partial", candidates=[(1, 5, None)])
    )
    only_oso = results.merge(night, live, ["oso"])
    assert only_oso.phase == "partial"
    assert "predseda:9" in only_oso.records()
    merged = results.merge(None, live, elections)
    assert merged.phase == "final"
    assert results.write(tmp_path, merged, NOW) is not None
    assert results.check(tmp_path) == []
    again = results.read_live(tmp_path)
    assert {c: r.to_json() for c, r in again.records().items()} == {
        c: r.to_json() for c, r in merged.records().items()
    }


def test_final_needs_the_table_list(tmp_path):
    package = tmp_path / "OSO2026_SK_csv.zip"
    with zipfile.ZipFile(package, "w") as z:
        z.writestr("OSO2026_SK_tab05f.csv", "OBEC|OKRSOK|PC_HL|P_HL|KANDIDAT\n")
    with pytest.raises(results.ResultsError, match="tab_info"):
        results.read_final([package])
