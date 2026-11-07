"""ŠÚ SR's definitive packages of the regular elections of 2022, 2018 and 2017.

ŠÚ SR published the municipal (OSO) and regional (OSK) elections of 2022
as zips of ``|``-separated UTF-8 tables with coded column names, one row
per candidate, obvod or okrsok, described by each zip's ``tab_info.csv``
(:func:`open_package` reads them). This module turns them into what the
pipeline takes from other sources for 2026 (format ``susr``; the
packages of 2018 and 2017, below, come in through the same functions,
:func:`read_lists` and :func:`read_final`):

- :func:`read_candidates`: the candidate lists as the rows the MV SR lists
  give (:class:`candidates.Entry`, for :func:`candidates.match` and
  :func:`candidates.merge_persons`), with the seats of every council and
  regional obvod, the regional obvod of every obec and the candidates who
  withdrew;
- :func:`read_results`: the final results (:class:`results.Live`, for
  :func:`results.write`), summed from the tables per okrsok.

The tables read, OSO / OSK:

===================  =================================================
``tab0dd`` / tab0dc  each obec with okres and kraj / its regional obvod
``tab0ad`` / tab0a   mayor / president candidates
``tab0bd`` / tab0b   council / regional council candidates
``tab0c``            party code → name (the same in both)
``tab02ad`` / ab     seats per council obvod / regional obvod
``tab02bf`` / bd     turnout per okrsok
``tab05f`` / tab06d  mayor / president votes per okrsok
``tab08f`` / tab09d  council / regional council votes per okrsok
===================  =================================================

What the tables hold beyond what ``tab_info.csv`` says:

- A candidate's parties are codes separated by ``,``; ``001``, missing
  from ``tab0c``, is an independent candidate. ``X`` in ``POZNAMKA`` of
  the lists and in ``KANDIDAT`` of the vote tables marks a candidate who
  withdrew or was recalled, yet stayed on the ballot with votes counted.
- Municipal candidates have no residence; regional ones have the obec of
  residence by name (``TP_NOBEC``).
- A few occupations run over two lines, unquoted, and the name of party
  145 contains the separator; :func:`parse_table` mends both.
- Shares of votes are as in 2026: a mayor's or president's of the okrsok's
  valid ballots, a council candidate's of all the okrsok's votes.
- Bratislava (582000) and Košice (599981) as wholes are municipalities of
  the municipal tables; their okrsky are numbered per city council obvod
  with the number the okrsok has in its district, so in Košice, whose
  obvody can span districts, a number can repeat within an obvod, as in
  2026. The regional tables have the districts only. Twelve city okrsky
  have other voters than their district's record, or the same as another
  okrsok (:func:`join_by_number`).
- Krušovce has candidates but no result: its commission could not draw up
  its record, and the election there was repeated.
- The council of Gemerské Dechtáre (514764) filled 5 seats (``tab02ad``),
  but 4 candidates are flagged elected; the flags are taken as given.

Contest ids are those of 2026 (:mod:`election_map_slovakia.candidates`):
``starosta:<obec>``, ``oz:<obec>/<obvod>`` (obvod 1 where there is one),
``predseda:<kraj>``, ``zsk:<kraj>/<obvod>``; Bratislava's and Košice's
own are ``BA`` and ``KE``.

Before 2022 the municipal and the regional elections were held on days of
their own: the regional on 4 November 2017, the municipal on 10 November
2018. ŠÚ SR published each as zips of XLSX tables of full Slovak column
names (``OSK_2017_xlsx.zip``; ``OSO_2018_xlsx.zip`` and, of the tables per
okrsok, ``OSO_2018_okrsky-xlsx.zip``), read by
:mod:`election_map_slovakia.tables`, their rows then read into those of the
2022 tables (:func:`_coded`) so that they are summed, and the cities'
okrsky joined, as 2022's:

- 2017 (:func:`regional_lists`, :func:`regional_results`): complete, as
  2022's; the okrsky are named by obec and number, the elected and the
  withdrawn flagged by number in ``Poznámka``.
- 2018 (:func:`municipal_lists`, :func:`municipal_results`): counted by
  okrsok, with every council candidate, only where the obec had ŠÚ SR's
  system (``IVIS``) count it: 446 obce and the two cities. Of the others
  the package has the mayors' votes and the turnout per obec and of the
  councils the elected only, with their votes; no candidate has an age or
  occupation. ŠÚ SR gives no seats per council obvod
  (:func:`council_seats`). One elected councillor's name is written as one
  word (:func:`candidates.split_name`). The withdrawn council candidates
  have votes per okrsok but not per obvod.
"""

from __future__ import annotations

import datetime as dt
import re
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from election_map_slovakia import (
    candidates,
    contests as kinds,
    progress,
    results,
    tables,
)
from election_map_slovakia.results import Area, Ballot, Live, Record

_PACKAGE_FILE = re.compile(r"(OSO|OSK)2022_SK_(tab\w+?)\.csv$", re.IGNORECASE)
_SEPARATOR = "|"
_TABLES: dict[str, dict[str, tuple[str, ...]]] = {
    "oso": {
        "tab0dd": (
            "KRAJ", "NKRAJ", "OBVOD", "NOBVOD", "OKRES", "NOKRES", "OBEC", "NOBEC",
            "P_ALL_VOOBEC", "P_ALL_OKRSOK", "P_POS_VOL", "VOLBY_TYP",
        ),
        "tab0ad": (
            "OBEC", "PC_HL", "MENO", "PRIEZVISKO", "TITUL", "VEK", "ZAMESTNANIE",
            "PS", "POZNAMKA",
        ),
        "tab0bd": (
            "OBEC", "VOOBEC", "PC_HL", "MENO", "PRIEZVISKO", "TITUL", "VEK",
            "ZAMESTNANIE", "PS", "POZNAMKA",
        ),
        "tab0c": ("PS", "NPS", "SNPS"),
        "tab02ad": ("OBEC", "VOOBEC", "P_POS_VOL", "P_POS_ZVOL"),
        "tab02bf": (
            "OBEC", "VOOBEC", "OKRSOK", "P_ZAP", "P_ZUC", "UCAST", "P_OO",
            "P_OO_PCT", "P_HL_ZAS", "P_HL_STA",
        ),
        "tab05f": ("OBEC", "VOOBEC", "OKRSOK", "PC_HL", "P_HL", "P_HL_PCT", "KANDIDAT"),
        "tab08f": ("OBEC", "VOOBEC", "OKRSOK", "PC_HL", "P_HL", "P_HL_PCT", "KANDIDAT"),
    },
    "osk": {
        "tab0dc": (
            "KRAJ", "NKRAJ", "VOBVOD", "NVOBVOD", "OBEC", "NOBEC", "P_ALL_OKRSOK",
        ),
        "tab0a": (
            "KRAJ", "PC_HL", "MENO", "PRIEZVISKO", "TITUL", "VEK", "ZAMESTNANIE",
            "TP_NOBEC", "PS", "POZNAMKA",
        ),
        "tab0b": (
            "VOBVOD", "PC_HL", "MENO", "PRIEZVISKO", "TITUL", "VEK", "ZAMESTNANIE",
            "TP_NOBEC", "PS", "POZNAMKA",
        ),
        "tab0c": ("PS", "NPS", "SNPS"),
        "tab02ab": ("VOBVOD", "P_POS_VOL", "P_POS_ZVOL"),
        "tab02bd": (
            "OBEC", "OKRSOK", "P_ZAP", "P_ZUC", "UCAST", "P_OO", "P_OO_PCT",
            "P_HL_PRE", "P_HL_POS",
        ),
        "tab06d": ("OBEC", "OKRSOK", "PC_HL", "P_HL", "P_HL_PCT", "KANDIDAT"),
        "tab09d": ("OBEC", "OKRSOK", "PC_HL", "P_HL", "P_HL_PCT", "KANDIDAT"),
    },
}  # fmt: skip
"""The tables read of each package, with their header."""
_WIDE = {"tab0c": "NPS"}
"""The column of a table whose text can contain the separator."""
_INDEPENDENT = "001"
_WITHDRAWN = "X"
_ELECTED = "1"
_NOT_HELD = "0"
"""``VOLBY_TYP`` of an obec where no election was held."""
_VOLBY_TYP = {
    "0": "nekonajú sa",
    "1": "starosta a zastupiteľstvo",
    "2": "len starosta",
    "3": "len zastupiteľstvo",
}
"""``VOLBY_TYP`` of 2022 → the kind of election the other years' tables
name (``OSO2022_SK_tab_info.csv``)."""
_VALID = {
    "starosta": "P_HL_STA",
    "oz": "P_HL_ZAS",
    "predseda": "P_HL_PRE",
    "zsk": "P_HL_POS",
}
"""The turnout column of the valid ballots of each kind of contest."""
# results' functions for the two cities' okrsky read rows by the column
# names of the 2026 tables; the 2022 rows they are given are renamed so.
_C_CITY = "Kód mesta"
_C_OBEC = "Kód obce"
_C_OKRES = "Kód okresu"
_C_OBVOD = "Volebný obvod v obci"
_C_OKRSOK = "Okrsok"
_C_ELIGIBLE = "Počet zapísaných voličov"
_C_VOTERS = "Počet zúčastnených voličov"
_C_NUMBER = "Poradie na hlasovacom lístku"
_C_VOTES = "Počet platných hlasov"
_C_SHARE = "Podiel platných hlasov v %"
_C_VALID = {
    kind: f"Počet platných hlasovacích lístkov odovzdaných pre voľby {name}"
    for kind, name in (("starosta", "starostu"), ("oz", "do zastupiteľstva"))
}

