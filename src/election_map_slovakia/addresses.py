"""Turn the MV SR address register into the files of the address search.

The register lists every address with its okres, obec, part of the obec
(*časť obce*), street, súpisné and orientačné číslo and a WGS84 point. Its
municipality names are matched to obec codes like the candidate lists (by
name within the okres); Bratislava and Košice appear as their districts.
About half the addresses have no street: villages number their houses by
súpisné číslo within a part of the obec, so those are grouped by part (the
obec name where the part is empty).

Every contest but the municipal council follows from the obec (see
``geo``: ``zsk``, ``city``, ``city_obvod``). The council obvod depends on
the obec's ``council``: ``"single"`` where the obec (or city district)
elects its council in one obvod, given as ``obvod``; ``"address"`` where it
has several and its rule set (``obvody/oz/<obec>.toml`` in the election's data, see
:mod:`election_map_slovakia.obvody`) gives every address its obvod, which
must place each in exactly one of the candidate lists' obvody, or
``addresses`` fails; ``"pending"`` where it has several and no rule set yet;
``"none"`` in the obce with no council election (no candidates, a
military district, every obec but those of a by-election's councils, every
obec in a country-wide election, which has no council rule sets either).

Points farther than ``MAX_OUTSIDE`` metres outside the ZBGIS polygon of
their obec are published as missing: drawn there, a house number would
sit in a neighbouring obec and a click on it would yield that obec's
contests. All points outside their obec are reported.

Output, ``data/build/<election day>/addr/`` (JSON, compact, sorted)::

    index.json   {scale: 100000,
                  okresy:  {okres: name},
                  obce:    [[obec, name, okres, key]],   by code
                  streets: [[name, key, [obec, ...]]],   by key, then name
                  parts:   [[name, key, [obec, ...]]]}   by key, then name
    <obec>.json  {council: "single" | "address" | "pending" | "none",
                  (obvod: n),                            with "single"
                  streets: [{name, numbers, points, (obvod | obvody),
                             (okrsok | okrsky)}],
                  parts:   [{name, numbers, points, (obvod | obvody),
                             (okrsok | okrsky)}]}

``key`` is :func:`search_key` of the name; the frontend normalizes the query
the same way. ``index.json`` lists the obce that have addresses, every
street name with the obce that have it, and the parts of obce that have
addresses without a street and are named other than their obec. In an obec
file, streets and parts are sorted by key, then name; ``numbers`` holds the
display form of each house number (:func:`house_number`), sorted by
:func:`number_order`. ``points`` is flat, two integers per number:
longitude and latitude in 1/``scale`` degree (about 1 m), each the
difference from the previous located point in the file, streets first, the
first from 0; ``null, null`` where the address has no point. With
``"address"`` each street and part has ``obvod``, the council obvod of all
its houses, or ``obvody``, one per number.

Where the obec's okrsky (polling districts) are drawn, that is where its
rule set (:func:`election_map_slovakia.obvody.okrsok_rule_sets`) places
every address in one okrsok, each street and part has ``okrsok``, the
okrsok of all its houses, or ``okrsky``, one per number, numbered as the
obec numbers them; ``geo`` draws the same obce (``okrsky.drawn`` of its
index). An obec with one okrsok has neither: every address is in okrsok
1. An obec with several whose okrsky are not known by address has
neither either. A rule set that leaves an address in no okrsok or in two
is reported, its obec written without okrsky (``geo`` fails on it).

The addresses of every obec with several council obvody or several okrsky
also go to ``data/build/<election day>/obvod-addresses/<obec>.json``
(:func:`election_map_slovakia.obvody.write_places`): the input of the
``obvod-rules`` and ``okrsok-rules`` jobs, their checks and the okrsky;
with the council obvod and okrsok of each address assigned here, so that
``geo`` draws them without assigning them again.

Most of that depends on the register alone, with ZBGIS level 0 and the
overrides of the register: reading and sorting it, checking its 1.7
million points, the search index, every obec's streets and parts with
their points (:func:`obec_body`), every obec's addresses for the rules,
the outliers. That is the same for every election that reads the
register, so :func:`register` makes it once into a :class:`Register`,
cached in ``data/build/shared/addresses/<register input>/`` under a digest
of all it depends on and of the code; :func:`build` adds an election's
council and okrsky: the council fields of each obec file and the units
of each house, inserted into the cached JSON (:func:`obec_file`), and
the assignment of the obce with rule sets, each in a worker process that
reads the obec's ``obvod-addresses`` file content. The cache also keeps
every row's identifikator (:meth:`Register.houses`), which the crosswalk
of ``results`` pairs the registers of two elections by.
"""

from __future__ import annotations

import csv
import io
import pickle
import random
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import orjson
import pyproj
import shapely
from pyproj.enums import TransformDirection

from election_map_slovakia import config, geo, obvody, output, parallel, progress
from election_map_slovakia.candidates import (
    OUTPUT_FILE,
    Admin,
    Obec,
    load_admin,
    municipal_index,
    name_key,
    search_key,
)
from election_map_slovakia.contests import SELF_GOVERNMENT, parse
from election_map_slovakia.output import format_size

OUTPUT_DIR = "addr"
OUTSIDE_FILE = "addresses-outside.tsv"
COLUMNS = (
    "IDENTIFIKATOR",
    "KRAJ",
    "OKRES",
    "OBEC",
    "CAST_OBCE",
    "ULICA",
    "SUPISNE_CISLO",
    "ORIENTACNE_CISLO_CELE",
    "PSC",
    "ADRBOD_X",
    "ADRBOD_Y",
)
SCALE = obvody.POINT_SCALE
# Slovakia spans 16.83–22.57° E and 47.73–49.62° N. A point outside this box
# means the register changed its coordinate system (S-JTSK values are
# negative and in metres) or swapped the axes.
LON_RANGE = (16.5, 23.0)
LAT_RANGE = (47.5, 50.0)
STREETS = "streets"
PARTS = "parts"
SAMPLE_SIZE = 100
SAMPLE_SHOWN = 10
SAMPLE_SEED = 20261024
ADDRESS = "address"
"""``council`` of an obec whose rule set gives each address its obvod."""
OBVOD_DIR = "obvod-addresses"
"""Below an election's build directory: the addresses of the obce with
several council obvody or okrsky, as their rules see them (see
:func:`election_map_slovakia.obvody.write_places`)."""
_SEVERAL = 2
TOP = 20
# Distance classes for points outside their obec, in metres.
OUTSIDE_BINS = (1, 10, 100, 1000)
MAX_OUTSIDE = 100.0
"""Metres outside its obec polygon beyond which a point is not published."""
# Rows between two looks at how far the register is read.
_PROGRESS_ROWS = 10_000


class AddressesError(Exception):
    """The address register cannot be read or matched."""


class House(NamedTuple):
    """One address within its street or part."""

    number: str
    """Display form, :func:`house_number`."""
    order: tuple[int, str, int, str]
    point: tuple[int, int] | None
    """Longitude and latitude in 1/``SCALE`` degree."""
    part: str = ""
    """Part of the obec (the obec's name where the register gives none)."""
    supisne: str = ""
    orientacne: str = ""


