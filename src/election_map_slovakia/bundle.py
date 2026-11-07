"""Assemble the data parts of the site: the elections' bundles, sources, results.

The site is deployed in parts, each a Cloudflare Pages project of its own
(``build`` lays them out in ``dist/``, docs/deploy.md has the projects):
the app, which :mod:`election_map_slovakia.build` assembles, and the data
assembled here, which change far more rarely. Each data part is a pure
function of the repository and the pinned inputs, so it has a key
(:mod:`election_map_slovakia.lock`) and is built and deployed again only
when that changes.

An election's files are in two bundles, written from its
``data/build/<day>/`` (the output of ``candidates``, ``geo``,
``addresses``, ``links`` and ``results``), the curated data and the
configuration: its map, which depends on that election alone and so
seldom changes, and its data, which depends on every election (the
persons linked across them, the research reused). Its base map is that of
its OpenStreetMap extract, a part of its own that every election on the
extract shares (:func:`bundles`). The app fetches each bundle's files
below its address (km-config ``map``, ``data`` and ``base``; locally
``/map/<slug>``, ``/data/<slug>`` and ``/base/<extract>``, deployed the
address of the deployment that carries its key), with ``?v=`` its version
(``mapVersion``, ``dataVersion``, ``baseVersion``). Paths below are
relative to the bundle. Each has::

    manifest.json            {key, election, version, files}: the key the
                             bundle was built for, the election day (of a
                             base map ``base``, its extract instead), a
                             short hash of its files (the ``?v=`` the app
                             asks for them with) and the paths of its
                             files; the app is built against it, and
                             checked against its list of files; a data
                             bundle's also ``occupations``, language → how
                             many occupations are not translated into it
    _headers                 its response headers, from web/_headers-data
    404.html                 web/part-404.html

The map bundle, ``dist/map/<slug>/`` (:func:`bundles`)::

    geo/                     data/build/<day>/geo/, verbatim (see geo)
    addr/                    data/build/<day>/addr/, verbatim (see addresses)

The base map, ``dist/base/<extract>/``, holds
data/build/base/<extract>/base/ verbatim (``okres/``, ``obec/``,
``coarse.json``, ``index.json``; see basemap), which the app asks for as
``/base/<path>``.

The data bundle, ``dist/data/<slug>/``::

    data/index.json          names and facts every view needs (below)
    data/about.json          source allowlist, inputs, obvod decisions
    data/okres/<okres>.json  candidates of the municipal contests of the
                             obce (and Bratislava/Košice districts) of an
                             okres
    data/city/<BA|KE>.json   candidates for mayor and city council
    data/kraj/<kraj>.json    candidates for regional president and council
    data/country.json        the country-wide contests: the president's
                             rounds, a referendum's questions, the parties
                             of a party-list election
    data/list/<p>.json       the persons on the list of party number <p>
    data/names/<xx>.json     candidate-name search shard
    data/research/<lang>/<area>.json
                             the research findings of the persons of the
                             area file data/<area>.json, in <lang>
                             (:func:`research_files`)
    i18n/<lang>.json         {occupations: {Slovak occupation:
                             translation}, missing}: the occupations of the
                             election's candidates translated into <lang>,
                             and how many are not, for every language but
                             Slovak (:func:`occupation_files`); the app
                             fetches it once with the first candidates it
                             shows

The sources part, ``dist/sources/`` (:func:`sources_part`), holds the
cached copy of every page a research finding cites, ``cache/<sha256>.html``
from data/curated/cache/ (see cache.py), and the stylesheet they link,
``assets/cache.css`` (web/cache.css; the path cache.STYLESHEET, fixed in
each copy when it was cached). The results part, ``dist/results/``
(:func:`results_part`), holds ``<day>/``, each election's final results,
data/build/<day>/results/ verbatim where there is one
(``Config.results_dir``; see results.py and docs/results.md). The live
part, ``dist/live/`` (:func:`live_part`), holds ``<day>/`` likewise, each
election's live results of its night, data/build/<day>/live/
(``Config.live_dir``), which ``ems results deploy`` deploys on the night,
never a release. Each has its ``_headers`` (web/_headers-sources,
web/_headers-results, web/_headers-live), ``404.html`` and a
``manifest.json``: with its key, the live part's (which has none) with the
version of each election's live results.

Each contest is in exactly one area file (``contests.area_name``), so a
click loads the okres, kraj and (in Bratislava and Košice) city file of one
place and nothing twice::

    data/<area>.json  {contests: {contest: {(seats), (sources), (holder),
                          (incumbents), (past), (no_result), (elected_only),
                          (uncontested),
                          (round, day), (question), (party),
                          (preferences, quota, threshold, (coalitions),
                           subjects: [
                           [number, party, candidates, threshold,
                            (withdrawn)]],
                           (research): {number: [researched, findings,
                                                 affairs, disputes]}),
                          candidates: [
                          [number, title_before, first_name, surname,
                           title_after, age, occupation, [party, ...],
                           person, (residence)]]}},
                       persons: {person: [candidacy, ...]},
                       (elsewhere): {person: {slug: [[candidacy, votes,
                                                      valid, rank, of,
                                                      flag], ...]}},
                       (research): {person: [date, findings,
                                             [language, ...], affairs,
                                             disputes, (undated)]}}

``persons`` lists, for every person with a candidacy in the file who stands
in more than one contest, all their candidacies (in any file). ``seats`` is
known where the candidate lists give it (ŠÚ SR's of 2022 give every
council obvod's), for regional and city council obvody and the obvody of
obce with a rule set; else a council elected in one obvod has
``seats_2022``, the number its whole council elected in 2022, as a
stand-in until the 2026 number is known (councils of several obvody have
neither: a 2022 total says nothing about one obvod). ``no_result`` (1)
marks a contest that had candidates but has no final result
(:func:`no_result`), ``elected_only`` (1) a council contest whose
candidates are the elected only (``candidates.json``), ``uncontested``
``[title, url]`` a contest called but held nowhere, no candidate having
registered (``candidates.json``: what says so); a candidate's
``age`` is null, its ``occupation`` and titles empty, where the lists do
not give them. ``sources`` are the official
documents that set a council's obvody, as ``[title, url]``
(:func:`obvod_sources`). ``residence`` is the obec of residence of
regional and country-wide candidates: its code, or for a country-wide
candidate whose written residence matches no one obec, the name as written.
``round`` (1 or 2) and ``day`` (ISO) are a presidential contest's round
and the day it is voted on, ``question`` a referendum question's wording,
``party`` the party (``config/parties.toml``) of a list contest. A
party-list contest (``nrsr:SK``, ``ep:SK``) has ``subjects``, the parties
on the ballot, instead of ``candidates``: their ballot number, party,
number of candidates on the list, the share of the valid votes in % they
need for seats (a coalition's, by its ``members``, where it is one; see
:func:`election_map_slovakia.contests.subject_threshold`) and ``1`` where
the subject withdrew; ``research`` totals, by ballot number, the research
summaries (below) of the candidates on each subject's list: how many are
researched, and their findings, affairs and disputes summed (subjects
with none researched have no entry); with
``seats`` of the body, ``preferences``, how many of a list's candidates a
voter may mark, ``quota``, the % of its party's votes a candidate's
preference votes must reach to move up the list, and the rule the
thresholds follow: ``threshold``, the % a party standing alone needs, and
``coalitions``, ``[[parties, %], ...]`` by ascending parties, the % a
coalition of at least that many parties needs (none where coalitions need
what a party does). ``holder`` is the mayor
or regional president in office, ``[name, since, number, result]``
(``number`` the holder's ballot
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
``[election, day, eligible, voters, (scope)]``: the results input without
``results-`` (``oso2022``, ``osk2022``, ``oso202303``, …), its ISO day, the
voters on the roll and those who took part, in the whole municipality,
city or kraj, or for a regional council contest in the obce that make up
its 2026 obvod (:func:`regional_past`); see
:mod:`election_map_slovakia.candidates` for which election. A council of
several obvody in 2026 has ``scope``: the 2022 obvody were drawn
otherwise, so either ``1``, the figures being of the whole municipality or
city, or ``[method]``, the figures being the 2022 ones of the obvod's
okrsky (estimated where they changed), with the least certain method
among them (``results.PAST_METHODS``; :func:`council_past`).
``elsewhere`` lists, for each person of the file linked to a person of
another election (:mod:`election_map_slovakia.links`), every candidacy of
that person there by the other election's slug (:func:`elsewhere`), with
how it went where that election's results are final: the candidate's
votes, the contest's valid ballots (for a council: the voters with a valid
ballot), the candidate's rank by votes among its ``of`` candidates (equal
votes, equal rank) and the results' flag (``1`` elected, ``0``
substitute, ``-1`` withdrew, null not elected); a candidacy whose results
are not final, or whose contest has none, is ``[candidacy]`` alone. Where
the results have the elected only (a by-election of 2019–2022), each other
candidacy of the contest has null votes and rank and the flag ``0``, and
``of`` counts every candidacy.
``research`` summarizes, for each researched person of the file, when (the
latest date) and in which research languages they were researched and how
many findings there are (:func:`research_summary`); a person without an
entry is not researched yet. Research is done on the candidates of the
latest election; an earlier election's person linked to one of them gets
theirs cut to the findings published before its day
(:func:`reused_research`), and ``undated`` then counts the findings left
out for having no date of publication.

::

    data/index.json  {kraje: {kraj: name},
                      okresy: {okres: [name, kraj]},
                      obce: {obec: [name, okres, kraj, zsk, councils,
                                    (city, city_obvod)]},
                      by_address: [obec, ...],
                      estimated: [obec, ...],
                      reused: {obec: day},
                      adopted: {obec: day},
                      date_approximate: {obec: {by, (seen)}},
                      supplemented: {obec: {from, day}},
                      okrsky_reused: {obec: day},
                      okrsky_adopted: {obec: day},
                      okrsky_outliers: {obec: [[okrsok, voters, voters in
                                                okrsky_adopted's], ...]},
                      okrsky_referendum: {obec: day},
                      okrsky_date_approximate: {obec: {by, (seen)}},
                      okrsky_supplemented: {obec: {from, day}},
                      not_found: [obec, ...],
                      okrsky_unknown: [obec, ...],
                      special: {obec: {okrsok: {kind, voters, title, url,
                                                (okresy | facility)}}},
                      boundaries: {day, on, obce: {obec: [obec, ...]}} | null,
                      names: {prefix: persons},
                      parties: {party: [short, name, (logo)]},
                      uncontested: [contest, ...],
                      (held): {area: [contest, ...]}}

    data/about.json  {sources, inputs: [{name, url, (retrieved)}],
                      logos, obvody, council, research,
                      candidates: format | null, substitutes: {...} | null,
                      stand_ins: {obvody: [[day, [name, ...]], ...],
                                  okrsky: [[day, [name, ...]], ...]}}

``zsk`` is the obec's regional council obvod (0: none elected) and
``councils`` the number of municipal council obvody (0: no council
election; of a by-election, that of the whole council where its contests
are only some of its obvody, :func:`council_count`); ``uncontested``
lists the contests called but held nowhere, no candidate having
registered; ``held``, of a by-election only, maps each obec (or
Bratislava, Košice) and kraj (its 1-digit code) where something is elected
to the contests held there (:func:`held_areas`); ``by_address`` lists the obce
whose council obvod goes by
address (``addresses``: ``council`` ``"address"``) and whose shard
features are their obvody (``geo``); ``estimated`` those of them whose
rule set is a guess (``geo``: ``estimated``); ``reused`` those whose rule
set is another election's, with that election's ISO day (no document of
this election was found, and the layout provably matches, see
:mod:`election_map_slovakia.reuse`); ``adopted`` those whose rule set is
another vote's standing in, with its day, though the layout is not proven
to match (no usable document of this election places the addresses; that
vote is the nearest in time with a rule set of its own of the same obvody
and seats: the borders are indicative only); ``date_approximate`` those whose
documents state no date, with what dates them approximately (``by``: an
Internet Archive capture, a posting on the official page, the document
naming the election; ``seen``: the day of the first two;
:class:`election_map_slovakia.obvody.Dating`); ``supplemented`` those
whose documents do not place every address, where rules from a later
source fill them in (``from``: a later election's rule set, a
referendum's or another later document; ``day``: that vote's day or the
document's date; :class:`election_map_slovakia.obvody.Supplement`).
``okrsky_reused``, ``okrsky_adopted`` and ``okrsky_referendum`` give the
obce whose okrsky are another vote's (proven to match, or standing in), or
from a referendum's document, with its day, ``okrsky_outliers`` those
okrsky standing in whose voters on the roll differ beyond what the layout
allows elsewhere (:attr:`election_map_slovakia.obvody.Adoption.outliers`:
the voters in this election and in the vote standing in), and
``okrsky_date_approximate`` and ``okrsky_supplemented`` those whose okrsky
document is dated so, or filled in so
(:func:`election_map_slovakia.obvody.okrsky_origin`), of the obce whose
okrsky are drawn; ``not_found`` the
obce of several council obvody without a rule set whose document was
searched for and not found; ``okrsky_unknown`` the obce that voted in
several okrsky none of which is drawn (:func:`place_facts`); ``special``
the okrsky without territory that voted, which the map never draws and the
ballots name (:func:`special_okrsky`, :mod:`election_map_slovakia.special`:
``covid`` with the ``okresy`` it serves, ``prison`` with its ``facility``;
``voters`` on its roll, ``title`` and ``url`` the source);
``boundaries``, for an election drawn on a later one's boundaries (``on``,
its slug), the obce whose land moved since ``day``
(:func:`boundary_changes`);
About's ``inputs`` are those the election names and those no election
names, its ``candidates`` the format its candidate lists are read in (null
for a referendum, which has none); ``substitutes``, for an election other
than the latest, what it takes from the latest and what it lacks, with
counts (:func:`substitutes`); ``stand_ins`` the obce whose obvody or
okrsky another vote's stand in for, by that vote's day
(:func:`stand_ins`);
``okres`` is ``""`` and ``zsk`` 0 for Bratislava and Košice
themselves. A name shard holds every person with a name word (first name or
surname, :func:`election_map_slovakia.candidates.search_key`) starting with its two-letter
prefix, as ``[name, age, [candidacy, ...]]`` sorted by surname, the name and
age being those of the person's first candidacy (the age null where not
known); ``names`` maps each prefix
to its person count, so the search picks the smallest shard among the words
of a query. ``parties`` gives every party named in a candidacy or on a
party-list ballot (``subjects``) its short
form, official name and logo at this election (``config/parties.toml``
``logo.<slug>``; a file name below the app's party logos, km-config
``logos``); About's ``logos`` credit those logos.
"""

