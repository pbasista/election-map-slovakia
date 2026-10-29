"""Assemble the static site in ``dist/`` and serve it for local testing.

``build`` wipes ``dist/`` and writes the site in parts, each deployed to a
Cloudflare Pages project of its own (docs/deploy.md): the app, written
here from ``web/`` (the frontend source) and the configuration, and the
data parts, which :mod:`election_map_slovakia.bundle` assembles from each
election's ``data/build/<day>/`` and the curated data. Every file is a
pure function of those inputs, so two builds from the same inputs are byte
for byte identical.

Output (paths relative to ``dist/``; JSON is compact UTF-8 with sorted
keys)::

    app/                     the app (below)
    map/<slug>/              each election's map bundle (bundle.py)
    data/<slug>/             each election's data bundle (bundle.py)
    sources/                 the cached copies of the pages research cites
                             (bundle.py)
    results/                 the results of every election (bundle.py)

Built with ``--deployed``, ``dist/`` holds the app alone, whose shells
name the deployed data (:class:`Locations`), and of each election the
``manifest.json`` of the deployments of its bundles, which ``check``
checks the app against. ``serve`` serves the parts as one site, where the
app finds them without ``--deployed`` (:func:`mounts`): each bundle at
``/map/<slug>`` or ``/data/<slug>``, the results at ``/results``, the
sources at the root.

The app, below ``app/``. Every election of ``config/elections.toml`` has
its own pages, named by its slug (``2026``); the newest, the latest, is
also the one ``/<lang>/`` shows::

    index.html               language picker: stored choice, then
                             navigator.languages (aliases applied), then the
                             first fallback language
    404.html                 what Pages (and ``serve``) answers a missing path
                             with, status 404; from web/404.html
    <lang>/<slug>/index.html app shell per enabled language and election,
                             from web/index.html
    <lang>/index.html        the latest election's, whose canonical URL it
                             is (:func:`shells`)
    _headers                 Cloudflare Pages response headers, from
                             web/_headers (see :func:`header_rules`) with
                             the data parts' origins the app fetches from,
                             plus a noindex rule for the pages.dev hosts
                             once the site has a domain of its own
                             (:func:`headers`)
    sitemap.xml              the root page and every language's app shells,
                             absolute under ``base_url``; none without it
                             (:func:`sitemap`)
    assets/<v>/              web/app.css and web/js/; <v> is the code
                             version (below), and the modules import the
                             vendored libraries from assets/vendor/<vv>/
                             (:func:`code_files`)
    assets/vendor/<vv>/      web/vendor/, verbatim; <vv> its version
    assets/img/<iv>/         web/img/ (party logos), verbatim; <iv> its
                             version
    i18n/<lang>.json         UI strings: web/i18n/<lang>.json, or for other
                             languages the curated translations of the
                             current strings of the first fallback language
                             (translate.py), the rest taken from it. If a
                             UI string is untranslated, "_pending" is that
                             language's code (the app shows a notice) and
                             "_missing" the count; "_locale" is it too if
                             no UI string is translated (the app formats
                             dates and numbers in it). `{site}` in a string
                             becomes the site name of the language the
                             string is written in; "app.name" is the page
                             language's own site name (languages.toml)

Cache busting. The code, the vendored libraries and the images each live
under a directory named by a short hash of their files
(:func:`bundle.content_version`): ``/assets/<v>/``,
``/assets/vendor/<vv>/`` and ``/assets/img/<iv>/``. A release that changes
a file of one moves that tree to new URLs, which browsers may keep for
good (``immutable`` in web/_headers), and a release that changes none of a
tree keeps its URLs and the browsers' copies: the libraries, which change
only with a deliberate upgrade, and the logos outlast changes to the app's
code. The app's modules import each other by relative paths, so they need
not know ``<v>``; their imports of the libraries (``'../vendor/…'`` in
web/js, which keeps web/ runnable as it is) are rewritten to
``/assets/vendor/<vv>/``, and ``<v>`` is the hash of the rewritten files,
so a library upgrade is new code too. The UI strings (``i18n/``), the same
for every election, are requested with ``?v=<sv>``, a hash of them alone,
so that switching elections keeps the browser's copies; an election's
files with ``?v=`` its bundle's version (its ``manifest.json``), so that a
browser's copy belongs to the version it was fetched for. The results
files are requested with ``?v=`` the hash of each that their
``status.json`` lists, and ``status.json`` itself is revalidated on every
load (web/_headers-results). The app shells carry, in the ``km-config``
meta JSON (:func:`shells`), the versions as ``mapVersion``,
``dataVersion`` and ``stringsVersion``, the addresses of the election's
bundles (``map``, ``data``), of its results (``results``, named even
before there are any: a page loaded then finds them there once a
deployment brings them), of the cached sources (``sources``) and of the
party logos (``logos``). A shell whose map bundle is on another origin
preconnects to it, as the map's first files are what it fetches first.
"""

