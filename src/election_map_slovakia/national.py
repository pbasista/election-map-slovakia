"""Results of the country-wide elections: ŠÚ SR's national tables, and fakes.

The presidential election (each round), a referendum and the elections to
the National Council (NR SR) and the European Parliament have one contest
kind each (:mod:`election_map_slovakia.contests`): ``prezident:SK/<round>``,
``referendum:SK/<question>``, the party contest ``nrsr:SK`` (``ep:SK``) and a
list contest ``nrsr:SK/<party>`` per party. Their results are the same files
as the municipal and regional elections' (:mod:`election_map_slovakia.results`,
docs/results.md): ``country.json`` with the contests of the whole country,
``list/<party>.json`` with a party's list, and the okrsok files by kraj,
``okrsky/country/<kraj>.json`` and ``okrsky/list/<party>/<kraj>.json``.

:func:`read_final` reads ŠÚ SR's tables of such an election (format
``volbysr``; CSV or XLSX, one zip or many files, read by
:mod:`election_map_slovakia.tables`), each level from its own table:

==============  =======  =====  ==================================
level           turnout  votes  preference votes (party lists)
==============  =======  =====  ==================================
whole country   tab01    tab03a tab07a
obec            tab02d   tab03e tab07e (where the package has it)
okrsok          tab02e   tab03f tab07f (where the package has it)
==============  =======  =====  ==================================

A presidential election has a package per round, in order. A party's seats
are those of ``tab03a`` (``Počet získaných mandátov``) or else ``tab04``
(``Pridelené mandáty spolu``); its elected those whose place on the list
after the preference votes (``tab07a``, ``Poradie po zohľadnení prednostného
hlasovania``) is within its seats, or else those of ``tab06``. ŠÚ SR words
a column differently from one election and table to the next: each is
named by its aliases (the ``_`` tuples below), and one missing fails naming
the table, the columns wanted and the columns found.

Records (``[number, votes, flag]`` candidates as everywhere):

- ``prezident:SK/n``: flag 1 elected, :data:`results.ADVANCED` on to round 2
  (round 1 marks nobody elected: its two best), :data:`results.WITHDRAWN`;
- ``referendum:SK/q``: the answers ``[1, yes]`` and ``[2, no]``, ``valid``
  their sum; flag 1 on the answer that won a valid referendum (more than
  half the eligible took part, and it has more than half the valid votes);
- party contest: a party's votes, flag 1 where it won seats, ``won`` its
  seats, ``seats`` the body's;
- list contest: a person's preference votes by position, flag 1 elected,
  0 a substitute of a list that won seats, else null; ``valid`` the party's
  votes, ``seats`` its seats, ``areas`` (from ``tab07e``) and okrsky (from
  ``tab07f``) the party's votes in an obec or okrsok as its ``valid``.

Every contest has ``areas`` per obec and okrsky; a list where the package
has its tables. :func:`fake` makes plausible dummy results of every stage
for testing the app.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from election_map_slovakia import contests as kinds, progress, results, tables
from election_map_slovakia.results import (
    ADVANCED,
    STAGES,
    WITHDRAWN,
    Area,
    Ballot,
    Contest,
    Live,
    Record,
    Reference,
    ResultsError,
    apportion,
    deal,
    fake_okrsky,
    okrsok_file,
    okrsok_key,
    rng,
    source,
)

COUNTRY = "country"
"""The area file of a country-wide contest (:func:`contests.area_name`)."""
_TURNOUT = {"country": "tab01", "obec": "tab02d", "okrsok": "tab02e"}
_VOTE_TABLES = {"country": "tab03a", "obec": "tab03e", "okrsok": "tab03f"}
_PREFERENCE_TABLES = {"country": "tab07a", "obec": "tab07e", "okrsok": "tab07f"}
_SEATS_TABLE = "tab04"
_ELECTED_TABLE = "tab06"
# Column aliases, as seen in the packages of 2019, 2020, 2023 and 2024. In
# 2019 the obec and okrsok tables count the voters who took part as the
# envelopes issued to them, and those of the EP election their valid votes
# as "Počet platných hlasov" (elsewhere a party's).
_ELIGIBLE = ("Počet zapísaných voličov", "Počet voličov zapísaných v zoznamoch voličov")
_VOTERS = (
    "Počet zúčastnených voličov",
    "Počet voličov, ktorí sa zúčastnili na hlasovaní",
    "Počet vydaných obálok",
)
_VALID = (
    "Počet platných hlasov spolu",
    "Počet platných hlasov pre všetkých kandidátov",
    "Počet platných hlasov odovzdaných pre všetkých kandidátov",
    "Počet platných hlasov všetkých kandidátov",
    "Počet platných hlasovacích lístkov",
    "Počet platných hlasov",
)
_OKRSKY = ("Počet volebných okrskov",)
_CONFIRMED = (
    "Počet potvrdených okrskových zápisníc",
    "Počet odovzdaných zápisníc okrskových volebných komisií",
)
_KRAJ = ("Kód kraja",)
_OBEC = ("Kód obce",)
_OKRSOK = ("Okrsok",)
_NUMBER = ("Číslo politického subjektu", "Poradie na hlasovacom lístku")
"""A party's or a presidential candidate's ballot number."""
_SUBJECT = ("Číslo politického subjektu",)
_POSITION = ("Poradie na hlasovacom lístku", "Poradie na kandidátnej listine")
"""A person's position on a party's list."""
_VOTES = ("Počet platných hlasov",)
_NOTE = ("Poznámka", "Kandidát")
_PREFERENCES = ("Počet platných prednostných hlasov",)
_SEATS = ("Počet získaných mandátov",)
"""A party's seats in ``tab03a``: empty where it won none."""
_ALLOTTED = ("Pridelené mandáty spolu",)
_RANK = ("Poradie po zohľadnení prednostného hlasovania",)
"""A person's place on the list after the preference votes (``tab07a``):
empty on a list that won no seats."""
_CANDIDATE_COLUMN = re.compile(r"(\d+)\. ")
"""A person's column of a wide preference table: position, name."""
_SUBJECT_SHEET = re.compile(r"_PS(\d+)$")
"""The worksheet of one ballot subject's wide preference table."""
_YES = ('Počet hlasov "ÁNO"',)
_NO = ('Počet hlasov "NIE"',)
_QUESTION = ("Číslo otázky",)
_ELECTED_LABEL = "zvolen"
_WITHDRAWN_LABEL = "x"
_ADVANCED_LABEL = "postup"
_ADVANCED_MARK = "p"
"""How the tables of 2024 mark those on to round 2 (2019: ``postupujúci``)."""
_YES_ANSWER, _NO_ANSWER = 1, 2
_ABROAD = "599999"
"""The obec code of the votes from abroad in a referendum's tables (:func:`_rows`)."""
_FINALISTS = 2
"""Candidates who go on to round 2 of a presidential election."""

