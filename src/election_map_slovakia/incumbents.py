"""Find the current holders of the elected bodies and which of them stand again.

The holders are rebuilt from the final results published by ŠÚ SR: the
winners of the municipal and regional elections of 29 October 2022, then
every by-election ("nové voľby") of mayors and councils since, in date order.
A by-election of a mayor replaces the mayor (or leaves the office vacant when
nobody was elected); council by-election winners join the council, or replace
it when as many seats were elected as the council had in 2022 (a repeated or
fresh election of the whole council). A councillor elected mayor of the same
municipality leaves the council, the two offices being incompatible.
Councils are held per body, not per obvod: the 2026 obvody differ from 2022.

Not covered, because no central dataset has them: substitutes (náhradníci)
who took a seat later, and resignations or deaths not followed by a
by-election. There were no regional by-elections in the 2022–2026 term.

A holder stands again when exactly one 2026 person has the same name
(:func:`candidates.search_key` of first name and surname), an age consistent
with the time since the holder's election day (a year off either way only if
nobody fits exactly: the lists have a few wrong ages), and candidacies in the same
area: the municipality (Bratislava and Košice districts count as their city)
for mayors and councillors, the kraj for regional roles. Several fitting
persons are narrowed to those standing or living in the holder's
municipality, for regional roles to those living where the holder lived in
2022; if that does not leave one, nobody is marked.

Every holder carries how the seat was won (:class:`Result`): the votes and
the turnout of the unit it was won in, summed from the per-okrsok tables of
2022 (votes tab05f/tab08f and tab06d/tab09d, turnout tab02bf and tab02bd)
or read from the by-election tables (votes tab05d/tab08e, turnout tab02be).

Mayors, councils and presidents also have their past election
(:class:`Past`), with the turnout of their whole area: the latest
by-election that elected the mayor, or the whole council, again, else the
regular election of 2022; for a president, the regional election of 2022.
The 2022 regional turnout is kept per obec too, for the 2026 regional
obvody (unknown here) to be summed from.

Bodies are named like the 2026 contests without obvod: ``starosta:<obec>``,
``oz:<obec>``, ``predseda:<kraj>``, ``zsk:<kraj>``, with ``BA``/``KE`` for the
cities of Bratislava and Košice.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from election_map_slovakia import candidates, xlsx

MUNICIPAL_2022 = "results-oso2022"
REGIONAL_2022 = "results-osk2022"
ELECTION_2022 = dt.date(2022, 10, 29)
# Inputs in config/inputs.toml with the day of each by-election, in date order,
# as listed on https://volby.statistics.sk/oso/doplnkove2022/sk/index.html
BY_ELECTIONS = {
    "results-oso202303": dt.date(2023, 3, 25),
    "results-oso202309": dt.date(2023, 9, 9),
    "results-oso202402": dt.date(2024, 2, 10),
    "results-oso202410": dt.date(2024, 10, 5),
    "results-oso202503": dt.date(2025, 3, 15),
    "results-oso202509": dt.date(2025, 9, 6),
    "results-oso202603": dt.date(2026, 3, 21),
}
INPUTS = (MUNICIPAL_2022, REGIONAL_2022, *BY_ELECTIONS)
ROLES = ("starosta", "oz", "predseda", "zsk")
# The XLSX tables of the by-elections name their columns in words; they are
# renamed to the column names of the 2022 CSV tables.
_COLUMNS = {
    "Kód obce": "OBEC",
    "Kód okresu": "OKRES",
    "Volebný obvod v obci": "VOOBEC",
    "Poradie na hlasovacom lístku": "PC_HL",
    "Meno": "MENO",
    "Priezvisko": "PRIEZVISKO",
    "Titul": "TITUL",
    "Vek": "VEK",
    "Počet volených poslancov": "P_POS_VOL",
    "Počet volebných obvodov": "P_ALL_VOOBEC",
    "Typ volieb": "VOLBY_TYP",
    "Poznámka": "POZNAMKA",
    "Kandidát": "KANDIDAT",
    "Počet platných hlasov": "P_HL",
    "Počet zapísaných voličov": "P_ZAP",
    "Počet zúčastnených voličov": "P_ZUC",
    "Počet platných hlasovacích lístkov odovzdaných pre voľby do zastupiteľstva": "P_HL_ZAS",
    "Počet platných hlasovacích lístkov odovzdaných pre voľby starostu": "P_HL_STA",
}
_NOT_HELD = "Nekonajú sa"
# (mayor elected, council elected) per type of election of a municipality,
# as the 2022 codes and the by-election words have it. A by-election that was
# not held for lack of candidates still means the office is vacant; whether
# the mayor's office was among those declared shows only as no council seats.
_TYPES = {
    "0": (False, False),
    "1": (True, True),
    "2": (True, False),
    "3": (False, True),
    "Starosta a zastupiteľstvo": (True, True),
    "Len starosta": (True, False),
    "Len zastupiteľstvo": (False, True),
}
_ELECTED_2022 = "1"
_ELECTED_BY = "zvolený"
_DAYS_PER_YEAR = 365.2425
# Years of age difference tolerated beyond the elapsed time, tried in turn.
AGE_SLACK = (0, 1)


class IncumbentsError(Exception):
    """The election results cannot be read."""


@dataclass(frozen=True)
class Turnout:
    """Participation in one unit of an election."""

    eligible: int
    """Voters on the electoral roll."""
    voters: int
    """Voters who took part (were handed an envelope)."""
    valid: int
    """Valid ballots for the office. A council voter may mark as many
    candidates as there are seats but casts one ballot, so for a council this
    is the number of voters with a valid ballot, not the number of votes."""


@dataclass(frozen=True)
class Result:
    """How a holder won the seat, in the unit it was won in.

    The unit is the municipality for a mayor, the kraj for a regional
    president, the council obvod of that election for a councillor (the
    whole municipality when it was not split) and the regional obvod for a
    regional councillor. ``votes / turnout.valid`` is the share of the valid
    ballots that named the holder: of the votes cast for a single seat, of
    the voters for a council seat.
    """

    votes: int
    turnout: Turnout
    obvod: int | None
    """The obvod number when the unit is one of several obvody."""


@dataclass(frozen=True)
class Past:
    """The last election of a body before 2026: its turnout in the body's area."""

    election: str
    """The results input it comes from, one of :data:`INPUTS`."""
    day: dt.date
    turnout: Turnout


