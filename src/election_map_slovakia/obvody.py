"""Constituency (obvod) membership: by whole municipalities, or by address.

Regional council obvody, and the city council obvody of Bratislava and
Košice, consist of whole obce or city districts. Their membership is
transcribed from the official decisions into ``obvody/<area>.toml`` in the
election's curated data (:meth:`election_map_slovakia.config.Config.election_dir`;
form: :func:`election_map_slovakia.config.load_obvody`); :func:`resolve`
checks it against the municipalities of the area.

An obec (or city district) that elects its council in several obvody sets
them in a resolution of its council, by streets and house numbers, parts of
the obec (časti obce) or cadastral areas (katastrálne územia, k.ú.). Its rule
set, ``obvody/oz/<obec>.toml`` there (written by ``ems job ingest``
from an ``obvod-rules`` job, see :mod:`election_map_slovakia.obvodrules`),
gives every address of the obec its obvod (:func:`assign`)::

    obec = "500011"                  # the obec code
    name = "Nitra"
    date = 2026-06-23                # of the decision
    fill = "nearest"                 # optional, see below
    note = "…"                       # optional
    estimated = true                 # optional, see below

    [[document]]                     # one or more: the official source
    url = "https://nitra.sk/…"
    sha256 = "…"                     # of its copy in data/curated/cache/
    title = "Uznesenie MZ č. 123/2026"

    [obvod.1]
    seats = 7
    rules = [
      {street = "Bratislavská", numbers = "1-102"},
      {street = "Ulica generála Viesta", written = "gen. Viesta"},
      {part = "Zobor"},
    ]

A rule selects addresses by one of

- ``street``: the street as the address register names it (compared like the
  search does: ignoring case, diacritics and punctuation), optionally only
  in ``part``; ``written`` is the name as the document has it, where that
  differs (it must read as the same name, see :func:`same_name`, or the rule
  needs a ``note``);
- ``part``: a part of the obec (časť obce) as the register names it;
- ``ku``: a k.ú. of the obec by its ZBGIS name; the address's point decides;
- ``rest = true``: the addresses no other rule selects (one such rule);
- ``near = [lon, lat]``: the addresses (optionally only in ``part``) whose
  point is nearer to this point (WGS84) than to that of any other ``near``
  rule that may select them; only in an estimated rule set;
- none of these: every address of the obec, ``numbers`` then required.

``numbers`` narrows a rule to house numbers: comma-separated items ``12``
(12 with any letter: 12, 12A), ``12A`` (that house only), ``1-35`` (any
letter), ``50-`` (50 and up). ``parity = "odd"`` or ``"even"`` keeps the odd
or even numbers (without ``numbers``: all of them), ``except`` (same form)
leaves some out. The numbers are orientačné (the number on the building
within its street) in a street, súpisné (the number within the obec)
otherwise, unless ``by = "orientacne"`` or ``"supisne"`` says. A house
number 178/1 is súpisné 178, orientačné 1; a house without the kind of
number a rule counts is not selected by it.

``inferred = true`` marks a rule the document does not state (a street it
does not name, placed by the streets around it); its ``note`` says so. Any
rule may have a ``note``. ``supplemented = true`` marks a rule taken from a
later source (below).

The most specific rule that selects an address decides, by level: a number
with a letter (12A), other numbers, a whole street, a whole part, a k.ú.,
the nearest point, the rest. Two rules of one level for different obvody
both selecting an address are an error, and so is an address no rule
selects, unless ``fill = "nearest"``: then it takes the obvod of the
nearest address a rule placed (one without a point: the obvod most of its
street got, else most of its part).

``estimated = true`` marks a rule set that no document states: the obec
published only the obvody's names and seats (``the lower end``, ``above
the railway``, named hamlets), so the rules are a guess from the geography,
mostly by ``near`` points, which its ``note`` (then required) explains. The
map and the ballots say so.

``reused = 2026-10-24`` marks a rule set of an earlier election copied from
the rule set of the election of that day, its documents and date being
that election's: no document of its own election was found, and the
layout provably matches (the same obvody, seats and okrsky per obvod, each
okrsok with nearly as many voters; see :mod:`election_map_slovakia.reuse`).
Its ``note`` (then required) says so; the map says the borders are that
election's.

``adopted = 2026-10-24`` marks a rule set of an earlier election that is
the rule set of the election of that day as it stands, its documents and
date being that election's, though the layout is not proven to match: no
usable document of its own election places the addresses, and drawing
them so was chosen over leaving them unknown (the obec is listed for it,
see :mod:`election_map_slovakia.reuse`). Only its obvod numbers and seats
are known to be the election's. ``adopted_basis`` (then required) says
why there are no rules of its own and what is known to differ; the map
says the borders are the later election's, indicative only. Its okrsky,
where it gives them, are adopted with it (``okrsky_adopted``). Neither
``reused`` nor a supplement goes with it.

``date_approximate`` marks documents that state no date, which an earlier
election's rule set may still use where something else bounds their date
to that election (:mod:`election_map_slovakia.obvodrules` checks it), and
says what does: ``"archived"``, the Internet Archive captured the document,
or the official page linking it, on ``date_seen``, before the vote;
``"posted"``, the official page says it was posted (vyvesené,
zverejnené) on ``date_seen``, before the vote; ``"named"``, the document
names the election (no ``date_seen``). ``date_basis`` (then required)
says it in words: which capture or page, which wording. Such a rule set
has no ``date``; the ballots say its dating is approximate, the document
possibly older than the election::

    date_approximate = "archived"
    date_seen = 2022-09-28
    date_basis = "the Internet Archive captured the document on 2022-09-28"

``supplemented`` marks an earlier election's rule set whose documents do
not place every address (houses they leave out, hamlets the register has
no part for, a split they leave unclear), where a later source does: the
rules it gave are marked ``supplemented = true``, the others are the
documents'. ``supplemented`` is the day of that source: the later
election whose rule set (in this repository) has those rules
(``supplemented_from = "election"``), or the date of a later document of
the obec, listed among the documents (``"document"``; for okrsky also
``"referendum"``, the document of the referendum of that day).
``supplement_basis`` (then required) says what was taken from which source,
for which addresses. It fills in or fixes what the documents leave; it
never stands in for them, so some rules stay the documents' own. The
ballots say part of the borders comes from a later source::

    supplemented = 2026 - 10 - 24
    supplemented_from = "election"
    supplement_basis = "the hamlets U Tížikov, … as in the rule set of 2026 (…)"

The okrsky (volebné okrsky: the polling districts, each with its polling
station and its roll of voters) are set by the mayor for each election, and
each lies within one council obvod. A rule set may give each obvod its
okrsky, numbered across the obec 1..N, and the okrsky of an obvod that has
several rules of their own, which choose among the addresses of that obvod
only (:func:`assign_okrsky`; added by an ``okrsok-rules`` job, see
:mod:`election_map_slovakia.okrsokrules`)::

    okrsky_date = 2026-07-23         # of the decision on them; optional
    okrsky_fill = "nearest"          # optional, as fill, within an obvod
    okrsky_note = "…"                # optional
    okrsky_reused = 2026-10-24       # optional, see below
    okrsky_referendum = 2023-01-21   # optional, see below
    okrsky_adopted = 2026-10-24      # optional, see below, with
    okrsky_adopted_basis = "…"       # okrsky_adopted_basis
    okrsky_date_approximate = "named"  # optional, see below, with
    okrsky_date_basis = "…"            # okrsky_date_seen where it needs one
    okrsky_supplemented = 2026-10-24   # optional, see below, with
    okrsky_supplemented_from = "election"  # and okrsky_supplement_basis

    [obvod.1]
    seats = 7
    okrsky = [1, 2]
    rules = […]

    [okrsok.1]
    rules = [{street = "Bratislavská"}]

    [okrsok.2]
    rules = [{rest = true}]

Either every obvod lists its okrsky or none does. An okrsok alone in its
obvod has no rules: it is the obvod. The okrsky of the obvody with several
either all have rules or, where no document lists their streets, none in
the rule set has: then only which okrsky make up each obvod is known
(:attr:`RuleSet.okrsok_areas` is false). Okrsok rules take the forms above;
``rest = true`` is the rest of their obvod, at most once per obvod. An
okrsok of the residents registered without an address (bez ulice,
trvalý pobyt len na obec) has ``addressless = true`` instead of rules: no
address is in it, and the other okrsky of its obvod share the addresses as
if it were not there.

``okrsky_reused`` marks okrsky copied, like ``reused``, from the election
of that day; ``okrsky_referendum`` okrsky transcribed from the document of
the referendum of that day, which said they stay as they were, or where
no document of the election itself was found. Either needs
``okrsky_note`` saying so. ``okrsky_date_approximate``,
``okrsky_date_seen`` and ``okrsky_date_basis`` date the okrsky document
approximately, as ``date_approximate`` and its keys do the rule set's;
``okrsky_supplemented``, ``okrsky_supplemented_from`` and
``okrsky_supplement_basis`` mark okrsok rules from a later source, as
``supplemented`` and its keys do the obvod rules. ``okrsky_adopted`` and
``okrsky_adopted_basis`` mark okrsky that are those of the later election
of that day as they stand, as ``adopted`` and its key do a rule set; they
go with neither ``okrsky_reused``, ``okrsky_referendum`` nor a supplement.

An obec that elects its council in one obvod but votes in several okrsky
has no rule set; its okrsky are in ``okrsky/<obec>.toml`` in the
election's data (:func:`okrsky_path`; written by ``ems job ingest`` from an
``okrsok-rules`` job)::

    obec = "123456"
    name = "…"
    okrsky_date = 2026-07-20         # optional, as above
    okrsky_fill = "nearest"          # optional
    okrsky_note = "…"                # optional
    okrsky_reused = 2026-10-24       # optional, as above
    okrsky_referendum = 2023-01-21   # optional, as above
    okrsky_adopted = 2026-10-24      # optional, as above, with
    okrsky_adopted_basis = "…"       # okrsky_adopted_basis
    okrsky_date_approximate = "…"    # optional, as above, with
    okrsky_date_seen = 2022-09-28    # okrsky_date_seen and
    okrsky_date_basis = "…"          # okrsky_date_basis
    okrsky_supplemented = 2026-10-24 # optional, as above, with
    okrsky_supplemented_from = "…"   # okrsky_supplemented_from and
    okrsky_supplement_basis = "…"    # okrsky_supplement_basis

    [[document]]
    url = "https://…"
    sha256 = "…"
    title = "Utvorenie volebných okrskov"

    [okrsok.1]
    rules = [{part = "Horná Ves"}]

    [okrsok.2]
    rules = [{rest = true}]

The okrsky are numbered 1..N (N ≥ 2), each with rules of the forms above,
which choose among all the addresses of the obec, or ``addressless =
true``; where the others are all addressless, the one okrsok with the
addresses has an empty table. :func:`okrsky_set` reads it as a rule set
whose one obvod 1 is the whole obec and holds every okrsok
(:attr:`RuleSet.whole`), so the okrsky of both kinds of obec are assigned
and drawn alike; :func:`okrsok_rule_sets` returns every rule set that gives
the okrsky.
"""