_Key = tuple[str, ...]
"""A unit of a level: ``()`` the country, ``(obec,)``, ``(obec, okrsok)``."""


@dataclass
class _Tally:
    """A contest's figures at every level of a package."""

    whole: Area
    counted: tuple[int, int]
    obce: dict[str, Area]
    okrsky: dict[str, dict[str, Area]]
    """Kraj → :func:`results.okrsok_key` → figures."""
    labels: dict[int, str] = field(default_factory=dict)
    """Ballot number → ŠÚ SR's note on the candidate (whole country)."""


def read_final(
    paths: Sequence[Path], ref: Reference, log: results.Log = progress.note
) -> tuple[Live, list[str]]:
    """Return the results of national tables *paths*, and the sources they fill.

    *ref* has the election's contests: a presidential election's *paths*
    are a package per round, in order; any other's make one package. *log*
    is told what the tables leave out.
    """
    found = {kinds.parse(c).kind for c in ref.contests}
    if len(found) != 1:
        raise ResultsError(
            f"not the contests of one national election: {sorted(k.name for k in found)}"
        )
    kind = found.pop()
    live = Live("final")
    try:
        if kind.sub == "round":
            done = [
                _presidential(tables.open_package([p], results.TIMEZONE), ref, n, live)
                for n, p in enumerate(paths, 1)
            ]
        elif kind.sub == "question":
            done = [_referendum(tables.open_package(paths, results.TIMEZONE), live)]
        else:
            package = tables.open_package(paths, results.TIMEZONE)
            done = [_party_lists(package, ref, kind.name, live, log)]
    except tables.TableError as e:
        raise ResultsError(str(e)) from e
    return live, done


def _count(row: Mapping[str, str], column: str, table: tables.Table) -> int:
    """Return the count in *column* of *row*; fail where there is none."""
    text = row[column]
    # Most cells are plain integers, which results.number reads alike.
    try:
        return int(text)
    except ValueError:
        value = results.number(text)
    if value is None:
        raise tables.TableError(f"{table.name}: {column} {text!r} is no count")
    return value


def _keyer(t: tables.Table, level: str) -> Callable[[Mapping[str, str]], _Key]:
    """Return the unit key of a row of table *t* of *level*."""
    if level == COUNTRY:
        return lambda _: ()
    obec = t.column(*_OBEC)
    if level == "obec":
        return lambda r: (r[obec],)
    okrsok = t.column(*_OKRSOK)
    return lambda r: (r[obec], str(_count(r, okrsok, t)))


def _rows(t: tables.Table, level: str) -> list[dict[str, str]]:
    """Return the rows of table *t* of *level* of an obec of Slovakia.

    A referendum's tables of 2023 and 2026 count the votes sent from abroad
    as obec :data:`_ABROAD` ("Cudzina", kraj 9), with no voters on the roll;
    the country's figures (``tab01``, ``tab03a``) include them, and no map
    or place has them.
    """
    if level == COUNTRY:
        return t.rows
    obec = t.column(*_OBEC)
    return [r for r in t.rows if r[obec] != _ABROAD]


def _question_of(t: tables.Table) -> Callable[[Mapping[str, str]], int]:
    """Return the question of a row of a referendum's table *t*: 1 if it has none."""
    column = t.optional(*_QUESTION)
    if column is None:
        return lambda _: 1
    return lambda r: _count(r, column, t)


def _turnout(
    package: tables.Package, level: str, *, valid: bool = True
) -> tuple[dict[_Key, tuple[int, int, int | None]], tables.Table]:
    """Return unit → eligible, voters and (if *valid*) valid votes, and the table."""
    t = package.table(_TURNOUT[level])
    key = _keyer(t, level)
    eligible, voters = t.column(*_ELIGIBLE), t.column(*_VOTERS)
    total = t.column(*_VALID) if valid else None
    out = {
        key(r): (
            _count(r, eligible, t),
            _count(r, voters, t),
            None if total is None else _count(r, total, t),
        )
        for r in _rows(t, level)
    }
    return out, t


def _counted(package: tables.Package) -> tuple[int, int]:
    """Return the okrsky counted of all, of the whole country's turnout table."""
    t = package.table(_TURNOUT[COUNTRY])
    if len(t.rows) != 1:
        raise tables.TableError(f"{t.name}: {len(t.rows)} rows, not the country's one")
    row = t.rows[0]
    okrsky = _count(row, t.column(*_OKRSKY), t)
    confirmed = t.optional(*_CONFIRMED)
    return (okrsky if confirmed is None else _count(row, confirmed, t), okrsky)


