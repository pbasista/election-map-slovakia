"""Live election results: the files of the live site, from ŠÚ SR's data.

On election night (24–25 October 2026) ŠÚ SR publishes the counting of the
municipal (OSO) and regional (OSK) elections on https://volbysr.sk/oso/ and
https://volbysr.sk/osk/ as JSON files that its own pages read and that it
overwrites as the records of the electoral commissions come in; a day or two
later the definitive results follow as CSV tables in a zip. ``ems results``
turns either into the files of the live site, a Cloudflare Pages project of
its own (``live_pages_project`` in ``config/site.toml``, served at
``live_url``) that the app reads (``web/js/live.js``)::

    live/status.json   {version, updated, phase, source: {osk, oso}, files}
    live/<area>.json   {contests: {contest: {status, counted, eligible,
                        voters, valid, seats, filled, candidates, (areas)}}}
    live/_headers      CORS for every origin, no-cache, nosniff
    live/404.html      so that Pages answers a missing file with 404, not
                       with an index page

``<area>`` is the main site's area file of the contest without ``data/``
(:func:`live_path`). The format is the shared contract of docs/results.md.
``status.json`` names every area file with a hash of its content, which the
app appends to the URL; its ``version`` changes whenever anything in it does
(:func:`write`), and a run that changes nothing writes nothing, so that a
deployment follows only a change.

Sources (:func:`night`, :func:`read_final`, :func:`fake`):

- ``poll``: the night's JSON. The progress files (``tab01.json``,
  ``dateSK.json`` of each election) are fetched every interval with
  conditional requests; only when one changed are the per-unit files
  fetched: for the regional election the turnout per kraj, obvod and
  municipality (``tab02ba``, ``tab02bb/<kraj>``, ``tab02bc/<obvod>``) and
  the votes per kraj and obvod (``tab06b/<kraj>``, ``tab06c/<obvod>``,
  ``tab09c/<obvod>``), plus each municipality's (``tab06d/<obec>``,
  ``tab09d/<obec>``) once its okrsky are all counted, then not again until
  every okrsok is; for the municipal election each
  municipality's summary (``graph01/<obec>``: turnout, the elected mayor by
  name, the council seats filled), which is not fetched again once the
  municipality is fully counted, the mayor candidates of Bratislava and
  Košice (``tab05/<obec>``) and, once every municipality is counted, all
  mayor and council candidates (``tab05``, ``tab06e1`` elected and
  ``tab06e2`` all council candidates). A file missing (404) is a unit not
  counted yet. The night's mayors other than the two cities' come by name
  only; :func:`match_winner` finds their ballot number. Every fetched file
  is kept under ``data/raw/results/<UTC time>/``.
- ``final``: the definitive CSV tables (:func:`read_final`), per okrsok,
  summed per contest. Their tables are recognized by their titles in the
  package's ``tab_info`` table and checked for the columns used, as the
  letters ending their names change between elections.
- ``fake``: plausible, deterministic dummy results from the candidate lists
  for testing the app (:func:`fake`).

The column meanings of the night's JSON are those of the 2026 site scripts
(``functions.js`` of oso/ and osk/), checked against the 2018 and 2022
files where the tables existed then; the constants named ``_GRAPH``,
``_OSK_TURNOUT``, ``_BALLOT`` and ``_COUNCIL_BALLOT`` hold them.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import http.client
import io
import json
import math
import random
import re
import ssl
import subprocess
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from election_map_slovakia import build, candidates, fetch, geo, output, progress

LIVE_DIR = "live"
RAW_DIR = "results"
"""Below ``data/raw/``: every file ``poll`` fetched, per poll."""
STATUS_FILE = "status.json"
PORT = 8766
INTERVAL = 60
BASE_URL = "https://volbysr.sk"
CONCURRENCY = 8
"""Requests to volbysr.sk at a time."""
TIMEOUT = 30
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
_VERSION_HASH = 4
_HTTP_OK = 200
_HTTP_NOT_MODIFIED = 304
_HTTP_NOT_FOUND = 404
_FULL = 100.0
"""Per cent counted of a fully counted municipality."""
_LIVE_HEADERS = (
    "# Written by `ems results`: read-only public data for any origin, always\n"
    "# revalidated, as it changes all night.\n"
    "/*\n"
    "  Access-Control-Allow-Origin: *\n"
    "  Cache-Control: no-cache\n"
    "  X-Content-Type-Options: nosniff\n"
)
_NOT_FOUND_PAGE = b"<!doctype html>\n<title>404 Not Found</title>\n<p>Not found.\n"
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
_WITHDRAWN = "x"
_OBVOD_NAME = re.compile(r"^\s*(\d+)\.|č\.\s*(\d+)")
_NUMBER_GAPS = re.compile(r"[\s\u00a0\u202f]+")
_TIME = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([^\W\d_]+)?"
)
# ŠÚ SR writes the time zone after the time: summer (SELČ, CEST) or winter
# (SEČ, CET) time; the clocks go back at 03:00 on 25 October 2026.
_ZONES = {"SELČ": 2, "CEST": 2, "SEČ": 1, "CET": 1}
_CONTEST_ID = re.compile(
    r"(?:starosta:(?:\d{6}|BA|KE)|oz:(?:\d{6}|BA|KE)/[1-9]\d*"
    r"|predseda:[1-8]|zsk:[1-8]/[1-9]\d*)"
)
_AREA_KEY = re.compile(r"\d{6}|obvod:[1-9]\d*")
_RECORD_KEYS = frozenset(
    {"status", "counted", "eligible", "voters", "valid", "seats", "filled"}
    | {"candidates"}
)
_TABLE_ID = re.compile(r"_(tab\w+?)\.csv$", re.IGNORECASE)


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
class Contest:
    """A contest of the candidate lists."""

    id: str
    kind: str
    area: str
    obvod: int | None
    path: str
    """Its live area file (:func:`live_path`)."""
    seats: int | None
    """Seats elected, where known before the election."""
    past: tuple[int, int] | None
    """Eligible and voters of its area in its last election (``past``)."""


@dataclass(frozen=True)
class Place:
    """A municipality (or Bratislava or Košice as a whole)."""

    code: str
    name: str
    kraj: str
    city: str | None
    """BA or KE for a district of the city."""
    zsk: int | None
    """Its 2026 regional obvod."""
    city_obvod: int | None
    """Its city council obvod, for a district of Bratislava or Košice."""
    past: tuple[int, int] | None
    """Eligible and voters in the 2022 regional election."""


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


def live_path(contest: Mapping[str, Any], okres_of: Mapping[str, str]) -> str:
    """Return the live area file of *contest*: the main site's, bare.

    That is :func:`build.area_file` without ``data/`` and ``.json``, as the
    app's ``areaPath`` names it.
    """
    return (
        build.area_file(contest, okres_of).removeprefix("data/").removesuffix(".json")
    )


def reference(
    data: Mapping[str, Any],
    props: Mapping[str, Mapping[str, Any]],
    seats: Mapping[str, int],
) -> Reference:
    """Return the :class:`Reference` of ``candidates.json`` *data*.

    *props* are the municipalities' :func:`build.obec_props`, *seats* the
    known seats per obvod contest (:func:`build.obvod_seats`).
    """
    okres_of = {o["code"]: o.get("okres", "") for o in data["obce"]}
    regional_past = build.regional_past(data, props)
    contests = {}
    for c in data["contests"]:
        past = c.get("past") or regional_past.get(c["id"])
        known = seats.get(c["id"], 1 if c["kind"] in ("starosta", "predseda") else None)
        contests[c["id"]] = Contest(
            c["id"],
            c["kind"],
            str(c["area"]),
            c.get("obvod"),
            live_path(c, okres_of),
            known,
            (past["eligible"], past["voters"]) if past else None,
        )
    by_contest: dict[str, list[Candidate]] = defaultdict(list)
    for c in data["candidacies"]:
        by_contest[c["contest"]].append(
            Candidate(
                c["number"],
                candidates.search_key(f"{c['first_name']} {c['surname']}"),
                tuple(candidates.search_key(p) for p in c["parties"]),
                bool(c.get("independent")),
            )
        )
    places = {o["code"]: _place(o, props.get(o["code"], {})) for o in data["obce"]}
    return Reference(
        contests,
        {k: tuple(v) for k, v in by_contest.items()},
        places,
        {k["code"]: k["name"] for k in data["kraje"]},
        _bodies(contests.values(), "starosta", "oz"),
        _bodies(contests.values(), "predseda", "zsk"),
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


def load_reference(build_dir: Path, curated_dir: Path) -> Reference:
    """Return the :class:`Reference` of the built candidates and geometry."""
    data_path = build_dir / candidates.OUTPUT_FILE
    geo_dir = build_dir / geo.OUTPUT_DIR
    for path in (data_path, geo_dir):
        if not path.exists():
            raise ResultsError(f"{path} missing; run `ems make` first")
    return reference(
        json.loads(data_path.read_bytes()),
        build.obec_props(geo_dir),
        build.obvod_seats(geo_dir, curated_dir),
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


# The live files.

Area = tuple[int | None, int | None, int | None, dict[int, int]]
"""Eligible, voters, valid and votes per ballot number of a sub-unit."""
Ballot = tuple[int, int, int | None]
"""Ballot number, votes, flag (1 elected, 0 substitute, None)."""


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

    def to_json(self) -> dict[str, Any]:
        """Return the record as written, candidates by votes."""
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
        if self.areas is not None:
            out["areas"] = {
                key: [e, v, valid, {str(n): x for n, x in sorted(votes.items())}]
                for key, (e, v, valid, votes) in sorted(self.areas.items())
            }
        return out

    @classmethod
    def from_json(cls, entry: Mapping[str, Any]) -> Record:
        """Return the record of a written *entry*."""
        areas = entry.get("areas")
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
            None
            if areas is None
            else {
                k: (e, v, valid, {int(n): x for n, x in votes.items()})
                for k, (e, v, valid, votes) in areas.items()
            },
        )


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


def _no_source() -> dict[str, dict[str, Any]]:
    return {"osk": source(None, None, "okrsky"), "oso": source(None, None, "obce")}


@dataclass
class Live:
    """Everything a live site holds: phase, sources and area files."""

    phase: str
    source: dict[str, dict[str, Any]] = field(default_factory=_no_source)
    files: dict[str, dict[str, Record]] = field(default_factory=dict)
    """Area file → contest → record."""

    def add(self, path: str, contest: str, record: Record) -> None:
        """Put *record* of *contest* into area file *path*."""
        self.files.setdefault(path, {})[contest] = record

    def records(self) -> dict[str, Record]:
        """Return contest → record of every area file."""
        return {c: r for contests in self.files.values() for c, r in contests.items()}


def render(live: Live) -> dict[str, bytes]:
    """Return area file → content, of the area files with a contest."""
    return {
        path: build.encode({"contests": {c: r.to_json() for c, r in contests.items()}})
        for path, contests in sorted(live.files.items())
        if contests
    }


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
    fingerprint = _digest(build.encode([live.phase, live.source, files]))
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
        data = json.loads((directory / STATUS_FILE).read_bytes())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write(
    directory: Path, live: Live, now: dt.datetime | None = None
) -> dict[str, Any] | None:
    """Replace *directory* with *live*; return the new status, or None.

    Nothing is written when phase, sources and files are those of the status
    already there. The directory is written beside the old one and swapped
    in when complete.
    """
    contents = render(live)
    moment = now or dt.datetime.now(TIMEZONE).replace(microsecond=0)
    new = status(live, contents, read_status(directory), moment)
    if new is None:
        return None
    with output.replacing(directory) as tmp:
        for path, data in contents.items():
            out = tmp / f"{path}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
        (tmp / STATUS_FILE).write_bytes(build.encode(new))
        write_static(tmp)
    return new


def write_static(directory: Path) -> None:
    """Write the live site's ``_headers`` and ``404.html`` into *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / build.HEADERS).write_text(_LIVE_HEADERS, encoding="utf-8")
    (directory / build.NOT_FOUND).write_bytes(_NOT_FOUND_PAGE)