from __future__ import annotations

import bisect
import functools
import hashlib
import os
import re
import tomllib
from collections import Counter, defaultdict, deque
from collections.abc import Collection, Iterable, Iterator, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import orjson

from election_map_slovakia import (
    addresses,
    basemap,
    candidates,
    config,
    contests,
    geo,
    obvody,
    output,
    parallel,
    progress,
    research,
    special,
    translate,
)
from election_map_slovakia.config import Config

if TYPE_CHECKING:
    from election_map_slovakia.results import Live

# Hex digits of the bundles' and the app's asset versions: 40 bits, so two
# releases sharing a version by chance is not a concern.
VERSION_DIGITS = 10
MAP_PART = "map"
"""Below ``dist/``: the map bundle of each election, ``<slug>/``."""
DATA_PART = "data"
"""Below ``dist/``: the data bundle of each election, ``<slug>/``."""
BASE_PART = config.BASE_DIR
"""Below ``dist/``: the base map of each extract, ``<extract>/``; also the
directory the app asks for its files below (``/base/…``)."""
SOURCES_PART = "sources"
"""Below ``dist/``: the sources part."""
RESULTS_PART = config.RESULTS_DIR
"""Below ``dist/``: the results part, the final results."""
LIVE_PART = config.LIVE_DIR
"""Below ``dist/``: the live part, the live results of election nights."""
HEADERS = "_headers"
"""Each part's Cloudflare Pages response headers (``build.header_rules``)."""
NOT_FOUND = "404.html"
"""What Pages answers a missing path of a part with, status 404."""
MANIFEST = "manifest.json"
"""In each data part: its key (and a bundle's files)."""
CACHE_DIR = "cache"
"""Below the sources part: the cached copies of the pages research cites."""
DATA_DIR = "data"
I18N_DIR = "i18n"
LINKS_DIR = "links"
"""Below an election's build directory: its persons linked to those of every
election before it (``ems links``), ``<earlier slug>.json`` each."""
MAP_ROOTS = (geo.OUTPUT_DIR, addresses.OUTPUT_DIR)
"""The directories of a map bundle, which the app fetches below its address
(km-config ``map``)."""
DATA_ROOTS = (DATA_DIR, I18N_DIR)
"""Those of a data bundle (km-config ``data``)."""
PREFIX = 2
ORIGINS = (
    "reused",
    "adopted",
    "date_approximate",
    "supplemented",
    "okrsky_reused",
    "okrsky_adopted",
    "okrsky_outliers",
    "okrsky_referendum",
    "okrsky_date_approximate",
    "okrsky_supplemented",
)
"""The per-obec flags of ``data/index.json`` on where its obvody and okrsky
come from (:func:`election_map_slovakia.obvody.council_origin`,
:func:`election_map_slovakia.obvody.okrsky_origin`)."""
_BLOCKLIST_DATE = re.compile(r"retrieved (\d{4}-\d{2}-\d{2})")
WEB_DIR = "web"


class BuildError(Exception):
    """An input of the site is missing or inconsistent."""


class FileFacts(NamedTuple):
    """What ``build`` needs to know of a file it copies, read once."""

    size: int
    digest: str
    """The SHA-256 of its content, hex: the key of the gzip memo
    (:func:`election_map_slovakia.output.gzip_sizes`)."""
    device: int
    inode: int
    """With *device*, which file it is: ``dist/`` holds a hard link to it
    where the build links rather than copies (``build.write``)."""

    @classmethod
    def read(cls, path: str) -> tuple[bytes, FileFacts]:
        """Return the content of the file *path* and its facts."""
        with open(path, "rb") as f:
            content = f.read()
            st = os.fstat(f.fileno())
        digest = hashlib.sha256(content).hexdigest()
        return content, cls(len(content), digest, st.st_dev, st.st_ino)


@dataclass(frozen=True)
class Part:
    """What ``build`` writes of one part: path below it → content.

    *copies* are directories and files copied verbatim: path → source.
    *known* are the :class:`FileFacts` of source files read already, by
    their path (``<source>/<path below it>``), which ``build`` need not
    read again.
    """

    files: dict[str, bytes]
    copies: dict[str, Path]
    known: dict[str, FileFacts] = field(default_factory=dict)


