"""Read an election's candidate lists in the format ``elections.toml`` names.

:func:`read` reads every format (``candidates``,
:data:`election_map_slovakia.config.CANDIDATE_FORMATS`) into
:class:`candidates.Lists`, for :func:`candidates.build`, and adds what the
election's configuration says of its contests. MV SR's lists of the
regular elections are :func:`candidates.read_lists`', ŠÚ SR's packages of
2022, 2018 and 2017 :func:`statoffice.read_lists`'; this module reads the
others:

- ``susr-by`` (:func:`read_by_election`): ŠÚ SR's package of a municipal
  by-election, XLSX tables of full Slovak column names below a title, as
  :mod:`election_map_slovakia.tables` reads them. Since 2023 (the term
  elected in 2022): ``tab0dd`` each obec where something was declared,
  with its seats and kind of election (also "Nekonajú sa", not held for
  want of candidates); ``tab0ad`` and ``tab0bd`` the mayor and council
  candidates, with codes of okres, obec and council obvod; ``tab0c`` the
  parties, whose short forms the lists name. A candidate's ``Politický
  subjekt`` is short forms separated by ``, `` (a short form may hold one),
  ``NEKA`` an independent. Seats are given per obec only, so a council
  contest has them where the obec's candidates stand in one obvod. An
  obec "Nekonajú sa" has its contests called uncontested
  (:func:`_by_election_not_held`).
  The packages of 2019–2022 (the term elected in 2018,
  :func:`election_map_slovakia.results.older_by_election`) are laid out
  otherwise: ``tab0c`` the obce, ``tab0b`` the parties, ``tab0a`` the
  mayor candidates without title, age or occupation, and of the councils
  only the elected (``tab06``: name and titles in one column,
  :func:`candidates.split_name`; numbered by the order elected in the
  obec), so their council contests are ``elected_only``. The election's
  ``candidates.toml``, where there is one, supplements such a package:
  each contest it has replaces the package's, whose candidates must be on it
  (:func:`_supplement`).
- ``volbysr`` (:func:`read_presidential`, :func:`read_party_lists`): ŠÚ SR's
  candidate tables of a country-wide election, CSV or XLSX: each round's
  ``tab0a`` of a presidential election (ballot number, name, title, age,
  occupation, obec); the ballot subjects of a parliamentary or European
  one (``tab0a``: number, name, short form, list size) and their lists
  (``tab0b``, by subject number and position). The obec is the residence's
  name alone.
- ``curated`` (:func:`read_curated`): ``candidates.toml`` in the election's
  curated data (:func:`election_map_slovakia.config.load_candidates`).

``Poznámka`` ``X`` marks a candidate (or subject) who withdrew, yet stayed
on the ballot. These lists give their contests' areas by code
(:attr:`candidates.Entry.area`); a candidate's parties are named as the
lists name them in full, a party list's candidates have their list's
party, a president's none.

Whatever the format, the contests called but held nowhere, no candidate
having registered (:attr:`candidates.Lists.not_held`: of a regular
election's territorial division, :func:`statoffice.not_held`, which for
``mvsr`` is its ``units`` part; of a by-election's package; of the
election's ``uncontested.toml``, what the inputs do not tell) are
``uncontested`` contests, each with what says so (:func:`_uncontested`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from election_map_slovakia import (
    candidates,
    config,
    contests,
    results,
    statoffice,
    tables,
)
from election_map_slovakia.candidates import CandidatesError, Entry, Lists, Subject
from election_map_slovakia.config import CuratedLists, Election

CURATED_FILE = "candidates.toml"
"""The curated lists, in the election's curated data (``curated`` format, or
a supplement to a ``susr-by`` package)."""
_WITHDRAWN = "X"
_INDEPENDENT = "NEKA"
"""What a by-election's lists name an independent candidate's party."""
_SECOND_ROUND = 2
# Column names, with the aliases ŠÚ SR words them by (tables.Table.column).
_NUMBER = ("Poradie na hlasovacom lístku",)
_ELECTED_ORDER = ("Poradie zvolenia v obci",)
_FULL_NAME = ("Meno a priezvisko",)
_FIRST_NAME = ("Meno",)
_SURNAME = ("Priezvisko",)
_TITLE = ("Titul",)
_AGE = ("Vek",)
_OCCUPATION = ("Zamestnanie",)
_NOTE = ("Poznámka",)
_RESIDENCE = ("Obec trvalého pobytu", "Obec")
_SUBJECT = ("Číslo politického subjektu",)
_SUBJECT_NAME = ("Názov politického subjektu",)
_LIST_SIZE = ("Počet kandidátov",)
_OKRES = ("Kód okresu",)
_OKRES_NAME = ("Názov okresu",)
_OBEC = ("Kód obce",)
_OBEC_NAME = ("Názov obce",)
_OBVOD = ("Volebný obvod v obci",)
_PARTIES = ("Politický subjekt",)
_SEATS = ("Počet volených poslancov",)
_TYPE = ("Typ volieb",)
_OBVODY = ("Počet volebných obvodov", "Počet volebných obvodov v obci")
_NOT_HELD = "nekonajú sa"
"""``Typ volieb`` (case aside) of an obec where a by-election was held
nowhere, no candidate having registered."""
_PARTY_SHORT = ("Skratka politickej strany",)
_PARTY_NAME = ("Názov politickej strany",)


@dataclass(frozen=True)
class _ByLayout:
    """The tables of a by-election's package that :func:`read_by_election` reads."""

    parties: str
    units: str
    mayors: str
    councils: str
    council_number: tuple[str, ...]
    """The column numbering a council's candidates: the ballot number, or
    the order elected where the table has the elected only."""


