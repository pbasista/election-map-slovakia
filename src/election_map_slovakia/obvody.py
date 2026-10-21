"""Constituency (obvod) membership: by whole municipalities, or by address.

Regional council obvody, and the city council obvody of Bratislava and
Košice, consist of whole obce or city districts. Their membership is
transcribed from the official decisions into
``data/curated/obvody/<area>.toml`` (form: :func:`election_map_slovakia.config.load_obvody`);
:func:`resolve` checks it against the municipalities of the area.

An obec (or city district) that elects its council in several obvody sets
them in a resolution of its council, by streets and house numbers, parts of
the obec (časti obce) or cadastral areas (katastrálne územia, k.ú.). Its rule
set, ``data/curated/obvody/oz/<obec>.toml`` (written by ``ems job ingest``
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
rule may have a ``note``.

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
"""

from __future__ import annotations

import datetime as dt
import functools
import json
import re
import tomllib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
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
ORIENTACNE = "orientacne"
SUPISNE = "supisne"
PARITIES = ("odd", "even")
FILL_NEAREST = "nearest"
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
_OBEC = re.compile(r"\d{6}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ITEM = re.compile(r"(\d+)\s*([^\W\d_]*)(?:\s*(-)\s*(\d*))?")
_HOUSE = re.compile(r"0*(\d+)\s*([^\W\d_]*)")
_DASHES = str.maketrans("\u2010\u2011\u2012\u2013\u2014\u2212", "------")
# Words a document may add to or drop from a street name.
_FILLER = frozenset({"ulica", "ul"})
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
class Rule:
    """One rule of a rule set; see the module doc."""

    obvod: int
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

    @property
    def numbered(self) -> bool:
        """Return whether the rule narrows its selection to house numbers."""
        return bool(self.numbers or self.parity or self.excluded)

    @property
    def kind(self) -> str:
        """Return which number of a house the rule counts."""
        return self.by or (ORIENTACNE if self.street else SUPISNE)

    def describe(self) -> str:
        """Return the rule as one line, for reports."""
        what = (
            "the rest"
            if self.rest
            else f"k.ú. {self.ku}"
            if self.ku
            else " in ".join(
                x
                for x in (
                    self.street,
                    self.near and f"near {self.near[0]}, {self.near[1]}",
                    self.part and f"part {self.part}",
                )
                if x is not None
            )
            or "the obec"
        )
        if self.numbered:
            numbers = " ".join(
                x
                for x in (
                    self.numbers,
                    self.parity,
                    self.excluded and f"except {self.excluded}",
                )
                if x
            )
            what += f" {numbers} ({self.kind})"
        return f"obvod {self.obvod}: {what}"


@dataclass(frozen=True)
class RuleSet:
    """``data/curated/obvody/oz/<obec>.toml``; see the module doc."""

    obec: str
    name: str
    date: dt.date | None
    """The council's decision; None where no published document states it."""
    documents: tuple[Document, ...]
    seats: dict[int, int]
    """Obvod number → councillors elected there; numbered 1..N."""
    rules: tuple[Rule, ...]
    fill: bool = False
    """Whether addresses no rule selects take the nearest one's obvod."""
    note: str | None = None
    estimated: bool = False
    """Whether the rules are a guess that no document states."""

    @property
    def by_ku(self) -> bool:
        """Return whether the obvody are unions of whole k.ú."""
        return all(r.ku or r.rest for r in self.rules)


def rules_path(curated: Path, obec: str) -> Path:
    """Return the path of the rule set of *obec* below ``data/curated/``."""
    return curated / DIRECTORY / RULES_DIRECTORY / f"{obec}.toml"


def load_rule_sets(curated: Path) -> dict[str, RuleSet]:
    """Return obec → rule set, of every rule set in ``data/curated/``."""
    out = {}
    for path in sorted((curated / DIRECTORY / RULES_DIRECTORY).glob("*.toml")):
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ObvodyError(f"{path}: invalid TOML: {e}") from e
        rules = rule_set(data, str(path))
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
    obec = t.text("obec", required=True)
    if not _OBEC.fullmatch(obec or ""):
        raise t.error("obec", "must be a 6-digit obec code")
    date = t.get("date", dt.date)
    if isinstance(date, dt.datetime):
        raise t.error("date", "must be a date without a time")
    documents = tuple(
        _document(d, f"{where}.document[{i}]")
        for i, d in enumerate(t.get("document", list, required=True))
    )
    if not documents:
        raise t.error("document", "must list the official document")
    table = t.get("obvod", dict, required=True)
    seats, rules = {}, []
    for key, entry in table.items():
        if not re.fullmatch(r"[1-9]\d*", key):
            raise t.error(f"obvod.{key}", "obvod number must be a positive integer")
        o = _Fields(entry, f"{where}.obvod.{key}")
        seats[int(key)] = o.get("seats", int, required=True)
        if seats[int(key)] <= 0:
            raise o.error("seats", "must be positive")
        listed = o.get("rules", list, required=True)
        if not listed:
            raise o.error("rules", "must not be empty")
        rules += [
            _rule(int(key), r, f"{o.where}.rules[{i}]") for i, r in enumerate(listed)
        ]
        o.done()
    if sorted(seats) != list(range(1, len(seats) + 1)):
        raise t.error("obvod", f"must be numbered 1..{len(seats)} without gaps")
    if sum(r.rest for r in rules) > 1:
        raise t.error("obvod", "more than one rule is the rest")
    fill = t.choice("fill", (FILL_NEAREST,)) == FILL_NEAREST
    out = RuleSet(
        obec or "",
        t.text("name", required=True) or "",
        date,
        documents,
        dict(sorted(seats.items())),
        tuple(rules),
        fill,
        t.text("note"),
        bool(t.get("estimated", bool)),
    )
    t.done()
    _check_estimated(out, t)
    return out


def _check_estimated(rules: RuleSet, t: _Fields) -> None:
    """Fail unless *rules* has a note if estimated, and near rules only then."""
    if rules.estimated and not rules.note:
        raise t.error("estimated", "an estimated rule set needs a note saying how")
    if not rules.estimated and any(r.near for r in rules.rules):
        raise t.error("obvod", "near rules are only for an estimated rule set")


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


def _rule(obvod: int, data: object, where: str) -> Rule:
    t = _Fields(data, where)
    rest = t.get("rest", bool)
    if rest is False:
        raise t.error("rest", "must be true, or left out")
    rule = Rule(
        obvod,
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
    ``data/build/obvod-addresses/``.
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
    """The obvod of every address of an obec, and what went wrong."""

    obvody: list[int]
    """Per address its obvod, 0 where it has none."""
    rules: list[Rule | None]
    """Per address the rule that decided, None where none did."""
    filled: list[int] = field(default_factory=list)
    """Addresses placed by ``fill``."""
    unassigned: list[int] = field(default_factory=list)
    conflicts: dict[int, tuple[Rule, ...]] = field(default_factory=dict)
    """Address → rules of one level for different obvody that select it."""
    unused: list[Rule] = field(default_factory=list)
    """Rules that decide no address."""

    def problems(self, places: Sequence[Place]) -> list[str]:
        """Return why the assignment fails: addresses in none or two obvody."""
        out = []
        if self.unassigned:
            groups = Counter(_where(places[i]) for i in self.unassigned)
            out.append(
                f"{len(self.unassigned):,} addresses in no obvod, in "
                + ", ".join(f"{g} ({n})" for g, n in groups.most_common(_SHOWN))
                + (f" and {len(groups) - _SHOWN} more" if len(groups) > _SHOWN else "")
            )
        if self.conflicts:
            pairs = Counter(
                " vs ".join(r.describe() for r in rules)
                for rules in self.conflicts.values()
            )
            out.append(
                f"{len(self.conflicts):,} addresses selected for two obvody by: "
                + "; ".join(f"{p} ({n})" for p, n in pairs.most_common(_SHOWN))
            )
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
    index = _RuleIndex(rules.rules)
    out = Assignment([0] * len(places), [None] * len(places))
    used: set[int] = set()
    for i, place in enumerate(places):
        ku = kus[i] if kus is not None else None
        best: list[Rule] = []
        best_level = len(LEVELS)
        candidates = index.candidates(place)
        nearest = _nearest(candidates, place, points[i] if points is not None else None)
        for rule in candidates:
            level = _level(rule, place, ku, nearest)
            if level is None or level > best_level:
                continue
            if level < best_level:
                best, best_level = [], level
            best.append(rule)
        if not best:
            out.unassigned.append(i)
            continue
        used.update(id(r) for r in best)
        if len({r.obvod for r in best}) > 1:
            out.conflicts[i] = tuple(sorted(set(best), key=rules.rules.index))
            continue
        out.obvody[i] = best[0].obvod
        out.rules[i] = best[0]
    out.unused = [r for r in rules.rules if id(r) not in used]
    if rules.fill and out.unassigned:
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
    if point is None or np.isnan(point).any():
        return None
    near = [
        r
        for r in rules
        if r.near is not None and (r.part is None or _key(r.part) == _key(place.part))
    ]
    if not near:
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
    placed = np.array([o != 0 for o in out.obvody])
    located = (
        ~np.any(np.isnan(points), axis=1)
        if points is not None
        else np.zeros(len(places), dtype=bool)
    )
    sources = np.flatnonzero(placed & located)
    # Without a point: the obvod most of its street (or else its part) got.
    by_group: dict[tuple[str, str], Counter[int]] = defaultdict(Counter)
    by_part: dict[str, Counter[int]] = defaultdict(Counter)
    for i in np.flatnonzero(placed).tolist():
        by_group[(places[i].street, places[i].part)][out.obvody[i]] += 1
        by_part[places[i].part][out.obvody[i]] += 1
    tree = (
        shapely.STRtree(shapely.points(points[sources]))
        if points is not None and len(sources)
        else None
    )
    left = []
    for i in out.unassigned:
        obvod = 0
        if tree is not None and points is not None and located[i]:
            nearest = tree.query_nearest(shapely.points(points[i]), all_matches=False)
            obvod = out.obvody[int(sources[int(nearest[0])])]
        else:
            p = places[i]
            c = by_group.get((p.street, p.part)) or by_part.get(p.part)
            if c:
                obvod = min(c, key=lambda o: (-c[o], o))
        if obvod:
            out.obvody[i] = obvod
            out.filled.append(i)
        else:
            left.append(i)
    out.unassigned = left


# --- names ---------------------------------------------------------------------


def same_name(written: str, name: str) -> bool:
    """Return whether *written* reads as the street *name*.

    Words compare like the search does; a word may be abbreviated to its
    start (``gen.``, ``M. R.``), first names may be left out, and ``ulica``
    may be added or dropped: ``M. R. Štefánika`` is ``Milana Rastislava
    Štefánika``, ``Hollého`` is ``Jána Hollého``.
    """
    a = [w for w in search_key(written).split() if w not in _FILLER]
    b = [w for w in search_key(name).split() if w not in _FILLER]
    if not a or not b:
        return a == b
    return (
        all(
            x.startswith(y) or y.startswith(x)
            for x, y in zip(reversed(a), reversed(b), strict=False)
        )
        and a[-1] == b[-1]
    )


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
    for r in rules.rules:
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
    pairs = [
        (k, v)
        for k, v in (
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
        if v is not None
    ]
    fields = [f"{k} = {_toml_string(v)}" for k, v in pairs]
    if r.rest:
        fields.insert(0, "rest = true")
    if r.near:
        fields.insert(0, f"near = [{r.near[0]}, {r.near[1]}]")
    if r.inferred:
        fields.append("inferred = true")
    return f"{{{', '.join(fields)}}}"


def dump(rules: RuleSet, header: Sequence[str] = ()) -> str:
    """Return *rules* as the TOML of a rule set file, *header* as comments."""
    s = _toml_string
    lines = [f"# {h}" for h in header]
    lines += [f"obec = {s(rules.obec)}", f"name = {s(rules.name)}"]
    if rules.date:
        lines.append(f"date = {rules.date.isoformat()}")
    if rules.fill:
        lines.append(f"fill = {s(FILL_NEAREST)}")
    if rules.note:
        lines.append(f"note = {s(rules.note)}")
    if rules.estimated:
        lines.append("estimated = true")
    for d in rules.documents:
        lines += ["", "[[document]]", f"url = {s(d.url)}", f"sha256 = {s(d.sha256)}"]
        lines.append(f"title = {s(d.title)}")
    for number, seats in rules.seats.items():
        lines += ["", f"[obvod.{number}]", f"seats = {seats}", "rules = ["]
        lines += [f"  {_toml_rule(r)}," for r in rules.rules if r.obvod == number]
        lines.append("]")
    return "\n".join(lines) + "\n"