@dataclass(frozen=True)
class Holder:
    """A person holding (a seat in) a body, as elected."""

    body: str
    since: dt.date
    """The election day the role was won."""
    first_name: str
    surname: str
    title: str
    """All titles in one column, as the results have them."""
    age: int
    """Age on :attr:`since`."""
    result: Result
    residence: str = ""
    """Municipality of residence as named in the 2022 regional results."""

    @property
    def kind(self) -> str:
        """Return the role: ``starosta``, ``oz``, ``predseda`` or ``zsk``."""
        return self.body.partition(":")[0]

    @property
    def area(self) -> str:
        """Return the obec or kraj code of the body."""
        return self.body.partition(":")[2]

    @property
    def name(self) -> str:
        """Return the name with titles before and after it."""
        before, after = candidates.split_title(self.title)
        name = " ".join(p for p in (before, self.first_name, self.surname) if p)
        return f"{name}, {after}" if after else name

    def same_person(
        self, first_name: str, surname: str, age: int, day: dt.date
    ) -> bool:
        """Return whether a person of that name and age on *day* fits."""
        return _name(self.first_name, self.surname) == _name(
            first_name, surname
        ) and age_fits(self.age, self.since, age, day)


def age_fits(
    age: int, day: dt.date, later_age: int, later_day: dt.date, slack: int = 0
) -> bool:
    """Return whether *later_age* on *later_day* fits *age* on *day*.

    Ages are whole years on the day, so the difference is the elapsed years
    rounded down, or one more if a birthday fell in the remainder; *slack*
    widens that by as many years either way.
    """
    years = int((later_day - day).days / _DAYS_PER_YEAR)
    return years - slack <= later_age - age <= years + 1 + slack


def _name(first_name: str, surname: str) -> tuple[str, str]:
    return candidates.search_key(first_name), candidates.search_key(surname)


@dataclass
class Unit:
    """One municipality's row of an election: what was elected there."""

    obec: str
    okres: str
    seats: int
    typ: str
    obvody: int
    """Council obvody the municipality was divided into."""