from __future__ import annotations

import functools
import html
import json
import re
import shutil
import urllib.parse
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from election_map_slovakia import (
    __version__,
    basemap,
    bundle,
    config,
    geo,
    lock,
    output,
    progress,
    translate,
)
from election_map_slovakia.bundle import (
    HEADERS,
    MANIFEST,
    NOT_FOUND,
    WEB_DIR,
    BuildError,
    Part,
    content_version,
    encode,
    tree,
)
from election_map_slovakia.config import Config
from election_map_slovakia.output import format_size

OUTPUT_DIR = "dist"
APP_PART = "app"
"""Below ``dist/``: the app."""
SHELL = "index.html"
PICKER = "picker.html"
I18N_DIR = "i18n"
ASSETS_DIR = "assets"
# In web/ and, each below a version of its own, in ASSETS_DIR: the app's
# code (its directory named by the version), the vendored libraries and the
# images.
APP_CSS = "app.css"
JS_DIR = "js"
VENDOR_DIR = "vendor"
IMAGES_DIR = "img"
# How the modules directly in web/js import the vendored libraries; the
# build points it at the libraries' versioned directory (code_files).
_VENDOR_IMPORT = re.compile(rb"""(["'])\.\./vendor/""")
PARTY_LOGOS = config.PARTY_LOGO_DIR.relative_to(Path(WEB_DIR) / IMAGES_DIR).as_posix()
SITEMAP = "sitemap.xml"
# Also in web/js/i18n.js: the language the visitor last chose.
STORAGE_KEY = "election-map-slovakia.lang"
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
# Comments in the templates are for their maintainers, not for the site.
_COMMENT = re.compile(r"[ \t]*<!--.*?-->\n", re.DOTALL)
_PENDING = "_pending"
_MISSING = "_missing"
_LOCALE = "_locale"
_SITE_NAME_KEY = "app.name"
_SITE = "{site}"


@dataclass(frozen=True)
class Located:
    """An election's bundle, map or data, as the app finds it."""

    url: str
    """Its address: ``/map/<slug>`` or ``/data/<slug>`` served by ``serve``,
    else that of the deployment that carries its key."""
    manifest: dict[str, Any]
    """Its ``manifest.json`` (:mod:`election_map_slovakia.bundle`)."""


@dataclass(frozen=True)
class Locations:
    """Where the app finds the data parts."""

    maps: dict[str, Located]
    """Election slug → its map bundle."""
    data: dict[str, Located]
    """Election slug → its data bundle."""
    results: str
    """The address of the results part, the days below it."""
    sources: str
    """The address of the sources part, ``cache/`` below it (empty: the
    app's own origin)."""

    @property
    def origins(self) -> list[str]:
        """Return the other origins the app fetches from, sorted."""
        urls = [
            *(d.url for d in self.maps.values()),
            *(d.url for d in self.data.values()),
            self.results,
        ]
        return sorted({origin(url) for url in urls if origin(url)})

    def bundles(self) -> Iterator[tuple[str, Located]]:
        """Yield (directory below ``dist/``, bundle) of every bundle."""
        for part, located in (
            (bundle.MAP_PART, self.maps),
            (bundle.DATA_PART, self.data),
        ):
            for slug, one in located.items():
                yield f"{part}/{slug}", one


def origin(url: str) -> str:
    """Return the origin of absolute *url*, empty for a path."""
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else ""


def local_locations(maps: Mapping[str, Part], data: Mapping[str, Part]) -> Locations:
    """Return where ``serve`` serves the parts built with *maps* and *data*."""

    def located(part: str, bundles: Mapping[str, Part]) -> dict[str, Located]:
        return {
            slug: Located(f"/{part}/{slug}", json.loads(b.files[MANIFEST]))
            for slug, b in bundles.items()
        }

    return Locations(
        located(bundle.MAP_PART, maps),
        located(bundle.DATA_PART, data),
        f"/{bundle.RESULTS_PART}",
        "",
    )


@dataclass(frozen=True)
class Site:
    """Everything ``build`` writes: ``dist/`` path → content.

    *copies* are directories and files copied verbatim: ``dist/`` path →
    source.
    """

    files: dict[str, bytes]
    copies: dict[str, Path]
    log: list[str]
    """What ``build`` reports besides the files, e.g. untranslated strings."""

    @classmethod
    def of(cls, parts: Mapping[str, Part], log: list[str]) -> Site:
        """Return the site of *parts*, each by its directory below ``dist/``."""
        return cls(
            {
                f"{d}/{path}": blob
                for d, p in parts.items()
                for path, blob in p.files.items()
            },
            {
                f"{d}/{path}": src
                for d, p in parts.items()
                for path, src in p.copies.items()
            },
            log,
        )


