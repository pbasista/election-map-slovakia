"""Assemble the static site in ``dist/`` and serve it for local testing.

``build`` wipes ``dist/`` and writes it from ``web/`` (the frontend source),
``data/build/`` (output of ``candidates``, ``geo`` and ``addresses``) and the
configuration. Every file is a pure function of those inputs, so two builds
from the same inputs are byte for byte identical.

Output (paths relative to ``dist/``; JSON is compact UTF-8 with sorted
keys)::

    index.html               language picker: stored choice, then
                             navigator.languages (aliases applied), then the
                             first fallback language
    404.html                 what Pages (and ``serve``) answers a missing path
                             with, status 404; from web/404.html
    <lang>/index.html        app shell per enabled language, from
                             web/index.html
    _headers                 Cloudflare Pages response headers, from
                             web/_headers (see :func:`header_rules`), plus
                             a noindex rule for the pages.dev hosts once the
                             site has a domain of its own (:func:`headers`)
    sitemap.xml              the root page and every language's app shell,
                             absolute under ``base_url``; none without it
                             (:func:`sitemap`)
    assets/<v>/              web/app.css and web/js/; <v> is the code
                             version (below), and the modules import the
                             vendored libraries from assets/vendor/<vv>/
                             (:func:`code_files`)
    assets/vendor/<vv>/      web/vendor/, verbatim; <vv> its version
    assets/img/<iv>/         web/img/ (party logos), verbatim; <iv> its
                             version
    assets/cache.css         web/cache.css, unversioned: the cached copies
                             link it by this path (cache.py STYLESHEET)
    i18n/<lang>.json         UI strings: web/i18n/<lang>.json, or for other
                             languages the curated translations of the
                             current strings of the first fallback language
                             (translate.py), the rest taken from it. If a
                             UI string or an occupation is untranslated,
                             "_pending" is that language's code (the app
                             shows a notice) and "_missing" {ui,
                             occupations} the counts; "_locale" is it too if
                             no UI string is translated (the app formats
                             dates and numbers in it); "_occupations" is the
                             number of translated occupations, if any.
                             `{site}` in a string becomes the site name of the
                             language the string is written in; "app.name" is
                             the page language's own site name (languages.toml)
    i18n/<lang>/occupations.json
                             {Slovak occupation: translation} for the
                             occupations of the candidate files translated
                             into <lang> (one file per language, ~0.5 MB,
                             ~0.15 MB gzip when complete; the app fetches it
                             once with the first candidates it shows)
    geo/                     data/build/geo/, verbatim (see geo)
    addr/                    data/build/addr/, verbatim (see addresses)
    data/index.json          names and facts every view needs (below)
    data/about.json          source allowlist, inputs, obvod decisions
    data/okres/<okres>.json  candidates of the municipal contests of the
                             obce (and Bratislava/Košice districts) of an
                             okres
    data/city/<BA|KE>.json   candidates for mayor and city council
    data/kraj/<kraj>.json    candidates for regional president and council
    data/names/<xx>.json     candidate-name search shard
    data/research/<lang>/<area>.json
                             the research findings of the persons of the
                             area file data/<area>.json, in <lang>
                             (:func:`research_files`)
    cache/<sha256>.html      the cached copy of every page a finding cites,
                             from data/curated/cache/ (see cache.py)

Cache busting. The code, the vendored libraries and the images each live
under a directory named by a short hash of their files
(:func:`content_version`): ``/assets/<v>/``, ``/assets/vendor/<vv>/`` and
``/assets/img/<iv>/``. A release that changes a file of one moves that
tree to new URLs, which browsers may keep for good (``immutable`` in
web/_headers), and a release that changes none of a tree keeps its URLs
and the browsers' copies: the libraries, which change only with a
deliberate upgrade, and the logos outlast changes to the app's code. The
app's modules import each other by relative paths, so they need not know
``<v>``; their imports of the libraries (``'../vendor/…'`` in web/js, which
keeps web/ runnable as it is) are rewritten to ``/assets/vendor/<vv>/``,
and ``<v>`` is the hash of the rewritten files, so a library upgrade is new
code too. The JSON the app fetches at runtime (``data/``, ``i18n/``,
``geo/``, ``addr/``) keeps its paths and is requested with ``?v=<dv>``,
the data version: a short hash of all of those files. A browser's copy
then belongs to the version it was fetched for and a release with other
data makes the app ask for new URLs. ``data/index.json`` names the party
logos under ``/assets/img/<iv>/``, so new images are a new data version
too, and new code is not. The app shells carry the data version in the
``km-config`` meta JSON (:func:`shells`) as ``dataVersion``, and ``live``,
the live results origin (``live_url``, see
:mod:`election_map_slovakia.config`), which the CSP's connect-src in
``_headers`` allows (:func:`headers`).

Each contest is in exactly one area file, so a click loads the okres, kraj
and (in Bratislava and Košice) city file of one place and nothing twice::

    data/<area>.json  {contests: {contest: {(seats), (sources), (holder),
                          (incumbents), (past), candidates: [
                          [number, title_before, first_name, surname,
                           title_after, age, occupation, [party, ...],
                           person, (residence)]]}},
                       persons: {person: [candidacy, ...]},
                       (research): {person: [date, findings,
                                             [language, ...], affairs,
                                             disputes]}}

``persons`` lists, for every person with a candidacy in the file who stands
in more than one contest, all their candidacies (in any file). ``seats`` is
known for regional and city council obvody and the obvody of obce with a
rule set; a council elected in one obvod without it has ``seats_2022``, the
number its whole council elected in 2022, as a stand-in until the 2026
number is known (councils of several obvody have neither: a 2022 total
says nothing about one obvod). ``sources`` are the official
documents that set a council's obvody, as ``[title, url]`` (title possibly
empty; :func:`obvod_sources`). ``residence`` is the obec of residence of
regional candidates. ``holder`` is the mayor or regional president in
office, ``[name, since, number, result]`` (``number`` the holder's ballot
number in this contest, or null); ``incumbents`` maps the ballot number of
every candidate in office now to their offices, ``[[body, since, result],
...]``, a body being a contest id without the obvod (see
:mod:`election_map_slovakia.incumbents`). ``result`` is how the office was
won, ``[votes, valid, voters, eligible, (obvod)]``: the holder's votes, the
valid ballots for that office (for a council: the voters with a valid
ballot, each of whom could vote for several), the voters who took part and
those on the roll, in the unit it was won in, the municipality, kraj or
``obvod`` (its number in that election) of the body's area.
``past`` is the turnout of the last election of the contest's body,
``[election, day, eligible, voters, (1)]``: the results input without
``results-`` (``oso2022``, ``osk2022``, ``oso202303``, …), its ISO day, the
voters on the roll and those who took part, in the whole municipality,
city or kraj, or for a regional council contest in the obce that make up
its 2026 obvod (:func:`regional_past`); see
:mod:`election_map_slovakia.candidates` for which election. The trailing
``1`` marks a council of several obvody in 2026: its figures are of the
whole municipality or city, the 2022 obvody being different.
``research`` summarizes, for each researched person of the file, when (the
latest date) and in which research languages they were researched and how
many findings there are (:func:`research_summary`); a person without an
entry is not researched yet.

::

    data/index.json  {kraje: {kraj: name},
                      okresy: {okres: [name, kraj]},
                      obce: {obec: [name, okres, kraj, zsk, councils,
                                    (city, city_obvod)]},
                      by_address: [obec, ...],
                      estimated: [obec, ...],
                      names: {prefix: persons},
                      parties: {party: [short, name, (logo)]}}

``councils`` is the number of municipal council obvody (0: no council
election); ``by_address`` lists the obce whose council obvod goes by
address (``addresses``: ``council`` ``"address"``) and whose shard
features are their obvody (``geo``); ``estimated`` those of them whose
rule set is a guess (``geo``: ``estimated``);
``okres`` is ``""`` and ``zsk`` 0 for Bratislava and Košice
themselves. A name shard holds every person with a name word (first name or
surname, :func:`election_map_slovakia.candidates.search_key`) starting with its two-letter
prefix, as ``[name, age, [candidacy, ...]]`` sorted by surname, the name and
age being those of the person's first candidacy; ``names`` maps each prefix
to its person count, so the search picks the smallest shard among the words
of a query. ``parties`` gives every party named in a candidacy its short
form, official name and logo (``config/parties.toml``; the logo a path under
``/assets/img/<iv>/``).
"""