from __future__ import annotations

import datetime as dt
import functools
import json
import re
import tomllib
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import shapely

from election_map_slovakia import output
from election_map_slovakia.candidates import Obec, search_key
from election_map_slovakia.config import Obvod, ObvodList

DIRECTORY = "obvody"
RULES_DIRECTORY = "oz"
"""Rule sets, below :data:`DIRECTORY`."""
OKRSKY_DIRECTORY = "okrsky"
"""Below the election's data: the okrsky of the obce with one council obvod."""
ORIENTACNE = "orientacne"
SUPISNE = "supisne"
PARITIES = ("odd", "even")
FILL_NEAREST = "nearest"
APPROXIMATE = ("archived", "posted", "named")
"""What dates the documents of a rule set that state no date
(``date_approximate``): a capture or posting day, or naming the election."""
SEEN = ("archived", "posted")
"""The kinds of :data:`APPROXIMATE` that give a day (``date_seen``)."""
LATER_ELECTION, LATER_REFERENDUM, LATER_DOCUMENT = "election", "referendum", "document"
SUPPLEMENT_FROM = (LATER_ELECTION, LATER_REFERENDUM, LATER_DOCUMENT)
"""The later sources of rules that fill in an earlier election's documents
(``supplemented_from``): a later election's rule set, a referendum's
document, another later document of the obec."""
OBVOD = "obvod"
OKRSOK = "okrsok"
"""The units a rule places an address in."""
_PLURAL = {OBVOD: "obvody", OKRSOK: "okrsky"}
# Precedence levels of a rule selecting an address, most specific first.
LETTER, NUMBERS, STREET, PART, KU, NEAR, REST = range(7)
LEVELS = (
    "numbered house",
    "numbers",
    "street",
    "part",
    "k.ú.",
    "nearest point",
    "rest",
)
POINT_SCALE = 100_000
"""Units per degree of the address points (:attr:`ObecPlaces.points`)."""
_PLANAR = (np.cos(np.radians(48.7)), 1.0)
"""Scale of longitude and latitude for nearness within one obec."""
_EXTENT = (16.8, 47.7, 22.6, 49.7)
"""West, south, east, north: Slovakia, for a ``near`` point."""
_LONLAT = 2  # coordinates of a near point
_SEVERAL = 2  # okrsky of an obec with one council obvod
_OBEC = re.compile(r"\d{6}")
_NUMBER = re.compile(r"[1-9]\d*")
"""A table key that numbers an obvod or okrsok."""
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ITEM = re.compile(r"(\d+)\s*([^\W\d_]*)(?:\s*(-)\s*(\d*))?")
_HOUSE = re.compile(r"0*(\d+)\s*([^\W\d_]*)")
_DASHES = str.maketrans("\u2010\u2011\u2012\u2013\u2014\u2212", "------")
# Words a document may add to or drop from a street name.
_FILLER = frozenset({"ulica", "ul"})
_WORD = re.compile(r"[^\W_]+\.?")
"""A word of a street name, with the dot that marks it abbreviated."""
# Standard abbreviations that are not the start of their word.
_ABBREVIATIONS = {"cs": "ceskoslovensk", "csl": "ceskoslovensk"}
_SHOWN = 5
"""Examples listed per problem."""


class ObvodyError(Exception):
    """A membership file or rule set is malformed or does not cover its area."""


def resolve(
    obvody: ObvodList, area: Mapping[str, Obec], expected: int
) -> dict[int, tuple[str, ...]]:
    """Return obvod number → obec codes, okresy expanded to their obce.

    *area* holds every obec that must be in exactly one obvod; *expected* is
    the number of obvody the candidate lists have. Fails listing every
    problem at once.
    """
    errors = []
    if len(obvody.obvody) != expected:
        errors.append(
            f"{len(obvody.obvody)} obvody, but the candidate lists have {expected}"
        )
    members = {o.number: _expand(o, area, errors) for o in obvody.obvody}
    where: dict[str, list[int]] = defaultdict(list)
    for number, codes in members.items():
        for code in codes:
            where[code].append(number)
    for code, numbers in sorted(where.items()):
        if len(numbers) > 1:
            listed = " and ".join(map(str, numbers))
            errors.append(f"{_name(area[code])} is listed in obvod {listed}")
    errors += [
        f"{_name(area[c])} is in no obvod" for c in sorted(area) if c not in where
    ]
    if errors:
        raise ObvodyError("\n  ".join([f"{obvody.path}:", *errors]))
    return members


def _expand(
    obvod: Obvod, area: Mapping[str, Obec], errors: list[str]
) -> tuple[str, ...]:
    """Return the obce of *obvod*; append unknown members to *errors*."""
    codes = []
    for okres in obvod.okresy:
        in_okres = [c for c in sorted(area) if area[c].okres == okres]
        if not in_okres:
            errors.append(f"obvod {obvod.number}: okres {okres} is not in the area")
        codes += in_okres
    for code in obvod.obce:
        if code in area:
            codes.append(code)
        else:
            errors.append(f"obvod {obvod.number}: obec {code} is not in the area")
    return tuple(codes)


def _name(obec: Obec) -> str:
    return f"obec {obec.code} ({obec.name})"


# --- rule sets ---------------------------------------------------------------


@dataclass(frozen=True)
class Document:
    """An official document a rule set is transcribed from."""

    url: str
    sha256: str
    """Of the copy in ``data/curated/cache/``."""
    title: str


@dataclass(frozen=True)
class Dating:
    """What dates documents that state no date (``date_approximate``)."""

    by: str
    """One of :data:`APPROXIMATE`."""
    seen: dt.date | None
    """The capture or posting day, for the kinds of :data:`SEEN`."""
    basis: str
    """The same in words."""

    def flag(self) -> dict[str, str]:
        """Return the per-obec flag of ``data/index.json``: ``{by, (seen)}``."""
        return {"by": self.by} | ({"seen": self.seen.isoformat()} if self.seen else {})


@dataclass(frozen=True)
class Supplement:
    """The later source of rules the documents leave out (``supplemented``)."""

    day: dt.date
    """The later vote's day, or the later document's date."""
    source: str
    """One of :data:`SUPPLEMENT_FROM` (``supplemented_from``)."""
    basis: str
    """What was taken from it, for which addresses, in words."""

    def flag(self) -> dict[str, str]:
        """Return the per-obec flag of ``data/index.json``: ``{from, day}``."""
        return {"from": self.source, "day": self.day.isoformat()}