_BY_LAYOUT = _ByLayout("tab0c", "tab0dd", "tab0ad", "tab0bd", _NUMBER)
_OLDER_BY_LAYOUT = _ByLayout("tab0b", "tab0c", "tab0a", "tab06", _ELECTED_ORDER)
"""That of the packages of 2019–2022 (:func:`results.older_by_election`)."""


def read(
    election: Election,
    paths: Mapping[str, Path],
    curated_dir: Path,
    *,
    urls: Mapping[str, str] | None = None,
    councils: Mapping[str, Sequence[int]] | None = None,
) -> Lists:
    """Return the candidate lists of *election*, with its configured contests.

    *paths* are the files of the inputs its ``candidates`` names, by key,
    *urls* their sources (where none is, a contest held nowhere that one of
    them tells fails); *curated_dir* is its curated data
    (:meth:`config.Config.election_dir`); *councils*, of a by-election, obec
    → the council obvody of its term's candidate lists. A referendum has no
    lists: its contests are its questions. The contests called but held
    nowhere (:attr:`candidates.Lists.not_held`, and those of
    ``uncontested.toml``) become ``uncontested`` contests
    (:func:`_uncontested`).
    """
    lists = election.candidates
    try:
        if lists is None:
            out = Lists([])
        elif lists.format == "mvsr":
            out = _mvsr(paths)
        elif lists.format == "susr":
            out = statoffice.read_lists(paths)
        elif lists.format == "susr-by":
            path = curated_dir / CURATED_FILE
            supplement = (
                read_curated(config.load_candidates(path, election), election)
                if path.is_file()
                else None
            )
            out = read_by_election(_package(paths["package"]), supplement, councils)
        elif lists.format == "curated":
            out = read_curated(
                config.load_candidates(curated_dir / CURATED_FILE, election), election
            )
        elif "round1" in paths:
            out = read_presidential(
                {
                    n: _package(paths[f"round{n}"])
                    for n in (1, 2)
                    if f"round{n}" in paths
                }
            )
        else:
            out = read_party_lists(
                _kind(election),
                _package(paths["subjects"]).table("tab0a"),
                _package(paths["candidates"]).table("tab0b"),
            )
    except tables.TableError as e:
        raise CandidatesError(str(e)) from e
    _configured(out, election)
    path = curated_dir / UNCONTESTED_FILE
    if path.is_file():
        _curated_not_held(config.load_uncontested(path, election), out)
    _uncontested(out, urls or {})
    return out


def _mvsr(paths: Mapping[str, Path]) -> Lists:
    """Return the MV SR lists of *paths*, with what the territorial division says."""
    out = candidates.read_lists({k: p for k, p in paths.items() if k != UNITS_PART})
    if UNITS_PART in paths:
        table = _package(paths[UNITS_PART]).table("tab0dd")
        columns = [table.column(*c) for c in (_OBEC, _TYPE, _OBVODY, _SEATS)]
        rows = (tuple(r[c] for c in columns) for r in table.rows)
        statoffice.not_held(out, rows, table.name, part=UNITS_PART)
    return out