from __future__ import annotations

import functools
import hashlib
import html
import itertools
import json
import re
import shutil
import urllib.parse
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from election_map_slovakia import (
    __version__,
    addresses,
    cache,
    candidates,
    config,
    geo,
    obvody,
    output,
    progress,
    research,
    translate,
)
from election_map_slovakia.config import Config
from election_map_slovakia.output import format_size

OUTPUT_DIR = "dist"
WEB_DIR = "web"
SHELL = "index.html"
PICKER = "picker.html"
NOT_FOUND = "404.html"
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
# In web/; copied unversioned to cache.STYLESHEET, the path the cached
# copies link, fixed in each copy when it was cached.
CACHE_STYLESHEET = "cache.css"
# Hex digits of the asset and data versions: 40 bits, so two releases
# sharing a version by chance is not a concern.
VERSION_DIGITS = 10
CACHE_DIR = "cache"
"""Below ``dist/``: the cached copies of the pages research cites."""
PARTY_LOGOS = config.PARTY_LOGO_DIR.relative_to(Path(WEB_DIR) / IMAGES_DIR).as_posix()
HEADERS = "_headers"
SITEMAP = "sitemap.xml"
PREFIX = 2
MANIFEST = "manifest.json"
# Also in web/js/i18n.js: the language the visitor last chose.
STORAGE_KEY = "election-map-slovakia.lang"
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
# Comments in the templates are for their maintainers, not for the site.
_COMMENT = re.compile(r"[ \t]*<!--.*?-->\n", re.DOTALL)
_BLOCKLIST_DATE = re.compile(r"retrieved (\d{4}-\d{2}-\d{2})")
_PENDING = "_pending"
_MISSING = "_missing"
_LOCALE = "_locale"
_OCCUPATIONS = "_occupations"
_SITE_NAME_KEY = "app.name"
_SITE = "{site}"


class BuildError(Exception):
    """An input of the site is missing or inconsistent."""


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


def encode(content: object) -> bytes:
    """Return *content* as compact, key-sorted UTF-8 JSON."""
    return output.to_json(content, sort_keys=True)