@dataclass(frozen=True)
class Adoption:
    """The later election whose rules stand in, unproven (``adopted``)."""

    day: dt.date
    """That election's day."""
    basis: str
    """Why the election has no rules of its own, and what is known to differ."""


@dataclass(frozen=True)
class Rule:
    """One rule of a rule set; see the module doc."""

    unit: int
    """The obvod (or okrsok, by :attr:`level`) the rule places addresses in."""
    street: str | None = None
    part: str | None = None
    ku: str | None = None
    rest: bool = False
    near: tuple[float, float] | None = None
    """Longitude, latitude."""
    numbers: str | None = None
    parity: str | None = None
    excluded: str | None = None
    """``except`` in the file."""
    by: str | None = None
    written: str | None = None
    inferred: bool = False
    note: str | None = None
    supplemented: bool = False
    """Whether it is from a later source (:class:`Supplement`), not the documents."""
    level: str = OBVOD
    """:data:`OBVOD` or :data:`OKRSOK`: what :attr:`unit` numbers."""

    @property
    def numbered(self) -> bool:
        """Return whether the rule narrows its selection to house numbers."""
        return bool(self.numbers or self.parity or self.excluded)

    @property
    def kind(self) -> str:
        """Return which number of a house the rule counts."""
        return self.by or (ORIENTACNE if self.street else SUPISNE)

    @property
    def selects(self) -> tuple[object, ...]:
        """Return what the rule selects, numbers included, whatever its unit.

        Equal for the rules of two rule sets that select the same addresses
        (names compared as :func:`same_name` does).
        """
        names = tuple(_key(x) if x else None for x in (self.street, self.part, self.ku))
        numbers = (self.numbers, self.parity, self.excluded)
        return (*names, self.rest, self.near, *numbers, self.numbered and self.kind)

    def describe(self) -> str:
        """Return the rule as one line, for reports."""
        what = self._selection()
        if self.numbered:
            narrowed = (
                self.numbers,
                self.parity,
                self.excluded and f"except {self.excluded}",
            )
            what += f" {' '.join(x for x in narrowed if x)} ({self.kind})"
        return f"{self.level} {self.unit}: {what}"

    def _selection(self) -> str:
        """Return what the rule selects before any numbers narrow it."""
        if self.rest:
            return "the rest"
        if self.ku:
            return f"k.ú. {self.ku}"
        where = (
            self.street,
            self.near and f"near {self.near[0]}, {self.near[1]}",
            self.part and f"part {self.part}",
        )
        return " in ".join(x for x in where if x is not None) or "the obec"


@dataclass(frozen=True)
class RuleSet:
    """``obvody/oz/<obec>.toml``; see the module doc."""

    obec: str
    name: str
    date: dt.date | None
    """The council's decision; None where no published document states it."""
    documents: tuple[Document, ...]
    seats: dict[int, int]
    """Obvod number → councillors elected there; numbered 1..N. ``{1: 0}``
    in a :attr:`whole` rule set, which does not state the council's size."""
    rules: tuple[Rule, ...]
    fill: bool = False
    """Whether addresses no rule selects take the nearest one's obvod."""
    note: str | None = None
    estimated: bool = False
    """Whether the rules are a guess that no document states."""
    reused: dt.date | None = None
    """The day of the election whose rule set this is a copy of, if one."""
    adoption: Adoption | None = None
    """The later election whose rule set this is, unproven to match, if one
    (``adopted``)."""
    dating: Dating | None = None
    """What dates the documents, where they state no date and are dated
    approximately (``date_approximate``)."""
    supplement: Supplement | None = None
    """The later source of the obvod rules the documents leave out, if one
    (``supplemented``)."""
    okrsky: dict[int, tuple[int, ...]] = field(default_factory=dict)
    """Obvod → its okrsky; empty where they are not known."""
    okrsok_rules: tuple[Rule, ...] = ()
    """The rules of the okrsky of the obvody with several."""
    okrsky_fill: bool = False
    """Whether addresses no okrsok rule selects take the nearest one's okrsok."""
    okrsky_date: dt.date | None = None
    """The decision that set the okrsky (the mayor's, or the council's), where known."""
    okrsky_note: str | None = None
    okrsky_reused: dt.date | None = None
    """The day of the election whose okrsky these are a copy of, if one."""
    okrsky_referendum: dt.date | None = None
    """The day of the referendum whose okrsky document these are from, if one."""
    okrsky_dating: Dating | None = None
    """As :attr:`dating`, of the okrsky's documents (``okrsky_date_approximate``)."""
    okrsky_supplement: Supplement | None = None
    """As :attr:`supplement`, of the okrsok rules (``okrsky_supplemented``)."""
    okrsky_adoption: Adoption | None = None
    """As :attr:`adoption`, of the okrsky (``okrsky_adopted``)."""
    addressless: tuple[int, ...] = ()
    """Okrsky of residents registered without an address, which no address
    is in (``addressless = true`` in their table)."""
    whole: bool = False
    """Whether it is the okrsky of an obec with one council obvod
    (``okrsky/<obec>.toml``): obvod 1 is the whole obec."""

    @property
    def by_ku(self) -> bool:
        """Return whether the obvody are unions of whole k.ú."""
        return all(r.ku or r.rest for r in self.rules)

    @property
    def okrsok_obvod(self) -> dict[int, int]:
        """Return okrsok → its obvod, by okrsok number."""
        return dict(sorted((k, o) for o, ks in self.okrsky.items() for k in ks))

    @property
    def mapped(self) -> dict[int, list[int]]:
        """Return obvod → its okrsky that have addresses."""
        return {
            o: [k for k in ks if k not in self.addressless]
            for o, ks in self.okrsky.items()
        }

    @property
    def okrsok_areas(self) -> bool:
        """Return whether every address can be given its okrsok.

        That is where the okrsky are known and those with addresses that
        share an obvod have rules (:func:`assign_okrsky`).
        """
        return bool(self.okrsky) and (
            bool(self.okrsok_rules) or all(len(k) == 1 for k in self.mapped.values())
        )


def rules_path(election_dir: Path, obec: str) -> Path:
    """Return the path of the rule set of *obec* in the election's data.

    *election_dir* is :meth:`election_map_slovakia.config.Config.election_dir`.
    """
    return election_dir / DIRECTORY / RULES_DIRECTORY / f"{obec}.toml"


def okrsky_path(election_dir: Path, obec: str) -> Path:
    """Return the path of the okrsky of *obec*, one with one council obvod."""
    return election_dir / OKRSKY_DIRECTORY / f"{obec}.toml"


def load_rule_sets(election_dir: Path) -> dict[str, RuleSet]:
    """Return obec → rule set, of every rule set of the election (*election_dir*)."""
    return _load(sorted((election_dir / DIRECTORY / RULES_DIRECTORY).glob("*.toml")))


def okrsok_rule_sets(election_dir: Path) -> dict[str, RuleSet]:
    """Return obec → rule set, of every obec of the election whose okrsky are known.

    The rule sets of :func:`load_rule_sets` that give their okrsky, and the
    okrsky of the obce with one council obvod (:func:`okrsky_set`).
    """
    rule_sets = load_rule_sets(election_dir)
    whole = _load(sorted((election_dir / OKRSKY_DIRECTORY).glob("*.toml")), True)
    both = sorted(whole.keys() & rule_sets.keys())
    if both:
        raise ObvodyError(
            f"{okrsky_path(election_dir, both[0])}: the obec has council obvody;"
            f" its okrsky belong in {rules_path(election_dir, both[0])}"
        )
    out = {c: r for c, r in rule_sets.items() if r.okrsky} | whole
    return dict(sorted(out.items()))


def load_obec(election_dir: Path, obec: str) -> RuleSet | None:
    """Return the rule set of *obec* in the election's data, else its okrsky, else None.

    The rule set of its council obvody (:func:`rules_path`), or, for an obec
    with one obvod, its okrsky (:func:`okrsky_path`, :attr:`RuleSet.whole`).
    """
    for path, whole in (
        (rules_path(election_dir, obec), False),
        (okrsky_path(election_dir, obec), True),
    ):
        if path.is_file():
            return _load([path], whole)[obec]
    return None


def council_origin(rules: RuleSet) -> dict[str, Any]:
    """Return the per-obec flags of council obvody not from a dated document.

    ``reused``, the ISO day of the election whose rule set *rules* is a
    copy of, ``adopted``, that of the later election whose rule set it is
    without proof that it matches, ``date_approximate``, the
    :meth:`Dating.flag` of documents dated approximately, and
    ``supplemented``, the :meth:`Supplement.flag` of rules from a later
    source; ``data/index.json`` carries them.
    """
    out: dict[str, Any] = {}
    if rules.reused:
        out["reused"] = rules.reused.isoformat()
    if rules.adoption:
        out["adopted"] = rules.adoption.day.isoformat()
    if rules.dating:
        out["date_approximate"] = rules.dating.flag()
    if rules.supplement:
        out["supplemented"] = rules.supplement.flag()
    return out