def _kraje(package: tables.Package, ref: Reference) -> dict[str, str]:
    """Return the kraj of each obec of the okrsok turnout table.

    By the table's kraj code where it has one, else by the candidate lists'
    obce.
    """
    t = package.table(_TURNOUT["okrsok"])
    obec, kraj = t.column(*_OBEC), t.optional(*_KRAJ)
    out = {}
    for r in _rows(t, "okrsok"):
        code = r[obec]
        if kraj is not None:
            out[code] = str(_count(r, kraj, t))
        elif code in ref.places:
            out[code] = ref.places[code].kraj
        else:
            raise tables.TableError(
                f"{t.name}: obec {code} of no kraj (no column {_KRAJ[0]!r})"
            )
    return out


def _votes(
    package: tables.Package, level: str, number: tuple[str, ...] = _NUMBER
) -> tuple[dict[_Key, dict[int, int]], tables.Table]:
    """Return unit → ballot number → votes of the vote table of *level*."""
    t = package.table(_VOTE_TABLES[level])
    key = _keyer(t, level)
    n, votes = t.column(*number), t.column(*_VOTES)
    out: dict[_Key, dict[int, int]] = defaultdict(dict)
    for r in _rows(t, level):
        out[key(r)][_count(r, n, t)] = _count(r, votes, t)
    return out, t


def _tally(package: tables.Package, ref: Reference) -> _Tally:
    """Return the figures of a package of one contest of candidates (or parties)."""
    whole, _ = _turnout(package, COUNTRY)
    votes, t = _votes(package, COUNTRY)
    note = t.optional(*_NOTE)
    labels = {}
    if note is not None:
        n = t.column(*_NUMBER)
        labels = {_count(r, n, t): r[note] for r in t.rows}
    e, v, valid = whole[()]
    obce, _ = _turnout(package, "obec")
    obec_votes, _ = _votes(package, "obec")
    okrsky, _ = _turnout(package, "okrsok")
    okrsok_votes, _ = _votes(package, "okrsok")
    kraj_of = _kraje(package, ref)
    by_kraj: dict[str, dict[str, Area]] = defaultdict(dict)
    for key, (oe, ov, ob) in okrsky.items():
        by_kraj[kraj_of[key[0]]][okrsok_key(*key)] = (
            oe,
            ov,
            ob,
            okrsok_votes.get(key, {}),
        )
    return _Tally(
        (e, v, valid, votes.get((), {})),
        _counted(package),
        {k[0]: (oe, ov, ob, obec_votes.get(k, {})) for k, (oe, ov, ob) in obce.items()},
        dict(by_kraj),
        labels,
    )


def _add(live: Live, contest: str, record: Record, okrsky: Mapping[str, dict]) -> None:
    """Put a country-wide *contest* and its okrsky by kraj into *live*."""
    live.add(COUNTRY, contest, record)
    for kraj, areas in sorted(okrsky.items()):
        if areas:
            live.add_okrsky(okrsok_file(COUNTRY, kraj), contest, areas)


def _time(package: tables.Package) -> str | None:
    return package.time.isoformat() if package.time else None


def _presidential(
    package: tables.Package, ref: Reference, round_: int, live: Live
) -> str:
    """Add round *round_* of a presidential election to *live*; return its source."""
    contest = f"prezident:{kinds.COUNTRY}/{round_}"
    if contest not in ref.contests:
        raise ResultsError(
            f"results of round {round_} of a presidential election whose"
            " candidate lists have no such round"
        )
    tally = _tally(package, ref)
    ballots = _round_flags(tally.whole[3], tally.labels, round_)
    e, v, valid, _ = tally.whole
    record = Record(
        "final",
        tally.counted,
        e,
        v,
        valid,
        1,
        sum(1 for b in ballots if b[2] == 1),
        ballots,
        tally.obce,
    )
    _add(live, contest, record, tally.okrsky)
    name = kinds.source_of(contest)
    live.source[name] = source(_time(package), tally.counted, "okrsky")
    return name


def _round_flags(
    votes: Mapping[int, int], labels: Mapping[int, str], round_: int
) -> list[Ballot]:
    """Return a round's candidates flagged by ŠÚ SR's notes, else by the votes.

    ``zvolený`` elected, ``X`` withdrew, a note starting ``postup`` or just
    ``P`` on to round 2. Where the notes mark no one: round 1's two best (not
    withdrawn) go on to round 2, round 2's best is elected.
    """
    flags: dict[int, int | None] = {}
    for n in votes:
        label = labels.get(n, "").strip().casefold()
        flags[n] = (
            WITHDRAWN
            if label == _WITHDRAWN_LABEL
            else 1
            if label.startswith(_ELECTED_LABEL)
            else ADVANCED
            if label.startswith(_ADVANCED_LABEL) or label == _ADVANCED_MARK
            else None
        )
    if not any(f in (1, ADVANCED) for f in flags.values()):
        order = sorted(
            (n for n in votes if flags[n] != WITHDRAWN), key=lambda n: (-votes[n], n)
        )
        if round_ == 1:
            flags |= dict.fromkeys(order[:_FINALISTS], ADVANCED)
        else:
            flags |= dict.fromkeys(order[:1], 1)
    return [(n, x, flags[n]) for n, x in sorted(votes.items())]


def _answer_table(package: tables.Package, level: str) -> tables.Table:
    """Return the table of a referendum's answers at *level*.

    The votes table where the package has it with the answers, else the
    turnout table.
    """
    if package.has(_VOTE_TABLES[level]):
        t = package.table(_VOTE_TABLES[level])
        if t.optional(*_YES):
            return t
    return package.table(_TURNOUT[level])