@dataclass
class Election:
    """The municipal election of one day, reduced to what changes holders."""

    name: str
    """The results input it comes from, one of :data:`INPUTS`."""
    day: dt.date
    units: list[Unit]
    mayors: dict[str, list[dict[str, str]]]
    """Obec code → candidate rows of the elected mayor (one, or none)."""
    members: dict[str, list[dict[str, str]]]
    """Obec code → candidate rows of the elected councillors. The rows of
    both have the winner's votes as ``P_HL``."""
    turnout: dict[tuple[str, ...], Turnout]
    """``(obec, obvod)`` → turnout of a council obvod, ``(obec, "")`` →
    turnout of the municipality with the valid ballots for mayor."""


@dataclass
class Holders:
    """The current holders of every body, and what could not be placed."""

    bodies: dict[str, list[Holder]] = field(default_factory=dict)
    """Body → holders; a mayor or president body has at most one."""
    seats_2022: dict[str, int] = field(default_factory=dict)
    """Council body → seats elected in 2022."""
    unknown: set[str] = field(default_factory=set)
    """Municipality codes of the results that are not 2026 areas."""
    past: dict[str, Past] = field(default_factory=dict)
    """Mayor, council or president body → its last election, see :func:`apply`;
    the turnout is the whole area's, the 2026 council obvody being new."""
    regional: dict[str, Past] = field(default_factory=dict)
    """Obec code (Bratislava and Košice districts as such) → the 2022
    regional election in it, to be summed over the 2026 regional obvody,
    which are not known here."""

    def all(self) -> Iterable[Holder]:
        """Yield every holder, in body order."""
        for body in sorted(self.bodies, key=_body_order):
            yield from self.bodies[body]


def _body_order(body: str) -> tuple[int, str]:
    kind, _, area = body.partition(":")
    return ROLES.index(kind), area


def load(paths: Mapping[str, Path], admin: candidates.Admin) -> Holders:
    """Return the current holders from the result files of :data:`INPUTS`."""
    holders = Holders()
    apply(holders, _read_municipal_2022(paths[MUNICIPAL_2022]), admin)
    for name, day in BY_ELECTIONS.items():
        apply(holders, _read_by_election(paths[name], name, day), admin)
    _add_regional(holders, paths[REGIONAL_2022])
    return holders


def area(admin: candidates.Admin, okres: str, obec: str) -> str | None:
    """Return the 2026 area of a municipality of the results, or None.

    The results give Bratislava and Košice as municipalities of their own,
    in the okres code the candidate lists use for city-wide contests.
    """
    for city in candidates.CITIES:
        if okres == city.okres:
            return city.code
    return obec if obec in admin.obce else None


def apply(holders: Holders, election: Election, admin: candidates.Admin) -> None:
    """Update *holders* with the municipal results of *election*."""
    for unit in election.units:
        code = area(admin, unit.okres, unit.obec)
        if code is None:
            holders.unknown.add(unit.obec)
            continue
        mayor, council = _offices(election, unit)
        oz = f"oz:{code}"
        if election.day == ELECTION_2022:
            holders.seats_2022[oz] = unit.seats
        whole = unit.seats >= holders.seats_2022.get(oz, 0)
        if council:
            elected = [
                _holder(oz, election.day, r, _result(election, unit, r, r["VOOBEC"]))
                for r in election.members.get(unit.obec, [])
            ]
            if whole:
                holders.bodies[oz] = elected
            else:
                # A councillor elected again has vacated the earlier seat.
                kept = _without(holders.bodies.get(oz, []), elected)
                holders.bodies[oz] = kept + elected
        if mayor:
            starosta = f"starosta:{code}"
            winners = [
                _holder(starosta, election.day, r, _result(election, unit, r, ""))
                for r in election.mayors.get(unit.obec, [])
            ]
            holders.bodies[starosta] = winners
            holders.bodies[oz] = _without(holders.bodies.get(oz, []), winners)
        held = unit.typ != _NOT_HELD
        _add_past(
            holders,
            election,
            unit,
            code,
            mayor=mayor and held,
            council=council and whole,
        )
    for body in [b for b, hs in holders.bodies.items() if not hs]:
        del holders.bodies[body]


def _offices(election: Election, unit: Unit) -> tuple[bool, bool]:
    """Return whether *unit* elected (mayor, council); see :data:`_TYPES`."""
    if unit.typ == _NOT_HELD:
        return unit.seats == 0, False
    if unit.typ in _TYPES:
        return _TYPES[unit.typ]
    raise IncumbentsError(f"{election.day}: unknown election type {unit.typ!r}")