_T = TypeVar("_T")
_K = TypeVar("_K")
Rows = list[dict[str, str]]


class StatOfficeError(Exception):
    """A package cannot be read."""


# The packages.


@dataclass(frozen=True)
class Package:
    """The tables of one package of 2022 (:data:`_TABLES`).

    Or of 2018 or 2017, read into them (:func:`_coded_package`).
    """

    name: str
    election: str
    """``oso`` or ``osk``."""
    time: dt.datetime
    """The time of its newest table, as the zip has it (local time)."""
    tables: dict[str, Rows]

    def rows(self, table: str) -> Rows:
        """Return the rows of *table*, column name → text."""
        return self.tables[table]


def open_package(path: Path) -> Package:
    """Return the tables of a 2022 package zip, checked against :data:`_TABLES`."""
    found: dict[str, tuple[str, bytes]] = {}
    latest = (1980, 1, 1, 0, 0, 0)  # the earliest time a zip can hold
    try:
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                m = _PACKAGE_FILE.search(info.filename)
                if m:
                    found[m.group(2).lower()] = (m.group(1).lower(), z.read(info))
                    latest = max(latest, info.date_time)
    except (OSError, zipfile.BadZipFile) as e:
        raise StatOfficeError(f"{path}: {e}") from e
    elections = {election for election, _ in found.values()}
    if len(elections) != 1:
        raise StatOfficeError(f"{path}: not the tables of one 2022 election")
    election = elections.pop()
    tables = {}
    for table, header in _TABLES[election].items():
        if table not in found:
            raise StatOfficeError(f"{path.name}: no table {table}")
        tables[table] = parse_table(
            f"{path.name} {table}",
            found[table][1].decode("utf-8-sig"),
            header,
            _WIDE.get(table),
        )
    return Package(
        path.name, election, dt.datetime(*latest, tzinfo=results.TIMEZONE), tables
    )


def parse_table(
    name: str, text: str, header: Sequence[str], wide: str | None = None
) -> Rows:
    """Return the rows of table *text*, whose first line must be *header*.

    Fields are not quoted, so a line break within one splits its row: lines
    are joined, by a space, until the row has every column. Column *wide*
    keeps the separators of a row with more fields than columns. Empty
    lines are skipped.
    """
    lines = [line.rstrip("\r") for line in text.split("\n")]
    if lines[0].split(_SEPARATOR) != list(header):
        raise StatOfficeError(f"{name}: header {lines[0]!r}")
    rows = []
    pending = ""
    for number, line in enumerate(lines[1:], 2):
        pending = f"{pending} {line}" if pending else line
        if not pending.strip() or pending.count(_SEPARATOR) < len(header) - 1:
            continue
        cells = pending.split(_SEPARATOR)
        pending = ""
        extra = len(cells) - len(header)
        if extra:
            if wide is None:
                raise StatOfficeError(f"{name}: line {number} has {len(cells)} fields")
            i = header.index(wide)
            cells[i : i + extra + 1] = [_SEPARATOR.join(cells[i : i + extra + 1])]
        rows.append(dict(zip(header, cells, strict=True)))
    if pending.strip():
        raise StatOfficeError(f"{name}: last row incomplete: {pending!r}")
    return rows


def _expect(package: Package, election: str) -> None:
    if package.election != election:
        raise StatOfficeError(f"{package.name}: not the {election} package")


def _area(obec: str) -> str:
    """Return a municipal contest's area: the obec, ``BA`` or ``KE``."""
    return results.CITY_OBCE.get(obec, obec)


def _vobvod(code: str) -> tuple[str, int]:
    """Return the kraj and number of regional obvod *code*: ``105`` → 1, 5."""
    return code[:-2], int(code[-2:])


def _contest(table: str, row: Mapping[str, str]) -> str:
    """Return the contest of a row of a candidate list *table*."""
    if table == "tab0ad":
        return f"starosta:{_area(row['OBEC'])}"
    if table == "tab0bd":
        return f"oz:{_area(row['OBEC'])}/{int(row['VOOBEC'])}"
    if table == "tab0a":
        return f"predseda:{row['KRAJ']}"
    kraj, number = _vobvod(row["VOBVOD"])
    return f"zsk:{kraj}/{number}"


_LISTS = (
    ("oso", "tab0ad", "starosta"),
    ("oso", "tab0bd", "oz"),
    ("osk", "tab0a", "predseda"),
    ("osk", "tab0b", "zsk"),
)
"""The candidate lists: package, table, kind."""


def _lookup(mapping: Mapping[_K, _T], key: _K, what: str) -> _T:
    if key not in mapping:
        raise StatOfficeError(f"no {what} {key!r}")
    return mapping[key]


def _group(rows: Iterable[_T], key: Callable[[_T], _K]) -> dict[_K, list[_T]]:
    out: dict[_K, list[_T]] = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return dict(out)


# The candidates.


def read_candidates(oso: Package, osk: Package) -> candidates.Lists:
    """Return the candidates of the 2022 packages, with what they say beside.

    The withdrawn, the seats of every council and regional council obvod
    and the regional obvod of every obec (Bratislava's and Košice's
    districts). A municipal entry names its okres and obec as ``tab0dd``
    does (the two cities as okres 100 Bratislava and 800 Košice, which the
    MV SR lists use too), a regional one its kraj as the MV SR lists do, so
    that :func:`candidates.match` finds their codes by name.
    """
    _expect(oso, "oso")
    _expect(osk, "osk")
    units = {r["OBEC"]: r for r in oso.rows("tab0dd")}
    kraje = {r["KRAJ"]: r["NKRAJ"] for r in osk.rows("tab0dc")}
    out = candidates.Lists([])
    for election, table, kind in _LISTS:
        package = oso if election == "oso" else osk
        parties = {r["PS"]: candidates.clean(r["NPS"]) for r in package.rows("tab0c")}
        for line, row in enumerate(package.rows(table), 1):
            source = f"{package.name} {table}: data row {line}"
            try:
                contest = _contest(table, row)
                if kind in kinds.MUNICIPAL:
                    unit = _lookup(units, row["OBEC"], "obec")
                    entry = _entry(
                        kind,
                        source,
                        row,
                        parties,
                        region=unit["NOKRES"],
                        okres_code=unit["OKRES"],
                        obec=unit["NOBEC"],
                    )
                else:
                    kraj = row["KRAJ"] if kind == "predseda" else row["VOBVOD"][:-2]
                    entry = _entry(
                        kind,
                        source,
                        row,
                        parties,
                        region=_kraj_region(_lookup(kraje, kraj, "kraj")),
                    )
            except (ValueError, StatOfficeError, candidates.CandidatesError) as e:
                raise StatOfficeError(f"{source}: {e}") from e
            out.entries.append(entry)
            if row["POZNAMKA"] == _WITHDRAWN:
                out.withdrawn.add(f"{contest}#{entry.number}")
    for r in oso.rows("tab02ad"):
        out.seats[f"oz:{_area(r['OBEC'])}/{int(r['VOOBEC'])}"] = int(r["P_POS_VOL"])
    for r in osk.rows("tab02ab"):
        kraj, number = _vobvod(r["VOBVOD"])
        out.seats[f"zsk:{kraj}/{number}"] = int(r["P_POS_VOL"])
    for r in osk.rows("tab0dc"):
        kraj, number = _vobvod(r["VOBVOD"])
        if kraj != r["KRAJ"]:
            raise StatOfficeError(f"{osk.name} tab0dc: obvod {r['VOBVOD']} not of kraj")
        out.zsk[r["OBEC"]] = number
    not_held(
        out,
        (
            (r["OBEC"], _VOLBY_TYP[r["VOLBY_TYP"]], r["P_ALL_VOOBEC"], r["P_POS_VOL"])
            for r in units.values()
        ),
        "tab0dd",
    )
    return out