def read_live(directory: Path) -> Live | None:
    """Return the live site in *directory*, or None if it has none."""
    st = read_status(directory)
    if st is None:
        return None
    live = Live(st["phase"], st["source"])
    for path in st["files"]:
        content = json.loads((directory / f"{path}.json").read_bytes())
        for contest, entry in content["contests"].items():
            live.add(path, contest, Record.from_json(entry))
    return live


def merge(old: Live | None, new: Live, elections: Collection[str]) -> Live:
    """Return *old* with the contests and sources of *new* in place of its own.

    *elections* are those *new* has in full (``oso``, ``osk``): with both,
    the phase is final; otherwise the old phase stays, at least partial.
    """
    base = old or Live("none")
    merged = Live(
        base.phase,
        {**base.source, **{e: new.source[e] for e in elections}},
        {path: dict(contests) for path, contests in base.files.items()},
    )
    for path, contests in new.files.items():
        for contest, record in contests.items():
            merged.add(path, contest, record)
    both = {"oso", "osk"} <= set(elections)
    merged.phase = (
        "final" if both else ("partial" if base.phase == "none" else base.phase)
    )
    return merged


def check(directory: Path) -> list[str]:
    """Return what in the live site in *directory* breaks the contract."""
    st = read_status(directory)
    if st is None:
        return [f"{STATUS_FILE} missing or not a JSON object"]
    problems = _check_status(st)
    files = st.get("files")
    listed: dict[str, Any] = files if isinstance(files, dict) else {}
    present = {
        p.relative_to(directory).with_suffix("").as_posix()
        for p in directory.rglob("*.json")
    } - {STATUS_FILE.removesuffix(".json")}
    problems += [
        f"{p}.json is not in {STATUS_FILE}" for p in sorted(present - set(listed))
    ]
    for path, digest in sorted(listed.items()):
        problems += [
            f"{path}: {p}" for p in _check_file(directory / f"{path}.json", digest)
        ]
    headers = directory / build.HEADERS
    if not headers.is_file() or headers.read_text(encoding="utf-8") != _LIVE_HEADERS:
        problems.append(f"{build.HEADERS} missing or not the live site's")
    return problems