def okrsky_origin(rules: RuleSet) -> dict[str, Any]:
    """Return the per-obec flags of okrsky that are another vote's, or approximately dated.

    ``okrsky_reused`` (another election's okrsky), ``okrsky_adopted`` (a
    later election's, unproven) or ``okrsky_referendum`` (a referendum's
    document), each the ISO day of that vote, ``okrsky_date_approximate``,
    the :meth:`Dating.flag` of documents dated approximately, and
    ``okrsky_supplemented``, the :meth:`Supplement.flag` of okrsok rules
    from a later source; ``data/index.json`` carries them.
    """
    out: dict[str, Any] = {}
    if rules.okrsky_reused:
        out["okrsky_reused"] = rules.okrsky_reused.isoformat()
    if rules.okrsky_adoption:
        out["okrsky_adopted"] = rules.okrsky_adoption.day.isoformat()
    if rules.okrsky_referendum:
        out["okrsky_referendum"] = rules.okrsky_referendum.isoformat()
    if rules.okrsky_dating:
        out["okrsky_date_approximate"] = rules.okrsky_dating.flag()
    if rules.okrsky_supplement:
        out["okrsky_supplemented"] = rules.okrsky_supplement.flag()
    return out


def _load(paths: Sequence[Path], whole: bool = False) -> dict[str, RuleSet]:
    """Return obec → rule set of the files *paths*, okrsky files if *whole*."""
    out = {}
    for path in paths:
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ObvodyError(f"{path}: invalid TOML: {e}") from e
        rules = (okrsky_set if whole else rule_set)(data, str(path))
        if rules.obec != path.stem:
            raise ObvodyError(f"{path}: obec {rules.obec} in the file of {path.stem}")
        out[rules.obec] = rules
    return out


class _Fields:
    """Typed access to one table of a rule set, tracking the keys used."""

    def __init__(self, data: object, where: str) -> None:
        if not isinstance(data, Mapping):
            raise ObvodyError(f"{where}: must be a table")
        self.data: Mapping[str, Any] = data
        self.where = where
        self.used: set[str] = set()

    def error(self, key: str, message: str) -> ObvodyError:
        return ObvodyError(f"{self.where}.{key}: {message}")

    def get(self, key: str, kind: type, *, required: bool = False) -> Any:
        if key not in self.data:
            if required:
                raise self.error(key, "missing")
            return None
        value = self.data[key]
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            raise self.error(key, f"expected {kind.__name__}")
        self.used.add(key)
        return value

    def text(self, key: str, *, required: bool = False) -> str | None:
        value = self.get(key, str, required=required)
        if value is not None and not value.strip():
            raise self.error(key, "must not be empty")
        return value

    def choice(self, key: str, choices: Sequence[str]) -> str | None:
        value = self.text(key)
        if value is not None and value not in choices:
            raise self.error(key, f"must be one of {', '.join(choices)}")
        return value

    def done(self) -> None:
        unknown = sorted(set(self.data) - self.used)
        if unknown:
            raise self.error(unknown[0], "unknown key")


def rule_set(data: Mapping[str, Any], where: str) -> RuleSet:
    """Return the rule set in *data* (a parsed TOML file); see the module doc.

    Checks the form only; whether it fits the addresses is :func:`assign`'s.
    *where* names the source in errors.
    """
    t = _Fields(data, where)
    obec, documents = _source(t, where)
    date = _date(t, "date")
    dating = _dating(t, "", date)
    seats, rules, okrsky = _obvod_tables(t, where)
    fill = _nearest_fill(t, "fill")
    okrsok_rules, addressless = _okrsok_rules(t, where, seats, okrsky)
    okrsky_date = _date(t, "okrsky_date")
    okrsky_fill = _nearest_fill(t, "okrsky_fill")
    okrsky_note = t.text("okrsky_note")
    okrsky_reused = _date(t, "okrsky_reused")
    okrsky_referendum = _date(t, "okrsky_referendum")
    okrsky_dating = _dating(t, "okrsky_", okrsky_date)
    okrsky_supplement = _supplement(t, "okrsky_")
    okrsky_adoption = _adoption(t, "okrsky_")
    if not okrsky and (
        okrsky_date
        or okrsky_note
        or okrsky_reused
        or okrsky_referendum
        or okrsky_dating
        or okrsky_supplement
        or okrsky_adoption
    ):
        raise t.error("okrsky_date", "the okrsky_* keys need the okrsky")
    if okrsky_fill and not okrsok_rules:
        raise t.error("okrsky_fill", "is for okrsok rules")
    out = RuleSet(
        obec=obec,
        name=t.text("name", required=True) or "",
        date=date,
        documents=documents,
        seats=seats,
        rules=rules,
        fill=fill,
        note=t.text("note"),
        estimated=bool(t.get("estimated", bool)),
        reused=_date(t, "reused"),
        adoption=_adoption(t, ""),
        dating=dating,
        supplement=_supplement(t, ""),
        okrsky=okrsky,
        okrsok_rules=okrsok_rules,
        okrsky_fill=okrsky_fill,
        okrsky_date=okrsky_date,
        okrsky_note=okrsky_note,
        okrsky_reused=okrsky_reused,
        okrsky_referendum=okrsky_referendum,
        okrsky_dating=okrsky_dating,
        okrsky_supplement=okrsky_supplement,
        okrsky_adoption=okrsky_adoption,
        addressless=addressless,
    )
    t.done()
    _check_estimated(out, t)
    _check_origin(out, t)
    _check_supplement(out, t)
    return out


def okrsky_set(data: Mapping[str, Any], where: str) -> RuleSet:
    """Return the okrsky in *data* (a parsed ``okrsky/<obec>.toml``) as a rule set.

    Its one obvod 1 holds every address and every okrsok; see the module
    doc. Checks the form only, like :func:`rule_set`.
    """
    t = _Fields(data, where)
    obec, documents = _source(t, where)
    tables = t.get("okrsok", dict, required=True)
    numbers = sorted(int(k) for k in tables if _NUMBER.fullmatch(k))
    if len(numbers) < _SEVERAL or numbers != list(range(1, len(tables) + 1)):
        raise t.error("okrsok", "the okrsky must be numbered 1..N, N at least 2")
    okrsky = {1: tuple(numbers)}
    okrsok_rules, addressless = _okrsok_rules(t, where, {1: 0}, okrsky)
    okrsky_date = _date(t, "okrsky_date")
    out = RuleSet(
        obec=obec,
        name=t.text("name", required=True) or "",
        date=None,
        documents=documents,
        seats={1: 0},
        rules=(Rule(1, rest=True),),
        okrsky=okrsky,
        okrsok_rules=okrsok_rules,
        okrsky_fill=_nearest_fill(t, "okrsky_fill"),
        okrsky_date=okrsky_date,
        okrsky_note=t.text("okrsky_note"),
        okrsky_reused=_date(t, "okrsky_reused"),
        okrsky_referendum=_date(t, "okrsky_referendum"),
        okrsky_dating=_dating(t, "okrsky_", okrsky_date),
        okrsky_supplement=_supplement(t, "okrsky_"),
        okrsky_adoption=_adoption(t, "okrsky_"),
        addressless=addressless,
        whole=True,
    )
    t.done()
    if not out.okrsok_areas:
        raise t.error("okrsok", "the okrsky that share the obec need their rules")
    _check_estimated(out, t)
    _check_origin(out, t)
    _check_supplement(out, t)
    return out


def _source(t: _Fields, where: str) -> tuple[str, tuple[Document, ...]]:
    """Return the obec code and the documents of rule set *t*."""
    obec = t.text("obec", required=True) or ""
    if not _OBEC.fullmatch(obec):
        raise t.error("obec", "must be a 6-digit obec code")
    documents = tuple(
        _document(d, f"{where}.document[{i}]")
        for i, d in enumerate(t.get("document", list, required=True))
    )
    if not documents:
        raise t.error("document", "must list the official document")
    return obec, documents


def _date(t: _Fields, key: str) -> dt.date | None:
    value = t.get(key, dt.date)
    if isinstance(value, dt.datetime):
        raise t.error(key, "must be a date without a time")
    return value


