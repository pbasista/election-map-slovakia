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
``"none"`` in the few obce with no council election (no candidates, or a
military district).

Points farther than ``MAX_OUTSIDE`` metres outside the ZBGIS polygon of
their obec are published as missing: drawn there, a house number would
sit in a neighbouring obec and a click on it would yield that obec's
contests. All points outside their obec are reported.

Output, ``data/build/addr/`` (JSON, compact, sorted)::

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
also go to ``data/build/obvod-addresses/<obec>.json``
(:func:`election_map_slovakia.obvody.write_places`): the input of the
``obvod-rules`` and ``okrsok-rules`` jobs, their checks and the okrsky.
"""

from __future__ import annotations

import csv
import io
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import pyproj
import shapely
from pyproj.enums import TransformDirection

from election_map_slovakia import geo, obvody, output, progress
from election_map_slovakia.candidates import (
    Admin,
    Obec,
    load_admin,
    municipal_index,
    name_key,
    search_key,
)
from election_map_slovakia.output import format_size

INPUT = "addresses"
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
"""Below ``data/build/``: the addresses of the obce with several council
obvody or okrsky, as their rules see them (see
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


def read(path: Path, admin: Admin, overrides: Mapping[str, str]) -> Addresses:
    """Read the register; fail listing every unmatched municipality.

    *overrides* maps ``"<okres>/<obec>"`` as the register writes them to
    obec codes (``[address]`` in ``overrides.toml``).
    """
    okresy = {name_key(name): code for code, (name, _) in admin.okresy.items()}
    index = municipal_index(admin)
    matched: dict[tuple[str, str], str | None] = {}
    unmatched: Counter[str] = Counter()
    obce: dict[str, Groups] = defaultdict(lambda: defaultdict(list))
    # Most house numbers repeat across streets, and part names within an
    # obec; one shared display form, sort key and string per number and
    # part saves their parsing and their memory.
    numbers: dict[tuple[str, str], tuple[str, tuple[int, str, int, str], str, str]] = {}
    parts: dict[str, str] = {}
    rows = 0
    with (
        progress.stage(f"reading {path.name}", path.stat().st_size, format_size) as s,
        path.open("rb") as raw,
        io.TextIOWrapper(raw, encoding="utf-8", newline="") as f,
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
            _, _, okres, obec, part, street, supisne, orientacne, _, x, y = row
            place = (okres, obec)
            if place not in matched:
                code = overrides.get(f"{okres}/{obec}")
                if code is None:
                    code = index.get((okresy.get(name_key(okres), ""), name_key(obec)))
                matched[place] = code
            code = matched[place]
            if code is None:
                unmatched[f"obec {obec!r} in okres {okres!r}"] += 1
                continue
            try:
                point = _point(x, y)
            except AddressesError as e:
                raise AddressesError(f"{path}:{reader.line_num}: {e}") from None
            part = part or obec
            part = parts.setdefault(part, part)
            group = (STREETS, street) if street else (PARTS, part)
            number = numbers.get((supisne, orientacne))
            if number is None:
                number = numbers[(supisne, orientacne)] = (
                    house_number(supisne, orientacne),
                    number_order(supisne, orientacne),
                    supisne,
                    orientacne,
                )
            display, order, sup, ori = number
            obce[code][group].append(House(display, order, point, part, sup, ori))
    _check_matched(unmatched, matched, overrides)
    with progress.stage("sorting the house numbers"):
        duplicates = _sort_unique(obce.values())
    return Addresses({c: dict(g) for c, g in sorted(obce.items())}, rows, duplicates)


def _check_matched(
    unmatched: Mapping[str, int],
    matched: Iterable[tuple[str, str]],
    overrides: Mapping[str, str],
) -> None:
    """Fail listing the *unmatched* places and the overrides of no place."""
    errors = [f"{n:,} rows: {where}" for where, n in sorted(unmatched.items())]
    known = {f"{okres}/{obec}" for okres, obec in matched}
    errors += [
        f"unused override address {k!r}" for k in sorted(overrides.keys() - known)
    ]
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


def council_fields(numbers: Sequence[int], by_address: bool = False) -> dict[str, Any]:
    """Return ``council`` (and ``obvod``) of an obec with council obvody *numbers*.

    *by_address*: the obec has a rule set giving each address its obvod.
    See the module doc.
    """
    if len(numbers) == 1:
        return {"council": "single", "obvod": numbers[0]}
    if by_address:
        return {"council": ADDRESS}
    return {"council": "pending" if numbers else "none"}


ObvodMap = dict[tuple[str, str], list[int]]
"""Group → council obvod (or okrsok) per house, of an obec with a rule set."""


def obec_file(
    groups: Groups,
    council: Sequence[int],
    assigned: ObvodMap | None = None,
    okrsky: ObvodMap | None = None,
) -> dict[str, Any]:
    """Return the content of ``<obec>.json``; see the module doc.

    *council* is the obec's council obvody, from :func:`council_obvody`;
    *assigned* the obvod of each house where the obec has a rule set,
    *okrsky* the okrsok of each where its okrsky are drawn.
    """
    out: dict[str, list[dict[str, Any]]] = {STREETS: [], PARTS: []}
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
        group: dict[str, Any] = {
            "name": name,
            "numbers": [h.number for h in houses],
            "points": points,
        }
        for one, several, given in (
            ("obvod", "obvody", assigned),
            ("okrsok", "okrsky", okrsky),
        ):
            if given is not None:
                numbers = given[(kind, name)]
                if len(set(numbers)) == 1:
                    group[one] = numbers[0]
                else:
                    group[several] = numbers
        out[kind].append(group)
    return council_fields(council, assigned is not None) | out


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
) -> list[str]:
    """Return the contests a voter at an address in *obec* votes in.

    *council* is the obec's council obvody, *props* its ``geo`` shard
    properties, *obvod* the address's council obvod where the obec has a
    rule set. A council obvod pending street rules is written ``?``.
    """
    ids = [f"starosta:{obec.code}"]
    fields = council_fields(council)
    if fields["council"] != "none":
        ids.append(f"oz:{obec.code}/{obvod or fields.get('obvod', '?')}")
    if obec.city is not None:
        ids += [f"starosta:{obec.city}", f"oz:{obec.city}/{props['city_obvod']}"]
    ids += [f"predseda:{obec.kraj}", f"zsk:{obec.kraj}/{props['zsk']}"]
    return ids


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


@dataclass
class Result:
    """Everything ``addresses`` writes, plus the checks for the report."""

    admin: Admin
    addresses: Addresses
    files: dict[str, dict[str, Any]]
    """Path below ``addr/`` → JSON content."""
    council: dict[str, list[int]]
    dropped: int = 0
    """Points not published for lying over ``MAX_OUTSIDE`` outside their obec."""
    outside: list[Outside] = field(default_factory=list)
    """Farthest first."""
    sample: list[Sample] = field(default_factory=list)
    places: dict[str, obvody.ObecPlaces] = field(default_factory=dict)
    """The addresses of the obce with several council obvody or okrsky."""
    assigned: dict[str, ObvodMap] = field(default_factory=dict)
    """Obec → the council obvod of each house, for the obce with a rule set."""
    okrsky: dict[str, ObvodMap] = field(default_factory=dict)
    """Obec → the okrsok of each house, for the obce whose okrsky are drawn."""
    rules: list[str] = field(default_factory=list)
    """Report lines on the rule sets."""
    okrsok_lines: list[str] = field(default_factory=list)
    """Report lines on the okrsky by address."""


def build(
    path: Path,
    gpkg: Path,
    election_dir: Path,
    contest_list: Sequence[Mapping[str, Any]],
    overrides: Mapping[str, str],
    okrsky: Mapping[str, int],
) -> Result:
    """Read and check the register and build the output files.

    *gpkg* is ZBGIS level 0; *election_dir* the election's curated data
    (:attr:`election_map_slovakia.config.Config.election_dir`);
    *contest_list* the contests of ``candidates.json``; *overrides* the
    ``[address]`` table of ``overrides.toml``; *okrsky* obec → its number
    of okrsky in the election.
    """
    admin = load_admin(gpkg)
    addresses = read(path, admin, overrides)
    council = council_obvody(contest_list)
    result = Result(admin, addresses, {}, council)
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
    result.outside = sorted(
        (o for o in by_point if isinstance(o, Outside)),
        key=lambda o: (-o.distance, o.ref.obec, o.ref.place, o.ref.house.number),
    )
    result.dropped = drop_far(addresses, result.outside)
    with progress.stage("the addresses of the obce with several obvody or okrsky"):
        result.places = obec_places(addresses, council, okrsky, gpkg)
    rule_sets = obvody.load_rule_sets(election_dir)
    with progress.stage(f"assigning the council obvody of {len(rule_sets)} obce"):
        result.assigned, result.rules, units = assign_obvody(
            rule_sets, council, result.places
        )
    okrsok_sets = obvody.okrsok_rule_sets(election_dir)
    with progress.stage(f"assigning the okrsky of {len(okrsok_sets)} obce"):
        result.okrsky, result.okrsok_lines = assign_okrsky(
            okrsok_sets, result.places, units
        )
    with progress.stage("making the search index and obec files"):
        result.files["index.json"] = index_file(addresses, admin)
        for code, groups in addresses.obce.items():
            result.files[f"{code}.json"] = obec_file(
                groups,
                council.get(code, []),
                result.assigned.get(code),
                result.okrsky.get(code),
            )
    with progress.stage("resolving a random sample of addresses"):
        members = geo.memberships(election_dir, admin, contest_list)
        props = geo.obec_properties(admin, geo.obec_codes(admin), members)
        known = {str(c["id"]) for c in contest_list}
        for i in random.Random(SAMPLE_SEED).sample(range(len(refs)), SAMPLE_SIZE):
            ref = refs[i]
            located = by_point[i]
            obec = admin.obce[ref.obec]
            assigned = result.assigned.get(ref.obec)
            obvod = assigned[ref.group][positions[i]] if assigned else None
            ids = contests(obec, council.get(ref.obec, []), props[ref.obec], obvod)
            result.sample.append(
                Sample(
                    ref,
                    located.within if isinstance(located, Outside) else located,
                    ids,
                    [c for c in ids if not c.endswith("?") and c not in known],
                )
            )
    return result


def obec_places(
    addresses: Addresses,
    council: Mapping[str, Sequence[int]],
    okrsky: Mapping[str, int],
    gpkg: Path,
) -> dict[str, obvody.ObecPlaces]:
    """Return the addresses of each obec with several council obvody or okrsky.

    *okrsky* is obec → its number of okrsky; *gpkg* is ZBGIS level 0, for
    the k.ú. that hold the points.
    """
    kus = geo.read_kus(gpkg)
    to_wgs84 = geo.transformer()
    out = {}
    for code, groups in addresses.obce.items():
        if len(council.get(code, ())) < _SEVERAL and okrsky.get(code, 0) < _SEVERAL:
            continue
        places, points, sizes = [], [], []
        for (kind, name), houses in groups.items():
            sizes.append(((kind, name), len(houses)))
            street = name if kind == STREETS else ""
            for h in houses:
                places.append(obvody.Place(street, h.part, h.supisne, h.orientacne))
                points.append(h.point or (np.nan, np.nan))
        xy = np.array(points, dtype=float).reshape(-1, 2)
        located = np.flatnonzero(~np.isnan(xy[:, 0]))
        x, y = to_wgs84.transform(
            xy[located, 0] / SCALE,
            xy[located, 1] / SCALE,
            direction=TransformDirection.INVERSE,
        )
        within: list[str | None] = [None] * len(places)
        for _, name, polygon in kus.get(code, []):
            for i in located[shapely.intersects_xy(polygon, x, y)]:
                within[int(i)] = name
        out[code] = obvody.ObecPlaces(
            places, xy, within, [k[1] for k in kus.get(code, [])], sizes
        )
    return out


def assign_obvody(
    rule_sets: Mapping[str, obvody.RuleSet],
    council: Mapping[str, Sequence[int]],
    places: Mapping[str, obvody.ObecPlaces],
) -> tuple[dict[str, ObvodMap], list[str], dict[str, list[int]]]:
    """Return obec → the council obvod of each house, by the obec's rules.

    Also returns lines for the report, and obec → the obvod of each of its
    places. Fails listing every rule set that does not fit the candidate
    lists or leaves an address in no obvod or in two (see
    :func:`check_assignment`).
    """
    out: dict[str, ObvodMap] = {}
    units: dict[str, list[int]] = {}
    lines: list[str] = []
    errors: list[str] = []
    for code, rules in rule_sets.items():
        name = f"{rules.name} ({code})"
        if code not in places:
            errors.append(f"{name}: has rules, but not several council obvody")
            continue
        p = places[code]
        a = obvody.assign(rules, p.places, p.kus, p.planar())
        problems = check_assignment(rules, council.get(code, []), p, a)
        if problems:
            errors += [f"{name}: {x}" for x in problems]
            continue
        counts = Counter(a.units)
        lines.append(
            f"  {name:<36} {len(p.places):>7,} addresses: "
            + ", ".join(f"{n} {counts[n]:,}" for n in rules.seats)
            + (f"; {len(a.filled):,} by the nearest" if a.filled else "")
        )
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
        out[code] = _per_group(p.groups, a.units)
        units[code] = a.units
    if errors:
        raise AddressesError(
            "the council obvody by address do not fit:\n  " + "\n  ".join(errors)
        )
    return out, lines, units


def assign_okrsky(
    rule_sets: Mapping[str, obvody.RuleSet],
    places: Mapping[str, obvody.ObecPlaces],
    council: Mapping[str, Sequence[int]] | None = None,
) -> tuple[dict[str, ObvodMap], list[str]]:
    """Return obec → the okrsok of each house, where its okrsky are drawn.

    That is where the obec's rule set (:func:`election_map_slovakia.obvody.okrsok_rule_sets`)
    places every address in one okrsok, as ``geo`` draws them
    (:func:`election_map_slovakia.geo.address_cuts`). Also returns lines
    for the report, among them the rule sets that do not: ``geo`` fails on
    those, but the addresses are still written, for the jobs that fix them.
    *council* is obec → the obvod of each of its places where
    :func:`assign_obvody` has them already.
    """
    out: dict[str, ObvodMap] = {}
    lines: list[str] = []
    for code, rules in rule_sets.items():
        if not rules.okrsok_areas or code not in places:
            continue
        p = places[code]
        planar = p.planar()
        a = (council or {}).get(code)
        if a is None:
            a = obvody.assign(rules, p.places, p.kus, planar).units
        k = obvody.assign_okrsky(rules, p.places, a, p.kus, planar)
        problems = k.problems(p.places)
        if problems:
            lines.append(f"  {rules.name} ({code}), okrsky: " + "; ".join(problems))
            continue
        out[code] = _per_group(p.groups, k.units)
    lines.append(f"  okrsok of every address in {len(out)} obce")
    return out, lines


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
) -> list[str]:
    """Return why *assignment* of *places* by *rules* is not acceptable.

    The obvody must be those of the candidate lists (*council*), and every
    address in exactly one of them, each obvod with addresses.
    """
    if list(rules.seats) != list(council):
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