def _answers(
    package: tables.Package, level: str
) -> dict[int, dict[_Key, tuple[int | None, int | None, int, int]]]:
    """Return question → unit → eligible, voters, yes and no at *level*.

    Eligible and voters from the turnout table, of the question where it
    has them per question.
    """
    t = _answer_table(package, level)
    key, question = _keyer(t, level), _question_of(t)
    yes, no = t.column(*_YES), t.column(*_NO)
    turnout_table = package.table(_TURNOUT[level])
    turnout_key = _keyer(turnout_table, level)
    turnout_question = (
        _question_of(turnout_table)
        if turnout_table.optional(*_QUESTION)
        else (lambda _: 0)
    )
    eligible = turnout_table.column(*_ELIGIBLE)
    voters = turnout_table.column(*_VOTERS)
    turnout = {
        (turnout_key(r), turnout_question(r)): (
            _count(r, eligible, turnout_table),
            _count(r, voters, turnout_table),
        )
        for r in _rows(turnout_table, level)
    }
    per_question = turnout_table.optional(*_QUESTION) is not None
    out: dict[int, dict[_Key, tuple[int | None, int | None, int, int]]] = defaultdict(
        dict
    )
    for r in _rows(t, level):
        k, q = key(r), question(r)
        e, v = turnout.get((k, q if per_question else 0), (None, None))
        out[q][k] = (e, v, _count(r, yes, t), _count(r, no, t))
    return out


def _answer_area(figures: tuple[int | None, int | None, int, int]) -> Area:
    e, v, yes, no = figures
    return (e, v, yes + no, {_YES_ANSWER: yes, _NO_ANSWER: no})


def _referendum(package: tables.Package, live: Live) -> str:
    """Add a referendum's questions to *live*; return its source."""
    counted = _counted(package)
    whole = _answers(package, COUNTRY)
    obce = _answers(package, "obec")
    okrsky = _answers(package, "okrsok")
    kraj_of = _kraje_of_answers(package)
    for q, units in sorted(whole.items()):
        e, v, valid, votes = _answer_area(units[()])
        record = Record(
            "final",
            counted,
            e,
            v,
            valid,
            1,
            None,
            [(n, x, None) for n, x in sorted(votes.items())],
            {k[0]: _answer_area(f) for k, f in obce.get(q, {}).items()},
        )
        won = _winning_answer(e, v, votes)
        if won is not None:
            record.candidates = [
                (n, x, 1 if n == won else None) for n, x, _ in record.candidates
            ]
            record.filled = 1
        by_kraj: dict[str, dict[str, Area]] = defaultdict(dict)
        for key, figures in okrsky.get(q, {}).items():
            by_kraj[kraj_of[key[0]]][okrsok_key(*key)] = _answer_area(figures)
        _add(live, f"referendum:{kinds.COUNTRY}/{q}", record, by_kraj)
    name = kinds.KINDS["referendum"].source
    live.source[name] = source(_time(package), counted, "okrsky")
    return name


def _kraje_of_answers(package: tables.Package) -> dict[str, str]:
    """Return the kraj of each obec of a referendum's okrsok tables."""
    for t in (_answer_table(package, "okrsok"), package.table(_TURNOUT["okrsok"])):
        obec, kraj = t.column(*_OBEC), t.optional(*_KRAJ)
        if kraj is not None:
            return {r[obec]: str(_count(r, kraj, t)) for r in _rows(t, "okrsok")}
    raise tables.TableError(f"{_TURNOUT['okrsok']}: no column {_KRAJ[0]!r}")


def _winning_answer(
    eligible: int | None, voters: int | None, votes: Mapping[int, int]
) -> int | None:
    """Return the answer that won a valid referendum, or None.

    Valid where more than half the eligible took part; an answer wins with
    more than half the valid votes.
    """
    if eligible is None or voters is None or 2 * voters <= eligible:
        return None
    valid = sum(votes.values())
    return next((n for n, x in sorted(votes.items()) if 2 * x > valid), None)


def _party_lists(
    package: tables.Package, ref: Reference, kind: str, live: Live, log: results.Log
) -> str:
    """Add a party-list election's party and list contests to *live*."""
    party = f"{kind}:{kinds.COUNTRY}"
    known = ref.contests.get(party)
    tally = _tally(package, ref)
    seats = _party_seats(package)
    won = {n: s for n, s in sorted(seats.items()) if s}
    e, v, valid, votes = tally.whole
    record = Record(
        "final",
        tally.counted,
        e,
        v,
        valid,
        known.seats if known and known.seats else sum(won.values()),
        sum(won.values()),
        [(n, x, 1 if n in won else None) for n, x in sorted(votes.items())],
        tally.obce,
        won,
    )
    _add(live, party, record, tally.okrsky)
    list_areas = _list_areas(package, "obec", tally.obce)
    okrsky = {k: a for areas in tally.okrsky.values() for k, a in areas.items()}
    kraj_of = {k: kraj for kraj, areas in tally.okrsky.items() for k in areas}
    list_okrsky = _list_areas(package, "okrsok", okrsky)
    for p, ballots in sorted(_list_ballots(package, won).items()):
        contest = f"{party}/{p}"
        if p not in votes:
            log(f"{contest}: preference votes of a party without votes; left out")
            continue
        path = kinds.area_name(contest, {})
        live.add(
            path,
            contest,
            Record(
                "final",
                tally.counted,
                e,
                v,
                votes[p],
                won.get(p, 0),
                sum(1 for b in ballots if b[2] == 1),
                ballots,
                list_areas.get(p),
            ),
        )
        by_kraj: dict[str, dict[str, Area]] = defaultdict(dict)
        for key, area in list_okrsky.get(p, {}).items():
            by_kraj[kraj_of[key]][key] = area
        for kraj, areas in sorted(by_kraj.items()):
            live.add_okrsky(okrsok_file(path, kraj), contest, areas)
    name = kinds.KINDS[kind].source
    live.source[name] = source(_time(package), tally.counted, "okrsky")
    return name