def _add_past(
    holders: Holders,
    election: Election,
    unit: Unit,
    code: str,
    *,
    mayor: bool,
    council: bool,
) -> None:
    """Make *election* the past election of the bodies of area *code* it renewed.

    That is the regular one of 2022, then a by-election that elected the
    *mayor* or the whole *council*. Voters of a municipality vote for both on
    one roll, so the turnout of the municipality is that of either body.
    """
    turnout = election.turnout.get((unit.obec, ""))
    if turnout is None:
        return
    past = Past(election.name, election.day, turnout)
    regular = election.day == ELECTION_2022
    if regular or mayor:
        holders.past[f"starosta:{code}"] = past
    if regular or council:
        holders.past[f"oz:{code}"] = past


def _without(holders: Iterable[Holder], others: Sequence[Holder]) -> list[Holder]:
    """Return *holders* except those who are one of *others*."""
    return [
        h
        for h in holders
        if not any(
            h.same_person(o.first_name, o.surname, o.age, o.since) for o in others
        )
    ]


def _result(
    election: Election, unit: Unit, row: Mapping[str, str], obvod: str
) -> Result:
    """Return the result of a winner of *unit* in *obvod* ("" for mayor)."""
    turnout = election.turnout.get((unit.obec, obvod))
    if turnout is None:
        raise IncumbentsError(
            f"{election.day}: no turnout of {unit.obec} {obvod or 'for mayor'}"
        )
    number = int(obvod) if obvod and unit.obvody > 1 else None
    return Result(int(row["P_HL"]), turnout, number)


def _holder(
    body: str,
    day: dt.date,
    row: Mapping[str, str],
    result: Result,
    residence: str = "",
) -> Holder:
    return Holder(
        body,
        day,
        row["MENO"].strip(),
        row["PRIEZVISKO"].strip(),
        candidates.clean(row["TITUL"]),
        int(row["VEK"]),
        result,
        residence,
    )


def _read_municipal_2022(path: Path) -> Election:
    with _open(path) as z:
        units = _csv(z, path, "tab0dd")
        mayors = _csv(z, path, "tab0ad")
        members = _csv(z, path, "tab0bd")
        # Votes and turnout are per okrsok, summed here.
        won_mayor = _winners(_csv(z, path, "tab05f"), ("OBEC", "PC_HL"), _ELECTED_2022)
        won_member = _winners(
            _csv(z, path, "tab08f"), ("OBEC", "VOOBEC", "PC_HL"), _ELECTED_2022
        )
        turnout = _turnout(_csv(z, path, "tab02bf"), _municipal_units)
    return Election(
        MUNICIPAL_2022,
        ELECTION_2022,
        _units(units),
        _elected(mayors, ("OBEC", "PC_HL"), won_mayor),
        _elected(members, ("OBEC", "VOOBEC", "PC_HL"), won_member),
        turnout,
    )


def _read_by_election(path: Path, name: str, day: dt.date) -> Election:
    with _open(path) as z:
        units = _xlsx(z, path, "tab0dd")
        mayors = _xlsx(z, path, "tab0ad")
        members = _xlsx(z, path, "tab0bd")
        won_mayor = _winners(
            _xlsx(z, path, "tab05d"), ("OBEC", "PC_HL"), _ELECTED_BY, "POZNAMKA"
        )
        won_member = _winners(
            _xlsx(z, path, "tab08e"), ("OBEC", "VOOBEC", "PC_HL"), _ELECTED_BY
        )
        turnout = _turnout(_xlsx(z, path, "tab02be"), _municipal_units)
    return Election(
        name,
        day,
        _units(units),
        _elected(mayors, ("OBEC", "PC_HL"), won_mayor),
        _elected(members, ("OBEC", "VOOBEC", "PC_HL"), won_member),
        turnout,
    )


def _winners(
    rows: Iterable[Mapping[str, str]],
    key: tuple[str, ...],
    elected: str,
    column: str = "KANDIDAT",
) -> dict[tuple[str, ...], int]:
    """Return the candidates marked *elected* in *column*, with their votes.

    The votes are summed over the rows: the okrsky, in the 2022 tables.
    """
    votes: Counter[tuple[str, ...]] = Counter()
    won = set()
    for r in rows:
        k = tuple(r[c] for c in key)
        votes[k] += int(r["P_HL"])
        if r[column] == elected:
            won.add(k)
    return {k: votes[k] for k in won}