def code_files(web: Path, vendor: str) -> dict[str, bytes]:
    """Return the app's code: path below its directory → content.

    The modules directly in web/js import the vendored libraries from
    ``'../vendor/…'``; that prefix becomes *vendor*, the URL of the
    libraries' versioned directory (``/assets/vendor/<vv>``). A module in a
    subdirectory of js/ would mean another directory by it and is left as
    it is (``check`` reports what it imports if that is missing).
    """
    out = dict(tree(APP_CSS, web / APP_CSS))
    for path, content in tree(JS_DIR, web / JS_DIR):
        flat = path.count("/") == 1
        out[path] = (
            _VENDOR_IMPORT.sub(lambda m: m[1] + f"{vendor}/".encode(), content)
            if flat and path.endswith(".js")
            else content
        )
    return out


@dataclass(frozen=True)
class Strings:
    """The UI strings of every language: what :func:`i18n_files` returns."""

    ui: dict[str, dict[str, Any]]
    """Language → ``i18n/<lang>.json``."""
    log: list[str]
    """Per language, how much of it is translated."""


def hand_written(cfg: Config, web: Path) -> dict[str, dict[str, str]]:
    """Return language → its ``web/i18n/<lang>.json``, checked."""
    langs = cfg.languages
    base_code = langs.fallback[0]
    own = {
        path.stem: json.loads(path.read_bytes())
        for path in sorted((web / I18N_DIR).glob("*.json"))
    }
    for code, strings in own.items():
        if code not in langs.codes:
            raise BuildError(f"web/{I18N_DIR}/{code}.json: not an enabled language")
        if _SITE_NAME_KEY in strings:
            raise BuildError(
                f"web/{I18N_DIR}/{code}.json: {_SITE_NAME_KEY} comes from"
                " languages.toml `site_name`"
            )
    if base_code not in own:
        raise BuildError(f"web/{I18N_DIR}/{base_code}.json missing")
    keys = set(own[base_code])
    for code, strings in own.items():
        if set(strings) != keys:
            diff = sorted(set(strings) ^ keys)
            raise BuildError(
                f"web/{I18N_DIR}/{code}.json: keys differ from {base_code}.json:"
                f" {', '.join(diff[:5])}"
            )
    return own


def _site_names(langs: config.Languages) -> dict[str, str]:
    """Return language → the site's name in it (``languages.toml``)."""
    return {lang.code: lang.site_name for lang in langs.languages}


def i18n_files(cfg: Config, web: Path) -> Strings:
    """Return the UI strings of every language.

    Languages with their own ``web/i18n/<lang>.json`` (:func:`hand_written`)
    must define exactly the keys of the first fallback language; the others
    get the curated translations of its current strings (:mod:`translate`)
    and the rest from it. See the module doc for the ``_`` fields. (The
    occupations of the candidates are translated in each election's bundle,
    :func:`bundle.occupation_files`.)

    The site's name comes from ``languages.toml``: ``{site}`` in a string is
    replaced by the name in the language the string is written in, and
    ``app.name`` (the header) is always the page language's own name.
    """
    langs = cfg.languages
    base_code = langs.fallback[0]
    own = hand_written(cfg, web)
    base = own[base_code]
    site_names = _site_names(langs)
    out = Strings({}, [])
    for code in langs.codes:
        texts = own.get(code) or translate.load(cfg, code).ui_strings(base)
        strings: dict[str, Any] = {
            k: texts[k].replace(_SITE, site_names[code])
            if k in texts
            else v.replace(_SITE, site_names[base_code])
            for k, v in base.items()
        }
        if len(texts) < len(base):
            strings |= {_PENDING: base_code, _MISSING: len(base) - len(texts)}
        if not texts:
            strings[_LOCALE] = base_code
        out.ui[code] = strings | {_SITE_NAME_KEY: site_names[code]}
        if code in own:
            ui = "hand-written"
        else:
            ui = f"{len(texts):,}/{len(base):,}"
            if len(texts) < len(base):
                ui += f" (the rest in {base_code})"
        out.log.append(f"{code}: UI strings {ui}")
    return out