def tree(name: str, source: Path) -> Iterator[tuple[str, bytes]]:
    """Yield (path, content) of the file or directory tree *source*.

    A path is *name* for a file, else *name*/<path below *source*>, in
    sorted order, so that :func:`content_version` sees a stable sequence.
    """
    if not source.exists():
        raise BuildError(f"{source} missing")
    if source.is_file():
        yield name, source.read_bytes()
        return
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        yield f"{name}/{path.relative_to(source).as_posix()}", path.read_bytes()


def content_version(files: Iterable[tuple[str, bytes]]) -> str:
    """Return a short hash of the (path, content) pairs *files*, in order.

    Paths count as well as contents: a file renamed is a new version.
    """
    digest = hashlib.sha256()
    for path, content in files:
        digest.update(f"{path}\0{len(content)}\0".encode())
        digest.update(content)
    return digest.hexdigest()[:VERSION_DIGITS]


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


def area_file(contest: Mapping[str, Any], okres_of: Mapping[str, str]) -> str:
    """Return the ``dist/`` path of the area file holding *contest*.

    *okres_of* maps obec codes to their okres.
    """
    area = str(contest["area"])
    if contest["kind"] in ("predseda", "zsk"):
        return f"data/kraj/{area}.json"
    if area in candidates.CITY_CODES:
        return f"data/city/{area}.json"
    return f"data/okres/{okres_of[area]}.json"


def _result_row(r: Mapping[str, int]) -> list[int]:
    row = [r["votes"], r["valid"], r["voters"], r["eligible"]]
    if "obvod" in r:
        row.append(r["obvod"])
    return row


def _candidate_row(c: Mapping[str, Any]) -> list[Any]:
    row = [
        c["number"],
        c["title_before"],
        c["first_name"],
        c["surname"],
        c["title_after"],
        c["age"],
        c["occupation"],
        c["parties"],
        c["person"],
    ]
    if "residence" in c:
        row.append(c["residence"])
    return row