Groups = dict[tuple[str, str], list[House]]
"""(``STREETS`` or ``PARTS``, name) → houses, of one obec."""


@dataclass
class Addresses:
    """The register, grouped by obec, then by street or part."""

    obce: dict[str, Groups]
    rows: int
    duplicates: int
    """Rows dropped as repeating another one in number and point."""
    ids: dict[str, list[tuple[str, tuple[str, str], str]]] = field(default_factory=dict)
    """Obec → its rows in register order, repeats included: identifikator,
    group and house number (:func:`house_number`)."""


def house_number(supisne: str, orientacne: str) -> str:
    """Return the house number as written in Slovakia: ``súpisné/orientačné``.

    Either part may be missing; the other is then written alone.
    """
    return "/".join(p for p in (supisne, orientacne) if p)


def number_order(supisne: str, orientacne: str) -> tuple[int, str, int, str]:
    """Return the sort key of a house number.

    Houses sort by the number on the building, the orientačné číslo where
    there is one, else the súpisné, numerically, then by letter suffix.
    """
    return (*_natural(orientacne or supisne), *_natural(supisne))


def _natural(number: str) -> tuple[int, str]:
    digits = len(number) - len(number.lstrip("0123456789"))
    return int(number[:digits]) if digits else -1, number[digits:]


class Row(NamedTuple):
    """A row of the register, matched to its obec."""

    identifikator: str
    """The address's id, which a later register keeps for the same address."""
    obec: str
    """Its obec code; "" for a place of ``address_skip``."""
    part: str
    """Part of the obec (the obec's name where the register gives none)."""
    street: str
    supisne: str
    orientacne: str
    x: str
    y: str
    line: int
    """Line number in the file, for messages."""

    @property
    def group(self) -> tuple[str, str]:
        """Return the street, or without one the part, the address is listed under."""
        return (STREETS, self.street) if self.street else (PARTS, self.part)


def register_rows(
    path: Path,
    admin: Admin,
    overrides: Mapping[str, str],
    skip: Collection[str] = (),
) -> Iterator[Row]:
    """Yield every row of the register; fail listing every unmatched municipality.

    *overrides* maps ``"<okres>/<obec>"`` as the register writes them to
    obec codes (``[address]`` in ``overrides.toml``); the rows of the places
    in *skip* (``address_skip``), no obec of ZBGIS, come with obec "". The
    file may start with a byte order mark (the register of 09/2022 does).
    The failure comes after the last row.
    """
    okresy = {name_key(name): code for code, (name, _) in admin.okresy.items()}
    index = municipal_index(admin)
    matched: dict[tuple[str, str], str | None] = {}
    unmatched: Counter[str] = Counter()
    # Part names repeat within an obec; one shared string per name saves
    # memory where the rows are kept.
    parts: dict[str, str] = {}
    rows = 0
    with (
        progress.stage(f"reading {path.name}", path.stat().st_size, format_size) as s,
        path.open("rb") as raw,
        io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as f,
    ):
        reader = csv.reader(f, delimiter=";")
        if tuple(next(reader, ())) != COLUMNS:
            raise AddressesError(f"{path}: header is not {';'.join(COLUMNS)}")
        for row in reader:
            rows += 1
            if not rows % _PROGRESS_ROWS:
                s.update(raw.tell())
            if len(row) != len(COLUMNS):
                raise AddressesError(f"{path}:{reader.line_num}: {len(row)} fields")
            ident, _, okres, obec, part, street, supisne, orientacne, _, x, y = row
            place = (okres, obec)
            if place not in matched:
                matched[place] = _match_place(place, overrides, skip, okresy, index)
            code = matched[place]
            if code is None:
                unmatched[f"obec {obec!r} in okres {okres!r}"] += 1
                continue
            part = part or obec
            part = parts.setdefault(part, part)
            yield Row(
                ident, code, part, street, supisne, orientacne, x, y, reader.line_num
            )
    _check_matched(unmatched, matched, overrides, skip)


def read(
    path: Path,
    admin: Admin,
    overrides: Mapping[str, str],
    skip: Collection[str] = (),
) -> Addresses:
    """Read the register (:func:`register_rows`), grouped by obec and street or part."""
    obce: dict[str, Groups] = defaultdict(lambda: defaultdict(list))
    ids: dict[str, list[tuple[str, tuple[str, str], str]]] = defaultdict(list)
    # Most house numbers repeat across streets; one shared display form,
    # sort key and string per number saves their parsing and their memory.
    numbers: dict[tuple[str, str], tuple[str, tuple[int, str, int, str], str, str]] = {}
    rows = 0
    for r in register_rows(path, admin, overrides, skip):
        rows += 1
        if not r.obec:
            # A place of address_skip, left out.
            continue
        try:
            point = _point(r.x, r.y)
        except AddressesError as e:
            raise AddressesError(f"{path}:{r.line}: {e}") from None
        number = numbers.get((r.supisne, r.orientacne))
        if number is None:
            number = numbers[(r.supisne, r.orientacne)] = (
                house_number(r.supisne, r.orientacne),
                number_order(r.supisne, r.orientacne),
                r.supisne,
                r.orientacne,
            )
        display, order, sup, ori = number
        group = r.group
        obce[r.obec][group].append(House(display, order, point, r.part, sup, ori))
        ids[r.obec].append((r.identifikator, group, display))
    with progress.stage("sorting the house numbers"):
        duplicates = _sort_unique(obce.values())
    return Addresses(
        {c: dict(g) for c, g in sorted(obce.items())}, rows, duplicates, dict(ids)
    )


def _match_place(
    place: tuple[str, str],
    overrides: Mapping[str, str],
    skip: Collection[str],
    okresy: Mapping[str, str],
    index: Mapping[tuple[str, str], str],
) -> str | None:
    """Return the obec of the register's (okres, obec) *place*.

    By override, else by name within the okres; "" for a place of *skip*,
    None for one of no obec.
    """
    okres, obec = place
    key = f"{okres}/{obec}"
    if key in overrides:
        return overrides[key]
    if key in skip:
        return ""
    return index.get((okresy.get(name_key(okres), ""), name_key(obec)))


def _check_matched(
    unmatched: Mapping[str, int],
    matched: Iterable[tuple[str, str]],
    overrides: Mapping[str, str],
    skip: Collection[str],
) -> None:
    """Fail listing the *unmatched* places and the overrides of no place."""
    errors = [f"{n:,} rows: {where}" for where, n in sorted(unmatched.items())]
    known = {f"{okres}/{obec}" for okres, obec in matched}
    errors += [
        f"unused override address {k!r}" for k in sorted(overrides.keys() - known)
    ]
    errors += [f"unused address_skip {k!r}" for k in sorted(set(skip) - known)]
    if errors:
        raise AddressesError(
            f"{len(errors)} unmatched (add them to overrides.toml [address]):\n  "
            + "\n  ".join(errors)
        )


def _point(x: str, y: str) -> tuple[int, int] | None:
    """Return the register's ``ADRBOD_X``, ``ADRBOD_Y`` in 1/``SCALE`` degree."""
    if not (x and y):
        return None
    try:
        lon, lat = float(x.replace(",", ".")), float(y.replace(",", "."))
    except ValueError:
        raise AddressesError(f"point {x};{y} is not a number pair") from None
    if not (LON_RANGE[0] < lon < LON_RANGE[1] and LAT_RANGE[0] < lat < LAT_RANGE[1]):
        raise AddressesError(
            f"point {x};{y} is not WGS84 lon/lat in Slovakia"
            " (has the coordinate system changed?)"
        )
    return round(lon * SCALE), round(lat * SCALE)