def _dating(t: _Fields, prefix: str, date: dt.date | None) -> Dating | None:
    """Return the ``<prefix>date_approximate`` of *t* and its keys, if given.

    *date* is the ``<prefix>date`` stated beside it; see the module doc.
    """
    key = f"{prefix}date_approximate"
    by = t.choice(key, APPROXIMATE)
    seen = _date(t, f"{prefix}date_seen")
    basis = t.text(f"{prefix}date_basis")
    if by is None:
        if seen or basis:
            raise t.error(key, f"{prefix}date_seen and {prefix}date_basis need it")
        return None
    if date is not None:
        raise t.error(
            key, f"is for documents that state no date, not with {prefix}date"
        )
    if basis is None:
        raise t.error(f"{prefix}date_basis", "missing: what dates the documents")
    if (seen is None) == (by in SEEN):
        need = "needs the day it was seen" if by in SEEN else "names no day"
        raise t.error(f"{prefix}date_seen", f"{by!r} {need}")
    return Dating(by, seen, basis)


def _supplement(t: _Fields, prefix: str) -> Supplement | None:
    """Return the ``<prefix>supplemented`` of *t* and its keys, if given."""
    key = f"{prefix}supplemented"
    day = _date(t, key)
    source = t.choice(f"{prefix}supplemented_from", SUPPLEMENT_FROM)
    basis = t.text(f"{prefix}supplement_basis")
    if day is None:
        if source or basis:
            raise t.error(
                key, f"{prefix}supplemented_from and {prefix}supplement_basis need it"
            )
        return None
    if source is None:
        raise t.error(f"{prefix}supplemented_from", "missing: what the later source is")
    if basis is None:
        raise t.error(
            f"{prefix}supplement_basis", "missing: what was taken from the later source"
        )
    return Supplement(day, source, basis)


def _adoption(t: _Fields, prefix: str) -> Adoption | None:
    """Return the ``<prefix>adopted`` of *t* and its basis, if given."""
    key = f"{prefix}adopted"
    day = _date(t, key)
    basis = t.text(f"{prefix}adopted_basis")
    if day is None:
        if basis:
            raise t.error(key, f"missing: {prefix}adopted_basis needs it")
        return None
    if basis is None:
        raise t.error(
            f"{prefix}adopted_basis", "missing: why no rules of its own, what differs"
        )
    return Adoption(day, basis)


def _nearest_fill(t: _Fields, key: str) -> bool:
    """Return whether *key* of *t* is ``"nearest"``, the one fill there is."""
    return t.choice(key, (FILL_NEAREST,)) == FILL_NEAREST


def _obvod_tables(
    t: _Fields, where: str
) -> tuple[dict[int, int], tuple[Rule, ...], dict[int, tuple[int, ...]]]:
    """Return the seats, rules and okrsky of the obvody of rule set *t*."""
    seats, rules, okrsky = {}, [], {}
    for key, entry in t.get("obvod", dict, required=True).items():
        if not _NUMBER.fullmatch(key):
            raise t.error(f"obvod.{key}", "obvod number must be a positive integer")
        number = int(key)
        o = _Fields(entry, f"{where}.obvod.{key}")
        seats[number] = o.get("seats", int, required=True)
        if seats[number] <= 0:
            raise o.error("seats", "must be positive")
        listed = o.get("rules", list, required=True)
        if not listed:
            raise o.error("rules", "must not be empty")
        rules += [
            _rule(number, r, f"{o.where}.rules[{i}]") for i, r in enumerate(listed)
        ]
        listed_okrsky = o.get("okrsky", list)
        if listed_okrsky is not None:
            if not listed_okrsky or not all(
                isinstance(k, int) and not isinstance(k, bool) and k > 0
                for k in listed_okrsky
            ):
                raise o.error("okrsky", "must list positive okrsok numbers")
            okrsky[number] = tuple(listed_okrsky)
        o.done()
    if sorted(seats) != list(range(1, len(seats) + 1)):
        raise t.error("obvod", f"must be numbered 1..{len(seats)} without gaps")
    if sum(r.rest for r in rules) > 1:
        raise t.error("obvod", "more than one rule is the rest")
    return dict(sorted(seats.items())), tuple(rules), dict(sorted(okrsky.items()))


def _check_numbering(
    t: _Fields, seats: Mapping[int, int], okrsky: Mapping[int, tuple[int, ...]]
) -> None:
    """Fail unless the okrsky of every obvod or none are listed, numbered 1..N."""
    if okrsky and set(okrsky) != set(seats):
        raise t.error("obvod", "the okrsky must be listed in every obvod or in none")
    numbers = sorted(k for ks in okrsky.values() for k in ks)
    if numbers != list(range(1, len(numbers) + 1)):
        raise t.error(
            "obvod", f"the okrsky must be numbered 1..{len(numbers)}, each in one obvod"
        )


def _okrsok_rules(
    t: _Fields,
    where: str,
    seats: Mapping[int, int],
    okrsky: Mapping[int, tuple[int, ...]],
) -> tuple[tuple[Rule, ...], tuple[int, ...]]:
    """Return the okrsok rules of rule set *t* and its okrsky without addresses.

    Checks the okrsky of its obvody; see the module doc.
    """
    _check_numbering(t, seats, okrsky)
    obvod_of = {k: o for o, ks in okrsky.items() for k in ks}
    tables = t.get("okrsok", dict) or {}
    for key in tables:
        if not _NUMBER.fullmatch(key) or int(key) not in obvod_of:
            raise t.error(f"okrsok.{key}", "is no okrsok of the obvody")
    addressless = tuple(
        sorted(
            int(k)
            for k, e in tables.items()
            if isinstance(e, Mapping) and e.get("addressless")
        )
    )
    mapped = {o: [k for k in ks if k not in addressless] for o, ks in okrsky.items()}
    rules: list[Rule] = []
    for key, entry in tables.items():
        rules += _okrsok_table(t, where, key, entry, mapped[obvod_of[int(key)]])
    shared = {k for ks in mapped.values() if len(ks) > 1 for k in ks}
    missing = sorted(shared - {r.unit for r in rules})
    if rules and missing:
        raise t.error(
            "okrsok",
            f"okrsky {', '.join(map(str, missing))} share an obvod but have no rules",
        )
    rests = Counter(obvod_of[r.unit] for r in rules if r.rest)
    if any(n > 1 for n in rests.values()):
        raise t.error("okrsok", "more than one rule is the rest of an obvod")
    return tuple(sorted(rules, key=lambda r: r.unit)), addressless


def _okrsok_table(
    t: _Fields, where: str, key: str, entry: object, mapped: Sequence[int]
) -> list[Rule]:
    """Return the rules of table ``okrsok.<key>``.

    *mapped* are the okrsky with addresses of its obvod.
    """
    o = _Fields(entry, f"{where}.okrsok.{key}")
    if o.get("addressless", bool):
        o.done()
        if not mapped:
            raise t.error(f"okrsok.{key}", "its obvod needs an okrsok with addresses")
        return []
    if len(mapped) == 1:
        # An empty table only numbers it, as an okrsky file must.
        if entry:
            raise t.error(f"okrsok.{key}", "is alone in its obvod: it has no rules")
        return []
    listed = o.get("rules", list, required=True)
    if not listed:
        raise o.error("rules", "must not be empty")
    o.done()
    return [
        _rule(int(key), r, f"{o.where}.rules[{i}]", OKRSOK)
        for i, r in enumerate(listed)
    ]


def _check_estimated(rules: RuleSet, t: _Fields) -> None:
    """Fail unless *rules* has a note if estimated, and near rules only then."""
    if rules.estimated and not rules.note:
        raise t.error("estimated", "an estimated rule set needs a note saying how")
    if not rules.estimated and any(r.near for r in (*rules.rules, *rules.okrsok_rules)):
        raise t.error("obvod", "near rules are only for an estimated rule set")


def _check_origin(rules: RuleSet, t: _Fields) -> None:
    """Fail unless rules or okrsky of another vote say so, and come from one."""
    if rules.reused and not rules.note:
        raise t.error("reused", "a reused rule set needs a note saying why")
    if (rules.okrsky_reused or rules.okrsky_referendum) and not rules.okrsky_note:
        raise t.error("okrsky_note", "okrsky of another vote need a note saying why")
    if rules.reused and rules.adoption:
        raise t.error("adopted", "a rule set is reused or adopted, not both")
    others = [rules.okrsky_reused, rules.okrsky_referendum, rules.okrsky_adoption]
    if sum(x is not None for x in others) > 1:
        raise t.error(
            "okrsky_referendum",
            "okrsky are reused, adopted or a referendum's, only one of them",
        )