def encode(content: object) -> bytes:
    """Return *content* as compact, key-sorted UTF-8 JSON."""
    return output.to_json(content, sort_keys=True)


def files_below(directory: Path) -> list[str]:
    """Return the paths of the files below *directory*, relative to it.

    Sorted as :class:`~pathlib.Path` objects sort, component by component
    (``a/b`` before ``a-b``), the order :func:`content_version` has always
    seen. Plain strings: making a Path of each of the site's 170,000
    files, and taking it relative, took longer than reading them.
    """
    top = str(directory)
    out = []
    for parent, _, names in os.walk(top):
        below = parent[len(top) + 1 :]
        out += [f"{below}/{name}" if below else name for name in names]
    out.sort(key=lambda path: path.split("/"))
    return out


def tree(name: str, source: Path) -> Iterator[tuple[str, bytes]]:
    """Yield (path, content) of the file or directory tree *source*.

    A path is *name* for a file, else *name*/<path below *source*>, in
    :func:`files_below` order, so that :func:`content_version` sees a
    stable sequence. Threads read the files of a directory side by side:
    one by one, the thousands of data files took more than a second.
    """
    if not source.exists():
        raise BuildError(f"{source} missing")
    if source.is_file():
        yield name, source.read_bytes()
        return
    paths = files_below(source)
    top = str(source)

    def read(path: str) -> bytes:
        with open(f"{top}/{path}", "rb") as f:
            return f.read()

    with ThreadPoolExecutor() as pool:
        for path, content in zip(paths, pool.map(read, paths), strict=True):
            yield f"{name}/{path}", content


def content_version(files: Iterable[tuple[str, bytes]]) -> str:
    """Return a short hash of the (path, content) pairs *files*, in order.

    Paths count as well as contents: a file renamed is a new version.
    """
    digest = hashlib.sha256()
    for path, content in files:
        _add_version(digest, path, content)
    return digest.hexdigest()[:VERSION_DIGITS]


def _add_version(digest: hashlib._Hash, path: str, content: bytes) -> None:
    digest.update(f"{path}\0{len(content)}\0".encode())
    digest.update(content)


def copied_files(
    copies: Mapping[str, Path],
) -> tuple[str, list[str], dict[str, FileFacts]]:
    """Return the version, files and :class:`FileFacts` of a map bundle or base map.

    *copies* are its directories and files (target → source): its version
    is the :func:`content_version` of them in turn, its files their paths
    below the part, sorted, and the facts those of each source file, by
    its path. Each file is read once, for all three: they are most of the
    site's bytes.
    """
    version = hashlib.sha256()
    files = [
        pair
        for target, source in copies.items()
        for pair in (
            [(f"{target}/{path}", f"{source}/{path}") for path in files_below(source)]
            if source.is_dir()
            else [(target, str(source))]
        )
    ]
    known = {}
    contents = _read_ahead([full for _, full in files])
    for (name, full), (content, facts) in zip(files, contents, strict=True):
        known[full] = facts
        _add_version(version, name, content)
    return version.hexdigest()[:VERSION_DIGITS], sorted(n for n, _ in files), known


# Threads reading a worker's files, batches of files each, at once: one
# file at a time, a worker waited for the disk three times as long as it
# hashed; one file per thread, they cost more than the disk where the
# files are in memory already.
_READERS = 8
_READ_BATCH = 16


def _read_ahead(paths: list[str]) -> Iterator[tuple[bytes, FileFacts]]:
    """Yield :meth:`FileFacts.read` of each of *paths*, in order.

    Threads read some batches ahead (:data:`_READERS`), and no more, so
    that only those are held at once.
    """

    def read(batch: list[str]) -> list[tuple[bytes, FileFacts]]:
        return [FileFacts.read(path) for path in batch]

    with ThreadPoolExecutor(_READERS) as pool:
        pending: deque[Future[list[tuple[bytes, FileFacts]]]] = deque()
        for start in range(0, len(paths), _READ_BATCH):
            pending.append(pool.submit(read, paths[start : start + _READ_BATCH]))
            if len(pending) > _READERS:
                yield from pending.popleft().result()
        while pending:
            yield from pending.popleft().result()


def _area_path(contest: str, okres_of: Mapping[str, str]) -> str:
    """Return the bundle path of the area file holding *contest*.

    *okres_of* maps obec codes to their okres (:func:`_okres_of`).
    """
    return f"{DATA_DIR}/{contests.area_name(contest, okres_of)}.json"


def _okres_of(data: Mapping[str, Any]) -> dict[str, str]:
    """Return obec → its okres ("" for Bratislava and Košice) of *data*."""
    return {o["code"]: o.get("okres", "") for o in data["obce"]}


def _result_row(r: Mapping[str, int]) -> list[int]:
    row = [r["votes"], r["valid"], r["voters"], r["eligible"]]
    if "obvod" in r:
        row.append(r["obvod"])
    return row


# A candidate row of an area file, before the optional residence.
_CANDIDATE_FIELDS = (
    "number",
    "title_before",
    "first_name",
    "surname",
    "title_after",
    "age",
    "occupation",
    "parties",
    "person",
)


def _candidate_row(c: Mapping[str, Any]) -> list[Any]:
    row = [c[field] for field in _CANDIDATE_FIELDS]
    # A country-wide candidate's residence that matches no one obec is
    # shown as written.
    if "residence" in c:
        row.append(c["residence"])
    elif "residence_name" in c:
        row.append(c["residence_name"])
    return row


def linked_persons(
    pairs: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, dict[str, dict[str, str]]]:
    """Return election → other election → person → the person linked there.

    *pairs* maps (later slug, earlier slug) to the persons of the later
    linked to those of the earlier (:mod:`election_map_slovakia.links`);
    each link goes both ways.
    """
    out: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for (later, earlier), linked in pairs.items():
        out[later][earlier] = dict(linked["persons"])
        out[earlier][later] = {e: p for p, e in linked["persons"].items()}
    return out


def candidacy_results(
    final: Mapping[str, Mapping[str, Any]], data: Mapping[str, Any]
) -> dict[str, list[Any]]:
    """Return candidacy → ``[votes, valid, rank, of, flag]`` (see the module doc).

    *final* maps contests to their final results (:func:`final_contests`),
    *data* is the election's ``candidates.json``.
    """
    listed: dict[str, list[str]] = defaultdict(list)
    for c in data["candidacies"]:
        listed[c["contest"]].append(c["id"])
    out = {}
    for contest, record in final.items():
        rows = record["candidates"]
        of = max(len(rows), len(listed[contest]))
        # Most votes first, negated so that bisect finds the votes' place.
        order = sorted(-v for _, v, _ in rows)
        for number, v, flag in rows:
            # Equal votes, equal rank: one more than those with more votes.
            rank = 1 + bisect.bisect_left(order, -v)
            out[f"{contest}#{number}"] = [v, record["valid"], rank, of, flag]
        for cid in listed[contest]:
            # Results of the elected only: the others were not, with votes
            # not published.
            out.setdefault(cid, [None, record["valid"], None, of, 0])
    return out


def elsewhere(
    data: Mapping[str, Mapping[str, Any]],
    persons: Mapping[str, Mapping[str, Mapping[str, str]]],
    results: Mapping[str, Mapping[str, list[Any]]],
) -> dict[str, dict[str, dict[str, list[list[Any]]]]]:
    """Return election → person → {other election: their candidacies there}.

    *data* maps election slugs to their ``candidates.json``, *persons* is
    :func:`linked_persons`, *results* maps slugs to their
    :func:`candidacy_results`. Each candidacy is ``[candidacy, votes, valid,
    rank, of, flag]``, or ``[candidacy]`` without a final result.
    """
    candidacies = {
        slug: {p["id"]: p["candidacies"] for p in d["persons"]}
        for slug, d in data.items()
    }
    out: dict[str, dict[str, dict[str, list[list[Any]]]]] = {
        slug: defaultdict(dict) for slug in data
    }
    for slug, others in persons.items():
        for other, linked in others.items():
            for person, theirs in linked.items():
                out[slug][person][other] = [
                    [cid, *results.get(other, {}).get(cid, [])]
                    for cid in candidacies[other][theirs]
                ]
    return out