def _sort_unique(obce: Iterable[Groups]) -> int:
    """Sort the houses of every group, drop exact repeats; return their count."""
    duplicates = 0
    for groups in obce:
        for houses in groups.values():
            houses.sort(key=lambda h: (h.order, h.number, h.point or (0, 0)))
            unique = [h for i, h in enumerate(houses) if i == 0 or h != houses[i - 1]]
            duplicates += len(houses) - len(unique)
            houses[:] = unique
    return duplicates


def council_obvody(contests: Iterable[Mapping[str, Any]]) -> dict[str, list[int]]:
    """Return obec → its municipal council obvod numbers, sorted.

    Bratislava and Košice districts elect their own councils, so a district
    has its own obvody, distinct from the city council's (``oz:BA/<n>``).
    """
    numbers: dict[str, list[int]] = defaultdict(list)
    for c in contests:
        if c["kind"] == "oz":
            numbers[str(c["area"])].append(int(c["obvod"]))
    return {code: sorted(n) for code, n in sorted(numbers.items())}


def split_councils(term: Iterable[Mapping[str, Any]]) -> set[str]:
    """Return the obce whose council regular election contests *term* elect in several obvody."""
    return {code for code, n in council_obvody(term).items() if len(n) >= _SEVERAL}


def part_councils(
    contests: Iterable[Mapping[str, Any]], split: Collection[str]
) -> set[str]:
    """Return the obce whose by-election council contests may be part of more.

    Of a by-election's contests (*contests*): candidates.json does not say
    how many obvody a council has, so only obvod 1 with its ``seats`` given
    is taken for a whole council of one obvod, unless the council the
    by-election fills seats of, elected in its term, had several obvody
    (*split*, :func:`split_councils` of the term's contests); an obvod
    above 1, or one without ``seats`` (candidates in several obvody), is
    part of a larger council, its other obvody electing no one.
    """
    return {
        str(c["area"])
        for c in contests
        if c["kind"] == "oz"
        and ("seats" not in c or int(c["obvod"]) > 1 or str(c["area"]) in split)
    }


def council_parts(
    cfg: config.Config, election: config.Election, contests: Iterable[Mapping[str, Any]]
) -> set[str]:
    """Return the obce whose council contests *contests* of *election* are part of more.

    :func:`part_councils` of a by-election, by the built candidates of its
    term (:meth:`election_map_slovakia.config.Config.term`); none of any
    other election. The address files, the data index (``councils``) and
    the results (their council obvody) all go by it.
    """
    if election.kind != config.BY_ELECTION:
        return set()
    term = cfg.term(election)
    if term is None:
        return part_councils(contests, ())
    path = cfg.election_build_dir(term) / OUTPUT_FILE
    if not path.is_file():
        raise config.ConfigError(f"{path} missing; run `ems candidates` first")
    then = orjson.loads(path.read_bytes())["contests"]
    return part_councils(contests, split_councils(then))


def council_fields(
    numbers: Sequence[int], by_address: bool = False, whole: bool = True
) -> dict[str, Any]:
    """Return ``council`` (and ``obvod``) of an obec with council obvody *numbers*.

    *by_address*: the obec has a rule set giving each address its obvod.
    Not *whole*: the obvody are some of its council's (:func:`part_councils`),
    so where no rule set places the addresses, they are ``"pending"``, not
    all in the one obvod listed. See the module doc.
    """
    if len(numbers) == 1 and whole:
        return {"council": "single", "obvod": numbers[0]}
    if by_address:
        return {"council": ADDRESS}
    return {"council": "pending" if numbers else "none"}


ObvodMap = dict[tuple[str, str], list[int]]
"""Group → council obvod (or okrsok) per house, of an obec with a rule set."""


class ObecBody(NamedTuple):
    """An obec file without its council fields and units (:func:`obec_body`)."""

    data: bytes
    """JSON ``{streets: [...], parts: [...]}``, each group without ``obvod``
    and ``okrsok``."""
    groups: list[tuple[str, str]]
    """The groups in the order of the file."""
    ends: list[int]
    """Per group, the offset in :attr:`data` of the ``}`` that closes it."""


def obec_body(groups: Groups) -> ObecBody:
    """Return the streets and parts of ``<obec>.json``; see the module doc.

    The same for every election on the register: :func:`obec_file` adds
    the council fields, and the units of each house where the election
    has them, at the offsets kept.
    """
    lists: dict[str, list[bytes]] = {STREETS: [], PARTS: []}
    last = (0, 0)
    order = sorted(groups, key=lambda g: (g[0] != STREETS, search_key(g[1]), g[1]))
    for kind, name in order:
        houses = groups[(kind, name)]
        points: list[int | None] = []
        for h in houses:
            if h.point is None:
                points += [None, None]
            else:
                points += [h.point[0] - last[0], h.point[1] - last[1]]
                last = h.point
        lists[kind].append(
            output.to_json(
                {"name": name, "numbers": [h.number for h in houses], "points": points}
            )
        )
    # JSON is compositional: this is output.to_json of the dict of the lists.
    data = bytearray(b"{")
    ends: list[int] = []
    for i, kind in enumerate((STREETS, PARTS)):
        data += (b"," if i else b"") + output.to_json(kind) + b":["
        for j, group in enumerate(lists[kind]):
            data += (b"," if j else b"") + group
            ends.append(len(data) - 1)
        data += b"]"
    data += b"}"
    return ObecBody(bytes(data), order, ends)


def obec_file(
    body: ObecBody,
    council: Sequence[int],
    assigned: ObvodMap | None = None,
    okrsky: ObvodMap | None = None,
    whole: bool = True,
) -> bytes:
    """Return ``<obec>.json`` of an obec of streets and parts *body*; see the module doc.

    *council* is the obec's council obvody, from :func:`council_obvody`,
    not its *whole* council where a by-election elects part of it;
    *assigned* the obvod of each house where the obec has a rule set,
    *okrsky* the okrsok of each where its okrsky are drawn.
    """
    head = output.to_json(council_fields(council, assigned is not None, whole))
    pieces = [head[:-1], b","]
    start = 1
    if assigned is not None or okrsky is not None:
        for group, end in zip(body.groups, body.ends, strict=True):
            pieces.append(body.data[start:end])
            for one, several, given in (
                ("obvod", "obvody", assigned),
                ("okrsok", "okrsky", okrsky),
            ):
                if given is not None:
                    numbers = given[group]
                    if len(set(numbers)) == 1:
                        pieces.append(
                            b',"%s":%s' % (one.encode(), output.to_json(numbers[0]))
                        )
                    else:
                        pieces.append(
                            b',"%s":%s' % (several.encode(), output.to_json(numbers))
                        )
            start = end
    pieces.append(body.data[start:])
    return b"".join(pieces)