def _fill(template: str, values: Mapping[str, str], name: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group(1) not in values:
            raise BuildError(f"web/{name}: unknown placeholder {match.group(0)}")
        return values[match.group(1)]

    return _PLACEHOLDER.sub(replace, _COMMENT.sub("", template))


def _attribute_json(content: object) -> str:
    return html.escape(encode(content).decode())


def headers(cfg: Config, web: Path, locations: Locations) -> bytes:
    """Return the app's ``_headers``: web/_headers for these *locations*.

    Its CSP lets the app fetch from its own origin and the other origins of
    the data parts (:attr:`Locations.origins`). A noindex rule for
    pages.dev is added once the site has a domain of its own
    (``base_url``): Pages keeps serving every deployment at
    <project>.pages.dev and at <hash>.<project>.pages.dev, and a search
    engine should know the site only by its domain.
    """
    connect = " ".join(["'self'", *locations.origins])
    text = _fill(
        (web / HEADERS).read_text(encoding="utf-8"), {"connect_src": connect}, HEADERS
    )
    base = cfg.site.base_url
    pages = f"{cfg.site.pages_project}.pages.dev"
    if not base or urllib.parse.urlsplit(base).hostname == pages:
        return text.encode()
    return (
        f"{text.rstrip()}\n\n"
        f"# The site's own domain is {base} (config/site.toml base_url).\n"
        f"https://{pages}/*\n  X-Robots-Tag: noindex\n\n"
        f"https://:deployment.{pages}/*\n  X-Robots-Tag: noindex\n"
    ).encode()


def page(cfg: Config, lang: str, election: config.Election) -> str:
    """Return the path of *election*'s page in *lang*, as linked and canonical.

    ``<lang>/`` for the latest election, else ``<lang>/<slug>/``.
    """
    if election.slug == cfg.latest.slug:
        return f"{lang}/"
    return f"{lang}/{election.slug}/"


def sitemap(cfg: Config) -> bytes | None:
    """Return ``sitemap.xml``: the root page and every app shell's page.

    A sitemap lists absolute URLs only, so without ``base_url`` there is
    none. The pages name their other languages themselves (:func:`shells`).
    Each page is listed by its canonical URL (:func:`page`): the latest
    election's ``<lang>/<slug>/`` copy is the same page as ``<lang>/``.
    """
    base = cfg.site.base_url
    if not base:
        return None
    urls = [
        f"{base}/",
        *(
            f"{base}/{page(cfg, code, election)}"
            for election in cfg.elections
            for code in cfg.languages.codes
        ),
    ]
    entries = "".join(f"  <url><loc>{html.escape(u)}</loc></url>\n" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}</urlset>\n"
    ).encode()


@dataclass(frozen=True)
class _Assets:
    """The URLs of the app's versioned directories (module doc)."""

    code: str
    """``/assets/<v>``."""
    vendor: str
    """``/assets/vendor/<vv>``."""
    images: str
    """``/assets/img/<iv>``."""
    strings: str
    """The version of the UI strings, their ``?v=``."""


def shells(
    cfg: Config,
    web: Path,
    strings: Mapping[str, Mapping[str, Any]],
    assets: _Assets,
    locations: Locations,
) -> dict[str, bytes]:
    """Return the app shells, the root language picker and the 404 page.

    One shell per language and election, ``<lang>/<slug>/index.html``, the
    latest election's also as ``<lang>/index.html``, which both name as
    canonical (:func:`page`); each fetches the election's files from its
    bundle in *locations*, with ``?v=`` its version.
    """
    langs = cfg.languages
    site_names = _site_names(langs)
    base = cfg.site.base_url or ""

    def alternates(election: config.Election) -> str:
        return "\n".join(
            f'    <link rel="alternate" hreflang="{code}"'
            f' href="{base}/{page(cfg, code, election)}" />'
            for code in langs.codes
        )

    # Only an absolute URL is a canonical one: with the site's own domain
    # set, search engines file every copy of a page under that domain.
    def canonical(path: str) -> str:
        return f'\n    <link rel="canonical" href="{base}/{path}" />' if base else ""

    template = (web / SHELL).read_text(encoding="utf-8")
    out = {}
    for election in cfg.elections:
        mapped = locations.maps[election.slug]
        # The map's files are what the page fetches first (index.html).
        preconnect = (
            f'\n    <link rel="preconnect" href="{html.escape(origin(mapped.url))}"'
            ' crossorigin="anonymous" />'
            if origin(mapped.url)
            else ""
        )
        config_json = _attribute_json(_app_config(cfg, election, assets, locations))
        links = alternates(election)
        for lang in langs.languages:
            s = strings[lang.code]
            values = {
                "lang": lang.code,
                "dir": lang.direction,
                "title": html.escape(_year(s["app.title"], election)),
                "description": html.escape(_year(s["app.description"], election)),
                "noscript": html.escape(s["app.noscript"]),
                "features": html.escape(_year(s["app.features"], election)),
                "alternates": links,
                "canonical": canonical(page(cfg, lang.code, election)),
                "assets": assets.code,
                "vendor": assets.vendor,
                "map": html.escape(mapped.url),
                "map_version": mapped.manifest["version"],
                "preconnect": preconnect,
                "strings_version": assets.strings,
                "config": config_json,
            }
            shell = _fill(template, values, SHELL).encode()
            out[f"{lang.code}/{election.slug}/index.html"] = shell
            if election.slug == cfg.latest.slug:
                out[f"{lang.code}/index.html"] = shell
    picker_config = {
        "codes": list(langs.codes),
        "aliases": langs.aliases,
        "fallback": list(langs.fallback),
        "storage": STORAGE_KEY,
    }
    links = "\n".join(
        f'      <li><a href="{lang.code}/" hreflang="{lang.code}"'
        f' lang="{lang.code}">{html.escape(lang.name)}</a></li>'
        for lang in langs.languages
    )
    values = {
        # Shown before a language is known: the names in the fallback languages.
        "title": html.escape(" · ".join(site_names[code] for code in langs.fallback)),
        # The page is in the first fallback language (web/picker.html).
        "description": html.escape(
            _year(strings[langs.fallback[0]]["app.description"], cfg.latest)
        ),
        # What the site offers, in each fallback language.
        "features": "\n".join(
            f'    <p lang="{code}">'
            f"{html.escape(_year(strings[code]['app.features'], cfg.latest))}</p>"
            for code in langs.fallback
        ),
        "alternates": alternates(cfg.latest),
        "canonical": canonical(""),
        "config": _attribute_json(picker_config),
        "links": links,
        "assets": assets.code,
    }
    picker = (web / PICKER).read_text(encoding="utf-8")
    out["index.html"] = _fill(picker, values, PICKER).encode()
    not_found = (web / NOT_FOUND).read_text(encoding="utf-8")
    out[NOT_FOUND] = _fill(not_found, {"title": values["title"]}, NOT_FOUND).encode()
    return out


