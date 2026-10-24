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
           language, every geo shard of every okres and every level of the
           countries around Slovakia, and for every obec in the geo shards
           its address file and candidate files; every address file, name
           shard and party logo the indexes list; the cached copy of every
           page a research finding cites and the stylesheet they link
contests   every contest of ``candidates.json`` is in exactly one candidate
           area file, the one the frontend looks in (``areaPath`` in
           ``web/js/data.js``)
origins    no HTML, JS or CSS refers to another origin, except as the
           target of a link (``href``, not on ``<link>``), as an XML
           namespace or in a comment, and the live results origin
           (``live_url``) in the HTML (the app shells' config, which the
           scripts read it from); cached copies of cited pages
           (``cache/``) are documents, not code, and are not checked: what
           they refer to is only links (``cache.py`` sanitizes them). The
           CSP's connect-src in ``_headers`` is ``'self'`` and exactly the
           live results origin, if there is one
addresses  every address point lies in the bounding box of its obec at the
           finest level of detail, widened by ``addresses.MAX_OUTSIDE``;
           in an obec whose council obvod goes by address every address
           has one of its obvody, and the shards cut exactly those obce,
           into exactly their obvody
geometry   at each level of detail the lines drawn are the borders of its
           obce (or coarse cells), each exactly once, and every kraj,
           okres, obvod and the country merged from them is bounded by
           exactly the lines drawn as its border, and the council obvody
           within an obec by exactly the lines flagged so (``geo.verify``); the
           countries around Slovakia have the lines drawn between them,
           each once, leave no gap at Slovakia's border at any level
           (``geo.verify_neighbours``) and have names in every language
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

