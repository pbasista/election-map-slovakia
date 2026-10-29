import datetime as dt
from pathlib import Path

from election_map_slovakia import candidates as cand, config, incumbents as inc
from election_map_slovakia.candidates import Admin, Candidacy, Entry, Obec
from election_map_slovakia.config import Overrides
from election_map_slovakia.incumbents import Election, Holders, Unit

# The results the holders at the 2026 elections are rebuilt from.
SOURCE = config.load(
    Path(__file__).resolve().parent.parent / "config"
).latest.incumbents
assert SOURCE is not None

ADMIN = Admin(
    kraje={"1": "Bratislavský", "4": "Nitriansky"},
    okresy={"101": ("Bratislava I", "1"), "403": ("Nitra", "4")},
    obce={
        "BA": Obec("BA", "Bratislava", None, "1"),
        "528595": Obec("528595", "Bratislava-Staré Mesto", "101", "1", "BA"),
        "500011": Obec("500011", "Nitra", "403", "4"),
        "500411": Obec("500411", "Kolíňany", "403", "4"),
    },
)
DAY_2022 = SOURCE.day
DAY_2026 = dt.date(2026, 10, 24)


def row(
    first: str, surname: str, age: int, title: str = "", obvod: str = "1"
) -> dict[str, str]:
    return {
        "MENO": first,
        "PRIEZVISKO": surname,
        "VEK": str(age),
        "TITUL": title,
        "VOOBEC": obvod,
        "P_HL": "100",
    }


TURNOUT = inc.Turnout(eligible=1000, voters=500, valid=480)


def election(day, units, mayors=None, members=None) -> Election:
    turnout: dict[tuple[str, ...], inc.Turnout] = {
        (u.obec, obvod): TURNOUT for u in units for obvod in ("", "1", "3")
    }
    by = {b.day: b.input for b in SOURCE.by_elections}
    name = by.get(day, SOURCE.municipal)
    return Election(name, day, units, mayors or {}, members or {}, turnout)


def names(holders: Holders, body: str) -> list[str]:
    return [h.name for h in holders.bodies.get(body, [])]


def start() -> Holders:
    holders = Holders(SOURCE)
    inc.apply(
        holders,
        election(
            DAY_2022,
            [
                Unit("500011", "403", 3, "1", 1),
                Unit("582000", "100", 45, "1", 17),
            ],
            mayors={
                "500011": [row("Marek", "Hattas", 35)],
                "582000": [row("Matúš", "Vallo", 41, "Ing. arch.")],
            },
            members={
                "500011": [row("Ján", "Novák", 50), row("Eva", "Malá", 40)],
                "582000": [row("Ján", "Mrkva", 50, obvod="3")],
            },
        ),
        ADMIN,
    )
    return holders


def test_2022_winners_and_city_codes():
    holders = start()
    assert names(holders, "starosta:500011") == ["Marek Hattas"]
    # Bratislava is a municipality of its own in the results, BA in 2026.
    assert names(holders, "starosta:BA") == ["Ing. arch. Matúš Vallo"]
    assert names(holders, "oz:BA") == ["Ján Mrkva"]
    assert names(holders, "oz:500011") == ["Ján Novák", "Eva Malá"]
    # The obvod is named only where the municipality had several.
    mrkva = holders.bodies["oz:BA"][0].result
    assert (mrkva.votes, mrkva.turnout, mrkva.obvod) == (100, TURNOUT, 3)
    assert holders.bodies["oz:500011"][0].result.obvod is None
    assert holders.bodies["starosta:BA"][0].result.obvod is None


def test_by_election_mayor_replaces_and_leaves_council():
    holders = start()
    day = dt.date(2024, 10, 5)
    inc.apply(
        holders,
        election(
            day,
            [Unit("500011", "403", 0, "Len starosta", 1)],
            mayors={"500011": [row("Eva", "Malá", 42)]},
        ),
        ADMIN,
    )
    assert [(h.name, h.since) for h in holders.bodies["starosta:500011"]] == [
        ("Eva Malá", day)
    ]
    assert names(holders, "oz:500011") == ["Ján Novák"]


def test_mayor_by_election_without_candidates_leaves_vacancy():
    holders = start()
    inc.apply(
        holders,
        election(dt.date(2025, 3, 15), [Unit("500011", "403", 0, "Nekonajú sa", 1)]),
        ADMIN,
    )
    assert "starosta:500011" not in holders.bodies
    assert names(holders, "oz:500011") == ["Ján Novák", "Eva Malá"]