def _year(text: str, election: config.Election) -> str:
    """Return a UI string with ``{year}`` filled in: *election*'s year, its slug."""
    return text.replace("{year}", election.slug)


def _credits(cfg: Config, election: config.Election) -> dict[str, Any] | None:
    """Return what an earlier election's map credits name, None for the latest.

    ``boundaries``: ``[slug, n]`` where it is drawn on a later election's
    boundaries, *n* obce of its own differing
    (:func:`bundle.boundary_changes`), else null; ``osm`` and ``addresses``
    the dates their data are of (``inputs.toml`` ``as_of``), which the
    credits must name.
    """
    if election == cfg.latest:
        return None
    inputs = {i.name: i for i in cfg.inputs.inputs}
    for name in (election.osm, election.addresses):
        if not inputs[name].as_of:
            raise BuildError(
                f"config/inputs.toml: input {name} of the {election.slug} election"
                " needs `as_of`, which its map credits name"
            )
    on = bundle.drawn_on(cfg, election)
    changes = bundle.boundary_changes(cfg.election_dir(election))
    if on != election and changes is None:
        raise BuildError(
            f"{cfg.election_dir(election) / bundle.BOUNDARIES_FILE} missing: the"
            f" {election.slug} election is drawn on the boundaries of {on.slug}"
        )
    return {
        "boundaries": None if changes is None else [on.slug, len(changes["obce"])],
        "osm": inputs[election.osm].as_of,
        "addresses": inputs[election.addresses].as_of,
    }


def _app_config(
    cfg: Config, election: config.Election, assets: _Assets, locations: Locations
) -> dict[str, Any]:
    """Return the ``km-config`` of *election*'s app shells; see :func:`shells`."""
    located = locations.data[election.slug]
    mapped = locations.maps[election.slug]
    return {
        "languages": [[lang.code, lang.name] for lang in cfg.languages.languages],
        "storage": STORAGE_KEY,
        "election": str(election.day),
        # Every election the site shows, newest first, with its kind: the
        # search card lists them under a heading per kind and links to each
        # one's page, /<lang>/<slug>/.
        "elections": [
            {"day": str(e.day), "slug": e.slug, "kind": e.kind} for e in cfg.elections
        ],
        # Where the app fetches the election's files: its map bundle, below
        # which are geo/…, base/…, addr/…, and its data bundle, below which
        # are data/…, i18n/… (bundle.py).
        "map": mapped.url,
        "data": located.url,
        # Day of the regular elections before, of which the office holders
        # and the past turnouts are; null where they are not known.
        "previous": str(election.incumbents.day) if election.incumbents else None,
        # For an election before the latest, the dates and boundaries the
        # map's credits name (:func:`_credits`); null for the latest.
        "credits": _credits(cfg, election),
        # When the polls open and close (ISO 8601 with the offset): the search
        # card shows the voting under way between them.
        "polls": [election.polls_open.isoformat(), election.polls_close.isoformat()],
        # Research language → the source categories it searches: the scope
        # the app states before every research result.
        "research": {
            lang: list(categories) for lang, categories in cfg.sources.research.items()
        },
        "repository": cfg.site.repository,
        # The About dialog names the version, linked to its release.
        "version": __version__,
        # Appended to every file of the election the app fetches (``?v=``):
        # its bundle's version, the map's or the data's.
        "mapVersion": mapped.manifest["version"],
        "dataVersion": located.manifest["version"],
        # Appended to the UI strings (``/i18n/``), which every election
        # shares: switching keeps the browser's copies.
        "stringsVersion": assets.strings,
        # The election's results directory (status.json and the files it
        # names, docs/results.md); nothing there before there are results.
        "results": f"{locations.results}/{election.day.isoformat()}",
        # The cached copies of the pages research cites: <sources>/cache/….
        "sources": locations.sources,
        # The party logos, which data/index.json names by file.
        "logos": f"{assets.images}/{PARTY_LOGOS}",
        # Language → how many of the election's occupations its bundle has
        # not translated into it (i18n/<lang>.json there; none for Slovak,
        # in which they are written): the app says the translation is
        # incomplete where any are not.
        "occupations": located.manifest["occupations"],
        # Whether the app polls them (elections.toml live); without, it reads
        # them once per page load.
        "live": election.live,
        # When, polling, it reads them every minute (ISO 8601); null: any time.
        "liveWindow": [when.isoformat() for when in election.live_window]
        if election.live_window
        else None,
    }