def _party_seats(package: tables.Package) -> dict[int, int]:
    """Return each party's seats: of ``tab03a``, else of ``tab04``."""
    t = package.table(_VOTE_TABLES[COUNTRY])
    column = t.optional(*_SEATS)
    if column is None and package.has(_SEATS_TABLE):
        t = package.table(_SEATS_TABLE)
        column = t.column(*_ALLOTTED)
        n = t.column(*_SUBJECT)
    else:
        column = t.column(*_SEATS)
        n = t.column(*_NUMBER)
    return {_count(r, n, t): _count(r, column, t) if r[column] else 0 for r in t.rows}


def _list_ballots(
    package: tables.Package, won: Mapping[int, int]
) -> dict[int, list[Ballot]]:
    """Return party → its persons: position, preference votes, flag.

    Elected (1) are those whose place after the preference votes is within
    the party's seats (``tab07a``), else those of ``tab06``; the others of a
    list that won seats are substitutes (0), of any other list null.
    """
    t = package.table(_PREFERENCE_TABLES[COUNTRY])
    subject, position = t.column(*_SUBJECT), t.column(*_POSITION)
    prefs = t.column(*_PREFERENCES)
    rank = t.optional(*_RANK)
    if rank is None and package.has(_ELECTED_TABLE):
        t6 = package.table(_ELECTED_TABLE)
        s6, p6 = t6.column(*_SUBJECT), t6.column(*_POSITION)
        elected = {(_count(r, s6, t6), _count(r, p6, t6)) for r in t6.rows}
    else:
        rank = t.column(*_RANK)
        elected = {
            (s, _count(r, position, t))
            for r in t.rows
            if r[rank] and _count(r, rank, t) <= won.get(s := _count(r, subject, t), 0)
        }
    out: dict[int, list[Ballot]] = defaultdict(list)
    for r in t.rows:
        p, n = _count(r, subject, t), _count(r, position, t)
        flag = (1 if (p, n) in elected else 0) if won.get(p) else None
        out[p].append((n, _count(r, prefs, t), flag))
    return dict(out)


def _list_areas(
    package: tables.Package, level: str, units: Mapping[str, Area]
) -> dict[int, dict[str, Area]]:
    """Return party → its list per unit of *level*, none where the package lacks its table.

    Per obec from ``tab07e``, per okrsok from ``tab07f``; *units* are the
    party contest's figures there, keyed as its ``areas`` (obec code) or
    okrsky (:func:`results.okrsok_key`). A unit's list has the unit's
    eligible and voters, the party's votes there as the valid ones, and the
    positions' preference votes; an okrsok's only those not 0 (seven in
    eight of NR SR 2023's 12 million rows are 0). Every unit has the list
    where the table has the party's rows of it, or where the party has no
    votes (so none to give): the wide table has no row there. One where the
    party has votes but the table no rows is left out, its preference votes
    not known.

    The table is long, a row per unit and person (subject, position,
    votes), or (NR SR 2020, XLSX) wide: a worksheet per subject (``…_PS<n>``)
    of a row per unit where the subject has votes and a column per person
    (``1. Jozef Sásik``). Read row by row: NR SR 2023's are 0.8 and 1.8 GB.
    """
    table = _PREFERENCE_TABLES[level]
    if not package.has(table):
        return {}
    sparse = level == "okrsok"
    out: dict[int, dict[str, dict[int, int]]] = defaultdict(dict)
    for s in package.stream(table):
        columns, key = _unit_of(s, level)
        if s.optional(*_SUBJECT) is None:
            _wide_preferences(s, columns, key, units, out, sparse=sparse)
            continue
        subject, position = s.index(*_SUBJECT), s.index(*_POSITION)
        prefs = s.index(*_PREFERENCES)
        for cells in s.cells(*columns, subject, position, prefs):
            k = key(cells)
            if k in units:
                person = out[_figure(cells[-3], s)].setdefault(k, {})
                votes = _figure(cells[-1], s)
                if votes or not sparse:
                    person[_figure(cells[-2], s)] = votes
    return {party: _unit_lists(party, by_unit, units) for party, by_unit in out.items()}


def _unit_lists(
    party: int, by_unit: Mapping[str, dict[int, int]], units: Mapping[str, Area]
) -> dict[str, Area]:
    """Return *party*'s list per unit of *units*, of its preference votes *by_unit*.

    The units where the table has its rows, or where it has no votes.
    """
    out = {}
    for k, (e, v, _, votes) in sorted(units.items()):
        mine = votes.get(party, 0)
        if k in by_unit or not mine:
            out[k] = (e, v, mine, by_unit.get(k, {}))
    return out


def _unit_of(
    s: tables.Stream, level: str
) -> tuple[list[int], Callable[[Sequence[str]], str]]:
    """Return the columns of a streamed table's unit at *level*, and its key of their cells."""
    obec = s.index(*_OBEC)
    if level == "obec":
        return [obec], lambda cells: cells[0]
    return [obec, s.index(*_OKRSOK)], lambda cells: okrsok_key(
        cells[0], _figure(cells[1], s)
    )


def _wide_preferences(
    s: tables.Stream,
    columns: Sequence[int],
    key: Callable[[Sequence[str]], str],
    units: Mapping[str, Area],
    out: dict[int, dict[str, dict[int, int]]],
    *,
    sparse: bool,
) -> None:
    """Add a subject's worksheet of a wide preference table to *out*.

    Its unit in *columns*, keyed by *key*; with *sparse*, without the 0s.
    """
    m = _SUBJECT_SHEET.search(s.sheet)
    if m is None:
        raise tables.TableError(
            f"{s.name}: no column {_SUBJECT[0]!r}, and not the sheet of a subject"
        )
    persons = [
        (i, int(p.group(1)))
        for i, column in enumerate(s.header)
        if (p := _CANDIDATE_COLUMN.match(column))
    ]
    by_unit = out[int(m.group(1))]
    for r in s.rows():
        k = key([r[i] for i in columns])
        if k in units:
            by_unit[k] = {
                n: x for i, n in persons if (x := _figure(r[i], s)) or not sparse
            }


