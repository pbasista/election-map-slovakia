"""Election results: the site's results files, from ŠÚ SR's data.

On election night (24–25 October 2026) ŠÚ SR publishes the count of the
municipal (OSO) and regional (OSK) elections on https://volbysr.sk/oso/
and https://volbysr.sk/osk/ as JSON files, which its own pages read and
which it overwrites as the commissions' records come in. A day or two
later the definitive results follow as CSV tables in a zip. Both are
written in the same format, apart: ``ems results poll`` turns the night's
files into the live results of the election in
``data/build/<election day>/live/`` (:meth:`Config.live_dir`), which
``ems results deploy`` deploys on the night as the live part
(``dist/live/<election day>/``); the ``results`` step of ``ems make`` turns
the pinned definitive packages into its final results in
``data/build/<election day>/results/`` (:meth:`Config.results_dir`), which
``build`` copies to ``dist/results/<election day>/``, the results part, and
a release deploys. The app reads the final results, and the live ones where
there are none yet (``web/js/live.js``)::

    status.json        {version, updated, phase, source: {<source>: {time,
                        counted, unit, voters}}, files}
    <area>.json        {contests: {contest: {status, counted, eligible,
                        voters, valid, seats, filled, candidates, (areas),
                        (won), (preferences), (units: {kraj, okres | zsk:
                        {code: [eligible, voters, valid, {number:
                        votes}]}}), (origins: {number: [most, highest]:
                        [[okrsok, votes, valid]]})}}}
    okrsky/<area>.json {contests: {contest: {okrsok: [eligible, voters,
                        valid, {number: votes}]}}, units: {contest:
                        {obvod | obec: {unit: figures}}}, past: {} | {day,
                        okrsky: {okrsok: method}, contests: {contest:
                        {okrsok | obec: [eligible, voters, valid,
                        {number: votes}]}}, totals, units: {contest:
                        {level: {unit: [method, figures]}}}}}
                                                     okrsok "500011/3"
    turnout.json       {municipal: {total, obce, councils, zsk | okres},
                        city: {total, obce, zsk | okres}, regional:
                        {total}}: [eligible, voters] each

The format is the shared contract of docs/results.md.

- ``<area>`` is the site's area file of the contest without ``data/``
  (:func:`live_path`, :func:`contests.area_name`): ``kraj/<k>``,
  ``city/<BA|KE>``, ``okres/<okres>``, ``country`` (the country-wide
  contests) or ``list/<p>`` (party p's list).
- ``candidates`` are ``[number, votes, flag]``: flag 1 elected, 0 a
  council's (or a party list's) substitute, :data:`WITHDRAWN` (-1) a
  candidate who withdrew yet stayed on the ballot (ŠÚ SR counts and
  publishes their votes), :data:`ADVANCED` (2) a presidential candidate on
  to round 2, else null; the national kinds' are in
  :mod:`election_map_slovakia.national`. A party contest's ``won`` has the
  seats of each party that won some.
- ``status.json`` names every area and okrsok file with a hash of its
  content, which the app appends to the URL. Its ``version`` changes
  whenever anything in it does; a run that changes nothing writes nothing
  (:func:`write`), so a deployment follows only a change. Its ``source``
  has an entry per source of the election's contests (:func:`sources_of`):
  ``oso`` (municipal), ``osk`` (regional), ``prez1``, ``prez2`` (a round of
  a presidential election), ``ref``, ``nrsr``, ``ep``; the phase is final
  once each has its definitive results (:func:`finalize`).
- Each election has a directory of its own, keyed by its day, so a later
  election's results never replace an earlier one's.
- The okrsok files (final results only) hold the area file's contests per
  okrsok (polling district), keyed ``<obec>/<okrsok>`` (:func:`okrsok_key`)
  in the obec's own numbering; Bratislava's and Košice's own contests in
  their districts'; the country-wide contests' by kraj,
  ``okrsky/country/<kraj>``, and a party's list's likewise,
  ``okrsky/list/<p>/<kraj>`` (:func:`okrsok_file`). ``past`` holds the
  figures of the election before (``day``) on these okrsky and their obce,
  the newest earlier one that held the file's contests (of a regular
  election, their half: 2022's municipal contests are 2018's, its regional
  ones 2017's, held apart then), as far as they are known (:class:`Past`,
  made by :mod:`election_map_slovakia.crosswalk`), ``{}`` where there is
  none (a party's list's always).
- The units the app shows a contest by, or the map colours, that are sums
  of finer ones are summed here, once, so that the app only reads them
  (:func:`render`): a country-wide contest's kraje and okresy, a regional
  president's regional obvody and a city contest's coarsest units
  (``units``, its ``areas`` summed, :func:`units_of`); in an okrsok file
  a council obvod's and an obec's okrsky (``units``,
  :func:`okrsok_units`) and in ``past`` the election before in an obec, a
  council obvod, a kraj, an okres, a regional obvod or the whole contest
  made of okrsky or obce (:func:`past_units`); the turnout of the
  municipal, the cities' and the regional elections as wholes, by obec and
  by coarse unit (:data:`TURNOUT_FILE`, :func:`turnout`). A party's list
  has its persons' preference votes summed beside the party's votes: the
  record's ``preferences``, and a fifth figure in each of its units
  (:func:`area_json`). :class:`Divisions` says where each obec lies, the
  regional council contests in which regional obvod (:func:`file_obvody`).
  A country-wide contest of persons (a president's round, a party's list)
  has the okrsky each of its candidates' votes came from most, by votes
  and by share (``origins``, :func:`origins`): its okrsky are in a file
  per kraj, which the candidate card would otherwise all have to load.

:func:`check` holds the files to the format, the sources to those of the
election (:class:`Expect`), and the votes to what they must add up to in
every unit counted (the contest, each of its ``areas`` and okrsky): in a
single-choice contest (a mayor, a president, a referendum's question, a
party contest) the candidates' votes are the valid ballots; in a council's
no candidate has more votes than there are valid ballots, nor all together
more than seats times those; on a party's list no person has more
preference votes than the party's votes, nor all together more than the
preferences a voter may give times those, and a final list's elected are
the first by the preference rule (:func:`preference_order`).

Sources:

- ``poll`` (:class:`Poller`, :func:`night`): the night's JSON of a
  municipal and regional election (the other kinds' night files differ;
  their results come final only). The progress
  files (``tab01.json``, ``dateSK.json`` of each election) are fetched
  every interval with conditional requests; only when one changed are the
  per-unit files fetched (:func:`unit_paths`):

  - regional: the turnout per kraj, obvod and municipality (``tab02ba``,
    ``tab02bb/<kraj>``, ``tab02bc/<obvod>``), the votes per kraj and obvod
    (``tab06b/<kraj>``, ``tab06c/<obvod>``, ``tab09c/<obvod>``), and a
    municipality's votes (``tab06d/<obec>``, ``tab09d/<obec>``) once its
    okrsky are all counted, then not again until every okrsok is;
  - municipal: each municipality's summary (``graph01/<obec>``: turnout,
    the elected mayor by name, the council seats filled) until it is
    fully counted, the mayor candidates of Bratislava and Košice
    (``tab05/<obec>``) and, once a municipality is fully counted, its
    mayor and council candidates (``tab05``, ``tab06e1`` elected,
    ``tab06e2`` all) until they have come, then not again until every
    municipality is.

  A file missing (404) is a unit not counted yet. Files due once others
  show their unit fully counted are fetched in a second round of the same
  poll. A mayor elected before the candidates' votes have come is known by
  name only; :func:`match_winner` finds the ballot number. Every fetched
  file is kept under ``data/raw/results/<UTC time>/``.
- ``final`` (:func:`read_final`): the definitive CSV tables, the zips
  ``oso/files/OSO<year>_SK_csv.zip`` and ``osk/files/OSK<year>_SK_csv.zip``
  of volbysr.sk, pinned as inputs of ``config/inputs.toml`` that
  ``config/elections.toml`` names as the election's ``results``, which the
  results step of ``ems make`` reads, so a release's results are a pure
  function of its inputs like every other file. The tables summed per
  municipality, council obvod, kraj and regional obvod give the contests;
  those per okrsok the okrsok files and the two cities' own contests by
  district (the city's okrsky found among the districts' by
  :func:`city_matches`, okrsky of a number told apart by their shares by
  :func:`city_votes`). The tables and columns read are named per election
  (:data:`_FINAL_TABLES`) and checked; the results are written only if
  they pass :func:`check`.
- ``by-election`` (:func:`read_by_election`): ŠÚ SR's package of the
  municipal by-elections held on one day (format ``susr-by``), XLSX tables
  of the 2026 tables' columns, read the same way; those of 2019–2022
  (:func:`older_by_election`) have no okrsky and of the councils the
  elected only.
- national: the tables of a presidential election, a referendum or an
  election to the NR SR or the European Parliament, read by
  :mod:`election_map_slovakia.national`.
- ``fake`` (:func:`fake`): plausible, deterministic dummy results from the
  candidate lists of a municipal and regional election or a by-election
  (:func:`national.fake` the national kinds') for testing the app, with
  okrsky at ``final``, written as live results.

The column meanings of the night's JSON (``_GRAPH``, ``_OSK_TURNOUT``,
``_BALLOT``, ``_COUNCIL_BALLOT``) are those of the 2026 site scripts
(``functions.js`` of oso/ and osk/), checked against the 2018 and 2022
files where the tables existed then.

The module also summarizes a results directory (:func:`describe`).
"""

from __future__ import annotations

import csv
import datetime as dt
import functools
import gzip
import hashlib
import heapq
import http
import http.client
import io
import itertools
import json
import math
import random
import re
import ssl
import threading
import urllib.parse
import zipfile
from collections import Counter, defaultdict
from collections.abc import (
    Callable,
    Collection,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from functools import partial
from operator import attrgetter, itemgetter
from pathlib import Path
from typing import Any, NamedTuple, TypeVar
from zoneinfo import ZoneInfo

import orjson

from election_map_slovakia import (
    bundle,
    candidates,
    contests as kinds,
    fetch,
    geo,
    output,
    progress,
    tables,
)

RAW_DIR = "results"
"""Below ``data/raw/``: every file ``poll`` fetched, per poll."""
STATUS_FILE = "status.json"
INTERVAL = 60
"""Seconds between polls."""
BASE_URL = "https://volbysr.sk"
CONCURRENCY = 8
"""Requests to volbysr.sk at a time."""
TIMEOUT = 30
"""Seconds a request may take."""
PHASES = ("none", "partial", "final")
STATUSES = ("partial", "winner", "final")
TIMEZONE = ZoneInfo("Europe/Bratislava")
CITY_OBCE = {"582000": "BA", "599981": "KE"}
"""ŠÚ SR's municipality codes of Bratislava and Košice as wholes."""
OBEC_OF_CITY = {city: obec for obec, city in CITY_OBCE.items()}
PROGRESS_FILES = (
    "oso/json/tab01.json",
    "oso/json/dateSK.json",
    "osk/json/tab01.json",
    "osk/json/dateSK.json",
)
CITY_LIST = "oso/json/tab0dx.json"
"""Bratislava and Košice with their okrsky (C05)."""
_HASH = 8
"""Hex digits of a file's hash in ``status.json``."""
_VERSION_HASH = 4
"""Hex digits of the hash in a ``version``."""
_FULL = 100.0
"""Per cent counted of a fully counted municipality."""
# The night's tables. graph01/<obec>: one row per municipality.
_GRAPH = {
    "processed": "C03",  # per cent of the okrsky counted, a number
    "eligible": "C04",
    "voters": "C05",  # envelopes issued
    "returned": "C07",
    "valid_mayor": "C09",
    "valid_council": "C10",
    "mayor": "C11",  # the elected mayor's name, empty until known
    "party": "C12",
    "votes": "C13",
    "seats": "C15",
    "filled": "C16",
    "type": "C17",  # 0 no election, 1 both, 2 mayor only, 3 council only
}
_MAYOR_HELD = frozenset({1, 2})
_COUNCIL_HELD = frozenset({1, 3})
# tab02b{a,b,c}: turnout per kraj, obvod, municipality, one row each, named
# (not coded) in C01.
_OSK_TURNOUT = {
    "total": "C03",  # okrsky
    "processed": "C04",
    "eligible": "C06",
    "voters": "C07",
    "predseda": "C11",  # valid ballots for the president
    "zsk": "C12",  # valid ballots for the council
}
# Candidates' votes (oso tab05, osk tab06*, tab09*): ballot number, votes,
# the "zvolený" label.
_BALLOT = ("C01", "C05", "C07")
# Council candidates (oso tab06e1 elected, tab06e2 all): ballot number,
# votes, obvod in the municipality.
_COUNCIL_BALLOT = ("C01", "C06", "C05")
_ELECTED = "zvolen"
_WITHDRAWN_LABEL = "x"
WITHDRAWN = -1
"""The flag of a candidate who withdrew (``X``) in a record's candidates:
still on the ballot, their votes counted among the valid ones, never
elected."""
ADVANCED = 2
"""The flag of a candidate who goes on to round 2 of a presidential
election: round 1 elected nobody, and they are among its two best."""
_OBVOD_NAME = re.compile(r"^\s*(\d+)\.|č\.\s*(\d+)")
_NUMBER_GAPS = re.compile(r"[\s\u00a0\u202f]+")
_TIME = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([^\W\d_]+)?"
)
# ŠÚ SR writes the time zone after the time: summer (SELČ, CEST) or winter
# (SEČ, CET) time; the clocks go back at 03:00 on 25 October 2026.
_ZONES = {"SELČ": 2, "CEST": 2, "SEČ": 1, "CET": 1}
_AREA_KEY = re.compile(r"\d{6}|obvod:[1-9]\d*")
_OKRSOK_KEY = re.compile(r"\d{6}/[1-9]\d*")
OKRSKY_DIR = "okrsky"
"""The okrsok files: ``okrsky/<area>``, beside the area files; a country-wide
contest's by kraj, ``okrsky/country/<kraj>`` or ``okrsky/list/<p>/<kraj>``
(:func:`okrsok_file`)."""
_COUNTRY = "country"
"""The area file of the country-wide contests (:func:`contests.area_name`)."""
_LIST = "list/"
"""The prefix of a party's list's area file, ``list/<p>`` (:func:`contests.area_name`)."""
_OKRES = "okres/"
"""The prefix of the area file of an okres's municipal contests, ``okres/<o>``."""
_KRAJ = "kraj/"
"""The prefix of a kraj's area file, ``kraj/<k>``, of its regional contests."""
_CITY = "city/"
"""The prefix of Bratislava's and Košice's own area files, ``city/<BA|KE>``."""
TURNOUT_FILE = "turnout"
"""The file of the turnout of the municipal, the two cities' and the
regional elections as wholes and by coarse unit (:func:`turnout`), beside
the area files."""
_OBEC_KEY = re.compile(r"\d{6}")
UNKNOWN = 0
"""``past`` method of an okrsok whose earlier figures are not known: the
okrsky changed, and neither their addresses nor their numbers tell how."""
SAME = 1
"""``past`` method of an okrsok of the same area as one of the earlier
election, by the okrsky of their addresses then and now."""
IDENTITY = 2
"""``past`` method of an okrsok taken for the earlier one of its number:
the obec's okrsky have the same numbers and registered voters as then."""
APPROXIMATE = 3
"""``past`` method of an okrsok whose earlier figures are estimated from
the earlier okrsky its addresses were in."""
PAST_METHODS = (UNKNOWN, SAME, IDENTITY, APPROXIMATE)
PAST_DOUBT = (SAME, IDENTITY, APPROXIMATE, UNKNOWN)
"""The methods from the most certain: several okrsky together are as
certain as the least certain of them."""
_RECORD_KEYS = frozenset(
    {"status", "counted", "eligible", "voters", "valid", "seats", "filled"}
    | {"candidates"}
)
"""The keys of every record; ``areas`` and (party contests) ``won`` are
optional."""


class ResultsError(Exception):
    """Results cannot be read or written."""


Log = Callable[[str], None]
_T = TypeVar("_T")


# Numbers and times as ŠÚ SR writes them.


def decimal(value: object) -> float | None:
    """Return a number as ŠÚ SR writes it, or None if there is none.

    Counts come as strings with spaces between thousands (``"2 921"``),
    shares with a decimal comma and maybe a per cent sign (``"43,74 %"``),
    some as JSON numbers (``36.54``, ``45.0``); an empty string (a value not
    known yet) or a mark such as ``"X"`` is None.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = _NUMBER_GAPS.sub("", str(value)).removesuffix("%").replace(",", ".")
    try:
        result = float(text)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def number(value: object) -> int | None:
    """Return a count as ŠÚ SR writes it (see :func:`decimal`), or None."""
    result = decimal(value)
    return None if result is None else round(result)


def source_time(text: object) -> str | None:
    """Return ŠÚ SR's time ``24.10.2026 21:40:00 SELČ`` as ISO 8601, or None.

    The zone named after the time gives the offset; without one (as in
    2022) the time is Slovak local time.
    """
    m = _TIME.search(str(text or ""))
    if m is None:
        return None
    day, month, year, hour, minute, second, zone = m.groups()
    try:
        local = dt.datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second or 0)
        )
    except ValueError:
        return None
    hours = _ZONES.get((zone or "").upper())
    tz = TIMEZONE if hours is None else dt.timezone(dt.timedelta(hours=hours))
    return local.replace(tzinfo=tz).isoformat()


def vobvod(kraj: str, obvod: int) -> str:
    """Return ŠÚ SR's code of regional obvod *obvod* of *kraj*: 1, 5 → ``105``."""
    return f"{kraj}{obvod:02d}"


# What the candidate lists say about the contests.


@dataclass(frozen=True)
class Candidate:
    """A candidate as the night's names are matched against."""

    number: int
    name: str
    """:func:`candidates.search_key` of first name and surname."""
    parties: tuple[str, ...]
    """Search keys of the parties."""
    independent: bool


@dataclass(frozen=True)
class Subject:
    """A ballot subject (party or coalition) of a party-list contest."""

    number: int
    party: str
    """Its key in ``config/parties.toml``."""
    candidates: int
    """The persons on its list."""
    threshold: float
    """The share of the valid votes, in per cent, it needs for seats
    (:func:`contests.subject_threshold`)."""


@dataclass(frozen=True)
class Contest:
    """A contest of the candidate lists."""

    id: str
    kind: str
    area: str
    obvod: int | None
    """The ``/<sub>`` of its id: obvod, round, question or a party's number."""
    path: str
    """Its live area file (:func:`live_path`)."""
    seats: int | None
    """Seats elected, where known before the election."""
    past: tuple[int, int] | None
    """Eligible and voters of its area in its last election (``past``)."""
    subjects: tuple[Subject, ...] = ()
    """A party contest's ballot subjects."""
    preferences: int | None = None
    """A party contest's: how many persons of one list a voter may mark."""
    quota: float | None = None
    """A party contest's: the share of a party's votes, in per cent, that a
    person's preference votes must reach to go ahead of the list order."""
    day: str | None = None
    """Round 2 of a presidential election: its ISO day."""

    @property
    def single(self) -> bool:
        """Whether a voter marks one of its candidates."""
        return kinds.parse(self.id).single


@dataclass(frozen=True)
class Place:
    """A municipality (or Bratislava or Košice as a whole)."""

    code: str
    name: str
    kraj: str
    city: str | None
    """BA or KE for a district of the city."""
    zsk: int | None
    """Its regional obvod; 0 where the election has none, None for
    Bratislava and Košice as wholes, which have no map properties."""
    city_obvod: int | None
    """Its city council obvod, for a district of Bratislava or Košice."""
    past: tuple[int, int] | None
    """Eligible and voters in the 2022 regional election."""


@dataclass(frozen=True)
class Divisions:
    """Where each obec lies, as the app's ``data/index.json`` has it.

    What the results sum their units by (:func:`render`): the okres and kraj
    of a country-wide contest's obce, the council obvody of an obec's okrsky.
    """

    okres: Mapping[str, str]
    """Obec → its okres; "" for Bratislava and Košice as wholes, in none."""
    kraj: Mapping[str, str]
    """Obec → its kraj."""
    split: frozenset[str]
    """The obce of several council obvody (``data/index.json`` ``councils``
    above 1): of more than one council contest, or a by-election's whose
    council contests are part of a larger council
    (:func:`election_map_slovakia.addresses.council_parts`: an obvod above
    1, or obvod 1 of a council its term elected in several)."""

    @classmethod
    def of(cls, data: Mapping[str, Any], parts: Collection[str]) -> Divisions:
        """Return the divisions of ``candidates.json`` *data*.

        *parts* are the obce whose council contests are part of a larger
        council (:func:`election_map_slovakia.addresses.council_parts`).
        """
        councils = Counter(
            str(c["area"]) for c in data["contests"] if c["kind"] == "oz"
        )
        return cls(
            {o["code"]: o.get("okres", "") for o in data["obce"]},
            {o["code"]: o["kraj"] for o in data["obce"]},
            frozenset(code for code, n in councils.items() if n > 1) | frozenset(parts),
        )


@dataclass(frozen=True)
class Reference:
    """The contests, candidates and places the results are normalized to."""

    contests: dict[str, Contest]
    candidates: dict[str, tuple[Candidate, ...]]
    """Contest → its candidates."""
    places: dict[str, Place]
    kraje: dict[str, str]
    """Kraj code → name."""
    municipal: dict[str, tuple[Contest | None, tuple[Contest, ...]]]
    """Municipal area → its mayor contest and council contests (by obvod)."""
    regional: dict[str, tuple[Contest | None, tuple[Contest, ...]]]
    """Kraj → its president contest and council contests (by obvod)."""
    sources: frozenset[str]
    """The ``source`` keys of ``status.json`` (:func:`sources_of`)."""
    divisions: Divisions
    """The units the results are summed by (:func:`render`)."""


def live_path(contest: str, okres_of: Mapping[str, str]) -> str:
    """Return the results area file of *contest*: :func:`contests.area_name`.

    The site's area file without ``data/`` and ``.json``, as the app's
    ``areaPath`` names it; *okres_of* maps an obec to its okres.
    """
    return kinds.area_name(contest, okres_of)


def okrsok_file(path: str, kraj: str) -> str:
    """Return the okrsok file of the contests of area file *path* in *kraj*.

    A country-wide contest's okrsky are split by kraj (``country/<kraj>``, a
    party's list's ``list/<p>/<kraj>``), which keeps a file the size of a
    regional one; any other contest's okrsky are in the file of its area
    (*path*).
    """
    return f"{path}/{kraj}" if path == _COUNTRY or path.startswith(_LIST) else path


def area_of_okrsok_file(path: str) -> str:
    """Return the area file of the contests of okrsok file *path* (no prefix)."""
    by_kraj = path.startswith((f"{_COUNTRY}/", _LIST))
    return path.rpartition("/")[0] if by_kraj else path


def sources_of(ids: Iterable[str]) -> frozenset[str]:
    """Return the ``source`` keys of the results of contests *ids*.

    ``oso`` (municipal), ``osk`` (regional), ``prez1``, ``prez2`` (each round
    of a presidential election), ``ref``, ``nrsr``, ``ep``
    (:func:`contests.source_of`).
    """
    return frozenset(kinds.source_of(c) for c in ids)