def _curated_not_held(curated: Sequence[config.CuratedUncontested], out: Lists) -> None:
    """Add to *out* the contests held nowhere of ``uncontested.toml``."""
    for u in curated:
        out.not_held[u.id] = candidates.Uncontested(u.title, source=u.source)
        if u.seats is not None:
            out.seats[u.id] = u.seats


UNITS_PART = "units"
"""The part of the ``mvsr`` inputs that is ŠÚ SR's territorial division
(``tab0dd``), whose ``Typ volieb`` says what is held where."""
UNCONTESTED_FILE = "uncontested.toml"
"""The contests called but held nowhere that the inputs do not tell, in
the election's curated data (:func:`config.load_uncontested`)."""


def _uncontested(lists: Lists, urls: Mapping[str, str]) -> None:
    """Make the contests of *lists* held nowhere ``uncontested`` contests.

    Each with the URL of what says so (an input's, *urls* by part, where
    it is an input) and what in it (:func:`candidates.build` checks that
    none has candidates).
    """
    for cid, why in sorted(lists.not_held.items()):
        source = why.source or urls.get(why.part, "")
        if not source:
            raise CandidatesError(f"{cid}: no source says it was held nowhere")
        lists.contests.setdefault(cid, {})["uncontested"] = {
            "source": source,
            "title": why.title,
        }


def _package(path: Path) -> tables.Package:
    return tables.open_package([path], results.TIMEZONE)


def _kind(election: Election) -> str:
    """Return the contest kind of a country-wide *election*."""
    return contests.ELECTION_KINDS[election.kind][0]


def _configured(lists: Lists, election: Election) -> None:
    """Add to *lists* what *election*'s configuration says of its contests."""
    kind = contests.KINDS[_kind(election)]
    if kind.sub == "round" and election.second_round is not None:
        second = f"{kind.name}:{contests.COUNTRY}/{_SECOND_ROUND}"
        # Round 2 is a contest once its candidates are known.
        if any(e.kind == kind.name and e.obvod == _SECOND_ROUND for e in lists.entries):
            lists.contests.setdefault(second, {})["day"] = (
                election.second_round.isoformat()
            )
    for q, question in enumerate(election.questions, 1):
        lists.contests[f"{kind.name}:{contests.COUNTRY}/{q}"] = {"question": question}
    if kind.party:
        fields: dict[str, object] = {
            "seats": election.seats,
            "threshold": election.threshold,
        }
        if election.coalition_thresholds:
            fields["coalition_thresholds"] = [
                [n, t] for n, t in election.coalition_thresholds
            ]
        fields |= {
            "preferences": election.preferences,
            "quota": election.preference_quota,
        }
        lists.contests.setdefault(f"{kind.name}:{contests.COUNTRY}", {}).update(fields)


def _person(
    kind: str,
    sub: int,
    table: tables.Table,
    row: Mapping[str, str],
    source: str,
    parties: list[str],
) -> Entry:
    """Return the :class:`Entry` of a country-wide candidate's *row*."""
    before, after = candidates.split_title(candidates.clean(row[table.column(*_TITLE)]))
    return Entry(
        kind=kind,
        source=source,
        region="",
        okres_code="",
        obec="",
        obvod=sub,
        number=int(row[table.column(*_NUMBER)]),
        first_name=candidates.clean(row[table.column(*_FIRST_NAME)]),
        surname=candidates.clean(row[table.column(*_SURNAME)]),
        title_before=before,
        title_after=after,
        age=int(row[table.column(*_AGE)]),
        occupation=candidates.clean(row[table.column(*_OCCUPATION)]),
        parties=parties,
        independent=False,
        residence=candidates.clean(row[table.column(*_RESIDENCE)]),
        area=contests.COUNTRY,
    )


def _withdrew(table: tables.Table, row: Mapping[str, str]) -> bool:
    note = table.optional(*_NOTE)
    return note is not None and row[note].strip() == _WITHDRAWN


def read_presidential(rounds: Mapping[int, tables.Package]) -> Lists:
    """Return the candidates of each round of a presidential election.

    *rounds* are round number → its tables (``tab0a``).
    """
    out = Lists([])
    for n, package in sorted(rounds.items()):
        table = package.table("tab0a")
        for line, row in enumerate(table.rows, 1):
            source = f"{table.name}: data row {line}"
            try:
                entry = _person("prezident", n, table, row, source, [])
            except ValueError as e:
                raise CandidatesError(f"{source}: {e}") from e
            out.entries.append(entry)
            if _withdrew(table, row):
                out.withdrawn.add(f"prezident:{contests.COUNTRY}/{n}#{entry.number}")
    return out