def area_files(
    data: Mapping[str, Any],
    seats: Mapping[str, int],
    sources: Mapping[str, list[list[str]]] | None = None,
    researched: Mapping[str, list[Any]] | None = None,
    pasts: Mapping[str, Mapping[str, Any]] | None = None,
    no_result: Collection[str] = (),
    other: Mapping[str, Mapping[str, list[list[Any]]]] | None = None,
    *,
    day: str | None = None,
    parties: Mapping[str, config.Party] | None = None,
    part: Collection[str] = (),
) -> dict[str, dict[str, Any]]:
    """Return the candidate area files; see the module doc.

    *data* is ``candidates.json``; *seats* maps obvod contests to their seat
    count where known; *sources* is :func:`obvod_sources`; *researched* maps
    persons to their research summary (:func:`research_summary`); *pasts*
    maps contests to the ``past`` made here (:func:`regional_past`,
    :func:`council_past`), which replaces theirs; *no_result* names the
    contests the final results have none of (:func:`no_result`); *other*
    maps persons to their candidacies in other elections (:func:`elsewhere`).
    *day* is the election's (ISO), the day of a presidential first round;
    *parties* is ``config/parties.toml``, whose ``members`` make a ballot
    subject a coalition (:func:`contests.subject_threshold`). *part* names
    the obce of a by-election whose council contests are part of a larger
    council (:func:`addresses.part_councils`): none is one of a single obvod.
    """
    sources = sources or {}
    researched = researched or {}
    pasts = pasts or {}
    other = other or {}
    parties = parties or {}
    okres_of = _okres_of(data)
    files: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"contests": {}, "persons": {}}
    )
    path_of: dict[str, str] = {}
    council_obvody = Counter(c["area"] for c in data["contests"] if c["kind"] == "oz")
    for contest in data["contests"]:
        path = path_of[contest["id"]] = _area_path(contest["id"], okres_of)
        entry = files[path]["contests"][contest["id"]] = _contest_entry(
            contest,
            seats,
            sources,
            pasts.get(contest["id"]),
            single=council_obvody[contest["area"]] == 1 and contest["area"] not in part,
        )
        entry |= _national_entry(contest, day, parties)
        if contest["id"] in no_result:
            entry["no_result"] = 1
    by_person: dict[str, list[str]] = defaultdict(list)
    for c in data["candidacies"]:
        by_person[c["person"]].append(c["id"])
    for c in sorted(data["candidacies"], key=lambda c: (c["contest"], c["number"])):
        person = c["person"]
        file = files[path_of[c["contest"]]]
        entry = file["contests"][c["contest"]]
        entry["candidates"].append(_candidate_row(c))
        if "incumbent" in c:
            entry.setdefault("incumbents", {})[str(c["number"])] = [
                [office["body"], office["since"], _result_row(office["result"])]
                for office in c["incumbent"]
            ]
        if person in other:
            file.setdefault("elsewhere", {})[person] = other[person]
        if len(by_person[person]) > 1:
            file["persons"][person] = by_person[person]
        if person in researched:
            file.setdefault("research", {})[person] = researched[person]
            # A party list (`<party contest>/<number>`) adds its researched
            # candidates to its subject's totals on the party-list ballot.
            parent, _, number = c["contest"].rpartition("/")
            ballot = (
                files[path_of[parent]]["contests"][parent] if parent in path_of else {}
            )
            if "subjects" in ballot:
                _, findings, _, affairs, disputes = researched[person][:5]
                totals = ballot.setdefault("research", {}).setdefault(
                    number, [0, 0, 0, 0]
                )
                totals[0] += 1
                totals[1] += findings
                totals[2] += affairs
                totals[3] += disputes
    return dict(files)


def _national_entry(
    contest: Mapping[str, Any], day: str | None, parties: Mapping[str, config.Party]
) -> dict[str, Any]:
    """Return what a country-wide contest's entry has besides the common keys.

    See the module doc and :func:`area_files`; empty for other contests.
    """
    c = contests.parse(contest["id"])
    if c.kind.sub == "round":
        # Round 2's day is its own; round 1 is voted on the election day.
        when = contest.get("day", day)
        if when is None:
            raise BuildError(f"{contest['id']}: the day of its round is not known")
        return {"round": c.sub, "day": when}
    if c.kind.sub == "question":
        return {"question": contest["question"]}
    if c.is_list:
        return {"party": contest["party"]}
    if c.kind.party:
        entry: dict[str, Any] = {
            "preferences": contest["preferences"],
            "quota": contest["quota"],
            # The rule, which the ballot states in full, besides each
            # subject's own threshold.
            "threshold": contest["threshold"],
            "subjects": [
                _subject_row(contest, subject, parties)
                for subject in contest["subjects"]
            ],
        }
        if coalitions := contest.get("coalition_thresholds"):
            entry["coalitions"] = coalitions
        return entry
    return {}


def _subject_row(
    contest: Mapping[str, Any],
    subject: Mapping[str, Any],
    parties: Mapping[str, config.Party],
) -> list[Any]:
    """Return a ballot subject of party-list *contest* as a ``subjects`` row."""
    party = parties.get(subject["party"])
    # site_index names a subject without an entry in parties.toml.
    members = len(party.members) if party else 0
    row = [
        subject["number"],
        subject["party"],
        subject["candidates"],
        contests.subject_threshold(contest, members),
    ]
    if subject.get("withdrawn"):
        row.append(1)
    return row


def _contest_entry(
    contest: Mapping[str, Any],
    seats: Mapping[str, int],
    sources: Mapping[str, list[list[str]]],
    computed: Mapping[str, Any] | None,
    *,
    single: bool,
) -> dict[str, Any]:
    """Return a contest's entry of an area file, without its candidates.

    *computed* is the contest's ``past`` made here (:func:`area_files`), if
    any; *single*: the contest's council (if it is one) is elected in one obvod.
    A party-list contest, whose candidates are its ``subjects``
    (:func:`_national_entry`), has no ``candidates``.
    """
    c = contests.parse(contest["id"])
    entry: dict[str, Any] = {} if c.kind.party and not c.is_list else {"candidates": []}
    # The candidate lists' own count (ŠÚ SR's of 2022) is the obvod's.
    if "seats" in contest:
        entry["seats"] = contest["seats"]
    elif contest["id"] in seats:
        entry["seats"] = seats[contest["id"]]
    elif "seats_2022" in contest and single:
        # 2022 counts are per whole council: comparable only to a single obvod.
        entry["seats_2022"] = contest["seats_2022"]
    documents = sources.get(_sources_key(contest))
    if documents:
        entry["sources"] = documents
    if contest.get("elected_only"):
        entry["elected_only"] = 1
    if "uncontested" in contest:
        why = contest["uncontested"]
        entry["uncontested"] = [why["title"], why["source"]]
    if "incumbent" in contest:
        holder = contest["incumbent"]
        number = holder["candidacy"] and int(holder["candidacy"].split("#")[1])
        entry["holder"] = [
            holder["name"],
            holder["since"],
            number,
            _result_row(holder["result"]),
        ]
    past = computed or contest.get("past")
    if past is not None:
        entry["past"] = [
            past["election"],
            past["day"],
            past["eligible"],
            past["voters"],
        ]
        if contest["kind"] == "oz" and not single:
            entry["past"].append(past.get("scope", 1))
    return entry


