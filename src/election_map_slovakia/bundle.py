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
``basemap``, ``addresses``, ``links`` and ``results``), the curated data
and the configuration: its map, which depends on that election alone and
so seldom changes, and its data, which depends on every election (the
persons linked across them, the research reused). The app fetches each
bundle's files below its address (km-config ``map`` and ``data``;
locally ``/map/<slug>`` and ``/data/<slug>``, deployed the address of the
deployment that carries its key), with ``?v=`` its version (``mapVersion``,
``dataVersion``). Paths below are relative to the bundle. Both have::

    manifest.json            {key, election, version, files}: the key the
                             bundle was built for, the election day, a
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
    base/                    data/build/<day>/base/, verbatim: the base map
                             (see basemap)
    addr/                    data/build/<day>/addr/, verbatim (see addresses)

The data bundle, ``dist/data/<slug>/``::

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
(:func:`results_part`), holds ``<day>/``, each election's
data/build/<day>/results/ verbatim where there is one (``Config.results_dir``;
see results.py and docs/results.md). Each has its ``_headers``
(web/_headers-sources, web/_headers-results), ``404.html`` and a
``manifest.json`` with its key.

Each contest is in exactly one area file, so a click loads the okres, kraj
and (in Bratislava and Košice) city file of one place and nothing twice::

    data/<area>.json  {contests: {contest: {(seats), (sources), (holder),
                          (incumbents), (past), (no_result),
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
(:func:`no_result`). ``sources`` are the official
documents that set a council's obvody, as ``[title, url]``
(:func:`obvod_sources`). ``residence`` is the obec of residence of
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
are not final, or whose contest has none, is ``[candidacy]`` alone.
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
                      okrsky_referendum: {obec: day},
                      okrsky_date_approximate: {obec: {by, (seen)}},
                      okrsky_supplemented: {obec: {from, day}},
                      not_found: [obec, ...],
                      okrsky_unknown: [obec, ...],
                      boundaries: {day, on, obce: {obec: [obec, ...]}} | null,
                      names: {prefix: persons},
                      parties: {party: [short, name, (logo)]}}

    data/about.json  {sources, inputs: [{name, url, (retrieved)}],
                      logos, obvody, council, research, candidates: format,
                      substitutes: {...} | null}

``councils`` is the number of municipal council obvody (0: no council
election); ``by_address`` lists the obce whose council obvod goes by
address (``addresses``: ``council`` ``"address"``) and whose shard
features are their obvody (``geo``); ``estimated`` those of them whose
rule set is a guess (``geo``: ``estimated``); ``reused`` those whose rule
set is another election's, with that election's ISO day (no document of
this election was found, and the layout provably matches, see
:mod:`election_map_slovakia.reuse`); ``adopted`` those whose rule set is a
later election's, with its day, though the layout is not proven to match
(no usable document of this election places the addresses, only the
obvod numbers and seats are known to be the same: the borders are
indicative only); ``date_approximate`` those whose
documents state no date, with what dates them approximately (``by``: an
Internet Archive capture, a posting on the official page, the document
naming the election; ``seen``: the day of the first two;
:class:`election_map_slovakia.obvody.Dating`); ``supplemented`` those
whose documents do not place every address, where rules from a later
source fill them in (``from``: a later election's rule set, a
referendum's or another later document; ``day``: that vote's day or the
document's date; :class:`election_map_slovakia.obvody.Supplement`).
``okrsky_reused``, ``okrsky_adopted`` and ``okrsky_referendum`` give the
obce whose okrsky are another election's (proven to match, or not), or
from a referendum's document, with its day, and
``okrsky_date_approximate`` and ``okrsky_supplemented`` those whose okrsky
document is dated so, or filled in so
(:func:`election_map_slovakia.obvody.okrsky_origin`), of the obce whose
okrsky are drawn; ``not_found`` the
obce of several council obvody without a rule set whose document was
searched for and not found; ``okrsky_unknown`` the obce that voted in
several okrsky none of which is drawn (:func:`place_facts`);
``boundaries``, for an election drawn on a later one's boundaries (``on``,
its slug), the obce whose land moved since ``day``
(:func:`boundary_changes`);
About's ``inputs`` are those the election names and those no election
names; ``substitutes``, for an election before the latest, what it takes
from the latest and what it lacks, with counts (:func:`substitutes`);
``okres`` is ``""`` and ``zsk`` 0 for Bratislava and Košice
themselves. A name shard holds every person with a name word (first name or
surname, :func:`election_map_slovakia.candidates.search_key`) starting with its two-letter
prefix, as ``[name, age, [candidacy, ...]]`` sorted by surname, the name and
age being those of the person's first candidacy; ``names`` maps each prefix
to its person count, so the search picks the smallest shard among the words
of a query. ``parties`` gives every party named in a candidacy its short
form, official name and logo at this election (``config/parties.toml``
``logo.<slug>``; a file name below the app's party logos, km-config
``logos``); About's ``logos`` credit those logos.
"""

from __future__ import annotations

import bisect
import functools
import hashlib
import itertools
import json
import re
import tomllib
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from election_map_slovakia import (
    addresses,
    basemap,
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

if TYPE_CHECKING:
    from election_map_slovakia.results import Live

# Hex digits of the bundles' and the app's asset versions: 40 bits, so two
# releases sharing a version by chance is not a concern.
VERSION_DIGITS = 10
MAP_PART = "map"
"""Below ``dist/``: the map bundle of each election, ``<slug>/``."""
DATA_PART = "data"
"""Below ``dist/``: the data bundle of each election, ``<slug>/``."""
SOURCES_PART = "sources"
"""Below ``dist/``: the sources part."""
RESULTS_PART = config.RESULTS_DIR
"""Below ``dist/``: the results part."""
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
MAP_ROOTS = (geo.OUTPUT_DIR, basemap.OUTPUT_DIR, addresses.OUTPUT_DIR)
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


@dataclass(frozen=True)
class Part:
    """What ``build`` writes of one part: path below it → content.

    *copies* are directories and files copied verbatim: path → source.
    """

    files: dict[str, bytes]
    copies: dict[str, Path]


def encode(content: object) -> bytes:
    """Return *content* as compact, key-sorted UTF-8 JSON."""
    return output.to_json(content, sort_keys=True)


def tree(name: str, source: Path) -> Iterator[tuple[str, bytes]]:
    """Yield (path, content) of the file or directory tree *source*.

    A path is *name* for a file, else *name*/<path below *source*>, in
    sorted order, so that :func:`content_version` sees a stable sequence.
    Threads read the files of a directory side by side: one by one, the
    thousands of data files took more than a second.
    """
    if not source.exists():
        raise BuildError(f"{source} missing")
    if source.is_file():
        yield name, source.read_bytes()
        return
    paths = sorted(p for p in source.rglob("*") if p.is_file())
    with ThreadPoolExecutor() as pool:
        for path, content in zip(paths, pool.map(Path.read_bytes, paths), strict=True):
            yield f"{name}/{path.relative_to(source).as_posix()}", content


def content_version(files: Iterable[tuple[str, bytes]]) -> str:
    """Return a short hash of the (path, content) pairs *files*, in order.

    Paths count as well as contents: a file renamed is a new version.
    """
    digest = hashlib.sha256()
    for path, content in files:
        digest.update(f"{path}\0{len(content)}\0".encode())
        digest.update(content)
    return digest.hexdigest()[:VERSION_DIGITS]


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
    if "residence" in c:
        row.append(c["residence"])
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


def candidacy_results(final: Mapping[str, Mapping[str, Any]]) -> dict[str, list[Any]]:
    """Return candidacy → ``[votes, valid, rank, of, flag]`` (see the module doc).

    *final* maps contests to their final results (:func:`final_contests`).
    """
    out = {}
    for contest, record in final.items():
        rows = record["candidates"]
        # Most votes first, negated so that bisect finds the votes' place.
        order = sorted(-v for _, v, _ in rows)
        for number, v, flag in rows:
            # Equal votes, equal rank: one more than those with more votes.
            rank = 1 + bisect.bisect_left(order, -v)
            out[f"{contest}#{number}"] = [v, record["valid"], rank, len(rows), flag]
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
) -> dict[str, dict[str, Any]]:
    """Return the candidate area files; see the module doc.

    *data* is ``candidates.json``; *seats* maps obvod contests to their seat
    count where known; *sources* is :func:`obvod_sources`; *researched* maps
    persons to their research summary (:func:`research_summary`); *pasts*
    maps contests to the ``past`` made here (:func:`regional_past`,
    :func:`council_past`), which replaces theirs; *no_result* names the
    contests the final results have none of (:func:`no_result`); *other*
    maps persons to their candidacies in other elections (:func:`elsewhere`).
    """
    sources = sources or {}
    researched = researched or {}
    pasts = pasts or {}
    other = other or {}
    okres_of = _okres_of(data)
    files: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"contests": {}, "persons": {}}
    )
    path_of: dict[str, str] = {}
    council_obvody = Counter(c["area"] for c in data["contests"] if c["kind"] == "oz")
    for contest in data["contests"]:
        path = path_of[contest["id"]] = area_file(contest, okres_of)
        entry = files[path]["contests"][contest["id"]] = _contest_entry(
            contest,
            seats,
            sources,
            pasts.get(contest["id"]),
            single=council_obvody[contest["area"]] == 1,
        )
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
    return dict(files)


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
    """
    entry: dict[str, Any] = {"candidates": []}
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


def council_past(
    data: Mapping[str, Any], live: Live | None
) -> dict[str, dict[str, Any]]:
    """Return council obvod contest → its ``past``, of its own okrsky.

    For each obvod of a council of several whose ``past`` is of the
    election its final results (*live*, :func:`final_okrsky`) compare its
    okrsky with (``past`` of the okrsok files, :mod:`crosswalk`): the
    earlier figures of its okrsky added up, an obec wholly in it as a
    whole, where all are known, with ``scope`` ``[method]``, the least
    certain method of its okrsky (``results.PAST_DOUBT``). Otherwise its
    ``past``
    stays that of the whole municipality or city.
    """
    from election_map_slovakia import results  # results imports this module

    if live is None or not live.past.day:
        return {}
    past = live.past
    keys_of = {c: areas for files in live.okrsky.values() for c, areas in files.items()}
    councils = Counter(c["area"] for c in data["contests"] if c["kind"] == "oz")
    out: dict[str, dict[str, Any]] = {}
    for c in data["contests"]:
        whole = c.get("past")
        if c["kind"] != "oz" or councils[c["area"]] == 1 or whole is None:
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
    coarse = json.loads((geo_dir / geo.COARSE_FILE).read_bytes())
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
) -> dict[str, Any]:
    """Return ``data/index.json``; see the module doc.

    *parties* is ``config/parties.toml``, whose logos of the election
    *slug* are named by their file below the app's; *rule_sets* the council obvod rule sets
    (:func:`election_map_slovakia.obvody.load_rule_sets`), *okrsky* the rule
    sets that give okrsky (:func:`election_map_slovakia.obvody.okrsok_rule_sets`);
    *places* what else the ballots say of an obec (:func:`place_facts`).
    """
    named = {p for c in data["candidacies"] for p in c["parties"]}
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
        **origin_flags(props, rule_sets, okrsky, places["okrsky_unknown"]),
        # Of the obce with several council obvody not drawn, those whose
        # document was searched for and not found.
        "not_found": sorted(
            c for c in places["not_found"] if "oz" not in props.get(c, {})
        ),
        "okrsky_unknown": places["okrsky_unknown"],
        "boundaries": places["boundaries"],
        "names": {prefix: len(rows) for prefix, rows in shards.items()},
        "parties": {
            name: [p.short, p.name] + ([p.logos[slug].file] if slug in p.logos else [])
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
    for change in table["change"]:
        codes = change["obce"]
        for code in codes:
            obce[code] = (
                [] if change.get("state_border") else [c for c in codes if c != code]
            )
    return {"day": str(table["compared"]), "obce": dict(sorted(obce.items()))}


def several_okrsky(live: Live | None) -> set[str]:
    """Return the obce that voted in several okrsky, by the final results.

    *live* is those results (:func:`final_okrsky`), None before them (then
    none is known).
    """
    numbers: dict[str, set[str]] = defaultdict(set)
    for contests in live.okrsky.values() if live else ():
        for contest, areas in contests.items():
            if contest.startswith("starosta:"):
                for key in areas:
                    obec, _, n = key.partition("/")
                    numbers[obec].add(n)
    return {obec for obec, ns in numbers.items() if len(ns) > 1}


def place_facts(
    cfg: Config,
    election: config.Election,
    several: Collection[str],
    drawn: Collection[str],
) -> dict[str, Any]:
    """Return what the ballots of an obec say of its data besides the rules.

    ``not_found``: the obce whose council obvod document was searched for
    and not found (:func:`election_map_slovakia.obvodrules.load_not_found`);
    ``okrsky_unknown``: of the obce that voted in *several* okrsky
    (:func:`several_okrsky`), those whose okrsky the map does not draw
    (*drawn*, ``geo`` index ``okrsky.drawn``); ``boundaries``
    (:func:`boundary_changes`) with ``on``, the slug of the election whose
    boundaries are drawn (:func:`drawn_on`).
    """
    from election_map_slovakia import obvodrules  # it imports what imports this

    changes = boundary_changes(cfg.election_dir(election))
    return {
        "not_found": sorted(obvodrules.load_not_found(cfg, election)),
        "okrsky_unknown": sorted(set(several) - set(drawn)),
        "boundaries": changes and {**changes, "on": drawn_on(cfg, election).slug},
    }


def election_inputs(election: config.Election) -> set[str]:
    """Return the names of the inputs (``inputs.toml``) *election* names."""
    return {
        *election.candidates.inputs.values(),
        *(election.incumbents.inputs if election.incumbents else ()),
        election.units.input,
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
) -> dict[str, Any]:
    """Return what an earlier *election* takes from the latest, and lacks.

    About's ``substitutes`` (module doc): *index* is its ``data/index.json``
    (:func:`site_index`), *several* the obce that voted in several okrsky
    (:func:`several_okrsky`), *persons* how many of its persons are linked
    to the latest's, and of how many; *records* the research reused for
    them (:func:`reused_research`).
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
            "adopted": names(obce[c][0] for c in index["adopted"]),
            "unknown": sum(c not in by_address for c in councils),
            "not_found": len(index["not_found"]),
            "approximate": len(index["date_approximate"]),
            "supplemented": len(index["supplemented"]),
        },
        "okrsky": {
            "several": len(several),
            "unknown": len(index["okrsky_unknown"]),
            "reused": len(index["okrsky_reused"]),
            "adopted": names(obce[c][0] for c in index["okrsky_adopted"]),
            "referendum": len(index["okrsky_referendum"]),
            "approximate": len(index["okrsky_date_approximate"]),
            "supplemented": len(index["okrsky_supplemented"]),
        },
        "persons": list(persons),
        "research": [
            len(records),
            sum(bool(r["findings"]) for r in records.values()),
            sum(len(r["findings"]) for r in records.values()),
            sum(r["undated"] for r in records.values()),
        ],
    }


def about(
    cfg: Config,
    election: config.Election,
    data: Mapping[str, Any],
    records: Mapping[str, Any],
    rule_sets: Mapping[str, obvody.RuleSet],
    replaced: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return ``data/about.json``: what the About dialog lists from the config.

    *election* is the page's: its inputs are listed, with the day their
    pinned file was retrieved and those no election names (the countries
    around), and its curated obvod files. *data* is ``candidates.json``,
    for the names of the areas of the curated obvod files. *records* is
    the curated research (:func:`research_records`), counted per research
    language: candidates researched and those with findings. *rule_sets*
    are the council rule sets (:func:`obvody.load_rule_sets`). *replaced*
    is what an earlier election takes from the latest (:func:`substitutes`),
    None for the latest.
    """
    election_dir = cfg.election_dir(election)
    named_parties = {p for c in data["candidacies"] for p in c["parties"]}
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
            if name in named_parties and (logo := p.logos.get(election.slug))
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
        # section says where they come from.
        "candidates": election.candidates.format,
        "substitutes": replaced,
    }


def _built(cfg: Config, election: config.Election) -> dict[str, Path]:
    """Return step → what it made of *election*, which the build reads."""
    directory = cfg.election_build_dir(election)
    paths = {
        "candidates": directory / candidates.OUTPUT_FILE,
        "geo": directory / geo.OUTPUT_DIR,
        "basemap": directory / basemap.OUTPUT_DIR,
        "addresses": directory / addresses.OUTPUT_DIR,
        "links": directory / LINKS_DIR,
    }
    for step, path in paths.items():
        if not path.exists():
            raise BuildError(f"{path} missing; run `ems {step}` first")
    return paths


@dataclass(frozen=True)
class _Context:
    """What every election's generated files are made with besides its own."""

    records: Mapping[str, Any]
    """The curated research (:func:`research_records`)."""
    persons: Mapping[str, Mapping[str, Mapping[str, str]]]
    """The persons linked across elections (:func:`linked_persons`)."""
    translations: Mapping[str, translate.Curated]
    """Language → its curated translations (:mod:`translate`)."""


def _election_files(
    cfg: Config,
    election: config.Election,
    data: Mapping[str, Any],
    geo_dir: Path,
    context: _Context,
    final: Mapping[str, Mapping[str, Any]] | None,
    other: Mapping[str, Mapping[str, list[list[Any]]]],
) -> dict[str, object]:
    """Return *election*'s generated JSON, path below its bundle → content.

    *data* is its ``candidates.json``, *geo_dir* its ``geo`` output, *final*
    its final results (:func:`final_contests`), *other* its persons'
    candidacies in other elections (:func:`elsewhere`).
    """
    curated = cfg.election_dir(election)
    rule_sets = obvody.load_rule_sets(curated)
    props = obec_props(geo_dir)
    # The curated research is keyed by the person ids of the latest
    # election, whose candidates it researched; another election's ids can
    # match one by chance (same obec, name and age), so its persons get the
    # research of those linked to them, as of their own election day.
    latest = cfg.latest
    records = (
        context.records
        if election == latest
        else reused_research(
            context.records,
            context.persons.get(latest.slug, {}).get(election.slug, {}),
            election.day.isoformat(),
        )
    )
    live = final_okrsky(cfg.results_dir(election))
    content: dict[str, object] = {}
    content |= area_files(
        data,
        _obvod_seats(geo_dir, rule_sets),
        obvod_sources(curated, rule_sets),
        research_summary(cfg, records),
        regional_past(data, props) | council_past(data, live),
        no_result(final, data),
        other,
    )
    content |= research_files(
        cfg,
        data,
        records,
        {code: t.research for code, t in context.translations.items()},
    )
    shards = name_shards(data)
    content |= {f"{DATA_DIR}/names/{p}.json": rows for p, rows in shards.items()}
    several = several_okrsky(live)
    drawn = json.loads((geo_dir / "index.json").read_bytes())["okrsky"]["drawn"]
    index = site_index(
        data,
        props,
        shards,
        cfg.parties,
        election.slug,
        rule_sets,
        obvody.okrsok_rule_sets(curated),
        place_facts(cfg, election, several, drawn),
    )
    content[f"{DATA_DIR}/index.json"] = index
    linked = context.persons.get(election.slug, {}).get(latest.slug, {})
    replaced = (
        None
        if election == latest
        else substitutes(
            cfg,
            election,
            index,
            several,
            (len(linked), len(data["persons"])),
            records,
        )
    )
    content[f"{DATA_DIR}/about.json"] = about(
        cfg, election, data, records, rule_sets, replaced
    )
    occupations = {c["occupation"] for c in data["candidacies"]} - {""}
    content |= occupation_files(context.translations, occupations)
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
        for contest, record in json.loads((results_dir / f"{path}.json").read_bytes())[
            "contests"
        ].items()
    }