def _elected(
    rows: Iterable[dict[str, str]],
    key: tuple[str, ...],
    winners: Mapping[tuple[str, ...], int],
) -> dict[str, list[dict[str, str]]]:
    """Return by obec the candidate rows of *winners*, with their votes."""
    return _by_obec(
        {**r, "P_HL": str(winners[k])}
        for r in rows
        if (k := tuple(r[c] for c in key)) in winners
    )


def _municipal_units(r: Mapping[str, str]) -> Iterable[tuple[tuple[str, ...], str]]:
    return (((r["OBEC"], r["VOOBEC"]), "P_HL_ZAS"), ((r["OBEC"], ""), "P_HL_STA"))


def _turnout(
    rows: Iterable[Mapping[str, str]],
    units: Callable[[Mapping[str, str]], Iterable[tuple[tuple[str, ...], str]]],
) -> dict[tuple[str, ...], Turnout]:
    """Return the turnout per unit, summed over *rows*.

    *units* gives the units a row counts in, each with the column of its
    valid ballots.
    """
    sums: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        for key, valid in units(r):
            s = sums[key]
            s[0] += int(r["P_ZAP"])
            s[1] += int(r["P_ZUC"])
            s[2] += int(r[valid])
    return {k: Turnout(*s) for k, s in sums.items()}


def _units(rows: Iterable[Mapping[str, str]]) -> list[Unit]:
    return [
        Unit(
            r["OBEC"],
            r["OKRES"],
            int(r["P_POS_VOL"]),
            r["VOLBY_TYP"],
            int(r["P_ALL_VOOBEC"]),
        )
        for r in rows
    ]