def _check_status(st: Mapping[str, Any]) -> list[str]:
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
    if not isinstance(sources, dict) or set(sources) != {"oso", "osk"}:
        return [*problems, f"{STATUS_FILE}: source {sources!r}"]
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


def _check_file(path: Path, digest: str) -> list[str]:
    try:
        data = path.read_bytes()
    except OSError:
        return ["missing"]
    if _digest(data)[:_HASH] != digest:
        return ["hash differs from status.json"]
    try:
        content = json.loads(data)
    except ValueError:
        return ["not JSON"]
    contests = content.get("contests") if isinstance(content, dict) else None
    if not isinstance(contests, dict) or not contests or set(content) != {"contests"}:
        return ["no contests"]
    return [
        f"{contest}: {p}"
        for contest, entry in sorted(contests.items())
        for p in _check_record(contest, entry)
    ]


def _check_record(contest: str, entry: object) -> list[str]:
    if not _CONTEST_ID.fullmatch(contest):
        return ["not a contest id"]
    if not isinstance(entry, dict) or not _RECORD_KEYS <= set(entry):
        return ["keys missing"]
    problems = []
    if set(entry) - _RECORD_KEYS - {"areas"}:
        problems.append(f"unknown keys {sorted(set(entry) - _RECORD_KEYS)}")
    if entry["status"] not in STATUSES:
        problems.append(f"status {entry['status']!r}")
    if entry["counted"] is not None and not _is_pair(entry["counted"]):
        problems.append(f"counted {entry['counted']!r}")
    for key in ("eligible", "voters", "valid", "seats", "filled"):
        if entry[key] is not None and not _is_count(entry[key]):
            problems.append(f"{key} {entry[key]!r}")
    if not isinstance(entry["candidates"], list) or not all(
        _is_ballot(c) for c in entry["candidates"]
    ):
        problems.append("candidates not [number, votes, flag] rows")
    if "areas" in entry and not _is_areas(entry["areas"]):
        problems.append("areas malformed")
    return problems


def _is_ballot(c: object) -> bool:
    ballot_length = 3
    return (
        isinstance(c, list)
        and len(c) == ballot_length
        and _is_count(c[0])
        and _is_count(c[1])
        and c[2] in (None, 0, 1)
    )


def _is_areas(areas: object) -> bool:
    area_length = 4
    if not isinstance(areas, dict):
        return False
    for key, value in areas.items():
        if not _AREA_KEY.fullmatch(key) or not isinstance(value, list):
            return False
        if len(value) != area_length or not isinstance(value[3], dict):
            return False
        if not all(v is None or _is_count(v) for v in value[:3]):
            return False
        if not all(n.isdigit() and _is_count(x) for n, x in value[3].items()):
            return False
    return True


# The night's JSON.


def _rows(files: Mapping[str, bytes], path: str) -> list[dict[str, Any]]:
    """Return the rows (objects) of JSON file *path*, none if absent or invalid."""
    body = files.get(path)
    if body is None:
        return []
    try:
        data = json.loads(body)
    except ValueError:
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _progress(files: Mapping[str, bytes], election: str, unit: str) -> dict[str, Any]:
    """Return the ``source`` entry of *election* from its ``tab01``."""
    rows = _rows(files, f"{election}/json/tab01.json")
    row = rows[0] if rows else {}
    # Since 2026 the time comes in Slovak and in English (C01, C02) before
    # the counts; in 2022 only once.
    first = 3 if ":" in str(row.get("C02", "")) else 2
    total, done = number(row.get(f"C{first:02d}")), number(row.get(f"C{first + 1:02d}"))
    time = source_time(row.get("C01"))
    if time is None:
        body = files.get(f"{election}/json/dateSK.json")
        try:
            dates = json.loads(body) if body else []
        except ValueError:
            dates = []
        time = source_time(dates[0]) if isinstance(dates, list) and dates else None
    counted = (done, total) if total is not None and done is not None else None
    return source(time, counted, unit)


def _started(entry: Mapping[str, Any]) -> bool:
    return bool(entry["counted"] and entry["counted"][0] > 0)


def _complete(entry: Mapping[str, Any]) -> bool:
    counted = entry["counted"]
    return bool(counted and counted[1] > 0 and counted[0] >= counted[1])


def night(files: Mapping[str, bytes], ref: Reference, log: Log = progress.note) -> Live:
    """Return the live site of the night's JSON *files* (path → content).

    Paths are relative to https://volbysr.sk/ (``oso/json/tab01.json``). A
    unit that fails to normalize is logged and left out.
    """
    oso = _progress(files, "oso", "obce")
    osk = _progress(files, "osk", "okrsky")
    live = Live("partial" if _started(oso) or _started(osk) else "none")
    live.source = {"osk": osk, "oso": oso}
    if live.phase == "none":
        return live
    if _started(osk):
        for kraj in ref.regional:
            _guard(
                log,
                f"kraj {kraj}",
                lambda k=kraj: _regional(files, ref, k, _complete(osk), live),
            )
    if _started(oso):
        okrsky = {
            str(r.get("C01")): number(r.get("C05")) for r in _rows(files, CITY_LIST)
        }
        for area in ref.municipal:
            _guard(
                log,
                area,
                lambda a=area: _municipal(
                    files, ref, a, _complete(oso), okrsky, live, log
                ),
            )
    _count_voters(live, ref)
    return live