def not_held(
    out: candidates.Lists,
    rows: Iterable[Sequence[str]],
    table: str,
    *,
    part: str = "oso",
) -> None:
    """Add to *out* the contests of a regular election that were held nowhere.

    *rows* are ŠÚ SR's territorial division, table *table* of the input
    *part* (the municipal package, ``oso``, or the table itself): each
    obec's code, kind of election (``Typ volieb``,
    :data:`candidates.NOT_HELD_TYPES`), obvody and seats, which also give
    each obec's council seats (:attr:`candidates.Lists.council_seats`).
    """
    for obec, kind, obvody, seats in rows:
        out.council_seats[_area(obec)] = int(seats)
        kinds = candidates.NOT_HELD_TYPES.get(kind.casefold())
        if kinds:
            why = candidates.Uncontested(
                f"ŠÚ SR, {table}: Typ volieb „{kind.casefold()}“", part=part
            )
            candidates.not_held(
                out, _area(obec), kinds, int(obvody), int(seats) or None, why
            )


def okrsok_counts(oso: Package) -> dict[str, int]:
    """Return obec → its number of okrsky (``tab0dd``).

    Bratislava's and Košice's districts are obce; the two cities as wholes
    are left out, as ŠÚ SR's territorial tables of 2026 leave them out.
    """
    _expect(oso, "oso")
    return {
        r["OBEC"]: int(r["P_ALL_OKRSOK"])
        for r in oso.rows("tab0dd")
        if r["OBEC"] not in results.CITY_OBCE
    }


def okrsky(oso: Package) -> dict[str, dict[int, dict[int, int]]]:
    """Return obec → council obvod → okrsok → voters on the roll (``tab02bf``).

    The okrsky of each obvod as the council's results group them, with
    ``P_ZAP``; Bratislava's and Košice's districts are obce, the two cities
    as wholes left out as in :func:`okrsok_counts`.
    """
    _expect(oso, "oso")
    out: dict[str, dict[int, dict[int, int]]] = defaultdict(lambda: defaultdict(dict))
    for r in oso.rows("tab02bf"):
        if r["OBEC"] not in results.CITY_OBCE:
            out[r["OBEC"]][int(r["VOOBEC"])][int(r["OKRSOK"])] = int(r["P_ZAP"])
    return {
        o: {n: dict(sorted(k.items())) for n, k in sorted(g.items())}
        for o, g in out.items()
    }


def _kraj_region(name: str) -> str:
    """Return the kraj ``Bratislavský kraj`` as the MV SR lists name it.

    That is the self-governing region, ``Bratislavský samosprávny kraj``,
    whose suffix :func:`candidates.match` drops to compare with ZBGIS.
    """
    return f"{name.removesuffix(' kraj')} samosprávny kraj"


def _entry(
    kind: str,
    source: str,
    row: Mapping[str, str],
    parties: Mapping[str, str],
    *,
    region: str,
    okres_code: str = "",
    obec: str = "",
) -> candidates.Entry:
    """Return the :class:`candidates.Entry` of a candidate list's *row*.

    The tables have one title column, as the municipal MV SR lists do.
    """
    before, after = candidates.split_title(candidates.clean(row["TITUL"]))
    names, independent = nomination(row["PS"], parties)
    return candidates.Entry(
        kind=kind,
        source=source,
        region=region,
        okres_code=okres_code,
        obec=obec,
        obvod=_obvod(kind, row),
        number=int(row["PC_HL"]),
        first_name=candidates.clean(row["MENO"]),
        surname=candidates.clean(row["PRIEZVISKO"]),
        title_before=before,
        title_after=after,
        age=int(row["VEK"]),
        occupation=candidates.clean(row["ZAMESTNANIE"]),
        parties=names,
        independent=independent,
        residence=candidates.clean(row.get("TP_NOBEC", "")),
    )


def _obvod(kind: str, row: Mapping[str, str]) -> int | None:
    """Return the obvod of a council candidate's *row*, None for the others."""
    if kind == "oz":
        return int(row["VOOBEC"])
    if kind == "zsk":
        return _vobvod(row["VOBVOD"])[1]
    return None


def nomination(codes: str, parties: Mapping[str, str]) -> tuple[list[str], bool]:
    """Return (party names, independent) of a ``PS`` column of party *codes*."""
    parts = [c.strip() for c in codes.split(",")]
    if parts == [_INDEPENDENT]:
        return [], True
    unknown = [c for c in parts if c not in parties]
    if unknown:
        raise StatOfficeError(f"unknown party codes {unknown} in {codes!r}")
    return [parties[c] for c in parts], False


# The results.


@dataclass
class FinalResults:
    """The final results of 2022 and what could not be placed in them."""

    live: Live
    """Phase final; area files of every contest counted, okrsok files."""
    no_result: list[str]
    """Contests with candidates but no result (Krušovce's)."""
    city_by_number: list[str] = field(default_factory=list)
    """City okrsky joined to the district's okrsok of their number alone
    (:func:`join_by_number`): ``BA 3/43 → 529320/43``."""
    city_unmatched: list[str] = field(default_factory=list)
    """City okrsky joined to no okrsok of a district (``BA 3/43``), left out
    of the okrsok files."""


def read_results(
    oso: Package, osk: Package, log: results.Log = progress.note
) -> FinalResults:
    """Return the final results of the 2022 packages; see :class:`FinalResults`.

    As the 2026 final results (:func:`results.read_final`): a contest's
    record sums its okrsky; a regional contest has ``areas`` per obec,
    Bratislava's and Košice's own per district; every contest has its
    okrsky, keyed by obec and okrsok, the cities' by the district's okrsok
    they are joined to (:func:`results.city_matches`, then
    :func:`join_by_number`). No ``past``: the site has no turnout of 2018.
    *log* is told what is left out.
    """
    _expect(oso, "oso")
    _expect(osk, "osk")
    out = FinalResults(Live("final"), [])
    _municipal(oso, out, log)
    _regional(osk, out.live)
    listed = {
        _contest(table, row)
        for election, table, _ in _LISTS
        for row in (oso if election == "oso" else osk).rows(table)
    }
    out.no_result = sorted(listed - out.live.records().keys())
    if out.no_result:
        log(f"no result, though candidates stood: {', '.join(out.no_result)}")
    return out


def _sums(rows: Iterable[Mapping[str, str]], kind: str) -> tuple[int, int, int]:
    """Return eligible, voters and valid ballots of *kind* of turnout *rows*."""
    eligible = voters = valid = 0
    for r in rows:
        eligible += int(r["P_ZAP"])
        voters += int(r["P_ZUC"])
        valid += int(r[_VALID[kind]])
    return eligible, voters, valid


def _votes(rows: Iterable[Mapping[str, str]]) -> dict[int, int]:
    """Return ballot number → votes of vote *rows*."""
    out: Counter[int] = Counter()
    for r in rows:
        out[int(r["PC_HL"])] += int(r["P_HL"])
    return dict(out)


def ballots(rows: Sequence[Mapping[str, str]], kind: str) -> list[Ballot]:
    """Return the candidates of a contest's vote *rows* (per okrsok), summed.

    Flag 1 elected (``1``), :data:`results.WITHDRAWN` (``X``), else 0 (a
    substitute) in a council, None for a mayor or president, as in 2026.
    The flag must be the same in every okrsok.
    """
    others = None if kinds.KINDS[kind].single else 0
    flags = {_ELECTED: 1, _WITHDRAWN: results.WITHDRAWN}
    labels: dict[int, set[str]] = defaultdict(set)
    for r in rows:
        labels[int(r["PC_HL"])].add(r["KANDIDAT"])
    votes = _votes(rows)
    out = []
    for number, seen in sorted(labels.items()):
        if len(seen) != 1:
            raise StatOfficeError(f"candidate {number} flagged {sorted(seen)}")
        out.append((number, votes[number], flags.get(seen.pop(), others)))
    return out