def app(cfg: Config, locations: Locations) -> tuple[Part, list[str]]:
    """Return the app, which finds the data parts at *locations*, and its log.

    The log says how much of each language is translated.
    """
    web = cfg.root / WEB_DIR
    # The libraries are hashed before the code that names their directory.
    vendor, images = (
        f"{ASSETS_DIR}/{name}/{content_version(tree(name, web / name))}"
        for name in (VENDOR_DIR, IMAGES_DIR)
    )
    code = code_files(web, f"/{vendor}")
    strings = i18n_files(cfg, web)
    files = {f"{I18N_DIR}/{code}.json": encode(s) for code, s in strings.ui.items()}
    assets = _Assets(
        f"/{ASSETS_DIR}/{content_version(sorted(code.items()))}",
        f"/{vendor}",
        f"/{images}",
        content_version(sorted(files.items())),
    )
    files |= shells(cfg, web, strings.ui, assets, locations)
    files |= {f"{assets.code[1:]}/{path}": blob for path, blob in code.items()}
    files[HEADERS] = headers(cfg, web, locations)
    site_map = sitemap(cfg)
    if site_map is not None:
        files[SITEMAP] = site_map
    copies = {vendor: web / VENDOR_DIR, images: web / IMAGES_DIR}
    return Part(files, copies), strings.log


def assemble(cfg: Config, keys: lock.Keys | None) -> Site:
    """Return the whole site built from *cfg*'s inputs; see the module doc.

    *keys* are the keys of the data parts (:func:`lock.keys`), which their
    manifests name; None where the repository does not determine them (an
    input not pinned yet).
    """
    maps, data = bundle.bundles(
        cfg, keys.maps if keys else {}, keys.data if keys else {}
    )
    parts = {f"{bundle.MAP_PART}/{slug}": part for slug, part in maps.items()}
    parts |= {f"{bundle.DATA_PART}/{slug}": part for slug, part in data.items()}
    parts[bundle.SOURCES_PART] = bundle.sources_part(
        cfg, keys.sources if keys else None
    )
    parts[bundle.RESULTS_PART] = bundle.results_part(
        cfg, keys.results if keys else None
    )
    parts[APP_PART], log = app(cfg, local_locations(maps, data))
    site = Site.of(parts, log)
    for source in site.copies.values():
        if not source.exists():
            raise BuildError(f"{source} missing")
    return site


def assemble_deployed(cfg: Config, locations: Locations) -> Site:
    """Return the app alone, for the data parts deployed at *locations*.

    With the manifest of each election's bundles, which ``check`` checks
    the app against: ``dist/map/<slug>/manifest.json`` and
    ``dist/data/<slug>/manifest.json`` (module doc).
    """
    part, log = app(cfg, locations)
    parts = {APP_PART: part} | {
        directory: Part({MANIFEST: encode(located.manifest | {"url": located.url})}, {})
        for directory, located in locations.bundles()
    }
    return Site.of(parts, log)