def _count_voters(live: Live, ref: Reference) -> None:
    """Set each source's ``voters`` of *live*: counted and all registered.

    The registered voters of the units counted and of all units, as a list
    (as the status.json read back has it: :func:`write` compares them). A
    unit (a kraj's president, a municipality's mayor or else council; the
    city districts of Bratislava and Košice, not the cities again) counts
    whole once it is in, however many voted; one partly counted with those
    of its okrsky counted, of as many as at its last election (or as
    counted, if more); one not counted yet with those of its last election.
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
        if live.source[name]["counted"]:
            live.source[name] = {**live.source[name], "voters": tally(contests)}


def _guard(log: Log, what: str, run: Callable[[], None]) -> None:
    """Run *run*; log and go on if the data it reads is malformed."""
    try:
        run()
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
        log(f"{what}: skipped, unexpected data: {e!r}")


def _fully_counted(row: Mapping[str, Any]) -> bool:
    """Whether a turnout row's okrsky are all counted."""
    total = number(row.get(_OSK_TURNOUT["total"]))
    done = number(row.get(_OSK_TURNOUT["processed"]))
    return bool(total and done is not None and done >= total)


def _regional_obec_rows(
    files: Mapping[str, bytes], ref: Reference, kraj: str
) -> dict[str, dict[str, Any]]:
    """Return municipality code → turnout row (``tab02bc``) of a kraj."""
    _, councils = ref.regional[kraj]
    places = [p for p in ref.places.values() if p.kraj == kraj and p.zsk is not None]
    rows: dict[str, dict[str, Any]] = {}
    for c in councils:
        obvod = [p for p in places if p.zsk == c.obvod]
        rows |= _obec_rows(
            _rows(files, f"osk/json/tab02bc/{vobvod(kraj, c.obvod or 0)}.json"), obvod
        )
    return rows


def _regional(
    files: Mapping[str, bytes], ref: Reference, kraj: str, complete: bool, live: Live
) -> None:
    president, councils = ref.regional[kraj]
    obvody = _obvod_rows(_rows(files, f"osk/json/tab02bb/{kraj}.json"))
    # The municipalities fully counted have their own votes in ``areas``,
    # beside the obvody (the president's) known as a whole meanwhile.
    obec_rows = {
        code: row
        for code, row in _regional_obec_rows(files, ref, kraj).items()
        if complete or _fully_counted(row)
    }
    if president is not None:
        ballots = _ballots(_rows(files, f"osk/json/tab06b/{kraj}.json"))
        if ballots:
            row = _kraj_row(_rows(files, "osk/json/tab02ba.json"), ref.kraje[kraj])
            record = _osk_record(row, "predseda", ballots, 1)
            record.areas = {
                **(_obvod_areas(files, kraj, councils, obvody) or {}),
                **_obec_areas(files, "tab06d", "predseda", obec_rows),
            } or None
            live.add(president.path, president.id, record)
    for c in councils:
        code = vobvod(kraj, c.obvod or 0)
        ballots = _ballots(_rows(files, f"osk/json/tab09c/{code}.json"))
        if ballots:
            record = _osk_record(obvody.get(c.obvod or 0), "zsk", ballots, c.seats)
            mine = {k: r for k, r in obec_rows.items() if ref.places[k].zsk == c.obvod}
            record.areas = _obec_areas(files, "tab09d", "zsk", mine) or None
            live.add(c.path, c.id, record)


def _osk_record(
    row: Mapping[str, Any] | None, kind: str, ballots: list[Ballot], seats: int | None
) -> Record:
    row = row or {}
    total = number(row.get(_OSK_TURNOUT["total"]))
    done = number(row.get(_OSK_TURNOUT["processed"]))
    elected = sum(1 for b in ballots if b[2] == 1)
    return Record(
        "partial",
        (done, total) if done is not None and total is not None else None,
        number(row.get(_OSK_TURNOUT["eligible"])),
        number(row.get(_OSK_TURNOUT["voters"])),
        number(row.get(_OSK_TURNOUT[kind])),
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
) -> dict[str, Area] | None:
    """Return the regional president's votes per obvod, as ``areas``."""
    areas = {}
    for c in councils:
        n = c.obvod or 0
        ballots = _ballots(_rows(files, f"osk/json/tab06c/{vobvod(kraj, n)}.json"))
        if ballots:
            areas[f"obvod:{n}"] = _turnout_area(obvody.get(n, {}), "predseda", ballots)
    return areas or None


def _obec_areas(
    files: Mapping[str, bytes],
    table: str,
    kind: str,
    rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Area]:
    """Return the votes per municipality of *rows* (code → turnout row)."""
    areas = {}
    for code, row in rows.items():
        ballots = _ballots(_rows(files, f"osk/json/{table}/{code}.json"))
        if ballots:
            areas[code] = _turnout_area(row, kind, ballots)
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
    """Return the candidates of *rows*: ballot number, votes, elected (1).

    Withdrawn candidates (``X``) and rows without a number are left out.
    """
    number_column, votes_column, label_column = columns
    out = []
    for r in rows:
        n, votes = number(r.get(number_column)), number(r.get(votes_column))
        label = str(r.get(label_column) or "").strip().casefold()
        if n is None or votes is None or label == _WITHDRAWN:
            continue
        out.append((n, votes, 1 if label.startswith(_ELECTED) else None))
    return out


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
    code = OBEC_OF_CITY.get(contest.area, contest.area)
    record = Record(
        "winner",
        eligible=number(g.get(_GRAPH["eligible"])),
        voters=number(g.get(_GRAPH["voters"])),
        valid=number(g.get(_GRAPH["valid_mayor"])),
        seats=1,
    )
    full = _ballots(_rows(files, f"oso/json/tab05/{code}.json"))
    elected = sum(1 for b in full if b[2] == 1)
    if full and (complete or contest.area in candidates.CITY_CODES):
        record.status = "final" if complete else "partial"
        record.candidates = full
        record.filled = elected if complete else (elected or None)
        if not complete:
            share = decimal(g.get(_GRAPH["processed"]))
            if okrsky and share is not None:
                record.counted = (min(okrsky, round(share / _FULL * okrsky)), okrsky)
        return record
    if contest.area in candidates.CITY_CODES:
        return None
    return _night_mayor(ref, contest, g, record, log)


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
    when every seat is filled. Bratislava's and Košice's councils are known
    only when the city is fully counted.
    """
    if code in CITY_OBCE and (decimal(g.get(_GRAPH["processed"])) or 0) < _FULL:
        return
    single = len(contests) == 1
    seats_all, filled_all = (
        number(g.get(_GRAPH["seats"])),
        number(g.get(_GRAPH["filled"])),
    )
    finals = _council_ballots(files, code) if complete else {}
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


def _settled(files: Mapping[str, bytes], code: str) -> bool:
    """Whether a municipality's summary is final for the night: fully counted."""
    rows = _rows(files, f"oso/json/graph01/{code}.json")
    if not rows or not _approved(rows[0]):
        return False
    return (decimal(rows[0].get(_GRAPH["processed"])) or 0) >= _FULL