def _record(
    turnout: Sequence[Mapping[str, str]],
    kind: str,
    votes: Sequence[Mapping[str, str]],
    seats: int | None,
) -> Record:
    """Return a contest's record from its okrsky's *turnout* and *votes* rows."""
    eligible, voters, valid = _sums(turnout, kind)
    cands = ballots(votes, kind)
    return Record(
        "final",
        (len(turnout), len(turnout)),
        eligible,
        voters,
        valid,
        seats,
        sum(1 for b in cands if b[2] == 1),
        cands,
    )


def _areas(
    turnout: Iterable[Mapping[str, str]],
    kind: str,
    votes: Iterable[Mapping[str, str]],
    key: Callable[[Mapping[str, str]], str],
) -> dict[str, Area]:
    """Return a contest's figures summed by *key* of its rows."""
    vote_rows = _group(votes, key)
    return {
        k: (*_sums(rows, kind), _votes(vote_rows.get(k, [])))
        for k, rows in _group(turnout, key).items()
    }


def _okrsok(row: Mapping[str, str]) -> str:
    return results.okrsok_key(row["OBEC"], row["OKRSOK"])


def _obec(row: Mapping[str, str]) -> str:
    return row["OBEC"]


def _municipal(p: Package, out: FinalResults, log: results.Log) -> None:
    """Add the contests of municipal package *p* and its source to *out*."""
    live = out.live
    units = p.rows("tab0dd")
    okres_of = {r["OBEC"]: r["OKRES"] for r in units}
    seats = {(r["OBEC"], r["VOOBEC"]): int(r["P_POS_VOL"]) for r in p.rows("tab02ad")}
    okrsky = [r for r in p.rows("tab02bf") if r["OBEC"] not in results.CITY_OBCE]
    by_obec = _group(okrsky, _obec)
    by_obvod = _group(okrsky, lambda r: (r["OBEC"], r["VOOBEC"]))

    def add(contest: str, record: Record, areas: dict[str, Area]) -> None:
        path = results.live_path(contest, okres_of)
        live.add(path, contest, record)
        # A city council obvod of 2018 whose districts ŠÚ SR did not count
        # by okrsok has none joined.
        if areas:
            live.add_okrsky(path, contest, areas)

    mayors = _group(p.rows("tab05f"), _obec)
    for code, votes in sorted(mayors.items()):
        if code not in results.CITY_OBCE:
            turnout = _lookup(by_obec, code, "turnout of obec")
            record = _record(turnout, "starosta", votes, 1)
            add(f"starosta:{code}", record, _areas(turnout, "starosta", votes, _okrsok))
    councils = _group(p.rows("tab08f"), lambda r: (r["OBEC"], r["VOOBEC"]))
    for (code, obvod), votes in sorted(councils.items()):
        if code not in results.CITY_OBCE:
            turnout = _lookup(by_obvod, (code, obvod), "turnout of obvod")
            record = _record(turnout, "oz", votes, seats.get((code, obvod)))
            add(
                f"oz:{code}/{int(obvod)}", record, _areas(turnout, "oz", votes, _okrsok)
            )
    for contest, record, areas in _cities(p, okres_of, seats, out, log):
        add(contest, record, areas)
    held = {
        r["OBEC"]
        for r in units
        if r["VOLBY_TYP"] != _NOT_HELD and r["OBEC"] not in results.CITY_OBCE
    }
    counted = (len(held & by_obec.keys()), len(held))
    live.source["oso"] = results.source(p.time.isoformat(), counted, "obce")


def _regional(p: Package, live: Live) -> None:
    """Add the contests of regional package *p* and its source to *live*."""
    units = {r["OBEC"]: r for r in p.rows("tab0dc")}
    seats = {r["VOBVOD"]: int(r["P_POS_VOL"]) for r in p.rows("tab02ab")}
    okrsky = p.rows("tab02bd")
    levels = (("predseda", "KRAJ", "tab06d"), ("zsk", "VOBVOD", "tab09d"))
    for kind, column, table in levels:
        unit = _unit_of(units, column)
        turnout = _group(okrsky, unit)
        for code, votes in sorted(_group(p.rows(table), unit).items()):
            if kind == "predseda":
                kraj, contest, n = code, f"predseda:{code}", 1
            else:
                kraj, number = _vobvod(code)
                contest, n = f"zsk:{kraj}/{number}", _lookup(seats, code, "seats of")
            rows = _lookup(turnout, code, "turnout of")
            record = _record(rows, kind, votes, n)
            record.areas = _areas(rows, kind, votes, _obec)
            path = results.live_path(contest, {})
            live.add(path, contest, record)
            live.add_okrsky(path, contest, _areas(rows, kind, votes, _okrsok))
    counted = (len(okrsky), len(okrsky))
    live.source["osk"] = results.source(p.time.isoformat(), counted, "okrsky")


def _unit_of(
    units: Mapping[str, Mapping[str, str]], column: str
) -> Callable[[Mapping[str, str]], str]:
    """Return what gives a row's regional unit: *column* of its obec's units row."""

    def unit(row: Mapping[str, str]) -> str:
        return _lookup(units, row["OBEC"], "obec in tab0dc")[column]

    return unit


# Bratislava's and Košice's own contests.


def _as_2026(row: Mapping[str, str], okres_of: Mapping[str, str]) -> dict[str, str]:
    """Return turnout *row* (``tab02bf``) with the columns of the 2026 tables."""
    return {
        _C_CITY: row["OBEC"],
        _C_OBEC: row["OBEC"],
        _C_OKRES: okres_of.get(row["OBEC"], ""),
        _C_OBVOD: row["VOOBEC"],
        _C_OKRSOK: row["OKRSOK"],
        _C_ELIGIBLE: row["P_ZAP"],
        _C_VOTERS: row["P_ZUC"],
        _C_VALID["starosta"]: row["P_HL_STA"],
        _C_VALID["oz"]: row["P_HL_ZAS"],
    }


def _vote_as_2026(row: Mapping[str, str]) -> dict[str, str]:
    """Return vote *row* (``tab05f``, ``tab08f``) as the 2026 tables have it.

    The share has a decimal point there.
    """
    return {
        _C_OBVOD: row["VOOBEC"],
        _C_OKRSOK: row["OKRSOK"],
        _C_NUMBER: row["PC_HL"],
        _C_VOTES: row["P_HL"],
        _C_SHARE: row["P_HL_PCT"].replace(",", "."),
    }


def join_by_number(
    turnout: Sequence[Mapping[str, str]],
    districts: Sequence[Mapping[str, str]],
    matches: Mapping[int, int],
) -> dict[int, int]:
    """Return city okrsok rows left by *matches* → their district's row.

    Rows are given by their index in *turnout* (the cities') and *districts*
    as in :func:`results.city_matches`, which gives *matches*. The cities
    number each okrsok as its district does, which every okrsok matched by
    its voters in 2022 bears out. An okrsok whose voters differ from its
    district's record, or equal those of another, is joined to the okrsok
    of its number in the districts of its council obvod's matched okrsky,
    where exactly one such row is not matched yet and no other city okrsok
    claims it.
    """
    near: dict[tuple[str, str], set[str]] = defaultdict(set)
    for i, j in matches.items():
        near[(turnout[i][_C_CITY], turnout[i][_C_OBVOD])].add(districts[j][_C_OBEC])
    index = {(r[_C_OBEC], int(r[_C_OKRSOK])): j for j, r in enumerate(districts)}
    taken = set(matches.values())
    claims: dict[int, list[int]] = defaultdict(list)
    for i, r in enumerate(turnout):
        if r[_C_CITY] not in results.CITY_OBCE or i in matches:
            continue
        options = {
            index[key]
            for district in near[(r[_C_CITY], r[_C_OBVOD])]
            if (key := (district, int(r[_C_OKRSOK]))) in index
            and index[key] not in taken
        }
        if len(options) == 1:
            claims[options.pop()].append(i)
    return {mine[0]: j for j, mine in claims.items() if len(mine) == 1}


@dataclass
class _Cities:
    """Bratislava's and Košice's okrsky, joined to the districts' okrsky.

    Okrsky are given by their index in :attr:`rows`, :attr:`turnout`.
    """

    rows: Rows
    """The cities' rows of ``tab02bf``."""
    turnout: list[dict[str, str]]
    """The same with the columns of the 2026 tables (:func:`_as_2026`)."""
    districts: list[dict[str, str]]
    """The other rows of ``tab02bf``, so renamed."""
    matches: dict[int, int]
    """City okrsok → its district's row in :attr:`districts`."""
    district_of: dict[int, str]
    """City okrsok → its district (:func:`results.city_districts`)."""

    def name(self, i: int) -> str:
        """Return city okrsok *i* as ``BA <council obvod>/<number>``."""
        r = self.turnout[i]
        return f"{results.CITY_OBCE[r[_C_CITY]]} {r[_C_OBVOD]}/{r[_C_OKRSOK]}"

    def okrsok_of(self, i: int) -> str | None:
        """Return city okrsok *i* in its district's numbering, if joined."""
        j = self.matches.get(i)
        if j is None:
            return None
        d = self.districts[j]
        return results.okrsok_key(d[_C_OBEC], d[_C_OKRSOK])