def write(result: Result, directory: Path) -> dict[str, tuple[int, int]]:
    """Replace *directory* with the files of *result*.

    Returns path → (bytes, gzip -9 bytes).
    """
    encoded = {}
    with (
        progress.stage(f"writing {directory.name}/", len(result.files)) as s,
        output.replacing(directory) as tmp,
    ):
        for path, content in s.track(sorted(result.files.items())):
            data = encoded[path] = output.to_json(content)
            (tmp / path).write_bytes(data)
    gzipped = output.gzip_sizes(list(encoded.values()))
    return {
        path: (len(data), gz)
        for (path, data), gz in zip(encoded.items(), gzipped, strict=True)
    }


def write_outside(result: Result, path: Path) -> None:
    """Write the points outside their obec as a tab-separated table."""
    obce = result.admin.obce
    lines = [
        "obec\tname\tplace\tnumber\tlon\tlat\tdistance_m\twithin\twithin_name"
        "\tpublished"
    ]
    for o in result.outside:
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _percentile(values: Sequence[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _obec(admin: Admin, code: str | None) -> str:
    return "none" if code is None else f"{admin.obce[code].name} ({code})"


def report(result: Result, sizes: Mapping[str, tuple[int, int]]) -> Iterator[str]:
    """Yield the human-readable summary lines of a written *result*."""
    admin, a = result.admin, result.addresses
    houses = Counter({c: sum(map(len, g.values())) for c, g in a.obce.items()})
    far = Counter(o.ref.obec for o in result.outside if o.distance > MAX_OUTSIDE)
    unlocated = Counter(
        {
            c: n
            for c, g in a.obce.items()
            if (n := sum(h.point is None for hs in g.values() for h in hs) - far[c])
        }
    )
    total = houses.total()
    yield (
        f"rows {a.rows:,}, {a.duplicates} exact duplicates dropped: {total:,}"
        f" addresses in {len(a.obce):,} obce"
    )
    yield (
        f"without coordinates {unlocated.total():,} ({unlocated.total() / total:.1%})"
        f" in {len(unlocated):,} obce, plus {result.dropped:,} points over"
        f" {MAX_OUTSIDE:.0f} m outside their obec not published; all kept for"
        f" search; top {TOP} without coordinates:"
    )
    for code, n in unlocated.most_common(TOP):
        yield f"  {_obec(admin, code):<40} {n:>6,} of {houses[code]:,}"

    by_status: Counter[str] = Counter()
    obce_by_status: Counter[str] = Counter()
    pending_by: Counter[str] = Counter()
    for code, n in houses.items():
        council = result.council.get(code, [])
        status = council_fields(council, code in result.assigned)["council"]
        by_status[status] += n
        obce_by_status[status] += 1
        if status == "pending":
            pending_by[code] = n
    no_council_obce = sorted(c for c in houses if c not in result.council)
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

    yield from _report_outside(result)
    yield from _report_sample(result)
    yield from _report_sizes(result, sizes)


def _report_outside(result: Result) -> Iterator[str]:
    admin = result.admin
    located = result.dropped + sum(
        h.point is not None
        for g in result.addresses.obce.values()
        for hs in g.values()
        for h in hs
    )
    labels = [*(f"≤ {b:,} m" for b in OUTSIDE_BINS), "more"]
    bins = Counter(
        next(
            (label for b, label in zip(OUTSIDE_BINS, labels) if o.distance <= b), "more"
        )
        for o in result.outside
    )
    yield (
        f"points outside their obec polygon (ZBGIS level 0):"
        f" {len(result.outside):,} of {located:,}; "
        + ", ".join(f"{k} {bins[k]:,}" for k in labels)
    )
    yield f"  not published (over {MAX_OUTSIDE:.0f} m): {result.dropped:,}"
    yield f"  farthest {TOP} (all in data/build/{OUTSIDE_FILE}):"
    for o in result.outside[:TOP]:
        yield (
            f"  {o.distance:>9,.0f} m  {_obec(admin, o.ref.obec)}, {o.ref.place}"
            f" {o.ref.house.number}; in {_obec(admin, o.within)}"
        )


def _report_sample(result: Result) -> Iterator[str]:
    admin = result.admin
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


def _report_sizes(
    result: Result, sizes: Mapping[str, tuple[int, int]]
) -> Iterator[str]:
    index = result.files["index.json"]
    yield "index.json by part:      bytes        gzip"
    for key in ("obce", STREETS, PARTS):
        raw = output.to_json(index[key])
        yield (
            f"  {key:<10} {len(index[key]):>6,} {format_size(len(raw)):>11}"
            f" {format_size(output.gzip_size(raw)):>11}"
        )
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
        name = _obec(result.admin, path.removesuffix(".json"))
        yield f"  {name:<40} {format_size(raw):>11} {format_size(gz):>11}"