def unit_paths(files: Mapping[str, bytes], ref: Reference) -> list[str]:
    """Return the per-unit files to fetch, given the progress in *files*."""
    oso = _progress(files, "oso", "obce")
    osk = _progress(files, "osk", "okrsky")
    paths = []
    if _started(osk):
        paths += _regional_paths(files, ref, _complete(osk))
    if _started(oso):
        paths += _municipal_paths(files, ref, _complete(oso))
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
        counted |= {code for code, row in rows.items() if _fully_counted(row)}
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
        if complete or not _settled(files, code):
            paths.append(f"oso/json/graph01/{code}.json")
        if complete or area in candidates.CITY_CODES:
            paths.append(f"oso/json/tab05/{code}.json")
        if complete and councils:
            paths += [f"oso/json/tab06e1/{code}.json", f"oso/json/tab06e2/{code}.json"]
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
        if code == _HTTP_NOT_MODIFIED:
            return "same"
        if code == _HTTP_NOT_FOUND:
            with self._lock:
                return "changed" if self.copies.pop(path, None) else "missing"
        if code != _HTTP_OK:
            return self._fail(f"{path}: HTTP {code}")
        try:
            json.loads(body)
        except ValueError:
            return self._fail(f"{path}: not JSON, previous copy kept")
        target = self.archive / stamp / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        with self._lock:
            self.copies[path] = _Copy(body, *validators)
        return "same" if previous and previous.body == body else "changed"

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
        """Poll with *client* into live directory *directory*."""
        self.client = client
        self.ref = ref
        self.directory = directory
        self.log = log
        self.pending = True
        """Whether the per-unit files are due even without a progress change:
        on the first cycle, and after one of them failed."""

    def cycle(self) -> dict[str, Any] | None:
        """Fetch what changed and rewrite the live site; return its new status.

        None when nothing changed.
        """
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        changed = self.client.get_all([*PROGRESS_FILES, CITY_LIST], stamp)
        self._report("progress files", changed)
        if not changed["changed"] and not self.pending:
            return None
        units = self.client.get_all(unit_paths(self.client.files(), self.ref), stamp)
        self.pending = units["failed"] > 0
        self._report("units", units)
        live = night(self.client.files(), self.ref, self.log)
        new = write(self.directory, live)
        self.log(
            f"{live.phase}: {sum(map(len, live.files.values()))} contests; "
            + (f"version {new['version']}" if new else "live site unchanged")
        )
        return new

    def _report(self, what: str, outcomes: Counter[str]) -> None:
        for message in self.client.messages:
            self.log(message)
        self.client.messages.clear()
        counts = ", ".join(f"{n} {k}" for k, n in sorted(outcomes.items()))
        self.log(f"{what}: {counts or 'nothing fetched'}")


# The definitive CSV tables.

_ROLE_TITLES = (
    # Role, words of the table's title in tab_info (casefolded), in this
    # order: the vote tables also say "hlas".
    ("mayor", ("hlas", "starost")),
    ("president", ("hlas", "predsed")),
    ("council", ("hlas", "poslanc")),
    ("seats", ("volených a zvolených",)),
    ("turnout", ("účasť",)),
    ("units", ("územné členenie",)),
)
_ROLE_COLUMNS = {
    "mayor": {"OBEC", "OKRSOK", "PC_HL", "P_HL", "KANDIDAT"},
    "president": {"OBEC", "OKRSOK", "PC_HL", "P_HL", "KANDIDAT"},
    "council": {"OBEC", "OKRSOK", "PC_HL", "P_HL", "KANDIDAT"},
    "seats": {"P_POS_VOL", "P_POS_ZVOL"},
    "turnout": {"OBEC", "OKRSOK", "P_ZAP", "P_ZUC"},
    "units": {"OBEC", "P_ALL_OKRSOK"},
}
_ROLES_OF = {
    "oso": ("units", "seats", "turnout", "mayor", "council"),
    "osk": ("units", "seats", "turnout", "president", "council"),
}
_EXTRA_COLUMNS = {
    "oso": {
        "seats": {"OBEC", "VOOBEC"},
        "council": {"VOOBEC"},
        "turnout": {"P_HL_STA", "P_HL_ZAS", "VOOBEC"},
    },
    "osk": {
        "seats": {"VOBVOD"},
        "units": {"KRAJ", "VOBVOD"},
        "turnout": {"P_HL_PRE", "P_HL_POS"},
    },
}
_NO_ELECTION = "0"
_INFO_FIELDS = 3
"""Fields of a table's line in tab_info: id, title, file."""


@dataclass
class Tables:
    """The CSV tables of a definitive results package, by table id."""

    name: str
    time: dt.datetime
    raw: dict[str, bytes]
    """Table id (``tab05f``) → content."""

    def text(self, table: str) -> str:
        """Return a table's text: UTF-8, but tab_info has been windows-1250."""
        data = self.raw[table]
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("cp1250")

    def rows(self, table: str) -> list[dict[str, str]]:
        """Return the rows of a table (``|``-separated, with a header)."""
        return list(csv.DictReader(io.StringIO(self.text(table)), delimiter="|"))

    def columns(self, table: str) -> set[str]:
        """Return the column names of a table."""
        return set(self.text(table).partition("\n")[0].strip().split("|"))

    def roles(self) -> tuple[str, dict[str, str]]:
        """Return the election (``oso``, ``osk``) and role → table id."""
        titles = self._titles()
        found: dict[str, str] = {}
        for table, title in sorted(titles.items()):
            folded = title.casefold()
            role = next(
                (r for r, words in _ROLE_TITLES if all(w in folded for w in words)),
                None,
            )
            if role and table in self.raw and role not in found:
                found[role] = table
        election = "oso" if "mayor" in found else "osk"
        missing = [r for r in _ROLES_OF[election] if r not in found]
        if missing:
            raise ResultsError(f"{self.name}: no table of {', '.join(missing)}")
        for role in _ROLES_OF[election]:
            needed = _ROLE_COLUMNS[role] | _EXTRA_COLUMNS[election].get(role, set())
            lacking = needed - self.columns(found[role])
            if lacking:
                raise ResultsError(
                    f"{self.name}: {found[role]} ({role}) lacks {sorted(lacking)}"
                )
        return election, found

    def _titles(self) -> dict[str, str]:
        """Return table id → title, from the table list ``tab_info``."""
        if "tab_info" not in self.raw:
            raise ResultsError(f"{self.name}: no tab_info (list of tables)")
        titles = {}
        for line in self.text("tab_info").splitlines():
            parts = line.split(";")
            if len(parts) >= _INFO_FIELDS:
                m = _TABLE_ID.search(parts[2].strip())
                if m:
                    titles[m.group(1)] = parts[1]
        return titles