def _join_cities(
    rows: Rows, okres_of: Mapping[str, str], out: FinalResults, log: results.Log
) -> _Cities:
    """Return the cities' okrsky of turnout *rows* (``tab02bf``), joined.

    By voters (:func:`results.city_matches`), then by number
    (:func:`join_by_number`); those joined by number and those not joined
    go to *out*, and *log* is told.
    """
    cities = [r for r in rows if r["OBEC"] in results.CITY_OBCE]
    turnout = [_as_2026(r, okres_of) for r in cities]
    districts = [
        _as_2026(r, okres_of) for r in rows if r["OBEC"] not in results.CITY_OBCE
    ]
    matches = results.city_matches(turnout, districts)
    extra = join_by_number(turnout, districts, matches)
    matches |= extra
    district_of = results.city_districts(turnout, districts, matches)
    c = _Cities(cities, turnout, districts, matches, district_of)
    out.city_by_number = [f"{c.name(i)} → {c.okrsok_of(i)}" for i in sorted(extra)]
    out.city_unmatched = [c.name(i) for i in range(len(turnout)) if i not in matches]
    log(
        f"city okrsky: {len(matches) - len(extra)} of {len(turnout)} joined to a"
        f" district's by voters, {len(extra)} by number alone"
        + (f" ({', '.join(out.city_by_number)})" if extra else "")
        + f"; {len(out.city_unmatched)} left out of the okrsok files"
        + (f" ({', '.join(out.city_unmatched)})" if out.city_unmatched else "")
    )
    return c


def _city_contest(
    c: _Cities,
    contest: str,
    indices: Sequence[int],
    votes: Sequence[Mapping[str, str]],
    seats: int | None,
    log: results.Log,
) -> tuple[str, Record, dict[str, Area]]:
    """Return a city contest of okrsky *indices* and vote rows *votes*.

    Its record has ``areas`` by district; it is returned with its okrsky.
    Okrsky whose votes cannot be told apart (:func:`results.city_votes`)
    are left out of the okrsky, and so are the districts' ``areas`` they
    make unknown; *log* is told.
    """
    kind = contest.partition(":")[0]
    record = _record([c.rows[i] for i in indices], kind, votes, seats)
    renamed = [_vote_as_2026(v) for v in votes]
    by_row = results.city_votes(c.turnout, indices, renamed, kind, seats)
    record.areas, gone = results.city_areas(
        c.turnout, indices, by_row, kind, c.district_of.get
    )
    if by_row.unresolved:
        numbers = ", ".join(
            f"{c.name(u.okrsky[0])} ×{len(u.okrsky)}" for u in by_row.unresolved
        )
        log(
            f"{contest}: okrsky of a number not told apart ({numbers}); left out"
            " of the okrsok file"
            + (f" and of the areas of {', '.join(sorted(gone))}" if gone else "")
        )
    okrsky, _ = results.city_areas(c.turnout, indices, by_row, kind, c.okrsok_of)
    return contest, record, okrsky


def _cities(
    p: Package,
    okres_of: Mapping[str, str],
    seats: Mapping[tuple[str, str], int],
    out: FinalResults,
    log: results.Log,
) -> list[tuple[str, Record, dict[str, Area]]]:
    """Return the contests of Bratislava and Košice as wholes, as in 2026.

    A city okrsok joined to one of a district (:func:`_join_cities`) goes to
    the okrsok files by it.
    """
    c = _join_cities(p.rows("tab02bf"), okres_of, out, log)
    rows_of = _group(range(len(c.turnout)), lambda i: c.turnout[i][_C_CITY])
    mayors = _group((r for r in p.rows("tab05f") if r["OBEC"] in rows_of), _obec)
    found = [
        _city_contest(c, f"starosta:{_area(code)}", rows_of[code], votes, 1, log)
        for code, votes in sorted(mayors.items())
    ]
    councils = _group(
        (r for r in p.rows("tab08f") if r["OBEC"] in rows_of),
        lambda r: (r["OBEC"], r["VOOBEC"]),
    )
    for (code, obvod), votes in sorted(councils.items()):
        mine = [i for i in rows_of[code] if c.turnout[i][_C_OBVOD] == obvod]
        contest = f"oz:{_area(code)}/{int(obvod)}"
        found.append(
            _city_contest(c, contest, mine, votes, seats.get((code, obvod)), log)
        )
    return found


# The packages of the elections held apart: 2017 and 2018.

PARTS = ("oso", "okrsky", "osk")
"""What format ``susr`` names (``elections.toml``), in this order: the
municipal package, the okrsky of the municipal package of 2018 (a zip of
their own), the regional package."""
_OF = {"oso": ("oso", "okrsky"), "osk": ("osk",)}
"""The parts of :data:`PARTS` that make up each election's package."""
_XLSX_FILE = re.compile(r"(OSO|OSK)_\d{4}_tab\w+\.xlsx$", re.IGNORECASE)
# Columns of the XLSX tables, which name them in full.
_X_KRAJ = "Kód kraja"
_X_KRAJ_NAME = "Kraj"
_X_REGION = "Kód samosprávneho kraja"
_X_OKRES = "Kód okresu"
_X_OKRES_NAME = "Názov okresu"
_X_OBEC = "Kód obce"
_X_OBEC_NAME = ("Názov obce", "Obec")
_X_VOBVOD = "Kód volebného obvodu"
_X_OBVOD = "Volebný obvod v obci"
_X_OKRSOK = "Okrsok"
_X_NUMBER = "Poradie na hlasovacom lístku"
_X_ORDER = "Poradie zvolenia v obci"
_X_FIRST_NAME = "Meno"
_X_SURNAME = "Priezvisko"
_X_FULL_NAME = ("Meno a priezvisko", "Meno a priezvisko kandidáta")
_X_TITLE = "Titul"
_X_AGE = "Vek"
_X_OCCUPATION = "Zamestnanie"
_X_RESIDENCE = "Obec"
"""Of a regional candidate: the obec of residence, by name."""
_X_PARTIES = "Politický subjekt"
_X_NOTE = "Poznámka"
_X_FLAG = "Kandidát"
_X_VOTES = "Počet platných hlasov"
_X_SHARE = "Podiel platných hlasov v %"
_X_ELIGIBLE = (
    "Počet zapísaných voličov",
    "Počet voličov zapísaných v zoznamoch voličov",
)
_X_VOTERS = (
    # The envelopes issued: the voters who took part, as 2022 counts them.
    "Počet vydaných obálok",
    "Počet voličov, ktorí sa zúčastnili na hlasovaní",
)
_X_VALID = "Počet platných hlasovacích lístkov odovzdaných pre voľby "
_X_OKRSKY = "Počet okrskov"
_X_SEATS = "Počet volených poslancov"
_X_OBVODY = "Počet volebných obvodov v obci"
_X_TYPE = "Typ volieb"
_X_PARTY_SHORT = "Skratka politickej strany"
_X_PARTY_NAME = "Názov politickej strany"
_X_INDEPENDENT = "NEKA"
_X_NOT_HELD = "nekonajú sa"
"""``Typ volieb`` of an obec where no election was held, casefolded."""
_X_ELECTED = "zvolený"
_X_FLAGS = {_X_ELECTED: _ELECTED, _WITHDRAWN: _WITHDRAWN, "": ""}
"""``Kandidát`` of the 2018 vote tables → ``KANDIDAT`` of 2022."""
_X_NOTES = {"2": _ELECTED, "0": _WITHDRAWN, "1": ""}
"""``Poznámka`` of the 2017 vote tables (2 elected, 0 withdrawn, 1 neither,
as the candidates marked ``X`` in ``tab0ab`` and ``tab0bc`` bear out) →
``KANDIDAT`` of 2022."""


def read_lists(paths: Mapping[str, Path]) -> candidates.Lists:
    """Return the candidates of the packages *paths*, by part (:data:`PARTS`).

    Those of 2022 (:func:`read_candidates`), or of either or both of the
    elections before (:func:`municipal_lists`, :func:`regional_lists`).
    """
    try:
        if _of_2022(paths):
            return read_candidates(
                open_package(paths["oso"]), open_package(paths["osk"])
            )
        out = candidates.Lists([])
        if "oso" in paths:
            municipal_lists(xlsx_package(paths, "oso"), out)
        if "osk" in paths:
            regional_lists(xlsx_package(paths, "osk"), out)
    except tables.TableError as e:
        raise StatOfficeError(str(e)) from e
    return out


