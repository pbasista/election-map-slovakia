"""Verify the site in ``dist/`` before it is deployed.

Every check runs and lists all its problems, so one run shows everything
that is wrong. The site is in parts (``build``): the app in ``app/``, per
election a map bundle in ``map/<slug>/`` and a data bundle in
``data/<slug>/``, per OpenStreetMap extract a base map in
``base/<extract>/``, ``sources/`` and ``results/``. Problems name the files
by their path in ``dist/``. The app requests its files as ``serve`` serves
the parts (``build.mounts``): a path of the app's ``/x`` is ``app/x`` (or,
for the cached copies, ``sources/x``), and an election's ``/x`` is
``map/<slug>/x`` below ``geo/`` and ``addr/``, ``base/<extract>/y`` for
``/base/y``, else ``data/<slug>/x`` (:func:`election_path`). Built with
``--deployed``, ``dist/`` holds the app and each bundle's and base map's
manifest only: the checks of their content are then those they passed
where they were built, and the app is checked against the files each
manifest lists.

=========  ==============================================================
files      at most ``file_budget`` files (``config/site.toml``) in each
           part, which a Pages project of its own serves
sizes      no file larger than ``max_file_bytes``
json       every ``.json`` file parses
headers    each part's ``_headers`` parses and stays within the
           Cloudflare Pages limits (100 rules, 2,000 characters per line);
           each data part has its ``404.html`` and ``manifest.json``, and
           a bundle's or base map's manifest lists exactly its files
links      every file the frontend can request exists: the files HTML
           pages, scripts and app.css refer to (the code below
           ``assets/<v>/``, the libraries below ``assets/vendor/<vv>/``,
           which the build points the modules' imports at; see ``build``),
           the literal paths in the
           scripts (those of an election's files in every election's
           bundle, whose address the app puts before them, but candidate
           area files, which go by the contests), the 404 page,
           the shells of every language and election and the UI strings
           of every language; of every election its indexes, About data,
           occupations and coarse geometry, every geo shard of every
           okres, every okrsky file the geo index lists and every level of
           the countries around Slovakia, and for every obec in the geo
           shards its address file and, of the regular municipal and
           regional elections, its candidate files, of the others the
           area file of every contest; every address
           file, name shard and party logo the indexes list, and every
           base map file of the base index; the cached copy of every page
           a research finding cites and the stylesheet they link
contests   every contest of an election's ``candidates.json`` is in
           exactly one of its candidate area files, the one the frontend
           looks in (``contests.area_name``, ``areaName`` in
           ``web/js/kinds.js``)
councils   every council contest of a by-election in an obec whose
           council its term (the regular election before it) elected in
           several obvody has the obec's addresses placed in those obvody
           by a rule set (``by_address`` of the data index); without, the
           map and the address lookup take it for the whole obec's
origins    no HTML, JS or CSS of the app refers to another origin than
           the data parts' its shells name (km-config ``map``, ``data``,
           ``base``, ``results``, ``live``, ``sources``), except as the
           target of a link (``href``, not on ``<link>``), as an XML
           namespace or in a comment; every HTML page of the app has a
           Content-Security-Policy ``<meta>`` before anything that loads,
           whose connect-src is, in a shell, ``'self'`` and the origins of
           the bundles, the base maps, the results and, where an election
           reads them, the live results, and ``'self'`` alone in the
           picker and the 404 page; the CSP of the app's ``_headers`` has
           no default-src or connect-src, which would narrow them
results    every directory of ``results/`` (the final results) and of
           ``live/`` (the live results) is an election day's and holds
           results that keep the contract of docs/results.md
           (``results.check``) for the contests of that election's
           ``candidates.json``: its ``status.json`` well-formed with the
           sources of those contests, every file it lists there with that
           hash, and no other; the votes of every unit counted of a
           single-choice contest are its valid ballots, a council's within
           them and its seats, a party list's within its preferences; the
           units summed are their parts' sums, by where the election's
           ``candidates.json`` places its obce
addresses  every address point lies in the bounding box of its obec at the
           finest level of detail, widened by ``addresses.MAX_OUTSIDE``;
           in an obec whose council obvod goes by address every address
           has one of its obvody, and the shards cut exactly those obce,
           into exactly their obvody; every address has its okrsok
           exactly in the obce whose okrsky the map draws
geometry   at each level of detail the lines drawn are the borders of its
           obce (or coarse cells), each exactly once, and every kraj,
           okres, obvod and the country merged from them is bounded by
           exactly the lines drawn as its border, and the council obvody
           within an obec by exactly the lines flagged so (``geo.verify``);
           the okrsky the index lists, and no other, tile their obec's
           shard features at each level within ``geo.MAX_OKRSKY_OFFSET``,
           and the lines drawn are exactly the borders between two okrsky of
           an obec, those between council obvody flagged so
           (``geo.verify_okrsky``); the
           countries around Slovakia have the lines drawn between them,
           each once, leave no gap at Slovakia's border at any level
           (``geo.verify_neighbours``) and have names in every language
base       each base map has the shards' levels of detail and okresy of
           every election on its extract (its ``index.json`` against their
           ``geo/index.json``), holds no file its index does not let the app
           request (``links`` reports those missing), and each file has
           only the line classes of its level and water areas whose rings
           are exactly the arcs coded as such, each buildings file its
           scale, as many vertices as its rings count, rings of three or
           more with an area and an outer ring first (``basemap.verify``)
i18n       every UI string is translated into every language (none taken
           from a fallback language); notes the share of each bundle's
           occupations translated per language
=========  ==============================================================

The vendored Leaflet stylesheet is not followed for ``links``: it styles
controls the app does not use (layers control, default marker), whose
images are not vendored.
"""

from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import html
import itertools
import json
import math
import os
import pickle
import posixpath
import re
import urllib.parse
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

from election_map_slovakia import (
    addresses,
    basemap,
    build,
    bundle,
    cache,
    config,
    contests,
    geo,
    obvody,
    output,
    parallel,
    progress,
    results,
    stamp,
    translate,
)
from election_map_slovakia.candidates import NEW
from election_map_slovakia.output import format_size

APP = f"{build.APP_PART}/"
SOURCES = f"{bundle.SOURCES_PART}/"
RESULTS = f"{bundle.RESULTS_PART}/"
LIVE = f"{bundle.LIVE_PART}/"
MAP = f"{bundle.MAP_PART}/"
DATA = f"{bundle.DATA_PART}/"
BASE = f"{bundle.BASE_PART}/"
BUNDLES = (MAP, DATA, BASE)
"""The parts deployed once per key, which the app names by deployment."""
MEMO_FILE = "verified.pickle"
"""What :func:`run` verified last, which the next run reuses; the CLI keeps
it in ``data/build/shared/check/``."""

# https://developers.cloudflare.com/pages/platform/limits/
MAX_HEADER_RULES = 100
MAX_HEADER_LINE = 2000
SHOWN_PROBLEMS = 20

_CODE = (".html", ".js", ".mjs", ".css")
_LEAFLET_CSS = re.compile(
    rf"{build.APP_PART}/{build.ASSETS_DIR}/{build.VENDOR_DIR}/[^/]+/leaflet/leaflet\.css"
)
_HTML_REF = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"']*)["']""")
# Relative imports, and the absolute ones of the libraries the build writes.
_JS_IMPORT = re.compile(r"""\b(?:from|import)\s*\(?\s*["']((?:\.{1,2})?/[^"']+)["']""")
_JS_PATH = re.compile(r"""(["'`])(/[\w./-]*\.\w+)\1""")
_CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""")
_URL = re.compile(
    r"(?:\b[a-zA-Z][a-zA-Z0-9+.-]*:)?//[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+[^\s\"'`<>()\\]*"
)
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_HREF_BEFORE = re.compile(r"""\bhref\s*=\s*["']?$""")
_TAG = re.compile(r"<\s*([^\s/>]+)")
# Namespace names identify vocabularies; nothing fetches them.
_NAMESPACES = frozenset(
    {
        "http://www.w3.org/2000/svg",
        "http://www.w3.org/1999/xhtml",
        "http://www.w3.org/1999/xlink",
        "http://www.w3.org/2000/xmlns/",
        "http://www.w3.org/XML/1998/namespace",
        "http://www.w3.org/1998/Math/MathML",
    }
)
# Tags whose href loads or redirects resources rather than linking.
_RESOURCE_TAGS = frozenset({"link", "base"})
# Below an election's bundle.
_AREA_DIRS = (
    "data/okres/",
    "data/city/",
    "data/kraj/",
    "data/country.json",
    "data/list/",
)
_METRES_PER_DEGREE = 111_320
# Address points and geometry are both rounded to 1e-5 degree.
_ROUNDING = 2e-5


@dataclass
class Check:
    """The outcome of one check: how many items it looked at, and problems."""

    name: str
    checked: int = 0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """What the summary shows besides problems."""


def _load(dist: Path, rel: str) -> Any:
    try:
        return orjson.loads((dist / rel).read_bytes())
    except (OSError, ValueError):
        return None


def part_of(rel: str) -> str:
    """Return the part of ``dist/`` path *rel*: ``app``, ``data/<slug>``, ..."""
    first, _, rest = rel.partition("/")
    if first in (bundle.MAP_PART, bundle.DATA_PART, bundle.BASE_PART):
        return f"{first}/{rest.partition('/')[0]}"
    return first