def open_tables(path: Path) -> Tables:
    """Return the CSV tables of a zip or of a directory of the unzipped files."""
    raw: dict[str, bytes] = {}
    if path.is_dir():
        files = sorted(path.rglob("*.csv"))
        for f in files:
            m = _TABLE_ID.search(f.name)
            if m:
                raw[m.group(1)] = f.read_bytes()
        stamp = max((f.stat().st_mtime for f in files), default=0.0)
        return Tables(path.name, dt.datetime.fromtimestamp(stamp, TIMEZONE), raw)
    try:
        with zipfile.ZipFile(path) as z:
            latest = (1980, 1, 1, 0, 0, 0)
            for info in z.infolist():
                m = _TABLE_ID.search(info.filename)
                if m:
                    raw[m.group(1)] = z.read(info)
                    latest = max(latest, info.date_time)
    except (OSError, zipfile.BadZipFile) as e:
        raise ResultsError(f"{path}: {e}") from e
    return Tables(path.name, dt.datetime(*latest, tzinfo=TIMEZONE), raw)


def read_final(
    paths: Sequence[Path], okres_of: Mapping[str, str] | None = None
) -> tuple[Live, list[str]]:
    """Return the definitive results of the packages *paths*, and their elections.

    *okres_of* maps municipalities to their okres where the candidate lists
    know them; for others the tables' own okres codes are used.
    """
    live = Live("final")
    elections = []
    for path in paths:
        tables = open_tables(path)
        election, roles = tables.roles()
        with progress.stage(f"reading {tables.name} ({election})"):
            if election == "oso":
                _final_municipal(tables, roles, okres_of or {}, live)
            else:
                _final_regional(tables, roles, live)
        elections.append(election)
    return live, elections


def _group(rows: Iterable[_T], key: Callable[[_T], Any]) -> dict[Any, list[_T]]:
    out: dict[Any, list[_T]] = defaultdict(list)
    for r in rows:
        k = key(r)
        if k is not None:
            out[k].append(r)
    return out


def _counted(rows: Iterable[Mapping[str, str]]) -> list[Mapping[str, str]]:
    """Return vote rows without those of withdrawn candidates."""
    return [r for r in rows if r["KANDIDAT"].strip().casefold() != _WITHDRAWN]


def _tally(
    turnout: Sequence[Mapping[str, str]], votes: Iterable[Mapping[str, str]], valid: str
) -> Record:
    """Return the final record of a contest from its okrsky's rows.

    *turnout* and *votes* are the contest's rows of the turnout and vote
    tables, *valid* the turnout column of its valid ballots.
    """
    totals: Counter[int] = Counter()
    flags: dict[int, int | None] = {}
    for r in _counted(votes):
        n = int(r["PC_HL"])
        totals[n] += int(r["P_HL"])
        flag = r["KANDIDAT"].strip()
        flags[n] = int(flag) if flag else flags.get(n)
    return Record(
        "final",
        (len(turnout), len(turnout)),
        sum(int(r["P_ZAP"]) for r in turnout),
        sum(int(r["P_ZUC"]) for r in turnout),
        sum(int(r[valid]) for r in turnout),
        candidates=[(n, v, flags.get(n)) for n, v in sorted(totals.items())],
    )


def _areas(
    pairs: Iterable[tuple[str | None, Mapping[str, str], Iterable[Mapping[str, str]]]],
    valid: str,
) -> dict[str, Area]:
    """Return ``areas`` from (municipality, turnout row, vote rows) per okrsok."""
    sums: dict[str, tuple[int, int, int, dict[int, int]]] = {}
    for area, t, votes in pairs:
        if area is None:
            continue
        e, v, va, prior = sums.get(area, (0, 0, 0, {}))
        mine: dict[int, int] = {}
        for r in _counted(votes):
            mine[int(r["PC_HL"])] = mine.get(int(r["PC_HL"]), 0) + int(r["P_HL"])
        sums[area] = (
            e + int(t["P_ZAP"]),
            v + int(t["P_ZUC"]),
            va + int(t[valid]),
            _add(prior, mine),
        )
    return dict(sums)


def _obec_totals(
    turnout: Iterable[Mapping[str, str]],
    votes: Iterable[Mapping[str, str]],
    valid: str,
) -> dict[str, Area]:
    """Return a regional contest's ``areas`` per municipality."""
    by_obec = _group(votes, lambda r: r["OBEC"])
    seen: set[str] = set()
    pairs = []
    for t in turnout:
        # The municipality's votes go with its first okrsok, its turnout with
        # each of them.
        pairs.append((t["OBEC"], t, [] if t["OBEC"] in seen else by_obec[t["OBEC"]]))
        seen.add(t["OBEC"])
    return _areas(pairs, valid)


Okrsok = tuple[str, str, int]
"""A city okrsok in the vote tables: council obvod, number, copy."""


def _copies(votes: Iterable[Mapping[str, str]]) -> Iterator[tuple[Okrsok, Mapping]]:
    """Yield each vote row with its okrsok.

    Košice numbers its okrsky per district, and the city's tables do not
    name the district: okrsky of one council obvod can share a number. The
    table lists their rows by ballot number, the okrsky's rows of a
    candidate in a row, so the n-th row of a candidate with a number is the
    n-th okrsok, or copy, of that number.
    """
    seen: Counter[tuple[str, str, str]] = Counter()
    for r in votes:
        key = (r.get("VOOBEC", ""), r["OKRSOK"], r["PC_HL"])
        yield (key[0], key[1], seen[key]), r
        seen[key] += 1


def city_okrsky(
    turnout: Sequence[Mapping[str, str]], mayor: Iterable[Mapping[str, str]], obec: str
) -> dict[Okrsok, int]:
    """Return each okrsok of a city's vote tables → its row in *turnout*.

    Copies of an okrsok number (:func:`_copies`) are told apart by the
    mayor's votes, which add up to the okrsok's valid ballots for mayor;
    copies with the same sum go by order.
    """
    rows: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, r in enumerate(turnout):
        if r["OBEC"] == obec:
            rows[(r.get("VOOBEC", ""), r["OKRSOK"])].append(i)
    sums: Counter[Okrsok] = Counter()
    for okrsok, r in _copies(v for v in mayor if v["OBEC"] == obec):
        sums[okrsok] += int(r["P_HL"])
    out = {}
    for (obvod, number_), indices in rows.items():
        free = list(indices)
        for copy in range(len(indices)):
            total = sums[(obvod, number_, copy)]
            i = next((i for i in free if int(turnout[i]["P_HL_STA"]) == total), free[0])
            free.remove(i)
            out[(obvod, number_, copy)] = i
    return out