def index_file(addresses: Addresses, admin: Admin) -> dict[str, Any]:
    """Return the content of ``index.json``; see the module doc."""
    names: dict[str, dict[str, set[str]]] = {
        STREETS: defaultdict(set),
        PARTS: defaultdict(set),
    }
    for code, groups in addresses.obce.items():
        own = search_key(admin.obce[code].name)
        for kind, name in groups:
            if kind == STREETS or search_key(name) != own:
                names[kind][name].add(code)
    lists = {
        kind: [
            [name, search_key(name), sorted(by_name[name])]
            for name in sorted(by_name, key=lambda n: (search_key(n), n))
        ]
        for kind, by_name in names.items()
    }
    return {
        "scale": SCALE,
        "okresy": {c: n for c, (n, _) in sorted(admin.okresy.items())},
        "obce": [
            [c, admin.obce[c].name, admin.obce[c].okres, search_key(admin.obce[c].name)]
            for c in addresses.obce
        ],
        STREETS: lists[STREETS],
        PARTS: lists[PARTS],
    }


def contests(
    obec: Obec,
    council: Sequence[int],
    props: Mapping[str, Any],
    obvod: int | None = None,
    kinds: Collection[str] = SELF_GOVERNMENT,
    national: Sequence[str] = (),
    *,
    whole: bool = True,
) -> list[str]:
    """Return the contests a voter at an address in *obec* votes in.

    *council* is the obec's council obvody, *props* its ``geo`` shard
    properties, *obvod* the address's council obvod where the obec has a
    rule set. A council obvod pending street rules is written ``?``, as is
    one of a council a by-election elects part of (not *whole*) without
    them. Of the self-governments' contests, those of *kinds*, the kinds
    the election has; then its country-wide contests, *national*,
    everyone's.
    """
    ids = [f"starosta:{obec.code}"] if "starosta" in kinds else []
    fields = council_fields(council, whole=whole)
    # An address in an obvod a by-election leaves out elects no councillor.
    if fields["council"] != "none" and (obvod is None or obvod in council):
        ids.append(f"oz:{obec.code}/{obvod or fields.get('obvod', '?')}")
    if obec.city is not None and "starosta" in kinds:
        ids.append(f"starosta:{obec.city}")
    if "city_obvod" in props:
        ids.append(f"oz:{obec.city}/{props['city_obvod']}")
    if "predseda" in kinds:
        ids.append(f"predseda:{obec.kraj}")
    if props["zsk"]:
        ids.append(f"zsk:{obec.kraj}/{props['zsk']}")
    return [*ids, *national]


class Ref(NamedTuple):
    """Where an address is in the output."""

    obec: str
    group: tuple[str, str]
    """``STREETS`` or ``PARTS``, and the name."""
    house: House

    @property
    def place(self) -> str:
        """Street, or part of the obec."""
        return self.group[1]


@dataclass(frozen=True)
class Outside:
    """An address point outside the polygon of its obec."""

    ref: Ref
    distance: float
    """To the obec polygon, metres."""
    within: str | None
    """The obec whose polygon holds the point."""


@dataclass(frozen=True)
class Sample:
    """A randomly drawn address, resolved."""

    ref: Ref
    by_point: str | None
    """The obec whose polygon holds the point; None without coordinates."""
    contests: list[str]
    missing: list[str]
    """Contests derived for the address that the candidate lists lack."""


class Drawn(NamedTuple):
    """An address of the random sample, before the election resolves it."""

    ref: Ref
    position: int
    """Of the house within its group."""
    by_point: str | None
    """The obec whose polygon holds the point; None without coordinates."""


class RegisterObec(NamedTuple):
    """What the register makes of one obec, the same in every election."""

    houses: int
    groups: list[tuple[tuple[str, str], int]]
    """Its groups in the register's order, with their house counts
    (:attr:`election_map_slovakia.obvody.ObecPlaces.groups`)."""
    body: ObecBody
    places: bytes
    """Its file of ``obvod-addresses/``
    (:func:`election_map_slovakia.obvody.write_places`)."""


HouseKey = tuple[str, str, str]
"""``STREETS`` or ``PARTS``, the name and the house number of an address."""


@dataclass
class Register:
    """What ``addresses`` makes of the register and ZBGIS level 0 alone.

    The same for every election that reads them, so it is cached
    (:func:`register`); an election adds its council and okrsky
    (:func:`build`).
    """

    directory: Path
    """The cache, where :meth:`houses` reads the rows."""
    admin: Admin
    obce: dict[str, RegisterObec]
    """By code, of the obce with addresses."""
    index: bytes
    """``index.json``."""
    outside: bytes
    """``OUTSIDE_FILE``."""
    sample: list[Drawn]
    summary: list[str]
    """Report lines on the rows and the addresses without coordinates."""
    outside_lines: list[str]
    """Report lines on the points outside their obec."""
    index_lines: list[str]
    """Report lines on the parts of ``index.json``."""

    def houses(self, obce: Collection[str]) -> dict[str, dict[str, HouseKey]]:
        """Return obec → identifikator → key of every row of the register in *obce*.

        Repeats included; where an identifikator repeats within an obec, its
        last row's key, as reading the rows in order into a dict gives.
        """
        with progress.stage(f"reading the rows of {self.directory.name}"):
            rows = pickle.loads((self.directory / _ROWS_FILE).read_bytes())
        numbers = rows["numbers"]
        out = {}
        for code in obce:
            if code in rows["obce"]:
                groups, idents, group_of, number_of = rows["obce"][code]
                keys = [
                    (*groups[g], numbers[n])
                    for g, n in zip(group_of.tolist(), number_of.tolist(), strict=True)
                ]
                out[code] = dict(zip(idents, keys, strict=True))
        return out


_KEY_FILE = "key"
_REGISTER_FILE = "register.pickle"
_ROWS_FILE = "rows.pickle"


def register(
    directory: Path,
    key: str,
    path: Path,
    gpkg: Path,
    overrides: Mapping[str, str],
    skip: Collection[str] = (),
) -> Register:
    """Return the :class:`Register` of register *path*, cached in *directory*.

    *key* is a digest of everything it depends on: the register, *gpkg*
    (ZBGIS level 0), *overrides* and *skip* (:func:`read`), the code. The
    cache is used where it was made with the same *key*, else made again;
    it is written whole or not at all (:func:`output.replacing`).
    """
    try:
        cached = (directory / _KEY_FILE).read_text() == key
    except OSError:
        cached = False
    if cached:
        with progress.stage(f"reading the register cached in {directory.name}/"):
            return Register(
                directory, **pickle.loads((directory / _REGISTER_FILE).read_bytes())
            )
    fields, rows = _make_register(path, gpkg, overrides, skip)
    with (
        progress.stage(f"caching the register in {directory.name}/"),
        output.replacing(directory) as tmp,
    ):
        (tmp / _REGISTER_FILE).write_bytes(
            pickle.dumps(fields, pickle.HIGHEST_PROTOCOL)
        )
        (tmp / _ROWS_FILE).write_bytes(pickle.dumps(rows, pickle.HIGHEST_PROTOCOL))
        (tmp / _KEY_FILE).write_text(key)
    return Register(directory, **fields)