def read_final(
    paths: Mapping[str, Path], log: results.Log = progress.note
) -> FinalResults:
    """Return the final results of the packages *paths*, by part (:data:`PARTS`).

    Those of 2022 (:func:`read_results`), or of either or both of the
    elections before (:func:`municipal_results`, :func:`regional_results`).
    """
    try:
        if _of_2022(paths):
            return read_results(
                open_package(paths["oso"]), open_package(paths["osk"]), log
            )
        out = FinalResults(Live("final"), [])
        if "oso" in paths:
            municipal_results(xlsx_package(paths, "oso"), out, log)
        if "osk" in paths:
            regional_results(xlsx_package(paths, "osk"), out.live)
    except (tables.TableError, ValueError) as e:
        raise StatOfficeError(str(e)) from e
    return out


def _of_2022(paths: Mapping[str, Path]) -> bool:
    """Return whether *paths* are the packages of 2022; fail if only some are."""
    found = []
    for path in paths.values():
        try:
            with zipfile.ZipFile(path) as z:
                found.append(any(_PACKAGE_FILE.search(n) for n in z.namelist()))
        except (OSError, zipfile.BadZipFile) as e:
            raise StatOfficeError(f"{path}: {e}") from e
    if any(found) and (not all(found) or set(paths) != {"oso", "osk"}):
        raise StatOfficeError("the packages of 2022 are two, oso and osk, both of 2022")
    return any(found)


def xlsx_package(paths: Mapping[str, Path], election: str) -> tables.Package:
    """Return the XLSX tables of *election* (``oso``, ``osk``) of *paths*.

    The municipal package of 2018 is two zips, ``oso`` and ``okrsky``.
    Every table must be of the election (``OSO_2018_tab0a.xlsx``).
    """
    package = tables.open_package(
        [paths[part] for part in _OF[election] if part in paths], results.TIMEZONE
    )
    for f in package.files.values():
        m = _XLSX_FILE.search(f.name)
        if m is None or m.group(1).lower() != election:
            raise StatOfficeError(f"{f.name}: not a table of the {election} package")
    if not package.files:
        raise StatOfficeError(f"no tables of the {election} package")
    return package


def _coded(
    p: tables.Package, table: str, columns: Mapping[str, str | tuple[str, ...]]
) -> Rows:
    """Return the rows of *table* of *p* with the coded columns of 2022.

    *columns* maps a coded column to the column (or its aliases) it is
    read from. Read row by row, the vote tables per okrsok being large,
    from the first worksheet: a second, if any, explains the columns.
    """
    streams = p.stream(table)
    s = next(streams)
    at = {
        code: s.index(*((name,) if isinstance(name, str) else name))
        for code, name in columns.items()
    }
    out = [dict(zip(at, cells)) for cells in s.cells(*at.values())]
    # The worksheet is read while the file stays open.
    streams.close()
    return out


def _short_names(table: tables.Table) -> dict[str, str]:
    """Return short form → name of the parties of *table* (``tab0b``, ``tab0ca``)."""
    short, name = table.column(_X_PARTY_SHORT), table.column(_X_PARTY_NAME)
    return {candidates.clean(r[short]): candidates.clean(r[name]) for r in table.rows}


def short_nomination(text: str, parties: Mapping[str, str]) -> tuple[list[str], bool]:
    """Return (party names, independent) of short forms *text* separated by ``,``.

    A short form may hold ``,`` (:func:`candidates.parse_parties`);
    ``NEKA`` is an independent candidate.
    """
    shorts, _ = candidates.parse_parties(text, ",", parties)
    if shorts == [_X_INDEPENDENT]:
        return [], True
    unknown = [s for s in shorts if s not in parties]
    if unknown:
        raise StatOfficeError(f"unknown parties {unknown} in {text!r}")
    return [parties[s] for s in shorts], False


def _xlsx_entry(
    kind: str,
    table: tables.Table,
    row: Mapping[str, str],
    source: str,
    parties: Mapping[str, str],
    number: str,
) -> candidates.Entry:
    """Return the :class:`candidates.Entry` of a candidate's *row* of *table*.

    Numbered by column *number*; the name in two columns, else with the
    titles in one (:func:`candidates.split_name`); title, age and
    occupation where the table has them. Its contest's area by code: the
    obec (Bratislava and Košice as wholes ``BA``, ``KE``) or the kraj; a
    regional candidate's residence the obec's name.
    """
    full = table.optional(*_X_FULL_NAME)
    if full is not None:
        before, first, surname, after = candidates.split_name(row[full])
    else:
        first = candidates.clean(row[table.column(_X_FIRST_NAME)])
        surname = candidates.clean(row[table.column(_X_SURNAME)])
        title = table.optional(_X_TITLE)
        before, after = candidates.split_title(
            candidates.clean(row[title]) if title else ""
        )
    age, occupation = table.optional(_X_AGE), table.optional(_X_OCCUPATION)
    names, independent = short_nomination(row[table.column(_X_PARTIES)], parties)
    if kind in kinds.MUNICIPAL:
        code = row[table.column(_X_OBEC)]
        where = {
            "region": candidates.clean(row[table.column(_X_OKRES_NAME)]),
            "okres_code": row[table.column(_X_OKRES)],
            "obec": candidates.clean(row[table.column(*_X_OBEC_NAME)]),
            "residence": "",
            "area": _area(code),
        }
        obvod = int(row[table.column(_X_OBVOD)]) if kind == "oz" else None
    else:
        kraj = row[table.column(_X_KRAJ)]
        where = {
            "region": _kraj_region(candidates.clean(row[table.column(_X_KRAJ_NAME)])),
            "okres_code": "",
            "obec": "",
            "residence": candidates.clean(row[table.column(_X_RESIDENCE)]),
            "area": kraj,
        }
        obvod = None
        if kind == "zsk":
            of, obvod = _vobvod(row[table.column(_X_VOBVOD)])
            if of != kraj:
                raise StatOfficeError(
                    f"obvod {row[table.column(_X_VOBVOD)]} not of kraj"
                )
    return candidates.Entry(
        kind=kind,
        source=source,
        obvod=obvod,
        number=int(row[table.column(number)]),
        first_name=first,
        surname=surname,
        title_before=before,
        title_after=after,
        age=int(row[age]) if age else None,
        occupation=candidates.clean(row[occupation]) if occupation else "",
        parties=names,
        independent=independent,
        **where,
    )


def _entry_contest(e: candidates.Entry) -> str:
    """Return the id of the contest of an *e* whose area is given."""
    return f"{e.kind}:{e.area}" + (f"/{e.obvod}" if e.obvod is not None else "")


def _add_lists(
    out: candidates.Lists,
    table: tables.Table,
    rows: Iterable[tuple[int, Mapping[str, str]]],
    kind: str,
    parties: Mapping[str, str],
    number: str,
) -> set[str]:
    """Add the candidates of numbered *rows* of *table* to *out*.

    ``X`` in ``Poznámka`` marks one who withdrew. Returns their contests.
    """
    note = table.optional(_X_NOTE)
    found = set()
    for line, row in rows:
        source = f"{table.name}: data row {line}"
        try:
            entry = _xlsx_entry(kind, table, row, source, parties, number)
        except (ValueError, StatOfficeError, candidates.CandidatesError) as e:
            raise StatOfficeError(f"{source}: {e}") from e
        out.entries.append(entry)
        contest = _entry_contest(entry)
        found.add(contest)
        if note is not None and row[note].strip() == _WITHDRAWN:
            out.withdrawn.add(f"{contest}#{entry.number}")
    return found