def _figure(text: str, s: tables.Stream) -> int:
    """Return the count *text* of a streamed table *s*; fail where it is none."""
    try:
        return int(text)
    except ValueError:
        value = results.number(text)
    if value is None:
        raise tables.TableError(f"{s.name}: {text!r} is no count")
    return value


# Dummy results.

_POLLS_CLOSE = dt.time(22)
"""When the polls of a national election close: its counting starts."""
_VOTERS_PER_OKRSOK = 800
_DEFAULT_ELIGIBLE = 1500
"""Registered voters of a fake obec whose past election is not known."""
_TURNOUT_OF = {"prezident": (0.45, 0.55), "nrsr": (0.6, 0.7), "ep": (0.25, 0.35)}
"""Fake turnout per kind of contest: the range of the country's."""
_REFERENDUM_TURNOUT = ((0.55, 0.62), (0.3, 0.42))
"""Fake turnout of a referendum's questions but the last, and of the last:
the last question fails its quorum (half the eligible) even where every obec
turns out the most its noise allows (+15 %)."""
_VALID_SHARE = (0.97, 0.995)
_FINALIST_WEIGHT = (1.0, 0.9)
"""Popularity in round 1 of round 2's two candidates."""
_OTHERS_WEIGHT = 0.45
"""The most popularity in round 1 of a candidate not in round 2."""
_PREFERENCE_MARKS = 0.6
"""Share of the marks a party's voters could make that they make."""
_STAR_BOOST = 6.0
"""Popularity of a list's star (a person far down the list), relative."""
_YES_RANGE = (0.3, 0.8)


@dataclass(frozen=True)
class _Obec:
    code: str
    kraj: str
    eligible: int
    okrsky: int
    rank: float
    """The obec is counted once the stage's share passes it."""


class _NationalFake:
    """The figures behind :func:`fake`, the same at every stage."""

    def __init__(self, ref: Reference, seed: int, okrsky: Mapping[str, int]) -> None:
        self.ref = ref
        self.seed = seed
        self.okrsky = okrsky
        self.obce = []
        for p in sorted(ref.places.values(), key=lambda p: p.code):
            if not p.code.isdigit():
                continue
            r = rng(seed, "obec", p.code)
            base = p.past[0] if p.past else _DEFAULT_ELIGIBLE
            eligible = max(1, round(base * r.uniform(0.97, 1.01)))
            count = okrsky.get(p.code) or max(1, round(eligible / _VOTERS_PER_OKRSOK))
            self.obce.append(_Obec(p.code, p.kraj, eligible, count, r.random()))

    def counted(self, share: float) -> list[_Obec]:
        """Return the obce counted at *share*."""
        return [o for o in self.obce if share >= 1 or o.rank < share]

    def turnout(
        self, contest: str, o: _Obec, span: tuple[float, float]
    ) -> tuple[int, int, int]:
        """Return an obec's eligible, voters and valid votes in *contest*."""
        r = rng(self.seed, "turnout", contest, o.code)
        level = rng(self.seed, "turnout", contest).uniform(*span)
        voters = min(o.eligible, round(o.eligible * level * r.uniform(0.85, 1.15)))
        return (o.eligible, voters, round(voters * r.uniform(*_VALID_SHARE)))

    def votes(
        self, contest: str, o: _Obec, valid: int, weights: Mapping[int, float]
    ) -> dict[int, int]:
        """Return the votes of *valid* ballots of an obec by *weights*, noisy."""
        r = rng(self.seed, "votes", contest, o.code)
        noisy = [w * r.uniform(0.7, 1.3) for w in weights.values()]
        return dict(zip(weights, apportion(valid, noisy), strict=True))

    def numbers(self, contest: str) -> list[int]:
        return sorted(c.number for c in self.ref.candidates.get(contest, ()))

    def single(
        self,
        contest: str,
        span: tuple[float, float],
        weights: Mapping[int, float],
        share: float,
    ) -> Record:
        """Return a single-choice contest counted at *share*, its obce as areas.

        Final at a share of 1; the flags are its caller's.
        """
        areas = {}
        for o in self.counted(share):
            e, v, valid = self.turnout(contest, o, span)
            areas[o.code] = (e, v, valid, self.votes(contest, o, valid, weights))
        return self.record(contest, areas, share)

    def record(self, contest: str, areas: dict[str, Area], share: float) -> Record:
        """Return a contest of obce *areas* at *share*: totals and progress."""
        total = results.sum_areas(areas.values())
        counted = [o for o in self.obce if o.code in areas]
        return Record(
            "final" if share >= 1 else "partial",
            (sum(o.okrsky for o in counted), sum(o.okrsky for o in self.obce)),
            total[0],
            total[1],
            total[2],
            1,
            None,
            [(n, x, None) for n, x in sorted(total[3].items())],
            areas,
        )

    def okrsky_of(self, contest: str, record: Record) -> _Okrsky:
        """Return kraj → okrsky of *contest*, those of obce given okrsky.

        None before it is final.
        """
        if record.status != "final":
            return {}
        kraj = {o.code: o.kraj for o in self.obce}
        out: dict[str, dict[str, Area]] = defaultdict(dict)
        for code, area in sorted((record.areas or {}).items()):
            count = self.okrsky.get(code)
            if count:
                out[kraj[code]] |= fake_okrsky(
                    self.seed, contest, code, area, range(1, count + 1)
                )
        return dict(out)

    def weights(self, contest: str, numbers: Iterable[int]) -> dict[int, float]:
        r = rng(self.seed, "weights", contest)
        return {n: r.expovariate(1) ** 2 + 0.01 for n in numbers}