def _make_register(
    path: Path, gpkg: Path, overrides: Mapping[str, str], skip: Collection[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the fields of the :class:`Register` of *path* but its directory.

    And the rows for :meth:`Register.houses`: numbers (every house number),
    obce (obec → its groups, the identifikator, group and number of each row).
    """
    admin = load_admin(gpkg)
    addresses = read(path, admin, overrides, skip)
    numbers: dict[str, int] = {}
    rows = {}
    for code, ids in addresses.ids.items():
        groups = list(addresses.obce[code])
        position = {g: i for i, g in enumerate(groups)}
        rows[code] = (
            groups,
            [r[0] for r in ids],
            np.array([position[r[1]] for r in ids], dtype=np.int32),
            np.array([numbers.setdefault(r[2], len(numbers)) for r in ids], np.int32),
        )
    addresses.ids = {}
    refs, positions = [], []
    for code, groups in addresses.obce.items():
        for group, houses in groups.items():
            refs += [Ref(code, group, h) for h in houses]
            positions += range(len(houses))
    polygons = {
        c: g for c, (_, g) in geo.read_layer(gpkg, "obec", "IDN4", "NM4").items()
    }
    with progress.stage(f"checking {len(refs):,} points against their obec"):
        by_point = locate(refs, polygons, geo.transformer())
    outside = sorted(
        (o for o in by_point if isinstance(o, Outside)),
        key=lambda o: (-o.distance, o.ref.obec, o.ref.place, o.ref.house.number),
    )
    dropped = drop_far(addresses, outside)
    sample = []
    for i in random.Random(SAMPLE_SEED).sample(range(len(refs)), SAMPLE_SIZE):
        located = by_point[i]
        within = located.within if isinstance(located, Outside) else located
        sample.append(Drawn(refs[i], positions[i], within))
    del refs, positions, by_point
    kus = geo.read_kus(gpkg)
    # One call for all points: PROJ takes long to set up a call.
    lonlat = np.array(
        [
            h.point or (np.nan, np.nan)
            for groups in addresses.obce.values()
            for houses in groups.values()
            for h in houses
        ],
        dtype=float,
    ).reshape(-1, 2)
    xy = np.full_like(lonlat, np.nan)
    located = ~np.isnan(lonlat[:, 0])
    xy[located, 0], xy[located, 1] = geo.transformer().transform(
        lonlat[located, 0] / SCALE,
        lonlat[located, 1] / SCALE,
        direction=TransformDirection.INVERSE,
    )
    obce = {}
    start = 0
    with progress.stage("the obec files and places", len(addresses.obce)) as s:
        for code, groups in s.track(addresses.obce.items()):
            houses = sum(map(len, groups.values()))
            obce[code] = RegisterObec(
                houses,
                [(g, len(h)) for g, h in groups.items()],
                obec_body(groups),
                obec_places(
                    groups, kus.get(code, []), xy[start : start + houses]
                ).to_json(),
            )
            start += houses
    index = index_file(addresses, admin)
    fields = {
        "admin": admin,
        "obce": obce,
        "index": output.to_json(index),
        "outside": _outside_file(admin, outside),
        "sample": sample,
        "summary": _summary(admin, addresses, outside, dropped),
        "outside_lines": _report_outside(admin, addresses, outside, dropped),
        "index_lines": _report_index(index),
    }
    return fields, {"numbers": list(numbers), "obce": rows}


@dataclass
class Result:
    """Everything ``addresses`` writes, plus the checks for the report."""

    register: Register
    files: dict[str, bytes]
    """Path below ``addr/`` → content."""
    council: dict[str, list[int]]
    parts: set[str] = field(default_factory=set)
    """The obce of a by-election that elect part of their council
    (:func:`part_councils`)."""
    sample: list[Sample] = field(default_factory=list)
    places: dict[str, bytes] = field(default_factory=dict)
    """The files of ``obvod-addresses/``: of the obce with several council
    obvody or okrsky."""
    assigned: dict[str, ObvodMap] = field(default_factory=dict)
    """Obec → the council obvod of each house, for the obce with a rule set."""
    okrsky: dict[str, ObvodMap] = field(default_factory=dict)
    """Obec → the okrsok of each house, for the obce whose okrsky are drawn."""
    rules: list[str] = field(default_factory=list)
    """Report lines on the rule sets."""
    okrsok_lines: list[str] = field(default_factory=list)
    """Report lines on the okrsky by address."""


def build(
    reg: Register,
    election_dir: Path,
    contest_list: Sequence[Mapping[str, Any]],
    okrsky: Mapping[str, int],
    *,
    partial: bool = False,
    parts: Collection[str] = (),
) -> Result:
    """Build the output files of an election on register *reg*.

    *election_dir* is the election's curated data
    (:meth:`election_map_slovakia.config.Config.election_dir`);
    *contest_list* the contests of ``candidates.json``; *okrsky* obec → its
    number of okrsky in the election (none where it counts none). *partial*:
    the contests are held in some areas only (a by-election), so an address
    may well have none of the self-governments' contests; *parts* then the
    obce whose council contests are part of a larger council
    (:func:`council_parts`). An election without council contests has no
    council obvody by address either.
    """
    admin = reg.admin
    council = council_obvody(contest_list)
    every = obvody.load_rule_sets(election_dir)
    rule_sets = every if council else {}
    parts = set(parts)
    if problems := uncontested_problems(contest_list, rule_sets):
        raise AddressesError(
            "uncontested council obvody without a decision of their own:\n  "
            + "\n  ".join(problems)
        )
    result = Result(reg, {}, council, parts)
    result.places = {
        code: o.places
        for code, o in reg.obce.items()
        if len(council.get(code, ())) >= _SEVERAL
        or okrsky.get(code, 0) >= _SEVERAL
        or code in parts
    }
    okrsok_sets = obvody.okrsok_rule_sets(election_dir, every)
    with progress.stage(
        f"assigning the council obvody of {len(rule_sets)} obce"
        f" and the okrsky of {len(okrsok_sets)}"
    ):
        assign(result, rule_sets, okrsok_sets)
    with progress.stage("making the obec files"):
        result.files["index.json"] = reg.index
        for code, o in reg.obce.items():
            result.files[f"{code}.json"] = obec_file(
                o.body,
                council.get(code, []),
                result.assigned.get(code),
                result.okrsky.get(code),
                code not in parts,
            )
    with progress.stage("resolving a random sample of addresses"):
        members = geo.memberships(election_dir, admin, contest_list, partial=partial)
        props = geo.obec_properties(admin, geo.obec_codes(admin), members)
        known = {str(c["id"]) for c in contest_list}
        kinds = {str(c["kind"]) for c in contest_list}
        # Every voter's: a party's list is chosen on its party's ballot.
        national = [
            cid
            for cid in (str(c["id"]) for c in contest_list)
            if parse(cid).kind.scope == "country" and not parse(cid).is_list
        ]
        for ref, position, by_point in reg.sample:
            assigned = result.assigned.get(ref.obec)
            ids = contests(
                admin.obce[ref.obec],
                council.get(ref.obec, []),
                props[ref.obec],
                assigned[ref.group][position] if assigned else None,
                kinds,
                national,
                whole=ref.obec not in parts,
            )
            result.sample.append(
                Sample(
                    ref,
                    by_point,
                    ids,
                    [
                        c
                        for c in ids
                        if not c.endswith("?") and c not in known and not partial
                    ],
                )
            )
    return result


def uncontested_problems(
    contests: Iterable[Mapping[str, Any]], rule_sets: Mapping[str, obvody.RuleSet]
) -> list[str]:
    """Return why the uncontested council obvody of *contests* may not stand.

    An obvod no candidate stood in, of an obec of several (``uncontested``
    in ``candidates.json``), comes from the municipality's decision: the
    election's own rule set of the obec (*rule_sets*, not another vote's
    standing in or reused), which lists it with its seats and has the
    document it is sourced to among its documents.
    """
    contests = list(contests)
    numbers = council_obvody(contests)
    problems = []
    for c in contests:
        code, n = str(c["area"]), c.get("obvod")
        if c["kind"] != "oz" or "uncontested" not in c or len(numbers[code]) < _SEVERAL:
            continue
        rules = rule_sets.get(code)
        cid, source = c["id"], c["uncontested"]["source"]
        if rules is None or rules.adoption or rules.reused:
            problems.append(f"{cid}: no rule set of the election's own decision")
        elif n not in rules.seats:
            problems.append(f"{cid}: not an obvod of its rule set")
        elif "seats" in c and rules.seats[n] != c["seats"]:
            problems.append(f"{cid}: {c['seats']} seats, its rule set {rules.seats[n]}")
        elif source not in {d.url for d in rules.documents}:
            problems.append(f"{cid}: {source} is none of its rule set's documents")
    return problems


def obec_places(
    groups: Groups, kus: Sequence[geo.Ku], projected: np.ndarray
) -> obvody.ObecPlaces:
    """Return the addresses of an obec of *groups* as its rules see them.

    *kus* are its k.ú. (:func:`election_map_slovakia.geo.read_kus`), for
    the k.ú. that holds each point; *projected* the points in EPSG:5514, in
    the order of the houses, NaN where none.
    """
    places, points, sizes = [], [], []
    for (kind, name), houses in groups.items():
        sizes.append(((kind, name), len(houses)))
        street = name if kind == STREETS else ""
        for h in houses:
            places.append(obvody.Place(street, h.part, h.supisne, h.orientacne))
            points.append(h.point or (np.nan, np.nan))
    xy = np.array(points, dtype=float).reshape(-1, 2)
    located = np.flatnonzero(~np.isnan(xy[:, 0]))
    x, y = projected[located, 0], projected[located, 1]
    within: list[str | None] = [None] * len(places)
    for _, name, polygon in kus:
        for i in located[shapely.intersects_xy(polygon, x, y)]:
            within[int(i)] = name
    return obvody.ObecPlaces(places, xy, within, [k[1] for k in kus], sizes)


def assign(
    result: Result,
    rule_sets: Mapping[str, obvody.RuleSet],
    okrsok_sets: Mapping[str, obvody.RuleSet],
) -> None:
    """Set the council obvod and the okrsok of each house of *result*'s places.

    By the obce's rule sets: *rule_sets* the council obvody's
    (:attr:`Result.assigned`, report lines in :attr:`Result.rules`),
    *okrsok_sets* the okrsky's
    (:func:`election_map_slovakia.obvody.okrsok_rule_sets`), where they
    place every address in one okrsok, as ``geo`` draws them
    (:func:`election_map_slovakia.geo.address_cuts`): :attr:`Result.okrsky`;
    report lines in :attr:`Result.okrsok_lines`, among them the rule sets
    that do not (``geo`` fails on those, but the addresses are still
    written, for the jobs that fix them). Fails listing every council rule
    set that does not fit the candidate lists (of an obec of
    :attr:`Result.parts`, a by-election's, is not a superset of theirs) or
    leaves an address in no obvod or in two (see :func:`check_assignment`).
    Each obec is done in a worker process.
    """
    places = result.places
    by_obvod = {c for c in rule_sets if c in places}
    by_okrsok = {c for c, r in okrsok_sets.items() if r.okrsok_areas and c in places}
    codes = sorted(by_obvod | by_okrsok)
    tasks = [
        (
            rule_sets[c] if c in by_obvod else None,
            result.council.get(c, []),
            c in result.parts,
            okrsok_sets[c] if c in by_okrsok else None,
            places[c],
        )
        for c in codes
    ]
    done = list(parallel.each(_assign, tasks, cost=_cost))
    # The files now hold the units too, for ``geo``.
    places.update((c, data) for c, (_, _, data) in zip(codes, done, strict=True))
    obvod_done = {
        c: o for c, (o, _, _) in zip(codes, done, strict=True) if o is not None
    }
    okrsok_done = {
        c: k for c, (_, k, _) in zip(codes, done, strict=True) if k is not None
    }
    errors: list[str] = []
    for code, rules in rule_sets.items():
        if code not in obvod_done:
            errors.append(
                f"{rules.name} ({code}): has rules, but not several council obvody"
            )
            continue
        problems, report, assigned = obvod_done[code]
        errors += problems
        result.rules += report
        if assigned is not None:
            result.assigned[code] = _per_group(
                result.register.obce[code].groups, assigned
            )
    if errors:
        raise AddressesError(
            "the council obvody by address do not fit:\n  " + "\n  ".join(errors)
        )
    for code in okrsok_sets:
        if code in okrsok_done:
            problem, okrsky = okrsok_done[code]
            if problem:
                result.okrsok_lines.append(problem)
            else:
                result.okrsky[code] = _per_group(
                    result.register.obce[code].groups, okrsky
                )
    result.okrsok_lines.append(
        f"  okrsok of every address in {len(result.okrsky)} obce"
    )


def _cost(task: tuple[Any, ...]) -> int:
    """Return how long a task of one obec's places (its last item) takes."""
    return len(task[-1])


def _assign(
    rules: obvody.RuleSet | None,
    seats: Sequence[int],
    part: bool,
    okrsok_rules: obvody.RuleSet | None,
    data: bytes,
) -> tuple[
    tuple[list[str], list[str], list[int] | None] | None,
    tuple[str | None, list[int]] | None,
    bytes,
]:
    """Return the council obvody and the okrsky of one obec's places, *data*.

    Each where its rule set is given: :func:`_assign_obvody` of *rules*,
    then :func:`_assign_okrsky` of *okrsok_rules* within those obvody (by
    *okrsok_rules* alone without *rules*). And its file with the units of
    every address where they have no problems
    (:attr:`election_map_slovakia.obvody.ObecPlaces.obvody`, ``okrsky``).
    """
    p = obvody.parse_places(data)
    by_obvod = None if rules is None else _assign_obvody(rules, seats, part, p)
    units = None if by_obvod is None else by_obvod[2]
    if rules is not None and units is not None:
        p.obvody = obvody.Placed(geo.rules_digest(rules), units)
    if okrsok_rules is None:
        return by_obvod, None, p.to_json()
    if rules is None:
        a = obvody.assign(okrsok_rules, p.places, p.kus, p.planar())
        units = a.units
        if not a.problems(p.places):
            p.obvody = obvody.Placed(geo.rules_digest(okrsok_rules), units)
    by_okrsok = _assign_okrsky(okrsok_rules, units, p)
    if by_okrsok[0] is None:
        p.okrsky = obvody.Placed(geo.rules_digest(okrsok_rules), by_okrsok[1])
    return by_obvod, by_okrsok, p.to_json()


def _assign_obvody(
    rules: obvody.RuleSet, seats: Sequence[int], part: bool, p: obvody.ObecPlaces
) -> tuple[list[str], list[str], list[int] | None]:
    """Return the problems, report lines and obvod of each place of one obec.

    See :func:`assign`; the obvody are None where there are problems.
    """
    name = f"{rules.name} ({rules.obec})"
    a = obvody.assign(rules, p.places, p.kus, p.planar())
    problems = check_assignment(rules, seats, p, a, part=part)
    if problems:
        return [f"{name}: {x}" for x in problems], [], None
    counts = Counter(a.units)
    lines = [
        f"  {name:<36} {len(p.places):>7,} addresses: "
        + ", ".join(f"{n} {counts[n]:,}" for n in rules.seats)
        + (f"; {len(a.filled):,} by the nearest" if a.filled else "")
    ]
    lines += [f"    unused: {r.describe()}" for r in a.unused]
    lines += [
        f"    {x}"
        for x in obvody.name_problems(
            rules,
            sorted({x.street for x in p.places if x.street}),
            sorted({x.part for x in p.places}),
            p.ku_names,
        )
    ]
    return [], lines, a.units


def _assign_okrsky(
    rules: obvody.RuleSet, council: Sequence[int] | None, p: obvody.ObecPlaces
) -> tuple[str | None, list[int]]:
    """Return the problem line, or else the okrsok of each place, of one obec.

    See :func:`assign`; *council* is the obvod of each place, if known.
    """
    planar = p.planar()
    a = council
    if a is None:
        a = obvody.assign(rules, p.places, p.kus, planar).units
    k = obvody.assign_okrsky(rules, p.places, a, p.kus, planar)
    problems = k.problems(p.places)
    if problems:
        return f"  {rules.name} ({rules.obec}), okrsky: " + "; ".join(problems), []
    return None, k.units


def _per_group(
    groups: Iterable[tuple[tuple[str, str], int]], units: list[int]
) -> ObvodMap:
    """Split *units*, one per address in group order, by group."""
    out: ObvodMap = {}
    start = 0
    for group, size in groups:
        out[group] = units[start : start + size]
        start += size
    return out


def check_assignment(
    rules: obvody.RuleSet,
    council: Sequence[int],
    places: obvody.ObecPlaces,
    assignment: obvody.Assignment,
    *,
    part: bool = False,
) -> list[str]:
    """Return why *assignment* of *places* by *rules* is not acceptable.

    The obvody must be those of the candidate lists (*council*), or, for
    a by-election electing *part* of the council, include them; every
    address in exactly one of them, each obvod with addresses.
    """
    if part:
        missing = [n for n in council if n not in rules.seats]
        if missing:
            return [f"the rules have no obvod {missing[0]} of the candidate lists"]
    elif list(rules.seats) != list(council):
        return [
            f"the rules have {len(rules.seats)} obvody, the candidate lists"
            f" {len(council)}"
        ]
    problems = assignment.problems(places.places)
    counts = Counter(assignment.units)
    problems += [f"obvod {n} has no address" for n in rules.seats if not counts[n]]
    return problems


def drop_far(addresses: Addresses, outside: Iterable[Outside]) -> int:
    """Remove the points farther than ``MAX_OUTSIDE`` from their obec.

    The addresses stay, without a point. Returns how many were removed.
    """
    far: dict[tuple[str, tuple[str, str]], set[House]] = defaultdict(set)
    for o in outside:
        if o.distance > MAX_OUTSIDE:
            far[(o.ref.obec, o.ref.group)].add(o.ref.house)
    for (code, group), houses in far.items():
        addresses.obce[code][group] = [
            h._replace(point=None) if h in houses else h
            for h in addresses.obce[code][group]
        ]
    return sum(map(len, far.values()))


def locate(
    refs: Sequence[Ref],
    polygons: Mapping[str, shapely.Geometry],
    to_wgs84: pyproj.Transformer,
) -> list[str | Outside | None]:
    """Check every point against the polygon of its obec.

    Returns per ref its obec code where the point lies in its obec polygon,
    :class:`Outside` where not, None where it has no point. *refs* must be
    grouped by obec; *polygons* are in EPSG:5514, *to_wgs84* is
    :func:`election_map_slovakia.geo.transformer`.
    """
    rows = [i for i, r in enumerate(refs) if r.house.point is not None]
    lonlat = np.array([refs[i].house.point for i in rows], dtype=float) / SCALE
    x, y = to_wgs84.transform(
        lonlat[:, 0], lonlat[:, 1], direction=TransformDirection.INVERSE
    )
    codes = np.array([refs[i].obec for i in rows])
    inside = np.zeros(len(rows), dtype=bool)
    starts = (np.flatnonzero(codes[1:] != codes[:-1]) + 1).tolist()
    for a, b in zip([0, *starts], [*starts, len(rows)]):
        polygon = polygons[str(codes[a])]
        shapely.prepare(polygon)
        inside[a:b] = shapely.intersects_xy(polygon, x[a:b], y[a:b])
    out: list[str | Outside | None] = [None] * len(refs)
    for i, ok in zip(rows, inside):
        if ok:
            out[i] = refs[i].obec
    far = np.flatnonzero(~inside)
    points = shapely.points(x[far], y[far])
    distances = shapely.distance(
        np.array([polygons[str(codes[j])] for j in far]), points
    )
    order = sorted(polygons)
    tree = shapely.STRtree([polygons[c] for c in order])
    within = {
        int(p): order[int(t)] for p, t in tree.query(points, predicate="within").T
    }
    for k, j in enumerate(far):
        i = rows[j]
        out[i] = Outside(refs[i], float(distances[k]), within.get(k))
    return out


def write(
    result: Result, directory: Path, memo: Path | None = None
) -> dict[str, tuple[int, int]]:
    """Replace *directory* with the files of *result*.

    Returns path → (bytes, gzipped bytes), the gzip sizes kept in *memo*
    (:func:`election_map_slovakia.output.gzip_sizes`).
    """
    files = dict(sorted(result.files.items()))
    with (
        progress.stage(f"writing {directory.name}/", len(files)) as s,
        output.replacing(directory) as tmp,
    ):
        for path, data in s.track(files.items()):
            (tmp / path).write_bytes(data)
    gzipped = output.gzip_sizes(list(files.values()), memo)
    return {
        path: (len(data), gz)
        for (path, data), gz in zip(files.items(), gzipped, strict=True)
    }


def write_outside(result: Result, path: Path) -> None:
    """Write the points outside their obec as a tab-separated table."""
    output.write_file(path, result.register.outside)


def _outside_file(admin: Admin, outside: Iterable[Outside]) -> bytes:
    """Return the table of :func:`write_outside` of the points *outside*."""
    obce = admin.obce
    lines = [
        "obec\tname\tplace\tnumber\tlon\tlat\tdistance_m\twithin\twithin_name"
        "\tpublished"
    ]
    for o in outside:
        point = o.ref.house.point or (0, 0)
        within = obce[o.within].name if o.within else ""
        lines.append(
            "\t".join(
                [
                    o.ref.obec,
                    obce[o.ref.obec].name,
                    o.ref.place,
                    o.ref.house.number,
                    f"{point[0] / SCALE:.5f}",
                    f"{point[1] / SCALE:.5f}",
                    f"{o.distance:.1f}",
                    o.within or "",
                    within,
                    "no" if o.distance > MAX_OUTSIDE else "yes",
                ]
            )
        )
    return ("\n".join(lines) + "\n").encode()


def _percentile(values: Sequence[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _obec(admin: Admin, code: str | None) -> str:
    return "none" if code is None else f"{admin.obce[code].name} ({code})"


def report(result: Result, sizes: Mapping[str, tuple[int, int]]) -> Iterator[str]:
    """Yield the human-readable summary lines of a written *result*."""
    reg = result.register
    admin = reg.admin
    yield from reg.summary

    by_status: Counter[str] = Counter()
    obce_by_status: Counter[str] = Counter()
    pending_by: Counter[str] = Counter()
    for code, o in reg.obce.items():
        council = result.council.get(code, [])
        status = council_fields(
            council, code in result.assigned, code not in result.parts
        )["council"]
        by_status[status] += o.houses
        obce_by_status[status] += 1
        if status == "pending":
            pending_by[code] = o.houses
    no_council_obce = sorted(c for c in reg.obce if c not in result.council)
    yield "council: " + "; ".join(
        f"{s} {obce_by_status[s]:,} obce, {by_status[s]:,} addresses"
        for s in ("single", ADDRESS, "pending", "none")
    )
    yield "  none: " + (", ".join(_obec(admin, c) for c in no_council_obce) or "-")
    yield f"by address (rule sets in obvody/{obvody.RULES_DIRECTORY}/ of the election):"
    yield from result.rules or ["  -"]
    yield f"pending, top {TOP}:"
    for code, n in pending_by.most_common(TOP):
        yield f"  {_obec(admin, code):<40} {n:>7,}  {len(result.council[code])} obvody"
    yield "okrsky by address (geo draws their areas):"
    yield from result.okrsok_lines

    yield from reg.outside_lines
    yield from _report_sample(result)
    yield from _report_sizes(result, sizes)


def _summary(
    admin: Admin, a: Addresses, outside: Sequence[Outside], dropped: int
) -> list[str]:
    """Return the report lines on the rows and the addresses without coordinates.

    Of the register *a*, its far points (*outside*, *dropped*) dropped.
    """
    houses = Counter({c: sum(map(len, g.values())) for c, g in a.obce.items()})
    far = Counter(o.ref.obec for o in outside if o.distance > MAX_OUTSIDE)
    unlocated = Counter(
        {
            c: n
            for c, g in a.obce.items()
            if (n := sum(h.point is None for hs in g.values() for h in hs) - far[c])
        }
    )
    total = houses.total()
    return [
        f"rows {a.rows:,}, {a.duplicates} exact duplicates dropped: {total:,}"
        f" addresses in {len(a.obce):,} obce",
        f"without coordinates {unlocated.total():,} ({unlocated.total() / total:.1%})"
        f" in {len(unlocated):,} obce, plus {dropped:,} points over"
        f" {MAX_OUTSIDE:.0f} m outside their obec not published; all kept for"
        f" search; top {TOP} without coordinates:",
        *(
            f"  {_obec(admin, code):<40} {n:>6,} of {houses[code]:,}"
            for code, n in unlocated.most_common(TOP)
        ),
    ]


def _report_outside(
    admin: Admin, a: Addresses, outside: Sequence[Outside], dropped: int
) -> list[str]:
    """Return the report lines on the points *outside* their obec, of *a*."""
    located = dropped + sum(
        h.point is not None for g in a.obce.values() for hs in g.values() for h in hs
    )
    labels = [*(f"≤ {b:,} m" for b in OUTSIDE_BINS), "more"]
    bins = Counter(
        next(
            (label for b, label in zip(OUTSIDE_BINS, labels) if o.distance <= b), "more"
        )
        for o in outside
    )
    return [
        f"points outside their obec polygon (ZBGIS level 0):"
        f" {len(outside):,} of {located:,}; "
        + ", ".join(f"{k} {bins[k]:,}" for k in labels),
        f"  not published (over {MAX_OUTSIDE:.0f} m): {dropped:,}",
        f"  farthest {TOP} (all in data/build/<election day>/{OUTSIDE_FILE}):",
        *(
            f"  {o.distance:>9,.0f} m  {_obec(admin, o.ref.obec)}, {o.ref.place}"
            f" {o.ref.house.number}; in {_obec(admin, o.within)}"
            for o in outside[:TOP]
        ),
    ]


def _report_sample(result: Result) -> Iterator[str]:
    admin = result.register.admin
    ok = [
        s
        for s in result.sample
        if not s.missing and (s.ref.house.point is None or s.by_point == s.ref.obec)
    ]
    yield (
        f"random sample of {len(result.sample)}: {len(ok)} resolve to the obec"
        " holding their point and to contests with candidates"
    )
    for s in [s for s in result.sample if s not in ok] + ok[:SAMPLE_SHOWN]:
        r = s.ref
        if r.house.point is None:
            point = "no point"
        elif s.by_point == r.obec:
            point = "point inside"
        else:
            point = f"point in {_obec(admin, s.by_point)}"
        missing = f"; no candidates: {', '.join(s.missing)}" if s.missing else ""
        yield (
            f"  {admin.obce[r.obec].name}, {r.place} {r.house.number} → {r.obec}"
            f" ({point}): {' '.join(s.contests)}{missing}"
        )


def _report_index(index: Mapping[str, Any]) -> list[str]:
    """Return the report lines on the parts of ``index.json``, of content *index*."""
    lines = ["index.json by part:      bytes        gzip"]
    for key in ("obce", STREETS, PARTS):
        raw = output.to_json(index[key])
        lines.append(
            f"  {key:<10} {len(index[key]):>6,} {format_size(len(raw)):>11}"
            f" {format_size(output.gzip_size(raw)):>11}"
        )
    return lines


def _report_sizes(
    result: Result, sizes: Mapping[str, tuple[int, int]]
) -> Iterator[str]:
    yield from result.register.index_lines
    raw, gz = sizes["index.json"]
    yield f"  {'all':<17} {format_size(raw):>11} {format_size(gz):>11}"
    obce = {p: s for p, s in sizes.items() if p != "index.json"}
    yield f"<obec>.json ({len(obce):,} files):  bytes        gzip"
    for label, pick in (
        ("total", sum),
        ("median", lambda v: _percentile(v, 0.5)),
        ("p95", lambda v: _percentile(v, 0.95)),
        ("max", max),
    ):
        yield (
            f"  {label:<17} {format_size(pick([s[0] for s in obce.values()])):>11}"
            f" {format_size(pick([s[1] for s in obce.values()])):>11}"
        )
    yield "  largest:"
    for path, (raw, gz) in sorted(obce.items(), key=lambda kv: -kv[1][0])[:10]:
        name = _obec(result.register.admin, path.removesuffix(".json"))
        yield f"  {name:<40} {format_size(raw):>11} {format_size(gz):>11}"