def municipal_lists(p: tables.Package, out: candidates.Lists) -> None:
    """Add the candidates of the municipal package of 2018 *p* to *out*.

    ``tab0b`` the parties, whose short forms the lists name; ``tab0a`` the
    mayor candidates. The councils of the obce whose results ŠÚ SR counted
    by okrsok (its okrsky zip; ``IVIS``) have every candidate in ``tab0d``;
    of the others only the elected are published (:func:`_elected`). These
    council contests are ``elected_only``. No list has the candidates'
    titles (but ``tab06d``), ages or occupations. The seats:
    :func:`council_seats`.
    """
    parties = _short_names(p.table("tab0b"))
    mayors = p.table("tab0a")
    _add_lists(out, mayors, enumerate(mayors.rows, 1), "starosta", parties, _X_NUMBER)
    full = p.table("tab0d")
    councils = _add_lists(out, full, enumerate(full.rows, 1), "oz", parties, _X_NUMBER)
    elected: set[str] = set()
    numbered, ordered = _elected(p)
    for table, rows, number in (numbered, ordered):
        first = len(out.entries)
        elected |= _add_lists(out, table, rows, "oz", parties, number)
        if table is numbered[0]:
            _titled(out.entries[first:], p.table("tab06d"))
    for contest in elected:
        out.contests[contest] = {"elected_only": True}
    # An obec of one obvod has seats, though it may have no candidates.
    seats = {f"oz:{_area(c)}/{n}": s for (c, n), s in council_seats(p).items()}
    out.seats |= {c: s for c, s in seats.items() if c in councils | elected}
    columns = {"OBEC": _X_OBEC, "TYPE": _X_TYPE, "OBVODY": _X_OBVODY, "SEATS": _X_SEATS}
    units = _coded(p, "tab0c", columns)
    rows = ((r["OBEC"], r["TYPE"], r["OBVODY"], r["SEATS"]) for r in units)
    not_held(out, rows, "tab0c")


_Elected = tuple[tables.Table, list[tuple[int, dict[str, str]]], str]
"""A table of the elected councillors, its rows by line, the column
numbering them."""


def _elected(p: tables.Package) -> tuple[_Elected, _Elected]:
    """Return the elected councillors of the obce of 2018 *p* without ``tab0d``.

    ``tab06`` has those of the obce ŠÚ SR counted with its system, by
    ballot number (of 8 obce outside ``tab0d``); ``tab06d`` those of every
    other obec and again those 8, numbered by the order elected in the
    obec, the name with its titles in one column. Each obec's are taken
    from one table: ``tab06`` where it has them, its ballot numbers being
    those of the ballot.
    """
    listed = {r[_X_OBEC] for r in p.table("tab0d").rows}
    numbered = p.table("tab06")
    rows = [
        (line, r)
        for line, r in enumerate(numbered.rows, 1)
        if r[numbered.column(_X_OBEC)] not in listed
    ]
    taken = listed | {r[_X_OBEC] for _, r in rows}
    ordered = p.table("tab06d")
    others = [
        (line, r)
        for line, r in enumerate(ordered.rows, 1)
        if r[ordered.column(_X_OBEC)] not in taken
    ]
    return (numbered, rows, _X_NUMBER), (ordered, others, _X_ORDER)


def _titled(entries: Sequence[candidates.Entry], ordered: tables.Table) -> None:
    """Give *entries* (of ``tab06``) the titles ``tab06d`` has of them.

    The same councillor there: of the same obec and obvod, with the same
    name (:func:`candidates.name_words`).
    """
    full = ordered.column(*_X_FULL_NAME)
    titles = {}
    for r in ordered.rows:
        before, first, surname, after = candidates.split_name(r[full])
        key = (
            r[_X_OBEC],
            int(r[_X_OBVOD]),
            candidates.name_words(f"{first} {surname}"),
        )
        titles[key] = (before, after)
    for e in entries:
        key = (e.area, e.obvod, candidates.name_words(f"{e.first_name} {e.surname}"))
        e.title_before, e.title_after = titles.get(key, ("", ""))


def council_seats(p: tables.Package) -> dict[tuple[str, int], int]:
    """Return (obec, obvod) → seats of the councils of the 2018 package *p*.

    ``tab0c`` gives an obec's seats and obvody: an obec of one obvod elects
    them there. Of an obec of several, ŠÚ SR gives no seats per obvod; where
    the obec filled every seat (as many elected, in ``tab08e`` or
    :func:`_elected`, as it had seats), each obvod elected as many as it
    had, no obvod electing more, so its seats are its elected.
    """
    votes = p.table("tab08e")
    elected = Counter(
        (r[_X_OBEC], int(r[_X_OBVOD])) for r in votes.rows if r[_X_FLAG] == _X_ELECTED
    )
    for _, rows, _ in _elected(p):
        elected.update((r[_X_OBEC], int(r[_X_OBVOD])) for _, r in rows)
    units = p.table("tab0c")
    code, count, number = (
        units.column(_X_OBEC),
        units.column(_X_OBVODY),
        units.column(_X_SEATS),
    )
    out = {}
    for r in units.rows:
        if r[count] == "1":
            out[(r[code], 1)] = int(r[number])
            continue
        mine = {key: n for key, n in elected.items() if key[0] == r[code]}
        if sum(mine.values()) == int(r[number]):
            out |= mine
    return out


def regional_lists(p: tables.Package, out: candidates.Lists) -> None:
    """Add the candidates of the regional package of 2017 *p* to *out*.

    ``tab0ca`` the parties, whose short forms the lists name; ``tab0ab``
    the president candidates, ``tab0bc`` the council candidates, with
    title, age, occupation and the obec of residence; ``tab0db`` the seats
    of each regional obvod (code ``<kraj><nn>``), ``tab0dc`` the obvod of
    every obec (Bratislava's and Košice's districts).
    """
    parties = _short_names(p.table("tab0ca"))
    for table_id, kind in (("tab0ab", "predseda"), ("tab0bc", "zsk")):
        t = p.table(table_id)
        _add_lists(out, t, enumerate(t.rows, 1), kind, parties, _X_NUMBER)
    seats = p.table("tab0db")
    obvod, number = seats.column(_X_VOBVOD), seats.column(_X_SEATS)
    for r in seats.rows:
        kraj, n = _vobvod(r[obvod])
        out.seats[f"zsk:{kraj}/{n}"] = int(r[number])
    units = p.table("tab0dc")
    kraj_of, obvod, obec = (
        units.column(_X_KRAJ),
        units.column(_X_VOBVOD),
        units.column(_X_OBEC),
    )
    for r in units.rows:
        kraj, n = _vobvod(r[obvod])
        if kraj != r[kraj_of]:
            raise StatOfficeError(f"{units.name}: obvod {r[obvod]} not of its kraj")
        out.zsk[r[obec]] = n


def _coded_package(p: tables.Package, election: str, coded: dict[str, Rows]) -> Package:
    """Return the rows *coded* as the 2022 package of *election* (``oso``, ``osk``)."""
    name = ", ".join(sorted({f.path.name for f in p.files.values()}))
    if p.time is None:
        raise StatOfficeError(f"{name}: not a zip, so of no time")
    return Package(name, election, p.time, coded)