def _check_supplement(rules: RuleSet, t: _Fields) -> None:
    """Fail unless rules from a later source are marked, beside the documents' own.

    Marked rules need their level's supplement, and a supplement needs both
    the rules it gave and rules of the documents: it fills them in, it does
    not stand in for them (as a reused or adopted rule set, which has no
    document of its own, does).
    """
    levels = (
        ("", rules.supplement, rules.rules, rules.reused or rules.adoption),
        (
            "okrsky_",
            rules.okrsky_supplement,
            rules.okrsok_rules,
            rules.okrsky_reused or rules.okrsky_adoption,
        ),
    )
    for prefix, supplement, listed, reused in levels:
        key = f"{prefix}supplemented"
        marked = sum(r.supplemented for r in listed)
        if supplement is None:
            if marked:
                raise t.error(key, "missing: rules are marked supplemented")
            continue
        if reused:
            raise t.error(key, "is for documents of its own, not rules of another vote")
        if not marked or marked == len(listed):
            raise t.error(
                key,
                "mark the rules from the later source and keep the documents'"
                " own: it fills them in, it does not stand in for them",
            )
    if rules.supplement and rules.supplement.source == LATER_REFERENDUM:
        raise t.error("supplemented_from", "a referendum sets no council obvody")


def _document(data: object, where: str) -> Document:
    t = _Fields(data, where)
    url = t.text("url", required=True) or ""
    if not url.startswith(("https://", "http://")):
        raise t.error("url", "must be an absolute http(s) URL")
    sha256 = t.text("sha256", required=True) or ""
    if not _SHA256.fullmatch(sha256):
        raise t.error("sha256", "must be 64 lowercase hex digits")
    out = Document(url, sha256, t.text("title", required=True) or "")
    t.done()
    return out


def _rule(unit: int, data: object, where: str, level: str = OBVOD) -> Rule:
    t = _Fields(data, where)
    rest = t.get("rest", bool)
    if rest is False:
        raise t.error("rest", "must be true, or left out")
    rule = Rule(
        unit,
        street=t.text("street"),
        part=t.text("part"),
        ku=t.text("ku"),
        rest=bool(rest),
        near=_point(t),
        numbers=t.text("numbers"),
        parity=t.choice("parity", PARITIES),
        excluded=t.text("except"),
        by=t.choice("by", (ORIENTACNE, SUPISNE)),
        written=t.text("written"),
        inferred=bool(t.get("inferred", bool)),
        note=t.text("note"),
        supplemented=bool(t.get("supplemented", bool)),
        level=level,
    )
    t.done()
    problem = _rule_problem(rule)
    if problem:
        raise ObvodyError(f"{where}: {problem}")
    for key, text in (("numbers", rule.numbers), ("except", rule.excluded)):
        if text is not None:
            try:
                parse_numbers(text)
            except ValueError as e:
                raise t.error(key, str(e)) from None
    return rule


def _point(t: _Fields) -> tuple[float, float] | None:
    """Return the ``near`` point of rule *t*, or None."""
    value = t.get("near", list)
    if value is None:
        return None
    if (
        len(value) != _LONLAT
        or not all(
            isinstance(v, int | float) and not isinstance(v, bool) for v in value
        )
        or not (_EXTENT[0] <= value[0] <= _EXTENT[2])
        or not (_EXTENT[1] <= value[1] <= _EXTENT[3])
    ):
        raise t.error("near", "must be [longitude, latitude] in Slovakia")
    return (float(value[0]), float(value[1]))


def _rule_problem(rule: Rule) -> str | None:
    """Return what makes the combination of keys of *rule* invalid."""
    if rule.rest and any((rule.street, rule.part, rule.ku, rule.near, rule.numbered)):
        return "rest = true takes no street, part, k.ú., near or numbers"
    if rule.ku and any((rule.street, rule.part, rule.near, rule.numbered)):
        return "a k.ú. rule takes no street, part, near or numbers"
    if rule.near and any((rule.street, rule.numbered)):
        return "a near rule takes no street or numbers"
    if not any((rule.rest, rule.street, rule.part, rule.ku, rule.near, rule.numbers)):
        return "selects nothing: give a street, part, ku, near, numbers or rest = true"
    if rule.by and not rule.numbered:
        return "by is for numbers"
    if rule.written and not rule.street:
        return "written is for street rules"
    if rule.inferred and not rule.note:
        return "an inferred rule needs a note saying why"
    return None


# --- house numbers -------------------------------------------------------------

NumberItem = tuple[int, int | None, str]
"""From, to (None: no end), letter ("" any); a single house: from = to."""


@functools.cache
def parse_numbers(text: str) -> tuple[NumberItem, ...]:
    """Return the items of a ``numbers`` or ``except`` value; see the module doc.

    Raises ValueError naming the item that is not a number or range.
    """
    items = []
    for raw in text.translate(_DASHES).split(","):
        item = raw.strip().casefold()
        m = _ITEM.fullmatch(item)
        if not m:
            raise ValueError(
                f"{raw.strip()!r} is not a number like 12, 12A, 1-35 or 50-"
            )
        low, letter, dash, high = m.groups()
        if dash and letter:
            raise ValueError(f"{raw.strip()!r}: a range takes no letter")
        end = (int(high) if high else None) if dash else int(low)
        if end is not None and end < int(low):
            raise ValueError(f"{raw.strip()!r} runs backwards")
        items.append((int(low), end, letter))
    return tuple(items)


def house(number: str) -> tuple[int, str] | None:
    """Return a súpisné or orientačné číslo as (number, letter), None if not one."""
    m = _HOUSE.fullmatch(number.strip().casefold())
    return (int(m[1]), m[2]) if m else None


def _in(items: Sequence[NumberItem], n: int, letter: str) -> int | None:
    """Return LETTER or NUMBERS where *items* hold the house, else None."""
    level = None
    for low, high, want in items:
        if want:
            if (n, letter) == (low, want):
                return LETTER
        elif low <= n and (high is None or n <= high):
            level = NUMBERS
    return level


def number_level(rule: Rule, supisne: str, orientacne: str) -> int | None:
    """Return the level at which the numbers of *rule* select a house, or None."""
    number = house(orientacne if rule.kind == ORIENTACNE else supisne)
    if number is None:
        return None
    n, letter = number
    if rule.excluded and _in(parse_numbers(rule.excluded), n, letter) is not None:
        return None
    if rule.parity and n % 2 != (1 if rule.parity == "odd" else 0):
        return None
    if not rule.numbers:
        return NUMBERS
    return _in(parse_numbers(rule.numbers), n, letter)


# --- assignment ----------------------------------------------------------------


class Place(NamedTuple):
    """An address as the rules see it."""

    street: str
    """"" where the address has none."""
    part: str
    supisne: str
    orientacne: str


@dataclass
class ObecPlaces:
    """The addresses of an obec with several council obvody, for its rules."""

    places: list[Place]
    points: np.ndarray
    """n × 2: longitude, latitude in 1/:data:`POINT_SCALE` degree; NaN where
    none."""
    kus: list[str | None]
    """Per address the name of the k.ú. its point is in."""
    ku_names: list[str]
    """Every k.ú. of the obec."""
    groups: list[tuple[tuple[str, str], int]] = field(default_factory=list)
    """The groups the places come from, in order, with their house counts."""

    def planar(self) -> np.ndarray:
        """Return the points in a plane, for nearness within one obec."""
        return self.points * _PLANAR

    def content(self) -> dict[str, Any]:
        """Return the content of its file; see :func:`write_places`."""
        return {
            "kus": self.ku_names,
            "addresses": [
                [
                    *p,
                    *(None if np.isnan(c) else int(c) for c in xy),
                    ku,
                ]
                for p, xy, ku in zip(self.places, self.points, self.kus, strict=True)
            ],
        }


def write_places(places: Mapping[str, ObecPlaces], directory: Path) -> None:
    """Replace *directory* with one file per obec of *places*.

    ``<obec>.json`` (JSON, compact)::

        {
            kus: [name, ...],
            addresses: [[street, part, supisne, orientacne, lon, lat, ku], ...],
        }

    ``street`` is ``""`` where the address has none; ``lon``, ``lat`` in
    1/100,000 degree, null without a point; ``ku`` is null where the point
    is in none of the obec's k.ú. Written by ``ems addresses`` into
    ``data/build/<election day>/obvod-addresses/``.
    """
    with output.replacing(directory) as tmp:
        for code, p in places.items():
            (tmp / f"{code}.json").write_bytes(output.to_json(p.content()))


def load_places(path: Path) -> ObecPlaces:
    """Read a file :func:`write_places` wrote."""
    content = json.loads(path.read_bytes())
    rows = content["addresses"]
    return ObecPlaces(
        [Place(*r[:4]) for r in rows],
        np.array(
            [[np.nan if v is None else v for v in r[4:6]] for r in rows], dtype=float
        ).reshape(-1, 2),
        [r[6] for r in rows],
        content["kus"],
    )