def write(
    site: Site, directory: Path, memo: Path | None = None
) -> dict[str, tuple[int, int]]:
    """Replace *directory* with *site*.

    Returns ``dist/`` path → (bytes, gzip -9 bytes) of every file, the gzip
    sizes kept in *memo* (:func:`election_map_slovakia.output.gzip_sizes`).
    """
    with (
        progress.stage(f"writing {directory.name}/") as s,
        output.replacing(directory) as tmp,
    ):

        def copy(source: str, target: str) -> None:
            shutil.copy2(source, target)
            s.advance()

        for target, source in sorted(site.copies.items()):
            if source.is_dir():
                shutil.copytree(source, tmp / target, copy_function=copy)
            else:
                (tmp / target).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, tmp / target)
                s.advance()
        for path, data in s.track(sorted(site.files.items())):
            out = tmp / path
            if out.exists():
                raise BuildError(f"{path} is both generated and copied")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
    with (
        progress.stage(f"reading {directory.name}/ for the size report") as s,
        ThreadPoolExecutor() as pool,
    ):
        files = sorted(p for p in directory.rglob("*") if p.is_file())
        blobs = list(s.track(pool.map(Path.read_bytes, files)))
    return {
        path.relative_to(directory).as_posix(): (len(data), gz)
        for path, data, gz in zip(
            files, blobs, output.gzip_sizes(blobs, memo), strict=True
        )
    }


_GROUPS = (
    ("data/okres/", "candidates per okres"),
    ("data/kraj/", "candidates per kraj"),
    ("data/city/", "candidates per city"),
    ("data/names/", "name search shards"),
    ("data/research/", "research findings"),
    ("data/index.json", "data/index.json"),
    ("geo/", "geometry"),
    (f"geo/{geo.OKRSKY_DIR}/", "  of it okrsky"),
    (f"{basemap.OUTPUT_DIR}/", "base map"),
    ("addr/", "addresses"),
    (f"{bundle.I18N_DIR}/", "occupations"),
    (f"{bundle.SOURCES_PART}/{bundle.CACHE_DIR}/", "cached pages"),
    (f"{bundle.RESULTS_PART}/", "results"),
    (f"{APP_PART}/{I18N_DIR}/", "UI strings"),
    (f"{APP_PART}/{ASSETS_DIR}/", "assets"),
)


def report(sizes: Mapping[str, tuple[int, int]]) -> Iterator[str]:
    """Yield a summary of the written files: count, bytes, gzip per group.

    The bundles' files are counted together, without their ``map/<slug>/``
    or ``data/<slug>/``; then each part's, which a Pages project limits.
    """
    prefixes = (f"{bundle.MAP_PART}/", f"{bundle.DATA_PART}/")
    files = [
        (p.split("/", 2)[2] if p.startswith(prefixes) else p, s)
        for p, s in sizes.items()
    ]
    bundles = sorted(
        {"/".join(p.split("/")[:2]) for p in sizes if p.startswith(prefixes)}
    )
    parts = [*bundles, APP_PART, bundle.SOURCES_PART, bundle.RESULTS_PART]
    rows = [
        *((prefix, label, files) for prefix, label in _GROUPS),
        *((f"{d}/", f"part {d}", sizes.items()) for d in parts),
        ("", "total", files),
    ]
    yield f"{'':<22} {'files':>6} {'bytes':>11} {'gzip':>11} {'max gzip':>11}"
    for prefix, label, within in rows:
        group = [s for p, s in within if p.startswith(prefix)]
        if not group:
            continue
        yield (
            f"{label:<22} {len(group):>6,} {format_size(sum(s[0] for s in group)):>11}"
            f" {format_size(sum(s[1] for s in group)):>11}"
            f" {format_size(max(s[1] for s in group)):>11}"
        )


@dataclass(frozen=True)
class HeaderRule:
    """One rule of a ``_headers`` file."""

    pattern: re.Pattern[str]
    headers: tuple[tuple[str, str], ...]
    detach: tuple[str, ...]


_PATTERN_PART = re.compile(r"(\*)|:[A-Za-z]\w*")


def _url_pattern(url: str) -> re.Pattern[str]:
    parts, end = [], 0
    for m in _PATTERN_PART.finditer(url):
        parts += [re.escape(url[end : m.start()]), ".*" if m.group(1) else "[^/]+"]
        end = m.end()
    return re.compile("".join([*parts, re.escape(url[end:])]))


def header_rules(text: str) -> list[HeaderRule]:
    """Parse a Cloudflare Pages ``_headers`` file.

    A rule is an unindented URL pattern (``*`` splat, ``:name``
    placeholder) followed by indented ``Name: value`` lines and ``! Name``
    lines that remove a header set by an earlier rule. Absolute URL
    patterns (``https://host/path``) are kept but never match a path.
    """
    rules: list[tuple[str, list[tuple[str, str]], list[str]]] = []
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[0].isspace():
            rules.append((stripped, [], []))
            continue
        if not rules:
            raise BuildError(f"{HEADERS}:{n}: header before any URL pattern")
        _, added, removed = rules[-1]
        if stripped.startswith("!"):
            removed.append(stripped[1:].strip())
            continue
        name, colon, value = stripped.partition(":")
        if not colon or not name.strip():
            raise BuildError(f"{HEADERS}:{n}: expected `Name: value`")
        added.append((name.strip(), value.strip()))
    return [
        HeaderRule(_url_pattern(url), tuple(added), tuple(removed))
        for url, added, removed in rules
    ]