def reference(
    data: Mapping[str, Any],
    props: Mapping[str, Mapping[str, Any]],
    seats: Mapping[str, int],
    members: Mapping[str, int] | None = None,
    *,
    parts: Collection[str],
) -> Reference:
    """Return the :class:`Reference` of ``candidates.json`` *data*.

    *props* are the municipalities' :func:`bundle.obec_props`, *seats* the
    known seats per obvod contest (:func:`bundle.obvod_seats`), else those
    of the contest in *data* (a by-election's council); *members* the
    member parties' count of each coalition by its party key
    (``config/parties.toml``), which sets its threshold; *parts* as
    :meth:`Divisions.of` takes them.
    """
    okres_of = {o["code"]: o.get("okres", "") for o in data["obce"]}
    regional_past = bundle.regional_past(data, props)
    found = {}
    for c in data["contests"]:
        past = c.get("past") or regional_past.get(c["id"])
        single = kinds.parse(c["id"]).single
        known = seats.get(c["id"], c.get("seats", 1 if single else None))
        found[c["id"]] = Contest(
            c["id"],
            c["kind"],
            str(c["area"]),
            c.get("obvod"),
            live_path(c["id"], okres_of),
            known,
            (past["eligible"], past["voters"]) if past else None,
            tuple(
                Subject(
                    s["number"],
                    s["party"],
                    s.get("candidates", 0),
                    kinds.subject_threshold(c, (members or {}).get(s["party"], 0)),
                )
                for s in c.get("subjects", ())
            ),
            c.get("preferences"),
            c.get("quota"),
            c.get("day"),
        )
    # A party's name repeats over its candidacies: keyed once.
    party_key = functools.cache(candidates.search_key)
    by_contest: dict[str, list[Candidate]] = defaultdict(list)
    for c in data["candidacies"]:
        by_contest[c["contest"]].append(
            Candidate(
                c["number"],
                candidates.search_key(f"{c['first_name']} {c['surname']}"),
                tuple(party_key(p) for p in c["parties"]),
                bool(c.get("independent")),
            )
        )
    places = {o["code"]: _place(o, props.get(o["code"], {})) for o in data["obce"]}
    return Reference(
        found,
        {k: tuple(v) for k, v in by_contest.items()},
        places,
        {k["code"]: k["name"] for k in data["kraje"]},
        _bodies(found.values(), "starosta", "oz"),
        _bodies(found.values(), "predseda", "zsk"),
        sources_of(found),
        Divisions.of(data, parts),
    )


def _place(o: Mapping[str, Any], props: Mapping[str, Any]) -> Place:
    past = o.get("past")
    return Place(
        o["code"],
        o["name"],
        o["kraj"],
        o.get("city"),
        props.get("zsk"),
        props.get("city_obvod"),
        (past["eligible"], past["voters"]) if past else None,
    )


def _bodies(
    contests: Iterable[Contest], single: str, council: str
) -> dict[str, tuple[Contest | None, tuple[Contest, ...]]]:
    heads: dict[str, Contest] = {}
    members: dict[str, list[Contest]] = defaultdict(list)
    for c in contests:
        if c.kind == single:
            heads[c.area] = c
        elif c.kind == council:
            members[c.area].append(c)
    return {
        area: (
            heads.get(area),
            tuple(sorted(members[area], key=lambda c: c.obvod or 0)),
        )
        for area in sorted(heads.keys() | members.keys())
    }


def load_reference(
    build_dir: Path,
    election_dir: Path,
    members: Mapping[str, int],
    parts: Collection[str],
) -> Reference:
    """Return the :class:`Reference` of the built candidates and geometry.

    *build_dir* is the election's build directory
    (:meth:`election_map_slovakia.config.Config.election_build_dir`),
    *election_dir* its curated data
    (:meth:`election_map_slovakia.config.Config.election_dir`), *members*
    and *parts* as :func:`reference` takes them.
    """
    data_path = build_dir / candidates.OUTPUT_FILE
    geo_dir = build_dir / geo.OUTPUT_DIR
    for path in (data_path, geo_dir):
        if not path.exists():
            raise ResultsError(f"{path} missing; run `ems make` first")
    return reference(
        orjson.loads(data_path.read_bytes()),
        bundle.obec_props(geo_dir),
        bundle.obvod_seats(geo_dir, election_dir),
        members,
        parts=parts,
    )


def match_winner(cands: Sequence[Candidate], name: str, party: str) -> int | None:
    """Return the ballot number of the candidate named *name*, or None.

    The night's municipal results name the elected mayor (and party) but
    not the ballot number. Names are compared by :func:`candidates.search_key`
    without titles (words with a dot), first in order, then as a set of
    words; several candidates of the same name are told apart by *party*.
    None if no candidate or several fit.
    """
    words = [w for w in name.replace(",", " ").split() if "." not in w]
    key = candidates.search_key(" ".join(words))
    found = [c for c in cands if c.name == key] or [
        c for c in cands if sorted(c.name.split()) == sorted(key.split())
    ]
    if len(found) > 1:
        wanted = candidates.search_key(party)
        found = [c for c in found if _party_fits(c, wanted)]
    return found[0].number if len(found) == 1 else None


def _party_fits(c: Candidate, party: str) -> bool:
    if not party:
        return False
    # ŠÚ SR calls independent candidates NEKA (nezávislý kandidát).
    if party in ("neka", "nezavisly kandidat", "nezavisla kandidatka"):
        return c.independent
    return any(party in p or p in party for p in c.parties)


# The results files.

Area = tuple[int | None, int | None, int | None, dict[int, int]]
"""Eligible, voters, valid and votes per ballot number of a sub-unit."""
Ballot = tuple[int, int, int | None]
"""Ballot number, votes, flag (1 elected, 0 substitute, :data:`WITHDRAWN`,
:data:`ADVANCED`, None)."""


@dataclass
class Record:
    """A contest's entry of a live area file; see the module doc."""

    status: str
    counted: tuple[int, int] | None = None
    eligible: int | None = None
    voters: int | None = None
    valid: int | None = None
    seats: int | None = None
    filled: int | None = None
    candidates: list[Ballot] = field(default_factory=list)
    areas: dict[str, Area] | None = None
    won: dict[int, int] | None = None
    """A party contest's seats per party that won some."""

    def to_json(self, *, preferences: bool = False) -> dict[str, Any]:
        """Return the record as written, candidates by votes.

        A party's list's (*preferences*) has its persons' preference votes
        summed too: the whole list's ``preferences``, and of each of its
        ``areas`` a fifth figure (:func:`area_json`).
        """
        out: dict[str, Any] = {
            "status": self.status,
            "counted": list(self.counted) if self.counted else None,
            "eligible": self.eligible,
            "voters": self.voters,
            "valid": self.valid,
            "seats": self.seats,
            "filled": self.filled,
            "candidates": [
                list(c) for c in sorted(self.candidates, key=lambda c: (-c[1], c[0]))
            ],
        }
        if preferences:
            out["preferences"] = sum(c[1] for c in self.candidates)
        if self.areas is not None:
            out["areas"] = {
                key: area_json(a, preferences=preferences)
                for key, a in sorted(self.areas.items())
            }
        if self.won is not None:
            out["won"] = {str(n): seats for n, seats in sorted(self.won.items())}
        return out

    @classmethod
    def from_json(cls, entry: Mapping[str, Any]) -> Record:
        """Return the record of a written *entry*."""
        areas = entry.get("areas")
        won = entry.get("won")
        counted = entry["counted"]
        return cls(
            entry["status"],
            (counted[0], counted[1]) if counted else None,
            entry["eligible"],
            entry["voters"],
            entry["valid"],
            entry["seats"],
            entry["filled"],
            [(c[0], c[1], c[2]) for c in entry["candidates"]],
            None if areas is None else {k: area_of_json(a) for k, a in areas.items()},
            None if won is None else {int(n): s for n, s in won.items()},
        )


def area_json(area: Area, *, preferences: bool = False) -> list[Any]:
    """Return *area* as written: votes keyed by the ballot number as text.

    A party's list's (*preferences*) has a fifth figure, its persons'
    preference votes summed, which the app shows beside the party's votes.
    """
    e, v, valid, votes = area
    out = [e, v, valid, {str(n): x for n, x in sorted(votes.items())}]
    if preferences:
        out.append(sum(votes.values()))
    return out


def area_of_json(entry: Sequence[Any]) -> Area:
    """Return the :data:`Area` of a written *entry*.

    A party's list's fifth figure, its votes summed, is not kept: it is
    made again when written (:func:`area_json`).
    """
    e, v, valid, votes = entry[:4]
    return (e, v, valid, {int(n): x for n, x in votes.items()})


def sum_areas(areas: Iterable[Area]) -> Area:
    """Return the figures of *areas* added up, a missing figure as 0."""
    eligible = voters = valid = 0
    votes: Counter[int] = Counter()
    for e, v, b, x in areas:
        eligible += e or 0
        voters += v or 0
        valid += b or 0
        votes.update(x)
    return (eligible, voters, valid, dict(votes))


def okrsok_key(obec: str, okrsok: str | int) -> str:
    """Return the key of okrsok *okrsok* of *obec* in the okrsok files: ``obec/n``."""
    return f"{obec}/{int(okrsok)}"


