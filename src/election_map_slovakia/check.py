"""Verify the site in ``dist/`` before it is deployed.

Every check runs and lists all its problems, so one run shows everything
that is wrong:

=========  ==============================================================
files      at most ``file_budget`` files (``config/site.toml``)
sizes      no file larger than ``max_file_bytes``
json       every ``.json`` file parses
headers    ``_headers`` parses and stays within the Cloudflare Pages
           limits (100 rules, 2,000 characters per line)
links      every file the frontend can request exists: the files HTML
           pages, scripts and app.css refer to (the code below
           ``assets/<v>/``, the libraries below ``assets/vendor/<vv>/``,
           which the build points the modules' imports at; see ``build``),
           the literal paths in the
           scripts, the 404 page, the shell and UI strings of every
           language, every geo shard of every okres, every okrsky file the
           geo index lists and every level of the
           countries around Slovakia, and for every obec in the geo shards
           its address file and candidate files; every address file, name
           shard and party logo the indexes list, and every base map file
           of the base index; the cached copy of every
           page a research finding cites and the stylesheet they link
contests   every contest of ``candidates.json`` is in exactly one candidate
           area file, the one the frontend looks in (``areaPath`` in
           ``web/js/data.js``)
origins    no HTML, JS or CSS refers to another origin, except as the
           target of a link (``href``, not on ``<link>``), as an XML
           namespace or in a comment; cached copies of cited pages
           (``cache/``) are documents, not code, and are not checked: what
           they refer to is only links (``cache.py`` sanitizes them). The
           CSP's connect-src in ``_headers`` is ``'self'`` alone
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
           holds no file its index does not let the app request (``links``
           reports those missing), and each file has only the line classes
           of its level and water areas whose rings are exactly the arcs
           coded as such, each
           buildings file its scale, as many vertices as its rings count,
           rings of three or more with an area and an outer ring first
           (``basemap.verify``)
i18n       every UI string is translated into every language (none taken
           from a fallback language) and each language's occupations file
           holds as many as its UI strings say; notes the share of
           occupations translated per language
=========  ==============================================================

The vendored Leaflet stylesheet is not followed for ``links``: it styles
controls the app does not use (layers control, default marker), whose
images are not vendored.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import posixpath
import re
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from election_map_slovakia import (
    addresses,
    basemap,
    build,
    cache,
    candidates,
    config,
    geo,
    parallel,
    progress,
    results,
)
from election_map_slovakia.output import format_size

# https://developers.cloudflare.com/pages/platform/limits/
MAX_HEADER_RULES = 100
MAX_HEADER_LINE = 2000
SHOWN_PROBLEMS = 20

_CODE = (".html", ".js", ".mjs", ".css")
_LEAFLET_CSS = re.compile(
    rf"{build.ASSETS_DIR}/{build.VENDOR_DIR}/[^/]+/leaflet/leaflet\.css"
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


def check_budget(sizes: dict[str, int], site: config.Site) -> tuple[Check, Check]:
    """Return the file count and file size checks."""
    files = Check("files", len(sizes))
    if len(sizes) > site.file_budget:
        files.problems.append(f"{len(sizes):,} files, budget {site.file_budget:,}")
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


def check_headers(dist: Path) -> Check:
    """Return the check of ``_headers`` against the Pages limits."""
    result = Check("headers")
    path = dist / build.HEADERS
    if not path.is_file():
        result.problems.append(f"{build.HEADERS} missing")
        return result
    text = path.read_text(encoding="utf-8")
    try:
        rules = build.header_rules(text)
    except build.BuildError as e:
        result.problems.append(str(e))
        return result
    result.checked = len(rules)
    if len(rules) > MAX_HEADER_RULES:
        result.problems.append(f"{len(rules)} rules, limit {MAX_HEADER_RULES}")
    result.problems += [
        f"{build.HEADERS}:{n}: {len(line):,} characters, limit {MAX_HEADER_LINE:,}"
        for n, line in enumerate(text.splitlines(), 1)
        if len(line) > MAX_HEADER_LINE
    ]
    return result


def _local_target(page: str, ref: str) -> str | None:
    """Return the ``dist/`` path *ref* in *page* requests, if it is local."""
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


def _code_references(dist: Path, rels: Iterable[str]) -> list[tuple[str, str]]:
    """Return (``dist/`` path, referring file) for the static references."""
    references = []
    for rel in rels:
        if not rel.endswith(_CODE) or _LEAFLET_CSS.fullmatch(rel):
            continue
        text = (dist / rel).read_text(encoding="utf-8")
        if rel.endswith(".html"):
            refs = _HTML_REF.findall(text)
        elif rel.endswith(".css"):
            refs = _CSS_URL.findall(text)
        else:
            refs = [*_JS_IMPORT.findall(text), *(m[1] for m in _JS_PATH.findall(text))]
        for ref in refs:
            target = _local_target(rel, ref)
            if target is not None:
                references.append((target, rel))
    return references


def area_path(contest: str, obce: dict[str, list[Any]]) -> str | None:
    """Return the area file the frontend loads for *contest*.

    Mirrors ``areaPath`` in ``web/js/data.js``; None if the obec of a
    municipal contest is not in ``data/index.json``.
    """
    kind, area = contest.split(":")
    area = area.split("/")[0]
    if kind in ("predseda", "zsk"):
        return f"data/kraj/{area}.json"
    if area in candidates.CITY_CODES:
        return f"data/city/{area}.json"
    if area not in obce:
        return None
    return f"data/okres/{obce[area][1]}.json"


@dataclass
class _Geo:
    """What the geo shards say about the obce."""

    features: dict[str, dict[str, Any]] = field(default_factory=dict)
    """obec → properties."""
    bounds: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    """obec → (west, south, east, north) at the finest level of detail."""
    shards: list[str] = field(default_factory=list)
    """Every file of ``okres/``, ``okrsky/`` and ``neighbours/`` the index lists."""
    council: dict[str, dict[str, set[int]]] = field(default_factory=dict)
    """obec cut into council obvody → shard → its obvody (``oz``) there."""
    okrsky: set[str] = field(default_factory=set)
    """The obce whose okrsky the map draws (``okrsky.drawn`` of the index)."""


def _geo(dist: Path, geo_index: Any) -> _Geo | None:
    """Return what the shards of *geo_index* say; None if it is None."""
    if geo_index is None:
        return None
    out = _Geo()
    bands = geo_index["shards"]
    finest = next(b["lod"] for b in bands if b["zoom"][1] is None)
    for okres in geo_index["okresy"]:
        for band in bands:
            rel = f"geo/okres/{okres}/{band['lod']}.json"
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
        f"geo/{geo.okrsky_path(okres, band['lod'])}"
        for okres in okrsky["okresy"]
        for band in okrsky["bands"]
    ]
    out.shards += [
        f"geo/{geo.neighbours_path(n['lod'])}" for n in geo_index["neighbours"]
    ]
    return out


_BASE_INDEX = f"{basemap.OUTPUT_DIR}/{basemap.INDEX_FILE}"


def _index_requests(
    geo: _Geo | None, data_index: Any, addr_index: Any
) -> Iterator[tuple[str, str]]:
    """Yield (``dist/`` path, why) for the files the indexes point to."""
    if geo is not None:
        yield from ((rel, "geo/index.json") for rel in geo.shards)
    if data_index is not None:
        yield from (
            (f"data/names/{prefix}.json", "data/index.json")
            for prefix in data_index["names"]
        )
        # A party is [short, name] or [short, name, logo].
        yield from (
            (logo.removeprefix("/"), "data/index.json")
            for _, _, *logos in data_index["parties"].values()
            for logo in logos
        )
    if addr_index is not None:
        yield from (
            (f"addr/{row[0]}.json", "addr/index.json") for row in addr_index["obce"]
        )
    if geo is None or data_index is None:
        return
    for code, props in sorted(geo.features.items()):
        by = f"obec {code} in geo/okres/"
        yield f"addr/{code}.json", by
        path = area_path(f"starosta:{code}", data_index["obce"])
        if path is not None:
            yield path, by
        if "city" in props:
            yield f"data/city/{props['city']}.json", by


def _research_requests(dist: Path, rels: Iterable[str]) -> list[tuple[str, str]]:
    """Return (``dist/`` path, why) for the cached pages research cites."""
    return [
        (f"{build.CACHE_DIR}/{f[7]}.html", rel)
        for rel in rels
        if rel.startswith("data/research/") and (content := _load(dist, rel))
        for findings in content.values()
        for f in findings
    ]


def check_links(
    rels: set[str],
    languages: config.Languages,
    geo: _Geo | None,
    data_index: Any,
    addr_index: Any,
    base_index: Any,
    references: Iterable[tuple[str, str]],
    research: Iterable[tuple[str, str]],
) -> Check:
    """Return the check that every file the frontend can request exists.

    *references* and *research* are the :func:`_code_references` and the
    :func:`_research_requests` of all *rels*, in order.
    """
    result = Check("links")
    indexes = {
        "geo/index.json": geo,
        "data/index.json": data_index,
        "addr/index.json": addr_index,
        _BASE_INDEX: base_index,
    }
    result.problems += [
        f"{name} missing or broken"
        for name, content in indexes.items()
        if content is None
    ]
    requests = [
        *references,
        *((f"{code}/index.html", "config/languages.toml") for code in languages.codes),
        *((f"i18n/{code}.json", "config/languages.toml") for code in languages.codes),
        *((name, "web/js") for name in indexes),
        # Without it Pages answers a missing file with the root page and 200.
        (build.NOT_FOUND, "Cloudflare Pages"),
        *_index_requests(geo, data_index, addr_index),
        *(
            (f"{basemap.OUTPUT_DIR}/{rel}", _BASE_INDEX)
            for rel in (basemap.requested(base_index) if base_index else ())
        ),
        *research,
        (cache.STYLESHEET.removeprefix("/"), "the cached copies (cache.py)"),
    ]
    wanted: dict[str, str] = {}
    for target, by in requests:
        wanted.setdefault(target, by)
    if geo is not None and data_index is not None:
        result.problems += [
            f"obec {code} in geo/okres/: not in data/index.json"
            for code in sorted(geo.features)
            if code not in data_index["obce"]
        ]
    result.checked = len(wanted)
    result.problems += [
        f"{target} missing (needed by {by})"
        for target, by in sorted(wanted.items())
        if target not in rels
    ]
    return result


def check_basemap(
    dist: Path, sizes: dict[str, int], base_index: Any, geo_index: Any
) -> Check:
    """Return the check of the base map against the shards and its index."""
    result = Check("base")
    if base_index is None or geo_index is None:
        result.problems.append(f"{_BASE_INDEX} or geo/index.json missing or broken")
        return result
    if base_index["bands"] != geo_index["shards"]:
        result.problems.append(f"{_BASE_INDEX}: bands differ from the geo shards'")
    if base_index["okresy"] != sorted(geo_index["okresy"]):
        result.problems.append(f"{_BASE_INDEX}: okresy differ from the geo shards'")
    prefix = f"{basemap.OUTPUT_DIR}/"
    present = {rel.removeprefix(prefix) for rel in sizes if rel.startswith(prefix)}
    present.discard(basemap.INDEX_FILE)
    wanted = set(basemap.requested(base_index))
    if extra := sorted(present - wanted):
        result.problems.append(
            f"{_BASE_INDEX}: {len(extra)} files in {prefix} the app never requests,"
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
    dist: Path, rels: Iterable[str], contests: Iterable[str], data_index: Any
) -> Check:
    """Return the check that each contest is where the frontend looks."""
    result = Check("contests")
    found: dict[str, list[str]] = defaultdict(list)
    for rel in sorted(rels):
        if rel.startswith(_AREA_DIRS):
            content = _load(dist, rel)
            for contest in content["contests"] if content else ():
                found[contest].append(rel)
    if data_index is None:
        result.problems.append("data/index.json missing or broken")
        return result
    expected = set()
    for contest in contests:
        expected.add(contest)
        result.checked += 1
        files = found.get(contest, [])
        if not files:
            result.problems.append(f"{contest}: in no area file")
        elif len(files) > 1:
            result.problems.append(f"{contest}: in {', '.join(files)}")
        elif (path := area_path(contest, data_index["obce"])) != files[0]:
            result.problems.append(
                f"{contest}: in {files[0]}, the frontend looks in {path}"
            )
    result.problems += [
        f"{contest}: in {', '.join(files)} but not in candidates.json"
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
        rules = build.header_rules((dist / build.HEADERS).read_text(encoding="utf-8"))
    except (OSError, build.BuildError):
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


def check_origins(dist: Path, rels: Iterable[str], site: config.Site) -> Check:
    """Return the check that no code refers to another origin."""
    result = Check("origins")
    own = urllib.parse.urlsplit(site.base_url).netloc if site.base_url else None
    for rel in sorted(rels):
        if not rel.endswith(_CODE) or rel.startswith(f"{build.CACHE_DIR}/"):
            continue
        result.checked += 1
        text = (dist / rel).read_text(encoding="utf-8")
        comments = _comment_spans(text) if not rel.endswith(".html") else []
        for m in _URL.finditer(text):
            url = m.group()
            if _netloc(url) == own:
                continue
            # A link target the About dialog builds from the shell's config.
            if url.startswith(site.repository):
                continue
            if not _allowed(text, m.start(), url, comments):
                line = text.count("\n", 0, m.start()) + 1
                result.problems.append(f"{rel}:{line}: {url}")
    connect = _connect_sources(dist)
    if connect is not None and connect != ["'self'"]:
        result.problems.append(
            f"{build.HEADERS}: CSP connect-src is {' '.join(connect)}, expected 'self'"
        )
    return result


def check_results(dist: Path) -> Check:
    """Return the check of the results of each election in ``results/``."""
    result = Check("results")
    root = dist / config.RESULTS_DIR
    days = sorted(root.iterdir()) if root.is_dir() else []
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
    dist: Path, rels: Iterable[str], geo_index: Any, data_index: Any
) -> Check:
    """Return the check that address points lie within their obec.

    And that in the obce whose council obvod goes by address every address
    has one of the obec's obvody, and the map draws all of them; and that
    every address has its okrsok exactly where the map draws the okrsky.
    """
    result = Check("addresses")
    geo = _geo(dist, geo_index)
    if geo is None or data_index is None:
        result.problems.append("geo/index.json or data/index.json missing or broken")
        return result
    for code, shards in sorted(geo.council.items()):
        want = set(range(1, data_index["obce"][code][4] + 1))
        result.problems += [
            f"{rel}: obec {code} cut into obvody {sorted(got)}, not {sorted(want)}"
            for rel, got in sorted(shards.items())
            if got != want
        ]
    for rel in sorted(rels):
        if not rel.startswith("addr/") or rel == "addr/index.json":
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
    dist: Path, name: str, rels: Iterable[str]
) -> tuple[int, list[str], Any] | None:
    """Return the number of features, problems and country outline of a level.

    *rels* are its files below ``geo/``; None if one is missing or broken:
    the links and json checks say so.
    """
    files = [_load(dist, f"geo/{rel}") for rel in rels]
    if any(f is None for f in files):
        return None
    return (
        sum(len(f["features"]) for f in files),
        [f"geo/{name}: {p}" for p in geo.verify(files)],
        geo.country_outline(files),
    )


def _verify_okrsky(dist: Path, lod: str, okrsky: Any) -> tuple[int, list[str]]:
    """Return the number of features and problems of the okrsky at *lod*.

    *okrsky* is ``okrsky`` of the geo index.
    """
    name = geo.okrsky_path("*", lod)
    files = [
        _load(dist, f"geo/{geo.okrsky_path(okres, lod)}") for okres in okrsky["okresy"]
    ]
    shards = [
        _load(dist, f"geo/okres/{okres}/{lod}.json") for okres in okrsky["okresy"]
    ]
    if any(f is None for f in [*files, *shards]):
        return 0, []  # missing or broken: the links and json checks say so
    return sum(len(f["features"]) for f in files), [
        f"geo/{name}: {p}" for p in geo.verify_okrsky(files, shards, okrsky["drawn"])
    ]


def check_geometry(
    dist: Path,
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
    each band of the okrsky.
    """
    result = Check("geometry")
    if geo_index is None:
        result.problems.append("geo/index.json missing or broken")
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
    strings = {code: _load(dist, f"i18n/{code}.json") or {} for code in languages.codes}
    for band in geo_index["neighbours"]:
        rel = geo.neighbours_path(band["lod"])
        content = _load(dist, f"geo/{rel}")
        if content is None:
            continue
        result.checked += len(content["features"])
        result.problems += [
            f"geo/{rel}: {p}" for p in geo.verify_neighbours(content, outlines)
        ]
        result.problems += [
            f"geo/{rel}: {f['properties']['id']} has no name in i18n/{code}.json"
            for f in content["features"]
            for code, s in strings.items()
            if f"country.{f['properties']['id']}" not in s
        ]
    return result