def response_headers(rules: list[HeaderRule], path: str) -> dict[str, str]:
    """Return the headers *rules* add to the response for URL *path*.

    As on Pages, every matching rule applies, and a header set by several
    gets their values joined by a comma.
    """
    out: dict[str, tuple[str, str]] = {}
    for rule in rules:
        if not rule.pattern.fullmatch(path):
            continue
        for name in rule.detach:
            out.pop(name.lower(), None)
        for name, value in rule.headers:
            key = name.lower()
            if key in out:
                value = f"{out[key][1]}, {value}"
            out[key] = (name, value)
    return dict(out.values())


def mounts(dist: Path) -> list[tuple[str, Path]]:
    """Return (URL path prefix, directory) of each part of *dist* as one site.

    As ``serve`` serves them, and as the app built without ``--deployed``
    finds them (:func:`local_locations`): each bundle at ``/map/<slug>/`` or
    ``/data/<slug>/``, the results at ``/results/``, the app at the root and
    the sources there too, below it (its ``cache/`` and
    ``assets/cache.css`` are no paths of the app's). Parts not built,
    without their ``_headers``, are left out.
    """
    candidates = [
        (f"/{part}/{d.name}/", d)
        for part in (bundle.MAP_PART, bundle.DATA_PART)
        if (dist / part).is_dir()
        for d in sorted((dist / part).iterdir())
    ]
    candidates += [
        (f"/{bundle.RESULTS_PART}/", dist / bundle.RESULTS_PART),
        ("/", dist / APP_PART),
        ("/", dist / bundle.SOURCES_PART),
    ]
    return [(prefix, d) for prefix, d in candidates if (d / HEADERS).is_file()]


def locate(parts: list[tuple[str, Path]], path: str) -> tuple[int, str] | None:
    """Return which of *parts* (:func:`mounts`) URL *path* is in, and its path there.

    The first part whose prefix it starts with and which has the file; a
    part of its own prefix has it or nothing does; at the root, the first
    part (the app) where none has it. None if no prefix matches.
    """
    first = None
    for i, (prefix, directory) in enumerate(parts):
        if not path.startswith(prefix):
            continue
        sub = "/" + path[len(prefix) :]
        first = first or (i, sub)
        target = directory / sub.lstrip("/")
        if sub.endswith("/"):
            target /= "index.html"
        # Pages reads _headers but does not serve it.
        if (sub != f"/{HEADERS}" and target.is_file()) or prefix != "/":
            return i, sub
    return first


class _Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".json": "application/json",
        ".svg": "image/svg+xml",
    }

    def __init__(
        self,
        *args: Any,
        parts: list[tuple[str, Path]],
        rules: list[list[HeaderRule]],
        **kwargs: Any,
    ) -> None:
        # The base class handles the request inside __init__; until it
        # locates the path, the root part (the app) answers.
        self.parts = parts
        self.rules = rules
        self.part = next(i for i, (prefix, _) in enumerate(parts) if prefix == "/")
        self.sub = "/"
        super().__init__(*args, **kwargs)

    def send_head(self) -> Any:
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        located = locate(self.parts, path)
        if located is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        self.part, self.sub = located
        if self.sub == f"/{HEADERS}":
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        return super().send_head()

    def translate_path(self, path: str) -> str:
        return str(self.parts[self.part][1] / self.sub.lstrip("/"))

    def list_directory(self, path: Any) -> None:
        # Pages lists no directories; a directory without index.html is
        # missing like any other path.
        self.send_error(HTTPStatus.NOT_FOUND)

    def send_error(
        self, code: int, message: str | None = None, explain: str | None = None
    ) -> None:
        # Pages answers a missing path with the part's 404.html and status 404.
        if code != HTTPStatus.NOT_FOUND:
            super().send_error(code, message, explain)
            return
        body = (self.parts[self.part][1] / NOT_FOUND).read_bytes()
        self.send_response(code, message)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def end_headers(self) -> None:
        for name, value in response_headers(self.rules[self.part], self.sub).items():
            self.send_header(name, value)
        super().end_headers()


def serve(dist: Path, host: str, port: int) -> None:
    """Serve the parts in *dist* as one site over HTTP until interrupted.

    Where :func:`mounts` puts them; each part's responses carry the headers
    of its ``_headers``, so local tests see the same Content-Security-Policy
    and caching as the deployed site.
    """
    parts = mounts(dist)
    rules = [
        header_rules((directory / HEADERS).read_text(encoding="utf-8"))
        for _, directory in parts
    ]
    handler = functools.partial(_Handler, parts=parts, rules=rules)
    with ThreadingHTTPServer((host, port), handler) as httpd:
        print(f"serving {dist} at http://{host}:{httpd.server_port}/")
        httpd.serve_forever()