def area_files(
    data: Mapping[str, Any],
    seats: Mapping[str, int],
    sources: Mapping[str, list[list[str]]] | None = None,
    researched: Mapping[str, list[Any]] | None = None,
    regional: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return the candidate area files; see the module doc.

    *data* is ``candidates.json``; *seats* maps obvod contests to their seat
    count where known; *sources* is :func:`obvod_sources`; *researched* maps
    persons to their research summary (:func:`research_summary`); *regional*
    is :func:`regional_past`.
    """
    sources = sources or {}
    researched = researched or {}
    regional = regional or {}
    okres_of = {o["code"]: o.get("okres", "") for o in data["obce"]}
    files: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"contests": {}, "persons": {}}
    )
    path_of: dict[str, str] = {}
    council_obvody = Counter(c["area"] for c in data["contests"] if c["kind"] == "oz")
    for contest in data["contests"]:
        path = path_of[contest["id"]] = area_file(contest, okres_of)
        files[path]["contests"][contest["id"]] = _contest_entry(
            contest,
            seats,
            sources,
            regional.get(contest["id"]),
            single=council_obvody[contest["area"]] == 1,
        )
    by_person: dict[str, list[str]] = defaultdict(list)
    for c in data["candidacies"]:
        by_person[c["person"]].append(c["id"])
    for c in sorted(data["candidacies"], key=lambda c: (c["contest"], c["number"])):
        path = path_of[c["contest"]]
        entry = files[path]["contests"][c["contest"]]
        entry["candidates"].append(_candidate_row(c))
        if "incumbent" in c:
            entry.setdefault("incumbents", {})[str(c["number"])] = [
                [office["body"], office["since"], _result_row(office["result"])]
                for office in c["incumbent"]
            ]
        if len(by_person[c["person"]]) > 1:
            files[path]["persons"][c["person"]] = by_person[c["person"]]
        if c["person"] in researched:
            files[path].setdefault("research", {})[c["person"]] = researched[
                c["person"]
            ]
    return dict(files)


def _contest_entry(
    contest: Mapping[str, Any],
    seats: Mapping[str, int],
    sources: Mapping[str, list[list[str]]],
    regional: Mapping[str, Any] | None,
    *,
    single: bool,
) -> dict[str, Any]:
    """Return a contest's entry of an area file, without its candidates.

    *regional* is the contest's :func:`regional_past`, if any; *single*: the
    contest's council (if it is one) is elected in one obvod.
    """
    entry: dict[str, Any] = {"candidates": []}
    if contest["id"] in seats:
        entry["seats"] = seats[contest["id"]]
    elif "seats_2022" in contest and single:
        # 2022 counts are per whole council: comparable only to a single obvod.
        entry["seats_2022"] = contest["seats_2022"]
    documents = sources.get(_sources_key(contest))
    if documents:
        entry["sources"] = documents
    if "incumbent" in contest:
        holder = contest["incumbent"]
        number = holder["candidacy"] and int(holder["candidacy"].split("#")[1])
        entry["holder"] = [
            holder["name"],
            holder["since"],
            number,
            _result_row(holder["result"]),
        ]
    past = contest.get("past", regional)
    if past is not None:
        entry["past"] = [
            past["election"],
            past["day"],
            past["eligible"],
            past["voters"],
        ]
        if contest["kind"] == "oz" and not single:
            entry["past"].append(1)
    return entry


def research_summary(cfg: Config, records: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Return person → ``[date, findings, [language, ...], affairs, disputes]``.

    *records* maps persons to their curated research (:mod:`research`). The
    date is the latest a category was researched, the languages those of
    ``[research]`` in ``sources.toml`` whose every category is researched,
    *affairs* how many of the findings are serious controversies, which the
    ballots flag, and *disputes* how many are disputed or lesser ones.
    """
    out = {}
    for person, record in records.items():
        seen = record["researched"]
        languages = [
            lang
            for lang, categories in cfg.sources.research.items()
            if all(c in seen for c in categories)
        ]
        if not languages:
            continue
        kinds = Counter(f["kind"] for f in record["findings"])
        out[person] = [
            max(s["date"] for s in seen.values()),
            len(record["findings"]),
            languages,
            kinds["affair"],
            kinds["dispute"],
        ]
    return out


def research_files(
    cfg: Config,
    data: Mapping[str, Any],
    records: Mapping[str, Any],
    translations: Mapping[str, Mapping[str, str]],
) -> dict[str, dict[str, list[list[Any]]]]:
    """Return the findings files, ``data/research/<lang>/<area>.json``.

    Each holds, for the persons with findings who stand in a contest of the
    area file ``data/<area>.json``, their findings as ``[kind, claim, quote,
    quote translated or null, url, title, published, cache, category,
    language]``: the claim in the file's language (English where it is not
    translated yet), the quote as written plus its translation into the
    file's language where the page is in another one. *translations* maps
    language → its curated research translations (:mod:`translate`).
    """
    okres_of = {o["code"]: o.get("okres", "") for o in data["obce"]}
    contest_of = {c["id"]: c for c in data["contests"]}
    areas: dict[str, set[str]] = defaultdict(set)
    for c in data["candidacies"]:
        if records.get(c["person"], {}).get("findings"):
            path = area_file(contest_of[c["contest"]], okres_of)
            areas[path.removeprefix("data/")].add(c["person"])
    files: dict[str, dict[str, list[list[Any]]]] = {}
    for lang in cfg.languages.codes:
        own = translations.get(lang, {})
        for area, persons in sorted(areas.items()):
            files[f"data/research/{lang}/{area}"] = {
                person: [
                    [
                        f["kind"],
                        f["claim"].get(lang)
                        or own.get(f["claim"]["en"])
                        or f["claim"]["en"],
                        f["quote"],
                        None if f["language"] == lang else own.get(f["quote"]),
                        f["url"],
                        f["title"],
                        f["published"],
                        f["cache"],
                        f["category"],
                        f["language"],
                    ]
                    for f in records[person]["findings"]
                ]
                for person in sorted(persons)
            }
    return files


def research_records(cfg: Config) -> dict[str, Any]:
    """Return person → curated research record, of every researched person."""
    root = cfg.curated_dir / research.CURATED_DIR
    return {
        path.stem: json.loads(path.read_bytes())
        for path in sorted(root.glob("*/*.json"))
    }


def obec_props(geo_dir: Path) -> dict[str, dict[str, Any]]:
    """Return obec → its properties in the coarsest ``geo`` shard."""
    coarsest = geo.SHARD_LODS[0].level
    props = {}
    for path in sorted((geo_dir / "okres").glob(f"*/{coarsest}.json")):
        for feature in json.loads(path.read_bytes())["features"]:
            props[feature["properties"]["id"]] = feature["properties"]
    return props


def regional_past(
    data: Mapping[str, Any], props: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Return regional council contest → its ``past``, as in ``candidates.json``.

    The obce's 2022 figures (``candidates.json``) summed over the 2026 obvod
    each is in (*props*, :func:`obec_props`): the 2022 obvody were different.
    """
    out: dict[str, dict[str, Any]] = {}
    for o in data["obce"]:
        if "past" in o:
            past = o["past"]
            contest = f"zsk:{o['kraj']}/{props[o['code']]['zsk']}"
            total = out.setdefault(contest, {**past, "eligible": 0, "voters": 0})
            total["eligible"] += past["eligible"]
            total["voters"] += past["voters"]
    return out


def obvod_seats(geo_dir: Path, curated: Path) -> dict[str, int]:
    """Return obvod contest → seats, where known.

    Regional and city council obvody from ``geo``; the council obvody of the
    obce with a rule set from it.
    """
    coarse = json.loads((geo_dir / geo.COARSE_FILE).read_bytes())
    seats = {o["id"]: o["seats"] for o in coarse["obvody"]}
    for code, rules in obvody.load_rule_sets(curated).items():
        seats |= {f"oz:{code}/{n}": s for n, s in rules.seats.items()}
    return seats


def _sources_key(contest: Mapping[str, Any]) -> str:
    """Return the :func:`obvod_sources` area of *contest* ("" for none)."""
    if contest["kind"] == "zsk":
        return f"zsk-{contest['area']}"
    return str(contest["area"]) if contest["kind"] == "oz" else ""


def obvod_sources(curated: Path) -> dict[str, list[list[str]]]:
    """Return area → the official documents that set its obvody.

    Areas are an obec (council obvody by address), ``BA``/``KE`` (city
    council) or ``zsk-<kraj>`` (regional council), as named by the curated
    files; documents are ``[title, url]``, the title empty where the curated
    file records none.
    """
    out = {
        path.stem: [["", config.load_obvody(path).source]]
        for path in sorted((curated / "obvody").glob("*.toml"))
    }
    for code, rules in obvody.load_rule_sets(curated).items():
        out[code] = [[d.title, d.url] for d in rules.documents]
    return out


def site_index(
    data: Mapping[str, Any],
    props: Mapping[str, Mapping[str, Any]],
    shards: Mapping[str, list[Any]],
    parties: Mapping[str, config.Party],
    images: str,
) -> dict[str, Any]:
    """Return ``data/index.json``; see the module doc.

    *images* is the URL of the versioned image directory,
    ``/assets/img/<iv>``.
    """
    named = {p for c in data["candidacies"] for p in c["parties"]}
    if missing := sorted(named - parties.keys()):
        raise BuildError(
            f"config/{config.PARTIES_FILE}: no entry for {', '.join(missing)}"
        )
    councils = addresses.council_obvody(data["contests"])
    obce = {}
    for o in data["obce"]:
        code = o["code"]
        n = len(councils.get(code, ()))
        if code in candidates.CITY_CODES:
            obce[code] = [o["name"], "", o["kraj"], 0, n]
            continue
        if code not in props:
            raise BuildError(f"obec {code} {o['name']} has no geometry")
        p = props[code]
        row = [o["name"], o["okres"], o["kraj"], p["zsk"], n]
        if "city" in p:
            row += [p["city"], p["city_obvod"]]
        obce[code] = row
    return {
        "kraje": {k["code"]: k["name"] for k in data["kraje"]},
        "okresy": {o["code"]: [o["name"], o["kraj"]] for o in data["okresy"]},
        "obce": obce,
        "by_address": sorted({c for c, p in props.items() if "oz" in p}),
        "estimated": sorted({c for c, p in props.items() if "estimated" in p}),
        "names": {prefix: len(rows) for prefix, rows in shards.items()},
        "parties": {
            name: [p.short, p.name]
            + ([f"{images}/{PARTY_LOGOS}/{p.logo}"] if p.logo else [])
            for name, p in sorted(parties.items())
            if name in named
        },
    }


def name_shards(data: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Return name prefix → its shard; see the module doc."""
    persons: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for c in data["candidacies"]:
        persons[c["person"]].append(c)
    shards: dict[str, list[tuple[str, list[Any]]]] = defaultdict(list)
    for cs in persons.values():
        first = cs[0]
        name = f"{first['first_name']} {first['surname']}"
        key = candidates.search_key(name)
        order = f"{candidates.search_key(first['surname'])} {key}"
        entry = [name, first["age"], [c["id"] for c in cs]]
        prefixes = {w[:PREFIX] for w in key.split() if len(w) >= PREFIX}
        # A word that is not plain ASCII after search_key cannot be typed on
        # a Latin keyboard anyway (one surname in the 2026 lists is spelled
        # with Cyrillic ӧ); the person stays findable by their other words.
        for prefix in sorted(p for p in prefixes if p.isascii() and p.isalnum()):
            shards[prefix].append((order, entry))
    return {
        p: [entry for _, entry in sorted(rows)] for p, rows in sorted(shards.items())
    }


def blocklist_date(path: Path) -> str:
    """Return the retrieval date written in the header of the blocklist."""
    match = _BLOCKLIST_DATE.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise BuildError(f"{path}: no 'retrieved YYYY-MM-DD' in the header")
    return match.group(1)


def about(
    cfg: Config,
    manifest: Mapping[str, Any],
    data: Mapping[str, Any],
    records: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``data/about.json``: what the About dialog lists from the config.

    *manifest* is ``data/raw/manifest.json`` (empty if missing); inputs it
    records carry their retrieval date. *data* is ``candidates.json``, for
    the names of the areas of the curated obvod files. *records* is the
    curated research (:func:`research_records`), counted per research
    language: candidates researched and those with findings.
    """
    records = records or {}
    recorded = manifest.get("inputs", {})
    inputs = [
        {"name": i.name, "url": i.url}
        | (
            {"retrieved": recorded[i.name]["retrieved_at"][:10]}
            if i.name in recorded
            else {}
        )
        for i in cfg.inputs.inputs
    ]
    names = {f"zsk-{k['code']}": k["name"] for k in data["kraje"]}
    names |= {
        o["code"]: o["name"] for o in data["obce"] if o["code"] in candidates.CITY_CODES
    }
    membership = []
    for path in sorted((cfg.curated_dir / "obvody").glob("*.toml")):
        listed = config.load_obvody(path)
        if path.stem not in names:
            raise BuildError(f"{path}: no kraj or city named {path.stem!r}")
        membership.append(
            {
                "kind": "zsk" if path.stem.startswith("zsk-") else "city",
                "name": names[path.stem],
                "source": listed.source,
                "date": str(listed.date),
            }
        )
    council = [
        {
            "name": rules.name,
            "sources": [d.url for d in rules.documents],
            "date": str(rules.date) if rules.date else None,
        }
        for rules in sorted(
            obvody.load_rule_sets(cfg.curated_dir).values(),
            key=lambda r: (candidates.search_key(r.name), r.obec),
        )
    ]
    sources = cfg.sources
    return {
        "sources": {
            # Pairs, not an object: the keys of encode() are sorted, and the
            # categories keep the order of sources.toml.
            "categories": list(sources.categories.items()),
            "references": sources.references,
            "exclude": {
                "host_labels": sources.exclude_host_labels,
                "path_segments": sources.exclude_path_segments,
            },
            "blocklist": {
                "date": blocklist_date(cfg.root / "config" / sources.blocklist_file),
                "hosts": len(sources.blocklist),
            },
        },
        "inputs": inputs,
        # Some logos are licensed CC BY(-SA), which requires naming the
        # author and license wherever they are shown.
        "logos": [
            {"name": p.short, "source": p.logo_source, "license": p.logo_license}
            for p in sorted(cfg.parties.values(), key=lambda p: p.short.casefold())
            if p.logo
        ],
        "obvody": membership,
        "council": council,
        "research": [
            [
                lang,
                list(categories),
                sum(
                    all(c in r["researched"] for c in categories)
                    for r in records.values()
                ),
                sum(
                    any(f["category"] in categories for f in r["findings"])
                    for r in records.values()
                ),
            ]
            for lang, categories in sources.research.items()
        ],
    }


@dataclass(frozen=True)
class Strings:
    """The texts of every language: what :func:`i18n_files` returns."""

    ui: dict[str, dict[str, Any]]
    """Language → ``i18n/<lang>.json``."""
    occupations: dict[str, dict[str, str]]
    """Language → ``i18n/<lang>/occupations.json``, where it has any."""
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


def i18n_files(cfg: Config, web: Path, occupations: Collection[str]) -> Strings:
    """Return the UI strings and occupations of every language.

    Languages with their own ``web/i18n/<lang>.json`` (:func:`hand_written`)
    must define exactly the keys of the first fallback language; the others
    get the curated translations of its current strings (:mod:`translate`)
    and the rest from it. *occupations* are those of the candidate files, in
    Slovak, which every other language gets where translated. See the module
    doc for the ``_`` fields.

    The site's name comes from ``languages.toml``: ``{site}`` in a string is
    replaced by the name in the language the string is written in, and
    ``app.name`` (the header) is always the page language's own name.
    """
    langs = cfg.languages
    base_code = langs.fallback[0]
    own = hand_written(cfg, web)
    base = own[base_code]
    site_names = {lang.code: lang.site_name for lang in langs.languages}
    out = Strings({}, {}, [])
    for code in langs.codes:
        curated = translate.load(cfg, code)
        texts = own.get(code) or curated.ui_strings(base)
        strings: dict[str, Any] = {
            k: texts[k].replace(_SITE, site_names[code])
            if k in texts
            else v.replace(_SITE, site_names[base_code])
            for k, v in base.items()
        }
        # Occupations are written in Slovak.
        needed = () if code == translate.REFERENCE else occupations
        translated = {
            o: curated.occupations[o] for o in needed if o in curated.occupations
        }
        missing = {
            "ui": len(base) - len(texts),
            "occupations": len(needed) - len(translated),
        }
        if any(missing.values()):
            strings |= {_PENDING: base_code, _MISSING: missing}
        if not texts:
            strings[_LOCALE] = base_code
        if translated:
            strings[_OCCUPATIONS] = len(translated)
            out.occupations[code] = translated
        out.ui[code] = strings | {_SITE_NAME_KEY: site_names[code]}
        if needed:
            ui = f"{len(texts):,}/{len(base):,}"
            if code in own:
                ui = "hand-written"
            elif len(texts) < len(base):
                ui += f" (the rest in {base_code})"
            coverage = f"{len(translated):,}/{len(needed):,}"
            if len(translated) < len(needed):
                coverage += " (the rest in Slovak)"
            out.log.append(f"{code}: UI strings {ui}, occupations {coverage}")
    return out


def _fill(template: str, values: Mapping[str, str], name: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group(1) not in values:
            raise BuildError(f"web/{name}: unknown placeholder {match.group(0)}")
        return values[match.group(1)]

    return _PLACEHOLDER.sub(replace, _COMMENT.sub("", template))


def _attribute_json(content: object) -> str:
    return html.escape(encode(content).decode())


def headers(cfg: Config, web: Path) -> bytes:
    """Return ``_headers``: web/_headers, plus a noindex rule for pages.dev.

    The CSP's connect-src (``{{connect}}`` in web/_headers) adds the live
    results origin (``live_url``) to the site's own. The noindex rule is
    added once the site has a domain of its own (``base_url``):
    Pages keeps serving every deployment at <project>.pages.dev and at
    <hash>.<project>.pages.dev, and a search engine should know the site
    only by its domain.
    """
    live = cfg.site.live_url
    connect = f"'self' {live}" if live else "'self'"
    text = _fill(
        (web / HEADERS).read_text(encoding="utf-8"), {"connect": connect}, HEADERS
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


def sitemap(cfg: Config) -> bytes | None:
    """Return ``sitemap.xml``: the root page and every language's app shell.

    A sitemap lists absolute URLs only, so without ``base_url`` there is
    none. The pages name their other languages themselves (:func:`shells`).
    """
    base = cfg.site.base_url
    if not base:
        return None
    urls = [f"{base}/", *(f"{base}/{code}/" for code in cfg.languages.codes)]
    entries = "".join(f"  <url><loc>{html.escape(u)}</loc></url>\n" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}</urlset>\n"
    ).encode()


def shells(
    cfg: Config,
    web: Path,
    strings: Mapping[str, Mapping[str, Any]],
    assets: str,
    vendor: str,
    data_version: str,
) -> dict[str, bytes]:
    """Return the app shells, the root language picker and the 404 page.

    *assets* and *vendor* are the URLs of the versioned code and library
    directories (``/assets/<v>``, ``/assets/vendor/<vv>``), *data_version*
    what the app appends to the JSON it fetches (``?v=``).
    """
    langs = cfg.languages
    base = cfg.site.base_url or ""
    alternates = "\n".join(
        f'    <link rel="alternate" hreflang="{code}" href="{base}/{code}/" />'
        for code in langs.codes
    )

    # Only an absolute URL is a canonical one: with the site's own domain
    # set, search engines file every copy of a page under that domain.
    def canonical(path: str) -> str:
        return f'\n    <link rel="canonical" href="{base}/{path}" />' if base else ""

    app_config = {
        "languages": [[lang.code, lang.name] for lang in langs.languages],
        "storage": STORAGE_KEY,
        "election": str(cfg.site.election),
        # When the polls open and close (ISO 8601 with the offset): the search
        # card shows the voting under way between them.
        "polls": [cfg.site.polls_open.isoformat(), cfg.site.polls_close.isoformat()],
        # Research language → the source categories it searches: the scope
        # the app states before every research result.
        "research": {
            lang: list(categories) for lang, categories in cfg.sources.research.items()
        },
        "repository": cfg.site.repository,
        # The About dialog names the version, linked to its release.
        "version": __version__,
        # Appended to every JSON file the app fetches (``?v=``; module doc).
        "dataVersion": data_version,
        # The origin the app fetches the live results from; empty: none.
        "live": cfg.site.live_url or "",
        # When the app reads them every minute (ISO 8601); null: any time.
        "liveWindow": [when.isoformat() for when in cfg.site.live_window]
        if cfg.site.live_window
        else None,
    }
    template = (web / SHELL).read_text(encoding="utf-8")
    out = {}
    for lang in langs.languages:
        s = strings[lang.code]
        values = {
            "lang": lang.code,
            "dir": lang.direction,
            "title": html.escape(s["app.title"]),
            "description": html.escape(s["app.description"]),
            "noscript": html.escape(s["app.noscript"]),
            "features": html.escape(s["app.features"]),
            "alternates": alternates,
            "canonical": canonical(f"{lang.code}/"),
            "assets": assets,
            "vendor": vendor,
            "data_version": data_version,
            "config": _attribute_json(app_config),
        }
        out[f"{lang.code}/index.html"] = _fill(template, values, SHELL).encode()
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
        "title": html.escape(
            " · ".join(
                lang.site_name
                for code in langs.fallback
                for lang in langs.languages
                if lang.code == code
            )
        ),
        # The page is in the first fallback language (web/picker.html).
        "description": html.escape(strings[langs.fallback[0]]["app.description"]),
        # What the site offers, in each fallback language.
        "features": "\n".join(
            f'    <p lang="{code}">{html.escape(strings[code]["app.features"])}</p>'
            for code in langs.fallback
        ),
        "alternates": alternates,
        "canonical": canonical(""),
        "config": _attribute_json(picker_config),
        "links": links,
        "assets": assets,
    }
    picker = (web / PICKER).read_text(encoding="utf-8")
    out["index.html"] = _fill(picker, values, PICKER).encode()
    not_found = (web / NOT_FOUND).read_text(encoding="utf-8")
    out[NOT_FOUND] = _fill(not_found, {"title": values["title"]}, NOT_FOUND).encode()
    return out


def assemble(cfg: Config) -> Site:
    """Return the site built from *cfg*'s inputs; see the module doc."""
    web = cfg.root / WEB_DIR
    built = cfg.build_dir
    paths = {
        "candidates": built / candidates.OUTPUT_FILE,
        "geo": built / geo.OUTPUT_DIR,
        "addr": built / addresses.OUTPUT_DIR,
    }
    for step, path in paths.items():
        if not path.exists():
            raise BuildError(f"{path} missing; run `ems {step}` first")
    # The libraries are hashed before the code that names their directory,
    # the images before data/index.json, which names the party logos.
    vendor, images = (
        f"{ASSETS_DIR}/{name}/{content_version(tree(name, web / name))}"
        for name in (VENDOR_DIR, IMAGES_DIR)
    )
    code = code_files(web, f"/{vendor}")
    assets = f"{ASSETS_DIR}/{content_version(sorted(code.items()))}"
    with progress.stage("making the candidate, name search and UI string files"):
        data = json.loads(paths["candidates"].read_bytes())
        manifest_path = cfg.raw_dir / MANIFEST
        manifest = (
            json.loads(manifest_path.read_bytes()) if manifest_path.is_file() else {}
        )
        content: dict[str, object] = {}
        records = research_records(cfg)
        props = obec_props(paths["geo"])
        content.update(
            area_files(
                data,
                obvod_seats(paths["geo"], cfg.curated_dir),
                obvod_sources(cfg.curated_dir),
                research_summary(cfg, records),
                regional_past(data, props),
            )
        )
        translations = {
            code: translate.load(cfg, code).research for code in cfg.languages.codes
        }
        content.update(research_files(cfg, data, records, translations))
        shards = name_shards(data)
        content.update({f"data/names/{p}.json": rows for p, rows in shards.items()})
        content["data/index.json"] = site_index(
            data, props, shards, cfg.parties, f"/{images}"
        )
        content["data/about.json"] = about(cfg, manifest, data, records)
        occupations = sorted({c["occupation"] for c in data["candidacies"]} - {""})
        strings = i18n_files(cfg, web, occupations)
        content.update({f"i18n/{code}.json": s for code, s in strings.ui.items()})
        content.update(
            {
                f"i18n/{code}/occupations.json": o
                for code, o in strings.occupations.items()
            }
        )
        files = {path: encode(value) for path, value in content.items()}
    with progress.stage("hashing the data files"):
        # Everything the app fetches with ?v=: the generated JSON (so far
        # only data/ and i18n/) and the copied geo/ and addr/.
        data_version = content_version(
            itertools.chain(
                sorted(files.items()),
                tree("geo", paths["geo"]),
                tree("addr", paths["addr"]),
            )
        )
    files.update(shells(cfg, web, strings.ui, f"/{assets}", f"/{vendor}", data_version))
    files.update({f"{assets}/{path}": content for path, content in code.items()})
    files[HEADERS] = headers(cfg, web)
    site_map = sitemap(cfg)
    if site_map is not None:
        files[SITEMAP] = site_map

    copies = {vendor: web / VENDOR_DIR, images: web / IMAGES_DIR}
    copies[cache.STYLESHEET.removeprefix("/")] = web / CACHE_STYLESHEET
    copies["geo"] = paths["geo"]
    copies["addr"] = paths["addr"]
    cached = cfg.curated_dir / research.CACHE_DIR
    for record in records.values():
        for f in record["findings"]:
            copies[f"{CACHE_DIR}/{f['cache']}.html"] = cached / f"{f['cache']}.html"
    for target, source in copies.items():
        if not source.exists():
            raise BuildError(f"{source} missing")
    return Site(files, copies, strings.log)


def write(site: Site, directory: Path) -> dict[str, tuple[int, int]]:
    """Replace *directory* with *site*.

    Returns ``dist/`` path → (bytes, gzip -9 bytes) of every file.
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
    with progress.stage(f"reading {directory.name}/ for the size report") as s:
        files = sorted(p for p in directory.rglob("*") if p.is_file())
        blobs = [p.read_bytes() for p in s.track(files)]
    return {
        path.relative_to(directory).as_posix(): (len(data), gz)
        for path, data, gz in zip(files, blobs, output.gzip_sizes(blobs), strict=True)
    }


_GROUPS = (
    ("data/okres/", "candidates per okres"),
    ("data/kraj/", "candidates per kraj"),
    ("data/city/", "candidates per city"),
    ("data/names/", "name search shards"),
    ("data/research/", "research findings"),
    ("cache/", "cached pages"),
    ("data/index.json", "data/index.json"),
    ("geo/", "geometry"),
    ("addr/", "addresses"),
    ("i18n/", "UI strings and occupations"),
    ("assets/", "assets"),
)


def report(sizes: Mapping[str, tuple[int, int]]) -> Iterator[str]:
    """Yield a summary of the written files: count, bytes, gzip per group."""
    yield f"{'':<22} {'files':>6} {'bytes':>11} {'gzip':>11} {'max gzip':>11}"
    for prefix, label in (*_GROUPS, ("", "total")):
        group = [s for p, s in sizes.items() if p.startswith(prefix)]
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
        if stripped.startswith("!"):
            rules[-1][2].append(stripped[1:].strip())
            continue
        name, colon, value = stripped.partition(":")
        if not colon or not name.strip():
            raise BuildError(f"{HEADERS}:{n}: expected `Name: value`")
        rules[-1][1].append((name.strip(), value.strip()))
    return [
        HeaderRule(_url_pattern(url), tuple(headers), tuple(detach))
        for url, headers, detach in rules
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
            out[key] = (
                (name, f"{out[key][1]}, {value}") if key in out else (name, value)
            )
    return dict(out.values())


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

    def __init__(self, *args: Any, rules: list[HeaderRule], **kwargs: Any) -> None:
        # The base class handles the request inside __init__.
        self.rules = rules
        super().__init__(*args, **kwargs)

    def _path(self) -> str:
        return urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)

    def send_head(self) -> Any:
        # Pages reads _headers but does not serve it.
        if self._path() == f"/{HEADERS}":
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        return super().send_head()

    def list_directory(self, path: Any) -> None:
        # Pages lists no directories; a directory without index.html is
        # missing like any other path.
        self.send_error(HTTPStatus.NOT_FOUND)

    def send_error(
        self, code: int, message: str | None = None, explain: str | None = None
    ) -> None:
        # Pages answers a missing path with 404.html and status 404.
        if code != HTTPStatus.NOT_FOUND:
            super().send_error(code, message, explain)
            return
        body = (Path(self.directory) / NOT_FOUND).read_bytes()
        self.send_response(code, message)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def end_headers(self) -> None:
        for name, value in response_headers(self.rules, self._path()).items():
            self.send_header(name, value)
        super().end_headers()


def serve(directory: Path, host: str, port: int) -> None:
    """Serve *directory* over HTTP until interrupted.

    Responses carry the headers of ``<directory>/_headers``, so local tests
    see the same Content-Security-Policy as the deployed site.
    """
    rules = header_rules((directory / HEADERS).read_text(encoding="utf-8"))
    handler = functools.partial(_Handler, directory=str(directory), rules=rules)
    with ThreadingHTTPServer((host, port), handler) as httpd:
        print(f"serving {directory} at http://{host}:{httpd.server_port}/")
        httpd.serve_forever()