def test_council_by_election_adds_or_replaces():
    holders = start()
    inc.apply(
        holders,
        election(
            dt.date(2023, 3, 25),
            [Unit("500011", "403", 2, "Len zastupiteľstvo", 1)],
            # Novák is elected again: his 2022 seat was vacated.
            members={"500011": [row("Ján", "Novák", 50), row("Ivan", "Nový", 30)]},
        ),
        ADMIN,
    )
    assert names(holders, "oz:500011") == ["Eva Malá", "Ján Novák", "Ivan Nový"]
    inc.apply(
        holders,
        election(
            dt.date(2023, 9, 9),
            [Unit("500011", "403", 3, "Len zastupiteľstvo", 1)],
            members={"500011": [row("Pavol", "Prvý", 30)]},
        ),
        ADMIN,
    )
    # As many seats as in 2022: the whole council was elected anew.
    assert names(holders, "oz:500011") == ["Pavol Prvý"]


def past(holders: Holders, body: str) -> tuple[str, dt.date]:
    p = holders.past[body]
    return p.election, p.day


def test_past_election_is_the_latest_that_elected_the_whole_body():
    holders = start()
    regular = (SOURCE.municipal, DAY_2022)
    assert past(holders, "starosta:BA") == past(holders, "oz:BA") == regular
    assert past(holders, "starosta:500011") == past(holders, "oz:500011") == regular
    for name, units in (
        ("results-oso202303", [Unit("500011", "403", 2, "Len zastupiteľstvo", 1)]),
        ("results-oso202309", [Unit("500011", "403", 0, "Len starosta", 1)]),
        # Declared but not held for lack of candidates: no vote took place.
        ("results-oso202402", [Unit("500011", "403", 0, "Nekonajú sa", 1)]),
    ):
        day = next(b.day for b in SOURCE.by_elections if b.input == name)
        inc.apply(holders, election(day, units), ADMIN)
    mayor = ("results-oso202309", dt.date(2023, 9, 9))
    # Two of three seats is no new council: its last full election is 2022.
    assert past(holders, "starosta:500011") == mayor
    assert past(holders, "oz:500011") == regular
    inc.apply(
        holders,
        election(
            dt.date(2024, 10, 5), [Unit("500011", "403", 3, "Len zastupiteľstvo", 1)]
        ),
        ADMIN,
    )
    assert past(holders, "oz:500011") == ("results-oso202410", dt.date(2024, 10, 5))
    assert past(holders, "starosta:500011") == mayor
    assert inc.past_json(holders.past["oz:500011"]) == {
        "election": "oso202410",
        "day": "2024-10-05",
        "eligible": 1000,
        "voters": 500,
    }


def test_age_fits_elapsed_years():
    assert inc.age_fits(35, DAY_2022, 38, DAY_2026)
    assert inc.age_fits(35, DAY_2022, 39, DAY_2026)
    assert not inc.age_fits(35, DAY_2022, 40, DAY_2026)
    assert not inc.age_fits(35, DAY_2022, 37, DAY_2026)
    assert inc.age_fits(35, DAY_2022, 40, DAY_2026, slack=1)


def candidacy(contest: str, number: int, obec: str, first: str, surname: str, age: int):
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


def matched(cs: list[Candidacy], holders: Holders) -> inc.Incumbency:
    persons, _ = cand.merge_persons(cs, ADMIN, Overrides({}, {}, (), (), {}))
    return inc.match(holders, cs, persons, ADMIN, DAY_2026)


def test_match_marks_every_role_and_the_mayor_contest():
    holders = start()
    cs = [
        candidacy("starosta:500011", 1, "500011", "Marek", "Hattas", 39),
        candidacy("oz:500011/1", 2, "500011", "Ján", "Novák", 54),
        candidacy("starosta:BA", 5, "BA", "Matúš", "Vallo", 45),
        candidacy("oz:500411/1", 1, "500411", "Eva", "Malá", 44),  # other obec
    ]
    result = matched(cs, holders)
    roles = {c.id: [h.body for h in result.roles.get(c.person, [])] for c in cs}
    assert roles == {
        "starosta:500011#1": ["starosta:500011"],
        "oz:500011/1#2": ["oz:500011"],
        "starosta:BA#5": ["starosta:BA"],
        "oz:500411/1#1": [],
    }
    assert result.contests["starosta:500011"][1] == "starosta:500011#1"
    assert result.contests["starosta:BA"][1] == "starosta:BA#5"


def test_namesakes_are_never_matched():
    holders = start()
    cs = [
        candidacy("oz:500011/1", 1, "500011", "Ján", "Novák", 54),
        candidacy("oz:500011/1", 2, "500011", "Ján", "Novák", 53),
    ]
    result = matched(cs, holders)
    assert not result.roles
    assert len(result.ambiguous) == 1


def test_mayor_standing_elsewhere_has_no_contest_candidacy():
    holders = start()
    cs = [candidacy("oz:500011/1", 1, "500011", "Marek", "Hattas", 39)]
    result = matched(cs, holders)
    assert result.contests["starosta:500011"][1] is None
    assert [h.body for h in result.roles[cs[0].person]] == ["starosta:500011"]