@dataclass
class Assignment:
    """The obvod (or okrsok) of every address of an obec, and what went wrong."""

    units: list[int]
    """Per address its obvod (or okrsok), 0 where it has none."""
    rules: list[Rule | None]
    """Per address the rule that decided, None where none did."""
    filled: list[int] = field(default_factory=list)
    """Addresses placed by ``fill``."""
    unassigned: list[int] = field(default_factory=list)
    conflicts: dict[int, tuple[Rule, ...]] = field(default_factory=dict)
    """Address → rules of one level for different units that select it."""
    unused: list[Rule] = field(default_factory=list)
    """Rules that decide no address."""
    level: str = OBVOD
    """What :attr:`units` are: :data:`OBVOD` or :data:`OKRSOK`."""
    elsewhere: list[tuple[Rule, tuple[int, ...]]] = field(default_factory=list)
    """Okrsok rules that select addresses only of other obvody than their
    okrsok's, with those obvody (:func:`assign_okrsky`)."""

    def problems(self, places: Sequence[Place]) -> list[str]:
        """Return why the assignment fails.

        Addresses in no unit or in two, okrsok rules that select addresses
        of another obvod only.
        """
        out = []
        plural = _PLURAL[self.level]
        if self.unassigned:
            groups = Counter(_where(places[i]) for i in self.unassigned)
            out.append(
                f"{len(self.unassigned):,} addresses in no {self.level}, in "
                + ", ".join(f"{g} ({n})" for g, n in groups.most_common(_SHOWN))
                + (f" and {len(groups) - _SHOWN} more" if len(groups) > _SHOWN else "")
            )
        if self.conflicts:
            pairs = Counter(
                " vs ".join(r.describe() for r in rules)
                for rules in self.conflicts.values()
            )
            out.append(
                f"{len(self.conflicts):,} addresses selected for two {plural} by: "
                + "; ".join(f"{p} ({n})" for p, n in pairs.most_common(_SHOWN))
            )
        out += [
            f"{r.describe()}: selects addresses only of obvod "
            + ", ".join(map(str, obvody))
            + ", not of its okrsok's"
            for r, obvody in self.elsewhere
        ]
        return out


def _where(place: Place) -> str:
    return place.street or f"part {place.part}"


def assign(
    rules: RuleSet,
    places: Sequence[Place],
    kus: Sequence[str | None] | None = None,
    points: np.ndarray | None = None,
) -> Assignment:
    """Return the obvod of each of *places*, the addresses of the obec.

    *kus* gives each address's k.ú. (by name; None outside any or without a
    point), needed where a rule names a k.ú. *points* (n × 2, NaN where none)
    are :meth:`ObecPlaces.planar`, for ``fill`` and ``near`` rules.
    """
    return _assign(rules.rules, rules.fill, OBVOD, places, kus, points)


def assign_okrsky(
    rules: RuleSet,
    places: Sequence[Place],
    obvody: Sequence[int],
    kus: Sequence[str | None] | None = None,
    points: np.ndarray | None = None,
) -> Assignment:
    """Return the okrsok of each of *places*, in obvod *obvody* (:func:`assign`).

    An okrsok alone in its obvod takes all its addresses; the okrsky of an
    obvod with several share its addresses by their rules, which see only
    those. *kus* and *points* are as for :func:`assign`. Needs
    :attr:`RuleSet.okrsok_areas`.
    """
    out = Assignment([0] * len(places), [None] * len(places), level=OKRSOK)
    rows_of: dict[int, list[int]] = defaultdict(list)
    for i, o in enumerate(obvody):
        rows_of[o].append(i)
    for obvod, okrsky in rules.mapped.items():
        rows = rows_of.get(obvod, [])
        if len(okrsky) == 1:
            for i in rows:
                out.units[i] = okrsky[0]
            continue
        sub = _assign(
            [r for r in rules.okrsok_rules if r.unit in okrsky],
            rules.okrsky_fill,
            OKRSOK,
            [places[i] for i in rows],
            [kus[i] for i in rows] if kus is not None else None,
            points[rows] if points is not None else None,
        )
        for j, i in enumerate(rows):
            out.units[i], out.rules[i] = sub.units[j], sub.rules[j]
        out.filled += [rows[j] for j in sub.filled]
        out.unassigned += [rows[j] for j in sub.unassigned]
        out.conflicts |= {rows[j]: c for j, c in sub.conflicts.items()}
        out.unused += sub.unused
    out.filled.sort()
    out.unassigned.sort()
    obvod_of = rules.okrsok_obvod
    for rule in out.unused:
        hit = {
            obvody[i]
            for i, place in enumerate(places)
            if _level(rule, place, kus[i] if kus is not None else None, None)
            is not None
        }
        if hit and obvod_of[rule.unit] not in hit:
            out.elsewhere.append((rule, tuple(sorted(hit))))
    return out


def _assign(
    rules: Sequence[Rule],
    fill: bool,
    level: str,
    places: Sequence[Place],
    kus: Sequence[str | None] | None,
    points: np.ndarray | None,
) -> Assignment:
    """Return the unit of each of *places* by *rules* (see :func:`assign`)."""
    index = _RuleIndex(rules)
    order = list(rules)
    out = Assignment([0] * len(places), [None] * len(places), level=level)
    used: set[int] = set()
    for i, place in enumerate(places):
        ku = kus[i] if kus is not None else None
        best: list[Rule] = []
        best_level = len(LEVELS)
        candidates = index.candidates(place)
        nearest = _nearest(candidates, place, points[i] if points is not None else None)
        for rule in candidates:
            precedence = _level(rule, place, ku, nearest)
            if precedence is None or precedence > best_level:
                continue
            if precedence < best_level:
                best, best_level = [], precedence
            best.append(rule)
        if not best:
            out.unassigned.append(i)
            continue
        used.update(id(r) for r in best)
        if len({r.unit for r in best}) > 1:
            out.conflicts[i] = tuple(sorted(set(best), key=order.index))
            continue
        out.units[i] = best[0].unit
        out.rules[i] = best[0]
    out.unused = [r for r in rules if id(r) not in used]
    if fill and out.unassigned:
        _fill(out, places, points)
    return out


# Names repeat over the addresses of an obec; the rules compare them often.
_key = functools.cache(search_key)


class _RuleIndex:
    """The rules of a set by what they select, to try only those that may."""

    def __init__(self, rules: Sequence[Rule]) -> None:
        self.streets: dict[str, list[Rule]] = defaultdict(list)
        self.parts: dict[str, list[Rule]] = defaultdict(list)
        self.other: list[Rule] = []
        for r in rules:
            if r.street is not None:
                self.streets[search_key(r.street)].append(r)
            elif r.part is not None:
                self.parts[search_key(r.part)].append(r)
            else:
                self.other.append(r)

    def candidates(self, place: Place) -> list[Rule]:
        """Return the rules that may select *place*.

        Those of its street and of its part, and the ones by k.ú., numbers
        alone or the rest.
        """
        return [
            *self.streets.get(_key(place.street), ()),
            *self.parts.get(_key(place.part), ()),
            *self.other,
        ]


def _nearest(
    rules: Sequence[Rule], place: Place, point: np.ndarray | None
) -> Rule | None:
    """Return the ``near`` rule of *rules* that selects *place* at *point*.

    That is the one nearest to *point* (planar, see :meth:`ObecPlaces.planar`)
    of those whose part, if any, is the place's; None without a point.
    """
    near = [
        r
        for r in rules
        if r.near is not None and (r.part is None or _key(r.part) == _key(place.part))
    ]
    if not near or point is None or np.isnan(point).any():
        return None
    return min(
        near,
        key=lambda r: float(
            np.hypot(*(np.asarray(r.near) * POINT_SCALE * _PLANAR - point))
        ),
    )


def _level(
    rule: Rule, place: Place, ku: str | None, nearest: Rule | None
) -> int | None:
    """Return the level at which *rule* selects *place*, or None.

    *nearest* is the ``near`` rule that selects it (:func:`_nearest`).
    """
    if rule.rest:
        return REST
    if rule.ku is not None:
        return KU if ku is not None and _key(ku) == _key(rule.ku) else None
    if rule.near is not None:
        return NEAR if rule is nearest else None
    if rule.street is not None and _key(rule.street) != _key(place.street):
        return None
    if rule.part is not None and _key(rule.part) != _key(place.part):
        return None
    if rule.numbered:
        return number_level(rule, place.supisne, place.orientacne)
    return STREET if rule.street is not None else PART