def check_translations(dist: Path, languages: config.Languages) -> Check:
    """Return the check that every UI string is translated everywhere.

    Notes per language how many occupations are translated.
    """
    result = Check("i18n")
    for code in languages.codes:
        strings = _load(dist, f"i18n/{code}.json")
        if strings is None:
            continue  # missing or broken: the links and json checks say so
        result.checked += sum(not k.startswith("_") for k in strings)
        missing = strings.get("_missing", {})
        if missing.get("ui"):
            result.problems.append(
                f"i18n/{code}.json: {missing['ui']:,} UI strings untranslated"
                f" (shown in {strings['_pending']})"
            )
        count = strings.get("_occupations", 0)
        total = count + missing.get("occupations", 0)
        if total:
            result.notes.append(
                f"{code}: {count:,} of {total:,} occupations translated"
                f" ({count / total:.0%})"
            )
        rel = f"i18n/{code}/occupations.json"
        if count and len(_load(dist, rel) or {}) != count:
            result.problems.append(f"{rel}: missing, or not {count:,} occupations")
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
    dist: Path,
    site: config.Site,
    languages: config.Languages,
    contests: Iterable[str],
) -> list[Check]:
    """Run every check on the site in *dist*; see the module doc.

    The checks run in worker processes, the slowest split into independent
    parts; the results are put together as if they ran one by one.
    """
    with progress.stage(f"reading the indexes of {dist.name}/"):
        sizes = {
            p.relative_to(dist).as_posix(): p.stat().st_size
            for p in sorted(dist.rglob("*"))
            if p.is_file()
        }
        rels = set(sizes)
        ordered = sorted(rels)
        geo_index = _load(dist, "geo/index.json")
        data_index = _load(dist, "data/index.json")
        addr_index = _load(dist, "addr/index.json")
        base_index = _load(dist, _BASE_INDEX)
    levels = geo.level_files(geo_index) if geo_index is not None else {}
    okrsky = geo_index["okrsky"] if geo_index is not None else {"bands": []}
    bands = [band["lod"] for band in okrsky["bands"]]
    cpus = os.cpu_count() or 1
    # The slowest first, so that none of them starts last: the base map (its
    # thousands of files), then the okrsky and levels of detail, the finer
    # the later in the index and the slower. The files to parse come last,
    # in parts that keep every worker busy to the end.
    tasks = {
        "base": (check_basemap, dist, sizes, base_index, geo_index),
        **{
            f"geo/{geo.okrsky_path('*', lod)}": (_verify_okrsky, dist, lod, okrsky)
            for lod in reversed(bands)
        },
        **{
            f"geo/{name}": (_verify_level, dist, name, files)
            for name, files in reversed(levels.items())
        },
        "addresses": (check_addresses, dist, rels, geo_index, data_index),
        "shards": (_geo, dist, geo_index),
        "research": (_research_requests, dist, ordered),
        "results": (check_results, dist),
        **{
            f"json {i}": (check_json, dist, part)
            for i, part in enumerate(
                _chunks([rel for rel in ordered if rel.endswith(".json")], sizes, cpus)
            )
        },
        **{
            f"links {i}": (_code_references, dist, part)
            for i, part in enumerate(
                _chunks([rel for rel in ordered if rel.endswith(_CODE)], sizes, cpus)
            )
        },
        "contests": (check_contests, dist, rels, list(contests), data_index),
        "origins": (check_origins, dist, rels, site),
        "headers": (check_headers, dist),
        "i18n": (check_translations, dist, languages),
    }
    with progress.stage(f"checking in {len(tasks)} parts", len(tasks)) as s:
        parts = parallel.each(parallel.call, tasks.values())
        done = dict(zip(tasks, s.track(parts), strict=True))
    return [
        *check_budget(sizes, site),
        _join("json", (c for key, c in done.items() if key.startswith("json "))),
        done["headers"],
        check_links(
            rels,
            languages,
            done["shards"],
            data_index,
            addr_index,
            base_index,
            [
                ref
                for key, refs in done.items()
                if key.startswith("links ")
                for ref in refs
            ],
            done["research"],
        ),
        done["contests"],
        done["origins"],
        done["results"],
        done["addresses"],
        check_geometry(
            dist,
            geo_index,
            languages,
            [done[f"geo/{name}"] for name in levels],
            [done[f"geo/{geo.okrsky_path('*', lod)}"] for lod in bands],
        ),
        done["base"],
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