def no_result(
    final: Mapping[str, Mapping[str, Any]] | None, data: Mapping[str, Any]
) -> set[str]:
    """Return the contests of *data* that the *final* results lack.

    Where a contest had candidates but the count could not be completed (in
    2022, Krušovce: its commission drew up no record and the election was
    held again), the final results (:func:`final_contests`) have no record
    of it. None before the results are final.
    """
    if final is None:
        return set()
    return {c["id"] for c in data["contests"]} - final.keys()


def bundles(
    cfg: Config,
    map_keys: Mapping[str, str | None],
    data_keys: Mapping[str, str | None],
) -> tuple[dict[str, Part], dict[str, Part]]:
    """Return the map and the data bundle of every election, by slug.

    See the module doc. *map_keys* and *data_keys* are the bundles' keys
    (:func:`election_map_slovakia.lock.keys`) by slug, which their
    manifests name; None where the repository does not determine them (an
    input not pinned yet).
    """
    built = {e.slug: _built(cfg, e) for e in cfg.elections}
    own: dict[str, dict[str, bytes]] = {}
    # Language → how many occupations are not translated into it.
    untranslated: dict[str, dict[str, int]] = {}
    with progress.stage("making the candidate, name search and occupation files"):
        datas = {
            e.slug: json.loads(built[e.slug]["candidates"].read_bytes())
            for e in cfg.elections
        }
        persons = linked_persons(
            {
                (e.slug, path.stem): json.loads(path.read_bytes())
                for e in cfg.elections
                for path in sorted(built[e.slug]["links"].glob("*.json"))
            }
        )
        finals = {e.slug: final_contests(cfg.results_dir(e)) for e in cfg.elections}
        others = elsewhere(
            datas,
            persons,
            {slug: candidacy_results(f or {}) for slug, f in finals.items()},
        )
        context = _Context(
            research_records(cfg),
            persons,
            {code: translate.load(cfg, code) for code in cfg.languages.codes},
        )
        for election in cfg.elections:
            slug = election.slug
            content = _election_files(
                cfg,
                election,
                datas[slug],
                built[slug]["geo"],
                context,
                finals[slug],
                others[slug],
            )
            own[slug] = {path: encode(value) for path, value in content.items()}
            untranslated[slug] = {
                path.split("/")[1].removesuffix(".json"): value["missing"]
                for path, value in content.items()
                if path.startswith(f"{I18N_DIR}/") and isinstance(value, dict)
            }
    web = cfg.root / WEB_DIR
    maps, data = {}, {}
    with progress.stage("hashing the bundles"):
        for election in cfg.elections:
            slug, paths = election.slug, built[election.slug]
            copies = {
                geo.OUTPUT_DIR: paths["geo"],
                basemap.OUTPUT_DIR: paths["basemap"],
                addresses.OUTPUT_DIR: paths["addresses"],
            }
            names = [
                f"{target}/{p.relative_to(source).as_posix()}"
                for target, source in copies.items()
                for p in sorted(source.rglob("*"))
                if p.is_file()
            ]
            version = content_version(
                itertools.chain(
                    *(tree(target, source) for target, source in copies.items())
                )
            )
            manifest: dict[str, Any] = {
                "key": map_keys.get(slug),
                "election": election.day.isoformat(),
                "version": version,
                "files": sorted(names),
            }
            # Served as the data are: web/_headers-data.
            maps[slug] = Part(
                _part_files(web, DATA_PART) | {MANIFEST: encode(manifest)}, copies
            )
            generated = sorted(own[slug].items())
            manifest = {
                "key": data_keys.get(slug),
                "election": election.day.isoformat(),
                "version": content_version(generated),
                "occupations": untranslated[slug],
                "files": [path for path, _ in generated],
            }
            data[slug] = Part(
                own[slug] | _part_files(web, "data") | {MANIFEST: encode(manifest)}, {}
            )
    return maps, data


def cited(cfg: Config) -> set[str]:
    """Return the names of the cached copies of the pages research cites."""
    root = cfg.curated_dir / research.CURATED_DIR
    return {
        finding["cache"]
        for path in sorted(root.glob("*/*.json"))
        for finding in json.loads(path.read_bytes())["findings"]
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


def _part_files(web: Path, part: str) -> dict[str, bytes]:
    """Return the response headers and 404 page of data part *part*."""
    return {
        HEADERS: (web / f"{HEADERS}-{part}").read_bytes(),
        NOT_FOUND: (web / "part-404.html").read_bytes(),
    }
