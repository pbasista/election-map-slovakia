"""ŠÚ SR's definitive packages of the elections of 29 October 2022.

ŠÚ SR published the municipal (OSO) and regional (OSK) elections of 2022
as zips of ``|``-separated UTF-8 tables with coded column names, one row
per candidate, obvod or okrsok, described by each zip's ``tab_info.csv``
(:func:`open_package` reads them). This module turns them into what the
pipeline takes from other sources for 2026:

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

from election_map_slovakia import candidates, progress, results
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
    """A 2022 package cannot be read."""


# The packages.


@dataclass(frozen=True)
class Package:
    """The tables of one 2022 package (:data:`_TABLES`)."""

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
                if kind in candidates.MUNICIPAL:
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
    return out


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
    others = None if kind in results.SINGLE_CHOICE else 0
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
        kind, _, area = contest.partition(":")
        area = area.partition("/")[0]
        path = results.live_path({"kind": kind, "area": area}, okres_of)
        live.add(path, contest, record)
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
            path = results.live_path({"kind": kind, "area": kraj}, {})
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
