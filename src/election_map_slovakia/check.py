"""Verify the site in ``dist/`` before it is deployed.

Every check runs and lists all its problems, so one run shows everything
that is wrong. The site is in parts (``build``): the app in ``app/``, per
election a map bundle in ``map/<slug>/`` and a data bundle in
``data/<slug>/``, ``sources/`` and ``results/``. Problems name the files
by their path in ``dist/``. The app requests its files as ``serve`` serves
the parts (``build.mounts``): a path of the app's ``/x`` is ``app/x`` (or,
for the cached copies, ``sources/x``), and an election's ``/x`` is
``map/<slug>/x`` below ``geo/``, ``base/`` and ``addr/``, else
``data/<slug>/x`` (:func:`election_path`). Built with ``--deployed``,
``dist/`` holds the app and each bundle's manifest only: the checks of a
bundle's content are then those it passed where it was built, and the app
is checked against the files its manifest lists.

=========  ==============================================================
files      at most ``file_budget`` files (``config/site.toml``) in each
           part, which a Pages project of its own serves
sizes      no file larger than ``max_file_bytes``
json       every ``.json`` file parses
headers    each part's ``_headers`` parses and stays within the
           Cloudflare Pages limits (100 rules, 2,000 characters per line);
           each data part has its ``404.html`` and ``manifest.json``, and
           a bundle's manifest lists exactly its files
links      every file the frontend can request exists: the files HTML
           pages, scripts and app.css refer to (the code below
           ``assets/<v>/``, the libraries below ``assets/vendor/<vv>/``,
           which the build points the modules' imports at; see ``build``),
           the literal paths in the
           scripts (those of an election's files in every election's
           bundle, whose address the app puts before them), the 404 page,
           the shells of every language and election and the UI strings
           of every language; of every election its indexes, About data,
           occupations and coarse geometry, every geo shard of every
           okres, every okrsky file the geo index lists and every level of
           the countries around Slovakia, and for every obec in the geo
           shards its address file and candidate files; every address
           file, name shard and party logo the indexes list, and every
           base map file of the base index; the cached copy of every page
           a research finding cites and the stylesheet they link
contests   every contest of an election's ``candidates.json`` is in
           exactly one of its candidate area files, the one the frontend
           looks in (``areaPath`` in ``web/js/data.js``)
origins    no HTML, JS or CSS of the app refers to another origin than
           the data parts' its shells name (km-config ``map``, ``data``,
           ``results``, ``sources``), except as the target of a link
           (``href``, not on ``<link>``), as an XML namespace or in a
           comment; the CSP's connect-src in the app's ``_headers`` is
           ``'self'`` and the origins of the bundles and the results
results    every directory of ``results/`` is an election day's and holds
           results that keep the contract of docs/results.md
           (``results.check``): its ``status.json`` well-formed, every
           file it lists there with that hash, and no other; the votes of
           every unit counted of a mayor's or president's contest are its
           valid ballots, a council's within them and its seats
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
base       the base map has the shards' levels of detail and okresy
           (``base/index.json`` against ``geo/index.json``), ``base/``
           holds no file its index does not let the app request
           (``links`` reports those missing), and each file has only the
           line classes of its level and water areas whose rings are
           exactly the arcs coded as such, each buildings file its scale,
           as many vertices as its rings count, rings of three or more
           with an area and an outer ring first (``basemap.verify``)
i18n       every UI string is translated into every language (none taken
           from a fallback language); notes the share of each bundle's
           occupations translated per language
=========  ==============================================================

The vendored Leaflet stylesheet is not followed for ``links``: it styles
controls the app does not use (layers control, default marker), whose
images are not vendored.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import posixpath
import re
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from election_map_slovakia import (
    addresses,
    basemap,
    build,
    bundle,
    cache,
    candidates,
    config,
    geo,
    parallel,
    progress,
    results,
    translate,
)
from election_map_slovakia.output import format_size

APP = f"{build.APP_PART}/"
SOURCES = f"{bundle.SOURCES_PART}/"
RESULTS = f"{bundle.RESULTS_PART}/"
MAP = f"{bundle.MAP_PART}/"
DATA = f"{bundle.DATA_PART}/"
BUNDLES = (MAP, DATA)

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
_AREA_DIRS = ("data/okres/", "data/city/", "data/kraj/")
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
        return json.loads((dist / rel).read_bytes())
    except (OSError, ValueError):
        return None


def part_of(rel: str) -> str:
    """Return the part of ``dist/`` path *rel*: ``app``, ``data/<slug>``, ..."""
    first, _, rest = rel.partition("/")
    if first in (bundle.MAP_PART, bundle.DATA_PART):
        return f"{first}/{rest.partition('/')[0]}"
    return first


def election_path(slug: str, rel: str) -> str:
    """Return the ``dist/`` path of election *slug*'s file *rel* (``geo/…``).

    In its map bundle if below one of its directories, else in its data
    bundle: where the app fetches it (``dataUrl`` in ``web/js/files.js``).
    """
    part = (
        bundle.MAP_PART
        if rel.split("/", 1)[0] in bundle.MAP_ROOTS
        else bundle.DATA_PART
    )
    return f"{part}/{slug}/{rel}"


def to_dist(path: str) -> str:
    """Return the ``dist/`` path of the app's request for URL path *path*.

    As ``serve`` serves it (``build.mounts``): the bundles' and the results'
    paths are theirs; at the root, the cached copies are the sources' and
    everything else the app's.
    """
    if path.startswith((*BUNDLES, RESULTS)):
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


def check_json(dist: Path, rels: Iterable[str]) -> Check:
    """Return the check that every ``.json`` file parses."""
    result = Check("json")
    for rel in rels:
        if not rel.endswith(".json"):
            continue
        result.checked += 1
        try:
            json.loads((dist / rel).read_bytes())
        except ValueError as e:  # also invalid UTF-8
            result.problems.append(f"{rel}: {e}")
    return result


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
    dist: Path, rels: Iterable[str], slugs: Iterable[str]
) -> list[tuple[str, str]]:
    """Return (``dist/`` path, referring file) for the static references.

    Of the app's code among *rels*. A script's literal path to an
    election's files is requested of every election of *slugs*, as the app
    puts the page's election's bundle before it (:func:`election_path`).
    """
    slugs = tuple(slugs)
    roots = (*bundle.MAP_ROOTS, *bundle.DATA_ROOTS)
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
                references += [(election_path(slug, target), rel) for slug in slugs]
            else:
                references.append((to_dist(target), rel))
    return references


def area_path(contest: str, obce: dict[str, list[Any]], root: str) -> str | None:
    """Return the area file the frontend loads for *contest*.

    Mirrors ``areaPath`` in ``web/js/data.js``; *root* is the election's
    data bundle, ``data/<slug>/``, *obce* those of its ``data/index.json``.
    None if the obec of a municipal contest is not there.
    """
    kind, area = contest.split(":")
    area = area.split("/")[0]
    if kind in ("predseda", "zsk"):
        return f"{root}data/kraj/{area}.json"
    if area in candidates.CITY_CODES:
        return f"{root}data/city/{area}.json"
    if area not in obce:
        return None
    return f"{root}data/okres/{obce[area][1]}.json"


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


_BASE_INDEX = f"{basemap.OUTPUT_DIR}/{basemap.INDEX_FILE}"
_INDEXES = ("geo/index.json", "data/index.json", "addr/index.json", _BASE_INDEX)
"""Of an election: its indexes, in :class:`_Election` order."""


@dataclass
class _Election:
    """An election, with the indexes of its bundles.

    An index is None if it is missing or broken.
    """

    slug: str
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
        return election_path(self.slug, rel)

    @property
    def indexes(self) -> dict[str, Any]:
        """Each of :data:`_INDEXES` → its content."""
        contents = (self.geo, self.data, self.addr, self.base)
        return dict(zip(_INDEXES, contents, strict=True))

    @classmethod
    def load(cls, dist: Path, slug: str, contests: Iterable[str]) -> _Election:
        """Return the election *slug* of the site in *dist*."""
        indexes = (_load(dist, election_path(slug, rel)) for rel in _INDEXES)
        return cls(slug, list(contests), *indexes)


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
    for code, props in sorted(geo.features.items()):
        by = f"obec {code} in {e.at('geo/okres/')}"
        yield e.at(f"addr/{code}.json"), by
        path = area_path(f"starosta:{code}", data_index["obce"], e.data_root)
        if path is not None:
            yield path, by
        if "city" in props:
            yield e.at(f"data/city/{props['city']}.json"), by


def _research_requests(
    dist: Path, rels: Iterable[str], root: str
) -> list[tuple[str, str]]:
    """Return (``dist/`` path, why) for the cached pages research cites.

    The research of the election whose data bundle is below *root*.
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
        (election.at(f"{basemap.OUTPUT_DIR}/{rel}"), election.at(_BASE_INDEX))
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