def read_party_lists(kind: str, subjects: tables.Table, lists: tables.Table) -> Lists:
    """Return the ballot subjects and their lists of a party-list election.

    *kind* is its contest kind (``nrsr``, ``ep``); *subjects* its table of
    subjects (``tab0a``), *lists* that of their candidates (``tab0b``). Each
    subject gets its list contest, whether its list has candidates or not.
    """
    party_contest = f"{kind}:{contests.COUNTRY}"
    out = Lists([])
    by_number: dict[int, Subject] = {}
    size = subjects.optional(*_LIST_SIZE)
    for line, row in enumerate(subjects.rows, 1):
        try:
            number = int(row[subjects.column(*_SUBJECT)])
            stated = int(row[size]) if size is not None and row[size] else None
        except ValueError as e:
            raise CandidatesError(f"{subjects.name}: data row {line}: {e}") from e
        if number in by_number:
            raise CandidatesError(f"{subjects.name}: subject {number} listed twice")
        party = candidates.clean(row[subjects.column(*_SUBJECT_NAME)])
        by_number[number] = Subject(number, party, stated, _withdrew(subjects, row))
        out.contests[f"{party_contest}/{number}"] = {"party": party}
    out.subjects[party_contest] = [by_number[n] for n in sorted(by_number)]
    for line, row in enumerate(lists.rows, 1):
        source = f"{lists.name}: data row {line}"
        try:
            subject = by_number.get(int(row[lists.column(*_SUBJECT)]))
            if subject is None:
                raise CandidatesError(f"no subject {row[lists.column(*_SUBJECT)]}")
            entry = _person(kind, subject.number, lists, row, source, [subject.party])
        except (ValueError, CandidatesError) as e:
            raise CandidatesError(f"{source}: {e}") from e
        out.entries.append(entry)
        if _withdrew(lists, row):
            out.withdrawn.add(f"{party_contest}/{subject.number}#{entry.number}")
    return out


def read_by_election(
    package: tables.Package,
    supplement: Lists | None = None,
    councils: Mapping[str, Sequence[int]] | None = None,
) -> Lists:
    """Return the candidates of a municipal by-election's package.

    Its contests only where something is elected; see the module doc.
    *supplement* is the election's curated lists (``candidates.toml``), which
    only a package of 2019–2022 may have (:func:`_supplement`). The obce
    where it was held nowhere, no candidate having registered (``Typ
    volieb`` ``Nekonajú sa``), have their contests called: of the mayor
    where no seat was (the package does not tell whether the mayor was
    called beside seats: ``uncontested.toml`` does), else of the council,
    in its one obvod of the term (*councils*: obec → the council obvody of
    the term's candidate lists); one of several is not known.
    """
    older = results.older_by_election(package)
    layout = _OLDER_BY_LAYOUT if older else _BY_LAYOUT
    table = package.table(layout.parties)
    short, name = table.column(*_PARTY_SHORT), table.column(*_PARTY_NAME)
    parties = {
        candidates.clean(r[short]): candidates.clean(r[name]) for r in table.rows
    }
    units = package.table(layout.units)
    code, number = units.column(*_OBEC), units.column(*_SEATS)
    seats = {r[code]: r[number] for r in units.rows}
    out = Lists([], partial=True)
    obvody: dict[str, set[int]] = defaultdict(set)
    for table_id, kind in ((layout.mayors, "starosta"), (layout.councils, "oz")):
        table = package.table(table_id)
        numbered = layout.council_number if kind == "oz" else _NUMBER
        for line, row in enumerate(table.rows, 1):
            source = f"{table.name}: data row {line}"
            try:
                entry = _by_entry(kind, table, row, source, parties, numbered)
            except (ValueError, CandidatesError) as e:
                raise CandidatesError(f"{source}: {e}") from e
            out.entries.append(entry)
            contest = _contest_of(entry)
            if _withdrew(table, row):
                out.withdrawn.add(f"{contest}#{entry.number}")
            if entry.obvod is not None:
                obvody[row[table.column(*_OBEC)]].add(entry.obvod)
                if older:
                    out.contests[contest] = {"elected_only": True}
    out.seats = {
        f"oz:{results.CITY_OBCE.get(code, code)}/{min(numbers)}": int(seats[code])
        for code, numbers in obvody.items()
        if len(numbers) == 1 and seats.get(code, "").isdigit()
    }
    _by_election_not_held(units, councils or {}, out)
    if supplement is not None:
        if not older:
            raise CandidatesError(
                f"{CURATED_FILE}: the package lists every candidate in full,"
                " so it has no supplement"
            )
        _supplement(out, supplement)
    return out