import json
import math
import posixpath
import re
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from election_map_slovakia import (
    addresses,
    build,
    cache,
    candidates,
    config,
    geo,
    progress,
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
    parts = urllib.parse.urlsplit(urllib.parse.urljoin(f"/{page}", ref))
    if parts.scheme or parts.netloc:
        return None
    path = urllib.parse.unquote(parts.path)
    return (path + "index.html" if path.endswith("/") else path).lstrip("/")


def _code_references(dist: Path, rels: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Yield (``dist/`` path, referring file) for the static references."""
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
                yield target, rel


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
    """Every file of ``okres/`` and ``neighbours/`` the index lists."""
    council: dict[str, dict[str, set[int]]] = field(default_factory=dict)
    """obec cut into council obvody → shard → its obvody (``oz``) there."""


def _geo(dist: Path, geo_index: Any) -> _Geo:
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
                    box = np.array(g.bounds) / shard["scale"]
                    code = f["properties"]["id"]
                    if code in out.bounds:
                        old = np.array(out.bounds[code])
                        box = np.concatenate(
                            [np.minimum(old[:2], box[:2]), np.maximum(old[2:], box[2:])]
                        )
                    west, south, east, north = (float(v) for v in box)
                    out.bounds[code] = (west, south, east, north)
    out.shards += [
        f"geo/{geo.neighbours_path(n['lod'])}" for n in geo_index["neighbours"]
    ]
    return out


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
    if addr_index is not None:
        yield from (
            (f"addr/{row[0]}.json", "addr/index.json") for row in addr_index["obce"]
        )
    if data_index is not None:
        # A party is [short, name] or [short, name, logo].
        yield from (
            (logo.removeprefix("/"), "data/index.json")
            for _, _, *logos in data_index["parties"].values()
            for logo in logos
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


def _research_requests(dist: Path, rels: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Yield (``dist/`` path, why) for the cached pages research cites."""
    for rel in rels:
        if rel.startswith("data/research/") and (content := _load(dist, rel)):
            for findings in content.values():
                yield from ((f"{build.CACHE_DIR}/{f[7]}.html", rel) for f in findings)


def check_links(
    dist: Path,
    rels: set[str],
    languages: config.Languages,
    geo: _Geo | None,
    data_index: Any,
    addr_index: Any,
) -> Check:
    """Return the check that every file the frontend can request exists."""
    result = Check("links")
    indexes = {
        "geo/index.json": geo,
        "data/index.json": data_index,
        "addr/index.json": addr_index,
    }
    result.problems += [
        f"{name} missing or broken"
        for name, content in indexes.items()
        if content is None
    ]
    requests = [
        *_code_references(dist, sorted(rels)),
        *((f"{code}/index.html", "config/languages.toml") for code in languages.codes),
        *((f"i18n/{code}.json", "config/languages.toml") for code in languages.codes),
        *((name, "web/js") for name in indexes),
        # Without it Pages answers a missing file with the root page and 200.
        (build.NOT_FOUND, "Cloudflare Pages"),
        *_index_requests(geo, data_index, addr_index),
        *_research_requests(dist, sorted(rels)),
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
        path = area_path(contest, data_index["obce"])
        if not files:
            result.problems.append(f"{contest}: in no area file")
        elif len(files) > 1:
            result.problems.append(f"{contest}: in {', '.join(files)}")
        elif path != files[0]:
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
    live = site.live_url
    for rel in sorted(rels):
        if not rel.endswith(_CODE) or rel.startswith(f"{build.CACHE_DIR}/"):
            continue
        result.checked += 1
        text = (dist / rel).read_text(encoding="utf-8")
        comments = _comment_spans(text) if not rel.endswith(".html") else []
        for m in _URL.finditer(text):
            url = m.group()
            # The live results origin as a value of the shells' config (the
            # escaped quote ends it), not as a prefix of a longer host.
            if (
                live
                and rel.endswith(".html")
                and (url == live or url.startswith(f"{live}&quot;"))
            ):
                continue
            if _netloc(url) == own:
                continue
            # A link target the About dialog builds from the shell's config.
            if url.startswith(site.repository):
                continue
            if not _allowed(text, m.start(), url, comments):
                line = text.count("\n", 0, m.start()) + 1
                result.problems.append(f"{rel}:{line}: {url}")
    connect = _connect_sources(dist)
    expected = ["'self'", live] if live else ["'self'"]
    if connect is not None and sorted(connect) != sorted(expected):
        result.problems.append(
            f"{build.HEADERS}: CSP connect-src is {' '.join(connect)},"
            f" expected {' '.join(expected)}"
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
    for kind in ("streets", "parts"):
        for group in content[kind]:
            points = group["points"]
            for i in range(0, len(points), 2):
                if points[i] is None:
                    continue
                x += points[i]
                y += points[i + 1]
                yield x / scale, y / scale


def check_addresses(
    dist: Path, rels: Iterable[str], geo: _Geo | None, data_index: Any
) -> Check:
    """Return the check that address points lie within their obec.

    And that in the obce whose council obvod goes by address every address
    has one of the obec's obvody, and the map draws all of them.
    """
    result = Check("addresses")
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
    for kind in (addresses.STREETS, addresses.PARTS):
        for group in content[kind]:
            numbers = (
                [group["obvod"]] * len(group["numbers"])
                if "obvod" in group
                else group.get("obvody", [])
            )
            if len(numbers) != len(group["numbers"]) or not all(
                1 <= n <= councils for n in numbers
            ):
                problems.append(
                    f"{rel}: {group['name']}: council obvody {numbers[:5]} are not"
                    f" one of 1..{councils} per address"
                )
    return problems


def check_geometry(dist: Path, geo_index: Any, languages: config.Languages) -> Check:
    """Return the check that each level draws its own obce's borders.

    And that the countries around Slovakia meet it at every level, and are
    named in every language.
    """
    result = Check("geometry")
    if geo_index is None:
        result.problems.append("geo/index.json missing or broken")
        return result
    outlines = {}
    for name, rels in geo.level_files(geo_index).items():
        with progress.stage(f"geo/{name}"):
            files = [_load(dist, f"geo/{rel}") for rel in rels]
            if any(f is None for f in files):
                continue  # missing or broken: the links and json checks say so
            result.checked += sum(len(f["features"]) for f in files)
            result.problems += [f"geo/{name}: {p}" for p in geo.verify(files)]
            outlines[name] = geo.country_outline(files)
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


def run(
    dist: Path,
    site: config.Site,
    languages: config.Languages,
    contests: Iterable[str],
) -> list[Check]:
    """Run every check on the site in *dist*; see the module doc."""
    with progress.stage(f"reading the indexes and geo shards of {dist.name}/"):
        sizes = {
            p.relative_to(dist).as_posix(): p.stat().st_size
            for p in sorted(dist.rglob("*"))
            if p.is_file()
        }
        rels = set(sizes)
        geo_index = _load(dist, "geo/index.json")
        geo = _geo(dist, geo_index) if geo_index is not None else None
        data_index = _load(dist, "data/index.json")
        addr_index = _load(dist, "addr/index.json")
    checks = [*check_budget(sizes, site)]
    for name, check in (
        ("json", lambda: check_json(dist, sorted(rels))),
        ("headers", lambda: check_headers(dist)),
        (
            "links",
            lambda: check_links(dist, rels, languages, geo, data_index, addr_index),
        ),
        ("contests", lambda: check_contests(dist, rels, contests, data_index)),
        ("origins", lambda: check_origins(dist, rels, site)),
        ("addresses", lambda: check_addresses(dist, rels, geo, data_index)),
        ("geometry", lambda: check_geometry(dist, geo_index, languages)),
        ("i18n", lambda: check_translations(dist, languages)),
    ):
        with progress.stage(f"checking {name}"):
            checks.append(check())
    return checks


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