def _shift(time: str, day: dt.date) -> str:
    """Return a stage's *time* moved to the counting night of a national *day*.

    The stages are times of the municipal night, whose counting starts at
    the ``none`` stage; a national one starts when its polls close.
    """
    start = dt.datetime.fromisoformat(STAGES["none"].time)
    close = dt.datetime.combine(day, _POLLS_CLOSE, results.TIMEZONE)
    return (close + (dt.datetime.fromisoformat(time) - start)).isoformat()


def fake(
    ref: Reference,
    stage: str,
    day: dt.date,
    seed: int = 0,
    okrsky: Mapping[str, int] | None = None,
) -> Live:
    """Return dummy results of a national election at *stage* (:data:`results.STAGES`).

    The obce are counted in a stable random order, as far as the stage's
    regional share; turnout follows an obec's past election where known.
    ``final`` has every contest final, with ``areas`` per obec and the
    okrsky of the obce *okrsky* gives okrsky to (an election without units
    has none). A presidential election's round 2 is counted on a night of
    its own, round 1 being final by then; round 1 elects nobody and its two
    best are round 2's candidates where these are on its list. A referendum's
    last question fails its quorum. A party-list election's seats go by
    the largest remainder to the parties over their threshold; preference
    votes lean to the top of each list and to a star further down, okrsok
    by okrsok of the party's votes there where there are okrsky, and a
    party's seats go to those over the quota first, then in list order.
    *day* is the election's: the source times are of its night.
    """
    s = STAGES[stage]
    model = _NationalFake(ref, seed, okrsky or {})
    live = Live("none")
    found = {kinds.parse(c).kind for c in ref.contests}
    sources = results.sources_of(ref.contests)
    live.source = results.no_sources(sources)
    if stage == "none":
        return live
    share = s.regional
    if any(k.sub == "round" for k in found):
        made = _fake_presidential(model, ref, share, day, s.time)
    elif any(k.sub == "question" for k in found):
        made = _fake_referendum(model, ref, share, day, s.time)
    else:
        made = _fake_party_lists(model, ref, share, day, s.time)
    for name, entry, contests in made:
        live.source[name] = entry
        for contest, record, by_kraj in contests:
            path = kinds.area_name(contest, {})
            live.add(path, contest, record)
            for kraj, areas in sorted(by_kraj.items()):
                live.add_okrsky(okrsok_file(path, kraj), contest, areas)
    live.phase = "final" if stage == "final" else "partial"
    return live


_Okrsky = dict[str, dict[str, Area]]
"""A contest's okrsky by kraj (:meth:`_NationalFake.okrsky_of`)."""
_Made = Iterator[tuple[str, dict, list[tuple[str, Record, _Okrsky]]]]
"""Per source: its name, its ``status.json`` entry and its contests, each
with its okrsky."""


def _entry(model: _NationalFake, record: Record, time: str) -> dict:
    """Return the ``source`` entry of a contest's *record*: okrsky and voters."""
    counted = [o for o in model.obce if o.code in (record.areas or {})]
    return source(
        time,
        record.counted,
        "okrsky",
        (sum(o.eligible for o in counted), sum(o.eligible for o in model.obce)),
    )


def _fake_presidential(
    model: _NationalFake, ref: Reference, share: float, day: dt.date, time: str
) -> _Made:
    rounds = sorted(c for c in ref.contests if kinds.parse(c).kind.sub == "round")
    finalists = {
        x.name: i
        for c in rounds[1:]
        for i, x in enumerate(sorted(ref.candidates.get(c, ()), key=lambda x: x.number))
    }
    for contest in rounds:
        c = ref.contests[contest]
        round_ = c.obvod or 1
        numbers = model.numbers(contest)
        if not numbers:
            continue
        r = rng(model.seed, "weights", contest)
        names = {x.number: x.name for x in ref.candidates.get(contest, ())}
        weights = {
            n: _FINALIST_WEIGHT[finalists[names[n]]]
            if round_ == 1 and names[n] in finalists
            else r.uniform(0.05, _OTHERS_WEIGHT)
            for n in numbers
        }
        # Round 1 is over by the night of round 2.
        mine = 1 if round_ < len(rounds) else share
        record = model.single(contest, _TURNOUT_OF["prezident"], weights, mine)
        if record.status == "final":
            record.candidates = _round_flags(
                {n: x for n, x, _ in record.candidates}, {}, round_
            )
            record.filled = sum(1 for b in record.candidates if b[2] == 1)
        when = _shift(time, dt.date.fromisoformat(c.day) if c.day else day)
        made = [(contest, record, model.okrsky_of(contest, record))]
        yield kinds.source_of(contest), _entry(model, record, when), made


def _fake_referendum(
    model: _NationalFake, ref: Reference, share: float, day: dt.date, time: str
) -> _Made:
    questions = sorted(
        (c for c in ref.contests if kinds.parse(c).kind.sub == "question"),
        key=lambda c: ref.contests[c].obvod or 0,
    )
    made = []
    for i, contest in enumerate(questions):
        span = _REFERENDUM_TURNOUT[i == len(questions) - 1]
        yes = rng(model.seed, "yes", contest).uniform(*_YES_RANGE)
        weights = {_YES_ANSWER: yes, _NO_ANSWER: 1 - yes}
        record = model.single(contest, span, weights, share)
        if record.status == "final":
            won = _winning_answer(
                record.eligible, record.voters, {n: x for n, x, _ in record.candidates}
            )
            if won is not None:
                record.candidates = [
                    (n, x, 1 if n == won else None) for n, x, _ in record.candidates
                ]
                record.filled = 1
        made.append((contest, record, model.okrsky_of(contest, record)))
    if made:
        entry = _entry(model, made[0][1], _shift(time, day))
        yield kinds.KINDS["referendum"].source, entry, made