def research_summary(cfg: Config, records: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Return person → their research summary, as in the area files.

    That is ``[date, findings, [language, ...], affairs, disputes,
    (undated)]``. *records* maps persons to their curated research
    (:mod:`research`), or to that reused for an earlier election
    (:func:`reused_research`). The
    date is the latest a category was researched, the languages those of
    ``[research]`` in ``sources.toml`` whose every category is researched,
    *affairs* how many of the findings are serious controversies, which the
    ballots flag, and *disputes* how many are disputed or lesser ones;
    *undated*, for reused research, how many were left out for want of a date.
    """
    out = {}
    for person, record in records.items():
        languages = [
            lang
            for lang, categories in cfg.sources.research.items()
            if research.done(record, categories)
        ]
        if not languages:
            continue
        kinds = Counter(f["kind"] for f in record["findings"])
        out[person] = [
            max(s["date"] for s in record["researched"].values()),
            len(record["findings"]),
            languages,
            kinds["affair"],
            kinds["dispute"],
        ]
        if "undated" in record:
            out[person].append(record["undated"])
    return out


def reused_research(
    records: Mapping[str, Any], persons: Mapping[str, str], day: str
) -> dict[str, Any]:
    """Return the research of an earlier election's persons, from the latest's.

    *records* maps the latest election's persons to their curated research
    (:func:`research_records`), *persons* them to the persons of the
    earlier election linked to them (:func:`linked_persons`). No research is
    done for an earlier election: a person linked to a researched one gets
    that research with the findings whose source was published before
    *day*, the earlier election's (ISO). A finding whose source has no date
    may be of after it, so it is left out too and counted, as ``undated``.
    """
    out = {}
    for later, earlier in persons.items():
        record = records.get(later)
        if record is None:
            continue
        findings = record["findings"]
        out[earlier] = {
            **record,
            "findings": [
                f for f in findings if f["published"] and f["published"] < day
            ],
            "undated": sum(not f["published"] for f in findings),
        }
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
    okres_of = _okres_of(data)
    areas: dict[str, set[str]] = defaultdict(set)
    for c in data["candidacies"]:
        if records.get(c["person"], {}).get("findings"):
            area = contests.area_name(c["contest"], okres_of)
            areas[f"{area}.json"].add(c["person"])
    files: dict[str, dict[str, list[list[Any]]]] = {}
    for lang in cfg.languages.codes:
        own = translations.get(lang, {})
        for area, persons in sorted(areas.items()):
            files[f"data/research/{lang}/{area}"] = {
                person: [
                    _finding_row(f, lang, own) for f in records[person]["findings"]
                ]
                for person in sorted(persons)
            }
    return files


def _finding_row(
    finding: Mapping[str, Any], lang: str, translated: Mapping[str, str]
) -> list[Any]:
    """Return *finding* as a row of a *lang* findings file (:func:`research_files`).

    *translated* maps English claims and foreign quotes to *lang*.
    """
    claim = finding["claim"]
    return [
        finding["kind"],
        claim.get(lang) or translated.get(claim["en"]) or claim["en"],
        finding["quote"],
        None if finding["language"] == lang else translated.get(finding["quote"]),
        finding["url"],
        finding["title"],
        finding["published"],
        finding["cache"],
        finding["category"],
        finding["language"],
    ]


def research_records(cfg: Config) -> dict[str, dict[str, Any]]:
    """Return election (ISO day) → person → curated research record."""
    root = cfg.curated_dir / research.CURATED_DIR
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    for path in sorted(root.glob("*/*.json")):
        record = orjson.loads(path.read_bytes())
        out[record["election"]][path.stem] = record
    return dict(out)


def obec_props(geo_dir: Path) -> dict[str, dict[str, Any]]:
    """Return obec → its properties in the coarsest ``geo`` shard."""
    coarsest = geo.SHARD_LODS[0].level
    props = {}
    for path in sorted((geo_dir / "okres").glob(f"*/{coarsest}.json")):
        for feature in orjson.loads(path.read_bytes())["features"]:
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


def council_past(
    data: Mapping[str, Any], live: Live | None
) -> dict[str, dict[str, Any]]:
    """Return council obvod contest → its ``past``, of its own okrsky.

    For each obvod of a council of several whose ``past`` is of the
    election its final results (*live*, :func:`final_okrsky`) compare its
    okrsky with (``past`` of the okrsok files, :mod:`crosswalk`: the
    municipal contests' election before): the earlier figures of its okrsky
    added up, an obec wholly in it as a whole, where all are known, with
    ``scope`` ``[method]``, the least certain method of its okrsky
    (``results.PAST_DOUBT``). Otherwise its ``past`` stays that of the
    whole municipality or city.
    """
    from election_map_slovakia import results  # results imports this module

    if live is None:
        return {}
    keys_of = {c: areas for files in live.okrsky.values() for c, areas in files.items()}
    councils = Counter(c["area"] for c in data["contests"] if c["kind"] == "oz")
    out: dict[str, dict[str, Any]] = {}
    for c in data["contests"]:
        whole = c.get("past")
        if c["kind"] != "oz" or councils[c["area"]] == 1 or whole is None:
            continue
        past = live.past.get(contests.source_of(c["id"]))
        if past is None:
            continue
        figures = past.contests.get(c["id"], {})
        by_obec: dict[str, list[str]] = defaultdict(list)
        for key in keys_of.get(c["id"], ()):
            by_obec[key.partition("/")[0]].append(key)
        parts = []
        doubt = 0
        for obec, keys in by_obec.items():
            if obec in figures:
                parts.append(figures[obec])
            elif all(k in figures for k in keys):
                parts += [figures[k] for k in keys]
                doubt = max(
                    doubt,
                    *(results.PAST_DOUBT.index(past.methods[k]) for k in keys),
                )
            else:
                break
        else:
            if whole["day"] != past.day or not parts:
                continue
            eligible, voters, _, _ = results.sum_areas(parts)
            out[c["id"]] = whole | {
                "eligible": eligible,
                "voters": voters,
                "scope": [results.PAST_DOUBT[doubt]],
            }
    return out


def final_okrsky(results_dir: Path) -> Live | None:
    """Return the final results in *results_dir*, with their okrsky and ``past``.

    None before the results are final (or without any).
    """
    from election_map_slovakia import results  # results imports this module

    st = results.read_status(results_dir) if results_dir.is_dir() else None
    if st is None or st.get("phase") != "final":
        return None
    return results.read_live(results_dir)


def obvod_seats(geo_dir: Path, election_dir: Path) -> dict[str, int]:
    """Return obvod contest → seats, where known.

    Regional and city council obvody from ``geo``; the council obvody of the
    obce with a rule set from it (in *election_dir*, :meth:`Config.election_dir`).
    """
    return _obvod_seats(geo_dir, obvody.load_rule_sets(election_dir))


def _obvod_seats(
    geo_dir: Path, rule_sets: Mapping[str, obvody.RuleSet]
) -> dict[str, int]:
    coarse = orjson.loads((geo_dir / geo.COARSE_FILE).read_bytes())
    seats = {o["id"]: o["seats"] for o in coarse["obvody"]}
    for code, rules in rule_sets.items():
        seats |= {f"oz:{code}/{n}": s for n, s in rules.seats.items()}
    return seats


def _sources_key(contest: Mapping[str, Any]) -> str:
    """Return the :func:`obvod_sources` area of *contest* ("" for none)."""
    if contest["kind"] == "zsk":
        return f"zsk-{contest['area']}"
    return str(contest["area"]) if contest["kind"] == "oz" else ""


def obvod_sources(
    election_dir: Path, rule_sets: Mapping[str, obvody.RuleSet]
) -> dict[str, list[list[str]]]:
    """Return area → the official documents that set its obvody.

    Areas are an obec (council obvody by address), ``BA``/``KE`` (city
    council) or ``zsk-<kraj>`` (regional council), as named by the curated
    files in *election_dir* and *rule_sets* (its council rule sets);
    documents are ``[title, url]``.
    """
    out = {}
    for path in sorted((election_dir / obvody.DIRECTORY).glob("*.toml")):
        listed = config.load_obvody(path)
        out[path.stem] = [[listed.title, listed.source]]
    for code, rules in rule_sets.items():
        out[code] = [[d.title, d.url] for d in rules.documents]
    return out


def origin_flags(
    props: Mapping[str, Mapping[str, Any]],
    rule_sets: Mapping[str, obvody.RuleSet],
    okrsky: Mapping[str, obvody.RuleSet],
    unknown: Collection[str],
) -> dict[str, dict[str, Any]]:
    """Return the :data:`ORIGINS` flags of ``data/index.json``: flag → obec → value.

    Those of the council obvody drawn (*props* of an obec with ``oz``,
    :func:`election_map_slovakia.obvody.council_origin`) and of the okrsky
    drawn: an obec whose okrsky are not drawn (*unknown*,
    ``okrsky_unknown``) says that instead
    (:func:`election_map_slovakia.obvody.okrsky_origin`).
    """
    origins: dict[str, dict[str, Any]] = defaultdict(dict)
    for c, r in rule_sets.items():
        if "oz" in props.get(c, {}):
            origins[c] |= obvody.council_origin(r)
    for c, r in okrsky.items():
        if c not in unknown:
            origins[c] |= obvody.okrsky_origin(r)
    return {
        key: {c: o[key] for c, o in sorted(origins.items()) if key in o}
        for key in ORIGINS
    }


def site_index(
    data: Mapping[str, Any],
    props: Mapping[str, Mapping[str, Any]],
    shards: Mapping[str, list[Any]],
    parties: Mapping[str, config.Party],
    slug: str,
    rule_sets: Mapping[str, obvody.RuleSet],
    okrsky: Mapping[str, obvody.RuleSet],
    places: Mapping[str, Any],
    part: Collection[str] = (),
) -> dict[str, Any]:
    """Return ``data/index.json``; see the module doc.

    *parties* is ``config/parties.toml``, whose logos of the election
    *slug* are named by their file below the app's; *rule_sets* the council obvod rule sets
    (:func:`election_map_slovakia.obvody.load_rule_sets`), *okrsky* the rule
    sets that give okrsky (:func:`election_map_slovakia.obvody.okrsok_rule_sets`);
    *places* what else the ballots say of an obec (:func:`place_facts`);
    *part* the obce of a by-election whose council contests are part of a
    larger council (:func:`council_count`).
    """
    named = named_parties(data)
    if missing := sorted(named - parties.keys()):
        raise BuildError(
            f"config/{config.PARTIES_FILE}: no entry for {', '.join(missing)}"
        )
    # A shared link's candidate filter names the parties by short form.
    by_short: dict[str, list[str]] = defaultdict(list)
    for name in sorted(named):
        by_short[parties[name].short].append(name)
    if shared := [names for names in by_short.values() if len(names) > 1]:
        raise BuildError(
            f"config/{config.PARTIES_FILE}: parties of one election share a short"
            f" form: {'; '.join(' / '.join(names) for names in shared)}"
        )
    councils = addresses.council_obvody(data["contests"])
    obce = {}
    for o in data["obce"]:
        code = o["code"]
        n = council_count(councils.get(code, ()), rule_sets.get(code), code in part)
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
        "uncontested": sorted(c["id"] for c in data["contests"] if "uncontested" in c),
        "estimated": sorted({c for c, p in props.items() if "estimated" in p}),
        **origin_flags(props, rule_sets, okrsky, places["okrsky_unknown"]),
        # Of the obce with several council obvody not drawn, those whose
        # document was searched for and not found.
        "not_found": sorted(
            c for c in places["not_found"] if "oz" not in props.get(c, {})
        ),
        "okrsky_unknown": places["okrsky_unknown"],
        "special": places["special"],
        "boundaries": places["boundaries"],
        "names": {prefix: len(rows) for prefix, rows in shards.items()},
        "parties": {
            name: [p.short, p.name] + ([p.logos[slug].file] if slug in p.logos else [])
            for name, p in sorted(parties.items())
            if name in named
        },
    }


def council_count(
    numbers: Collection[int], rules: obvody.RuleSet | None, part: bool
) -> int:
    """Return ``councils`` of ``data/index.json``: an obec's council obvody.

    *numbers* are those of its council contests. Where they are *part* of a
    larger council (a by-election's, :func:`addresses.part_councils`), its
    obvody are as many as its rule set (*rules*) has, else at least two: the
    obec is never taken for a council of one obvod, as its addresses are
    not (``addresses``: ``address`` or ``pending``).
    """
    if not part:
        return len(numbers)
    return max(len(rules.seats) if rules else 2, *numbers)


def named_parties(data: Mapping[str, Any]) -> set[str]:
    """Return the parties ``candidates.json`` *data* names.

    Those of its candidacies and the subjects of its party-list ballots.
    """
    return {p for c in data["candidacies"] for p in c["parties"]} | {
        s["party"] for c in data["contests"] for s in c.get("subjects", ())
    }


def held_areas(data: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return area → its contests held, of a by-election's ``candidates.json``.

    ``held`` of ``data/index.json``: a by-election has contests only where
    something is elected, each obec (or Bratislava, Košice) and kraj by
    its code; one called but held nowhere (``uncontested``) is not held.
    """
    held: dict[str, list[str]] = defaultdict(list)
    for c in data["contests"]:
        if "uncontested" not in c:
            held[c["area"]].append(c["id"])
    return {area: sorted(ids) for area, ids in sorted(held.items())}


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


BOUNDARIES_FILE = "boundaries.toml"
"""In an election's curated data, where it is drawn on the boundaries of
another: how they differ from its own (:func:`boundary_changes`)."""


def boundary_changes(election_dir: Path) -> dict[str, Any] | None:
    """Return how the boundaries an election is drawn on differ from its own.

    From ``boundaries.toml`` in its curated data (*election_dir*):
    ``{day, obce: {obec: [obec, ...]}}``, ``day`` the date its own
    boundaries are of, each obec whose land moved by more than redrawing
    mapped to the obce the land moved between, none where it moved along
    the state border. None without the file: drawn on its own boundaries.
    """
    path = election_dir / BOUNDARIES_FILE
    if not path.is_file():
        return None
    try:
        with path.open("rb") as f:
            table = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise BuildError(f"{path}: invalid TOML: {e}") from e
    obce: dict[str, list[str]] = {}
    # Boundaries that differ by redrawing alone list no change.
    for change in table.get("change", ()):
        codes = change["obce"]
        for code in codes:
            obce[code] = (
                [] if change.get("state_border") else [c for c in codes if c != code]
            )
    return {"day": str(table["compared"]), "obce": dict(sorted(obce.items()))}


def several_okrsky(live: Live | None, without: Collection[str] = ()) -> set[str]:
    """Return the obce that voted in several okrsky, by the final results.

    *live* is those results (:func:`final_okrsky`), None before them (then
    none is known), by the okrsky of the contests that cover an obec whole,
    those not split into obvody: its mayor's, its kraj's president's (a
    kraj is made of whole obce; a regional-only election has nothing
    else), or the country-wide ones; of the okrsky with territory, those
    not in *without* (the special okrsky, ``<obec>/<n>``,
    :mod:`election_map_slovakia.special`), which the map never draws.
    """
    numbers: dict[str, set[str]] = defaultdict(set)
    for files in live.okrsky.values() if live else ():
        for contest, areas in files.items():
            if contests.parse(contest).kind.sub != "obvod":
                for key in areas:
                    if key not in without:
                        obec, _, n = key.partition("/")
                        numbers[obec].add(n)
    return {obec for obec, ns in numbers.items() if len(ns) > 1}


def place_facts(
    cfg: Config,
    election: config.Election,
    several: Collection[str],
    drawn: Collection[str],
    specials: special.Specials,
    live: Live | None,
) -> dict[str, Any]:
    """Return what the ballots of an obec say of its data besides the rules.

    ``not_found``: the obce whose council obvod document was searched for
    and not found (:func:`election_map_slovakia.obvodrules.load_not_found`);
    ``okrsky_unknown``: of the obce that voted in *several* okrsky
    (:func:`several_okrsky`), those whose okrsky the map does not draw
    (*drawn*, ``geo`` index ``okrsky.drawn``); ``boundaries``
    (:func:`boundary_changes`) with ``on``, the slug of the election whose
    boundaries are drawn (:func:`drawn_on`); ``special``, its special
    okrsky *specials* that voted, by the final results *live*
    (:func:`special_okrsky`).
    """
    from election_map_slovakia import obvodrules  # it imports what imports this

    changes = boundary_changes(cfg.election_dir(election))
    return {
        "not_found": sorted(obvodrules.load_not_found(cfg, election)),
        "okrsky_unknown": sorted(set(several) - set(drawn)),
        "boundaries": changes and {**changes, "on": drawn_on(cfg, election).slug},
        "special": special_okrsky(specials, live),
    }


def special_okrsky(
    specials: special.Specials, live: Live | None
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return ``special`` of ``data/index.json``: obec → okrsok → what it is.

    Of *specials* (:mod:`election_map_slovakia.special`), those the final
    results *live* have (none before them): ``kind``, ``voters`` on the
    roll, ``title`` and ``url`` of what explains it, and of a COVID-19
    special okrsok its ``okresy`` (the okresy whose special okrsky the obec
    holds), of a prison's the ``facility``. A COVID-19 special okrsok voted
    only where a voter asked for one (ŠÚ SR's ``Áno``): the obec's special
    okrsky with results must be as many as voted, a prison's must have
    them, else the package, the curated facts and the results disagree.
    """
    if live is None:
        return {}
    voters: dict[str, int] = {}
    for files in live.okrsky.values():
        for areas in files.values():
            for key, (eligible, *_) in areas.items():
                if eligible is not None:
                    voters.setdefault(key, eligible)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for obec, okrsky in specials.items():
        found = {n: s for n, s in okrsky.items() if f"{obec}/{n}" in voters}
        # The obec's COVID-19 special okrsky share their okresy, which of
        # them is whose not being told.
        covid = next((s for s in okrsky.values() if s.kind == special.COVID), None)
        voted = sum(s.kind == special.PRISON for s in okrsky.values()) + (
            sum(v for _, v in covid.okresy) if covid else 0
        )
        if len(found) != voted:
            raise BuildError(
                f"obec {obec}: special okrsky {sorted(okrsky)}, of which the results"
                f" have {sorted(found)}, but {voted} voted"
            )
        out[obec] = {
            str(n): {
                "kind": s.kind,
                "voters": voters[f"{obec}/{n}"],
                "title": s.title,
                "url": s.url,
                **(
                    {"facility": s.facility}
                    if s.kind == special.PRISON
                    else {"okresy": [name for name, _ in s.okresy]}
                ),
            }
            for n, s in found.items()
        }
    return {obec: k for obec, k in out.items() if k}


def election_inputs(election: config.Election) -> set[str]:
    """Return the names of the inputs (``inputs.toml``) *election* names."""
    return {
        *(election.candidates.inputs.values() if election.candidates else ()),
        *(election.incumbents.inputs if election.incumbents else ()),
        *((election.units.input,) if election.units else ()),
        *election.results.inputs,
        election.addresses,
        *election.zbgis,
        election.osm,
        *election.records,
    }


def drawn_on(cfg: Config, election: config.Election) -> config.Election:
    """Return the election whose boundaries *election* is drawn on.

    The newest that names the same ZBGIS inputs: itself, or a later one
    whose boundaries stand in (``boundaries.toml`` says how they differ).
    """
    return next(e for e in cfg.elections if e.zbgis == election.zbgis)


def substitutes(
    cfg: Config,
    election: config.Election,
    index: Mapping[str, Any],
    several: Collection[str],
    persons: tuple[int, int],
    records: Mapping[str, Any],
    *,
    researched: bool,
) -> dict[str, Any]:
    """Return what *election*, not the latest, takes from the latest, and lacks.

    About's ``substitutes`` (module doc): *index* is its ``data/index.json``
    (:func:`site_index`), *several* the obce that voted in several okrsky
    (:func:`several_okrsky`), *persons* how many of its persons are linked
    to the latest's, and of how many; *records* its research, its own where
    *researched*, else that reused for them (:func:`reused_research`).
    """
    inputs = {i.name: i for i in cfg.inputs.inputs}
    obce = index["obce"]
    names = functools.partial(sorted, key=candidates.search_key)
    # The council obvody of Bratislava and Košice are the curated ones.
    councils = [
        c for c, row in obce.items() if row[4] > 1 and c not in candidates.CITY_CODES
    ]
    by_address = set(index["by_address"])
    other = index["reused"].keys() | index["adopted"].keys()
    changes = index["boundaries"]
    return {
        "latest": cfg.latest.slug,
        "boundaries": changes
        and {
            "zbgis": drawn_on(cfg, election).slug,
            "day": changes["day"],
            "obce": names(obce[c][0] for c in changes["obce"]),
        },
        "osm": inputs[election.osm].as_of,
        "addresses": inputs[election.addresses].as_of,
        "obvody": {
            "several": len(councils),
            "own": sum(c in by_address and c not in other for c in councils),
            "reused": names(obce[c][0] for c in index["reused"]),
            "unknown": sum(c not in by_address for c in councils),
            "not_found": len(index["not_found"]),
            "approximate": len(index["date_approximate"]),
            "supplemented": len(index["supplemented"]),
        },
        "okrsky": {
            "several": len(several),
            "unknown": len(index["okrsky_unknown"]),
            "reused": len(index["okrsky_reused"]),
            "referendum": len(index["okrsky_referendum"]),
            "approximate": len(index["okrsky_date_approximate"]),
            "supplemented": len(index["okrsky_supplemented"]),
            # The years of the elections whose okrsky stand in.
            "reused_from": sorted({d[:4] for d in index["okrsky_reused"].values()}),
        },
        "persons": list(persons),
        "research": [
            len(records),
            sum(bool(r["findings"]) for r in records.values()),
            sum(len(r["findings"]) for r in records.values()),
            sum(r.get("undated", 0) for r in records.values()),
        ],
        "research_own": researched,
    }


def stand_ins(index: Mapping[str, Any]) -> dict[str, list[list[Any]]]:
    """Return About's ``stand_ins``: the obce whose units another vote's stand in for.

    Of *index* (``data/index.json``, :func:`site_index`), per kind of unit,
    ``[day, [name, ...]]`` by the day of the vote whose borders they are
    (``adopted``, ``okrsky_adopted``; the app names that vote), earliest
    first.
    """
    names = functools.partial(sorted, key=candidates.search_key)
    out = {}
    for units, flag in (("obvody", "adopted"), ("okrsky", "okrsky_adopted")):
        by_day: dict[str, list[str]] = defaultdict(list)
        for code, day in index[flag].items():
            by_day[day].append(index["obce"][code][0])
        out[units] = [[day, names(n)] for day, n in sorted(by_day.items())]
    return out


def about(
    cfg: Config,
    election: config.Election,
    data: Mapping[str, Any],
    records: Mapping[str, Any],
    rule_sets: Mapping[str, obvody.RuleSet],
    replaced: Mapping[str, Any] | None,
    standing: Mapping[str, Any],
) -> dict[str, Any]:
    """Return ``data/about.json``: what the About dialog lists from the config.

    *election* is the page's: its inputs are listed, with the day their
    pinned file was retrieved and those no election names (the countries
    around), and its curated obvod files. *data* is ``candidates.json``,
    for the names of the areas of the curated obvod files. *records* is
    the curated research (:func:`research_records`), counted per research
    language: candidates researched and those with findings. *rule_sets*
    are the council rule sets (:func:`obvody.load_rule_sets`). *replaced*
    is what an election other than the latest takes from it
    (:func:`substitutes`), None for the latest; *standing* the stand-ins
    (:func:`stand_ins`).
    """
    election_dir = cfg.election_dir(election)
    parties = named_parties(data)
    named = {n for e in cfg.elections for n in election_inputs(e)}
    own = election_inputs(election)
    inputs = []
    for i in cfg.inputs.inputs:
        if i.name in named and i.name not in own:
            continue
        entry = {"name": i.name, "url": i.url}
        if i.retrieved is not None:
            entry["retrieved"] = i.retrieved.isoformat()
        inputs.append(entry)
    names = {f"zsk-{k['code']}": k["name"] for k in data["kraje"]}
    names |= {
        o["code"]: o["name"] for o in data["obce"] if o["code"] in candidates.CITY_CODES
    }
    membership = []
    for path in sorted((election_dir / obvody.DIRECTORY).glob("*.toml")):
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
            rule_sets.values(), key=lambda r: (candidates.search_key(r.name), r.obec)
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
        # author and license wherever they are shown: those of the election.
        "logos": [
            {"name": p.short, "source": logo.source, "license": logo.license}
            for name, p in sorted(
                cfg.parties.items(), key=lambda item: item[1].short.casefold()
            )
            if name in parties and (logo := p.logos.get(election.slug))
        ],
        "obvody": membership,
        "council": council,
        "research": [
            [
                lang,
                list(categories),
                sum(research.done(r, categories) for r in records.values()),
                sum(
                    any(f["category"] in categories for f in r["findings"])
                    for r in records.values()
                ),
            ]
            for lang, categories in sources.research.items()
        ],
        # How the candidate lists were read (elections.toml): the method
        # section says where they come from. A referendum has none.
        "candidates": election.candidates and election.candidates.format,
        "substitutes": replaced,
        "stand_ins": standing,
    }


def _built(cfg: Config, election: config.Election) -> dict[str, Path]:
    """Return step → what it made of *election*, which the build reads."""
    directory = cfg.election_build_dir(election)
    paths = {
        "candidates": directory / candidates.OUTPUT_FILE,
        "geo": directory / geo.OUTPUT_DIR,
        "addresses": directory / addresses.OUTPUT_DIR,
        "links": directory / LINKS_DIR,
    }
    for step, path in paths.items():
        if not path.exists():
            raise BuildError(f"{path} missing; run `ems {step}` first")
    return paths


@dataclass(frozen=True)
class _Shared:
    """What an election's data bundle is made of besides its own build output.

    Picked out of every election's in the main process, each election's
    bundle being made in a worker process (:func:`_data_bundle`).
    """

    records: Mapping[str, Any]
    """The research it shows: its own, else the latest election's of its
    persons linked to the latest's (see :func:`_election_research`)."""
    researched: bool
    """It was researched in its own right."""
    linked: int
    """How many of its persons are linked to the latest election's."""
    other: Mapping[str, Mapping[str, list[list[Any]]]]
    """Its persons' candidacies in other elections (:func:`elsewhere`)."""
    translations: Mapping[str, translate.Curated]
    """Language → its curated translations of its occupations and of the
    texts of *records* (:func:`_translations_of`)."""


def _election_research(
    cfg: Config,
    election: config.Election,
    records: Mapping[str, Mapping[str, Any]],
    persons: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> tuple[Mapping[str, Any], bool]:
    """Return the research *election* shows, and whether it is its own.

    *records* are the curated research by election (:func:`research_records`),
    *persons* the persons linked across elections (:func:`linked_persons`).
    """
    # The curated research names the election whose candidates it
    # researched (the ids of another election's persons can match by chance:
    # same obec, name and age). An election researched in its own right
    # shows its own; any other, its persons linked to the latest's
    # researched ones get theirs, as of its last round's day.
    latest = cfg.latest
    own = records.get(election.day.isoformat(), {})
    if own or election == latest:
        return own, bool(own)
    reused = reused_research(
        records.get(latest.day.isoformat(), {}),
        persons.get(latest.slug, {}).get(election.slug, {}),
        election.last_day.isoformat(),
    )
    return reused, False


def _translations_of(
    translations: Mapping[str, translate.Curated],
    occupations: Collection[str],
    records: Mapping[str, Any],
) -> dict[str, translate.Curated]:
    """Return *translations* of *occupations* and of the texts of *records*.

    All that :func:`occupation_files` and :func:`research_files` look up
    (:func:`_finding_row`: English claims and quotes): the whole of them
    sent to each worker process was 23 MB.
    """
    texts = {
        text
        for record in records.values()
        for f in record.get("findings", ())
        for text in (f["claim"].get("en"), f["quote"])
    }
    return {
        code: translate.Curated(
            occupations={
                o: t.occupations[o] for o in occupations if o in t.occupations
            },
            research={text: t.research[text] for text in texts if text in t.research},
        )
        for code, t in translations.items()
    }


def _occupations(data: Mapping[str, Any]) -> set[str]:
    """Return the occupations of the candidates of ``candidates.json`` *data*."""
    return {c["occupation"] for c in data["candidacies"]} - {""}


def _candidacy_results(cfg: Config, election: config.Election) -> dict[str, list[Any]]:
    """Return :func:`candidacy_results` of *election*, read in a worker process."""
    built = cfg.election_build_dir(election) / candidates.OUTPUT_FILE
    final = final_contests(cfg.results_dir(election))
    return candidacy_results(final or {}, orjson.loads(built.read_bytes()))


def _data_bundle(
    cfg: Config, election: config.Election, shared: _Shared
) -> tuple[dict[str, bytes], dict[str, int]]:
    """Return *election*'s generated files, encoded, and its untranslated counts.

    Path below its data bundle → content (:func:`_election_files`), and
    language → how many of its occupations are not translated into it. Run
    in a worker process, which reads the election's own build output.
    """
    directory = cfg.election_build_dir(election)
    data = orjson.loads((directory / candidates.OUTPUT_FILE).read_bytes())
    content = _election_files(
        cfg,
        election,
        data,
        directory / geo.OUTPUT_DIR,
        shared,
        final_contests(cfg.results_dir(election)),
    )
    untranslated = {
        path.split("/")[1].removesuffix(".json"): value["missing"]
        for path, value in content.items()
        if path.startswith(f"{I18N_DIR}/") and isinstance(value, dict)
    }
    return {path: encode(value) for path, value in content.items()}, untranslated


def _election_files(
    cfg: Config,
    election: config.Election,
    data: Mapping[str, Any],
    geo_dir: Path,
    shared: _Shared,
    final: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, object]:
    """Return *election*'s generated JSON, path below its bundle → content.

    *data* is its ``candidates.json``, *geo_dir* its ``geo`` output, *final*
    its final results (:func:`final_contests`).
    """
    curated = cfg.election_dir(election)
    # A country-wide election's council rule sets only give its okrsky
    # (copied from a municipal election's, reuse.py): it has no councils.
    councils = any(c["kind"] == "oz" for c in data["contests"])
    loaded = obvody.load_rule_sets(curated)
    rule_sets = loaded if councils else {}
    props = obec_props(geo_dir)
    records = shared.records
    latest = cfg.latest
    live = final_okrsky(cfg.results_dir(election))
    content: dict[str, object] = {}
    # A by-election's council contests may be some obvody of a council only.
    part = addresses.council_parts(cfg, election, data["contests"])
    content |= area_files(
        data,
        _obvod_seats(geo_dir, rule_sets),
        obvod_sources(curated, rule_sets),
        research_summary(cfg, records),
        regional_past(data, props) | council_past(data, live),
        no_result(final, data),
        shared.other,
        day=election.day.isoformat(),
        parties=cfg.parties,
        part=part,
    )
    content |= research_files(
        cfg,
        data,
        records,
        {code: t.research for code, t in shared.translations.items()},
    )
    shards = name_shards(data)
    content |= {f"{DATA_DIR}/names/{p}.json": rows for p, rows in shards.items()}
    from election_map_slovakia import okrsokrules  # it imports what imports this

    # Only the final results tell which special okrsky voted.
    specials = okrsokrules.special_okrsky(cfg, election) if live else {}
    several = several_okrsky(live, special.keys(specials))
    drawn = orjson.loads((geo_dir / "index.json").read_bytes())["okrsky"]["drawn"]
    index = site_index(
        data,
        props,
        shards,
        cfg.parties,
        election.slug,
        rule_sets,
        obvody.okrsok_rule_sets(curated, loaded),
        place_facts(cfg, election, several, drawn, specials, live),
        part,
    )
    if election.kind == config.BY_ELECTION:
        index["held"] = held_areas(data)
    content[f"{DATA_DIR}/index.json"] = index
    replaced = (
        None
        if election == latest
        else substitutes(
            cfg,
            election,
            index,
            several,
            (shared.linked, len(data["persons"])),
            records,
            researched=shared.researched,
        )
    )
    content[f"{DATA_DIR}/about.json"] = about(
        cfg, election, data, records, rule_sets, replaced, stand_ins(index)
    )
    content |= occupation_files(shared.translations, _occupations(data))
    return content


def occupation_files(
    translations: Mapping[str, translate.Curated], occupations: Collection[str]
) -> dict[str, dict[str, Any]]:
    """Return a bundle's ``i18n/<lang>.json``: its occupations translated.

    *occupations* are those of the election's candidates, in Slovak, which
    every other language of *translations* (language → its curated
    translations) gets where translated: ``{occupations: {Slovak:
    translation}, missing}``, ``missing`` how many are not translated yet
    (the app says the translation is incomplete then).
    """
    out = {}
    for code, curated in translations.items():
        if code == translate.REFERENCE:
            continue
        translated = {
            o: curated.occupations[o]
            for o in sorted(occupations)
            if o in curated.occupations
        }
        out[f"{I18N_DIR}/{code}.json"] = {
            "occupations": translated,
            "missing": len(occupations) - len(translated),
        }
    return out


def final_contests(results_dir: Path) -> dict[str, dict[str, Any]] | None:
    """Return contest → its record in the final results in *results_dir*.

    None before the results are final (or without any); see docs/results.md.
    """
    from election_map_slovakia import results  # results imports this module

    st = results.read_status(results_dir) if results_dir.is_dir() else None
    if st is None or st.get("phase") != "final":
        return None
    return {
        contest: record
        for path in st["files"]
        if not path.startswith(f"{results.OKRSKY_DIR}/")
        and path != results.TURNOUT_FILE
        for contest, record in orjson.loads(
            (results_dir / f"{path}.json").read_bytes()
        )["contests"].items()
    }


def no_result(
    final: Mapping[str, Mapping[str, Any]] | None, data: Mapping[str, Any]
) -> set[str]:
    """Return the contests of *data* that the *final* results lack.

    Where a contest had candidates but the count could not be completed (in
    2022, Krušovce: its commission drew up no record and the election was
    held again), the final results (:func:`final_contests`) have no record
    of it; one held nowhere (``uncontested``) has none to have. None before
    the results are final.
    """
    if final is None:
        return set()
    held = {c["id"] for c in data["contests"] if "uncontested" not in c}
    return held - final.keys()


def bundles(
    cfg: Config,
    map_keys: Mapping[str, str | None],
    data_keys: Mapping[str, str | None],
    base_keys: Mapping[str, str | None],
) -> tuple[dict[str, Part], dict[str, Part], dict[str, Part]]:
    """Return the map and data bundles by slug, and the base maps by extract.

    The extracts are those of :attr:`config.Config.bases`. See the module doc.
    *map_keys*, *data_keys* and *base_keys* are the parts' keys
    (:func:`election_map_slovakia.lock.keys`) by slug or extract, which
    their manifests name; None where the repository does not determine
    them (an input not pinned yet).

    Each election's data bundle is made, and its map bundle and each base
    map read and hashed, in a worker process
    (:mod:`election_map_slovakia.parallel`), once what they share is put
    together here: its persons' candidacies elsewhere need every
    election's results, which workers read first.
    """
    built = {e.slug: _built(cfg, e) for e in cfg.elections}
    bases = {osm: _built_base(cfg, osm) for osm in cfg.bases}
    with progress.stage("making the bundles"):
        datas = {
            e.slug: orjson.loads(built[e.slug]["candidates"].read_bytes())
            for e in cfg.elections
        }
        persons = linked_persons(
            {
                (e.slug, path.stem): orjson.loads(path.read_bytes())
                for e in cfg.elections
                for path in sorted(built[e.slug]["links"].glob("*.json"))
            }
        )
        results = parallel.each(_candidacy_results, [(cfg, e) for e in cfg.elections])
        others = elsewhere(datas, persons, dict(zip(datas, results, strict=True)))
        records = research_records(cfg)
        translations = {code: translate.load(cfg, code) for code in cfg.languages.codes}
        shared = {}
        for e in cfg.elections:
            research, own = _election_research(cfg, e, records, persons)
            shared[e.slug] = _Shared(
                research,
                own,
                len(persons.get(e.slug, {}).get(cfg.latest.slug, {})),
                others[e.slug],
                _translations_of(translations, _occupations(datas[e.slug]), research),
            )
        del datas
        copies = {
            e.slug: {
                geo.OUTPUT_DIR: built[e.slug]["geo"],
                addresses.OUTPUT_DIR: built[e.slug]["addresses"],
            }
            for e in cfg.elections
        }
        # The data bundles first: a few take far longer than any map's.
        done = list(
            parallel.each(
                parallel.call,
                [
                    *((_data_bundle, cfg, e, shared[e.slug]) for e in cfg.elections),
                    *((copied_files, copies[e.slug]) for e in cfg.elections),
                    *((copied_files, files) for files in bases.values()),
                ],
            )
        )
    web = cfg.root / WEB_DIR
    maps, data = {}, {}
    count = len(cfg.elections)
    for election, (own, untranslated), (version, names, known) in zip(
        cfg.elections, done[:count], done[count : 2 * count], strict=True
    ):
        slug = election.slug
        manifest: dict[str, Any] = {
            "key": map_keys.get(slug),
            "election": election.day.isoformat(),
            "version": version,
            "files": names,
        }
        # Served as the data are: web/_headers-data.
        maps[slug] = Part(
            _part_files(web, DATA_PART) | {MANIFEST: encode(manifest)},
            copies[slug],
            known,
        )
        generated = sorted(own.items())
        manifest = {
            "key": data_keys.get(slug),
            "election": election.day.isoformat(),
            "version": content_version(generated),
            "occupations": untranslated,
            "files": [path for path, _ in generated],
        }
        data[slug] = Part(
            own | _part_files(web, "data") | {MANIFEST: encode(manifest)}, {}
        )
    base_parts = {}
    for (osm, base_copies), (version, names, known) in zip(
        bases.items(), done[2 * count :], strict=True
    ):
        manifest = {
            "key": base_keys.get(osm),
            "base": osm,
            "version": version,
            "files": names,
        }
        base_parts[osm] = Part(
            _part_files(web, DATA_PART) | {MANIFEST: encode(manifest)},
            base_copies,
            known,
        )
    return maps, data, base_parts


def _built_base(cfg: Config, osm: str) -> dict[str, Path]:
    """Return the base map of extract *osm* to copy: its files and directories.

    Each by its path below the part, which is the base map's directory in
    ``data/build/`` (:meth:`config.Config.base_build_dir`).
    """
    source = cfg.base_build_dir(osm) / basemap.OUTPUT_DIR
    if not source.is_dir():
        raise BuildError(f"{source} missing; run `ems basemap` first")
    return {path.name: path for path in sorted(source.iterdir())}


def cited(cfg: Config) -> set[str]:
    """Return the names of the cached copies of the pages research cites."""
    root = cfg.curated_dir / research.CURATED_DIR
    return {
        finding["cache"]
        for path in sorted(root.glob("*/*.json"))
        for finding in orjson.loads(path.read_bytes())["findings"]
    }


def sources_part(cfg: Config, key: str | None) -> Part:
    """Return the sources part; see the module doc. *key* is its key."""
    from election_map_slovakia import cache  # cache imports what imports this

    web = cfg.root / WEB_DIR
    cached = cfg.curated_dir / research.CACHE_DIR
    copies = {
        f"{CACHE_DIR}/{name}.html": cached / f"{name}.html"
        for name in sorted(cited(cfg))
    }
    copies[cache.STYLESHEET.removeprefix("/")] = web / "cache.css"
    return Part(_part_files(web, "sources") | {MANIFEST: encode({"key": key})}, copies)


def results_part(cfg: Config, key: str | None) -> Part:
    """Return the results part; see the module doc. *key* is its key."""
    copies = {
        e.day.isoformat(): cfg.results_dir(e)
        for e in cfg.elections
        if cfg.results_dir(e).is_dir()
    }
    web = cfg.root / WEB_DIR
    return Part(_part_files(web, "results") | {MANIFEST: encode({"key": key})}, copies)


def live_part(cfg: Config) -> Part:
    """Return the live part; see the module doc."""
    from election_map_slovakia import results  # results imports this module

    copies = {
        e.day.isoformat(): cfg.live_dir(e)
        for e in cfg.elections
        if cfg.live_dir(e).is_dir()
    }
    versions = {
        day: (results.read_status(directory) or {}).get("version")
        for day, directory in copies.items()
    }
    web = cfg.root / WEB_DIR
    return Part(
        _part_files(web, "live") | {MANIFEST: encode({"versions": versions})}, copies
    )


def _part_files(web: Path, part: str) -> dict[str, bytes]:
    """Return the response headers and 404 page of data part *part*."""
    return {
        HEADERS: (web / f"{HEADERS}-{part}").read_bytes(),
        NOT_FOUND: (web / "part-404.html").read_bytes(),
    }