def _by_election_not_held(
    units: tables.Table, councils: Mapping[str, Sequence[int]], out: Lists
) -> None:
    """Add to *out* the contests a by-election held nowhere (:func:`read_by_election`).

    *units* is its package's territorial division; *councils* obec → the
    council obvody of its term's candidate lists.
    """
    code, number, kind_of = (units.column(*c) for c in (_OBEC, _SEATS, _TYPE))
    why = candidates.Uncontested(
        f"ŠÚ SR, {units.name}: Typ volieb „nekonajú sa“", part="package"
    )
    for r in units.rows:
        if r[kind_of].casefold() != _NOT_HELD:
            continue
        obec, called = results.CITY_OBCE.get(r[code], r[code]), int(r[number])
        term = len(councils.get(obec, ())) or 1
        if not called:
            candidates.not_held(out, obec, ("starosta",), 1, None, why)
        elif term == 1:
            candidates.not_held(out, obec, ("oz",), 1, called, why)
        else:
            out.unplaced.append(
                f"{obec}: {called} seat(s) in one of its {term} council obvody"
            )


def _contest_of(e: Entry) -> str:
    """Return the id of the contest of an *e* whose list gives its area."""
    return f"{e.kind}:{e.area}" + (f"/{e.obvod}" if e.obvod is not None else "")


def _supplement(lists: Lists, supplement: Lists) -> None:
    """Put the contests of *supplement* in place of those of *lists*.

    *lists* are a by-election package's of 2019–2022, *supplement* the
    curated lists of some of its contests (``candidates.toml``), each a
    municipality's own list of its registered candidates, complete with
    titles, ages and occupations. Every candidate of the package must be on
    it (:func:`_misfits`), so that the package's votes and elected (read by
    :func:`results.read_by_election`) are theirs; fails naming each contest
    that misses one, has seats other than the package's, or is none of the
    package's. A replaced council contest is no longer ``elected_only``.
    """
    package: dict[str, list[Entry]] = defaultdict(list)
    for e in lists.entries:
        package[_contest_of(e)].append(e)
    curated: dict[str, list[Entry]] = defaultdict(list)
    for e in supplement.entries:
        curated[_contest_of(e)].append(e)
    errors = []
    for cid, theirs in sorted(curated.items()):
        if cid not in package:
            errors.append(f"{cid}: not a contest of the package")
            continue
        errors += [f"{cid}: {p}" for p in _misfits(package[cid], theirs)]
        stated = supplement.seats.get(cid)
        if stated is not None and lists.seats.get(cid, stated) != stated:
            errors.append(f"{cid}: seats {stated}, the package's {lists.seats[cid]}")
    if errors:
        raise CandidatesError(
            "\n  ".join([f"{CURATED_FILE} does not fit the package:", *errors])
        )
    lists.entries = [e for e in lists.entries if _contest_of(e) not in curated]
    lists.entries += supplement.entries
    for cid in curated:
        # A by-election's lists say nothing else of a contest.
        lists.contests.pop(cid, None)
    lists.withdrawn |= supplement.withdrawn
    lists.seats |= supplement.seats


def _misfits(package: Sequence[Entry], curated: Sequence[Entry]) -> list[str]:
    """Return how the *curated* list of a contest misses the *package*'s.

    The package has every mayoral candidate: the same ballot numbers must
    have the same names. Of a council it has the elected only, each of whom
    must have one namesake on the list. Names are compared by
    :func:`candidates.name_words`.
    """

    def name(e: Entry) -> str:
        return f"{e.first_name} {e.surname}"

    def words(e: Entry) -> tuple[str, ...]:
        return candidates.name_words(name(e))

    if package[0].kind == "oz":
        out = []
        for e in package:
            found = sum(1 for c in curated if words(c) == words(e))
            if found != 1:
                where = "not on the list" if not found else "on the list twice"
                out.append(f"elected councillor {name(e)}: {where}")
        return out
    listed = {c.number: c for c in curated}
    stood = {e.number: e for e in package}
    out = [
        f"ballot number {n}: {name(e)} in the package, {name(listed[n])} on the list"
        for n, e in sorted(stood.items())
        if n in listed and words(listed[n]) != words(e)
    ]
    out += [
        f"ballot number {n} ({name(e)}): not on the list"
        for n, e in sorted(stood.items())
        if n not in listed
    ]
    out += [
        f"ballot number {n} ({name(c)}): not in the package"
        for n, c in sorted(listed.items())
        if n not in stood
    ]
    return out