def election_path(slug: str, osm: str, rel: str) -> str:
    """Return the ``dist/`` path of election *slug*'s file *rel* (``geo/…``).

    In its map bundle if below one of its directories, in the base map of
    its extract *osm* if below ``base/``, else in its data bundle: where
    the app fetches it (``dataUrl`` in ``web/js/files.js``).
    """
    first, _, rest = rel.partition("/")
    if first == bundle.BASE_PART:
        return f"{BASE}{osm}/{rest}"
    part = bundle.MAP_PART if first in bundle.MAP_ROOTS else bundle.DATA_PART
    return f"{part}/{slug}/{rel}"


def to_dist(path: str) -> str:
    """Return the ``dist/`` path of the app's request for URL path *path*.

    As ``serve`` serves it (``build.mounts``): the bundles' and the results'
    (final and live) paths are theirs; at the root, the cached copies are
    the sources' and everything else the app's.
    """
    if path.startswith((*BUNDLES, RESULTS, LIVE)):
        return path
    if path.startswith(f"{bundle.CACHE_DIR}/") or path == cache.STYLESHEET[1:]:
        return SOURCES + path
    return APP + path


def check_budget(sizes: dict[str, int], site: config.Site) -> tuple[Check, Check]:
    """Return the file count (per part) and file size checks."""
    counts: dict[str, int] = defaultdict(int)
    for rel in sizes:
        counts[part_of(rel)] += 1
    files = Check("files", len(sizes))
    files.problems += [
        f"{part}/: {n:,} files, budget {site.file_budget:,}"
        for part, n in sorted(counts.items())
        if n > site.file_budget
    ]
    files.notes += [f"{part}/: {n:,} files" for part, n in sorted(counts.items())]
    big = Check("sizes", len(sizes))
    big.problems += [
        f"{rel}: {format_size(size)}, limit {format_size(site.max_file_bytes)}"
        for rel, size in sizes.items()
        if size > site.max_file_bytes
    ]
    return files, big


def _parse(dist: Path, rel: str, errors: dict[str, str]) -> Any:
    """Return the JSON of ``dist/`` path *rel*; None if it does not parse.

    Why not is then in *errors*, by *rel*: the ``json`` check.
    """
    with open(f"{dist}/{rel}", "rb") as f:
        data = f.read()
    try:
        return orjson.loads(data)
    except ValueError as e:  # also invalid UTF-8, NaN and a byte order mark
        errors[rel] = str(e)
        return None


def _json_errors(dist: Path, rels: Iterable[str]) -> dict[str, str]:
    """Return path → why it does not parse, of those of *rels* that do not."""
    errors: dict[str, str] = {}
    for rel in rels:
        _parse(dist, rel, errors)
    return errors


def _digests(dist: Path, rels: Iterable[str]) -> list[str]:
    """Return the SHA-256 of each of *rels*: which files are the same."""
    out = []
    for rel in rels:
        with open(f"{dist}/{rel}", "rb") as f:
            out.append(hashlib.file_digest(f, "sha256").hexdigest())
    return out


def _join(name: str, parts: Iterable[Check]) -> Check:
    """Return the check *name* whose run on parts of the site gave *parts*."""
    result = Check(name)
    for part in parts:
        result.checked += part.checked
        result.problems += part.problems
        result.notes += part.notes
    return result


def check_headers(dist: Path, parts: Iterable[str], rels: set[str]) -> Check:
    """Return the check of each part's ``_headers`` and data part's files.

    *parts* are the parts of ``dist/`` built here, *rels* all files.
    """
    result = Check("headers")
    for part in parts:
        result.checked += 1
        result.problems += _headers_problems(dist, part)
        if part == build.APP_PART:
            continue
        result.problems += [
            f"{part}/{name} missing"
            for name in (bundle.NOT_FOUND, bundle.MANIFEST)
            if f"{part}/{name}" not in rels
        ]
        manifest = _load(dist, f"{part}/{bundle.MANIFEST}")
        if part.startswith(BUNDLES) and manifest is not None:
            own = (bundle.HEADERS, bundle.NOT_FOUND, bundle.MANIFEST)
            present = {
                rel.removeprefix(f"{part}/")
                for rel in rels
                if rel.startswith(f"{part}/")
            } - set(own)
            if present != set(manifest["files"]):
                result.problems.append(
                    f"{part}/{bundle.MANIFEST}: lists not exactly the bundle's files"
                )
    return result


def _headers_problems(dist: Path, part: str) -> list[str]:
    """Return the problems of *part*'s ``_headers`` against the Pages limits."""
    rel = f"{part}/{bundle.HEADERS}"
    path = dist / rel
    if not path.is_file():
        return [f"{rel} missing"]
    text = path.read_text(encoding="utf-8")
    try:
        rules = build.header_rules(text)
    except bundle.BuildError as e:
        return [f"{part}/{e}"]
    problems = []
    if len(rules) > MAX_HEADER_RULES:
        problems.append(f"{rel}: {len(rules)} rules, limit {MAX_HEADER_RULES}")
    problems += [
        f"{rel}:{n}: {len(line):,} characters, limit {MAX_HEADER_LINE:,}"
        for n, line in enumerate(text.splitlines(), 1)
        if len(line) > MAX_HEADER_LINE
    ]
    return problems


def _local_target(page: str, ref: str) -> str | None:
    """Return the URL path *ref* in *page* requests, if it is local."""
    # Most references are other sites' URLs, which urljoin returns as they
    # are: splitting them, cheaper than joining, rules them out.
    split = urllib.parse.urlsplit(ref)
    if split.scheme or split.netloc:
        return None
    parts = urllib.parse.urlsplit(urllib.parse.urljoin(f"/{page}", ref))
    if parts.scheme or parts.netloc:
        return None
    path = urllib.parse.unquote(parts.path)
    return (path + "index.html" if path.endswith("/") else path).lstrip("/")