def _by_obec(rows: Iterable[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        out[r["OBEC"]].append(r)
    return out


def _add_regional(holders: Holders, path: Path) -> None:
    """Add the 2022 regional election: its winners, and turnout per kraj and obec."""
    with _open(path) as z:
        units = _csv(z, path, "tab0dc")
        presidents = {(r["KRAJ"], r["PC_HL"]): r for r in _csv(z, path, "tab0a")}
        members = {(r["VOBVOD"], r["PC_HL"]): r for r in _csv(z, path, "tab0b")}
        kraj_of = {r["OBEC"]: r["KRAJ"] for r in units}
        obvod_of = {r["OBEC"]: r["VOBVOD"] for r in units}
        # Votes and turnout are per okrsok of an obec, summed here.
        won_president = _winners(
            ({**r, "KRAJ": kraj_of[r["OBEC"]]} for r in _csv(z, path, "tab06d")),
            ("KRAJ", "PC_HL"),
            _ELECTED_2022,
        )
        won_member = _winners(
            ({**r, "VOBVOD": obvod_of[r["OBEC"]]} for r in _csv(z, path, "tab09d")),
            ("VOBVOD", "PC_HL"),
            _ELECTED_2022,
        )
        turnout = _turnout(
            _csv(z, path, "tab02bd"),
            lambda r: (
                (("predseda", kraj_of[r["OBEC"]]), "P_HL_PRE"),
                (("zsk", obvod_of[r["OBEC"]]), "P_HL_POS"),
                (("obec", r["OBEC"]), "P_HL_POS"),
            ),
        )
    for (unit, code), t in turnout.items():
        past = Past(REGIONAL_2022, ELECTION_2022, t)
        if unit == "predseda":
            holders.past[f"predseda:{code}"] = past
        elif unit == "obec":
            holders.regional[code] = past
    kraj_of_obvod = {r["VOBVOD"]: r["KRAJ"] for r in units}
    for (kraj, number), votes in sorted(won_president.items()):
        row = presidents[(kraj, number)]
        body = f"predseda:{kraj}"
        result = Result(votes, turnout[("predseda", kraj)], None)
        holders.bodies.setdefault(body, []).append(
            _holder(body, ELECTION_2022, row, result, row["TP_NOBEC"])
        )
    for (obvod, number), votes in sorted(won_member.items()):
        row = members[(obvod, number)]
        body = f"zsk:{kraj_of_obvod[obvod]}"
        # The obvod code is the kraj code followed by the obvod's number.
        result = Result(votes, turnout[("zsk", obvod)], int(obvod[1:]))
        holders.bodies.setdefault(body, []).append(
            _holder(body, ELECTION_2022, row, result, row["TP_NOBEC"])
        )


def _open(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise IncumbentsError(f"{path}: {e}") from e


def _member(z: zipfile.ZipFile, path: Path, table: str, suffix: str) -> bytes:
    name = next((n for n in z.namelist() if n.endswith(f"_{table}{suffix}")), None)
    if name is None:
        raise IncumbentsError(f"{path}: no table {table}")
    return z.read(name)


def _csv(z: zipfile.ZipFile, path: Path, table: str) -> list[dict[str, str]]:
    """Return the rows of a CSV table (UTF-8, ``|``-separated, with header)."""
    text = _member(z, path, table, ".csv").decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter="|"))


def _xlsx(z: zipfile.ZipFile, path: Path, table: str) -> list[dict[str, str]]:
    """Return the rows of an XLSX table, columns renamed by :data:`_COLUMNS`.

    Each table has title rows above its header, which starts with the kraj.
    """
    data = _member(z, path, table, ".xlsx")
    try:
        header, rows = xlsx.find_header(xlsx.read_rows(io.BytesIO(data)), "Kód kraja")
        names = [_COLUMNS.get(candidates.clean(h), h) for h in header]
        return [
            {n: row[i] if i < len(row) else "" for i, n in enumerate(names)}
            for row in rows
        ]
    except xlsx.XlsxError as e:
        raise IncumbentsError(f"{path} {table}: {e}") from e


@dataclass
class Incumbency:
    """Holders matched to the 2026 persons and candidacies."""

    holders: Holders
    roles: dict[str, list[Holder]]
    """Person id → the roles it holds."""
    contests: dict[str, tuple[Holder, str | None]]
    """Mayor or president contest → (holder, its candidacy in that contest)."""
    ambiguous: list[str]
    """Descriptions of holders that fit several persons."""


@dataclass
class _Person:
    person: candidates.Person
    name: tuple[str, str]
    age: int
    areas: set[str]
    """Contest areas and residences of its candidacies."""
    kraje: set[str]


def match(
    holders: Holders,
    candidacies: Sequence[candidates.Candidacy],
    persons: Sequence[candidates.Person],
    admin: candidates.Admin,
    election: dt.date,
) -> Incumbency:
    """Find the 2026 person of every holder; see the module doc."""
    by_id = {c.id: c for c in candidacies}
    by_name = _index_persons(persons, by_id, admin)
    residences: dict[tuple[str, str], set[str]] = defaultdict(set)
    for o in admin.obce.values():
        residences[(o.kraj, candidates.name_key(o.name))].add(o.city or o.code)

    every = list(holders.all())
    # Position in *every* → person; namesake holders of one body are equal.
    found: dict[int, candidates.Person] = {}
    ambiguous = []
    for i, h in enumerate(every):
        named = by_name.get(_name(h.first_name, h.surname), [])
        options = _options(h, named, election, admin, residences)
        if len(options) == 1:
            found[i] = options[0].person
        elif len(options) > 1:
            ambiguous.append(_describe(h, [p.person for p in options]))

    # Two holders of one body taken for one person cannot both be right.
    claims = Counter((every[i].body, p.id) for i, p in found.items())
    for i, p in list(found.items()):
        if claims[(every[i].body, p.id)] > 1:
            ambiguous.append(_describe(every[i], [p]))
            del found[i]

    roles: dict[str, list[Holder]] = defaultdict(list)
    for i, p in found.items():
        roles[p.id].append(every[i])
    for rs in roles.values():
        rs.sort(key=lambda h: (_body_order(h.body), h.since))
    contests = {
        h.body: (h, _own_candidacy(found.get(i), h.body, by_id))
        for i, h in enumerate(every)
        if h.kind in ("starosta", "predseda")
    }
    return Incumbency(holders, dict(roles), contests, ambiguous)


def _index_persons(
    persons: Iterable[candidates.Person],
    by_id: Mapping[str, candidates.Candidacy],
    admin: candidates.Admin,
) -> dict[tuple[str, str], list[_Person]]:
    """Return the persons by name, with the areas of their candidacies."""
    by_name: dict[tuple[str, str], list[_Person]] = defaultdict(list)
    for p in persons:
        cs = [by_id[cid] for cid in p.candidacies]
        e = cs[0].entry
        kraje = {
            admin.obce[c.area].kraj if c.kind in candidates.MUNICIPAL else c.area
            for c in cs
        }
        info = _Person(
            p,
            _name(e.first_name, e.surname),
            e.age,
            {c.area for c in cs} | {c.obec for c in cs},
            kraje,
        )
        by_name[info.name].append(info)
    return by_name


def _own_candidacy(
    person: candidates.Person | None,
    contest: str,
    by_id: Mapping[str, candidates.Candidacy],
) -> str | None:
    """Return the candidacy of *person* in *contest*, if any."""
    if person is None:
        return None
    return next((c for c in person.candidacies if by_id[c].contest == contest), None)


def _options(
    h: Holder,
    named: Sequence[_Person],
    election: dt.date,
    admin: candidates.Admin,
    residences: Mapping[tuple[str, str], set[str]],
) -> list[_Person]:
    """Return the persons of *named* that may be *h*.

    An age off by a year more is taken for the lists' error only when nobody
    of the exact age fits.
    """
    for slack in AGE_SLACK:
        options = [p for p in named if age_fits(h.age, h.since, p.age, election, slack)]
        options = _narrow(h, options, admin, residences)
        if options:
            return options
    return []


def _narrow(
    h: Holder,
    options: list[_Person],
    admin: candidates.Admin,
    residences: Mapping[tuple[str, str], set[str]],
) -> list[_Person]:
    """Return the persons of *options* in the holder's area; see the module doc."""
    if h.kind in candidates.MUNICIPAL:
        merge = admin.obce[h.area].city or h.area
        options = [p for p in options if p.person.obec == merge]
        if len(options) > 1:
            options = [p for p in options if h.area in p.areas]
    else:
        options = [p for p in options if h.area in p.kraje]
        if len(options) > 1:
            lived = residences.get((h.area, candidates.name_key(h.residence)), set())
            options = [p for p in options if p.person.obec in lived]
    return options


def _describe(h: Holder, persons: Sequence[candidates.Person]) -> str:
    cids = ", ".join(p.candidacies[0] for p in persons)
    return f"{h.body} {h.name} ({h.age} in {h.since.year}): {cids}"


def roles_json(roles: Sequence[Holder]) -> list[dict[str, object]]:
    """Return the ``incumbent`` value of a candidacy."""
    return [
        {"body": h.body, "since": h.since.isoformat(), "result": result_json(h.result)}
        for h in roles
    ]


def contest_json(holder: Holder, candidacy: str | None) -> dict[str, object]:
    """Return the ``incumbent`` value of a mayor or president contest."""
    return {
        "name": holder.name,
        "since": holder.since.isoformat(),
        "candidacy": candidacy,
        "result": result_json(holder.result),
    }


def result_json(r: Result) -> dict[str, int]:
    """Return ``{votes, valid, voters, eligible, (obvod)}`` of a :class:`Result`.

    ``valid``, ``voters`` and ``eligible`` are those of :class:`Turnout`;
    ``obvod`` is there when the unit is one of several obvody.
    """
    out = {
        "votes": r.votes,
        "valid": r.turnout.valid,
        "voters": r.turnout.voters,
        "eligible": r.turnout.eligible,
    }
    if r.obvod is not None:
        out["obvod"] = r.obvod
    return out


def past_json(p: Past) -> dict[str, object]:
    """Return ``{election, day, eligible, voters}`` of a :class:`Past`.

    ``election`` is its results input without ``results-`` (``oso2022``,
    ``osk2022``, ``oso202303``, …); ``eligible`` and ``voters`` are those of
    :class:`Turnout`.
    """
    return {
        "election": p.election.removeprefix("results-"),
        "day": p.day.isoformat(),
        "eligible": p.turnout.eligible,
        "voters": p.turnout.voters,
    }


def report(inc: Incumbency) -> list[str]:
    """Return the summary lines: holders, matched and ambiguous per role."""
    holders = Counter(h.kind for h in inc.holders.all())
    matched = Counter(h.kind for rs in inc.roles.values() for h in rs)
    lines = [
        f"incumbents {holders.total():,}, {matched.total():,} stand again,"
        f" {len(inc.ambiguous)} ambiguous: "
        + ", ".join(f"{k} {matched[k]:,}/{holders[k]:,}" for k in ROLES)
    ]
    if inc.holders.unknown:
        lines.append(
            f"  results municipalities not in ZBGIS: {', '.join(sorted(inc.holders.unknown))}"
        )
    lines += [f"  ambiguous {a}" for a in inc.ambiguous]
    return lines