def _fake_party_lists(
    model: _NationalFake, ref: Reference, share: float, day: dt.date, time: str
) -> _Made:
    party = next(
        (
            c
            for c in ref.contests
            if kinds.parse(c).kind.party and not kinds.parse(c).is_list
        ),
        None,
    )
    if party is None:
        return
    c = ref.contests[party]
    kind = kinds.parse(party).kind.name
    subjects = {s.number: s for s in c.subjects}
    weights = model.weights(party, sorted(subjects))
    record = model.single(party, _TURNOUT_OF.get(kind, (0.5, 0.6)), weights, share)
    record.seats = c.seats
    if record.status == "final":
        votes = {n: x for n, x, _ in record.candidates}
        won = _largest_remainder(votes, subjects, c.seats or 0)
        record.won = {n: s for n, s in sorted(won.items()) if s}
        record.filled = sum(won.values())
        record.candidates = [
            (n, x, 1 if won.get(n) else None) for n, x in sorted(votes.items())
        ]
    okrsky = model.okrsky_of(party, record)
    made = [(party, record, okrsky)]
    for p in sorted(subjects):
        contest = f"{party}/{p}"
        if contest in ref.contests:
            made.append((contest, *_fake_list(model, c, contest, p, record, okrsky)))
    yield kinds.KINDS[kind].source, _entry(model, record, _shift(time, day)), made


def _largest_remainder(
    votes: Mapping[int, int], subjects: Mapping[int, results.Subject], seats: int
) -> dict[int, int]:
    """Return the seats of each party over its threshold, by the largest remainder.

    The parties' votes over the seats are the quota; each party gets its
    whole quotas, and the seats left go to the largest remainders. No party
    gets more seats than persons on its list: those go round the others in
    the same order.
    """
    valid = sum(votes.values())
    passed = {
        n: x
        for n, x in votes.items()
        if n in subjects and valid and 100 * x >= subjects[n].threshold * valid
    }
    total = sum(passed.values())
    if not total or not seats:
        return {}
    cap = {n: subjects[n].candidates or seats for n in passed}
    quotas = {n: x * seats / total for n, x in passed.items()}
    won = {n: min(int(q), cap[n]) for n, q in quotas.items()}
    order = sorted(quotas, key=lambda n: (-(quotas[n] - int(quotas[n])), n))
    left = seats - sum(won.values())
    while left and any(won[n] < cap[n] for n in order):
        for n in order:
            if left and won[n] < cap[n]:
                won[n] += 1
                left -= 1
    return won


def _fake_list(
    model: _NationalFake,
    c: Contest,
    contest: str,
    party: int,
    parent: Record,
    parent_okrsky: _Okrsky,
) -> tuple[Record, _Okrsky]:
    """Return party *party*'s list contest and its okrsky by kraj.

    By the party's votes in *parent*'s obce and okrsky (*parent_okrsky*):
    an obec with okrsky has its okrsky's preference votes summed, so that
    each okrsok keeps to the party's votes there. An okrsok's list has only
    the positions with votes, as the okrsky of ŠÚ SR's tables
    (:func:`_list_areas`).
    """
    positions = model.numbers(contest)
    marks = c.preferences or 1
    r = rng(model.seed, "list", contest)
    star = r.choice(positions) if positions else 0
    weights = [
        (_STAR_BOOST if n == star else 1.0) / n**0.8 * r.uniform(0.8, 1.2)
        for n in positions
    ]

    def dealt(mine: int) -> dict[int, int]:
        room = min(len(positions), marks) * mine
        given = round(room * _PREFERENCE_MARKS)
        cells = deal(given, weights, [mine] * len(positions)) if positions else []
        return dict(zip(positions, cells, strict=True))

    okrsky: _Okrsky = defaultdict(dict)
    by_obec: dict[str, list[Area]] = defaultdict(list)
    for kraj, units in sorted(parent_okrsky.items()):
        for key, (e, v, _, votes) in units.items():
            mine = votes.get(party, 0)
            prefs = {n: x for n, x in dealt(mine).items() if x}
            okrsky[kraj][key] = (e, v, mine, prefs)
            by_obec[key.partition("/")[0]].append(okrsky[kraj][key])
    areas: dict[str, Area] = {}
    for code, (e, v, _, votes) in (parent.areas or {}).items():
        if code in by_obec:
            summed = results.sum_areas(by_obec[code])
            areas[code] = (e, v, summed[2], {n: summed[3].get(n, 0) for n in positions})
        else:
            areas[code] = (e, v, votes.get(party, 0), dealt(votes.get(party, 0)))
    total = results.sum_areas(areas.values())
    seats = (parent.won or {}).get(party, 0)
    record = Record(
        parent.status,
        parent.counted,
        parent.eligible,
        parent.voters,
        total[2],
        None,
        None,
        [(n, total[3].get(n, 0), None) for n in positions],
        areas,
    )
    if parent.status == "final":
        record.seats = seats
        quota = (c.quota or 0) * (total[2] or 0) / 100
        prefs = total[3]
        ahead = sorted(
            (n for n in positions if prefs.get(n, 0) >= quota),
            key=lambda n: (-prefs.get(n, 0), n),
        )
        order = ahead + [n for n in positions if n not in ahead]
        elected = set(order[:seats])
        record.filled = len(elected)
        record.candidates = [
            (n, prefs.get(n, 0), (1 if n in elected else 0) if seats else None)
            for n in positions
        ]
    return record, dict(okrsky)