def _code_references(
    dist: Path, rels: Iterable[str], elections: Iterable[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Return (``dist/`` path, referring file) for the static references.

    Of the app's code among *rels*. A script's literal path to an
    election's files is requested of every election of *elections*, (slug,
    extract) each, as the app puts the page's election's bundle or base map
    before it (:func:`election_path`); but not an area file's
    (``data/country.json``): only the elections with its contests have it,
    and :func:`_area_requests` asks for it there.
    """
    elections = tuple(elections)
    roots = (*bundle.MAP_ROOTS, bundle.BASE_PART, *bundle.DATA_ROOTS)
    references = []
    for rel in rels:
        if not rel.endswith(_CODE) or _LEAFLET_CSS.fullmatch(rel):
            continue
        page = rel.removeprefix(APP)
        text = (dist / rel).read_text(encoding="utf-8")
        script = False
        if rel.endswith(".html"):
            refs = _HTML_REF.findall(text)
        elif rel.endswith(".css"):
            refs = _CSS_URL.findall(text)
        else:
            script = True
            refs = [*_JS_IMPORT.findall(text), *(m[1] for m in _JS_PATH.findall(text))]
        for ref in refs:
            target = _local_target(page, ref)
            if target is None:
                continue
            if script and target.split("/", 1)[0] in roots:
                if not target.startswith(_AREA_DIRS):
                    references += [
                        (election_path(slug, osm, target), rel)
                        for slug, osm in elections
                    ]
            else:
                references.append((to_dist(target), rel))
    return references


def area_path(contest: str, okres_of: Mapping[str, str], root: str) -> str | None:
    """Return the area file the frontend loads for *contest*.

    ``contests.area_name``, as ``areaName`` in ``web/js/kinds.js``; *root*
    is the election's data bundle, ``data/<slug>/``, *okres_of* the okres of
    each obec of its ``data/index.json`` (:func:`_okres_of`). None if the
    obec of a municipal contest is not there.
    """
    try:
        return f"{root}data/{contests.area_name(contest, okres_of)}.json"
    except KeyError:
        return None


def _okres_of(data_index: Any) -> dict[str, str]:
    """Return obec → its okres, of ``data/index.json`` *data_index*."""
    return {code: row[1] for code, row in data_index["obce"].items()}


@dataclass
class _Geo:
    """What the geo shards say about the obce."""

    features: dict[str, dict[str, Any]] = field(default_factory=dict)
    """obec → properties."""
    bounds: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    """obec → (west, south, east, north) at the finest level of detail."""
    shards: list[str] = field(default_factory=list)
    """The ``dist/`` path of every file of ``okres/``, ``okrsky/`` and
    ``neighbours/`` the index lists."""
    council: dict[str, dict[str, set[int]]] = field(default_factory=dict)
    """obec cut into council obvody → shard → its obvody (``oz``) there."""
    okrsky: set[str] = field(default_factory=set)
    """The obce whose okrsky the map draws (``okrsky.drawn`` of the index)."""


def _geo(dist: Path, root: str, geo_index: Any) -> _Geo | None:
    """Return what the shards of *geo_index* below *root* say; None if it is None."""
    if geo_index is None:
        return None
    out = _Geo()
    bands = geo_index["shards"]
    finest = next(b["lod"] for b in bands if b["zoom"][1] is None)
    for okres in geo_index["okresy"]:
        for band in bands:
            rel = f"{root}geo/okres/{okres}/{band['lod']}.json"
            out.shards.append(rel)
            shard = _load(dist, rel)
            if shard is None:
                continue
            for f in shard["features"]:
                code = f["properties"]["id"]
                out.features.setdefault(code, f["properties"])
                if "oz" in f["properties"]:
                    out.council.setdefault(code, {}).setdefault(rel, set()).add(
                        f["properties"]["oz"]
                    )
            if band["lod"] == finest:
                _, geometries = geo.decode(shard)
                for f, g in zip(shard["features"], geometries, strict=True):
                    # An obec cut into council obvody is several features.
                    code = f["properties"]["id"]
                    west, south, east, north = (v / shard["scale"] for v in g.bounds)
                    if (old := out.bounds.get(code)) is not None:
                        west, south = min(old[0], west), min(old[1], south)
                        east, north = max(old[2], east), max(old[3], north)
                    out.bounds[code] = (west, south, east, north)
    okrsky = geo_index["okrsky"]
    out.okrsky = set(okrsky["drawn"])
    out.shards += [
        f"{root}geo/{geo.okrsky_path(okres, band['lod'])}"
        for okres in okrsky["okresy"]
        for band in okrsky["bands"]
    ]
    out.shards += [
        f"{root}geo/{geo.neighbours_path(n['lod'])}" for n in geo_index["neighbours"]
    ]
    return out


_BASE_INDEX = f"{bundle.BASE_PART}/{basemap.INDEX_FILE}"
_INDEXES = ("geo/index.json", "data/index.json", "addr/index.json", _BASE_INDEX)
"""Of an election: its indexes, in :class:`_Election` order (the base
map's as the app asks for it)."""


@dataclass
class _Election:
    """An election, with the indexes of its bundles and its base map.

    An index is None if it is missing or broken.
    """

    slug: str
    osm: str
    """Its extract, whose base map it shows."""
    halves: tuple[str, ...]
    """The halves of a regular election it holds (:attr:`config.Election.halves`)."""
    contests: list[str]
    """The contests of its ``candidates.json``."""
    geo: Any
    data: Any
    addr: Any
    base: Any

    @property
    def map_root(self) -> str:
        """``map/<slug>/``, which the paths of its map bundle start with."""
        return f"{MAP}{self.slug}/"

    @property
    def data_root(self) -> str:
        """``data/<slug>/``, which those of its data bundle start with."""
        return f"{DATA}{self.slug}/"

    def at(self, rel: str) -> str:
        """Return the ``dist/`` path of its file *rel* (:func:`election_path`)."""
        return election_path(self.slug, self.osm, rel)

    @property
    def indexes(self) -> dict[str, Any]:
        """Each of :data:`_INDEXES` → its content."""
        contents = (self.geo, self.data, self.addr, self.base)
        return dict(zip(_INDEXES, contents, strict=True))

    @classmethod
    def load(
        cls, dist: Path, election: config.Election, contests: Iterable[str]
    ) -> _Election:
        """Return *election* of the site in *dist*."""
        slug, osm = election.slug, election.osm
        indexes = (_load(dist, election_path(slug, osm, rel)) for rel in _INDEXES)
        return cls(slug, osm, election.halves, list(contests), *indexes)


def _index_requests(
    e: _Election, geo: _Geo | None, logos: str
) -> Iterator[tuple[str, str]]:
    """Yield (``dist/`` path, why) for the files the indexes point to.

    The indexes of election *e*, *geo* the :func:`_geo` of its geo index;
    *logos* is the URL path of the app's party logos (km-config ``logos``).
    """
    data_index, addr_index = e.data, e.addr
    if geo is not None:
        yield from ((rel, e.at("geo/index.json")) for rel in geo.shards)
    if data_index is not None:
        yield from (
            (e.at(f"data/names/{prefix}.json"), e.at("data/index.json"))
            for prefix in data_index["names"]
        )
        # A party is [short, name] or [short, name, logo]; the logos, the
        # app's, serve every election.
        yield from (
            (to_dist(f"{logos}/{logo}"), e.at("data/index.json"))
            for _, _, *files in data_index["parties"].values()
            for logo in files
        )
    if addr_index is not None:
        yield from (
            (e.at(f"addr/{row[0]}.json"), e.at("addr/index.json"))
            for row in addr_index["obce"]
        )
    if geo is None or data_index is None:
        return
    yield from _area_requests(e, geo, data_index)


def _area_requests(
    e: _Election, geo: _Geo, data_index: Any
) -> Iterator[tuple[str, str]]:
    """Yield (``dist/`` path, why) for the address and candidate files.

    Of election *e* with :func:`_geo` *geo* and ``data/index.json``
    *data_index*: every obec's address file; where it holds the municipal
    elections (the regular ones of both halves, or of the municipal one)
    every obec's ballots, else those the app finds by the contests (a
    by-election's ``held``, the regional elections', the country's ballots
    and its party lists).
    """
    okres_of = _okres_of(data_index)
    municipal = "oso" in e.halves
    if not municipal:
        for contest in e.contests:
            path = area_path(contest, okres_of, e.data_root)
            if path is not None:
                yield path, f"contest {contest} in {e.at('data/index.json')}"
    for code, props in sorted(geo.features.items()):
        by = f"obec {code} in {e.at('geo/okres/')}"
        yield e.at(f"addr/{code}.json"), by
        if not municipal:
            continue
        path = area_path(f"starosta:{code}", okres_of, e.data_root)
        if path is not None:
            yield path, by
        if "city" in props:
            yield e.at(f"data/city/{props['city']}.json"), by


def _research_requests(
    dist: Path, rels: Iterable[str], root: str
) -> list[tuple[str, str]]:
    """Return (``dist/`` path, why) for the cached pages research cites.

    The research of the election whose data bundle is below *root*. The
    app links a copy as ``cache/<sha256>``, which Pages (and ``serve``)
    answers with the file ``cache/<sha256>.html``.
    """
    return [
        (f"{SOURCES}{bundle.CACHE_DIR}/{f[7]}.html", rel)
        for rel in rels
        if rel.startswith(f"{root}data/research/") and (content := _load(dist, rel))
        for findings in content.values()
        for f in findings
    ]


def _election_requests(
    election: _Election,
    shards: _Geo | None,
    languages: config.Languages,
    logos: str,
) -> Iterator[tuple[str, str]]:
    """Yield (``dist/`` path, why) for the files of *election* the app requests.

    Besides the scripts' literal paths and the research's.

    *shards* is the :func:`_geo` of its geo index, *logos* the URL path of
    the party logos.
    """
    # The app requests these, whatever form the scripts give their paths
    # in.
    for rel in _INDEXES:
        yield election.at(rel), "web/js"
    yield election.at("data/about.json"), "web/js/about.js"
    yield election.at(f"geo/{geo.COARSE_FILE}"), "web/js/map.js"
    # Occupations are written in Slovak, which has no file of them.
    yield from (
        (election.at(f"{bundle.I18N_DIR}/{code}.json"), "web/js/data.js")
        for code in languages.codes
        if code != translate.REFERENCE
    )
    yield from _index_requests(election, shards, logos)
    yield from (
        (election.at(f"{bundle.BASE_PART}/{rel}"), election.at(_BASE_INDEX))
        for rel in (basemap.requested(election.base) if election.base else ())
    )


def check_links(
    rels: set[str],
    languages: config.Languages,
    slugs: Iterable[str],
    elections: Iterable[tuple[_Election, _Geo | None]],
    references: Iterable[tuple[str, str]],
    research: Iterable[tuple[str, str]],
    logos: str,
) -> Check:
    """Return the check that every file the frontend can request exists.

    *rels* are the files of ``dist/`` and those the manifests of deployed
    bundles list; *slugs* every election's, *elections* each whose bundle
    is here with the :func:`_geo` of its geo index; *references* and
    *research* the :func:`_code_references` and the
    :func:`_research_requests` of all *rels*, in order; *logos* the URL path
    of the party logos.
    """
    result = Check("links")
    slugs = list(slugs)
    elections = list(elections)
    research = list(research)
    codes = languages.codes
    requests = [
        *references,
        *((f"{APP}{code}/index.html", "config/languages.toml") for code in codes),
        *(
            (f"{APP}{code}/{slug}/index.html", "config/elections.toml")
            for code in codes
            for slug in slugs
        ),
        *((f"{APP}i18n/{code}.json", "config/languages.toml") for code in codes),
        # Without it Pages answers a missing file with the root page and 200.
        (f"{APP}{bundle.NOT_FOUND}", "Cloudflare Pages"),
        *(
            r
            for e, shards in elections
            for r in _election_requests(e, shards, languages, logos)
        ),
        *research,
    ]
    if research:
        requests.append((to_dist(cache.STYLESHEET[1:]), "the cached copies (cache.py)"))
    wanted: dict[str, str] = {}
    for target, by in requests:
        wanted.setdefault(target, by)
    for e, shards in elections:
        result.problems += [
            f"{e.at(name)} missing or broken"
            for name, content in e.indexes.items()
            if content is None
        ]
        if shards is not None and e.data is not None:
            result.problems += [
                f"obec {code} in {e.at('geo/okres/')}: not in {e.at('data/index.json')}"
                for code in sorted(shards.features)
                if code not in e.data["obce"]
            ]
    result.checked = len(wanted)
    result.problems += [
        f"{target} missing (needed by {by})"
        for target, by in sorted(wanted.items())
        if target not in rels
    ]
    return result


def _base_files(
    below: Iterable[str], root: str, base_index: Any
) -> tuple[list[str], list[str]]:
    """Return the files of the base map *root*: unrequested, and requested.

    Those the app never requests by *base_index*, and those it does, which
    are verified; paths below *root* (``base/<extract>/``), sorted, of the
    ``dist/`` paths *below* it, without the part's own files.
    """
    present = {rel.removeprefix(root) for rel in below}
    present -= {basemap.INDEX_FILE, bundle.HEADERS, bundle.NOT_FOUND, bundle.MANIFEST}
    wanted = set(basemap.requested(base_index))
    return sorted(present - wanted), sorted(present & wanted)


def _verify_base(
    dist: Path, files: Iterable[tuple[str, str]]
) -> tuple[list[list[str] | None], dict[str, str]]:
    """Return ``basemap.verify`` of each of *files*, and the files that do not parse.

    *files* are (path below the base map, ``dist/`` path); None for one
    that does not parse (:func:`_parse`).
    """
    errors: dict[str, str] = {}
    out: list[list[str] | None] = []
    for name, rel in files:
        content = _parse(dist, rel, errors)
        out.append(None if content is None else basemap.verify(name, content))
    return out, errors


def check_basemap(
    below: Iterable[str],
    root: str,
    base_index: Any,
    geo_indexes: Mapping[str, Any],
    verified: Callable[[str], list[str] | None],
) -> Check:
    """Return the check of the base map *root* (``base/<extract>/``).

    Against its index and the shards of every election on its extract,
    *geo_indexes* (``dist/`` path of its ``geo/index.json`` → content).
    *below* are the ``dist/`` paths below *root*, *verified* returns the
    :func:`_verify_base` of a file to verify, by its path below *root*.
    """
    result = Check("base")
    index = f"{root}{basemap.INDEX_FILE}"
    if base_index is None:
        result.problems.append(f"{index} missing or broken")
        return result
    for path, geo_index in geo_indexes.items():
        if geo_index is None:
            result.problems.append(f"{path} missing or broken")
            continue
        if base_index["bands"] != geo_index["shards"]:
            result.problems.append(f"{index}: bands differ from the shards of {path}")
        if base_index["okresy"] != sorted(geo_index["okresy"]):
            result.problems.append(f"{index}: okresy differ from the shards of {path}")
    extra, files = _base_files(below, root, base_index)
    if extra:
        result.problems.append(
            f"{index}: {len(extra)} files in {root} the app never requests,"
            f" such as {root}{extra[0]}"
        )
    for rel in files:
        problems = verified(rel)
        if problems is None:
            continue  # `json` reports it
        result.checked += 1
        result.problems += [f"{root}{rel}: {p}" for p in problems]
    return result


def check_contests(
    dist: Path,
    rels: Iterable[str],
    root: str,
    contests: Iterable[str],
    data_index: Any,
) -> Check:
    """Return the check that each contest is where the frontend looks.

    The contests of the election below *root*.
    """
    result = Check("contests")
    found: dict[str, list[str]] = defaultdict(list)
    area_dirs = tuple(root + d for d in _AREA_DIRS)
    for rel in sorted(rels):
        if rel.startswith(area_dirs):
            content = _load(dist, rel)
            for contest in content["contests"] if content else ():
                found[contest].append(rel)
    if data_index is None:
        result.problems.append(f"{root}data/index.json missing or broken")
        return result
    expected = set()
    okres_of = _okres_of(data_index)
    # Contest ids recur from election to election.
    election = root.removesuffix("/")
    for contest in contests:
        expected.add(contest)
        result.checked += 1
        files = found.get(contest, [])
        if not files:
            result.problems.append(f"{election} {contest}: in no area file")
        elif len(files) > 1:
            result.problems.append(f"{election} {contest}: in {', '.join(files)}")
        elif (path := area_path(contest, okres_of, root)) != files[0]:
            result.problems.append(
                f"{election} {contest}: in {files[0]}, the frontend looks in {path}"
            )
    result.problems += [
        f"{election} {contest}: in {', '.join(files)} but not in candidates.json"
        for contest, files in sorted(found.items())
        if contest not in expected
    ]
    return result


def check_councils(
    cfg: config.Config,
    loaded: Iterable[_Election],
    candidates: Mapping[str, Mapping[str, Any]],
) -> Check:
    """Return the check that a by-election draws the council obvody of its term.

    Each council contest of a by-election proper (of *loaded*, the
    elections built here, with their ``candidates.json`` in *candidates*;
    not a new election, ``vote`` ``"new"``, whose obvody are its own) in an
    obec whose council its term elected in several obvody fills seats of
    one of them, so a rule set must place the addresses in them
    (``by_address`` of its data index), as ``ems job reuse`` copies from
    the term; without, the map draws the whole obec and the address lookup
    offers the ballot everywhere. One numbered above its term's council
    contests (those held nowhere among them, ``uncontested``) must be an
    obvod of the term's rule set: the term's decision set it.
    """
    result = Check("councils")
    for e in loaded:
        term = cfg.term(cfg.election(e.slug))
        held = candidates.get(e.slug)
        if term is None or term.slug not in candidates or held is None or not e.data:
            continue
        then = candidates[term.slug]["contests"]
        split, numbers = addresses.split_councils(then), addresses.council_obvody(then)
        drawn = set(e.data["by_address"])
        for c in held["contests"]:
            code = str(c["area"])
            if c["kind"] != "oz" or c.get("vote") == NEW:
                continue
            if c["obvod"] > max(numbers.get(code, [1])):
                result.checked += 1
                rules = obvody.load_obec(cfg.election_dir(term), code)
                if rules is None or c["obvod"] not in rules.seats:
                    result.problems.append(
                        f"{e.slug} {c['id']}: above the obvody of {term.day}, whose"
                        " rule set does not list it (an obvod of the term's decision"
                        " without candidates is uncontested there)"
                    )
            if code not in split:
                continue
            result.checked += 1
            if code not in drawn:
                result.problems.append(
                    f"{e.slug} {c['id']}: its council had {len(numbers[code])}"
                    f" obvody in {term.day}, but no rule set places the addresses"
                    f" in them (`ems job reuse --election {e.slug}`)"
                )
    return result


def _comment_spans(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in _COMMENT.finditer(text)]


def _allowed(text: str, start: int, url: str, comments: list[tuple[int, int]]) -> bool:
    if url in _NAMESPACES:
        return True
    if any(a <= start < b for a, b in comments):
        return True
    if not _HREF_BEFORE.search(text, max(0, start - 8), start):
        return False
    tag = _TAG.match(text, max(0, text.rfind("<", 0, start)))
    return tag is not None and tag.group(1).lower() not in _RESOURCE_TAGS


_PAGE_POLICY = re.compile(
    r'<meta http-equiv="Content-Security-Policy" content="([^"]*)"'
)
# What a page's <meta> policy must come before: what loads or runs.
_LOADING = re.compile(r"<(?:script|link|style|base|img)\b", re.IGNORECASE)
_KM_CONFIG = re.compile(r'<meta name="km-config" content="([^"]*)"')


def _directives(policy: str) -> dict[str, list[str]]:
    """Return directive → sources of a Content-Security-Policy, the first of each."""
    directives: dict[str, list[str]] = {}
    for directive in policy.split(";"):
        name, *sources = directive.split() or [""]
        directives.setdefault(name.lower(), sources)
    return directives


def _page_policy_problems(rel: str, text: str, expected: list[str]) -> list[str]:
    """Return the problems of the ``<meta>`` policy of app page *rel*.

    It must come before anything that loads or runs, as it covers only
    what follows it, and let the page fetch from *expected* alone.
    """
    match = _PAGE_POLICY.search(text)
    if match is None:
        return [f"{rel}: no Content-Security-Policy <meta>"]
    if _LOADING.search(text, 0, match.start()):
        return [f"{rel}: Content-Security-Policy <meta> after what it covers"]
    directives = _directives(html.unescape(match.group(1)))
    connect = directives.get("connect-src", directives.get("default-src", ["*"]))
    if connect == expected:
        return []
    return [
        f"{rel}: CSP connect-src is {' '.join(connect)}, expected {' '.join(expected)}"
    ]


def _header_policy_problems(dist: Path) -> list[str]:
    """Return the problems of the CSP of the app's ``_headers``.

    A browser enforces it besides each page's own, so a fetch directive
    there would narrow what the pages may fetch from. None if
    ``_headers`` is missing or broken (``check_headers`` says so).
    """
    try:
        text = (dist / APP / bundle.HEADERS).read_text(encoding="utf-8")
        rules = build.header_rules(text)
    except (OSError, bundle.BuildError):
        return []
    policy = next(
        (
            value
            for name, value in build.response_headers(rules, "/").items()
            if name.lower() == "content-security-policy"
        ),
        "",
    )
    return [
        f"{APP}{bundle.HEADERS}: CSP has {name}, which narrows the pages' own"
        for name in ("default-src", "connect-src")
        if name in _directives(policy)
    ]


def app_configs(dist: Path, code: str, slugs: Iterable[str]) -> dict[str, Any]:
    """Return slug → the km-config of the election's shell in language *code*.

    Each names where the app finds the election's data parts (``build``);
    an election whose shell is missing or broken is left out (``links``
    says so).
    """
    out = {}
    for slug in slugs:
        try:
            text = (dist / APP / code / slug / "index.html").read_text(encoding="utf-8")
        except OSError:
            continue
        match = _KM_CONFIG.search(text)
        if match is not None:
            out[slug] = orjson.loads(html.unescape(match.group(1)))
    return out


def check_origins(
    dist: Path, rels: Iterable[str], site: config.Site, configs: Mapping[str, Any]
) -> Check:
    """Return the check that no code of the app refers to another origin.

    Than those of the data parts the shells name (*configs*,
    :func:`app_configs`), which the shells' CSP must let them fetch from,
    and only those; every other page of the app fetches from its own origin
    alone.
    """
    result = Check("origins")
    fetched = {
        build.origin(url)
        for c in configs.values()
        for url in (c["map"], c["data"], c["base"], c["results"], c["live"] or "")
        if build.origin(url)
    }
    linked = {build.origin(c["sources"]) for c in configs.values()} - {""}
    own = urllib.parse.urlsplit(site.base_url).netloc if site.base_url else None
    # The shells' config names the data parts' addresses; a match can run on
    # into the escaped config there (_netloc), so they are told by prefix.
    data_parts = re.compile(
        "|".join(re.escape(o) + r"(?![\w.-])" for o in sorted(fetched | linked))
        or r"(?!)"
    )
    expected = ["'self'", *sorted(fetched)]
    for rel in sorted(rels):
        if not rel.startswith(APP) or not rel.endswith(_CODE):
            continue
        result.checked += 1
        text = (dist / rel).read_text(encoding="utf-8")
        page = rel.endswith(".html")
        comments = _comment_spans(text) if not page else []
        for m in _URL.finditer(text):
            url = m.group()
            if _netloc(url) == own or data_parts.match(url):
                continue
            # A link target the About dialog builds from the shell's config.
            if url.startswith(site.repository):
                continue
            if not _allowed(text, m.start(), url, comments):
                line = text.count("\n", 0, m.start()) + 1
                result.problems.append(f"{rel}:{line}: {url}")
        if page:
            # The shells are in the languages' directories; the picker and
            # the 404 page at the root.
            shell = "/" in rel.removeprefix(APP)
            result.problems += _page_policy_problems(
                rel, text, expected if shell else ["'self'"]
            )
    result.problems += _header_policy_problems(dist)
    return result


def result_dirs(dist: Path) -> list[str]:
    """Return ``results/<name>`` and ``live/<name>``, of what the two parts hold.

    Every name in ``results/`` and ``live/`` but the parts' own files.
    """
    own = {bundle.HEADERS, bundle.NOT_FOUND, bundle.MANIFEST}
    return [
        f"{part}/{p.name}"
        for part in (bundle.RESULTS_PART, bundle.LIVE_PART)
        if (dist / part).is_dir()
        for p in sorted((dist / part).iterdir())
        if p.name not in own
    ]


def check_results(dist: Path, rel: str, held: Mapping[str, Any] | None) -> Check:
    """Return the check of *rel*, ``results/<name>`` or ``live/<name>``.

    The final or the live results of an election. *held* is its
    ``candidates.json`` (its ``contests`` and ``obce``) with ``parts``
    (:func:`election_map_slovakia.addresses.council_parts`) and ``past``
    (:attr:`results.Expect.past`), whose contests its results must have
    the sources of; None without one.
    """
    result = Check("results", 1)
    directory = dist / rel
    name = rel.partition("/")[2]
    try:
        dt.date.fromisoformat(name)
    except ValueError:
        result.problems.append(f"{rel}: not an election day (YYYY-MM-DD)")
        return result
    if not directory.is_dir():
        result.problems.append(f"{rel}: not a directory")
        return result
    if held is None:
        result.problems.append(f"{rel}: no candidates.json of its election here")
        return result
    expect = results.Expect.of(held, held["parts"], held["past"])
    result.problems += [f"{rel}/{p}" for p in results.check(directory, expect)]
    status = results.read_status(directory)
    if status is not None:
        result.notes.append(
            f"{rel}: phase {status.get('phase')}, version {status.get('version')}"
        )
    return result


def _netloc(url: str) -> str | None:
    """Return the host of *url*, or None where it does not parse.

    A match can run on into the shells' escaped config, brackets and all.
    """
    try:
        return urllib.parse.urlsplit(url).netloc
    except ValueError:
        return None


def _points(content: dict[str, Any]) -> Iterator[tuple[float, float]]:
    """Yield the (lon, lat) of every located address of an address file."""
    scale = addresses.SCALE
    x = y = 0
    for group in _groups(content):
        points = group["points"]
        # Deltas from the previous located address; null for an unlocated one.
        for dx, dy in zip(points[::2], points[1::2], strict=True):
            if dx is None:
                continue
            x += dx
            y += dy
            yield x / scale, y / scale


def _address_facts(
    rel: str, geo: _Geo, data_index: Any
) -> tuple[str, int, bool, bool, tuple[float, float, float, float] | None]:
    """Return what address file *rel* is checked against besides its content.

    Its obec, the obec's council obvody, whether the map cuts the obec into
    them, whether it draws its okrsky and the obec's bounds (None if not in
    the shards *geo*), by ``data/index.json`` *data_index*.
    """
    code = posixpath.splitext(posixpath.basename(rel))[0]
    return (
        code,
        data_index["obce"][code][4],
        code in geo.council,
        code in geo.okrsky,
        geo.bounds.get(code),
    )


def _verify_addresses(
    dist: Path, files: Iterable[tuple[str, tuple[Any, ...]]]
) -> tuple[list[tuple[int, list[str]] | None], dict[str, str]]:
    """Return :func:`_address_problems` of each of *files*, and those that do not parse.

    *files* are (``dist/`` path, :func:`_address_facts`); None for one that
    does not parse (:func:`_parse`).
    """
    errors: dict[str, str] = {}
    out: list[tuple[int, list[str]] | None] = []
    for rel, facts in files:
        content = _parse(dist, rel, errors)
        out.append(None if content is None else _address_problems(content, *facts))
    return out, errors


def _address_problems(
    content: Any,
    code: str,
    councils: int,
    cut: bool,
    drawn: bool,
    bounds: tuple[float, float, float, float] | None,
) -> tuple[int, list[str]]:
    """Return the points checked and the problems of an address file.

    Its content and :func:`_address_facts`; a problem is what follows the
    file's path.
    """
    problems = _council_problems(content, councils, cut)
    problems += _okrsok_problems(content, drawn)
    if bounds is None:
        problems.append(f"obec {code} not in the geo shards")
        return 0, problems
    west, south, east, north = bounds
    dlat = addresses.MAX_OUTSIDE / _METRES_PER_DEGREE + _ROUNDING
    coslat = math.cos(math.radians(max(abs(south), abs(north))))
    dlon = addresses.MAX_OUTSIDE / (_METRES_PER_DEGREE * coslat) + _ROUNDING
    checked = 0
    outside = []
    for lon, lat in _points(content):
        checked += 1
        if not (
            west - dlon <= lon <= east + dlon and south - dlat <= lat <= north + dlat
        ):
            outside.append((lat, lon))
    if outside:
        lat, lon = outside[0]
        problems.append(f"{len(outside):,} points outside the obec, e.g. {lat}, {lon}")
    return checked, problems


def check_addresses(
    root: str,
    geo: _Geo | None,
    data_index: Any,
    files: Iterable[str],
    verified: Callable[[str], tuple[int, list[str]] | None],
) -> Check:
    """Return the check that address points lie within their obec.

    And that in the obce whose council obvod goes by address every address
    has one of the obec's obvody, and the map draws all of them; and that
    every address has its okrsok exactly where the map draws the okrsky.

    Of the election below *root*, whose shards say *geo* (:func:`_geo`);
    *files* are its address files, sorted; *verified* returns the
    :func:`_verify_addresses` of one.
    """
    result = Check("addresses")
    if geo is None or data_index is None:
        result.problems.append(
            f"{root}geo/index.json or its election's data/index.json missing or broken"
        )
        return result
    for code, shards in sorted(geo.council.items()):
        want = set(range(1, data_index["obce"][code][4] + 1))
        result.problems += [
            f"{rel}: obec {code} cut into obvody {sorted(got)}, not {sorted(want)}"
            for rel, got in sorted(shards.items())
            if got != want
        ]
    for rel in files:
        outcome = verified(rel)
        if outcome is None:
            continue  # `json` reports it
        checked, problems = outcome
        result.checked += checked
        result.problems += [f"{rel}: {p}" for p in problems]
    return result


def _council_problems(content: Any, councils: int, cut: bool) -> list[str]:
    """Return the problems of the per-address council obvody of an address file.

    *cut*: the geo shards draw the obec as its council obvody.
    """
    by_address = content["council"] == addresses.ADDRESS
    if by_address != cut:
        return [
            f"council {content['council']!r}, but the map"
            f" {'cuts' if cut else 'does not cut'} the obec"
        ]
    if not by_address:
        return []
    problems = []
    for group in _groups(content):
        numbers = _per_address(group, "obvod", "obvody")
        if len(numbers) != len(group["numbers"]) or not all(
            1 <= n <= councils for n in numbers
        ):
            problems.append(
                f"{group['name']}: council obvody {numbers[:5]} are not"
                f" one of 1..{councils} per address"
            )
    return problems


def _okrsok_problems(content: Any, drawn: bool) -> list[str]:
    """Return the problems of the per-address okrsky of an address file.

    *drawn*: the map draws the obec's okrsky.
    """
    problems = []
    for group in _groups(content):
        given = "okrsok" in group or "okrsky" in group
        numbers = _per_address(group, "okrsok", "okrsky")
        if given != drawn:
            problems.append(
                f"{group['name']}: okrsky {'given' if given else 'missing'},"
                f" but the map {'does not draw' if given else 'draws'} them"
            )
        elif given and (
            len(numbers) != len(group["numbers"]) or min(numbers, default=1) < 1
        ):
            problems.append(
                f"{group['name']}: okrsky {numbers[:5]} are not one per address"
            )
    return problems


def _groups(content: Any) -> Iterator[Any]:
    """Yield the street and part groups of an address file."""
    for kind in (addresses.STREETS, addresses.PARTS):
        yield from content[kind]


def _per_address(group: Any, one: str, each: str) -> list[int]:
    """Return the numbers of *group*'s addresses: *one* for all, or *each*'s own."""
    if one in group:
        return [group[one]] * len(group["numbers"])
    return group.get(each, [])


def _verify_level(
    dist: Path, rels: Iterable[str]
) -> tuple[tuple[int, list[str], Any] | None, dict[str, str]]:
    """Return the number of features, problems and country outline of a level.

    And its files that do not parse. *rels* are its files; None if one does
    not parse: the json check says so. A problem is what follows the
    level's name.
    """
    errors: dict[str, str] = {}
    files = [_parse(dist, rel, errors) for rel in rels]
    if any(f is None for f in files):
        return None, errors
    return (
        sum(len(f["features"]) for f in files),
        geo.verify(files),
        geo.country_outline(files),
    ), errors


def _verify_okrsky(
    dist: Path,
    rels: Iterable[str],
    shard_rels: Iterable[str],
    drawn: Mapping[str, Sequence[int]],
) -> tuple[tuple[int, list[str]], dict[str, str]]:
    """Return the number of features and problems of the okrsky at a level.

    And its files that do not parse. *rels* are the okrsky's files,
    *shard_rels* the shards of their okresy at that level, *drawn* the
    obce whose okrsky the map draws, with their okrsky (``okrsky`` of the
    geo index). A problem is what follows the level's name.
    """
    errors: dict[str, str] = {}
    files = [_parse(dist, rel, errors) for rel in rels]
    shards = [_parse(dist, rel, errors) for rel in shard_rels]
    if any(f is None for f in [*files, *shards]):
        return (0, []), errors  # the json check says so
    return (
        sum(len(f["features"]) for f in files),
        geo.verify_okrsky(files, shards, drawn),
    ), errors


def ui_strings(dist: Path, languages: config.Languages) -> dict[str, Any]:
    """Return language → the app's UI strings in it, empty if missing or broken."""
    return {
        code: _load(dist, f"{APP}{build.I18N_DIR}/{code}.json") or {}
        for code in languages.codes
    }


def check_geometry(
    dist: Path,
    root: str,
    geo_index: Any,
    strings: Mapping[str, Any],
    levels: Iterable[tuple[int, list[str], Any] | None],
    okrsky: Iterable[tuple[int, list[str]]],
) -> Check:
    """Return the check that each level draws its own obce's borders.

    And that the okrsky of every obec the index lists tile it at every
    level, and that the countries around Slovakia meet it at every level,
    and are named in every language (*strings*, :func:`ui_strings`).
    *levels* are the :func:`_verify_level` of each of ``geo.level_files``,
    *okrsky* the :func:`_verify_okrsky` of each band of the okrsky, of the
    election below *root*.
    """
    result = Check("geometry")
    if geo_index is None:
        result.problems.append(f"{root}geo/index.json missing or broken")
        return result
    outlines = {}
    for name, level in zip(geo.level_files(geo_index), levels, strict=True):
        if level is not None:
            checked, problems, outlines[name] = level
            result.checked += checked
            result.problems += problems
    for checked, problems in okrsky:
        result.checked += checked
        result.problems += problems
    for band in geo_index["neighbours"]:
        rel = f"{root}geo/{geo.neighbours_path(band['lod'])}"
        content = _load(dist, rel)
        if content is None:
            continue
        result.checked += len(content["features"])
        result.problems += [
            f"{rel}: {p}" for p in geo.verify_neighbours(content, outlines)
        ]
        result.problems += [
            f"{rel}: {f['properties']['id']} has no name in {APP}i18n/{code}.json"
            for f in content["features"]
            for code, s in strings.items()
            if f"country.{f['properties']['id']}" not in s
        ]
    return result


def check_translations(
    dist: Path, languages: config.Languages, roots: Iterable[str]
) -> Check:
    """Return the check that every UI string is translated everywhere.

    Notes per language how many of the occupations of each bundle below
    *roots* are translated.
    """
    result = Check("i18n")
    for code in languages.codes:
        rel = f"{APP}{build.I18N_DIR}/{code}.json"
        strings = _load(dist, rel)
        if strings is None:
            continue  # missing or broken: the links and json checks say so
        result.checked += sum(not k.startswith("_") for k in strings)
        if strings.get("_missing"):
            result.problems.append(
                f"{rel}: {strings['_missing']:,} UI strings untranslated"
                f" (shown in {strings['_pending']})"
            )
    for root in roots:
        for code in languages.codes:
            occupations = _load(dist, f"{root}{bundle.I18N_DIR}/{code}.json")
            if occupations is None:
                continue  # Slovak, or missing: the links check says so
            count = len(occupations["occupations"])
            total = count + occupations["missing"]
            if total:
                result.notes.append(
                    f"{root}: {code} {count:,} of {total:,} occupations translated"
                    f" ({count / total:.0%})"
                )
    return result


def _chunks(rels: list[str], sizes: dict[str, int], n: int) -> list[list[str]]:
    """Split *rels*, in order, into at most *n* runs of about the same size."""
    total = sum(sizes[rel] for rel in rels) or 1
    runs: list[list[str]] = [[] for _ in range(n)]
    done = 0
    for rel in rels:
        runs[min(n - 1, done * n // total)].append(rel)
        done += sizes[rel]
    return [run for run in runs if run]


def _listing(dist: Path) -> tuple[dict[str, int], dict[str, tuple[int, int]]]:
    """Return the files of *dist*: path → size, and path → (device, inode).

    In the order of their :class:`~pathlib.Path` objects; plain strings, as
    a Path of each of the site's 170,000 files took seconds.
    """
    sizes: dict[str, int] = {}
    ids: dict[str, tuple[int, int]] = {}
    pending = [""]
    while pending:
        below = pending.pop()
        with os.scandir(f"{dist}/{below}" if below else dist) as entries:
            for entry in entries:
                rel = f"{below}/{entry.name}" if below else entry.name
                if entry.is_dir(follow_symlinks=False):
                    pending.append(rel)
                elif entry.is_file():
                    st = entry.stat()
                    sizes[rel] = st.st_size
                    ids[rel] = (st.st_dev, st.st_ino)
    return {rel: sizes[rel] for rel in sorted(sizes, key=lambda r: r.split("/"))}, ids


def _below(ordered: list[str], prefix: str) -> list[str]:
    """Return the paths of the sorted *ordered* that start with *prefix*."""
    out = []
    for rel in itertools.islice(ordered, bisect.bisect_left(ordered, prefix), None):
        if not rel.startswith(prefix):
            break
        out.append(rel)
    return out


# Of a task, its cost per byte of the files it reads, against parsing JSON:
# so that the slowest start first (parallel.each).
_VERIFY_GEO = 15
_VERIFY_BASE = 1.5
_VERIFY_ADDRESSES = 2.5
# The bytes of JSON one task of many files parses: some 0.3 s.
_BATCH = 4 << 20


def _batches(items: list[tuple[str, Any]], sizes: Mapping[str, int]) -> list[list[Any]]:
    """Split *items*, (path, item), in order into batches of about :data:`_BATCH` bytes."""
    out: list[list[Any]] = [[]]
    size = 0
    for rel, item in items:
        if size >= _BATCH:
            out.append([])
            size = 0
        out[-1].append(item)
        size += sizes[rel]
    return [batch for batch in out if batch]


_KINDS = ("level", "okrsky", "base", "addresses")
"""What :func:`run` verifies each content of once: the levels of detail, the
bands of okrsky, the base map files and the address files."""


def _parsed_by(kind: str, unit: Any) -> list[str]:
    """Return the ``dist/`` paths a verification of *kind* parses.

    *unit* is what it is given (:attr:`_Site.units`); of the other JSON
    files (``json``), the path.
    """
    if kind == "level":
        return unit
    if kind == "okrsky":
        return [*unit[0], *unit[1]]
    if kind == "json":
        return [unit]
    return [unit[1] if kind == "base" else unit[0]]


@dataclass
class _Site:
    """The site in ``dist/`` as :func:`run` checks it.

    Each content to verify (:data:`_KINDS`) is verified once, by the first
    of its paths: :attr:`units` maps its key (the digests of the files,
    and what else the verification depends on) to what it is given.
    *memo* is what the last run verified (:func:`run`).
    """

    dist: Path
    sizes: dict[str, int]
    """``dist/`` path → bytes of every file, in :class:`~pathlib.Path` order."""
    ordered: list[str]
    """The paths, sorted."""
    digest: dict[str, str]
    """Path → the SHA-256 of its content, of every JSON file."""
    loaded: list[_Election]
    shards: dict[str, _Geo | None]
    """Of each election of *loaded*, by slug, its :func:`_geo`."""
    bases: dict[str, Any]
    """The base maps built here: root (``base/<extract>/``) → its index."""
    memo: dict[str, Any]
    units: dict[str, dict[Any, Any]] = field(
        default_factory=lambda: {kind: {} for kind in _KINDS}
    )
    level_of: dict[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    """(slug, level) → the key of its level of detail."""
    okrsky_of: dict[tuple[str, str], tuple[Any, ...]] = field(default_factory=dict)
    """(slug, level) → the key of its okrsky there."""
    verified: dict[str, dict[Any, Any]] = field(
        default_factory=lambda: {kind: {} for kind in _KINDS}
    )
    """Kind → key of :attr:`units` → its verification."""
    parsed: dict[str, str | None] = field(default_factory=dict)
    """Digest → why the content does not parse, None if it does."""
    batches: dict[str, list[list[tuple[Any, Any]]]] = field(default_factory=dict)
    """Of base map, address and other JSON files: the (key, unit) of each task."""
    results_of: dict[str, str | None] = field(default_factory=dict)
    """``results/<day>`` or ``live/<day>`` → the key of its check
    (:meth:`plan_results`), None where it is not remembered."""
    results: dict[str, Check] = field(default_factory=dict)
    """Key of :attr:`results_of` → that check, of :attr:`memo` or this run."""

    def below(self, prefix: str) -> list[str]:
        """Return the paths that start with *prefix*, sorted."""
        return _below(self.ordered, prefix)

    def size(self, paths: Iterable[str]) -> int:
        """Return the bytes of the files *paths*."""
        return sum(self.sizes[p] for p in paths)

    def plan(self) -> None:
        """Fill :attr:`units` with what each bundle and base map has to verify."""
        u, digest, sizes = self.units, self.digest, self.sizes
        for e in self.loaded:
            root = e.map_root
            for name, files in (geo.level_files(e.geo) if e.geo else {}).items():
                paths = [f"{root}geo/{f}" for f in files]
                if all(p in sizes for p in paths):  # else the level is None
                    self.level_of[e.slug, name] = key = tuple(digest[p] for p in paths)
                    u["level"].setdefault(key, paths)
            for lod, paths, shards in _okrsky_files(e):
                if all(p in sizes for p in [*paths, *shards]):  # else (0, [])
                    drawn = e.geo["okrsky"]["drawn"]
                    self.okrsky_of[e.slug, lod] = key = (
                        tuple(digest[p] for p in paths),
                        tuple(digest[p] for p in shards),
                        json.dumps(drawn),  # as it is, its order too
                    )
                    u["okrsky"].setdefault(key, (paths, shards, drawn))
            if (shards := self.shards[e.slug]) is not None and e.data is not None:
                for rel in _address_files(self.ordered, root):
                    facts = _address_facts(rel, shards, e.data)
                    u["addresses"].setdefault((digest[rel], facts), (rel, facts))
        self._plan_bases()

    def _plan_bases(self) -> None:
        """Fill :attr:`units` with the files each base map has to verify."""
        for root, index in self.bases.items():
            if index is None:
                continue
            for name in _base_files(self.below(root), root, index)[1]:
                key = name, self.digest[root + name]
                self.units["base"].setdefault(key, (name, root + name))

    def _todo(self) -> dict[str, dict[Any, Any]]:
        """Return kind → key → unit of what :attr:`memo` has not verified.

        What it has is taken from there. Kind ``json`` are the other JSON
        files: path → path, one of each content.
        """
        memo_verified, memo_parsed = self.memo["verified"], self.memo["parsed"]
        todo: dict[str, dict[Any, Any]] = {}
        covered: set[str] = set()
        for kind, units in self.units.items():
            todo[kind] = {}
            for key, unit in units.items():
                digests = [self.digest[rel] for rel in _parsed_by(kind, unit)]
                covered.update(digests)
                known = key in memo_verified[kind]
                if known and all(d in memo_parsed for d in digests):
                    self.verified[kind][key] = memo_verified[kind][key]
                    self.parsed |= {d: memo_parsed[d] for d in digests}
                else:
                    todo[kind][key] = unit
        unparsed: dict[str, str] = {}
        for rel in reversed(self.ordered):
            d = self.digest.get(rel)
            if d is None or d in covered:
                continue
            if d in memo_parsed:
                self.parsed[d] = memo_parsed[d]
            else:
                unparsed[d] = rel
        todo["json"] = {rel: rel for rel in unparsed.values()}
        return todo

    def verify_tasks(self) -> dict[tuple[Any, ...], tuple[float, tuple[Any, ...]]]:
        """Return (kind, which) → (cost, task) of the parsing and verifying.

        Of each unit not in :attr:`memo`, and of each content of the other
        JSON files not there either.
        """
        todo = self._todo()
        dist, tasks = self.dist, {}
        for key, paths in todo["level"].items():
            task = (_verify_level, dist, paths)
            tasks["level", key] = _VERIFY_GEO * self.size(paths), task
        for key, (paths, shards, drawn) in todo["okrsky"].items():
            task = (_verify_okrsky, dist, paths, shards, drawn)
            tasks["okrsky", key] = _VERIFY_GEO * self.size([*paths, *shards]), task
        for kind, fn, weight in (
            ("base", _verify_base, _VERIFY_BASE),
            ("addresses", _verify_addresses, _VERIFY_ADDRESSES),
            ("json", _json_errors, 1),
        ):
            units = todo[kind].items()
            items = [(_parsed_by(kind, u)[0], (k, u)) for k, u in units]
            self.batches[kind] = _batches(sorted(items), self.sizes)
            for i, batch in enumerate(self.batches[kind]):
                files = [unit for _, unit in batch]
                cost = weight * self.size(_parsed_by(kind, u)[0] for u in files)
                tasks[kind, i] = cost, (fn, dist, files)
        return tasks

    def take(self, kind: str, which: Any, outcome: Any) -> None:
        """Take the *outcome* of the verify task (*kind*, *which*)."""
        if kind in ("level", "okrsky"):
            self.verified[kind][which], found = outcome
            rels = _parsed_by(kind, self.units[kind][which])
        elif kind == "json":
            found = outcome
            rels = [rel for _, rel in self.batches[kind][which]]
        else:
            files, found = outcome
            batch = self.batches[kind][which]
            for (key, _), verified in zip(batch, files, strict=True):
                self.verified[kind][key] = verified
            rels = [_parsed_by(kind, unit)[0] for _, unit in batch]
        self.parsed |= {self.digest[rel]: found.get(rel) for rel in rels}

    def plan_results(self, rel: str, held: Mapping[str, Any] | None) -> bool:
        """Return whether *rel* (:func:`result_dirs`) is to be checked.

        :func:`check_results` reads the files below it, against *held*, alone:
        not if :attr:`memo` has its check of the same directory, *held* and
        files, each JSON file by its content (the others it only names).
        Where none is listed below it (not a directory, or empty) it is
        checked every time.
        """
        files = self.below(f"{rel}/")
        self.results_of[rel] = None
        if not files:
            return True
        content = [(path, self.digest.get(path)) for path in files]
        key = self.results_of[rel] = stamp.value_digest((rel, held, content))
        known = self.memo["results"].get(key)
        if known is None:
            return True
        self.results[key] = known
        return False

    def take_results(self, rel: str, outcome: Check) -> None:
        """Take the check of *rel* (:func:`result_dirs`) this run made."""
        if (key := self.results_of[rel]) is not None:
            self.results[key] = outcome

    def remembered(self) -> dict[str, Any]:
        """Return what this run verified, for the next one (:attr:`memo`)."""
        return {
            "verified": self.verified,
            "parsed": self.parsed,
            "results": self.results,
        }

    def json(self) -> Check:
        """Return the check that every ``.json`` file parses."""
        rels = [rel for rel in self.ordered if rel.endswith(".json")]
        result = Check("json", len(rels))
        for rel in rels:
            if (why := self.parsed[self.digest[rel]]) is not None:
                result.problems.append(f"{rel}: {why}")
        return result

    def geometry(self, e: _Election, strings: Mapping[str, Any]) -> Check:
        """Return the geometry check of election *e*."""
        root = e.map_root
        levels: list[tuple[int, list[str], Any] | None] = []
        for name in geo.level_files(e.geo) if e.geo else {}:
            key = self.level_of.get((e.slug, name))
            level = None if key is None else self.verified["level"][key]
            if level is not None:
                level = (
                    level[0],
                    [f"{root}geo/{name}: {p}" for p in level[1]],
                    level[2],
                )
            levels.append(level)
        okrsky: list[tuple[int, list[str]]] = []
        for lod, _, _ in _okrsky_files(e):
            key = self.okrsky_of.get((e.slug, lod))
            verified = self.verified["okrsky"]
            count, problems = (0, []) if key is None else verified[key]
            name = geo.okrsky_path("*", lod)
            okrsky.append((count, [f"{root}geo/{name}: {p}" for p in problems]))
        return check_geometry(self.dist, root, e.geo, strings, levels, okrsky)

    def base(self, root: str) -> Check:
        """Return the check of the base map *root* (``base/<extract>/``)."""
        osm = root.removeprefix(BASE).rstrip("/")
        return check_basemap(
            self.below(root),
            root,
            self.bases[root],
            {e.at("geo/index.json"): e.geo for e in self.loaded if e.osm == osm},
            lambda name: self.verified["base"][name, self.digest[root + name]],
        )

    def addresses(self, e: _Election) -> Check:
        """Return the addresses check of election *e*."""
        shards = self.shards[e.slug]

        def verified(rel: str) -> tuple[int, list[str]] | None:
            assert shards is not None  # check_addresses asks only then
            key = self.digest[rel], _address_facts(rel, shards, e.data)
            return self.verified["addresses"][key]

        files = _address_files(self.ordered, e.map_root)
        return check_addresses(e.map_root, shards, e.data, files, verified)


def _okrsky_files(e: _Election) -> Iterator[tuple[str, list[str], list[str]]]:
    """Yield of each band of *e*'s okrsky its level, files and shards there."""
    if e.geo is None:
        return
    root, okresy = e.map_root, e.geo["okrsky"]["okresy"]
    for band in e.geo["okrsky"]["bands"]:
        lod = band["lod"]
        yield (
            lod,
            [f"{root}geo/{geo.okrsky_path(o, lod)}" for o in okresy],
            [f"{root}geo/okres/{o}/{lod}.json" for o in okresy],
        )


def _address_files(ordered: list[str], root: str) -> list[str]:
    """Return the address files of the map bundle below *root*, sorted."""
    index = f"{root}addr/index.json"
    return [r for r in _below(ordered, f"{root}addr/") if r != index]


def _read(
    dist: Path,
    loaded: list[_Election],
    sizes: dict[str, int],
    ids: dict[str, tuple[int, int]],
) -> tuple[dict[str, str], dict[str, _Geo | None]]:
    """Return the digest of every JSON file of *dist*, and the shards of *loaded*.

    Its :func:`_digests`, a file's hard links hashed once, and of each
    election of *loaded*, by slug, its :func:`_geo`.
    """
    json_files = (rel for rel in reversed(sizes) if rel.endswith(".json"))
    unique = list({ids[rel]: rel for rel in json_files}.values())
    hashed = _chunks(unique, sizes, (os.cpu_count() or 1) * 4)
    tasks = [
        *((_geo, dist, e.map_root, e.geo) for e in loaded),
        *((_digests, dist, chunk) for chunk in hashed),
    ]
    with progress.stage(f"reading {dist.name}/ in {len(tasks)} parts", len(tasks)) as s:
        done = list(s.track(parallel.each(parallel.call, tasks)))
    by_id = {
        ids[rel]: d
        for chunk, digests in zip(hashed, done[len(loaded) :], strict=True)
        for rel, d in zip(chunk, digests, strict=True)
    }
    shards = {e.slug: g for e, g in zip(loaded, done, strict=False)}
    return {rel: by_id[ids[rel]] for rel in sizes if ids[rel] in by_id}, shards


def _recalled(memo: Path | None, code: str) -> dict[str, Any]:
    """Return what the run that wrote *memo* verified (:meth:`_Site.remembered`).

    Nothing unless it ran the same *code* (:func:`stamp.code_digest` with
    :data:`stamp.RUNTIME`).
    """
    content: dict[str, Any] = {}
    if memo is not None:
        try:
            content = pickle.loads(memo.read_bytes())
        except Exception:  # noqa: BLE001 - none yet, or broken: nothing is known
            content = {}
    if content.get("code") != code:
        return {"verified": {kind: {} for kind in _KINDS}, "parsed": {}, "results": {}}
    return content


def run(
    dist: Path,
    cfg: config.Config,
    candidates: Mapping[str, Mapping[str, Any]],
    memo: Path | None = None,
) -> list[Check]:
    """Run every check on the site in *dist*; see the module doc.

    *candidates* maps the slug of an election to its ``candidates.json``
    (its ``contests`` and ``obce``) with ``parts``, the obce whose council
    contests are part of more, where it is built here. The checks
    run in worker processes, the slowest split into independent parts; the
    results are put together as if they ran one by one.

    Much of the site is the same file in several elections' map bundles
    (elections share their boundaries and addresses) or in several base
    maps, and a check of a file's content says the same of each copy. So
    the workers first hash every JSON file, then parse and verify each
    content once (of a base map file, each content at each path below its
    base map; of a level of detail, each set of contents; of an address
    file, each content checked against the same obec facts); the
    ``json`` check takes the files those parse as they parse them, and
    parses the rest. *memo*, a file, keeps those verifications, and the
    check of each election's results (:meth:`_Site.plan_results`), for the
    next run, which verifies only the contents it has not seen: with the
    code of this module and of all it imports and the libraries as they
    run here (:func:`stamp.code_digest`, :data:`stamp.RUNTIME`), they say
    what they said then.
    """
    site, languages = cfg.site, cfg.languages
    slugs = [e.slug for e in cfg.elections]
    with progress.stage(f"reading the indexes of {dist.name}/"):
        sizes, ids = _listing(dist)
        rels = set(sizes)
        ordered = sorted(rels)
        bundle_dirs = [
            *(f"{part}{slug}" for part in (MAP, DATA) for slug in slugs),
            *(f"{BASE}{osm}" for osm in cfg.bases),
        ]
        manifests = {d: _load(dist, f"{d}/{bundle.MANIFEST}") for d in bundle_dirs}
        # Deployed bundles and base maps, of which dist/ holds the manifest only.
        deployed = {d for d, m in manifests.items() if m is not None and "url" in m}
        present = rels | {
            f"{d}/{rel}" for d in deployed for rel in manifests[d]["files"]
        }
        # Those whose bundles and base map are built here; ``build
        # --deployed`` builds none of them.
        loaded = [
            _Election.load(
                dist,
                e,
                [c["id"] for c in candidates.get(e.slug, {}).get("contests", ())],
            )
            for e in cfg.elections
            if not {f"{MAP}{e.slug}", f"{DATA}{e.slug}", f"{BASE}{e.osm}"} & deployed
        ]
        bases = {
            f"{d}/": _load(dist, f"{d}/{basemap.INDEX_FILE}")
            for d in (f"{BASE}{osm}" for osm in cfg.bases)
            if d not in deployed
        }
        configs = app_configs(dist, languages.codes[0], slugs)
    parts = sorted({part_of(rel) for rel in rels} - deployed)
    logos = next(iter(configs.values()))["logos"].lstrip("/") if configs else ""
    digest, shards = _read(dist, loaded, sizes, ids)
    code = stamp.value_digest((stamp.code_digest("check"), stamp.RUNTIME))
    memory = _recalled(memo, code)
    s = _Site(dist, sizes, ordered, digest, loaded, shards, bases, memory)
    s.plan()
    tasks = s.verify_tasks()
    code_files = _chunks(
        [r for r in ordered if r.startswith(APP) and r.endswith(_CODE)],
        sizes,
        os.cpu_count() or 1,
    )
    for i, part in enumerate(code_files):
        task = (_code_references, dist, part, [(e.slug, e.osm) for e in cfg.elections])
        tasks["links", i] = s.size(part), task
    for e in loaded:
        research = s.below(f"{e.data_root}data/research/")
        task = (_research_requests, dist, research, e.data_root)
        tasks["research", e.slug] = s.size(research), task
        areas = [r for d in _AREA_DIRS for r in s.below(e.data_root + d)]
        task = (check_contests, dist, areas, e.data_root, e.contests, e.data)
        tasks["contests", e.slug] = s.size(areas), task
    app = s.below(APP)
    tasks["origins", None] = s.size(app), (check_origins, dist, app, site, configs)
    tasks["headers", None] = 0, (check_headers, dist, parts, rels)
    roots = [e.data_root for e in loaded]
    tasks["i18n", None] = 0, (check_translations, dist, languages, roots)
    dirs = result_dirs(dist)
    by_day = {e.day.isoformat(): e.slug for e in cfg.elections if e.slug in candidates}
    for rel in dirs:
        day = rel.partition("/")[2]
        held = candidates.get(by_day[day]) if day in by_day else None
        if s.plan_results(rel, held):
            task = (check_results, dist, rel, held)
            tasks["results", rel] = s.size(s.below(f"{rel}/")), task
    order = sorted(tasks, key=lambda name: -tasks[name][0])
    with progress.stage(f"checking in {len(tasks)} parts", len(tasks)) as stage:
        outcomes = parallel.each(parallel.call, (tasks[name][1] for name in order))
        done = dict(zip(order, stage.track(outcomes), strict=True))
    for (kind, which), outcome in done.items():
        if kind in (*_KINDS, "json"):
            s.take(kind, which, outcome)
        elif kind == "results":
            s.take_results(which, outcome)
    checked = {
        rel: done["results", rel] if key is None else s.results[key]
        for rel, key in s.results_of.items()
    }
    if memo is not None:
        output.write_file(
            memo,
            pickle.dumps({"code": code, **s.remembered()}, pickle.HIGHEST_PROTOCOL),
        )
    strings = ui_strings(dist, languages)
    return [
        # A deployed bundle's manifest stands for files deployed elsewhere.
        *check_budget({r: n for r, n in sizes.items() if part_of(r) in parts}, site),
        s.json(),
        done["headers", None],
        check_links(
            present,
            languages,
            slugs,
            ((e, shards[e.slug]) for e in loaded),
            [ref for i in range(len(code_files)) for ref in done["links", i]],
            [request for e in loaded for request in done["research", e.slug]],
            logos,
        ),
        _join("contests", (done["contests", e.slug] for e in loaded)),
        check_councils(cfg, loaded, candidates),
        done["origins", None],
        _join("results", (checked[rel] for rel in dirs)),
        _join("addresses", (s.addresses(e) for e in loaded)),
        _join("geometry", (s.geometry(e, strings) for e in loaded)),
        _join("base", (s.base(root) for root in bases)),
        done["i18n", None],
    ]


def report(checks: Iterable[Check]) -> Iterator[str]:
    """Yield a summary table, the notes, then the problems of each failed check."""
    checks = list(checks)
    yield f"{'check':<10} {'checked':>10} {'problems':>9}"
    for c in checks:
        status = "ok" if not c.problems else "FAIL"
        yield f"{c.name:<10} {c.checked:>10,} {len(c.problems):>9,}  {status}"
    notes = [f"{c.name}: {note}" for c in checks for note in c.notes]
    if notes:
        yield ""
        yield from notes
    for c in checks:
        if not c.problems:
            continue
        yield ""
        yield f"{c.name}:"
        for problem in c.problems[:SHOWN_PROBLEMS]:
            yield f"  {problem}"
        if len(c.problems) > SHOWN_PROBLEMS:
            yield f"  … and {len(c.problems) - SHOWN_PROBLEMS:,} more"