def _city_areas(
    turnout: Sequence[Mapping[str, str]],
    indices: Iterable[int],
    votes: Iterable[Mapping[str, str]],
    valid: str,
    where: tuple[Mapping[Okrsok, int], Mapping[int, str]],
) -> dict[str, Area]:
    """Return a city-wide contest's ``areas`` per district.

    *indices* are the contest's rows in *turnout*; *where* is the city's
    :func:`city_okrsky` and :func:`city_districts`.
    """
    row_of, district_of = where
    by_row: dict[int, list[Mapping[str, str]]] = defaultdict(list)
    for okrsok, r in _copies(votes):
        i = row_of.get(okrsok)
        if i is not None:
            by_row[i].append(r)
    return _areas(((district_of.get(i), turnout[i], by_row[i]) for i in indices), valid)


def city_districts(
    turnout: Sequence[Mapping[str, str]], units: Mapping[str, Mapping[str, str]]
) -> dict[int, str]:
    """Return the district of each okrsok row of Bratislava's and Košice's.

    Rows are given by their index in *turnout*. The city-wide contests are
    tabulated per okrsok of the city without its district. Each okrsok
    votes for its district at the same time, so the district's row of the
    same okrsok has the same voters on the roll and taking part: that pair
    finds it. An okrsok whose pair is not unique goes to the district most
    of its council obvod's okrsky are in.
    """
    city_of = {o: city.code for city in candidates.CITIES for o in city.district_okresy}
    districts: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for r in turnout:
        city = city_of.get(units.get(r["OBEC"], {}).get("OKRES", ""))
        if city:
            districts[(city, r["P_ZAP"], r["P_ZUC"])].append(r["OBEC"])
    out: dict[int, str] = {}
    by_obvod: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    unsure = []
    for i, r in enumerate(turnout):
        city = CITY_OBCE.get(r["OBEC"])
        if city is None:
            continue
        found = districts.get((city, r["P_ZAP"], r["P_ZUC"]), [])
        if len(found) == 1:
            out[i] = found[0]
            by_obvod[(r["OBEC"], r.get("VOOBEC", ""))][found[0]] += 1
        else:
            unsure.append((i, r))
    for i, r in unsure:
        likely = by_obvod[(r["OBEC"], r.get("VOOBEC", ""))].most_common(1)
        if likely:
            out[i] = likely[0][0]
    return out


def _final_municipal(
    t: Tables, roles: Mapping[str, str], okres_of: Mapping[str, str], live: Live
) -> None:
    units = {r["OBEC"]: r for r in t.rows(roles["units"])}
    turnout = t.rows(roles["turnout"])
    seats = {(r["OBEC"], r["VOOBEC"]): r for r in t.rows(roles["seats"])}
    mayor = _group(t.rows(roles["mayor"]), lambda r: r["OBEC"])
    district_of = city_districts(turnout, units)
    where = {
        obec: (city_okrsky(turnout, mayor.get(obec, []), obec), district_of)
        for obec in CITY_OBCE
    }
    okres = {obec: r["OKRES"] for obec, r in units.items()} | dict(okres_of)

    def add(
        kind: str, obec: str, obvod: str, okrsky: Sequence[int], rows: list[dict]
    ) -> Record:
        area = CITY_OBCE.get(obec, obec)
        valid = "P_HL_STA" if kind == "starosta" else "P_HL_ZAS"
        record = _tally([turnout[i] for i in okrsky], rows, valid)
        if obec in where:
            record.areas = _city_areas(turnout, okrsky, rows, valid, where[obec])
        contest = (
            f"starosta:{area}" if kind == "starosta" else f"oz:{area}/{int(obvod)}"
        )
        live.add(live_path({"kind": kind, "area": area}, okres), contest, record)
        return record

    indices = range(len(turnout))
    by_obec = _group(indices, lambda i: turnout[i]["OBEC"])
    for obec, rows in mayor.items():
        record = add("starosta", obec, "", by_obec.get(obec, []), rows)
        record.seats = 1
        record.filled = sum(1 for c in record.candidates if c[2] == 1)
    by_obvod = _group(indices, lambda i: (turnout[i]["OBEC"], turnout[i]["VOOBEC"]))
    council = _group(t.rows(roles["council"]), lambda r: (r["OBEC"], r["VOOBEC"]))
    for (obec, obvod), rows in council.items():
        record = add("oz", obec, obvod, by_obvod.get((obec, obvod), []), rows)
        row = seats.get((obec, obvod), {})
        record.seats = number(row.get("P_POS_VOL"))
        record.filled = number(row.get("P_POS_ZVOL"))
    held = sum(1 for r in units.values() if r.get("VOLBY_TYP") != _NO_ELECTION)
    live.source["oso"] = source(t.time.isoformat(), (held, held), "obce")


def _final_regional(t: Tables, roles: Mapping[str, str], live: Live) -> None:
    units = {r["OBEC"]: r for r in t.rows(roles["units"])}
    turnout = t.rows(roles["turnout"])
    seats = {r["VOBVOD"]: r for r in t.rows(roles["seats"])}

    def unit(column: str) -> Callable[[Mapping[str, str]], str | None]:
        return lambda r: units.get(r["OBEC"], {}).get(column)

    by_kraj = _group(turnout, unit("KRAJ"))
    for kraj, rows in _group(t.rows(roles["president"]), unit("KRAJ")).items():
        record = _tally(by_kraj.get(kraj, []), rows, "P_HL_PRE")
        record.areas = _obec_totals(by_kraj.get(kraj, []), rows, "P_HL_PRE")
        record.seats = 1
        record.filled = sum(1 for c in record.candidates if c[2] == 1)
        live.add(_kraj_path(kraj), f"predseda:{kraj}", record)
    by_obvod = _group(turnout, unit("VOBVOD"))
    for code, rows in _group(t.rows(roles["council"]), unit("VOBVOD")).items():
        record = _tally(by_obvod.get(code, []), rows, "P_HL_POS")
        record.areas = _obec_totals(by_obvod.get(code, []), rows, "P_HL_POS")
        row = seats.get(code, {})
        record.seats = number(row.get("P_POS_VOL"))
        record.filled = number(row.get("P_POS_ZVOL"))
        # The obvod code is the kraj code followed by the obvod's number.
        live.add(_kraj_path(code[:-2]), f"zsk:{code[:-2]}/{int(code[-2:])}", record)
    total = sum(int(r["P_ALL_OKRSOK"]) for r in units.values())
    live.source["osk"] = source(t.time.isoformat(), (len(turnout), total), "okrsky")