def check_basemap(
    dist: Path, sizes: dict[str, int], root: str, base_index: Any, geo_index: Any
) -> Check:
    """Return the check of the base map below *root*.

    Against the shards and its index.
    """
    result = Check("base")
    index = f"{root}{_BASE_INDEX}"
    if base_index is None or geo_index is None:
        result.problems.append(f"{index} or {root}geo/index.json missing or broken")
        return result
    if base_index["bands"] != geo_index["shards"]:
        result.problems.append(f"{index}: bands differ from the geo shards'")
    if base_index["okresy"] != sorted(geo_index["okresy"]):
        result.problems.append(f"{index}: okresy differ from the geo shards'")
    prefix = f"{root}{basemap.OUTPUT_DIR}/"
    present = {rel.removeprefix(prefix) for rel in sizes if rel.startswith(prefix)}
    present.discard(basemap.INDEX_FILE)
    wanted = set(basemap.requested(base_index))
    if extra := sorted(present - wanted):
        result.problems.append(
            f"{index}: {len(extra)} files in {prefix} the app never requests,"
            f" such as {prefix}{extra[0]}"
        )
    for rel in sorted(present & wanted):
        content = _load(dist, prefix + rel)
        if content is None:
            continue  # `json` reports it
        result.checked += 1
        result.problems += [f"{prefix}{rel}: {p}" for p in basemap.verify(rel, content)]
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
        elif (path := area_path(contest, data_index["obce"], root)) != files[0]:
            result.problems.append(
                f"{election} {contest}: in {files[0]}, the frontend looks in {path}"
            )
    result.problems += [
        f"{election} {contest}: in {', '.join(files)} but not in candidates.json"
        for contest, files in sorted(found.items())
        if contest not in expected
    ]
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