def municipal_results(p: tables.Package, out: FinalResults, log: results.Log) -> None:
    """Add the final results of the municipal package of 2018 *p* to *out*.

    The obce counted by okrsok (``IVIS``: the okrsky zip, with Bratislava's
    and Košice's own contests) as in 2022 (:func:`_municipal`), their tables
    of turnout and votes per okrsok (``tab02bf``, ``tab05f``, ``tab08f``)
    read as 2022's, the elected and the withdrawn flagged from the mayors'
    votes per obec (``tab05``) and the councils' per obvod (``tab08e``):
    the withdrawn council candidates have no votes. The others per obec:
    the turnout (``tab02bd``, the voters the envelopes issued), the mayors'
    votes (``tab05``) and the elected councillors' (``tab06``, ``tab06d``,
    numbered as :func:`municipal_lists` numbers them), with the obec's
    turnout where it elects in one obvod and none where in several. Seats
    as :func:`council_seats` has them.
    """
    seats = council_seats(p)
    units = _coded(p, "tab0c", {"OBEC": _X_OBEC, "OKRES": _X_OKRES, "TYPE": _X_TYPE})
    held = {r["OBEC"] for r in units if r["TYPE"].casefold() != _X_NOT_HELD}
    okres_of = {r["OBEC"]: r["OKRES"] for r in units}
    place = {"OBEC": _X_OBEC, "VOOBEC": _X_OBVOD, "OKRSOK": _X_OKRSOK}
    vote = {"PC_HL": _X_NUMBER, "P_HL": _X_VOTES}
    valid = {
        "P_HL_STA": _X_VALID + "starostu",
        "P_HL_ZAS": _X_VALID + "do zastupiteľstva",
    }
    turnout = _coded(
        p,
        "tab02bf",
        place | {"P_ZAP": _X_ELIGIBLE, "P_ZUC": _X_VOTERS} | valid,
    )
    mayors = _coded(p, "tab05f", place | vote | {"P_HL_PCT": _X_SHARE})
    councils = _coded(p, "tab08f", place | vote | {"P_HL_PCT": _X_SHARE})
    of_obec = _coded(p, "tab05", {"OBEC": _X_OBEC, "KANDIDAT": _X_FLAG} | vote)
    of_obvod = _coded(
        p, "tab08e", {"OBEC": _X_OBEC, "VOOBEC": _X_OBVOD, "KANDIDAT": _X_FLAG} | vote
    )
    for rows in (turnout, mayors, councils, of_obvod):
        for r in rows:
            r["VOOBEC"] = str(int(r["VOOBEC"]))
            if "OKRSOK" in r:
                r["OKRSOK"] = str(int(r["OKRSOK"]))
    for rows in (of_obec, of_obvod):
        for r in rows:
            r["KANDIDAT"] = _lookup(_X_FLAGS, r["KANDIDAT"], "Kandidát")
    flag = {(r["OBEC"], int(r["PC_HL"])): r["KANDIDAT"] for r in of_obec}
    for r in mayors:
        r["KANDIDAT"] = _lookup(flag, (r["OBEC"], int(r["PC_HL"])), "mayor")
    flag = {(r["OBEC"], r["VOOBEC"], int(r["PC_HL"])): r["KANDIDAT"] for r in of_obvod}
    # The withdrawn have votes per okrsok, but none per obvod (tab08e).
    listed = _coded(
        p,
        "tab0d",
        {"OBEC": _X_OBEC, "VOOBEC": _X_OBVOD, "PC_HL": _X_NUMBER, "X": _X_NOTE},
    )
    flag |= {
        (r["OBEC"], str(int(r["VOOBEC"])), int(r["PC_HL"])): _WITHDRAWN
        for r in listed
        if r["X"] == _WITHDRAWN
    }
    for r in councils:
        key = (r["OBEC"], r["VOOBEC"], int(r["PC_HL"]))
        r["KANDIDAT"] = _lookup(flag, key, "council candidate")
    coded = _coded_package(
        p,
        "oso",
        {
            "tab0dd": [
                {"OBEC": c, "OKRES": o, "VOLBY_TYP": "1" if c in held else _NOT_HELD}
                for c, o in okres_of.items()
            ],
            "tab02ad": [
                {"OBEC": c, "VOOBEC": str(n), "P_POS_VOL": str(s)}
                for (c, n), s in seats.items()
            ],
            "tab02bf": turnout,
            "tab05f": mayors,
            "tab08f": councils,
        },
    )
    _municipal(coded, out, log)
    by_okrsok = {r["OBEC"] for r in turnout}
    if not results.CITY_OBCE.keys() <= by_okrsok:
        raise StatOfficeError("Bratislava and Košice are not counted by okrsok")
    obce = _coded(
        p,
        "tab02bd",
        {"OBEC": _X_OBEC, "OKRSKY": _X_OKRSKY, "P_ZAP": _X_ELIGIBLE, "P_ZUC": _X_VOTERS}
        | valid,
    )
    _by_obec(p, out.live, of_obec, obce, by_okrsok, seats, okres_of)
    held -= results.CITY_OBCE.keys()
    counted = (len(held & {r["OBEC"] for r in obce}), len(held))
    out.live.source["oso"] = results.source(coded.time.isoformat(), counted, "obce")
    listed = {
        _contest_of(kind, r)
        for table, kind in (("tab0a", "starosta"), ("tab0d", "oz"))
        for r in p.table(table).rows
    }
    out.no_result = sorted(listed - out.live.records().keys())
    if out.no_result:
        log(f"no result, though candidates stood: {', '.join(out.no_result)}")


def _contest_of(kind: str, row: Mapping[str, str]) -> str:
    """Return the contest of a municipal candidate's *row* of a 2018 table."""
    area = _area(row[_X_OBEC])
    return f"oz:{area}/{int(row[_X_OBVOD])}" if kind == "oz" else f"starosta:{area}"


def _by_obec(
    p: tables.Package,
    live: Live,
    mayors: Rows,
    obce: Rows,
    by_okrsok: set[str],
    seats: Mapping[tuple[str, int], int],
    okres_of: Mapping[str, str],
) -> None:
    """Add the contests of the obce of 2018 *p* not counted by okrsok to *live*.

    *mayors* are the mayors' votes per obec (``tab05``), *obce* the turnout
    per obec (``tab02bd``), both coded; see :func:`municipal_results`.
    """
    turnout = {r["OBEC"]: r for r in obce}
    obvody = {
        r["OBEC"]: r["N"] for r in _coded(p, "tab0c", {"OBEC": _X_OBEC, "N": _X_OBVODY})
    }

    def record(code: str, kind: str, cands: list[Ballot], n: int | None) -> Record:
        filled = sum(1 for c in cands if c[2] == 1)
        if kind == "oz" and obvody[code] != "1":
            # Which okrsky an obvod of several had, ŠÚ SR does not say.
            return Record("final", seats=n, filled=filled, candidates=cands)
        row = turnout[code]
        okrsky = int(row["OKRSKY"])
        eligible, voters, valid = _sums([row], kind)
        return Record(
            "final", (okrsky, okrsky), eligible, voters, valid, n, filled, cands
        )

    def add(contest: str, r: Record) -> None:
        live.add(results.live_path(contest, okres_of), contest, r)

    for code, rows in sorted(_group(mayors, _obec).items()):
        if code not in by_okrsok:
            add(
                f"starosta:{code}",
                record(code, "starosta", ballots(rows, "starosta"), 1),
            )
    for _, rows, number in _elected(p):
        councils = _group(
            (r for _, r in rows), lambda r: (r[_X_OBEC], int(r[_X_OBVOD]))
        )
        for (code, obvod), mine in sorted(councils.items()):
            if code not in by_okrsok:
                cands: list[Ballot] = [
                    (int(r[number]), int(r[_X_VOTES]), 1) for r in mine
                ]
                n = seats.get((code, obvod))
                add(f"oz:{code}/{obvod}", record(code, "oz", cands, n))


def regional_results(p: tables.Package, live: Live) -> None:
    """Add the final results of the regional package of 2017 *p* to *live*.

    As in 2022 (:func:`_regional`): the turnout per okrsok (``tab02d``) and
    the votes per okrsok of the presidents (``tab06e``) and councils
    (``tab09e``), read as 2022's; ``Poznámka`` flags the elected and the
    withdrawn (:data:`_X_NOTES`). An okrsok is named by its obec and number
    (``Bratislava - Staré Mesto 1``).
    """
    units = p.table("tab0dc")
    seats = p.table("tab0db")
    place = {"OBEC": _X_OBEC, "OBEC_NAME": _X_OBEC_NAME, "OKRSOK": _X_OKRSOK}
    vote = {
        "PC_HL": _X_NUMBER,
        "P_HL": _X_VOTES,
        "P_HL_PCT": _X_SHARE,
        "KANDIDAT": _X_NOTE,
    }
    turnout = _coded(
        p,
        "tab02d",
        place
        | {
            "P_ZAP": _X_ELIGIBLE,
            "P_ZUC": _X_VOTERS,
            "P_HL_PRE": _X_VALID + "predsedu",
            "P_HL_POS": _X_VALID + "do zastupiteľstva",
        },
    )
    presidents = _coded(p, "tab06e", place | vote)
    councils = _coded(p, "tab09e", place | vote)
    for rows in (turnout, presidents, councils):
        for r in rows:
            r["OKRSOK"] = _okrsok_number(r.pop("OBEC_NAME"), r["OKRSOK"])
    for rows in (presidents, councils):
        for r in rows:
            r["KANDIDAT"] = _lookup(_X_NOTES, r["KANDIDAT"], "Poznámka")
    coded = _coded_package(
        p,
        "osk",
        {
            "tab0dc": [
                {"OBEC": r[_X_OBEC], "KRAJ": r[_X_KRAJ], "VOBVOD": r[_X_VOBVOD]}
                for r in units.rows
            ],
            "tab02ab": [
                {"VOBVOD": r[_X_VOBVOD], "P_POS_VOL": r[_X_SEATS]} for r in seats.rows
            ],
            "tab02bd": turnout,
            "tab06d": presidents,
            "tab09d": councils,
        },
    )
    _regional(coded, live)


def _okrsok_number(obec: str, okrsok: str) -> str:
    """Return the number of okrsok *okrsok* of *obec*, named ``<obec> <number>``."""
    name, _, number = okrsok.rpartition(" ")
    if name != obec or not number.isdigit():
        raise StatOfficeError(f"okrsok {okrsok!r} not of {obec!r}")
    return number