def _by_entry(
    kind: str,
    table: tables.Table,
    row: Mapping[str, str],
    source: str,
    parties: Mapping[str, str],
    numbered: tuple[str, ...],
) -> Entry:
    """Return the :class:`Entry` of a by-election candidate's *row*.

    Numbered by column *numbered*; the name in two columns, else with the
    titles in one; title, age and occupation where the table has them.
    """
    full = table.optional(*_FULL_NAME)
    if full is not None:
        before, first, surname, after = candidates.split_name(row[full])
    else:
        first = candidates.clean(row[table.column(*_FIRST_NAME)])
        surname = candidates.clean(row[table.column(*_SURNAME)])
        title = table.optional(*_TITLE)
        before, after = candidates.split_title(
            candidates.clean(row[title]) if title else ""
        )
    age, occupation = table.optional(*_AGE), table.optional(*_OCCUPATION)
    names, independent = _nomination(row[table.column(*_PARTIES)], parties)
    code = row[table.column(*_OBEC)]
    return Entry(
        kind=kind,
        source=source,
        region=candidates.clean(row[table.column(*_OKRES_NAME)]),
        okres_code=row[table.column(*_OKRES)],
        obec=candidates.clean(row[table.column(*_OBEC_NAME)]),
        obvod=int(row[table.column(*_OBVOD)]) if kind == "oz" else None,
        number=int(row[table.column(*numbered)]),
        first_name=first,
        surname=surname,
        title_before=before,
        title_after=after,
        age=int(row[age]) if age else None,
        occupation=candidates.clean(row[occupation]) if occupation else "",
        parties=names,
        independent=independent,
        residence="",
        # The cities as wholes are municipalities of ŠÚ SR's tables.
        area=results.CITY_OBCE.get(code, code),
    )


def _nomination(text: str, parties: Mapping[str, str]) -> tuple[list[str], bool]:
    """Return (party names, independent) of short forms *text*."""
    shorts, _ = candidates.parse_parties(text, ",", parties)
    if shorts == [_INDEPENDENT]:
        return [], True
    unknown = [s for s in shorts if s not in parties]
    if unknown:
        raise CandidatesError(f"unknown parties {unknown} in {text!r}")
    return [parties[s] for s in shorts], False


def read_curated(curated: CuratedLists, election: Election) -> Lists:
    """Return the curated candidate lists of *election* (``candidates.toml``)."""
    out = Lists([], partial=election.kind == config.BY_ELECTION)
    for contest in curated.contests:
        c = contests.parse(contest.id)
        if contest.seats is not None:
            out.seats[contest.id] = contest.seats
        if contest.party is not None:
            out.contests[contest.id] = {"party": contest.party}
        for cand in contest.candidates:
            # A list's candidates are its party's, a president's of none.
            own = c.kind.scope != "country"
            party = [contest.party] if contest.party is not None else []
            out.entries.append(
                Entry(
                    kind=c.kind.name,
                    source=f"{curated.path.name}: {contest.id}#{cand.number}",
                    region="",
                    okres_code="",
                    obec="",
                    obvod=c.sub,
                    number=cand.number,
                    first_name=cand.first_name,
                    surname=cand.surname,
                    title_before=cand.title_before,
                    title_after=cand.title_after,
                    age=cand.age,
                    occupation=cand.occupation,
                    parties=list(cand.parties) if own else party,
                    independent=own and not cand.parties,
                    residence=cand.residence,
                    area=c.area,
                )
            )
            if cand.withdrawn:
                out.withdrawn.add(f"{contest.id}#{cand.number}")
    if curated.subjects:
        party_contest = f"{_kind(election)}:{contests.COUNTRY}"
        out.subjects[party_contest] = [Subject(n, p) for n, p in curated.subjects]
        for n, party in curated.subjects:
            out.contests[f"{party_contest}/{n}"] = {"party": party}
    return out