def _kraj_path(kraj: str) -> str:
    return live_path({"kind": "predseda", "area": kraj}, {})


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
_COUNCIL_SEATS = (3, 9)


@dataclass(frozen=True)
class _Unit:
    code: str
    eligible: int
    voters: int
    valid: int
    okrsky: int
    rank: float
    """The unit is counted once the stage's share passes it."""


def _rng(seed: int, *key: object) -> random.Random:
    # A string seed is hashed with SHA-512: the same numbers in every run.
    return random.Random(":".join(map(str, (seed, *key))))


def _add(a: Mapping[int, int], b: Mapping[int, int]) -> dict[int, int]:
    return {n: a.get(n, 0) + b.get(n, 0) for n in a.keys() | b.keys()}


class _Fake:
    """The figures behind :func:`fake`, the same at every stage."""

    def __init__(self, ref: Reference, seed: int) -> None:
        self.ref = ref
        self.seed = seed
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
                self.units[code] = _Unit(
                    u.code,
                    u.eligible,
                    u.voters,
                    u.valid,
                    u.okrsky,
                    u.rank * _LANDSLIDE_RANK,
                )

    def _unit(self, key: str, past: tuple[int, int] | None, code: str) -> _Unit:
        r = _rng(self.seed, "unit", key)
        e0, v0 = past or _DEFAULT_PAST
        eligible = max(1, round(e0 * r.uniform(0.97, 1.01)))
        turnout = v0 / max(e0, 1) * r.uniform(0.9, 1.15)
        voters = min(eligible, round(eligible * turnout))
        valid = round(voters * r.uniform(0.95, 0.99))
        okrsky = max(1, round(eligible / _VOTERS_PER_OKRSOK))
        return _Unit(code, eligible, voters, valid, okrsky, r.random())

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
        r = _rng(self.seed, "weights", c.id)
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

    def _votes(self, c: Contest, unit: _Unit) -> dict[int, int]:
        """Return the votes of each candidate of *c* in *unit*."""
        weights = self._weights(c)
        r = _rng(self.seed, "votes", c.id, unit.code)
        if self.landslide is not None and c.id == self.landslide.id:
            return {
                n: round(unit.valid * w * r.uniform(0.9, 1.1))
                for n, w in weights.items()
            }
        if c.kind in ("oz", "zsk"):
            # A council voter marks several candidates: each candidate is on
            # a share of the ballots of its own.
            top = max(weights.values())
            return {
                n: round(unit.valid * _COUNCIL_REACH * w / top * r.uniform(0.8, 1.2))
                for n, w in weights.items()
            }
        noisy = {n: w * r.uniform(0.85, 1.15) for n, w in weights.items()}
        total = sum(noisy.values())
        return {n: round(unit.valid * w / total) for n, w in noisy.items()}

    def _flag(self, c: Contest, record: Record, elected: int) -> None:
        """Flag the *elected* candidates with the most votes, the rest lost."""
        order = sorted(record.candidates, key=lambda b: (-b[1], b[0]))
        loser = 0 if c.kind in ("oz", "zsk") else None
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
            votes = self._votes(c, u)
            totals = _add(totals, votes)
            keys = [u.code]
            if night and c.kind == "predseda":
                keys.append(f"obvod:{self.ref.places[u.code].zsk}")
            for key in keys:
                e, v, va, prior = areas.get(key, (0, 0, 0, {}))
                areas[key] = (
                    (e or 0) + u.eligible,
                    (v or 0) + u.voters,
                    (va or 0) + u.valid,
                    _add(prior, votes),
                )
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
            self._flag(c, record, record.seats or 1)
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
        self._flag(c, record, record.seats or 1)
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
        r = _rng(self.seed, "seats", c.id)
        seats = c.seats or (1 if c.kind == "starosta" else r.randint(*_COUNCIL_SEATS))
        record = Record("winner", None, unit.eligible, unit.voters, unit.valid, seats)
        record.candidates = [(n, v, None) for n, v in self._votes(c, unit).items()]
        unfilled = c.kind == "oz" and r.random() < _UNFILLED
        self._flag(c, record, seats - unfilled)
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
        return share >= 1 or _rng(self.seed, "report", area).random() < share

    def sources(self, s: Stage) -> dict[str, dict[str, Any]]:
        """Return ``source`` of ``status.json`` at stage *s*."""
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
        return {
            "osk": source(
                s.time,
                (sum(u.okrsky for u in counted), sum(u.okrsky for u in units)),
                "okrsky",
            ),
            "oso": source(s.time, (len(areas), len(self.ref.municipal)), "obce"),
        }

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


def fake(ref: Reference, stage: str, seed: int = 0) -> Live:
    """Return dummy results of the counting at *stage* (:data:`STAGES`).

    Turnout follows each area's past election, votes a stable random
    distribution. The counted parts only grow from one stage to the next
    (same *seed*). The first kraj's president race stays too close to call
    to the end; the regional obvod with the fewest voters is fully counted
    by ``mid`` with a landslide that decides it.
    """
    s = STAGES[stage]
    model = _Fake(ref, seed)
    final = stage == "final"
    live = Live("none" if stage == "none" else ("final" if final else "partial"))
    live.source = model.sources(s)
    if live.phase == "none":
        return live
    for c, record in (*model.regional(s, final), *model.municipalities(s, final)):
        live.add(c.path, c.id, record)
    _count_voters(live, ref)
    return live


# Serving and deploying.


def deploy_command(directory: Path, project: str) -> list[str]:
    """Return the command that uploads *directory* to Pages project *project*."""
    return [
        "npx",
        "--yes",
        "wrangler",
        "pages",
        "deploy",
        str(directory),
        f"--project-name={project}",
        "--branch=main",
    ]


def deploy(directory: Path, project: str) -> int:
    """Upload *directory* to Pages project *project*; return Wrangler's exit code."""
    write_static(directory)
    return subprocess.run(deploy_command(directory, project), check=False).returncode


def describe(directory: Path) -> list[str]:
    """Return a summary of the live site in *directory*: phase, version, counts."""
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
    lines.append(
        f"  {len(st['files'])} area files, "
        + (", ".join(f"{n} {k}" for k, n in sorted(by_status.items())) or "no contests")
    )
    return lines