def source(
    time: str | None,
    counted: tuple[int, int] | None,
    unit: str,
    voters: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Return a ``source`` entry of ``status.json``."""
    return {
        "time": time,
        "counted": list(counted) if counted else None,
        "unit": unit,
        "voters": list(voters) if voters else None,
    }


def source_unit(name: str) -> str:
    """Return what source *name* counts: ``obce`` (municipal), else ``okrsky``."""
    return "obce" if name == "oso" else "okrsky"


def no_sources(names: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Return the ``source`` of ``status.json`` before any of *names* counted."""
    return {name: source(None, None, source_unit(name)) for name in sorted(names)}


@dataclass
class Past:
    """An election before on this one's okrsky and obce (``past``).

    Made by :mod:`election_map_slovakia.crosswalk`, one per election before
    (:attr:`Live.past`); empty (``day`` "") where nothing of it is known.
    """

    day: str = ""
    """ISO day of the election before."""
    methods: dict[str, int] = field(default_factory=dict)
    """:func:`okrsok_key` → how its figures were found (:data:`PAST_METHODS`),
    for every okrsok of an obec of several okrsky then or now; the okrsok
    of an obec of one both times is that obec."""
    contests: dict[str, dict[str, Area]] = field(default_factory=dict)
    """Contest → :func:`okrsok_key` (an okrsok whose method is not
    :data:`UNKNOWN`) or obec code (a whole obec of the contest's area) → the
    figures of the election before there, the votes by this election's
    ballot numbers of the candidates who stood for the same office then."""
    totals: dict[str, Area] = field(default_factory=dict)
    """Contest that is its own counterpart (:func:`contests.counterpart`: no
    obvod nor list, its area the same in both elections) → the figures of
    the same contest then, the votes as in
    :attr:`contests`: the contest as a whole, which its units then need not
    add up to where some are not known."""


@dataclass
class Live:
    """Everything the results hold: phase, sources, area and okrsok files."""

    phase: str
    source: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Source (:func:`sources_of`) → its ``status.json`` entry (:func:`source`)."""
    files: dict[str, dict[str, Record]] = field(default_factory=dict)
    """Area file → contest → record."""
    okrsky: dict[str, dict[str, dict[str, Area]]] = field(default_factory=dict)
    """Okrsok file without ``okrsky/`` (:func:`okrsok_file`, the area file
    but for a country-wide contest's) → contest → :func:`okrsok_key` → its
    figures (final only)."""
    past: dict[str, Past] = field(default_factory=dict)
    """Source (:func:`sources_of`) → the election before its contests are
    compared with, the sources compared with one sharing its :class:`Past`
    (2022's ``oso`` the municipal election of 2018, its ``osk`` the
    regional one of 2017); none where there is none (:func:`past_of`)."""

    def add(self, path: str, contest: str, record: Record) -> None:
        """Put *record* of *contest* into area file *path*."""
        self.files.setdefault(path, {})[contest] = record

    def add_okrsky(self, path: str, contest: str, areas: dict[str, Area]) -> None:
        """Put the okrsky *areas* of *contest* into okrsok file *path*."""
        self.okrsky.setdefault(path, {})[contest] = areas

    def records(self) -> dict[str, Record]:
        """Return contest → record of every area file."""
        return {c: r for contests in self.files.values() for c, r in contests.items()}

    def part(self, sources: Collection[str]) -> Live:
        """Return its contests of *sources* alone, without ``past``."""
        return Live(
            self.phase,
            {s: entry for s, entry in self.source.items() if s in sources},
            {
                path: mine
                for path, contests in self.files.items()
                if (
                    mine := {
                        c: r
                        for c, r in contests.items()
                        if kinds.source_of(c) in sources
                    }
                )
            },
            {
                path: mine
                for path, contests in self.okrsky.items()
                if (
                    mine := {
                        c: a
                        for c, a in contests.items()
                        if kinds.source_of(c) in sources
                    }
                )
            },
        )


def past_of(live: Live, path: str, contests: Iterable[str]) -> Past | None:
    """Return the election before okrsok file *path*'s *contests* are compared with.

    None where none: no election before of their kind. A file's contests
    are of one half of a regular election (a kraj's regional, an okres's or
    a city's municipal) or of one election of another kind, so of one
    election before; a file of several would need one ``past`` each.
    """
    found = {
        id(p): p
        for c in contests
        if (p := live.past.get(kinds.source_of(c))) is not None
    }
    if len(found) > 1:
        raise ValueError(f"{path}: contests compared with several elections")
    return next(iter(found.values()), None)


def render(live: Live, divisions: Divisions) -> dict[str, bytes]:
    """Return file → content, of the area and okrsok files with a contest.

    A record with ``areas`` has the units made of them too (:func:`units_of`):
    a country-wide contest's kraje and okresy, a regional president's
    regional obvody, a city contest's coarse units. A country-wide contest
    of persons with okrsky has the okrsky its candidates' votes came from
    most (:func:`origins`). An okrsok file has the
    units of its contests made of its okrsky (:func:`okrsok_units`), and
    the ``past`` of its contests and of the okrsky in them, of the election
    before they are compared with (:func:`past_of`), with that of the
    units made of them (:func:`past_units`). The turnout of the elections
    of many contests has a file of its own (:func:`turnout`). *divisions*
    says where each obec lies, the regional council contests in which
    regional obvody (:func:`file_obvody`).
    """
    obvody = file_obvody(
        {
            path: {c: r.areas or {} for c, r in contests.items()}
            for path, contests in live.files.items()
        },
        divisions,
    )
    spread = contest_okrsky(live.okrsky)
    out = {
        path: bundle.encode(
            {
                "contests": {
                    c: _record_json(c, r, divisions, obvody[path], spread.get(c))
                    for c, r in contests.items()
                }
            }
        )
        for path, contests in sorted(live.files.items())
        if contests
    }
    records = live.records()
    councils = council_of(live.okrsky, divisions.split)
    for path, contests in sorted(live.okrsky.items()):
        keys = {k for areas in contests.values() for k in areas}
        if not keys:
            continue
        then = past_of(live, path, contests)
        past = _past_json(then, contests, keys) if then else {}
        if past:
            obce = {c: r.areas for c in contests if (r := records.get(c)) and r.areas}
            past["units"] = past_units(
                past,
                contests,
                obce,
                councils,
                divisions,
                obvody.get(area_of_okrsok_file(path), {}),
            )
        with_areas = {
            c: (r := records.get(c)) is not None and r.areas is not None
            for c in contests
        }
        units = okrsok_units(contests, with_areas, councils)
        out[f"{OKRSKY_DIR}/{path}"] = bundle.encode(
            {
                "contests": {
                    c: {k: area_json(a, preferences=_is_list(c)) for k, a in o.items()}
                    for c, o in contests.items()
                },
                "units": {c: _units_json(c, u) for c, u in units.items()},
                "past": past,
            }
        )
    figures = turnout(live.files, divisions, regional_units(obvody))
    if figures:
        out[TURNOUT_FILE] = bundle.encode(figures)
    return out


def _is_list(contest: str) -> bool:
    """Whether *contest* is a party's list, whose figures carry their sum."""
    return kinds.parse(contest).is_list


def _units_json(contest: str, units: Mapping[str, Mapping[str, Area]]) -> Any:
    """Return *units* (level → unit → figures) of *contest* as written."""
    listed = _is_list(contest)
    return {
        level: {u: area_json(a, preferences=listed) for u, a in by_unit.items()}
        for level, by_unit in units.items()
    }


def _record_json(
    contest: str,
    record: Record,
    divisions: Divisions,
    obvody: Mapping[str, str],
    okrsky: Mapping[str, Area] | None,
) -> dict[str, Any]:
    """Return *record* of *contest* as written, with its ``units`` if any.

    *okrsky* are all its okrsky (:func:`contest_okrsky`), whose units its
    candidates' votes came from most are its ``origins``, if any.
    """
    out = record.to_json(preferences=_is_list(contest))
    units = units_of(contest, record.status, record.areas, divisions, obvody)
    if units is not None:
        out["units"] = _units_json(contest, units)
    found = origins(okrsky) if okrsky else None
    if found:
        out["origins"] = found
    return out


ORIGINS = 5
"""Okrsky ``origins`` lists each way (web/js/candidate.js ``ORIGINS``)."""
ORIGIN_VALID = 30
"""Valid ballots of the okrsky ``origins`` lists by share, where two or more
have as many: the share of a handful of ballots says little
(web/js/candidate.js ``ORIGIN_VALID``)."""


def _has_origins(contest: str) -> bool:
    """Whether *contest* has ``origins``: a country-wide contest of persons.

    A president's round or a party's list, whose okrsky are in a file per
    kraj; a card shows a person, not a party nor an answer.
    """
    c = kinds.parse(contest)
    return c.kind.scope == "country" and (c.is_list or c.kind.sub == "round")


def contest_okrsky(
    files: Mapping[str, Mapping[str, Mapping[str, Area]]],
) -> dict[str, dict[str, Area]]:
    """Return contest → all its okrsky of okrsok *files*, of those with ``origins``.

    *files* as :attr:`Live.okrsky`: a contest's okrsky in one file per kraj.
    """
    out: dict[str, dict[str, Area]] = defaultdict(dict)
    for contests in files.values():
        for c, areas in contests.items():
            if _has_origins(c):
                out[c].update(areas)
    return dict(out)


def origins(okrsky: Mapping[str, Area]) -> dict[str, list[list[list[Any]]]]:
    """Return where each candidate's votes in *okrsky* came from most.

    Number → [most, highest]: the :data:`ORIGINS` okrsky with the most of
    their votes and those with the highest share of the valid ballots (of
    the okrsky with at least :data:`ORIGIN_VALID`, where two or more have
    as many), each ``[okrsok, votes, valid]``, ties by okrsok; only the
    okrsky where they got votes. Nothing for a contest of fewer than two
    okrsky with valid ballots, as the card then lists none.
    """
    counted = [(key, a[2], a[3]) for key, a in sorted(okrsky.items()) if a[2]]
    if len(counted) < 2:  # noqa: PLR2004 - one okrsok is the whole contest
        return {}
    sizeable = sum(valid >= ORIGIN_VALID for _, valid, _ in counted) > 1
    voted: dict[int, list[tuple[str, int, int]]] = defaultdict(list)
    for key, valid, votes in counted:
        for n, x in votes.items():
            if x:
                voted[n].append((key, x, valid))
    out = {}
    for n, units in sorted(voted.items()):
        pool = [u for u in units if u[2] >= ORIGIN_VALID] if sizeable else units
        most = heapq.nsmallest(ORIGINS, units, key=lambda u: (-u[1], u[0]))
        highest = heapq.nsmallest(ORIGINS, pool, key=lambda u: (-u[1] / u[2], u[0]))
        out[str(n)] = [[list(u) for u in most], [list(u) for u in highest]]
    return out


def units_of(
    contest: str,
    status: str,
    areas: Mapping[str, Area] | None,
    divisions: Divisions,
    obvody: Mapping[str, str],
) -> dict[str, dict[str, Area]] | None:
    """Return the units of a record of *contest* made of its *areas*, or None.

    A country-wide contest's kraje and okresy (:func:`area_units`); a
    regional president's regional council obvody, ``zsk``
    (:func:`obvod_units`, *obvody* those of its file, :func:`file_obvody`);
    a contest of Bratislava or Košice, its districts summed by the coarsest
    units the map colours (:func:`coarse_units`). The app shows the contest
    by these, and the map colours the okresy or the regional obvody by
    them, so that it never sums the obce itself.
    """
    if areas is None:
        return None
    c = kinds.parse(contest)
    if c.kind.scope == "country":
        return area_units(areas, divisions)
    if c.kind.name == "predseda":
        zsk = obvod_units(areas, obvody, final=status == "final")
        return {ZSK_LEVEL: zsk} if zsk else None
    if c.area in candidates.CITY_CODES:
        return coarse_units(areas, obvody, divisions)
    return None


ZSK_LEVEL = "zsk"
"""The level of a regional president's ``units`` (and of its ``past``
units): the regional council obvody of its kraj, keyed by their number."""

_OBVOD_AREA = "obvod:"
"""The prefix of an ``areas`` key of a regional obvod as a whole (night)."""


def regional_obvody(areas: Mapping[str, Collection[str]]) -> dict[str, str]:
    """Return obec → the number of its regional council obvod, as text.

    *areas* maps the contests of an area file to the keys of their
    ``areas``: a regional council obvod's (``zsk:<kraj>/<n>``) are its
    obce, each in one obvod (an obvod as a whole, ``obvod:<n>``, aside).
    The candidate lists do not tell every election's obvody (2026's come
    with the geometry); its results do, final with every obce of each.
    """
    out: dict[str, str] = {}
    for contest, keys in areas.items():
        c = kinds.parse(contest)
        if c.kind.name == "zsk" and c.sub:
            out |= {k: str(c.sub) for k in keys if not k.startswith(_OBVOD_AREA)}
    return out


def file_obvody(
    areas: Mapping[str, Mapping[str, Collection[str]]], divisions: Divisions
) -> dict[str, dict[str, str]]:
    """Return area file → obec → its regional obvod (:func:`regional_obvody`).

    *areas* maps each area file to its contests' ``areas`` keys. A kraj's
    file has its own obce's obvody; Bratislava's and Košice's have those of
    their kraj's, the cities' districts being obce of its obvody; any other
    file none.
    """
    by_kraj = {
        path.removeprefix(_KRAJ): regional_obvody(contests)
        for path, contests in areas.items()
        if path.startswith(_KRAJ)
    }
    out: dict[str, dict[str, str]] = {}
    for path in areas:
        kraj = path.removeprefix(_KRAJ) if path.startswith(_KRAJ) else None
        if path.startswith(_CITY):
            kraj = divisions.kraj.get(path.removeprefix(_CITY))
        out[path] = by_kraj.get(kraj, {}) if kraj else {}
    return out


def regional_units(obvody: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    """Return obec → ``<kraj>/<n>``, its regional obvod, of all kraj files.

    *obvody* is :func:`file_obvody`; the key is the map's of a regional
    obvod (``<kraj>/<n>``), as the obce of all kraje are summed together.
    """
    return {
        code: f"{path.removeprefix(_KRAJ)}/{n}"
        for path, of in obvody.items()
        if path.startswith(_KRAJ)
        for code, n in of.items()
    }


def obvod_units(
    areas: Mapping[str, Area], obvody: Mapping[str, str], *, final: bool
) -> dict[str, Area]:
    """Return a regional president's figures per obvod of *areas*.

    Before it is *final*, the obvody ŠÚ SR counted as wholes
    (``obvod:<n>``), as its obce fully counted are fewer than the obvod's;
    final, the obce of each obvod (*obvody*, :func:`regional_obvody`)
    summed, of an obvod whose obce are all in *areas* (a sum short of one
    would mislead). By obvod number, ascending.
    """
    if not final:
        wholes = {
            k.removeprefix(_OBVOD_AREA): a
            for k, a in areas.items()
            if k.startswith(_OBVOD_AREA)
        }
        return dict(sorted(wholes.items(), key=lambda item: int(item[0])))
    members: dict[str, list[str]] = defaultdict(list)
    for code, n in obvody.items():
        members[n].append(code)
    return {
        n: sum_areas(areas[c] for c in codes)
        for n, codes in sorted(members.items(), key=lambda item: int(item[0]))
        if all(c in areas for c in codes)
    }


def area_units(
    areas: Mapping[str, Area], divisions: Divisions
) -> dict[str, dict[str, Area]]:
    """Return the kraje and okresy of *areas* (obec → figures), their obce summed.

    ``kraj`` and ``okres`` → code → figures, of every unit with an obec in
    *areas*; Bratislava and Košice as wholes are in no okres. The app shows
    a country-wide contest by these units, and the map colours its okresy
    by them.
    """
    return {
        "kraj": _sums_by(areas, divisions.kraj),
        "okres": _sums_by(areas, divisions.okres),
    }


def coarse_units(
    areas: Mapping[str, Area], obvody: Mapping[str, str], divisions: Divisions
) -> dict[str, dict[str, Area]]:
    """Return the coarsest units the map colours *areas* (obec → figures) by.

    Its regional obvody (``zsk``, by number, *obvody*), each its obce of
    *areas* summed; where the election has none (no regional contests: a
    municipal one alone, a by-election), its okresy (``okres``) likewise.
    The map shows these below the obce's zoom.
    """
    if obvody:
        return {ZSK_LEVEL: _sums_by(areas, obvody)}
    return {"okres": _sums_by(areas, divisions.okres)}


def _sums_by(areas: Mapping[str, Area], unit_of: Mapping[str, str]) -> dict[str, Area]:
    """Return unit → its obce of *areas* summed, *unit_of* naming each obec's."""
    parts: dict[str, list[Area]] = defaultdict(list)
    for code, area in areas.items():
        if unit := unit_of.get(code):
            parts[unit].append(area)
    return {unit: sum_areas(p) for unit, p in sorted(parts.items())}


def okrsok_units(
    okrsky: Mapping[str, Mapping[str, Area]],
    with_areas: Mapping[str, bool],
    councils: Mapping[str, str],
) -> dict[str, dict[str, dict[str, Area]]]:
    """Return the ``units`` of an okrsok file: its contests' okrsky summed.

    *okrsky* is the file's contest → okrsok → figures, *with_areas* whether
    each contest's record has ``areas``, *councils* :func:`council_of`. Per
    contest, the units the app narrows its results to that are made of its
    okrsky (live.js ``placeResults``), each of the okrsky of it in the file:

    - ``obvod``: a council obvod ``<obec>/<k>`` of an obec split into
      several (:func:`council_obvod`), its okrsky summed;
    - ``obec``: of a regional, a city or a country-wide contest without
      ``areas``, each obec with okrsky in the file, its okrsky summed (one
      with ``areas`` has the obec's own figures there).
    """
    out: dict[str, dict[str, dict[str, Area]]] = {}
    for contest, figures in okrsky.items():
        c = kinds.parse(contest)
        by_obvod: dict[str, list[Area]] = defaultdict(list)
        by_obec: dict[str, list[Area]] = defaultdict(list)
        for key, area in figures.items():
            if council := council_obvod(c, councils, key):
                by_obvod[council].append(area)
            by_obec[key.partition("/")[0]].append(area)
        units = {"obvod": by_obvod}
        if not with_areas[contest] and _by_obec(c):
            units["obec"] = by_obec
        sums = {
            level: {u: sum_areas(parts) for u, parts in sorted(groups.items())}
            for level, groups in units.items()
            if groups
        }
        if sums:
            out[contest] = sums
    return out


def _by_obec(c: kinds.Contest) -> bool:
    """Whether the app shows contest *c* by obec (live.js ``placeResults``).

    A regional, a city or a country-wide contest: one of an obec is all of
    it, or of one council obvod in it.
    """
    return c.kind.scope in ("country", "kraj") or c.area in candidates.CITY_CODES


def council_obvod(
    c: kinds.Contest, councils: Mapping[str, str], key: str
) -> str | None:
    """Return the council obvod okrsok *key* of contest *c* is shown in, if any.

    Its council obvod ``<obec>/<k>`` (*councils*, :func:`council_of`), of an
    obec split into several; not for a council of that obec, which is of one
    obvod, its okrsky those of that obvod alone: the app shows its whole
    (``all``), not an obvod in it.
    """
    council = councils.get(key)
    if council and c.kind.name == "oz" and council.partition("/")[0] == c.area:
        return None
    return council


Turnout = tuple[int, int]
"""An area's ``[eligible, voters]`` in :data:`TURNOUT_FILE`."""


def turnout(
    files: Mapping[str, Mapping[str, Record]],
    divisions: Divisions,
    regional: Mapping[str, str],
) -> dict[str, Any]:
    """Return the content of :data:`TURNOUT_FILE`: {} where nothing is known.

    The turnout map's figures of the elections of many contests
    (mapmode.js), each ``[eligible, voters]`` of the records whose two are
    known, summed here once:

    - ``municipal``, of the okres files: ``obce``, each obec's (its
      mayor's, else its council obvody's summed), ``councils``, each
      council obvod of an obec split into several (``<obec>/<k>``),
      ``total`` the obce's summed and its coarsest units (:func:`_coarse`);
    - ``city``, of Bratislava's and Košice's files: ``obce``, each city's
      (as an obec's), ``total`` and the coarsest units of the districts of
      its mayor's ``areas``;
    - ``regional``, of the kraj files: ``total``, the kraje's presidents'.

    *regional* is :func:`regional_units`; a part without figures is absent.
    """
    out: dict[str, Any] = {}
    municipal = {p: c for p, c in files.items() if p.startswith(_OKRES)}
    obce, councils = _municipal_turnouts(municipal, divisions.split)
    if obce:
        out["municipal"] = {
            "total": list(_add_turnouts(obce.values())),
            "obce": _pairs(obce),
            "councils": _pairs(councils),
            **_coarse(obce, divisions, regional),
        }
    city = {p: c for p, c in files.items() if p.startswith(_CITY)}
    cities, _ = _municipal_turnouts(city, frozenset())
    if cities:
        districts = {
            code: (a[0] or 0, a[1] or 0)
            for contests in city.values()
            for c, r in contests.items()
            if c.startswith("starosta:") and _turnout_of(r) and r.areas
            for code, a in r.areas.items()
        }
        out["city"] = {
            "total": list(_add_turnouts(cities.values())),
            "obce": _pairs(cities),
            **_coarse(districts, divisions, regional),
        }
    presidents = [
        t
        for path, contests in files.items()
        if path.startswith(_KRAJ)
        for c, r in contests.items()
        if c.startswith("predseda:") and (t := _turnout_of(r))
    ]
    if presidents:
        out["regional"] = {"total": list(_add_turnouts(presidents))}
    return out


def _turnout_of(record: Record) -> Turnout | None:
    """Return *record*'s turnout, None unless its eligible and voters are known."""
    if not record.eligible or record.voters is None:
        return None
    return (record.eligible, record.voters)


def _add_turnouts(parts: Iterable[Turnout]) -> Turnout:
    eligible = voters = 0
    for e, v in parts:
        eligible += e
        voters += v
    return (eligible, voters)


def _pairs(turnouts: Mapping[str, Turnout]) -> dict[str, list[int]]:
    return {key: list(t) for key, t in sorted(turnouts.items())}


def _municipal_turnouts(
    files: Mapping[str, Mapping[str, Record]], split: Collection[str]
) -> tuple[dict[str, Turnout], dict[str, Turnout]]:
    """Return the turnouts of the municipal contests of *files*.

    Area → its mayor's, else its councils' summed (a municipality where no
    mayor is elected, or whose mayor's figures are not known); and council
    obvod ``<area>/<k>`` → its own, of the areas in *split*.
    """
    mayors: dict[str, Turnout] = {}
    councils: dict[str, list[Turnout]] = defaultdict(list)
    obvody: dict[str, Turnout] = {}
    for contests in files.values():
        for contest, record in contests.items():
            t = _turnout_of(record)
            if t is None:
                continue
            c = kinds.parse(contest)
            if c.kind.name == "starosta":
                mayors[c.area] = t
            elif c.kind.name == "oz":
                councils[c.area].append(t)
                if c.area in split:
                    obvody[f"{c.area}/{c.sub}"] = t
    whole = {area: _add_turnouts(parts) for area, parts in councils.items()}
    return whole | mayors, obvody


def _coarse(
    areas: Mapping[str, Turnout], divisions: Divisions, regional: Mapping[str, str]
) -> dict[str, dict[str, list[int]]]:
    """Return *areas* (obec → turnout) by the coarsest units the map colours.

    Their regional obvody (``zsk``, ``<kraj>/<n>``, *regional*); where the
    election has none (a municipal election alone, a by-election), their
    okresy (``okres``). Each unit of the obce of *areas* in it.
    """
    level, unit_of = (ZSK_LEVEL, regional) if regional else ("okres", divisions.okres)
    parts: dict[str, list[Turnout]] = defaultdict(list)
    for code, t in areas.items():
        if unit := unit_of.get(code):
            parts[unit].append(t)
    return {level: {u: list(_add_turnouts(p)) for u, p in sorted(parts.items())}}


def council_of(
    okrsky: Mapping[str, Mapping[str, Collection[str]]], split: Collection[str]
) -> dict[str, str]:
    """Return okrsok → its council obvod ``<obec>/<k>``, of the obce in *split*.

    *okrsky* is okrsok file (without ``okrsky/``) → contest → its okrsky.
    Each council obvod's contest, in the file of its okres, lists its
    okrsky; an obec's okrsky are the same polling districts, numbered
    alike, in every contest, so this groups those of its other contests
    too (Bratislava's and Košice's own council obvody, in the cities'
    files, are not those of their districts).
    """
    out: dict[str, str] = {}
    for path, contests in okrsky.items():
        if not path.startswith(_OKRES):
            continue
        for contest, keys in contests.items():
            c = kinds.parse(contest)
            if c.kind.name == "oz" and c.sub and c.area in split:
                out |= dict.fromkeys(keys, f"{c.area}/{c.sub}")
    return out


PastUnit = list[Any]
"""The election before in a unit as written: ``[method, [eligible, voters,
valid, {number: votes}]]``; an okrsok's part of a sum has null figures
where its method is :data:`UNKNOWN`, which a sum never has."""


def past_units(
    past: Mapping[str, Any],
    okrsky: Mapping[str, Collection[str]],
    areas: Mapping[str, Collection[str]],
    councils: Mapping[str, str],
    divisions: Divisions,
    obvody: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Return the ``units`` of an okrsok file's written *past*.

    *okrsky* are its contests' okrsky, *areas* the obce of the ``areas`` of
    its contests that have them, *councils* :func:`council_of`, *obvody*
    the regional obvody of its area file's obce (:func:`file_obvody`).
    Per contest, the election before in the units the app narrows its
    results to, or colours the map by, that are made of okrsky or obce,
    each :data:`PastUnit`, its method the least certain of its parts', and
    only where every part is known (a sum short of some would mislead):

    - ``obec``: of a regional, a city or a country-wide contest, an obec
      with okrsky in the file but no figures of its own in ``contests``, its
      okrsky summed;
    - ``kraj``, ``okres``: of a country-wide contest, those of its obce
      (its own figures, else as ``obec``) in the file, summed;
    - ``zsk``: of a regional president, a regional obvod, its obce (as for
      ``kraj``) summed; of a city contest, its districts with okrsky in the
      file likewise by regional obvod, or (no regional obvody) ``okres``;
    - ``obvod``: a council obvod ``<obec>/<k>`` of an obec split into
      several, its okrsky summed; not of that obec's councils;
    - ``all``: a contest not country-wide without ``totals``, all of it,
      the file's okrsky of it summed;
    - ``obce``: such a contest of a kraj or a city (a regional or a city
      council obvod), each of its obce with figures of its own then, those
      summed (method same): the whole the map of the election before
      takes, as it colours the obce by those figures.
    """
    return {
        contest: units
        for contest, keys in okrsky.items()
        if (
            units := _contest_past(
                contest, keys, past, areas.get(contest), councils, divisions, obvody
            )
        )
    }


def _contest_past(
    contest: str,
    keys: Collection[str],
    past: Mapping[str, Any],
    areas: Collection[str] | None,
    councils: Mapping[str, str],
    divisions: Divisions,
    obvody: Mapping[str, str],
) -> dict[str, Any]:
    """Return :func:`past_units` of one contest."""
    figures = past["contests"].get(contest)
    if not figures:
        return {}
    c = kinds.parse(contest)
    country = c.kind.scope == "country"
    of = {key: _okrsok_past(past["okrsky"], figures, key) for key in keys}
    by_obec: dict[str, list[PastUnit | None]] = defaultdict(list)
    by_obvod: dict[str, list[PastUnit | None]] = defaultdict(list)
    for key, part in of.items():
        by_obec[key.partition("/")[0]].append(part)
        if council := council_obvod(c, councils, key):
            by_obvod[council].append(part)
    units: dict[str, Any] = {"obvod": _past_sums(by_obvod)}
    obce: dict[str, PastUnit] = {}
    if _by_obec(c):
        obce = units["obec"] = _past_sums(
            {code: parts for code, parts in by_obec.items() if code not in figures}
        )
    for level, unit_of, codes in _obce_groups(c, areas, by_obec, divisions, obvody):
        units[level] = _obce_past(codes, unit_of, figures, obce)
    if not country and contest not in past["totals"]:
        units["all"] = _past_sum(list(of.values()))
        own = all(code in figures for code in by_obec)
        if own and (c.kind.scope == "kraj" or c.area in candidates.CITY_CODES):
            units["obce"] = _past_sum([[SAME, figures[code]] for code in by_obec])
    return {level: u for level, u in units.items() if u}


def _obce_groups(
    c: kinds.Contest,
    areas: Collection[str] | None,
    okrsky: Collection[str],
    divisions: Divisions,
    obvody: Mapping[str, str],
) -> list[tuple[str, Mapping[str, str], Collection[str]]]:
    """Return the units of obce of contest *c*'s past: [(level, unit_of, obce)].

    A country-wide contest's kraje and okresy of its *areas*; a regional
    president's regional obvody of all of the kraj's obce (*obvody*); a
    city contest's coarsest units (as :func:`coarse_units`) of its obce
    with *okrsky*.
    """
    if c.kind.scope == "country":
        if areas is None:
            return []
        return [("kraj", divisions.kraj, areas), ("okres", divisions.okres, areas)]
    if c.kind.name == "predseda":
        return [(ZSK_LEVEL, obvody, obvody)]
    if c.area in candidates.CITY_CODES:
        level, unit_of = (ZSK_LEVEL, obvody) if obvody else ("okres", divisions.okres)
        return [(level, unit_of, okrsky)]
    return []


def _obce_past(
    codes: Collection[str],
    unit_of: Mapping[str, str],
    figures: Mapping[str, Any],
    obce: Mapping[str, PastUnit],
) -> dict[str, PastUnit]:
    """Return the units of obce *codes* (``unit_of`` each) at the election before.

    Each obec by its own figures then (*figures*), else its okrsky's
    (*obce*, the ``obec`` units); a unit only where all are known.
    """
    parts: dict[str, list[PastUnit | None]] = defaultdict(list)
    for code in codes:
        if unit := unit_of.get(code):
            own = figures.get(code)
            parts[unit].append([SAME, own] if own else obce.get(code))
    return _past_sums(parts)


def _okrsok_past(
    methods: Mapping[str, int], figures: Mapping[str, Any], key: str
) -> PastUnit | None:
    """Return the election before in okrsok *key*, as the app's ``pastOf``.

    *methods* and *figures* are a written ``past``'s ``okrsky`` and its
    contest's ``contests``; an okrsok not in *methods* is of an obec of one
    okrsok then and now, its figures the obec's. None where the method is
    known but not the figures.
    """
    method = methods.get(key, SAME)
    if method == UNKNOWN:
        return [UNKNOWN, None]
    obec = key.partition("/")[0]
    record = figures.get(key) or (None if key in methods else figures.get(obec))
    return [method, record] if record else None


def _past_sums(groups: Mapping[str, list[PastUnit | None]]) -> dict[str, PastUnit]:
    """Return unit → its *groups* of parts summed, where all are known."""
    return {
        unit: s for unit, parts in sorted(groups.items()) if (s := _past_sum(parts))
    }


def _past_sum(parts: Sequence[PastUnit | None]) -> PastUnit | None:
    """Return *parts* summed with the least certain method of theirs.

    None where there are none or the figures of one are not known.
    """
    if not parts or any(p is None or p[1] is None for p in parts):
        return None
    known = [p for p in parts if p is not None]
    return [
        max((p[0] for p in known), key=PAST_DOUBT.index),
        area_json(sum_areas(area_of_json(p[1]) for p in known)),
    ]


def _past_json(
    past: Past, contests: Collection[str], keys: Collection[str]
) -> dict[str, Any]:
    """Return the ``past`` of an okrsok file of *contests* and okrsky *keys*.

    A country-wide contest's past covers every kraj: the file gets its own
    okrsky and obce of it. Any other contest is in one file, which gets its
    past whole (so that the check sees a unit of no okrsok of the file). A
    file of a party's list alone gets none: a list is compared with nothing
    (:func:`contests.counterpart`), so how its okrsky map onto the earlier
    ones would tell nothing.
    """
    if not any(kinds.counterpart(c) for c in contests):
        return {}
    methods = {k: past.methods[k] for k in keys if k in past.methods}
    obce = {k.partition("/")[0] for k in keys}

    def own(contest: str, unit: str) -> bool:
        whole = kinds.parse(contest).kind.scope != "country"
        return whole or unit in keys or unit in obce

    records = {
        c: units
        for c in contests
        if (
            units := {
                unit: area_json(a)
                for unit, a in past.contests.get(c, {}).items()
                if own(c, unit)
            }
        )
    }
    totals = {c: area_json(past.totals[c]) for c in contests if c in past.totals}
    if not (methods or records or totals):
        return {}
    return {"day": past.day, "okrsky": methods, "contests": records, "totals": totals}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def status(
    live: Live,
    contents: Mapping[str, bytes],
    previous: Mapping[str, Any] | None,
    now: dt.datetime,
) -> dict[str, Any] | None:
    """Return ``status.json`` of *live*, or None if *previous* says the same.

    The version is the local time and a hash of phase, sources and files,
    so two different contents never share a version.
    """
    files = {path: _digest(data)[:_HASH] for path, data in sorted(contents.items())}
    same = previous is not None and (
        previous.get("phase"),
        previous.get("source"),
        previous.get("files"),
    ) == (live.phase, live.source, files)
    if same:
        return None
    fingerprint = _digest(bundle.encode([live.phase, live.source, files]))
    return {
        "version": f"{now:%Y%m%dT%H%M%S}-{fingerprint[:_VERSION_HASH]}",
        "updated": now.isoformat(timespec="seconds"),
        "phase": live.phase,
        "source": live.source,
        "files": files,
    }


def read_status(directory: Path) -> dict[str, Any] | None:
    """Return *directory*'s ``status.json``, or None if absent or unreadable."""
    try:
        data = orjson.loads((directory / STATUS_FILE).read_bytes())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write(
    directory: Path,
    live: Live,
    divisions: Divisions,
    now: dt.datetime | None = None,
    *,
    expect: Expect | None = None,
) -> dict[str, Any] | None:
    """Replace *directory* with *live*; return the new status, or None.

    *divisions* are the election's (:func:`render`). Nothing is written
    when phase, sources and files are those of the status already there.
    The directory is written beside the old one and swapped in when
    complete; with *expect*, only if it keeps the contract (:func:`check`),
    else a :class:`ResultsError` names what breaks it.
    """
    contents = render(live, divisions)
    moment = now or dt.datetime.now(TIMEZONE).replace(microsecond=0)
    new = status(live, contents, read_status(directory), moment)
    if new is None:
        return None
    with output.replacing(directory) as tmp:
        for path, data in contents.items():
            out = tmp / f"{path}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
        (tmp / STATUS_FILE).write_bytes(bundle.encode(new))
        problems = check(tmp, expect) if expect else []
        if problems:
            raise ResultsError(
                "the results break the contract of docs/results.md; not written:\n  "
                + "\n  ".join(problems)
            )
    return new


def read_live(directory: Path) -> Live | None:
    """Return the results in *directory*, or None if it has none.

    The sums written with them (``units``, :data:`TURNOUT_FILE`, a party
    list's preference votes) are left out: :func:`render` makes them again.
    The ``past`` of the okrsok files is gathered by its day, one
    :class:`Past` for each election before, under the sources of the files'
    contests.
    """
    st = read_status(directory)
    if st is None:
        return None
    live = Live(st["phase"], st["source"])
    by_day: dict[str, Past] = {}
    for path in st["files"]:
        if path == TURNOUT_FILE:
            continue
        content = orjson.loads((directory / f"{path}.json").read_bytes())
        area = path.removeprefix(f"{OKRSKY_DIR}/")
        if area != path:
            for contest, okrsky in content["contests"].items():
                live.add_okrsky(
                    area, contest, {k: area_of_json(a) for k, a in okrsky.items()}
                )
            if content["past"]:
                _read_past(live, by_day, content["contests"], content["past"])
            continue
        for contest, entry in content["contests"].items():
            live.add(path, contest, Record.from_json(entry))
    return live


def _read_past(
    live: Live,
    by_day: dict[str, Past],
    contests: Iterable[str],
    past: Mapping[str, Any],
) -> None:
    """Add an okrsok file's written *past* to *live*'s, of its *contests*.

    To the :class:`Past` of its day in *by_day*, made where none is yet.
    """
    then = by_day.setdefault(past["day"], Past(past["day"]))
    for source in sources_of(contests):
        live.past[source] = then
    then.methods |= past["okrsky"]
    for contest, units in past["contests"].items():
        then.contests[contest] = {u: area_of_json(a) for u, a in units.items()}
    for contest, total in past["totals"].items():
        then.totals[contest] = area_of_json(total)


def finalize(live: Live, final: Collection[str], sources: Collection[str]) -> Live:
    """Return the definitive results *live* with the sources of the election.

    *final* are the sources *live* has in full (``oso``, ``prez1``, …),
    *sources* those of the election (:attr:`Reference.sources`): each has
    its entry of *live* where it is final, else one of nothing counted
    (:func:`no_sources`); once *final* has them all, the phase is final,
    otherwise partial.
    """
    return Live(
        "final" if set(sources) <= set(final) else "partial",
        {**no_sources(sources), **{s: live.source[s] for s in final}},
        live.files,
        live.okrsky,
        live.past,
    )


@dataclass(frozen=True)
class Expect:
    """What :func:`check` holds an election's results to, beyond the format."""

    sources: frozenset[str]
    """The ``source`` keys of ``status.json``: exactly these."""
    preferences: Mapping[str, int]
    """Party contest → how many persons of one list a voter may mark."""
    quotas: Mapping[str, float]
    """Party contest → the % of a party's votes a person's preference votes
    must reach to go ahead of the list order (:func:`preference_order`)."""
    divisions: Divisions
    """What the units of the results are summed by (:func:`render`)."""
    past: Mapping[str, str] = field(default_factory=dict)
    """Source → ISO day of the election before its contests are compared
    with (``cli._compare``), which the ``past`` of their okrsok files must
    be of; a source compared with none has none, nor its files a ``past``."""

    @classmethod
    def of(
        cls, data: Mapping[str, Any], parts: Collection[str], past: Mapping[str, str]
    ) -> Expect:
        """Return the expectations of ``candidates.json`` *data*.

        *parts* as :meth:`Divisions.of` takes them, *past* as :attr:`past`.
        """
        entries = data["contests"]
        return cls(
            sources_of(c["id"] for c in entries),
            {c["id"]: c["preferences"] for c in entries if "preferences" in c},
            {c["id"]: c["quota"] for c in entries if c.get("quota") is not None},
            Divisions.of(data, parts),
            past,
        )


def check(directory: Path, expect: Expect) -> list[str]:
    """Return what in the results in *directory* breaks the contract.

    *expect* says which sources the election has, what its party lists
    allow and where its obce lie (:meth:`Expect.of`).
    """
    st = read_status(directory)
    if st is None:
        return [f"{STATUS_FILE} missing or not a JSON object"]
    problems = _check_status(st, expect.sources)
    files = st.get("files")
    listed: dict[str, Any] = files if isinstance(files, dict) else {}
    present = {
        p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()
    } - {STATUS_FILE}
    problems += [
        f"{p} is not a results file" for p in sorted(present) if not p.endswith(".json")
    ]
    present = {p.removesuffix(".json") for p in present if p.endswith(".json")}
    problems += [
        f"{p}.json is not in {STATUS_FILE}" for p in sorted(present - set(listed))
    ]
    contents: dict[str, Any] = {}
    for path, digest in sorted(listed.items()):
        content, problem = _load_file(directory / f"{path}.json", digest)
        if problem:
            problems.append(f"{path}: {problem}")
        else:
            contents[path] = content
    # The council obvody of the okrsky, from the files that are well formed
    # enough to tell them; a malformed one is reported with its file.
    okrsky = {
        path.removeprefix(f"{OKRSKY_DIR}/"): {
            c: keys
            for c, keys in content["contests"].items()
            if kinds.CONTEST_ID.fullmatch(c) and isinstance(keys, dict)
        }
        for path, content in contents.items()
        if path.startswith(f"{OKRSKY_DIR}/")
        and isinstance(content, dict)
        and isinstance(content.get("contests"), dict)
    }
    councils = council_of(okrsky, expect.divisions.split)
    # The well-formed records of the area files, and the regional obvody
    # their regional council contests tell.
    areas = {path for path in listed if not path.startswith(f"{OKRSKY_DIR}/")} - {
        TURNOUT_FILE
    }
    records = {
        path: {c: e for c, e in content["contests"].items() if not _check_record(c, e)}
        for path, content in contents.items()
        if path in areas
        and isinstance(content, dict)
        and isinstance(content.get("contests"), dict)
    }
    obvody = file_obvody(
        {
            p: {c: _keys(e.get("areas")) for c, e in cs.items()}
            for p, cs in records.items()
        },
        expect.divisions,
    )
    for path, content in contents.items():
        area = path.removeprefix(f"{OKRSKY_DIR}/")
        if path == TURNOUT_FILE:
            continue
        if area == path:
            found = _check_area_file(content, expect, obvody.get(path, {}))
        else:
            found = _check_okrsok_file(
                content,
                contents.get(area_of_okrsok_file(area)),
                expect,
                councils,
                obvody.get(area_of_okrsok_file(area), {}),
            )
        problems += [f"{path}: {p}" for p in found]
    problems += _check_origins(records, okrsky)
    # The turnout is of all the area files: checked once they are all sound,
    # else what is wrong with them is reported alone, as is a turnout file
    # that cannot be read.
    sound = records.keys() == areas and all(
        len(records[p]) == len(contents[p]["contests"]) for p in areas
    )
    if sound and (TURNOUT_FILE in contents or TURNOUT_FILE not in listed):
        found = _check_turnout(
            contents.get(TURNOUT_FILE), records, expect.divisions, obvody
        )
        problems += [f"{TURNOUT_FILE}: {p}" for p in found]
    return problems


def _check_origins(
    records: Mapping[str, Mapping[str, Any]],
    okrsky: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Check the ``origins`` of the well-formed *records* of each area file.

    Each must be what :func:`origins` makes of the contest's okrsky in all
    the okrsok files *okrsky* (path → contest → okrsky), none without them;
    a malformed okrsok is reported with its file, and left out here.
    """
    spread: dict[str, dict[str, Area]] = defaultdict(dict)
    for contests in okrsky.values():
        for c, areas in contests.items():
            if _has_origins(c):
                listed = _is_list(c)
                spread[c].update(
                    (k, area_of_json(a))
                    for k, a in areas.items()
                    if _is_area(a, complete=True, preferences=listed)
                )
    return [
        f"{path}: {c}: origins not those of its okrsky"
        for path, contests in sorted(records.items())
        for c, entry in sorted(contests.items())
        if entry.get("origins", {}) != (origins(spread[c]) if c in spread else {})
    ]


def _turnout_of_records(
    records: Mapping[str, Mapping[str, Any]],
    divisions: Divisions,
    obvody: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """Return :func:`turnout` of the written well-formed *records* of each area file."""
    files = {
        path: {c: Record.from_json(e) for c, e in contests.items()}
        for path, contests in records.items()
    }
    return turnout(files, divisions, regional_units(obvody))


def _check_turnout(
    content: Any,
    records: Mapping[str, Mapping[str, Any]],
    divisions: Divisions,
    obvody: Mapping[str, Mapping[str, str]],
) -> list[str]:
    """Check :data:`TURNOUT_FILE`, *content* (None if absent), against *records*.

    Those of the area files, all well formed.
    """
    want = _turnout_of_records(records, divisions, obvody)
    if content is None:
        return ["missing, though the area files have turnouts"] if want else []
    if not want:
        return ["present, though the area files have no turnouts"]
    got = content if isinstance(content, dict) else {}
    return [
        f"{part} not the turnout of the area files"
        for part in sorted(want.keys() | got.keys())
        if want.get(part) != got.get(part)
    ]


def _check_status(st: Mapping[str, Any], expected: Collection[str]) -> list[str]:
    problems = []
    if set(st) != {"version", "updated", "phase", "source", "files"}:
        problems.append(f"{STATUS_FILE}: keys {sorted(st)}")
    if st.get("phase") not in PHASES:
        problems.append(f"{STATUS_FILE}: phase {st.get('phase')!r}")
    if st.get("phase") == "none" and st.get("files"):
        problems.append(f"{STATUS_FILE}: files while phase is none")
    try:
        dt.datetime.fromisoformat(st["updated"])
    except (KeyError, TypeError, ValueError):
        problems.append(f"{STATUS_FILE}: updated {st.get('updated')!r}")
    sources = st.get("source")
    if not isinstance(sources, dict) or set(sources) != set(expected):
        return [
            *problems,
            f"{STATUS_FILE}: source {sources!r}, not of {sorted(expected)}",
        ]
    for name, entry in sorted(sources.items()):
        if not _is_source(entry):
            problems.append(f"{STATUS_FILE}: source.{name} {entry!r}")
    return problems


def _is_source(entry: object) -> bool:
    keys = {"time", "counted", "unit", "voters"}
    if not isinstance(entry, dict) or set(entry) != keys:
        return False
    time = entry["time"]
    if time is not None and (not isinstance(time, str) or "+" not in time[-6:]):
        return False
    return all(entry[k] is None or _is_pair(entry[k]) for k in ("counted", "voters"))


def _is_pair(value: object) -> bool:
    pair_length = 2
    return (
        isinstance(value, list)
        and len(value) == pair_length
        and all(_is_count(v) for v in value)
    )


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _load_file(path: Path, digest: str) -> tuple[Any, str | None]:
    """Return a listed file's JSON, or a problem: missing, other hash, not JSON."""
    try:
        data = path.read_bytes()
    except OSError:
        return None, "missing"
    if _digest(data)[:_HASH] != digest:
        return None, "hash differs from status.json"
    try:
        return orjson.loads(data), None
    except ValueError:
        return None, "not JSON"


def _check_area_file(
    content: Any, expect: Expect, obvody: Mapping[str, str]
) -> list[str]:
    """Check an area file; *obvody* are its regional obvody (:func:`file_obvody`)."""
    contests = content.get("contests") if isinstance(content, dict) else None
    if not isinstance(contests, dict) or not contests or set(content) != {"contests"}:
        return ["no contests"]
    problems = []
    for contest, entry in sorted(contests.items()):
        found = _check_record(contest, entry) or (
            _unit_votes(contest, _marks(contest, entry, expect), _counted_units(entry))
            + _check_preferences(contest, entry)
            + _check_units(contest, entry, expect.divisions, obvody)
            + _check_list_order(contest, entry, expect)
        )
        problems += [f"{contest}: {p}" for p in found]
    return problems


def _check_preferences(contest: str, entry: Mapping[str, Any]) -> list[str]:
    """Check a well-formed party list's preference votes summed.

    Of the whole list (``preferences``) and of each of its ``areas``: its
    persons' votes (``units`` are checked as the areas summed).
    """
    if not _is_list(contest):
        return []
    whole = sum(c[1] for c in entry["candidates"])
    wrong = [] if entry["preferences"] == whole else ["the list"]
    wrong += _unsummed(entry.get("areas") or {})
    if not wrong:
        return []
    return [f"preference votes not its persons' summed: {', '.join(wrong)}"]


def _unsummed(figures: Mapping[str, Sequence[Any]]) -> list[str]:
    """Return the units of a party list's well-formed *figures* not summed.

    Those whose fifth figure is not their votes summed.
    """
    return [k for k, a in sorted(figures.items()) if a[4] != sum(a[3].values())]


def _check_units(
    contest: str,
    entry: Mapping[str, Any],
    divisions: Divisions,
    obvody: Mapping[str, str],
) -> list[str]:
    """Check a well-formed record's ``units``: its ``areas`` summed.

    A country-wide contest with ``areas`` has them by kraj and okres, a
    regional president by its regional obvody, a city contest by its
    coarsest units (:func:`units_of`, *obvody* of its file); no other
    record has any.
    """
    areas = entry.get("areas")
    units = units_of(
        contest,
        entry["status"],
        None if areas is None else {k: area_of_json(a) for k, a in areas.items()},
        divisions,
        obvody,
    )
    want = None if units is None else _units_json(contest, units)
    got = entry.get("units")
    if got == want:
        return []
    if want is None:
        return ["units of a record without them"]
    if not isinstance(got, dict) or set(got) != set(want):
        return [f"units missing or not by {' and '.join(want)}"]
    wrong = [
        f"{level} {unit}"
        for level, by_unit in want.items()
        for unit in sorted(by_unit.keys() | _keys(got[level]))
        if not isinstance(got[level], dict) or got[level].get(unit) != by_unit.get(unit)
    ]
    return [f"units not the areas summed: {', '.join(wrong)}"]


def _check_list_order(
    contest: str, entry: Mapping[str, Any], expect: Expect
) -> list[str]:
    """Check a final party list's elected against the preference rule.

    They are the first of its persons in :func:`preference_order` of the
    whole list, as many as it filled, which the app takes the official
    order to be; the order of every other unit is the rule's on its votes.
    """
    quota = (
        expect.quotas.get(kinds.body(contest)) if kinds.parse(contest).is_list else None
    )
    if quota is None or entry["status"] != "final" or not entry["filled"]:
        return []
    votes = {n: v for n, v, _ in entry["candidates"]}
    order = preference_order(votes, entry["valid"] or 0, quota)
    elected = {n for n, _, flag in entry["candidates"] if flag == 1}
    if set(order[: entry["filled"]]) == elected:
        return []
    return ["the elected are not the first by the preference rule"]


def preference_order(votes: Mapping[int, int], valid: int, quota: float) -> list[int]:
    """Return a party list's positions in the order the law gives them seats.

    *votes* maps every position to its preference votes, *valid* is the
    party's votes, *quota* the % of them a person's preference votes must
    reach (Act No. 180/2014 Coll. § 68 ods. 5, § 94 ods. 5: three per cent
    for the NR SR and the European Parliament): those who reach it first,
    by preference votes (a tie by list position), then the others by list
    position. Applied to a unit's votes, it ranks the list there
    (web/js/ballots.js ``preferenceOrder`` does the same).
    """
    least = quota * valid / 100
    ahead = sorted(
        (n for n, v in votes.items() if v >= least), key=lambda n: (-votes[n], n)
    )
    reached = set(ahead)
    return ahead + sorted(n for n in votes if n not in reached)


def _keys(value: object) -> set[str]:
    """Return the keys of *value* if it is an object, else none."""
    return set(value) if isinstance(value, dict) else set()


def _marks(contest: str, entry: Mapping[str, Any], expect: Expect) -> int | None:
    """Return how many candidates of *contest* a voter may mark, if known.

    One in a single-choice contest, up to the preferences of its party
    contest on a party's list, up to the seats (of the well-formed *entry*)
    in a council.
    """
    c = kinds.parse(contest)
    if c.single:
        return 1
    if c.is_list:
        return expect.preferences.get(kinds.body(contest))
    return entry["seats"]


def _check_okrsok_file(
    content: Any,
    area: Any,
    expect: Expect,
    councils: Mapping[str, str],
    obvody: Mapping[str, str],
) -> list[str]:
    """Check an okrsok file against the area file of its contests (*area*).

    *councils* are the council obvody of the okrsky (:func:`council_of`),
    *obvody* the regional obvody of the area file (:func:`file_obvody`).
    """
    if not isinstance(content, dict) or set(content) != {"contests", "units", "past"}:
        return ["keys not contests, units and past"]
    contests, past = content["contests"], content["past"]
    if not isinstance(contests, dict) or not contests:
        return ["no contests"]
    records = area.get("contests") if isinstance(area, dict) else None
    if not isinstance(records, dict):
        return ["no area file of its contests"]
    problems = [
        f"{contest}: {p}"
        for contest, okrsky in sorted(contests.items())
        for p in _check_okrsky(contest, okrsky, records.get(contest), expect)
    ]
    if problems:
        return problems
    problems = _check_okrsok_units(content["units"], contests, records, councils)
    problems += _check_past(past, contests, records, expect.past)
    if problems or past == {}:
        return problems
    return _check_past_units_summed(
        past, contests, records, councils, expect.divisions, obvody
    )


def _check_okrsok_units(
    units: Any,
    contests: Mapping[str, Any],
    records: Mapping[str, Any],
    councils: Mapping[str, str],
) -> list[str]:
    """Check a well-formed okrsok file's ``units``: its okrsky summed.

    (:func:`okrsok_units`.) Not of a contest whose record is malformed,
    which is reported with its area file.
    """
    if not isinstance(units, dict):
        return ["units malformed"]
    sound = {c: o for c, o in contests.items() if not _check_record(c, records[c])}
    figures = {
        c: {k: area_of_json(a) for k, a in okrsky.items()}
        for c, okrsky in sound.items()
    }
    with_areas = {c: "areas" in records[c] for c in sound}
    want = {
        c: _units_json(c, u)
        for c, u in okrsok_units(figures, with_areas, councils).items()
    }
    got = {c: u for c, u in units.items() if c in sound or c not in contests}
    wrong = sorted(c for c in want.keys() | got.keys() if want.get(c) != got.get(c))
    return [f"{c}: units not those of its okrsky" for c in wrong]


def _check_past_units_summed(
    past: Mapping[str, Any],
    contests: Mapping[str, Any],
    records: Mapping[str, Any],
    councils: Mapping[str, str],
    divisions: Divisions,
    obvody: Mapping[str, str],
) -> list[str]:
    """Check a well-formed ``past``'s ``units``: its okrsky's summed.

    Not of a contest whose record is malformed, which is reported with its
    area file.
    """
    if not isinstance(past["units"], dict):
        return ["past units malformed"]
    sound = {c: o for c, o in contests.items() if not _check_record(c, records[c])}
    areas = {
        c: records[c]["areas"]
        for c in sound
        if isinstance(records[c].get("areas"), dict)
    }
    want = past_units(past, sound, areas, councils, divisions, obvody)
    got = {c: u for c, u in past["units"].items() if c in sound or c not in contests}
    wrong = sorted(c for c in want.keys() | got.keys() if want.get(c) != got.get(c))
    return [f"{c}: past units not those of its okrsky then" for c in wrong]


def _check_past(
    past: Any,
    contests: Mapping[str, Any],
    records: Mapping[str, Any],
    days: Mapping[str, str],
) -> list[str]:
    """Check an okrsok file's ``past`` against its well-formed *contests*.

    *records* are the contests' entries of their area file, *days* the
    elections before by source (:attr:`Expect.past`): the ``past`` is of the
    one its contests are compared with.
    """
    if past == {}:
        return []
    if not isinstance(past, dict) or set(past) != {
        "day",
        "okrsky",
        "contests",
        "totals",
        "units",
    }:
        return ["past malformed"]
    problems = []
    try:
        dt.date.fromisoformat(past["day"])
    except (TypeError, ValueError):
        problems.append(f"past day {past['day']!r}")
    want = {days.get(kinds.source_of(c)) for c in contests}
    if want != {past["day"]}:
        then = ", ".join(sorted(d or "none" for d in want))
        problems.append(
            f"past day {past['day']!r}, not that of the election before its"
            f" contests are compared with ({then})"
        )
    methods, units = past["okrsky"], past["contests"]
    keys = {k for okrsky in contests.values() for k in okrsky}
    if not isinstance(methods, dict) or not all(
        k in keys and v in PAST_METHODS for k, v in methods.items()
    ):
        return [*problems, "past okrsky malformed or not in its contests"]
    if not isinstance(units, dict) or not isinstance(past["totals"], dict):
        return [*problems, "past contests or totals malformed"]
    for contest, figures in sorted(units.items()):
        if contest not in contests:
            problems.append(f"{contest}: past of a contest not in the file")
        # A malformed record is reported with its area file.
        elif not _check_record(contest, records[contest]):
            found = _check_past_units(
                figures, contests[contest], methods, records[contest]
            )
            problems += [f"{contest}: past {p}" for p in found]
    return problems + _check_past_totals(past["totals"], contests, records)


def _check_past_totals(
    totals: Mapping[str, Any], contests: Mapping[str, Any], records: Mapping[str, Any]
) -> list[str]:
    """Check an okrsok file's ``past`` ``totals``: whole contests of the file."""
    problems = []
    for contest, total in sorted(totals.items()):
        if (
            contest not in contests
            or not kinds.CONTEST_ID.fullmatch(contest)
            or kinds.counterpart(contest) != contest
        ):
            problems.append(f"{contest}: past total of no whole contest of the file")
        # A malformed record is reported with its area file.
        elif not _check_record(contest, records[contest]):
            numbers = {str(c[0]) for c in records[contest]["candidates"]}
            if not _is_area(total, complete=True) or set(total[3]) - numbers:
                problems.append(
                    f"{contest}: past total malformed, or votes of no candidate"
                )
    return problems


def _check_past_units(
    figures: Any,
    okrsky: Mapping[str, Any],
    methods: Mapping[str, int],
    record: Mapping[str, Any],
) -> list[str]:
    """Check a contest's ``past`` figures against its *okrsky* and *record*.

    Each of an okrsok of the contest whose method is known, or of an obec it
    has okrsky in; the votes of its candidates only.
    """
    if not isinstance(figures, dict) or not figures:
        return ["malformed"]
    obce = {k.partition("/")[0] for k in okrsky}
    numbers = {str(c[0]) for c in record["candidates"]}
    wrong = []
    for unit, figure in sorted(figures.items()):
        known = (
            unit in okrsky and methods.get(unit, UNKNOWN) != UNKNOWN
            if _OKRSOK_KEY.fullmatch(unit)
            else bool(_OBEC_KEY.fullmatch(unit)) and unit in obce
        )
        if not known:
            wrong.append(f"{unit} (no okrsok of known method or obec of the contest)")
        elif not _is_area(figure, complete=True) or set(figure[3]) - numbers:
            wrong.append(f"{unit} (malformed, or votes of no candidate)")
    return wrong


def _check_okrsky(contest: str, okrsky: Any, record: Any, expect: Expect) -> list[str]:
    """Check a contest's okrsky against its *record* in the area file."""
    if record is None:
        return ["not in the area file"]
    if not isinstance(okrsky, dict) or not okrsky:
        return ["no okrsky"]
    listed = _is_list(contest)
    if not all(
        _OKRSOK_KEY.fullmatch(k) and _is_area(a, complete=True, preferences=listed)
        for k, a in okrsky.items()
    ):
        return ["okrsky malformed"]
    # A malformed record is reported with its area file.
    if _check_record(contest, record):
        return []
    units = [(key, a[2], a[3]) for key, a in sorted(okrsky.items())]
    marks = _marks(contest, record, expect)
    unsummed = _unsummed(okrsky) if listed else []
    return (
        _okrsok_sums(record, okrsky)
        + _unit_votes(contest, marks, units)
        + (
            [f"preference votes not its persons' summed: {', '.join(unsummed)}"]
            if unsummed
            else []
        )
    )


def _okrsok_sums(record: Mapping[str, Any], okrsky: Mapping[str, list]) -> list[str]:
    """Return how *okrsky* fail to add up to their contest's *record*.

    Only where they are all there: as many as the contest's okrsky counted.
    """
    counted = record["counted"]
    if not counted or len(okrsky) != counted[1]:
        return []
    problems = []
    for i, name in enumerate(("eligible", "voters", "valid")):
        total = sum(a[i] for a in okrsky.values())
        if total != record[name]:
            problems.append(
                f"{name} of the okrsky {total}, of the contest {record[name]}"
            )
    votes: Counter[int] = Counter()
    for a in okrsky.values():
        votes.update({int(n): x for n, x in a[3].items()})
    own = {c[0]: c[1] for c in record["candidates"] if c[1]}
    if {n: x for n, x in votes.items() if x} != own:
        problems.append("votes of the okrsky do not add up to the candidates'")
    return problems


_Counted = tuple[str, int | None, Mapping[Any, int]]
"""A counted unit of a contest as checked: its name, valid ballots, votes."""


def _counted_units(entry: Mapping[str, Any]) -> list[_Counted]:
    """Return the units of a well-formed record that are fully counted.

    The contest and each of its ``areas`` once it is final; none before, as
    the night's figures of a unit can come from files of different times.
    """
    if entry["status"] != "final":
        return []
    whole = {c[0]: c[1] for c in entry["candidates"]}
    areas = entry.get("areas") or {}
    return [
        ("the contest", entry["valid"], whole),
        *((key, a[2], a[3]) for key, a in sorted(areas.items())),
    ]


def _unit_votes(
    contest: str, marks: int | None, units: Iterable[_Counted]
) -> list[str]:
    """Return the counted *units* of *contest* whose votes break the rules.

    A voter of a single-choice contest (a mayor, a president, a question, a
    party) gives one candidate one vote: the votes are the valid ballots. A
    council's voter, or a party's voter among its list, gives a candidate
    one vote at most, and *marks* (:func:`_marks`) at most in all.
    """
    c = kinds.parse(contest)
    wrong = []
    for name, valid, votes in units:
        if valid is None:
            continue
        total, most = sum(votes.values()), max(votes.values(), default=0)
        if c.single and total != valid:
            wrong.append(f"{name} ({total} votes, {valid} valid)")
        elif not c.single and (most > valid or (marks and total > marks * valid)):
            wrong.append(
                f"{name} ({most} votes at most, {total} in all, {valid} valid)"
            )
    if not wrong:
        return []
    rule = (
        "votes other than the valid ballots"
        if c.single
        else f"votes beyond the valid ballots and {marks}"
        + (" preferences" if c.is_list else " seats")
    )
    return [f"{rule}: {'; '.join(wrong)}"]


def _check_record(contest: str, entry: object) -> list[str]:
    if not kinds.CONTEST_ID.fullmatch(contest):
        return ["not a contest id"]
    if not isinstance(entry, dict) or not _RECORD_KEYS <= set(entry):
        return ["keys missing"]
    c = kinds.parse(contest)
    party = c.kind.party and not c.is_list
    problems = []
    # ``units`` are checked against the areas (:func:`_check_units`), a
    # party list's ``preferences`` against its votes (:func:`_check_preferences`),
    # ``origins`` against the okrsky (:func:`_check_origins`).
    known = {
        "areas",
        "units",
        *(["won"] if party else []),
        *(["preferences"] if c.is_list else []),
        *(["origins"] if _has_origins(contest) else []),
    }
    unknown = set(entry) - _RECORD_KEYS - known
    if unknown:
        problems.append(f"unknown keys {sorted(unknown)}")
    if c.is_list and not _is_count(entry.get("preferences")):
        problems.append(f"preferences {entry.get('preferences')!r}")
    if entry["status"] not in STATUSES:
        problems.append(f"status {entry['status']!r}")
    problems += _figure_problems(entry)
    flags = _flags(c)
    if not isinstance(entry["candidates"], list) or not all(
        _is_ballot(b, flags) for b in entry["candidates"]
    ):
        problems.append("candidates not [number, votes, flag] rows")
    if "areas" in entry and not _is_areas(entry["areas"], preferences=c.is_list):
        problems.append("areas malformed")
    if not _is_won(entry.get("won")):
        problems.append(f"won {entry['won']!r}")
    return problems


def _figure_problems(entry: Mapping[str, Any]) -> list[str]:
    """Return what of a record's ``counted`` and counts is malformed."""
    problems = []
    if entry["counted"] is not None and not _is_pair(entry["counted"]):
        problems.append(f"counted {entry['counted']!r}")
    for key in ("eligible", "voters", "valid", "seats", "filled"):
        if entry[key] is not None and not _is_count(entry[key]):
            problems.append(f"{key} {entry[key]!r}")
    return problems


def _is_won(won: object) -> bool:
    """Whether *won* is absent or a party contest's seats by party number."""
    return won is None or (
        isinstance(won, dict)
        and all(n.isdigit() and _is_count(s) for n, s in won.items())
    )


def _flags(c: kinds.Contest) -> frozenset[int | None]:
    """Return the flags a candidate of contest *c* can have.

    An answer or a party wins (1) or not (null); a presidential candidate
    is elected, goes on to round 2 (:data:`ADVANCED`) or withdrew
    (:data:`WITHDRAWN`); any other person is elected, a substitute (0) or
    withdrew.
    """
    if c.kind.sub == "question" or (c.kind.party and not c.is_list):
        return frozenset({None, 1})
    if c.kind.sub == "round":
        return frozenset({None, 1, ADVANCED, WITHDRAWN})
    return frozenset({None, 0, 1, WITHDRAWN})


def _is_ballot(c: object, flags: frozenset[int | None]) -> bool:
    ballot_length = 3
    return (
        isinstance(c, list)
        and len(c) == ballot_length
        and _is_count(c[0])
        and _is_count(c[1])
        and c[2] in flags
    )


def _is_areas(areas: object, *, preferences: bool) -> bool:
    return isinstance(areas, dict) and all(
        _AREA_KEY.fullmatch(key) and _is_area(value, preferences=preferences)
        for key, value in areas.items()
    )


def _is_area(
    value: object, *, complete: bool = False, preferences: bool = False
) -> bool:
    """Whether *value* is ``[eligible, voters, valid, {number: votes}]``.

    The three figures can be null unless *complete*. A party's list's
    (*preferences*) has a fifth, a count: its votes summed
    (:func:`area_json`, checked apart).
    """
    area_length = 5 if preferences else 4
    if not isinstance(value, list) or len(value) != area_length:
        return False
    if preferences and not _is_count(value[4]):
        return False
    if not all((v is None and not complete) or _is_count(v) for v in value[:3]):
        return False
    votes = value[3]
    # Mapped, not a generator: the results hold millions of votes.
    return (
        isinstance(votes, dict)
        and all(map(str.isdigit, votes))
        and all(map(_is_count, votes.values()))
    )


# The night's JSON.


def _rows(files: Mapping[str, bytes], path: str) -> list[dict[str, Any]]:
    """Return the rows (objects) of JSON file *path*, none if absent or invalid."""
    body = files.get(path)
    if body is None:
        return []
    try:
        # volbysr.sk's files by json, as lenient as before (a byte order
        # mark, NaN); orjson reads the project's own.
        data = json.loads(body)
    except ValueError:
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _progress(files: Mapping[str, bytes], election: str, unit: str) -> dict[str, Any]:
    """Return the ``source`` entry of *election* from its ``tab01``."""
    row = next(iter(_rows(files, f"{election}/json/tab01.json")), {})
    # Since 2026 the time comes in Slovak and in English (C01, C02) before
    # the counts; in 2022 only once.
    first = 3 if ":" in str(row.get("C02", "")) else 2
    counted = _pair(
        number(row.get(f"C{first + 1:02d}")), number(row.get(f"C{first:02d}"))
    )
    time = source_time(row.get("C01")) or _date(files, election)
    return source(time, counted, unit)


def _date(files: Mapping[str, bytes], election: str) -> str | None:
    """Return the time of *election*'s ``dateSK.json``, or None."""
    body = files.get(f"{election}/json/dateSK.json")
    try:
        dates = json.loads(body) if body else []
    except ValueError:
        return None
    return source_time(dates[0]) if isinstance(dates, list) and dates else None


def _pair(done: int | None, total: int | None) -> tuple[int, int] | None:
    """Return a ``counted`` pair, or None unless both counts are known."""
    return None if done is None or total is None else (done, total)


def _all_in(counted: Sequence[int] | None) -> bool:
    """Whether a ``counted`` pair has every unit counted."""
    return bool(counted and counted[1] > 0 and counted[0] >= counted[1])


def _started(entry: Mapping[str, Any]) -> bool:
    return bool(entry["counted"] and entry["counted"][0] > 0)


def night(files: Mapping[str, bytes], ref: Reference, log: Log = progress.note) -> Live:
    """Return the results of the night's JSON *files* (path → content).

    Paths are relative to https://volbysr.sk/ (``oso/json/tab01.json``). A
    unit that fails to normalize is logged and left out.
    """
    oso = _progress(files, "oso", "obce")
    osk = _progress(files, "osk", "okrsky")
    live = Live("partial" if _started(oso) or _started(osk) else "none")
    # The night's files have both elections; status.json names the election's.
    live.source = {s: e for s, e in (("osk", osk), ("oso", oso)) if s in ref.sources}
    if live.phase == "none":
        return live
    if _started(osk):
        complete = _all_in(osk["counted"])
        for kraj in ref.regional:
            _guard(
                log,
                f"kraj {kraj}",
                partial(_regional, files, ref, kraj, complete, live),
            )
    if _started(oso):
        complete = _all_in(oso["counted"])
        okrsky = {
            str(r.get("C01")): number(r.get("C05")) for r in _rows(files, CITY_LIST)
        }
        for area in ref.municipal:
            _guard(
                log,
                area,
                partial(_municipal, files, ref, area, complete, okrsky, live, log),
            )
    _count_voters(live, ref)
    return live


def _count_voters(live: Live, ref: Reference) -> None:
    """Set each source's ``voters`` of *live*: registered voters counted, of all.

    A list, as ``status.json`` read back has it (:func:`write` compares
    them). The units are a kraj's president and a municipality's mayor, else
    its council; Bratislava's and Košice's districts, not the cities again.
    A unit counted has all its registered voters, however many voted; one
    partly counted those of its okrsky counted, of as many as at its last
    election (or as counted, if more); one not counted yet none, of those of
    its last election.
    """
    records = live.records()

    def tally(contests: Iterable[Contest | None]) -> list[int] | None:
        done = total = 0
        for c in contests:
            if c is None:
                continue
            r = records.get(c.id)
            past = c.past[0] if c.past else 0
            if r is not None and r.eligible is not None:
                whole = r.status != "partial" or bool(
                    r.counted and r.counted[0] >= r.counted[1]
                )
                done += r.eligible
                total += r.eligible if whole else max(past, r.eligible)
            else:
                total += past
        return [done, total] if total else None

    presidents = (president for president, _ in ref.regional.values())
    municipal = (
        mayor or next(iter(councils), None)
        for area, (mayor, councils) in ref.municipal.items()
        if area not in candidates.CITY_CODES
    )
    for name, contests in (("osk", presidents), ("oso", municipal)):
        if name in live.source and live.source[name]["counted"]:
            live.source[name] = {**live.source[name], "voters": tally(contests)}


def _guard(log: Log, what: str, run: Callable[[], None]) -> None:
    """Run *run*; log and go on if the data it reads is malformed."""
    try:
        run()
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
        log(f"{what}: skipped, unexpected data: {e!r}")


def _osk_counted(row: Mapping[str, Any]) -> tuple[int, int] | None:
    """Return the okrsky counted of all of a regional turnout row."""
    return _pair(
        number(row.get(_OSK_TURNOUT["processed"])),
        number(row.get(_OSK_TURNOUT["total"])),
    )


def _regional_obec_rows(
    files: Mapping[str, bytes], ref: Reference, kraj: str
) -> dict[str, dict[str, Any]]:
    """Return municipality code → turnout row (``tab02bc``) of a kraj."""
    _, councils = ref.regional[kraj]
    places = _group(
        (p for p in ref.places.values() if p.kraj == kraj and p.zsk is not None),
        lambda p: p.zsk,
    )
    rows: dict[str, dict[str, Any]] = {}
    for c in councils:
        turnout = _rows(files, f"osk/json/tab02bc/{vobvod(kraj, c.obvod or 0)}.json")
        rows |= _obec_rows(turnout, places.get(c.obvod, []))
    return rows


def _regional(
    files: Mapping[str, bytes], ref: Reference, kraj: str, complete: bool, live: Live
) -> None:
    """Add the contests of *kraj* whose votes have come."""
    president, councils = ref.regional[kraj]
    obvody = _obvod_rows(_rows(files, f"osk/json/tab02bb/{kraj}.json"))
    # The municipalities fully counted are in ``areas``, beside the obvody
    # known as a whole meanwhile: with their votes once these have come,
    # else (ŠÚ SR publishes them later) by their turnout alone.
    obec_rows = {
        code: row
        for code, row in _regional_obec_rows(files, ref, kraj).items()
        if complete or _all_in(_osk_counted(row))
    }
    if president is not None:
        record = _night_president(files, ref, kraj, councils, obvody, obec_rows)
        if record is not None:
            live.add(president.path, president.id, record)
    for c in councils:
        mine = {k: r for k, r in obec_rows.items() if ref.places[k].zsk == c.obvod}
        record = _night_obvod(files, kraj, c, obvody.get(c.obvod or 0), mine)
        if record is not None:
            live.add(c.path, c.id, record)


def _night_president(
    files: Mapping[str, bytes],
    ref: Reference,
    kraj: str,
    councils: Sequence[Contest],
    obvody: Mapping[int, Mapping[str, Any]],
    obec_rows: Mapping[str, Mapping[str, Any]],
) -> Record | None:
    """Return the president contest of *kraj*, or None before its votes."""
    ballots = _ballots(_rows(files, f"osk/json/tab06b/{kraj}.json"))
    if not ballots:
        return None
    row = _kraj_row(_rows(files, "osk/json/tab02ba.json"), ref.kraje[kraj])
    record = _osk_record(row, "predseda", ballots, 1)
    record.areas = {
        **_obvod_areas(files, kraj, councils, obvody),
        **_obec_areas(files, "tab06d", "predseda", obec_rows),
    } or None
    return record


def _night_obvod(
    files: Mapping[str, bytes],
    kraj: str,
    c: Contest,
    row: Mapping[str, Any] | None,
    obec_rows: Mapping[str, Mapping[str, Any]],
) -> Record | None:
    """Return regional council contest *c*, or None before its votes.

    *row* is the obvod's turnout, *obec_rows* that of its municipalities
    fully counted.
    """
    ballots = _ballots(
        _rows(files, f"osk/json/tab09c/{vobvod(kraj, c.obvod or 0)}.json")
    )
    if not ballots:
        return None
    record = _osk_record(row, "zsk", ballots, c.seats)
    areas = _obec_areas(files, "tab09d", "zsk", obec_rows)
    # The obvod as a whole too, where the votes of a municipality in it are
    # not known: the candidates' map shows it there.
    if any(a[2] is None for a in areas.values()):
        whole = _turnout_area(row or {}, "zsk", ballots)
        areas = {f"obvod:{c.obvod or 0}": whole, **areas}
    record.areas = areas or None
    return record


def _osk_record(
    row: Mapping[str, Any] | None, kind: str, ballots: list[Ballot], seats: int | None
) -> Record:
    """Return a regional contest of the night from its turnout *row*."""
    row = row or {}
    eligible, voters, valid, _ = _turnout_area(row, kind, ballots)
    elected = sum(1 for b in ballots if b[2] == 1)
    return Record(
        "partial",
        _osk_counted(row),
        eligible,
        voters,
        valid,
        seats,
        elected or None,
        ballots,
    )


def _turnout_area(row: Mapping[str, Any], kind: str, ballots: list[Ballot]) -> Area:
    return (
        number(row.get(_OSK_TURNOUT["eligible"])),
        number(row.get(_OSK_TURNOUT["voters"])),
        number(row.get(_OSK_TURNOUT[kind])),
        {n: v for n, v, _ in ballots},
    )


def _obvod_areas(
    files: Mapping[str, bytes],
    kraj: str,
    councils: Sequence[Contest],
    obvody: Mapping[int, Mapping[str, Any]],
) -> dict[str, Area]:
    """Return the regional president's votes per obvod, as ``areas``."""
    areas = {}
    for c in councils:
        n = c.obvod or 0
        ballots = _ballots(_rows(files, f"osk/json/tab06c/{vobvod(kraj, n)}.json"))
        if ballots:
            areas[f"obvod:{n}"] = _turnout_area(obvody.get(n, {}), "predseda", ballots)
    return areas


def _obec_areas(
    files: Mapping[str, bytes],
    table: str,
    kind: str,
    rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Area]:
    """Return the figures per municipality of *rows* (code → turnout row).

    A municipality whose votes (*table*) have not come has its turnout
    alone: valid ballots unknown (null), no votes, so that a candidate's
    map passes it over and a turnout map shows it.
    """
    areas = {}
    for code, row in rows.items():
        ballots = _ballots(_rows(files, f"osk/json/{table}/{code}.json"))
        eligible, voters, valid, votes = _turnout_area(row, kind, ballots)
        if ballots:
            areas[code] = (eligible, voters, valid, votes)
        elif eligible is not None:
            areas[code] = (eligible, voters, None, {})
    return areas


def _kraj_row(rows: Iterable[Mapping[str, Any]], name: str) -> dict[str, Any] | None:
    key = candidates.search_key(name)
    for r in rows:
        k = candidates.search_key(str(r.get("C01") or ""))
        if k in (key, f"{key} kraj"):
            return dict(r)
    return None


def _obvod_rows(rows: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    """Return obvod number → row, of rows named like ``Volebný obvod č. 5``."""
    out = {}
    for r in rows:
        m = _OBVOD_NAME.search(str(r.get("C01") or ""))
        if m:
            out[int(m.group(1) or m.group(2))] = dict(r)
    return out


def _obec_rows(
    rows: Iterable[Mapping[str, Any]], places: Iterable[Place]
) -> dict[str, dict[str, Any]]:
    """Return municipality code → row, of rows named like the municipalities."""
    code_of = {candidates.search_key(p.name): p.code for p in places}
    out = {}
    for r in rows:
        code = code_of.get(candidates.search_key(str(r.get("C01") or "")))
        if code:
            out[code] = dict(r)
    return out


def _ballots(
    rows: Iterable[Mapping[str, Any]], columns: tuple[str, str, str] = _BALLOT
) -> list[Ballot]:
    """Return the candidates of *rows*: ballot number, votes, flag.

    Flagged 1 elected, :data:`WITHDRAWN` withdrawn (``X``), whose votes
    count; rows without a number or votes are left out.
    """
    number_column, votes_column, label_column = columns
    out = []
    for r in rows:
        n, votes = number(r.get(number_column)), number(r.get(votes_column))
        if n is None or votes is None:
            continue
        out.append((n, votes, _flag(str(r.get(label_column) or ""), None)))
    return out


def _flag(label: str, others: int | None) -> int | None:
    """Return the flag of a candidate labelled *label* by ŠÚ SR.

    1 elected (``zvolený``), :data:`WITHDRAWN` (``X``), else *others*.
    """
    label = label.strip().casefold()
    if label == _WITHDRAWN_LABEL:
        return WITHDRAWN
    return 1 if label.startswith(_ELECTED) else others


def _approved(g: Mapping[str, Any]) -> bool:
    """Whether a municipality's record is approved: its figures are filled in."""
    keys = ("eligible", "voters", "returned")
    return any(str(g.get(_GRAPH[k]) or "").strip() for k in keys)


def _municipal(
    files: Mapping[str, bytes],
    ref: Reference,
    area: str,
    complete: bool,
    okrsky: Mapping[str, int | None],
    live: Live,
    log: Log,
) -> None:
    code = OBEC_OF_CITY.get(area, area)
    rows = _rows(files, f"oso/json/graph01/{code}.json")
    if not rows or not _approved(rows[0]):
        return
    g = rows[0]
    held = number(g.get(_GRAPH["type"]))
    mayor, councils = ref.municipal[area]
    if mayor is not None and held in _MAYOR_HELD:
        record = _mayor(files, ref, mayor, g, complete, okrsky.get(code), log)
        if record is not None:
            live.add(mayor.path, mayor.id, record)
    if councils and held in _COUNCIL_HELD:
        for contest, record in _councils(files, councils, code, g, complete):
            live.add(contest.path, contest.id, record)


def _mayor(
    files: Mapping[str, bytes],
    ref: Reference,
    contest: Contest,
    g: Mapping[str, Any],
    complete: bool,
    okrsky: int | None,
    log: Log,
) -> Record | None:
    """Return the mayor contest *contest* of the night, or None if unknown.

    With the candidates' votes once the municipality is fully counted, and
    Bratislava's and Košice's as they count (*okrsky* theirs); else with
    the winner alone.
    """
    code = OBEC_OF_CITY.get(contest.area, contest.area)
    record = Record(
        "winner",
        eligible=number(g.get(_GRAPH["eligible"])),
        voters=number(g.get(_GRAPH["voters"])),
        valid=number(g.get(_GRAPH["valid_mayor"])),
        seats=1,
    )
    city = contest.area in candidates.CITY_CODES
    ballots = _ballots(_rows(files, f"oso/json/tab05/{code}.json"))
    done = complete or _counted_whole(g)
    if not ballots or not (done or city):
        return None if city else _night_mayor(ref, contest, g, record, log)
    elected = sum(1 for b in ballots if b[2] == 1)
    record.candidates = ballots
    if done:
        record.status, record.filled = "final", elected
        return record
    record.status, record.filled = "partial", elected or None
    share = decimal(g.get(_GRAPH["processed"]))
    if okrsky and share is not None:
        record.counted = (min(okrsky, round(share / _FULL * okrsky)), okrsky)
    return record


def _night_mayor(
    ref: Reference, contest: Contest, g: Mapping[str, Any], record: Record, log: Log
) -> Record | None:
    """Fill in the elected mayor of the night, known by name only."""
    name = str(g.get(_GRAPH["mayor"]) or "").strip()
    if not name:
        record.filled = 0
        return record
    n = match_winner(
        ref.candidates.get(contest.id, ()), name, str(g.get(_GRAPH["party"]) or "")
    )
    votes = number(g.get(_GRAPH["votes"]))
    if n is None or votes is None:
        log(f"{contest.id}: elected mayor {name!r} fits no single candidate; skipped")
        return None
    record.filled = 1
    record.candidates = [(n, votes, 1)]
    return record


def _councils(
    files: Mapping[str, bytes],
    contests: Sequence[Contest],
    code: str,
    g: Mapping[str, Any],
    complete: bool,
) -> Iterator[tuple[Contest, Record]]:
    """Yield the council contests of a municipality with their records.

    The night's summary has the seats and the seats filled of the whole
    council: per obvod they are known only for a council of one obvod or
    when every seat is filled; the candidates' votes once the municipality
    is fully counted and they have come. Bratislava's and Košice's councils
    are known only when the city is fully counted.
    """
    whole = _counted_whole(g)
    if code in CITY_OBCE and not whole:
        return
    single = len(contests) == 1
    seats_all, filled_all = (
        number(g.get(_GRAPH["seats"])),
        number(g.get(_GRAPH["filled"])),
    )
    finals = _council_ballots(files, code) if complete or whole else {}
    for c in contests:
        seats = c.seats if c.seats is not None else (seats_all if single else None)
        record = Record("winner", seats=seats)
        if single:
            record.filled = filled_all
            record.eligible = number(g.get(_GRAPH["eligible"]))
            record.voters = number(g.get(_GRAPH["voters"]))
            record.valid = number(g.get(_GRAPH["valid_council"]))
        elif seats_all and filled_all == seats_all:
            record.filled = seats
        ballots = finals.get(c.obvod or 0)
        if ballots:
            record.status = "final"
            record.candidates = ballots
            record.filled = sum(1 for b in ballots if b[2] == 1)
        yield c, record


def _council_ballots(files: Mapping[str, bytes], code: str) -> dict[int, list[Ballot]]:
    """Return obvod → council candidates of a municipality, the elected flagged."""
    num, votes_column, obvod_column = _COUNCIL_BALLOT
    elected = {
        (number(r.get(obvod_column)), number(r.get(num)))
        for r in _rows(files, f"oso/json/tab06e1/{code}.json")
    }
    out: dict[int, list[Ballot]] = defaultdict(list)
    for r in _rows(files, f"oso/json/tab06e2/{code}.json"):
        obvod, n, votes = (
            number(r.get(obvod_column)),
            number(r.get(num)),
            number(r.get(votes_column)),
        )
        if obvod is not None and n is not None and votes is not None:
            out[obvod].append((n, votes, 1 if (obvod, n) in elected else 0))
    return dict(out)


def _counted_whole(g: Mapping[str, Any]) -> bool:
    """Whether a municipality's summary row says it is fully counted."""
    return (decimal(g.get(_GRAPH["processed"])) or 0) >= _FULL


def _settled(files: Mapping[str, bytes], code: str) -> bool:
    """Whether a municipality's summary is final for the night: fully counted."""
    rows = _rows(files, f"oso/json/graph01/{code}.json")
    return bool(rows) and _approved(rows[0]) and _counted_whole(rows[0])


def unit_paths(files: Mapping[str, bytes], ref: Reference) -> list[str]:
    """Return the per-unit files to fetch, given the progress in *files*."""
    oso = _progress(files, "oso", "obce")
    osk = _progress(files, "osk", "okrsky")
    paths = []
    if _started(osk):
        paths += _regional_paths(files, ref, _all_in(osk["counted"]))
    if _started(oso):
        paths += _municipal_paths(files, ref, _all_in(oso["counted"]))
    return paths


def _regional_paths(
    files: Mapping[str, bytes], ref: Reference, complete: bool
) -> list[str]:
    paths = ["osk/json/tab02ba.json"]
    counted: set[str] = set()
    for kraj, (_, councils) in ref.regional.items():
        paths += [f"osk/json/tab02bb/{kraj}.json", f"osk/json/tab06b/{kraj}.json"]
        for c in councils:
            code = vobvod(kraj, c.obvod or 0)
            paths += [
                f"osk/json/tab02bc/{code}.json",
                f"osk/json/tab06c/{code}.json",
                f"osk/json/tab09c/{code}.json",
            ]
        rows = _regional_obec_rows(files, ref, kraj)
        counted |= {code for code, row in rows.items() if _all_in(_osk_counted(row))}
    for p in ref.places.values():
        if p.zsk is None:
            continue
        votes = [f"osk/json/tab06d/{p.code}.json", f"osk/json/tab09d/{p.code}.json"]
        # A municipality fully counted no longer changes: its votes are
        # fetched until they have come, then only once every okrsok is in.
        if complete or (p.code in counted and not all(v in files for v in votes)):
            paths += votes
    return paths


def _municipal_paths(
    files: Mapping[str, bytes], ref: Reference, complete: bool
) -> list[str]:
    paths = []
    for area, (_, councils) in ref.municipal.items():
        code = OBEC_OF_CITY.get(area, area)
        settled = _settled(files, code)
        if complete or not settled:
            paths.append(f"oso/json/graph01/{code}.json")
        # A municipality fully counted publishes its candidates' votes then,
        # and they no longer change: fetched until they have come, then only
        # once every municipality is in.
        mayor = f"oso/json/tab05/{code}.json"
        if (
            complete
            or area in candidates.CITY_CODES
            or (settled and mayor not in files)
        ):
            paths.append(mayor)
        council = [f"oso/json/tab06e1/{code}.json", f"oso/json/tab06e2/{code}.json"]
        if councils and (
            complete or (settled and not all(p in files for p in council))
        ):
            paths += council
    return paths


@dataclass
class _Copy:
    body: bytes
    etag: str | None
    modified: str | None


class Client:
    """Conditional GETs of volbysr.sk files, the latest copy of each kept.

    Each worker thread keeps one connection open, so a poll of thousands of
    small files costs the server :data:`CONCURRENCY` connections. Every file
    received (status 200) is archived under ``<archive>/<stamp>/<path>``.
    """

    def __init__(
        self, base: str, agent: str, context: ssl.SSLContext, archive: Path
    ) -> None:
        """Fetch from *base* as User-Agent *agent*, archiving into *archive*."""
        parts = urllib.parse.urlsplit(base)
        self.https = parts.scheme == "https"
        self.host = parts.netloc
        self.prefix = parts.path.rstrip("/")
        self.agent = agent
        self.context = context
        self.archive = archive
        self.copies: dict[str, _Copy] = {}
        self.messages: list[str] = []
        self._local = threading.local()
        self._lock = threading.Lock()

    def files(self) -> dict[str, bytes]:
        """Return path → the latest content of every file present."""
        return {path: copy.body for path, copy in self.copies.items()}

    def get_all(self, paths: Sequence[str], stamp: str) -> Counter[str]:
        """Fetch *paths*; return how many were changed, same, missing, failed."""
        with ThreadPoolExecutor(CONCURRENCY) as pool:
            return Counter(pool.map(lambda p: self.get(p, stamp), paths))

    def get(self, path: str, stamp: str) -> str:
        """Fetch *path*; return ``changed``, ``same``, ``missing`` or ``failed``."""
        previous = self.copies.get(path)
        headers = {
            "User-Agent": self.agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        if previous and previous.etag:
            headers["If-None-Match"] = previous.etag
        if previous and previous.modified:
            headers["If-Modified-Since"] = previous.modified
        try:
            code, validators, body = self._request(path, headers)
        except (OSError, http.client.HTTPException) as e:
            return self._fail(f"{path}: {e}")
        if code == http.HTTPStatus.NOT_MODIFIED:
            return "same"
        if code == http.HTTPStatus.NOT_FOUND:
            with self._lock:
                return "changed" if self.copies.pop(path, None) else "missing"
        if code != http.HTTPStatus.OK:
            return self._fail(f"{path}: HTTP {code}")
        try:
            json.loads(body)
        except ValueError:
            return self._fail(f"{path}: not JSON, previous copy kept")
        self._archive(path, stamp, body)
        with self._lock:
            self.copies[path] = _Copy(body, *validators)
        return "same" if previous and previous.body == body else "changed"

    def _archive(self, path: str, stamp: str, body: bytes) -> Path:
        target = self.archive / stamp / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return target

    def _fail(self, message: str) -> str:
        with self._lock:
            self.messages.append(message)
        return "failed"

    def _connection(self) -> http.client.HTTPConnection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = (
                http.client.HTTPSConnection(
                    self.host, timeout=TIMEOUT, context=self.context
                )
                if self.https
                else http.client.HTTPConnection(self.host, timeout=TIMEOUT)
            )
            self._local.connection = conn
        return conn

    def _drop(self) -> None:
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            conn.close()
        self._local.connection = None

    def _request(
        self, path: str, headers: Mapping[str, str]
    ) -> tuple[int, tuple[str | None, str | None], bytes]:
        """Return status, (ETag, Last-Modified) and body.

        One retry on a new connection: the server may have closed an idle one.
        """
        try:
            response, body = self._exchange(path, headers)
        except (OSError, http.client.HTTPException):
            response, body = self._exchange(path, headers)
        if response.getheader("Content-Encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
        if response.will_close:
            self._drop()
        validators = (response.getheader("ETag"), response.getheader("Last-Modified"))
        return response.status, validators, body

    def _exchange(
        self, path: str, headers: Mapping[str, str]
    ) -> tuple[http.client.HTTPResponse, bytes]:
        conn = self._connection()
        try:
            conn.request("GET", f"{self.prefix}/{path}", headers=dict(headers))
            response = conn.getresponse()
            return response, response.read()
        except (OSError, http.client.HTTPException):
            self._drop()
            raise


def _stamp() -> str:
    """Return the directory of the files fetched now in the archive: UTC time."""
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def browser_agent(contact: str) -> str:
    """Return a browser-like User-Agent naming the project.

    Cloudflare in front of volbysr.sk rejects Python's default one.
    """
    return f"Mozilla/5.0 (compatible; {fetch.user_agent(contact)})"


class Poller:
    """``poll``: one cycle of fetching and normalizing at a time."""

    def __init__(
        self, client: Client, ref: Reference, directory: Path, log: Log
    ) -> None:
        """Poll with *client* into live results directory *directory*."""
        self.client = client
        self.ref = ref
        self.directory = directory
        self.log = log
        self.pending = True
        """Whether the per-unit files are due even without a progress change:
        on the first cycle, and after one of them failed."""

    def cycle(self) -> dict[str, Any] | None:
        """Fetch what changed and rewrite the results; return their new status.

        None when nothing changed.
        """
        stamp = _stamp()
        changed = self.client.get_all([*PROGRESS_FILES, CITY_LIST], stamp)
        self._report("progress files", changed)
        if not changed["changed"] and not self.pending:
            return None
        paths = unit_paths(self.client.files(), self.ref)
        units = self.client.get_all(paths, stamp)
        # Some files are due only once others just fetched show their unit
        # fully counted (a municipality's candidates, its regional votes):
        # fetched now, not a progress change later.
        asked = set(paths)
        due = [p for p in unit_paths(self.client.files(), self.ref) if p not in asked]
        if due:
            units += self.client.get_all(due, stamp)
        self.pending = units["failed"] > 0
        self._report("units", units)
        live = night(self.client.files(), self.ref, self.log)
        new = write(self.directory, live, self.ref.divisions)
        self.log(
            f"{live.phase}: {sum(map(len, live.files.values()))} contests; "
            + (f"version {new['version']}" if new else "results unchanged")
        )
        return new

    def _report(self, what: str, outcomes: Counter[str]) -> None:
        for message in self.client.messages:
            self.log(message)
        self.client.messages.clear()
        counts = ", ".join(f"{n} {k}" for k, n in sorted(outcomes.items()))
        self.log(f"{what}: {counts or 'nothing fetched'}")


# The definitive CSV tables.

# Columns of the 2026 tables, which name them in full in their header rows.
_C_KRAJ = "Kód kraja"
_C_OKRES = "Kód okresu"
_C_OBEC = "Kód obce"
_C_CITY = "Kód mesta"
_C_VOBVOD = "Kód volebného obvodu"
_C_OBVOD = "Volebný obvod v obci"
_C_OKRSOK = "Okrsok"
_C_VOKRSOK = "Volebný okrsok"
"""The okrsok number in the regional tables."""
_C_OKRSKY = "Počet okrskov"
_C_REGIONAL_OKRSKY = "Počet volebných okrskov"
_C_CONFIRMED = "Počet potvrdených okrskových zápisníc"
_C_SEATS = "Počet volených poslancov"
_C_ELIGIBLE = "Počet zapísaných voličov"
_C_VOTERS = "Počet zúčastnených voličov"
_C_NUMBER = "Poradie na hlasovacom lístku"
_C_VOTES = "Počet platných hlasov"
_C_SHARE = "Podiel platných hlasov v %"
"""Of a city okrsok's votes: of the okrsok's valid ballots (mayor) or of
all its votes (council), per cent with a decimal point."""
_C_NOTE = "Poznámka"
"""Of a mayor's votes: ``zvolený`` elected, ``X`` withdrawn."""
_C_FLAG = "Kandidát"
"""Of other votes: ``zvolený`` elected, ``náhradník`` (or, in the regional
tables, nothing) not elected, ``X`` withdrawn."""
_VALID = "Počet platných hlasovacích lístkov odovzdaných pre voľby "
_VALID_OF = {
    "starosta": _VALID + "starostu",
    "oz": _VALID + "do zastupiteľstva",
    "predseda": _VALID + "predsedu",
    "zsk": _VALID + "do zastupiteľstva",
}
_TURNOUT = frozenset({_C_ELIGIBLE, _C_VOTERS})
_VOTE_COLUMNS = frozenset({_C_NUMBER, _C_VOTES})
_FINAL_TABLES: dict[str, dict[str, frozenset[str]]] = {
    "oso": {
        "tab02d": _TURNOUT
        | {_C_OBEC, _C_OKRES, _C_OKRSKY, _C_SEATS, _VALID_OF["starosta"]},
        "tab02e": _TURNOUT | {_C_OBEC, _C_OBVOD, _C_OKRSKY, _VALID_OF["oz"]},
        "tab02f": _TURNOUT
        | {_C_OBEC, _C_OKRES, _C_OBVOD, _C_OKRSOK}
        | {_VALID_OF["starosta"], _VALID_OF["oz"]},
        "tab05d": _VOTE_COLUMNS | {_C_OBEC, _C_NOTE},
        "tab05f": _VOTE_COLUMNS | {_C_OBEC, _C_OKRSOK, _C_NOTE},
        "tab08e": _VOTE_COLUMNS | {_C_OBEC, _C_OBVOD, _C_FLAG},
        "tab08f": _VOTE_COLUMNS | {_C_OBEC, _C_OBVOD, _C_OKRSOK, _C_FLAG},
        "tab02x": _TURNOUT | {_C_CITY, _C_OKRSKY, _VALID_OF["starosta"]},
        "tab02ex": _TURNOUT | {_C_CITY, _C_OBVOD, _C_OKRSKY, _VALID_OF["oz"]},
        "tab02fx": _TURNOUT
        | {_C_CITY, _C_OBVOD, _C_OKRSOK, _VALID_OF["starosta"], _VALID_OF["oz"]},
        "tab05x": _VOTE_COLUMNS | {_C_CITY, _C_NOTE},
        "tab05fx": _VOTE_COLUMNS | {_C_CITY, _C_OBVOD, _C_OKRSOK, _C_NOTE, _C_SHARE},
        "tab08ex": _VOTE_COLUMNS | {_C_CITY, _C_OBVOD, _C_FLAG},
        "tab08fx": _VOTE_COLUMNS | {_C_CITY, _C_OBVOD, _C_OKRSOK, _C_FLAG, _C_SHARE},
    },
    "osk": {
        "tab02a": _TURNOUT
        | {_C_KRAJ, _C_REGIONAL_OKRSKY, _C_CONFIRMED, _VALID_OF["predseda"]},
        "tab02b": _TURNOUT
        | {_C_VOBVOD, _C_REGIONAL_OKRSKY, _C_CONFIRMED, _C_SEATS, _VALID_OF["zsk"]},
        "tab02c": _TURNOUT | {_C_OBEC, _VALID_OF["predseda"], _VALID_OF["zsk"]},
        "tab02d": _TURNOUT
        | {_C_KRAJ, _C_VOBVOD, _C_OBEC, _C_VOKRSOK}
        | {_VALID_OF["predseda"], _VALID_OF["zsk"]},
        "tab06a": _VOTE_COLUMNS | {_C_KRAJ, _C_FLAG},
        "tab06c": _VOTE_COLUMNS | {_C_KRAJ, _C_OBEC, _C_FLAG},
        "tab06d": _VOTE_COLUMNS | {_C_KRAJ, _C_OBEC, _C_VOKRSOK, _C_FLAG},
        "tab09b": _VOTE_COLUMNS | {_C_VOBVOD, _C_FLAG},
        "tab09c": _VOTE_COLUMNS | {_C_VOBVOD, _C_OBEC, _C_FLAG},
        "tab09d": _VOTE_COLUMNS | {_C_VOBVOD, _C_OBEC, _C_VOKRSOK, _C_FLAG},
    },
}
"""The tables read from the 2026 packages, by id, with the columns used:
those summed per municipality, council obvod, kraj and regional obvod for
the contests, those per okrsok for the okrsok files and to put
Bratislava's and Košice's own contests by district. ŠÚ SR changes its
tables between elections (2022's were ``|``-separated, per okrsok, with
coded columns): another election's packages need tables of their own
here."""
_PACKAGE_FILE = re.compile(r"(OSO|OSK)\d{4}_SK_(tab\w+?)\.csv$", re.IGNORECASE)


def data_time(live: Live) -> dt.datetime | None:
    """Return the time of the newest data of *live*'s sources, or None.

    The time the final results are written as (``updated``, the version),
    so that the same packages always give the same files.
    """
    times = [
        dt.datetime.fromisoformat(s["time"]) for s in live.source.values() if s["time"]
    ]
    return max(times, default=None)


@dataclass
class Tables:
    """The CSV tables of a definitive results package, by table id."""

    name: str
    election: str
    """``oso`` or ``osk``."""
    time: dt.datetime
    raw: dict[str, bytes]
    """Table id (``tab05d``) → content."""

    def rows(self, table: str) -> list[dict[str, str]]:
        """Return the rows of a table (comma-separated, with a header)."""
        return tables.dict_rows(self._text(table))

    def check(self) -> None:
        """Fail unless the package has the tables and columns read."""
        for table, columns in _FINAL_TABLES[self.election].items():
            if table not in self.raw:
                raise ResultsError(f"{self.name}: no table {table}")
            header = next(csv.reader(io.StringIO(self._text(table))), [])
            lacking = columns - set(header)
            if lacking:
                raise ResultsError(f"{self.name}: {table} lacks {sorted(lacking)}")

    def _text(self, table: str) -> str:
        return self.raw[table].decode("utf-8-sig")


_Found = dict[str, tuple[str, bytes]]
"""Table id → election and content, of a package's tables."""


def open_tables(path: Path) -> Tables:
    """Return the checked tables of a zip or of a directory of the unzipped files."""
    found, time = _unzipped(path) if path.is_dir() else _zipped(path)
    elections = {election for election, _ in found.values()}
    if len(elections) != 1:
        raise ResultsError(
            f"{path}: not the tables of one election (OSO… or OSK…_SK_tab….csv)"
        )
    tables = Tables(
        path.name, elections.pop(), time, {t: data for t, (_, data) in found.items()}
    )
    tables.check()
    return tables


def _unzipped(directory: Path) -> tuple[_Found, dt.datetime]:
    """Return the tables of *directory* and the time of its newest CSV file."""
    files = sorted(directory.rglob("*.csv"))
    found: _Found = {}
    for f in files:
        m = _PACKAGE_FILE.search(f.name)
        if m:
            found[m.group(2).lower()] = (m.group(1).lower(), f.read_bytes())
    stamp = max((f.stat().st_mtime for f in files), default=0.0)
    return found, dt.datetime.fromtimestamp(stamp, TIMEZONE)


def _zipped(path: Path) -> tuple[_Found, dt.datetime]:
    """Return the tables of zip *path* and the time of the newest of them."""
    found: _Found = {}
    latest = (1980, 1, 1, 0, 0, 0)  # the earliest time a zip can hold
    try:
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                m = _PACKAGE_FILE.search(info.filename)
                if m:
                    found[m.group(2).lower()] = (m.group(1).lower(), z.read(info))
                    latest = max(latest, info.date_time)
    except (OSError, zipfile.BadZipFile) as e:
        raise ResultsError(f"{path}: {e}") from e
    return found, dt.datetime(*latest, tzinfo=TIMEZONE)


def read_final(
    paths: Sequence[Path],
    contests: Mapping[str, Contest] | None = None,
    log: Log = progress.note,
) -> tuple[Live, list[str]]:
    """Return the definitive results of the packages *paths*, and their elections.

    *contests* (:attr:`Reference.contests`) give the results file and the seats
    of the contests they know: a council obvod's seats are not in the
    tables, but where the municipality has one obvod. Each contest's okrsky
    go to the okrsok files; *log* is told how many of the two cities' own
    okrsky are left out for want of a single match among their districts'
    (:func:`city_matches`), and which for want of their votes
    (:func:`city_votes`).
    """
    live = Live("final")
    elections = []
    for path in paths:
        tables = open_tables(path)
        with progress.stage(f"reading {tables.name} ({tables.election})"):
            if tables.election == "oso":
                _final_municipal(tables, contests or {}, live, log)
            else:
                _final_regional(tables, live)
        elections.append(tables.election)
    return live, elections


def _group(rows: Iterable[_T], key: Callable[[_T], Any]) -> dict[Any, list[_T]]:
    out: dict[Any, list[_T]] = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return out


def _final_ballots(
    rows: Iterable[Mapping[str, str]], flag: str, others: int | None
) -> list[Ballot]:
    """Return the candidates of vote *rows*, flagged by column *flag*.

    The elected 1, the withdrawn :data:`WITHDRAWN`, the others *others*: 0,
    a substitute, in a council; None for a mayor or president.
    """
    return [(int(r[_C_NUMBER]), int(r[_C_VOTES]), _flag(r[flag], others)) for r in rows]


def _final_council_ballots(
    rows: Iterable[Mapping[str, str]],
    okrsky: Iterable[Mapping[str, str]],
    okrsok_flag: str = _C_FLAG,
) -> list[Ballot]:
    """Return the candidates of a council obvod's vote *rows*, withdrawn too.

    ŠÚ SR's council tables per obvod (``tab08e``, ``tab08ex``) leave out a
    candidate who withdrew; its tables per okrsok (*okrsky*, the obvod's
    rows) have their votes, which count among the valid ones, and the ``X``
    in column *okrsok_flag* (a by-election's ``tab08f`` has it as a note).
    """
    ballots = _final_ballots(rows, _C_FLAG, 0)
    have = {n for n, _, _ in ballots}
    missing = _row_votes(
        r
        for r in okrsky
        if int(r[_C_NUMBER]) not in have and _flag(r[okrsok_flag], 0) == WITHDRAWN
    )
    return ballots + [(n, v, WITHDRAWN) for n, v in sorted(missing.items())]


def _final_record(
    turnout: Mapping[str, str],
    kind: str,
    ballots: list[Ballot],
    counted: tuple[int, int],
    seats: int | None,
) -> Record:
    """Return a contest's record from its turnout row and candidates."""
    return Record(
        "final",
        counted,
        int(turnout[_C_ELIGIBLE]),
        int(turnout[_C_VOTERS]),
        int(turnout[_VALID_OF[kind]]),
        seats,
        sum(1 for b in ballots if b[2] == 1),
        ballots,
    )


def _every_okrsok(row: Mapping[str, str]) -> tuple[int, int]:
    """Return ``counted`` of a municipal turnout row: all its okrsky."""
    okrsky = int(row[_C_OKRSKY])
    return okrsky, okrsky


def _confirmed(row: Mapping[str, str]) -> tuple[int, int]:
    """Return ``counted`` of a regional turnout row: okrsky confirmed of all."""
    return int(row[_C_CONFIRMED]), int(row[_C_REGIONAL_OKRSKY])


def _area(turnout: Mapping[str, str], kind: str, votes: dict[int, int]) -> Area:
    return (
        int(turnout[_C_ELIGIBLE]),
        int(turnout[_C_VOTERS]),
        int(turnout[_VALID_OF[kind]]),
        votes,
    )


def _row_votes(rows: Iterable[Mapping[str, str]]) -> dict[int, int]:
    """Return ballot number → votes of vote *rows*, the withdrawn's too."""
    out: Counter[int] = Counter()
    for r in rows:
        out[int(r[_C_NUMBER])] += int(r[_C_VOTES])
    return dict(out)


# Bratislava's and Košice's own contests by okrsok.

_SHARE_TOLERANCE = 0.0101
"""How far a vote row's share (``Podiel platných hlasov v %``: per cent,
two decimals, rounded or truncated) can be from 100 × its votes over the
total they are a share of."""
_MAX_WAYS = 100
"""The ways to share out the votes of okrsky of one number tried at most
(:func:`_share_out`); with more, none of them is taken as known."""


class _Bounds(NamedTuple):
    """What the votes of a city okrsok keep to (:func:`_share_out`)."""

    least: float
    """The least total of its votes."""
    most: float
    """The most total of its votes."""
    cap: int
    """The most votes of one candidate: its valid ballots."""


def _bounds(valid: int, kind: str, seats: int | None) -> _Bounds:
    """Return the bounds of an okrsok of *valid* ballots in a contest of *kind*.

    A mayor's votes are the valid ballots; a council's at least those (each
    marks a candidate) and at most *seats* times as many.
    """
    if kinds.KINDS[kind].single:
        return _Bounds(float(valid), float(valid), valid)
    return _Bounds(float(valid), valid * seats if seats else math.inf, valid)


class _VoteRow(NamedTuple):
    """A city okrsok's vote row as :func:`_share_out` places it."""

    number: int
    votes: int
    share: float
    least: float
    """The least total its share can be of."""
    most: float
    """The most total its share can be of."""


def _vote_row(row: Mapping[str, str]) -> _VoteRow:
    votes, share = int(row[_C_VOTES]), float(row[_C_SHARE])
    if votes == 0:
        # 0 % of any total; another share of none.
        least, most = (0.0, math.inf) if share < _SHARE_TOLERANCE else (math.inf, 0.0)
    else:
        least = 100 * votes / (share + _SHARE_TOLERANCE)
        most = (
            math.inf
            if share <= _SHARE_TOLERANCE
            else 100 * votes / (share - _SHARE_TOLERANCE)
        )
    return _VoteRow(int(row[_C_NUMBER]), votes, share, least, most)


def _share_out(
    rows: Sequence[Mapping[str, str]], okrsky: Sequence[_Bounds]
) -> list[list[dict[int, int]]] | None:
    """Return every way to share vote *rows* among *okrsky*, or None if many.

    The okrsky share a number in the city's tables, and each has a row of
    every candidate. A way gives each okrsok one row of every candidate, so
    that its votes keep to its bounds and add up to a total that all its
    rows' shares are of. Candidates are placed from the most votes down,
    which pins the totals soonest; a candidate's rows of the same votes and
    share are one choice. A way is each okrsok's votes per ballot number;
    ways differ in some okrsok's. None where more than :data:`_MAX_WAYS`
    fit; none fit where the rows are not one per candidate per okrsok.
    """
    by_number = _group(map(_vote_row, rows), attrgetter("number"))
    if any(len(mine) != len(okrsky) for mine in by_number.values()):
        return []
    order = sorted(by_number.values(), key=lambda mine: -max(r.votes for r in mine))
    ways: dict[tuple, list[dict[int, int]]] = {}

    def place(
        i: int,
        placed: list[dict[int, int]],
        totals: list[int],
        ranges: list[tuple[float, float]],
    ) -> None:
        """Place the rows of the candidates from *i* on, beside *placed*.

        *totals* are each okrsok's votes placed, *ranges* the least and most
        its total can be.
        """
        if len(ways) > _MAX_WAYS:
            return
        if i == len(order):
            if all(lo <= t <= hi for t, (lo, hi) in zip(totals, ranges, strict=True)):
                ways.setdefault(tuple(tuple(sorted(v.items())) for v in placed), placed)
            return
        # Rows of the same votes and share are equal: each order once.
        for perm in dict.fromkeys(itertools.permutations(order[i])):
            narrowed = _narrowed(perm, totals, ranges, okrsky)
            if narrowed is not None:
                place(
                    i + 1,
                    [
                        {**v, r.number: r.votes}
                        for v, r in zip(placed, perm, strict=True)
                    ],
                    [t + r.votes for t, r in zip(totals, perm, strict=True)],
                    narrowed,
                )

    place(
        0, [{} for _ in okrsky], [0] * len(okrsky), [(b.least, b.most) for b in okrsky]
    )
    return None if len(ways) > _MAX_WAYS else list(ways.values())


def _narrowed(
    rows: Sequence[_VoteRow],
    totals: Sequence[int],
    ranges: Sequence[tuple[float, float]],
    okrsky: Sequence[_Bounds],
) -> list[tuple[float, float]] | None:
    """Return the okrsky's *ranges* with *rows* placed, one each, or None.

    None where a row does not fit its okrsok: its share is of no total in
    the range, or its votes pass the range or the okrsok's cap.
    """
    out = []
    for r, total, (lo, hi), bounds in zip(rows, totals, ranges, okrsky, strict=True):
        lo, hi = max(lo, r.least), min(hi, r.most)
        # Every vote is part of the total: those placed so far too.
        if lo > hi or total + r.votes > hi or r.votes > bounds.cap:
            return None
        out.append((lo, hi))
    return out


@dataclass(frozen=True)
class Unresolved:
    """Okrsky of one number of a city contest whose votes are not known."""

    okrsky: list[int]
    """Their rows of ``tab02fx``."""
    ways: list[dict[int, dict[int, int]]]
    """The ways their votes can be shared out, okrsok row → votes per
    ballot number: none where too many or none fit."""
    votes: dict[int, int]
    """Their votes together, which are known."""


@dataclass
class CityVotes:
    """A city contest's votes by okrsok (rows of ``tab02fx``)."""

    rows: dict[int, dict[int, int]]
    """Okrsok row → its votes per ballot number, where known."""
    unresolved: list[Unresolved]


def city_votes(
    turnout: Sequence[Mapping[str, str]],
    indices: Iterable[int],
    votes: Iterable[Mapping[str, str]],
    kind: str,
    seats: int | None,
) -> CityVotes:
    """Return the votes of a city contest by its okrsok rows.

    *indices* are the contest's okrsok rows of *turnout* (``tab02fx``),
    *votes* its vote rows (``tab05fx``, ``tab08fx``), keyed like them by
    council obvod and okrsok number, but Košice numbers its okrsky per
    district, and the city's tables do not name it: a council obvod of
    several districts has two or three okrsky of a number, and each
    candidate's rows of them come in no fixed order. They are told apart
    by the shares of the rows (:func:`_share_out`): a mayor's of the
    okrsok's valid ballots, which the votes add up to; a council's of the
    total of the okrsok's votes, at least its valid ballots (each marks a
    candidate) and at most *seats* times as many, no candidate with more
    votes than those. An okrsok with the same votes in every way that fits
    is known; the others of its number stay unresolved.
    """
    out = CityVotes({}, [])
    by_okrsok = _group(votes, itemgetter(_C_OBVOD, _C_OKRSOK))
    groups = _group(indices, lambda i: (turnout[i][_C_OBVOD], turnout[i][_C_OKRSOK]))
    for key, group in groups.items():
        rows = by_okrsok.get(key, [])
        if len(group) == 1:
            out.rows[group[0]] = _row_votes(rows)
            continue
        bounds = [_bounds(int(turnout[i][_VALID_OF[kind]]), kind, seats) for i in group]
        ways = _share_out(rows, bounds) or []
        known = [
            j
            for j in range(len(group))
            if ways and all(w[j] == ways[0][j] for w in ways)
        ]
        out.rows |= {group[j]: ways[0][j] for j in known}
        rest = [j for j in range(len(group)) if j not in known]
        if rest:
            together = Counter(_row_votes(rows))
            for j in known:
                together.subtract(ways[0][j])
            out.unresolved.append(
                Unresolved(
                    [group[j] for j in rest],
                    [{group[j]: w[j] for j in rest} for w in ways],
                    dict(together),
                )
            )
    return out


def city_matches(
    turnout: Sequence[Mapping[str, str]], districts: Sequence[Mapping[str, str]]
) -> dict[int, int]:
    """Return each okrsok row of Bratislava's and Košice's → its district's row.

    Rows are given by their index in *turnout* (``tab02fx``) and *districts*
    (``tab02f``). The city-wide contests are tabulated per okrsok of the
    city without its district. Each okrsok votes for its district at the
    same time, so the district's row of the same okrsok has the same voters
    on the roll and taking part: that pair finds it. Only a pair that no
    other okrsok of the city and no other row of its districts has is a
    match.
    """
    city_of = {o: city.code for city in candidates.CITIES for o in city.district_okresy}
    cities: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for i, r in enumerate(turnout):
        city = CITY_OBCE.get(r[_C_CITY])
        if city:
            cities[(city, r[_C_ELIGIBLE], r[_C_VOTERS])].append(i)
    rows: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for j, r in enumerate(districts):
        city = city_of.get(r[_C_OKRES])
        if city:
            rows[(city, r[_C_ELIGIBLE], r[_C_VOTERS])].append(j)
    return {
        found[0]: rows[key][0]
        for key, found in cities.items()
        if len(found) == 1 and len(rows.get(key, ())) == 1
    }


def city_districts(
    turnout: Sequence[Mapping[str, str]],
    districts: Sequence[Mapping[str, str]],
    matches: Mapping[int, int],
) -> dict[int, str]:
    """Return the district of each okrsok row of Bratislava's and Košice's.

    That of its district's row (*matches*, :func:`city_matches`); an okrsok
    without one goes to the district most of its council obvod's okrsky are
    in, so that the districts add up to the city.
    """
    out = {i: districts[j][_C_OBEC] for i, j in matches.items()}
    by_obvod: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for i, district in out.items():
        by_obvod[(turnout[i][_C_CITY], turnout[i][_C_OBVOD])][district] += 1
    for i, r in enumerate(turnout):
        if r[_C_CITY] in CITY_OBCE and i not in out:
            likely = by_obvod[(r[_C_CITY], r[_C_OBVOD])].most_common(1)
            if likely:
                out[i] = likely[0][0]
    return out


def city_areas(
    turnout: Sequence[Mapping[str, str]],
    indices: Iterable[int],
    votes: CityVotes,
    kind: str,
    key_of: Callable[[int], str | None],
) -> tuple[dict[str, Area], set[str]]:
    """Return a city-wide contest's areas summed by *key_of* its rows.

    *indices* are the contest's rows in *turnout* (``tab02fx``), *votes*
    its :func:`city_votes`; *key_of* gives a row's district, or its okrsok
    in its district's numbering, None to leave it out. Okrsky whose votes
    are not known add theirs to an area where they all lie in it, or where
    every way their votes can be shared out gives it the same; other areas
    they lie in are left out, as their votes are not known: returned too.
    """
    sums: dict[str, Area] = {}
    for i in indices:
        key = key_of(i)
        if key is not None:
            row = _area(turnout[i], kind, votes.rows.get(i, {}))
            sums[key] = _add_area(sums.get(key, (0, 0, 0, {})), row)
    left_out: set[str] = set()
    for u in votes.unresolved:
        keys = {key_of(i) for i in u.okrsky}
        for key in {k for k in keys if k is not None}:
            part = u.votes if len(keys) == 1 else _part_in(u, key, key_of)
            if part is None:
                left_out.add(key)
            else:
                sums[key] = _add_area(sums[key], (0, 0, 0, part))
    return {k: a for k, a in sums.items() if k not in left_out}, left_out


def _part_in(
    u: Unresolved, key: str, key_of: Callable[[int], str | None]
) -> dict[int, int] | None:
    """Return the votes of *u*'s okrsky in area *key*, if every way agrees."""
    parts = [_sum_votes(w[i] for i in u.okrsky if key_of(i) == key) for w in u.ways]
    if not parts or any(p != parts[0] for p in parts):
        return None
    return parts[0]


def _add(a: Mapping[int, int], b: Mapping[int, int]) -> dict[int, int]:
    return {n: a.get(n, 0) + b.get(n, 0) for n in a.keys() | b.keys()}


def _sum_votes(parts: Iterable[Mapping[int, int]]) -> dict[int, int]:
    out: dict[int, int] = {}
    for votes in parts:
        out = _add(out, votes)
    return out


def _add_area(a: Area, b: Area) -> Area:
    """Return the figures of areas *a* and *b* together."""
    return (
        (a[0] or 0) + (b[0] or 0),
        (a[1] or 0) + (b[1] or 0),
        (a[2] or 0) + (b[2] or 0),
        _add(a[3], b[3]),
    )


def _okrsok_areas(
    turnout: Iterable[Mapping[str, str]],
    votes: Iterable[Mapping[str, str]],
    kind: str,
    okrsok: str,
) -> dict[str, Area]:
    """Return a contest's okrsky (:func:`okrsok_key`) from its per-okrsok rows.

    *turnout* and *votes* are the contest's rows of the turnout and vote
    tables per okrsok, *okrsok* their column of the okrsok number.
    """
    by_okrsok = _group(votes, itemgetter(_C_OBEC, okrsok))
    return {
        okrsok_key(t[_C_OBEC], t[okrsok]): _area(
            t, kind, _row_votes(by_okrsok.get((t[_C_OBEC], t[okrsok]), []))
        )
        for t in turnout
    }


# The packages' contests.

_Final = tuple[str, Record, dict[str, Area]]
"""A contest of a municipal package: its id, record and okrsky."""


def _final_municipal(
    t: Tables, contests: Mapping[str, Contest], live: Live, log: Log
) -> None:
    """Add the contests of municipal package *t* and its source to *live*.

    *contests* give the results file of those they know; the others' follow
    from their municipality's okres.
    """
    obce = {r[_C_OBEC]: r for r in t.rows("tab02d")}
    okres = {code: r[_C_OKRES] for code, r in obce.items()}
    okrsky = t.rows("tab02f")
    for contest, record, areas in itertools.chain(
        _final_mayors(t, obce, okrsky),
        _final_councils(t, obce, okrsky, contests),
        _final_cities(t, okrsky, contests, log),
    ):
        known = contests.get(contest)
        if known:
            path = known.path
        else:
            path = live_path(contest, okres)
        live.add(path, contest, record)
        if areas:
            live.add_okrsky(path, contest, areas)
    live.source["oso"] = source(t.time.isoformat(), (len(obce), len(obce)), "obce")


def _seats(contests: Mapping[str, Contest], contest: str) -> int | None:
    known = contests.get(contest)
    return known.seats if known else None


def _final_mayors(
    t: Tables,
    obce: Mapping[str, Mapping[str, str]],
    okrsky: Sequence[Mapping[str, str]],
) -> Iterator[_Final]:
    """Yield the mayors of a municipal package, but the two cities'."""
    turnout = _group(okrsky, itemgetter(_C_OBEC))
    votes = _group(t.rows("tab05f"), itemgetter(_C_OBEC))
    for code, rows in _group(t.rows("tab05d"), itemgetter(_C_OBEC)).items():
        row = obce[code]
        ballots = _final_ballots(rows, _C_NOTE, None)
        record = _final_record(row, "starosta", ballots, _every_okrsok(row), 1)
        areas = _okrsok_areas(
            turnout.get(code, []), votes.get(code, []), "starosta", _C_OKRSOK
        )
        yield f"starosta:{code}", record, areas


def _final_councils(
    t: Tables,
    obce: Mapping[str, Mapping[str, str]],
    okrsky: Sequence[Mapping[str, str]],
    contests: Mapping[str, Contest],
) -> Iterator[_Final]:
    """Yield the council obvody of a municipal package, but the two cities'.

    The tables have the seats of a whole council only: an obvod's are its
    municipality's where it is the only one, else those of *contests*.
    """
    obvody = {(r[_C_OBEC], r[_C_OBVOD]): r for r in t.rows("tab02e")}
    obvody_of = Counter(code for code, _ in obvody)
    of_obvod = itemgetter(_C_OBEC, _C_OBVOD)
    turnout = _group(okrsky, of_obvod)
    votes = _group(t.rows("tab08f"), of_obvod)
    for key, rows in _group(t.rows("tab08e"), of_obvod).items():
        code, obvod = key
        row = obvody[key]
        contest = f"oz:{code}/{int(obvod)}"
        seats = (
            number(obce[code][_C_SEATS])
            if obvody_of[code] == 1
            else _seats(contests, contest)
        )
        ballots = _final_council_ballots(rows, votes.get(key, []))
        record = _final_record(row, "oz", ballots, _every_okrsok(row), seats)
        areas = _okrsok_areas(turnout.get(key, []), votes.get(key, []), "oz", _C_OKRSOK)
        yield contest, record, areas


def _final_cities(
    t: Tables,
    districts: Sequence[Mapping[str, str]],
    contests: Mapping[str, Contest],
    log: Log,
) -> Iterator[_Final]:
    """Yield the contests of Bratislava and Košice as wholes, by district.

    *districts* are the okrsky of every municipality (``tab02f``), among
    them the districts'; a city okrsok matched to one (:func:`city_matches`)
    goes to the okrsok files by it. Okrsky whose votes cannot be told apart
    (:func:`city_votes`) are left out of the okrsok files, and so are the
    districts' ``areas`` of the contest they make unknown; *log* is told.
    """
    cities = {r[_C_CITY]: r for r in t.rows("tab02x")}
    turnout = t.rows("tab02fx")
    matches = city_matches(turnout, districts)
    district_of = city_districts(turnout, districts, matches)

    def okrsok_of(i: int) -> str | None:
        """Return city row *i*'s okrsok in its district's numbering, if matched."""
        j = matches.get(i)
        return (
            None
            if j is None
            else okrsok_key(districts[j][_C_OBEC], districts[j][_C_OKRSOK])
        )

    def by_district(
        contest: str,
        record: Record,
        indices: Sequence[int],
        votes: Sequence[Mapping[str, str]],
    ) -> dict[str, Area]:
        """Set a city contest's ``areas`` by district; return its okrsky."""
        kind = contest.partition(":")[0]
        by_row = city_votes(turnout, indices, votes, kind, record.seats)
        record.areas, gone = city_areas(turnout, indices, by_row, kind, district_of.get)
        if by_row.unresolved:
            numbers = ", ".join(
                f"{turnout[u.okrsky[0]][_C_OBVOD]}/{turnout[u.okrsky[0]][_C_OKRSOK]}"
                f" ×{len(u.okrsky)}"
                for u in by_row.unresolved
            )
            log(
                f"{contest}: okrsky of a number not told apart (council obvod/"
                f"number ×okrsky: {numbers}); left out of the okrsok file"
                + (f" and of the areas of {', '.join(sorted(gone))}" if gone else "")
            )
        okrsky, _ = city_areas(turnout, indices, by_row, kind, okrsok_of)
        return okrsky

    rows_of = _group(range(len(turnout)), lambda i: turnout[i][_C_CITY])
    mayor_votes = _group(t.rows("tab05fx"), itemgetter(_C_CITY))
    for city, rows in _group(t.rows("tab05x"), itemgetter(_C_CITY)).items():
        row = cities[city]
        ballots = _final_ballots(rows, _C_NOTE, None)
        record = _final_record(row, "starosta", ballots, _every_okrsok(row), 1)
        contest = f"starosta:{CITY_OBCE[city]}"
        votes = mayor_votes.get(city, [])
        yield contest, record, by_district(contest, record, rows_of[city], votes)
    obvody = {(r[_C_CITY], r[_C_OBVOD]): r for r in t.rows("tab02ex")}
    of_obvod = itemgetter(_C_CITY, _C_OBVOD)
    council_votes = _group(t.rows("tab08fx"), of_obvod)
    for key, rows in _group(t.rows("tab08ex"), of_obvod).items():
        city, obvod = key
        row = obvody[key]
        contest = f"oz:{CITY_OBCE[city]}/{int(obvod)}"
        votes = council_votes.get(key, [])
        ballots = _final_council_ballots(rows, votes)
        seats = _seats(contests, contest)
        record = _final_record(row, "oz", ballots, _every_okrsok(row), seats)
        indices = [i for i in rows_of[city] if turnout[i][_C_OBVOD] == obvod]
        yield contest, record, by_district(contest, record, indices, votes)
    for city, rows in rows_of.items():
        unmatched = sum(1 for i in rows if i not in matches)
        if unmatched:
            log(
                f"{CITY_OBCE.get(city, city)}: {unmatched} of {len(rows)} okrsky match"
                " no single okrsok of a district; left out of the okrsok files"
            )


_REGIONAL_LEVELS = (
    ("predseda", _C_KRAJ, ("tab02a", "tab06a", "tab06c", "tab06d")),
    ("zsk", _C_VOBVOD, ("tab02b", "tab09b", "tab09c", "tab09d")),
)
"""The regional contests of a package by level: kind, the column of the
unit's code (kraj, regional obvod), and the tables of the units' turnout
and of the votes per unit, municipality and okrsok."""


def _final_regional(t: Tables, live: Live) -> None:
    """Add the contests of regional package *t* and its source to *live*."""
    obce = {r[_C_OBEC]: r for r in t.rows("tab02c")}
    okrsky = t.rows("tab02d")
    for kind, column, (turnout, whole, per_obec, per_okrsok) in _REGIONAL_LEVELS:
        of_unit = itemgetter(column)
        units = {r[column]: r for r in t.rows(turnout)}
        obec_votes = _group(t.rows(per_obec), of_unit)
        okrsok_turnout = _group(okrsky, of_unit)
        okrsok_votes = _group(t.rows(per_okrsok), of_unit)
        for code, rows in _group(t.rows(whole), of_unit).items():
            row = units[code]
            if kind == "predseda":
                kraj, contest, seats, others = code, f"predseda:{code}", 1, None
            else:
                # A regional obvod's code is its kraj's and its number.
                kraj, contest = code[:-2], f"zsk:{code[:-2]}/{int(code[-2:])}"
                seats, others = int(row[_C_SEATS]), 0
            ballots = _final_ballots(rows, _C_FLAG, others)
            record = _final_record(row, kind, ballots, _confirmed(row), seats)
            by_obec = _group(obec_votes.get(code, []), itemgetter(_C_OBEC))
            record.areas = {
                obec: _area(obce[obec], kind, _row_votes(mine))
                for obec, mine in by_obec.items()
            }
            okrsky_of = _okrsok_areas(
                okrsok_turnout.get(code, []),
                okrsok_votes.get(code, []),
                kind,
                _C_VOKRSOK,
            )
            live.add(_kraj_path(kraj), contest, record)
            live.add_okrsky(_kraj_path(kraj), contest, okrsky_of)
    kraje = {r[_C_KRAJ]: _confirmed(r) for r in t.rows("tab02a")}.values()
    counted = (sum(done for done, _ in kraje), sum(total for _, total in kraje))
    live.source["osk"] = source(t.time.isoformat(), counted, "okrsky")


def _kraj_path(kraj: str) -> str:
    return live_path(f"predseda:{kraj}", {})


# A municipal by-election's package.

_TYPE = "Typ volieb"
_NOT_HELD = "nekonajú sa"
"""The ``Typ volieb`` of an obec whose by-election did not take place,
casefolded: since 2023 it is capitalised, before not."""
_BY_TABLES: dict[str, frozenset[str]] = {
    "tab0dd": frozenset({_C_OBEC, _TYPE}),
    "tab02ad": frozenset({_C_OBEC, _C_SEATS}),
    "tab02bd": _TURNOUT | {_C_OBEC, _C_OKRES, _C_OKRSKY, _VALID_OF["starosta"]},
    "tab02be": _TURNOUT | {_C_OBEC, _C_OBVOD, _C_OKRSKY, _VALID_OF["oz"]},
    "tab02bf": _TURNOUT
    | {_C_OBEC, _C_OBVOD, _C_OKRSOK, _VALID_OF["starosta"], _VALID_OF["oz"]},
    "tab05d": _VOTE_COLUMNS | {_C_OBEC, _C_NOTE},
    "tab05f": _VOTE_COLUMNS | {_C_OBEC, _C_OKRSOK},
    "tab08e": _VOTE_COLUMNS | {_C_OBEC, _C_OBVOD, _C_FLAG},
    "tab08f": _VOTE_COLUMNS | {_C_OBEC, _C_OBVOD, _C_OKRSOK, _C_NOTE},
}
"""The tables read from a by-election's package, with the columns used:
those of the 2026 tables, but for the turnout tables' ids, the seats per
obec (``tab02ad``) and the withdrawn's ``X`` per okrsok as a note."""
_C_ENVELOPES = "Počet vydaných obálok"
"""The voters in the turnout of a by-election of 2019–2022: the envelopes
issued, as the night's files count them (``_GRAPH``)."""
_C_NAME = "Meno a priezvisko"
_OLDER_BY_TABLES: dict[str, frozenset[str]] = {
    "tab0c": frozenset({_C_OBEC, _TYPE, _C_SEATS}),
    "tab02bd": frozenset({_C_OBEC, _C_OKRES, _C_OKRSKY, _C_ELIGIBLE, _C_ENVELOPES})
    | {_VALID_OF["starosta"], _VALID_OF["oz"]},
    "tab05": _VOTE_COLUMNS | {_C_OBEC, _C_FLAG},
    "tab06": frozenset({_C_OBEC, _C_OBVOD, _C_NAME, _C_VOTES}),
}
"""The tables read from a by-election's package of 2019–2022
(:func:`older_by_election`), with the columns used: the obce with their
seats, the turnout and the mayors' votes per obec, the elected councillors
per obvod with their votes."""


def older_by_election(package: tables.Package) -> bool:
    """Return whether a by-election's *package* is of 2019–2022.

    ŠÚ SR's packages of the term elected in 2018 (``OSO_<yyyymm>_xlsx.zip``)
    are laid out otherwise than those since: their obce are ``tab0c``, not
    ``tab0dd``, their mayor candidates ``tab0a``; they have no results per
    okrsok, and of the councils the elected only.
    """
    return not package.has("tab0dd")


def read_by_election(
    paths: Sequence[Path], ref: Reference, log: Log = progress.note
) -> tuple[Live, list[str]]:
    """Return the results of a municipal by-election's package, and its sources.

    ŠÚ SR publishes the doplňujúce and nové voľby held on one day as one
    package (``OSO<yyyymm>_SK_xlsx.zip``, format ``susr-by``) of XLSX tables
    read by :mod:`election_map_slovakia.tables` (:data:`_BY_TABLES`): the
    turnout per obec, council obvod and okrsok, the votes of the mayors per
    obec and okrsok and of the councils per obvod and okrsok. A contest's
    record is its unit's, its okrsky go to the okrsok files; the contests
    of *ref* give the results file and a council's seats where the obec
    elects in several obvody (the package has the seats of the whole obec).
    A package of 2019–2022 (:func:`older_by_election`) is read as
    :func:`_older_by_election` says. The source is ``oso``, counted in the
    obce where something was to be elected; *log* is told of the contests
    of the candidate lists without results.
    """
    contests = ref.contests
    try:
        package = tables.open_package(paths, TIMEZONE)
        older = older_by_election(package)
        wanted = _OLDER_BY_TABLES if older else _BY_TABLES
        rows = {t: _table_rows(package, t, cols) for t, cols in wanted.items()}
    except tables.TableError as e:
        raise ResultsError(str(e)) from e
    live = Live("final")
    obce = {r[_C_OBEC]: r for r in rows["tab02bd"]}
    okres = {code: r[_C_OKRES] for code, r in obce.items()}
    of_obec, of_obvod = itemgetter(_C_OBEC), itemgetter(_C_OBEC, _C_OBVOD)

    def add(contest: str, record: Record, areas: dict[str, Area]) -> None:
        known = contests.get(contest)
        path = known.path if known else live_path(contest, okres)
        live.add(path, contest, record)
        if areas:
            live.add_okrsky(path, contest, areas)

    def okrsky_of(
        code: str,
        turnout: Sequence[Mapping[str, str]],
        votes: Sequence[Mapping[str, str]],
        kind: str,
    ) -> dict[str, Area]:
        """Return a contest's okrsky from its rows.

        None of Bratislava or Košice as a whole, whose own okrsky the
        package does not join to their districts'.
        """
        if code in CITY_OBCE:
            log(f"{CITY_OBCE[code]}: a {kind} contest's okrsky left out")
            return {}
        return _okrsok_areas(turnout, votes, kind, _C_OKRSOK)

    if older:
        _older_by_election(rows, ref, add)
    else:
        turnout = _group(rows["tab02bf"], of_obec)
        votes = _group(rows["tab05f"], of_obec)
        for code, mine in _group(rows["tab05d"], of_obec).items():
            row = obce[code]
            ballots = _final_ballots(mine, _C_NOTE, None)
            record = _final_record(row, "starosta", ballots, _every_okrsok(row), 1)
            areas = okrsky_of(
                code, turnout.get(code, []), votes.get(code, []), "starosta"
            )
            add(f"starosta:{CITY_OBCE.get(code, code)}", record, areas)
        obvody = {of_obvod(r): r for r in rows["tab02be"]}
        seats = {r[_C_OBEC]: number(r[_C_SEATS]) for r in rows["tab02ad"]}
        turnout = _group(rows["tab02bf"], of_obvod)
        votes = _group(rows["tab08f"], of_obvod)
        councils = _group(rows["tab08e"], of_obvod)
        electing = Counter(code for code, _ in councils)
        for key, mine in councils.items():
            code, obvod = key
            row = obvody[key]
            contest = f"oz:{CITY_OBCE.get(code, code)}/{int(obvod)}"
            n = seats.get(code) if electing[code] == 1 else _seats(contests, contest)
            ballots = _final_council_ballots(mine, votes.get(key, []), _C_NOTE)
            record = _final_record(row, "oz", ballots, _every_okrsok(row), n)
            add(
                contest,
                record,
                okrsky_of(code, turnout.get(key, []), votes.get(key, []), "oz"),
            )
    units = rows["tab0c" if older else "tab0dd"]
    held = {r[_C_OBEC] for r in units if r[_TYPE].strip().casefold() != _NOT_HELD}
    time = package.time.isoformat() if package.time else None
    live.source["oso"] = source(time, (len(held & obce.keys()), len(held)), "obce")
    found = live.records()
    lacking = sorted(
        c for c in contests if kinds.source_of(c) == "oso" and c not in found
    )
    if lacking:
        log(f"no results of {len(lacking)} contests: {', '.join(lacking)}")
    return live, ["oso"]


def _older_by_election(
    rows: Mapping[str, Sequence[Mapping[str, str]]],
    ref: Reference,
    add: Callable[[str, Record, dict[str, Area]], None],
) -> None:
    """Add the contests of a by-election's package of 2019–2022 with *add*.

    *rows* are its tables (:data:`_OLDER_BY_TABLES`). A mayor's record is
    the obec's, the voters the envelopes issued. A council's lists its
    elected only, whom the package names (titles and all) but does not
    number: each is the candidate of that name in *ref*
    (:func:`candidates.name_words`), as the candidate lists have them (read
    from the same package, or curated where its list was replaced:
    :mod:`election_map_slovakia.lists`). Where one obvod of the obec
    elects, the obec's turnout and seats are its; where several, those of
    none is known.
    """
    obce = {r[_C_OBEC]: {**r, _C_VOTERS: r[_C_ENVELOPES]} for r in rows["tab02bd"]}
    for code, mine in _group(rows["tab05"], itemgetter(_C_OBEC)).items():
        row = obce[code]
        ballots = _final_ballots(mine, _C_FLAG, None)
        record = _final_record(row, "starosta", ballots, _every_okrsok(row), 1)
        add(f"starosta:{CITY_OBCE.get(code, code)}", record, {})
    seats = {r[_C_OBEC]: number(r[_C_SEATS]) for r in rows["tab0c"]}
    councils = _group(rows["tab06"], itemgetter(_C_OBEC, _C_OBVOD))
    electing = Counter(code for code, _ in councils)
    for (code, obvod), mine in councils.items():
        contest = f"oz:{CITY_OBCE.get(code, code)}/{int(obvod)}"
        named = ref.candidates.get(contest, ())
        ballots: list[Ballot] = [
            (_named(named, r[_C_NAME], contest), int(r[_C_VOTES]), 1) for r in mine
        ]
        if electing[code] == 1:
            row = obce[code]
            n = seats.get(code)
            record = _final_record(row, "oz", ballots, _every_okrsok(row), n)
        else:
            n = _seats(ref.contests, contest)
            record = Record("final", None, None, None, None, n, len(ballots), ballots)
        add(contest, record, {})


def _named(cands: Iterable[Candidate], name: str, contest: str) -> int:
    """Return the ballot number of the candidate of *contest* named *name*."""
    words = candidates.name_words(name)
    found = [c.number for c in cands if candidates.name_words(c.name) == words]
    if len(found) != 1:
        how = "more than one candidate" if found else "no candidate"
        raise ResultsError(f"{contest}: {how} named {name!r} in the candidate lists")
    return found[0]


def _table_rows(
    package: tables.Package, table: str, columns: Iterable[str]
) -> list[dict[str, str]]:
    """Return the rows of *table* of *package*; fail unless it has *columns*."""
    t = package.table(table)
    for column in sorted(columns):
        t.column(column)
    return t.rows


# Dummy results.


@dataclass(frozen=True)
class Stage:
    """How far the counting of a :func:`fake` stage is."""

    regional: float
    """Share of the municipalities whose okrsky are counted, regional."""
    municipal: float
    """Share of the municipalities whose results are in, municipal."""
    cities: float
    """Share of the districts counted for the mayors of Bratislava, Košice."""
    time: str


STAGES = {
    "none": Stage(0, 0, 0, "2026-10-24T20:00:00+02:00"),
    "early": Stage(0.1, 0, 0, "2026-10-24T22:30:00+02:00"),
    "mid": Stage(0.6, 0.4, 0.5, "2026-10-25T01:30:00+02:00"),
    "late": Stage(1, 1, 1, "2026-10-25T05:00:00+01:00"),
    "final": Stage(1, 1, 1, "2026-10-25T14:00:00+01:00"),
}
_VOTERS_PER_OKRSOK = 800
"""Registered voters of a fake okrsok where the real count is not given."""
_DEFAULT_PAST = (500, 200)
_LANDSLIDE_RANK = 0.5
"""The landslide obvod's municipalities are counted at half the others'
share: all of them by the middle of the night."""
_UNFILLED = 0.05
"""Share of fake councils with a seat left empty."""
_CLOSE = (1.0, 0.98)
"""Popularity of the close race's two leaders, relative."""
_LANDSLIDE = (0.75, 0.05)
"""Share of the ballots marking a winner, a loser of the landslide."""
_COUNCIL_REACH = 0.6
"""Share of the ballots marking a council's most popular candidate."""
_COUNCIL_MARKS = 0.5
"""Share of the marks a council's voters could make (one per seat) that
they make at most."""
_COUNCIL_SEATS = (3, 9)
_PAST_LEFT_OUT = 0.25
"""Share of the fake obce of several okrsky whose earlier okrsky are not
known (:data:`UNKNOWN`)."""
_PAST_RAN = 0.5
"""Share of the fake candidates who stood for the same office before."""


@dataclass(frozen=True)
class _Unit:
    code: str
    eligible: int
    voters: int
    valid: int
    okrsky: int
    rank: float
    """The unit is counted once the stage's share passes it."""


def rng(seed: int, *key: object) -> random.Random:
    """Return the random numbers of a fake's *key* for *seed*."""
    # A string seed is hashed with SHA-512: the same numbers in every run.
    return random.Random(":".join(map(str, (seed, *key))))


def apportion(total: int, weights: Sequence[float]) -> list[int]:
    """Return *total* split in proportion to *weights*, the parts adding up to it.

    Each part is the step between rounded running totals, so rounding
    never loses or adds a unit.
    """
    if not any(weights):
        weights = [1.0] * len(weights)
    whole = sum(weights)
    parts, done, running = [], 0, 0.0
    for w in weights:
        running += w
        upto = round(total * running / whole)
        parts.append(upto - done)
        done = upto
    parts[-1] += total - done
    return parts


def deal(total: int, weights: Sequence[float], caps: Sequence[int]) -> list[int]:
    """Return *total* split in proportion to *weights*, no part above its cap.

    What a part has no room for goes to the others with room, in proportion
    again. The caps leave room for it all (they add up to *total* or more).
    """
    parts = [0] * len(weights)
    left = total
    while left:
        room = [i for i, part in enumerate(parts) if part < caps[i]]
        for i, share in zip(room, apportion(left, [weights[i] for i in room])):
            given = min(share, caps[i] - parts[i])
            parts[i] += given
            left -= given
    return parts


def fake_okrsky(
    seed: int, contest: str, code: str, area: Area, numbers: Iterable[int]
) -> dict[str, Area]:
    """Return *area* of *contest* in obec *code* split into its okrsky *numbers*.

    An okrsok's size and turnout are its own in every contest; the
    candidates' votes lean a different way in each, keeping to what the
    check holds the okrsky to: in a single-choice contest each okrsok's
    votes are its valid ballots, dealt out okrsok by okrsok from what the
    candidates have left; in a council's no candidate has more votes in an
    okrsok than its valid ballots.
    """
    e, v, valid, votes = area
    numbers = list(numbers)
    shape = [rng(seed, "okrsok", code, k) for k in numbers]
    size = [r.uniform(0.5, 1.5) for r in shape]
    eligible = apportion(e or 0, size)
    voters = apportion(
        v or 0,
        [x * r.uniform(0.92, 1.08) for x, r in zip(eligible, shape, strict=True)],
    )
    valids = apportion(valid or 0, voters)
    lean = rng(seed, "lean", contest, code)
    names = sorted(votes)
    leans = {n: [lean.uniform(0.6, 1.4) for _ in numbers] for n in names}
    if kinds.parse(contest).single:
        left = dict(votes)
        cells = {n: [0] * len(numbers) for n in names}
        for i, count in enumerate(valids):
            parts = deal(
                count,
                [left[n] * leans[n][i] for n in names],
                [left[n] for n in names],
            )
            for n, part in zip(names, parts, strict=True):
                cells[n][i] = part
                left[n] -= part
    else:
        cells = {
            n: deal(
                votes[n],
                [w * x for w, x in zip(valids, leans[n], strict=True)],
                valids,
            )
            for n in names
        }
    return {
        okrsok_key(code, k): (
            eligible[i],
            voters[i],
            valids[i],
            {n: cells[n][i] for n in names},
        )
        for i, k in enumerate(numbers)
    }


class _Fake:
    """The figures behind :func:`fake`, the same at every stage."""

    def __init__(
        self,
        ref: Reference,
        seed: int,
        okrsky: Mapping[str, int],
        obvod_okrsky: Mapping[str, Mapping[int, Sequence[int]]],
    ) -> None:
        self.ref = ref
        self.seed = seed
        self.okrsky = okrsky
        self.obvod_okrsky = obvod_okrsky
        self.units = {
            p.code: self._unit(p.code, p.past, p.code)
            for p in ref.places.values()
            if p.zsk is not None
        }
        regional = [c for _, councils in ref.regional.values() for c in councils]
        self.landslide = min(
            (c for c in regional if c.past and self._numbers(c) and self._places(c)),
            key=lambda c: (c.past or _DEFAULT_PAST)[0],
            default=None,
        )
        self.close = next(
            (p.id for p, _ in ref.regional.values() if p and len(self._numbers(p)) > 1),
            None,
        )
        if self.landslide:
            for code in self._places(self.landslide):
                u = self.units[code]
                self.units[code] = replace(u, rank=u.rank * _LANDSLIDE_RANK)

    def _unit(self, key: str, past: tuple[int, int] | None, code: str) -> _Unit:
        r = rng(self.seed, "unit", key)
        e0, v0 = past or _DEFAULT_PAST
        eligible = max(1, round(e0 * r.uniform(0.97, 1.01)))
        turnout = v0 / max(e0, 1) * r.uniform(0.9, 1.15)
        voters = min(eligible, round(eligible * turnout))
        valid = round(voters * r.uniform(0.95, 0.99))
        okrsky = self._okrsok_count(code, eligible)
        return _Unit(code, eligible, voters, valid, okrsky, r.random())

    def _okrsok_count(self, code: str, eligible: int | None) -> int:
        """Return the okrsky of municipality *code*: the real count if given."""
        return self.okrsky.get(code) or max(
            1, round((eligible or 0) / _VOTERS_PER_OKRSOK)
        )

    def okrsky_of(self, c: Contest, record: Record) -> dict[str, Area]:
        """Return the okrsky of final contest *c*, adding up to its *record*.

        A regional or city contest has them per municipality (``areas``),
        a council obvod those of its rule set; none where the rule set does
        not give them, as the obvod's okrsky are then not known. Other
        contests have all those of their municipality.
        """
        if record.areas is not None:
            parts = list(record.areas.items())
        else:
            votes = {n: v for n, v, _ in record.candidates}
            parts = [(c.area, (record.eligible, record.voters, record.valid, votes))]
        out: dict[str, Area] = {}
        for code, area in parts:
            numbers: Iterable[int] = range(1, self._okrsok_count(code, area[0]) + 1)
            if c.kind == "oz" and code == c.area:
                known = self.obvod_okrsky.get(code, {}).get(c.obvod or 0)
                if known:
                    numbers = sorted(known)
                elif len(self.ref.municipal[code][1]) > 1:
                    continue
            out |= fake_okrsky(self.seed, c.id, code, area, numbers)
        return out

    def past(self, live: Live, day: str) -> Past:
        """Return a made-up :class:`Past` of *live*'s okrsky, of *day*.

        Each obec of several okrsky gets a method drawn for all of them, some
        :data:`UNKNOWN`; each okrsok of a known one and each obec wholly in
        a contest its figures, near this election's, with the votes of some
        of the candidates.
        """
        okrsky: dict[str, set[str]] = defaultdict(set)
        for contests in live.okrsky.values():
            for areas in contests.values():
                for key in areas:
                    okrsky[key.partition("/")[0]].add(key)
        past = Past(day, self._methods(okrsky))
        for contests in live.okrsky.values():
            for contest, areas in contests.items():
                units = self._units(contest, areas, past.methods, okrsky)
                if units:
                    past.contests[contest] = units
        return past

    def _units(
        self,
        contest: str,
        areas: Mapping[str, Area],
        methods: Mapping[str, int],
        okrsky: Mapping[str, Collection[str]],
    ) -> dict[str, Area]:
        """Return made-up earlier figures of *contest*'s okrsky and whole obce."""
        ran = {
            n
            for n in self._numbers(self.ref.contests[contest])
            if rng(self.seed, "ran", contest, n).random() < _PAST_RAN
        }
        units: dict[str, Area] = {}
        by_obec: dict[str, list[Area]] = defaultdict(list)
        for key, area in areas.items():
            then = self._then(contest, key, area, ran)
            by_obec[key.partition("/")[0]].append(then)
            if methods.get(key, UNKNOWN) != UNKNOWN:
                units[key] = then
        for obec, thens in by_obec.items():
            if len(thens) == len(okrsky[obec]):
                units[obec] = sum_areas(thens)
        return units

    def _methods(self, okrsky: Mapping[str, Collection[str]]) -> dict[str, int]:
        """Return a method drawn per obec of several *okrsky* for all of them."""
        methods: dict[str, int] = {}
        for obec, keys in sorted(okrsky.items()):
            if len(keys) > 1:
                r = rng(self.seed, "past", obec)
                left_out = r.random() < _PAST_LEFT_OUT
                method = UNKNOWN if left_out else r.choice(PAST_METHODS[1:])
                methods |= dict.fromkeys(keys, method)
        return methods

    def _then(self, contest: str, key: str, area: Area, ran: Collection[int]) -> Area:
        """Return made-up earlier figures of okrsok *key* of *contest*."""
        e, v, valid, votes = area
        r = rng(self.seed, "then", key)
        eligible = round((e or 0) * r.uniform(0.95, 1.05))
        share = r.uniform(0.8, 1.1)
        voters = min(eligible, round((v or 0) * share))
        valid_then = min(voters, round((valid or 0) * share))
        jitter = rng(self.seed, "then", contest, key)
        return (
            eligible,
            voters,
            valid_then,
            {
                n: min(valid_then, round(x * share * jitter.uniform(0.7, 1.3)))
                for n, x in votes.items()
                if n in ran
            },
        )

    def _places(self, c: Contest) -> list[str]:
        """Return the municipalities of a regional or city contest."""
        places = [p for p in self.ref.places.values() if p.code in self.units]
        if c.kind == "predseda":
            return [p.code for p in places if p.kraj == c.area]
        if c.kind == "zsk":
            return [p.code for p in places if p.kraj == c.area and p.zsk == c.obvod]
        if c.kind == "oz":
            return [
                p.code for p in places if p.city == c.area and p.city_obvod == c.obvod
            ]
        return [p.code for p in places if p.city == c.area]

    def _numbers(self, c: Contest) -> list[int]:
        return sorted(x.number for x in self.ref.candidates.get(c.id, ()))

    def _weights(self, c: Contest) -> dict[int, float]:
        """Return each candidate's popularity in *c*."""
        r = rng(self.seed, "weights", c.id)
        numbers = self._numbers(c)
        weights = {n: r.expovariate(1) ** 2 for n in numbers}
        order = sorted(numbers, key=lambda n: -weights[n])
        if c.id == self.close:
            top = weights[order[0]]
            weights[order[0]], weights[order[1]] = top * _CLOSE[0], top * _CLOSE[1]
        if self.landslide is not None and c.id == self.landslide.id:
            seats = c.seats or 1
            weights = {n: _LANDSLIDE[i >= seats] for i, n in enumerate(order)}
        return weights

    def _votes(self, c: Contest, unit: _Unit, seats: int) -> dict[int, int]:
        """Return the votes of each candidate of *c* of *seats* in *unit*."""
        weights = self._weights(c)
        r = rng(self.seed, "votes", c.id, unit.code)
        if c.single:
            noisy = [w * r.uniform(0.85, 1.15) for w in weights.values()]
            return dict(zip(weights, apportion(unit.valid, noisy), strict=True))
        if self.landslide is not None and c.id == self.landslide.id:
            votes = [
                round(unit.valid * w * r.uniform(0.9, 1.1)) for w in weights.values()
            ]
        else:
            # A council voter marks several candidates: each candidate is on
            # a share of the ballots of its own.
            top = max(weights.values())
            votes = [
                round(unit.valid * _COUNCIL_REACH * w / top * r.uniform(0.8, 1.2))
                for w in weights.values()
            ]
        room = math.floor(unit.valid * seats * _COUNCIL_MARKS)
        if sum(votes) > room:
            votes = apportion(room, votes)
        return dict(zip(weights, votes, strict=True))

    def _elect(self, c: Contest, record: Record, elected: int) -> None:
        """Flag the *elected* candidates with the most votes, the rest lost."""
        order = sorted(record.candidates, key=lambda b: (-b[1], b[0]))
        loser = None if c.single else 0
        won = {b[0] for b in order[:elected]}
        record.candidates = [(n, v, 1 if n in won else loser) for n, v, _ in order]
        record.filled = len(won)

    def counted(
        self, c: Contest, share: float, final: bool, night: bool
    ) -> Record | None:
        """Return a contest counted by municipality (regional, city), or None.

        ``areas`` per municipality when *final*, or by *night* (a regional
        contest) those of the municipalities counted, with a president's
        obvody as a whole too, as :func:`night` makes them; else none.
        """
        units = [self.units[k] for k in self._places(c)]
        counted = [u for u in units if share >= 1 or u.rank < share]
        if not counted or not self._numbers(c):
            return None
        totals: dict[int, int] = {}
        areas: dict[str, Area] = {}
        for u in counted:
            votes = self._votes(c, u, c.seats or 1)
            totals = _add(totals, votes)
            keys = [u.code]
            zsk = self.ref.places[u.code].zsk
            if night and c.kind == "predseda" and zsk:
                keys.append(f"obvod:{zsk}")
            for key in keys:
                unit = (u.eligible, u.voters, u.valid, votes)
                areas[key] = _add_area(areas.get(key, (0, 0, 0, {})), unit)
        record = Record(
            "final" if final else "partial",
            (sum(u.okrsky for u in counted), sum(u.okrsky for u in units)),
            sum(u.eligible for u in counted),
            sum(u.voters for u in counted),
            sum(u.valid for u in counted),
            c.seats or 1,
            candidates=[(n, v, None) for n, v in sorted(totals.items())],
            areas=areas if final or night else None,
        )
        if final:
            self._elect(c, record, record.seats or 1)
        return record

    def city(self, c: Contest, share: float, final: bool) -> Record | None:
        """Return a Bratislava or Košice contest at *share* of its districts.

        Its council obvody are in once the city is fully counted, with their
        winners only until *final*.
        """
        if c.kind == "oz" and share < 1:
            return None
        record = self.counted(c, share, final, night=False)
        if record is None or final or c.kind == "starosta":
            return record
        self._elect(c, record, record.seats or 1)
        record.status, record.counted, record.candidates = "winner", None, []
        return record

    def municipal(self, c: Contest, final: bool) -> Record | None:
        """Return a municipal contest outside the cities, its results in."""
        if not self._numbers(c):
            return None
        councils = self.ref.municipal[c.area][1]
        # A council of several obvody: each gets an equal part of the voters.
        part = 1 if c.kind == "starosta" else len(councils)
        e0, v0 = c.past or _DEFAULT_PAST
        unit = self._unit(c.id, (e0 // part, v0 // part), c.area)
        r = rng(self.seed, "seats", c.id)
        seats = c.seats or (1 if c.kind == "starosta" else r.randint(*_COUNCIL_SEATS))
        record = Record("winner", None, unit.eligible, unit.voters, unit.valid, seats)
        record.candidates = [
            (n, v, None) for n, v in self._votes(c, unit, seats).items()
        ]
        unfilled = c.kind == "oz" and r.random() < _UNFILLED
        self._elect(c, record, seats - unfilled)
        if final:
            record.status = "final"
        elif c.kind == "oz":
            record.candidates = []
            if part > 1:
                record.eligible = record.voters = record.valid = None
        else:
            record.candidates = [b for b in record.candidates if b[2] == 1]
        return record

    def reported(self, area: str, share: float) -> bool:
        """Whether a municipality's results are in at *share*."""
        return share >= 1 or rng(self.seed, "report", area).random() < share

    def sources(self, s: Stage) -> dict[str, dict[str, Any]]:
        """Return ``source`` of ``status.json`` at stage *s*: the election's."""
        units = self.units.values()
        counted = [u for u in units if s.regional >= 1 or u.rank < s.regional]
        areas = [
            area
            for area in self.ref.municipal
            if (
                s.cities >= 1
                if area in candidates.CITY_CODES
                else self.reported(area, s.municipal)
            )
        ]
        out = {
            "osk": source(
                s.time,
                (sum(u.okrsky for u in counted), sum(u.okrsky for u in units)),
                "okrsky",
            ),
            "oso": source(s.time, (len(areas), len(self.ref.municipal)), "obce"),
        }
        return {name: entry for name, entry in out.items() if name in self.ref.sources}

    def regional(self, s: Stage, final: bool) -> Iterator[tuple[Contest, Record]]:
        """Yield the regional contests counted at stage *s*."""
        if s.regional <= 0:
            return
        for president, councils in self.ref.regional.values():
            for c in (president, *councils):
                if c is None:
                    continue
                record = self.counted(c, s.regional, final, night=not final)
                if record:
                    yield c, record

    def municipalities(self, s: Stage, final: bool) -> Iterator[tuple[Contest, Record]]:
        """Yield the municipal contests with results at stage *s*."""
        for area, (mayor, councils) in self.ref.municipal.items():
            city = area in candidates.CITY_CODES
            share = s.cities if city else s.municipal
            if share <= 0 or not (city or self.reported(area, share)):
                continue
            for c in (mayor, *councils):
                if c is None:
                    continue
                record = (
                    self.city(c, share, final) if city else self.municipal(c, final)
                )
                if record:
                    yield c, record


def fake(
    ref: Reference,
    stage: str,
    seed: int = 0,
    okrsky: Mapping[str, int] | None = None,
    obvod_okrsky: Mapping[str, Mapping[int, Sequence[int]]] | None = None,
    past: Mapping[str, str] | None = None,
) -> Live:
    """Return dummy results of the counting at *stage* (:data:`STAGES`).

    Of a municipal and regional election or a by-election (the sources of
    *ref*'s contests); :func:`national.fake` makes the national kinds'.

    Turnout follows each area's past election, votes a stable random
    distribution. The counted parts only grow from one stage to the next
    (same *seed*). The first kraj's president race stays too close to call
    to the end; the regional obvod with the fewest voters is fully counted
    by ``mid`` with a landslide that decides it.

    ``final`` has the okrsky of every contest too, as many per municipality
    as *okrsky* says (else one per 800 registered voters), a council
    obvod's those of *obvod_okrsky* (municipality → obvod → okrsok numbers)
    where given, and, of the sources *past* names (source → the day of the
    election before its contests are compared with, :attr:`Expect.past`), a
    made-up ``past`` for most of the municipalities of several.
    """
    s = STAGES[stage]
    model = _Fake(ref, seed, okrsky or {}, obvod_okrsky or {})
    final = stage == "final"
    live = Live("none" if stage == "none" else ("final" if final else "partial"))
    live.source = model.sources(s)
    if live.phase == "none":
        return live
    for c, record in (*model.regional(s, final), *model.municipalities(s, final)):
        live.add(c.path, c.id, record)
        if final:
            areas = model.okrsky_of(c, record)
            if areas:
                # A municipal contest is counted by its okrsky, as the CSV
                # tables'.
                record.counted = record.counted or (len(areas), len(areas))
                live.add_okrsky(c.path, c.id, areas)
    if final:
        days = past or {}
        for day in sorted(set(days.values())):
            sources = [s for s, d in days.items() if d == day]
            then = model.past(live.part(sources), day)
            live.past |= dict.fromkeys(sources, then)
    _count_voters(live, ref)
    return live


def describe(directory: Path) -> list[str]:
    """Return a summary of the results in *directory*: phase, version, counts."""
    st = read_status(directory)
    if st is None:
        return [f"{directory}: no {STATUS_FILE}"]
    lines = [f"phase {st['phase']}, version {st['version']}, updated {st['updated']}"]
    for name, entry in sorted(st["source"].items()):
        counted = entry["counted"]
        done = (
            f"{counted[0]:,} of {counted[1]:,} {entry['unit']}"
            if counted
            else "unknown"
        )
        lines.append(f"  {name}: {done} counted, data of {entry['time']}")
    live = read_live(directory)
    by_status = Counter(r.status for r in (live.records().values() if live else ()))
    okrsky = sum(1 for path in st["files"] if path.startswith(f"{OKRSKY_DIR}/"))
    areas = len(st["files"]) - okrsky - (TURNOUT_FILE in st["files"])
    lines.append(
        f"  {areas} area files, {okrsky} okrsok files, "
        + (", ".join(f"{n} {k}" for k, n in sorted(by_status.items())) or "no contests")
    )
    return lines