def _fill(out: Assignment, places: Sequence[Place], points: np.ndarray | None) -> None:
    """Place the unassigned addresses by the nearest placed one (see the doc)."""
    placed = np.array([o != 0 for o in out.units])
    located = (
        ~np.any(np.isnan(points), axis=1)
        if points is not None
        else np.zeros(len(places), dtype=bool)
    )
    sources = np.flatnonzero(placed & located)
    # Without a point: the unit most of its street (or else its part) got.
    by_group: dict[tuple[str, str], Counter[int]] = defaultdict(Counter)
    by_part: dict[str, Counter[int]] = defaultdict(Counter)
    for i in np.flatnonzero(placed).tolist():
        by_group[(places[i].street, places[i].part)][out.units[i]] += 1
        by_part[places[i].part][out.units[i]] += 1
    # The nearest placed address with a point, of each located one left.
    nearest: dict[int, int] = {}
    if points is not None and len(sources):
        asked = np.array([i for i in out.unassigned if located[i]], dtype=int)
        found_in, found = shapely.STRtree(
            shapely.points(points[sources])
        ).query_nearest(shapely.points(points[asked]), all_matches=False)
        nearest = dict(
            zip(asked[found_in].tolist(), sources[found].tolist(), strict=True)
        )
    left = []
    for i in out.unassigned:
        unit = 0
        if i in nearest:
            unit = out.units[nearest[i]]
        else:
            p = places[i]
            c = by_group.get((p.street, p.part)) or by_part.get(p.part)
            if c:
                unit = min(c, key=lambda o: (-c[o], o))
        if unit:
            out.units[i] = unit
            out.filled.append(i)
        else:
            left.append(i)
    out.unassigned = left


# --- names ---------------------------------------------------------------------


def same_name(written: str, name: str) -> bool:
    """Return whether *written* reads as the street *name*.

    Words compare like the search does; a word may be abbreviated to its
    start (``gen.``, ``M. R.``, ``nám.``; the last word only with its dot),
    ``Čs.`` and ``Čsl.`` are ``Československ…``, first names may be left
    out, and ``ulica`` may be added or dropped: ``M. R. Štefánika`` is
    ``Milana Rastislava Štefánika``, ``Hollého`` is ``Jána Hollého``,
    ``Hlavné nám.`` is ``Hlavné námestie``.
    """
    a, b = _words(written), _words(name)
    if not a or not b:
        return a == b
    (p, p_short), (q, q_short) = a[-1], b[-1]
    return all(
        x.startswith(y) or y.startswith(x)
        for (x, _), (y, _) in zip(reversed(a), reversed(b), strict=False)
    ) and (p == q or (p_short and q.startswith(p)) or (q_short and p.startswith(q)))


def _words(name: str) -> list[tuple[str, bool]]:
    """Return the words of street *name* as compared, each with whether it ends in a dot."""
    out = []
    for word in _WORD.findall(name):
        key = search_key(word)
        if key not in _FILLER:
            out.append((_ABBREVIATIONS.get(key, key), word.endswith(".")))
    return out


def name_problems(
    rules: RuleSet,
    streets: Sequence[str],
    parts: Sequence[str],
    kus: Sequence[str],
) -> list[str]:
    """Return the rules naming a street, part or k.ú. the obec lacks.

    *streets*, *parts* and *kus* are the names the obec has, as the address
    register and ZBGIS write them. A ``written`` name that does not read as
    its street (:func:`same_name`) needs a note.
    """
    known = {
        "street": {search_key(s) for s in streets},
        "part": {search_key(p) for p in parts},
        "k.ú.": {search_key(k) for k in kus},
    }
    out = []
    for r in (*rules.rules, *rules.okrsok_rules):
        for kind, name in (("street", r.street), ("part", r.part), ("k.ú.", r.ku)):
            if name is not None and search_key(name) not in known[kind]:
                out.append(f"{r.describe()}: the obec has no {kind} {name!r}")
        if r.street and r.written and not r.note and not same_name(r.written, r.street):
            out.append(
                f"{r.describe()}: written {r.written!r} does not read as"
                f" {r.street!r}; a note must say why they are the same street"
            )
    return out


# --- writing -------------------------------------------------------------------


def _toml_string(value: str) -> str:
    # A JSON string is a valid TOML basic string.
    return json.dumps(value, ensure_ascii=False)


def _toml_rule(r: Rule) -> str:
    """Return rule *r* as a TOML inline table."""
    fields = []
    if r.near:
        fields.append(f"near = [{r.near[0]}, {r.near[1]}]")
    if r.rest:
        fields.append("rest = true")
    fields += [
        f"{key} = {_toml_string(value)}"
        for key, value in (
            ("street", r.street),
            ("part", r.part),
            ("ku", r.ku),
            ("numbers", r.numbers),
            ("parity", r.parity),
            ("except", r.excluded),
            ("by", r.by),
            ("written", r.written),
            ("note", r.note),
        )
        if value is not None
    ]
    if r.inferred:
        fields.append("inferred = true")
    if r.supplemented:
        fields.append("supplemented = true")
    return f"{{{', '.join(fields)}}}"


def _toml_rules(rules: Iterable[Rule]) -> list[str]:
    """Return the lines of a ``rules`` array of *rules*."""
    return ["rules = [", *(f"  {_toml_rule(r)}," for r in rules), "]"]


def _toml_dating(prefix: str, dating: Dating | None) -> list[tuple[str, str | None]]:
    """Return the ``<prefix>date_approximate`` keys of *dating*, if one."""
    if dating is None:
        return []
    return [
        (f"{prefix}date_approximate", _toml_string(dating.by)),
        (f"{prefix}date_seen", dating.seen.isoformat() if dating.seen else None),
        (f"{prefix}date_basis", _toml_string(dating.basis)),
    ]


def _toml_supplement(
    prefix: str, supplement: Supplement | None
) -> list[tuple[str, str | None]]:
    """Return the ``<prefix>supplemented`` keys of *supplement*, if one."""
    if supplement is None:
        return []
    return [
        (f"{prefix}supplemented", supplement.day.isoformat()),
        (f"{prefix}supplemented_from", _toml_string(supplement.source)),
        (f"{prefix}supplement_basis", _toml_string(supplement.basis)),
    ]


def _toml_adoption(prefix: str, adoption: Adoption | None) -> list[tuple[str, str]]:
    """Return the ``<prefix>adopted`` keys of *adoption*, if one."""
    if adoption is None:
        return []
    return [
        (f"{prefix}adopted", adoption.day.isoformat()),
        (f"{prefix}adopted_basis", _toml_string(adoption.basis)),
    ]


def dump(rules: RuleSet, header: Sequence[str] = ()) -> str:
    """Return *rules* as the TOML of its file, *header* as comments.

    A :attr:`RuleSet.whole` rule set as ``okrsky/<obec>.toml``, without its
    one obvod.
    """
    s = _toml_string
    lines = [f"# {h}" for h in header]
    lines += [f"obec = {s(rules.obec)}", f"name = {s(rules.name)}"]
    keys = (
        ("date", rules.date and rules.date.isoformat()),
        *_toml_dating("", rules.dating),
        ("fill", rules.fill and s(FILL_NEAREST)),
        ("note", rules.note and s(rules.note)),
        ("estimated", rules.estimated and "true"),
        ("reused", rules.reused and rules.reused.isoformat()),
        *_toml_adoption("", rules.adoption),
        *_toml_supplement("", rules.supplement),
        ("okrsky_date", rules.okrsky_date and rules.okrsky_date.isoformat()),
        ("okrsky_fill", rules.okrsky_fill and s(FILL_NEAREST)),
        ("okrsky_note", rules.okrsky_note and s(rules.okrsky_note)),
        ("okrsky_reused", rules.okrsky_reused and rules.okrsky_reused.isoformat()),
        *_toml_adoption("okrsky_", rules.okrsky_adoption),
        (
            "okrsky_referendum",
            rules.okrsky_referendum and rules.okrsky_referendum.isoformat(),
        ),
        *_toml_dating("okrsky_", rules.okrsky_dating),
        *_toml_supplement("okrsky_", rules.okrsky_supplement),
    )
    lines += [f"{key} = {value}" for key, value in keys if value]
    for d in rules.documents:
        lines += ["", "[[document]]", f"url = {s(d.url)}", f"sha256 = {s(d.sha256)}"]
        lines.append(f"title = {s(d.title)}")
    if not rules.whole:
        for number, seats in rules.seats.items():
            lines += ["", f"[obvod.{number}]", f"seats = {seats}"]
            if number in rules.okrsky:
                lines.append(f"okrsky = [{', '.join(map(str, rules.okrsky[number]))}]")
            lines += _toml_rules(r for r in rules.rules if r.unit == number)
    with_table = {r.unit for r in rules.okrsok_rules} | set(rules.addressless)
    # An okrsky file numbers every okrsok, the one alone with the addresses by
    # an empty table.
    for number in rules.okrsky[1] if rules.whole else sorted(with_table):
        lines += ["", f"[okrsok.{number}]"]
        if number in rules.addressless:
            lines.append("addressless = true")
        elif number in with_table:
            lines += _toml_rules(r for r in rules.okrsok_rules if r.unit == number)
    return "\n".join(lines) + "\n"