def _connect_sources(dist: Path) -> list[str] | None:
    """Return the sources the CSP of the app pages lets them fetch from.

    None if ``_headers`` is missing or broken (``check_headers`` says so).
    """
    try:
        text = (dist / APP / bundle.HEADERS).read_text(encoding="utf-8")
        rules = build.header_rules(text)
    except (OSError, bundle.BuildError):
        return None
    policy = next(
        (
            value
            for name, value in build.response_headers(rules, "/").items()
            if name.lower() == "content-security-policy"
        ),
        "",
    )
    directives: dict[str, list[str]] = {}
    for directive in policy.split(";"):
        name, *sources = directive.split() or [""]
        directives.setdefault(name.lower(), sources)
    return directives.get("connect-src", directives.get("default-src", ["*"]))


_KM_CONFIG = re.compile(r'<meta name="km-config" content="([^"]*)"')


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
            out[slug] = json.loads(html.unescape(match.group(1)))
    return out


def check_origins(
    dist: Path, rels: Iterable[str], site: config.Site, configs: Mapping[str, Any]
) -> Check:
    """Return the check that no code of the app refers to another origin.

    Than those of the data parts the shells name (*configs*,
    :func:`app_configs`), which the CSP must let the app fetch from.
    """
    result = Check("origins")
    fetched = {
        build.origin(url)
        for c in configs.values()
        for url in (c["map"], c["data"], c["results"])
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
    for rel in sorted(rels):
        if not rel.startswith(APP) or not rel.endswith(_CODE):
            continue
        result.checked += 1
        text = (dist / rel).read_text(encoding="utf-8")
        comments = _comment_spans(text) if not rel.endswith(".html") else []
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
    connect = _connect_sources(dist)
    expected = ["'self'", *sorted(fetched)]
    if connect is not None and connect != expected:
        result.problems.append(
            f"{APP}{bundle.HEADERS}: CSP connect-src is {' '.join(connect)},"
            f" expected {' '.join(expected)}"
        )
    return result


def check_results(dist: Path) -> Check:
    """Return the check of the results of each election in ``results/``."""
    result = Check("results")
    root = dist / bundle.RESULTS_PART
    own = {bundle.HEADERS, bundle.NOT_FOUND, bundle.MANIFEST}
    days = sorted(p for p in root.iterdir() if p.name not in own)
    for directory in days:
        result.checked += 1
        rel = directory.relative_to(dist).as_posix()
        try:
            dt.date.fromisoformat(directory.name)
        except ValueError:
            result.problems.append(f"{rel}: not an election day (YYYY-MM-DD)")
            continue
        if not directory.is_dir():
            result.problems.append(f"{rel}: not a directory")
            continue
        result.problems += [f"{rel}/{p}" for p in results.check(directory)]
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


def check_addresses(
    dist: Path, rels: Iterable[str], root: str, geo_index: Any, data_index: Any
) -> Check:
    """Return the check that address points lie within their obec.

    And that in the obce whose council obvod goes by address every address
    has one of the obec's obvody, and the map draws all of them; and that
    every address has its okrsok exactly where the map draws the okrsky.

    Of the election below *root*.
    """
    result = Check("addresses")
    geo = _geo(dist, root, geo_index)
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
    for rel in sorted(rels):
        if not rel.startswith(f"{root}addr/") or rel == f"{root}addr/index.json":
            continue
        code = posixpath.splitext(posixpath.basename(rel))[0]
        content = _load(dist, rel)
        if content is None:
            continue
        result.problems += _council_problems(
            rel, content, data_index["obce"][code][4], code in geo.council
        )
        result.problems += _okrsok_problems(rel, content, code in geo.okrsky)
        if code not in geo.bounds:
            result.problems.append(f"{rel}: obec {code} not in the geo shards")
            continue
        west, south, east, north = geo.bounds[code]
        dlat = addresses.MAX_OUTSIDE / _METRES_PER_DEGREE + _ROUNDING
        coslat = math.cos(math.radians(max(abs(south), abs(north))))
        dlon = addresses.MAX_OUTSIDE / (_METRES_PER_DEGREE * coslat) + _ROUNDING
        outside = []
        for lon, lat in _points(content):
            result.checked += 1
            if not (
                west - dlon <= lon <= east + dlon
                and south - dlat <= lat <= north + dlat
            ):
                outside.append((lat, lon))
        if outside:
            lat, lon = outside[0]
            result.problems.append(
                f"{rel}: {len(outside):,} points outside the obec, e.g. {lat}, {lon}"
            )
    return result


def _council_problems(rel: str, content: Any, councils: int, cut: bool) -> list[str]:
    """Return the problems of the per-address council obvody of an address file.

    *cut*: the geo shards draw the obec as its council obvody.
    """
    by_address = content["council"] == addresses.ADDRESS
    if by_address != cut:
        return [
            f"{rel}: council {content['council']!r}, but the map"
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
                f"{rel}: {group['name']}: council obvody {numbers[:5]} are not"
                f" one of 1..{councils} per address"
            )
    return problems


def _okrsok_problems(rel: str, content: Any, drawn: bool) -> list[str]:
    """Return the problems of the per-address okrsky of an address file.

    *drawn*: the map draws the obec's okrsky.
    """
    problems = []
    for group in _groups(content):
        given = "okrsok" in group or "okrsky" in group
        numbers = _per_address(group, "okrsok", "okrsky")
        if given != drawn:
            problems.append(
                f"{rel}: {group['name']}: okrsky {'given' if given else 'missing'},"
                f" but the map {'does not draw' if given else 'draws'} them"
            )
        elif given and (
            len(numbers) != len(group["numbers"]) or min(numbers, default=1) < 1
        ):
            problems.append(
                f"{rel}: {group['name']}: okrsky {numbers[:5]} are not one per address"
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
    dist: Path, root: str, name: str, rels: Iterable[str]
) -> tuple[int, list[str], Any] | None:
    """Return the number of features, problems and country outline of a level.

    *rels* are its files below *root*``geo/``; None if one is missing or
    broken: the links and json checks say so.
    """
    files = [_load(dist, f"{root}geo/{rel}") for rel in rels]
    if any(f is None for f in files):
        return None
    return (
        sum(len(f["features"]) for f in files),
        [f"{root}geo/{name}: {p}" for p in geo.verify(files)],
        geo.country_outline(files),
    )


def _verify_okrsky(
    dist: Path, root: str, lod: str, okrsky: Any
) -> tuple[int, list[str]]:
    """Return the number of features and problems of the okrsky at *lod*.

    *okrsky* is ``okrsky`` of the geo index below *root*.
    """
    name = geo.okrsky_path("*", lod)
    files = [
        _load(dist, f"{root}geo/{geo.okrsky_path(okres, lod)}")
        for okres in okrsky["okresy"]
    ]
    shards = [
        _load(dist, f"{root}geo/okres/{okres}/{lod}.json") for okres in okrsky["okresy"]
    ]
    if any(f is None for f in [*files, *shards]):
        return 0, []  # missing or broken: the links and json checks say so
    return sum(len(f["features"]) for f in files), [
        f"{root}geo/{name}: {p}"
        for p in geo.verify_okrsky(files, shards, okrsky["drawn"])
    ]


def check_geometry(
    dist: Path,
    root: str,
    geo_index: Any,
    languages: config.Languages,
    levels: Iterable[tuple[int, list[str], Any] | None],
    okrsky: Iterable[tuple[int, list[str]]],
) -> Check:
    """Return the check that each level draws its own obce's borders.

    And that the okrsky of every obec the index lists tile it at every
    level, and that the countries around Slovakia meet it at every level,
    and are named in every language. *levels* are the :func:`_verify_level`
    of each of ``geo.level_files``, *okrsky* the :func:`_verify_okrsky` of
    each band of the okrsky, of the election below *root*.
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
    strings = {
        code: _load(dist, f"{APP}{build.I18N_DIR}/{code}.json") or {}
        for code in languages.codes
    }
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


def run(
    dist: Path, cfg: config.Config, contests: Mapping[str, Iterable[str]]
) -> list[Check]:
    """Run every check on the site in *dist*; see the module doc.

    *contests* maps the slug of an election to the contests of its
    ``candidates.json``, where its bundle is built here. The checks run in
    worker processes, the slowest split into independent parts, those of
    a bundle's files once for each; the results are put together as if
    they ran one by one.
    """
    site, languages = cfg.site, cfg.languages
    slugs = [e.slug for e in cfg.elections]
    with progress.stage(f"reading the indexes of {dist.name}/"):
        sizes = {
            p.relative_to(dist).as_posix(): p.stat().st_size
            for p in sorted(dist.rglob("*"))
            if p.is_file()
        }
        rels = set(sizes)
        ordered = sorted(rels)
        bundle_dirs = [f"{part}{slug}" for part in BUNDLES for slug in slugs]
        manifests = {d: _load(dist, f"{d}/{bundle.MANIFEST}") for d in bundle_dirs}
        # Deployed bundles, of which dist/ holds the manifest only.
        deployed = {d for d, m in manifests.items() if m is not None and "url" in m}
        present = rels | {
            f"{d}/{rel}" for d in deployed for rel in manifests[d]["files"]
        }
        # Those whose bundles are built here; ``build --deployed`` builds
        # neither of an election's.
        loaded = [
            _Election.load(dist, slug, contests.get(slug, ()))
            for slug in slugs
            if not {f"{MAP}{slug}", f"{DATA}{slug}"} & deployed
        ]
        configs = app_configs(dist, languages.codes[0], slugs)
    parts = sorted({part_of(rel) for rel in rels} - deployed)
    logos = next(iter(configs.values()))["logos"].lstrip("/") if configs else ""
    levels = {
        e.slug: geo.level_files(e.geo) if e.geo is not None else {} for e in loaded
    }
    okrsky = {
        e.slug: e.geo["okrsky"] if e.geo is not None else {"bands": []} for e in loaded
    }
    bands = {slug: [band["lod"] for band in o["bands"]] for slug, o in okrsky.items()}
    cpus = os.cpu_count() or 1
    # The slowest first, so that none of them starts last: the base maps (their
    # thousands of files), then the okrsky and levels of detail, the finer
    # the later in the index and the slower. The files to parse come last,
    # in parts that keep every worker busy to the end. An election's tasks
    # are named by its slug.
    tasks = {
        **{
            f"{e.slug} base": (check_basemap, dist, sizes, e.map_root, e.base, e.geo)
            for e in loaded
        },
        **{
            f"{e.slug} geo/{geo.okrsky_path('*', lod)}": (
                _verify_okrsky,
                dist,
                e.map_root,
                lod,
                okrsky[e.slug],
            )
            for e in loaded
            for lod in reversed(bands[e.slug])
        },
        **{
            f"{e.slug} geo/{name}": (_verify_level, dist, e.map_root, name, files)
            for e in loaded
            for name, files in reversed(levels[e.slug].items())
        },
        **{
            f"{e.slug} addresses": (
                check_addresses,
                dist,
                rels,
                e.map_root,
                e.geo,
                e.data,
            )
            for e in loaded
        },
        **{f"{e.slug} shards": (_geo, dist, e.map_root, e.geo) for e in loaded},
        **{
            f"{e.slug} research": (_research_requests, dist, ordered, e.data_root)
            for e in loaded
        },
        **{
            f"json {i}": (check_json, dist, part)
            for i, part in enumerate(
                _chunks([rel for rel in ordered if rel.endswith(".json")], sizes, cpus)
            )
        },
        **{
            f"links {i}": (
                _code_references,
                dist,
                part,
                slugs,
            )
            for i, part in enumerate(
                _chunks(
                    [r for r in ordered if r.startswith(APP) and r.endswith(_CODE)],
                    sizes,
                    cpus,
                )
            )
        },
        **{
            f"{e.slug} contests": (
                check_contests,
                dist,
                rels,
                e.data_root,
                e.contests,
                e.data,
            )
            for e in loaded
        },
        "origins": (check_origins, dist, rels, site, configs),
        "headers": (check_headers, dist, parts, rels),
        "i18n": (check_translations, dist, languages, [e.data_root for e in loaded]),
    }
    if (dist / bundle.RESULTS_PART).is_dir():
        tasks["results"] = (check_results, dist)
    with progress.stage(f"checking in {len(tasks)} parts", len(tasks)) as s:
        done = dict(
            zip(
                tasks,
                s.track(parallel.each(parallel.call, tasks.values())),
                strict=True,
            )
        )

    def each(task: str) -> list[Any]:
        """Return the outcome of *task* for every election built here."""
        return [done[f"{e.slug} {task}"] for e in loaded]

    return [
        # A deployed bundle's manifest stands for files deployed elsewhere.
        *check_budget({r: s for r, s in sizes.items() if part_of(r) in parts}, site),
        _join("json", (c for key, c in done.items() if key.startswith("json "))),
        done["headers"],
        check_links(
            present,
            languages,
            slugs,
            zip(loaded, each("shards"), strict=True),
            [
                ref
                for key, refs in done.items()
                if key.startswith("links ")
                for ref in refs
            ],
            [request for requests in each("research") for request in requests],
            logos,
        ),
        _join("contests", each("contests")),
        done["origins"],
        done.get("results", Check("results")),
        _join("addresses", each("addresses")),
        _join(
            "geometry",
            (
                check_geometry(
                    dist,
                    e.map_root,
                    e.geo,
                    languages,
                    [done[f"{e.slug} geo/{name}"] for name in levels[e.slug]],
                    [
                        done[f"{e.slug} geo/{geo.okrsky_path('*', lod)}"]
                        for lod in bands[e.slug]
                    ],
                )
                for e in loaded
            ),
        ),
        _join("base", each("base")),
        done["i18n"],
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
