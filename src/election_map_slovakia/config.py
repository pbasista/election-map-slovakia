"""Load and validate the project configuration in ``config/``.

Every error names the file and the key, so a typo in a TOML file is reported
where it is, not as a failure somewhere downstream.
"""

from __future__ import annotations

import datetime as dt
import itertools
import os
import re
import tomllib
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from election_map_slovakia import contests

SITE_FILE = "site.toml"
LANGUAGES_FILE = "languages.toml"
SOURCES_FILE = "sources.toml"
INPUTS_FILE = "inputs.toml"
ELECTIONS_FILE = "elections.toml"
OVERRIDES_FILE = "overrides.toml"
PARTIES_FILE = "parties.toml"
RESULTS_ANYTIME_ENV = "EMS_RESULTS_ANYTIME"
"""Set to 1 at build time for testing with the output of ``ems results fake``
or ``poll`` before an election: the app then reads the live results of every
election every minute at any time, not only from the polls' closing
(elections.toml ``live``, ``live_days``)."""
# The elections' times (elections.toml polls_open, polls_close) are Slovak time.
_SLOVAK_TIME = ZoneInfo("Europe/Bratislava")
ELECTIONS_DIR = "elections"
"""Below ``data/curated/``: the data of each election (:meth:`Config.election_dir`)."""
RESULTS_DIR = "results"
"""Below each election's build directory and below ``dist/``: the final
results of that election (:meth:`Config.results_dir`)."""
LIVE_DIR = "live"
"""Below each election's build directory and below ``dist/``: the live
results of that election's night (:meth:`Config.live_dir`)."""
BASE_DIR = "base"
"""Below ``data/build/`` and below ``dist/``: the base map of each
OpenStreetMap extract (:attr:`Config.bases`, :meth:`Config.base_build_dir`)."""
ELECTION_KINDS = tuple(contests.ELECTION_KINDS)
"""The kinds of election (elections.toml ``kind``), each the app names
with its own heading in the list of elections (UI string
``elections.kind.<kind>``); :data:`election_map_slovakia.contests.ELECTION_KINDS`
says which contests each has. ``municipal-regional``: the regular
municipal and regional elections held together; ``by-election``: municipal
(or regional) by-elections and new elections held on one day in some
areas only; ``presidential``, ``referendum``, ``parliament`` (NR SR) and
``european`` (EP), country-wide."""
REGULAR = "municipal-regional"
"""The kind of the regular elections, whose obvody, okrsky and research
the jobs work on (:attr:`Config.latest`)."""
BY_ELECTION = "by-election"
_ROUNDS = tuple(
    e
    for e, ks in contests.ELECTION_KINDS.items()
    if contests.KINDS[ks[0]].sub == "round"
)
_QUESTIONS = tuple(
    e
    for e, ks in contests.ELECTION_KINDS.items()
    if contests.KINDS[ks[0]].sub == "question"
)
_PARTY_LISTS = tuple(
    e for e, ks in contests.ELECTION_KINDS.items() if contests.KINDS[ks[0]].party
)
_CURATED: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())
CANDIDATE_FORMATS: dict[str, dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {
    "municipal-regional": {
        "mvsr": (("starosta", "oz", "predseda", "zsk"), ("units",)),
        "susr": ((), ("oso", "okrsky", "osk")),
        "curated": _CURATED,
    },
    "by-election": {"susr-by": (("package",), ()), "curated": _CURATED},
    "presidential": {"volbysr": (("round1",), ("round2",)), "curated": _CURATED},
    "referendum": {},
    "parliament": {"volbysr": (("subjects", "candidates"), ()), "curated": _CURATED},
    "european": {"volbysr": (("subjects", "candidates"), ()), "curated": _CURATED},
}
"""Election kind → format of its candidate lists → the inputs ``candidates``
names, (required, optional) (src/election_map_slovakia/lists.py reads
them): ``mvsr``, the four lists MV SR publishes before the regular
elections (xlsx), one per contest kind, with ŠÚ SR's territorial division
(``units``, ``tab0dd``: the contests held nowhere for want of candidates,
lists.py); ``susr``, ŠÚ SR's definitive
packages of the municipal (``oso``) and regional (``osk``) elections, whose
tables list the candidates (statoffice.py): both of 2022, or one of the
elections held apart before, the regional of 2017 (``osk``) or the
municipal of 2018 (``oso``, with ``okrsky``, the zip of its tables per
okrsok); ``susr-by``, ŠÚ SR's package of
a municipal by-election (one of 2019–2022 supplemented by the election's
``candidates.toml``, where there is one); ``volbysr``, ŠÚ SR's candidate
tables of a country-wide election (a table file or a package holding it): of each
round of a presidential election, of the parties (``subjects``) and their
lists (``candidates``) of a parliamentary or European one; ``curated``,
nothing but ``candidates.toml`` in the election's curated data. A
referendum has no candidates (nor a ``candidates`` table)."""
UNIT_FORMATS = ("xlsx", "susr", "volbysr")
"""Format of an election's territorial division (ŠÚ SR ``tab0dd``): ``xlsx``,
the table alone; ``susr``, the table in ŠÚ SR's package of the municipal
elections of 2022 (statoffice.py); ``volbysr``, the table ``table`` of a
package of ŠÚ SR's XLSX or CSV tables (tables.py) with the okrsky per obec:
of a country-wide election (``tab0b`` in 2024, ``tab0c`` in 2019), of the
municipal elections of 2018 (``tab02bd``) or the regional of 2017
(``tab0dc``)."""
RESULT_FORMATS: dict[str, dict[str, tuple[tuple[str, ...], tuple[str, ...]] | None]] = {
    "municipal-regional": {"volbysr": None, "susr": ((), ("oso", "okrsky", "osk"))},
    "by-election": {"susr-by": (("package",), ())},
    "presidential": {"volbysr": (("round1",), ("round2",))},
    "referendum": {"volbysr": None},
    "parliament": {"volbysr": None},
    "european": {"volbysr": None},
}
"""Election kind → format of its definitive results → what its inputs are,
in order, (required, optional), or None: any number. None at all is
always allowed: the results are not published yet. ``volbysr``: the CSV
tables of ŠÚ SR's results site of the regular elections of 2026
(results.py ``read_final``), or ŠÚ SR's national tables of a country-wide
election (a package or table files; per round of a presidential one);
``susr``: ŠÚ SR's packages of the municipal and regional elections of
2022, 2018 or 2017 (statoffice.py), those its ``susr`` candidates name, in
their order; ``susr-by``: ŠÚ SR's package of a by-election. The
first format of a kind is that of an election without ``results``."""
HALVES = {"oso": "municipal", "osk": "regional"}
"""The halves of a regular election by the results source of their contests
(:attr:`contests.Kind.source`): until 2018 the municipal and the regional
elections were held on days of their own, so a regular election of then has
one (:attr:`Election.halves`)."""
ZBGIS_LEVELS = 3
"""ZBGIS levels of detail an election names, 0 (full detail) to 2."""
# An election's slug starts with a digit (it is the year), so that its
# pages and files (/<lang>/<slug>/, /<slug>/) never take the name of a
# language or of a directory the elections share; the projects of its
# bundles are told apart from others by it too (pages.py `unneeded`).
SLUG = re.compile(r"\d[0-9a-z]*(?:-[0-9a-z]+)*")
# Relative to the project root; the files are copied to dist/ with web/.
PARTY_LOGO_DIR = Path("web") / "img" / "parties"
_LOGO_SUFFIXES = (".svg", ".png", ".webp")
# Short forms go into compact candidate rows next to the name.
_MAX_SHORT = 20

INPUT_KINDS = ("xlsx", "zip", "rar", "csv", "pdf", "html", "geojson", "pbf")
_INPUT_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# A file name is also part of its asset's name in the input store, and
# GitHub replaces other characters in asset names.
_INPUT_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_AS_OF = re.compile(r"\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?")
# ZBGIS municipality code (ŠÚ SR, 6 digits) or one of the two synthetic city
# codes.
OBEC_CODE = re.compile(r"\d{6}|BA|KE")
OKRES_CODE = re.compile(r"\d{3}")
_KRAJ_CODE = re.compile(r"\d")
DISTRICT_CODE = re.compile(r"\d{6}")
_OBVOD_NUMBER = re.compile(r"[1-9]\d*")

_DIRECTIONS = ("ltr", "rtl")
_SCRIPT = re.compile(r"[A-Z][a-z]{3}")
_LANG_CODE = re.compile(r"[a-z]{2,3}")
_T = TypeVar("_T")
_MAX_LABEL = 63  # DNS limit
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")


class ConfigError(Exception):
    """A configuration file is missing, unparsable or invalid."""


@dataclass(frozen=True)
class Site:
    """``site.toml``: identity of the site, its Pages projects and budgets."""

    base_url: str | None
    repository: str
    """The source code repository, linked from the About dialog."""
    pages_project: str
    """Cloudflare Pages project of the app."""
    map_project: str
    """That of an election's map bundle, ``{slug}`` in it its slug
    (:meth:`map_project_of`)."""
    data_project: str
    """That of an election's data bundle, likewise (:meth:`data_project_of`)."""
    base_project: str
    """That of the base maps, one project for every extract: each is
    deployed once per key, and the app names the deployment."""
    sources_project: str
    results_project: str
    live_project: str
    sources_url: str
    """Where the sources project serves the cached copies the app links."""
    results_url: str
    """Where the results project serves the final results the app fetches."""
    live_url: str
    """Where the live project serves the live results of an election night,
    which the app fetches where the final results are not there yet."""
    file_budget: int
    max_file_bytes: int
    cache_image_max_bytes: int

    def map_project_of(self, slug: str) -> str:
        """Return the Pages project of the map bundle of the election *slug*."""
        return self.map_project.replace("{slug}", slug)

    def data_project_of(self, slug: str) -> str:
        """Return the Pages project of the data bundle of the election *slug*."""
        return self.data_project.replace("{slug}", slug)


@dataclass(frozen=True)
class CandidateLists:
    """Where an election's candidate lists come from (``elections.toml``)."""

    format: str
    """One of :data:`CANDIDATE_FORMATS` of its kind: how the lists are read."""
    inputs: dict[str, str]
    """What the format reads (for ``mvsr`` a contest kind) → input name."""


@dataclass(frozen=True)
class Units:
    """Where an election's territorial division comes from (``elections.toml``)."""

    format: str
    """One of :data:`UNIT_FORMATS`: how the table is read."""
    input: str
    table: str | None = None
    """The table's id in the input, of the ``volbysr`` format only."""


@dataclass(frozen=True)
class Results:
    """Where an election's definitive results come from (``elections.toml``)."""

    format: str
    """One of :data:`RESULT_FORMATS` of its kind: how the packages are read."""
    inputs: tuple[str, ...]
    """The packages, in the order :data:`RESULT_FORMATS` names them; none
    until they are published."""


@dataclass(frozen=True)
class ByElection:
    """A municipal by-election ("nové voľby") between two regular ones."""

    input: str
    day: dt.date


@dataclass(frozen=True)
class Incumbents:
    """The results an election's office holders are rebuilt from.

    Those of the regular elections before it and of every municipal
    by-election since (:mod:`election_map_slovakia.incumbents`).
    """

    day: dt.date
    """Election day of the regular elections before."""
    municipal: str
    """Their municipal results (ŠÚ SR CSV tables)."""
    regional: str
    """Their regional results."""
    by_elections: tuple[ByElection, ...]
    """In date order."""

    @property
    def inputs(self) -> tuple[str, ...]:
        """Return the names of all of these inputs."""
        return (
            self.municipal,
            self.regional,
            *(b.input for b in self.by_elections),
        )


@dataclass(frozen=True)
class Election:
    """One election the site shows (``elections.toml``).

    Its own pages (``/<lang>/<slug>/``) and data bundle
    (``dist/data/<slug>/``), curated data (:meth:`Config.election_dir`) and
    build output (:meth:`Config.election_build_dir`); the inputs
    (``inputs.toml``) its steps read.
    """

    day: dt.date
    slug: str
    """Its name in URLs (``/<lang>/<slug>/``) and of its bundle's project."""
    kind: str
    """One of :data:`ELECTION_KINDS`."""
    polls_open: dt.datetime
    polls_close: dt.datetime
    """When the polls open and close on election day (elections.toml gives
    the times of day in Slovak time; these carry its offset)."""
    live: bool
    """Whether the app reads the live results, every minute within
    ``live_window``, where the final results are not there yet (``live``, or
    ``EMS_RESULTS_ANYTIME=1``); without, it reads the final results alone,
    once per page load."""
    live_window: tuple[dt.datetime, dt.datetime] | None
    """When the app, with ``live``, reads the results every minute: from the
    polls' closing for ``live_days``; before, it reads nothing, after, the
    final results once per page load. None with ``EMS_RESULTS_ANYTIME=1``,
    for testing: any time."""
    candidates: CandidateLists | None
    """None for a referendum, which has none."""
    incumbents: Incumbents | None
    """None where the office holders before it are not known (only regular
    elections have them)."""
    units: Units | None
    """The territorial division (ŠÚ SR tab0dd): okrsky per obec. None (not
    for a regular election) where none is counted or drawn: the map stops
    at the municipalities."""
    results: Results
    """The definitive results, once published."""
    addresses: str
    """The address register."""
    zbgis: tuple[str, ...]
    """The administrative boundaries, by level of detail (0 to 2)."""
    osm: str
    """The OpenStreetMap extract of the base map."""
    records: tuple[str, ...]
    """Records of sources no step reads (optional inputs): the documents
    the curated obvody come from, the originals of data that stand in."""
    second_round: dt.date | None = None
    """A presidential election's second round, two weeks after the first,
    with the same polling hours; None where none is held (yet)."""
    questions: tuple[str, ...] = ()
    """A referendum's questions, worded as the President's decision has
    them, in order; empty for any other election."""
    seats: int | None = None
    """The seats a parliamentary or European election fills; None for the
    others (as for those below)."""
    threshold: float | None = None
    """The share of the valid votes, in %, a party needs to win seats."""
    coalition_thresholds: tuple[tuple[int, float], ...] = ()
    """(parties, %), ascending: a coalition of at least that many parties
    needs that share instead (``config/parties.toml`` ``members``); empty
    where coalitions need what a party does."""
    preferences: int | None = None
    """How many candidates of the chosen list a voter may circle."""
    preference_quota: float | None = None
    """The share of its party's valid votes, in %, a candidate's preference
    votes must reach to move ahead of the list order."""

    @property
    def last_day(self) -> dt.date:
        """Return the day of its last round: what its voters could know by then.

        A presidential election's second round where it has one, else its day.
        """
        return self.second_round or self.day

    @property
    def rounds(self) -> tuple[tuple[dt.datetime, dt.datetime], ...]:
        """Return when the polls open and close in each round.

        One round, but in a presidential election with its second round
        configured.
        """
        first = (self.polls_open, self.polls_close)
        if self.second_round is None:
            return (first,)
        return (
            first,
            (
                dt.datetime.combine(self.second_round, self.polls_open.timetz()),
                dt.datetime.combine(self.second_round, self.polls_close.timetz()),
            ),
        )

    @property
    def halves(self) -> tuple[str, ...]:
        """Return the halves a regular election holds, keys of :data:`HALVES`.

        Both, but of a regular election read from ŠÚ SR's package of one
        (``susr`` candidates without ``oso`` or ``osk``); none of the other
        kinds.
        """
        if self.kind != REGULAR:
            return ()
        if self.candidates is not None and self.candidates.format == "susr":
            return tuple(h for h in HALVES if h in self.candidates.inputs)
        return tuple(HALVES)

    @property
    def label(self) -> str:
        """Return what its kind's UI strings are keyed by (``app.title.<label>``).

        Its kind, but ``municipal`` or ``regional`` of a regular election of
        one half.
        """
        if len(self.halves) == 1:
            return HALVES[self.halves[0]]
        return self.kind


@dataclass(frozen=True)
class Language:
    """One enabled UI language."""

    code: str
    name: str
    site_name: str
    """The site's name in this language, shown in its header and titles."""
    script: str
    direction: str


@dataclass(frozen=True)
class Languages:
    """``languages.toml``: enabled languages, fallbacks and browser aliases."""

    languages: tuple[Language, ...]
    fallback: tuple[str, ...]
    aliases: dict[str, str]

    @property
    def codes(self) -> tuple[str, ...]:
        """Return the enabled language codes in switcher order."""
        return tuple(lang.code for lang in self.languages)


@dataclass(frozen=True)
class Sources:
    """``sources.toml`` plus the blocklist and official-sites files it names."""

    categories: dict[str, tuple[str, ...]]
    exclude_host_labels: tuple[str, ...]
    exclude_path_segments: tuple[str, ...]
    blocklist_file: str
    blocklist: frozenset[str]
    references: tuple[str, ...]
    """URLs of the reports the media categories were selected from."""
    research: dict[str, tuple[str, ...]]
    """Research language → the categories its agents search, in order."""
    municipal_sites: dict[str, str]
    """Obec code (BA, KE: the city) → host of its official website (``official``)."""
    regional_sites: dict[str, str]
    """Kraj code → host of the region's official website (``official``)."""


@dataclass(frozen=True)
class Input:
    """One file that ``fetch`` downloads; see ``inputs.toml``."""

    name: str
    url: str
    file: str
    kind: str
    members: tuple[str, ...]
    expect: str
    volatile: re.Pattern[bytes] | None
    sha256: str
    """The digest the file must have (a pinned input), or empty."""
    optional: bool
    """No step reads it (a record of a source): a failed download only warns."""
    as_of: str = ""
    """The day (``YYYY-MM-DD``) or month (``YYYY-MM``) the data are of, where
    it is not that of the election (the site names it in its credits), or
    empty."""
    retrieved: dt.date | None = None
    """The day the pinned file was downloaded from its source (About names
    it); None where the input is not pinned."""


@dataclass(frozen=True)
class Store:
    """``inputs.toml`` ``store``: the GitHub release holding the pinned files.

    Each pinned file is an asset named ``<sha256>-<file>``, never replaced:
    a new version of an input is a new asset.
    """

    repository: str
    """``owner/name`` of the public repository: the project's own."""
    release: str
    """The tag of its release that holds the files."""

    @staticmethod
    def asset(inp: Input) -> str:
        """Return the name of the asset of pinned input *inp*."""
        return Store.asset_name(inp.sha256, inp.file)

    @staticmethod
    def asset_name(sha256: str, file: str) -> str:
        """Return the name of the asset of the pinned file *file*, of *sha256*."""
        return f"{sha256}-{file}"

    def url(self, inp: Input) -> str:
        """Return where anyone can download the asset of pinned input *inp*."""
        return (
            f"https://github.com/{self.repository}/releases/download/"
            f"{self.release}/{self.asset(inp)}"
        )


@dataclass(frozen=True)
class Inputs:
    """``inputs.toml``: what ``fetch`` downloads and how it checks it."""

    contact: str
    ca_certificates: tuple[Path, ...]
    inputs: tuple[Input, ...]
    store: Store | None = None
    """Where the pinned files are kept; None: nowhere, only at their sources."""


@dataclass(frozen=True)
class Overrides:
    """One election's table of ``overrides.toml``: name-matching fixes."""

    obec: dict[str, str]
    """``"<okres>/<obec>"`` as written in a candidate list → obec code."""
    residence: dict[str, str]
    """Candidacy id → obec code of the candidate's residence."""
    person_merge: tuple[tuple[str, ...], ...]
    """Groups of candidacy ids that belong to one person."""
    person_split: tuple[tuple[str, ...], ...]
    """Groups of candidacy ids taken out of their person to form a new one."""
    address: dict[str, str]
    """``"<okres>/<obec>"`` as written in the address register → obec code."""
    address_skip: frozenset[str] = frozenset()
    """``"<okres>/<obec>"`` of the address register's places that are no
    obec of ZBGIS: their rows are left out."""


@dataclass(frozen=True)
class Obvod:
    """One constituency of a curated membership file."""

    number: int
    seats: int
    """Councillors elected in the obvod."""
    okresy: tuple[str, ...]
    """Whole okresy, as the source document names them."""
    obce: tuple[str, ...]
    """Single obce or Bratislava/Košice districts (6-digit codes)."""


@dataclass(frozen=True)
class ObvodList:
    """``obvody/<area>.toml`` of an election: which units form each obvod.

    See :meth:`Config.election_dir`.
    """

    path: Path
    source: str
    """URL of the official document the membership was transcribed from."""
    title: str
    """That document's title, as the ballots name it."""
    date: dt.date
    """Date of the decision that set the obvody."""
    obvody: tuple[Obvod, ...]
    """Sorted by number, numbered 1..N without gaps."""


@dataclass(frozen=True)
class CuratedCandidate:
    """One candidate of a contest of ``candidates.toml``."""

    number: int
    """Ballot number; a list contest's position on the list."""
    title_before: str
    first_name: str
    surname: str
    title_after: str
    age: int
    occupation: str
    parties: tuple[str, ...]
    """The nominating parties, empty for an independent; empty for a
    presidential candidate and a list contest's (the list's party is theirs)."""
    residence: str
    """The obec of residence as written, empty where not given."""
    withdrawn: bool


@dataclass(frozen=True)
class CuratedContest:
    """One contest of ``candidates.toml``."""

    id: str
    """A contest id (:mod:`election_map_slovakia.contests`)."""
    seats: int | None
    """A council contest's seats, where given."""
    party: str | None
    """A list contest's party (a ``[[subject]]``'s); None for the others."""
    source: str | None
    """The URL of the document its list is transcribed from, where given;
    always in a supplement to a by-election's package."""
    date: dt.date | None
    """The date that document bears, given with *source*."""
    candidates: tuple[CuratedCandidate, ...]


@dataclass(frozen=True)
class CuratedUncontested:
    """One contest of ``uncontested.toml``: called, but no candidate registered."""

    id: str
    """A contest id (:mod:`election_map_slovakia.contests`)."""
    seats: int | None
    """A council contest's seats, where given."""
    source: str
    """The URL of the document saying it was called: the Speaker's decision
    calling a by-election, the municipality's decision on its council
    obvody."""
    title: str
    """What in it says so."""


@dataclass(frozen=True)
class CuratedLists:
    """``candidates.toml`` of an election: its candidate lists curated by hand.

    The ``curated`` format of ``elections.toml`` ``candidates``, or a
    supplement to a by-election's package (``susr-by``) whose contests it
    replaces (:mod:`election_map_slovakia.lists`); see
    :meth:`Config.election_dir`.
    """

    path: Path
    contests: tuple[CuratedContest, ...]
    subjects: tuple[tuple[int, str], ...]
    """The ballot subjects of a parliamentary or European election: ballot
    number and party, by number."""


@dataclass(frozen=True)
class Logo:
    """A party's logo at one election (``parties.toml`` ``logo.<slug>``)."""

    file: str
    """File name in ``web/img/parties/``."""
    source: str
    """Page the file was taken from."""
    license: str


@dataclass(frozen=True)
class Party:
    """One entry of ``parties.toml``."""

    short: str
    """The form Slovak media use, for compact candidate rows."""
    name: str
    """Official name as in the Ministry of Interior's party register."""
    logos: dict[str, Logo]
    """Election slug → the party's logo as it was at that election, where
    there is one that may be redistributed."""
    members: tuple[str, ...] = ()
    """A coalition's member parties (their names, entries of the file);
    empty for a party. A coalition standing as one ballot subject needs the
    election's coalition threshold for as many parties
    (:attr:`Election.coalition_thresholds`)."""


@dataclass(frozen=True)
class Base:
    """The base map of an OpenStreetMap extract: every election on it shows it."""

    osm: str
    """The extract, which names the base map (:meth:`Config.base_build_dir`)."""
    okresy: str
    """The ZBGIS input whose okresy (level 1) cut it into shards."""
    obce: str
    """The ZBGIS input whose obce (level 0) its buildings are filed by."""


@dataclass(frozen=True)
class Config:
    """The whole configuration, loaded from one directory."""

    root: Path
    site: Site
    elections: tuple[Election, ...]
    """Newest first."""
    languages: Languages
    sources: Sources
    inputs: Inputs
    overrides: dict[str, Overrides]
    """Election slug → its overrides (empty where it has none)."""
    parties: dict[str, Party]
    """Party name as written in the candidate lists → its entry."""

    @property
    def latest(self) -> Election:
        """Return the newest regular election (``municipal-regional``).

        Everything about the obvody, okrsky, research, reuse and fakes of
        the regular elections is about it; the site's home is
        :attr:`home`.
        """
        return next(e for e in self.elections if e.kind == REGULAR)

    @property
    def home(self) -> Election:
        """Return the newest election that is not a by-election.

        The one ``/<lang>/`` shows, which the canonical pages, the sitemap
        and the language picker are of. Newest by day, whether held or
        upcoming: an election configured ahead of its day becomes the home
        at once, so the site opens on the most recent or upcoming election.
        A by-election is passed over even then: held in a few places only,
        it concerns few of the visitors.
        """
        return next(e for e in self.elections if e.kind != BY_ELECTION)

    def term(self, election: Election) -> Election | None:
        """Return the regular election whose council by-election *election* fills seats of.

        The newest before it; None where *election* is no by-election or
        none is configured before it.
        """
        if election.kind != BY_ELECTION:
            return None
        before = [
            e for e in self.elections if e.kind == REGULAR and e.day < election.day
        ]
        return max(before, key=lambda e: e.day) if before else None

    def election(self, key: str | None) -> Election:
        """Return the election of day or slug *key*; None: the latest."""
        if key is None:
            return self.latest
        for election in self.elections:
            if key in (election.day.isoformat(), election.slug):
                return election
        known = ", ".join(e.day.isoformat() for e in self.elections)
        raise ConfigError(f"no election {key!r} in config/{ELECTIONS_FILE}: {known}")

    @property
    def raw_dir(self) -> Path:
        """Return ``data/raw``, where downloads and their manifest live."""
        return self.root / "data" / "raw"

    @property
    def build_dir(self) -> Path:
        """Return ``data/build``, for intermediate pipeline output.

        What a step makes of an election goes below
        :meth:`election_build_dir`; directly in it, what serves them all:
        the GeoPackages unpacked from the inputs and the site's own memo.
        """
        return build_dir_of(self.root)

    @property
    def curated_dir(self) -> Path:
        """Return ``data/curated``, for hand-curated, committed inputs."""
        return self.root / "data" / "curated"

    def election_dir(self, election: Election) -> Path:
        """Return ``data/curated/elections/<day>``: *election*'s curated data.

        What the state sets anew for each election (constituencies, okrsky)
        is curated by hand or by jobs per election, so that a later one adds
        a directory of its own instead of changing this one's.
        """
        return self.curated_dir / ELECTIONS_DIR / election.day.isoformat()

    def election_build_dir(self, election: Election) -> Path:
        """Return ``data/build/<day>``: what the steps made of *election*.

        ``candidates.json``, ``addr/``, ``obvod-addresses/``, ``geo/``, its
        final results (:meth:`results_dir`), its live results
        (:meth:`live_dir`), which no step writes, and the stamps and gzip
        memos of its steps. Its base map is its extract's
        (:meth:`base_build_dir`).
        """
        return self.build_dir / election.day.isoformat()

    @property
    def bases(self) -> dict[str, Base]:
        """Return extract → the base map of every election on it, newest first.

        Its elections name the same ZBGIS levels 0 and 1
        (:func:`load_elections`).
        """
        out: dict[str, Base] = {}
        for e in self.elections:
            out.setdefault(e.osm, Base(e.osm, e.zbgis[1], e.zbgis[0]))
        return out

    def base_build_dir(self, osm: str) -> Path:
        """Return ``data/build/base/<osm>``: the base map of extract *osm*.

        Its ``base/`` (``ems basemap``), and the stamp and gzip memo of
        the step.
        """
        return self.build_dir / BASE_DIR / osm

    def results_dir(self, election: Election) -> Path:
        """Return ``data/build/<day>/results``: *election*'s final results.

        Only the ``results`` step of ``ems make`` writes them, from the final
        results inputs (absent without); ``build`` copies them to
        ``dist/results/<day>/``, which a release deploys.
        """
        return self.election_build_dir(election) / RESULTS_DIR

    def live_dir(self, election: Election) -> Path:
        """Return ``data/build/<day>/live``: *election*'s live results.

        ``ems results poll`` and ``fake`` write them on (or for a test of) an
        election night; ``build`` and ``ems results deploy`` copy them to
        ``dist/live/<day>/``, which only the latter deploys.
        """
        return self.election_build_dir(election) / LIVE_DIR


def find_config_dir(start: Path | None = None) -> Path:
    """Return the ``config`` directory of the project containing *start*.

    Walks up from *start* (default: the current directory), so the CLI works
    from any subdirectory of a checkout.
    """
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / "config"
        if (candidate / SITE_FILE).is_file():
            return candidate
    raise ConfigError(f"no config/{SITE_FILE} found in {here} or any parent")


def build_dir_of(root: Path) -> Path:
    """Return ``data/build`` of the project at *root* (:attr:`Config.build_dir`)."""
    return root / "data" / "build"


def load(config_dir: Path | None = None) -> Config:
    """Load and validate all configuration from *config_dir*."""
    directory = config_dir if config_dir is not None else find_config_dir()
    root = directory.resolve().parent
    inputs = load_inputs(directory / INPUTS_FILE)
    elections = load_elections(directory / ELECTIONS_FILE, inputs)
    return Config(
        root=root,
        site=load_site(directory / SITE_FILE),
        elections=elections,
        languages=load_languages(directory / LANGUAGES_FILE),
        sources=load_sources(directory / SOURCES_FILE),
        inputs=inputs,
        overrides=load_overrides(
            directory / OVERRIDES_FILE, [e.slug for e in elections]
        ),
        parties=load_parties(
            directory / PARTIES_FILE,
            root / PARTY_LOGO_DIR,
            [e.slug for e in elections],
        ),
    )


def load_site(path: Path) -> Site:
    """Load ``site.toml``."""
    t = _Table(path, _read_toml(path))
    base_url = t.string("base_url")
    if base_url and not _is_http_url(base_url):
        raise t.error("base_url", "must be empty or an absolute http(s) URL")
    repository = t.string("repository").rstrip("/")
    if not repository.startswith("https://"):
        raise t.error("repository", "must be an absolute https URL")
    projects = {
        key: t.string(key)
        for key in (
            "pages_project",
            "map_project",
            "data_project",
            "base_project",
            "sources_project",
            "results_project",
            "live_project",
        )
    }
    for key, project in projects.items():
        # It becomes the host name <project>.pages.dev; an election's slug
        # (a year) takes the place of {slug}.
        name = project.replace("{slug}", "2026")
        if len(name) > _MAX_LABEL or not _LABEL.fullmatch(name):
            raise t.error(key, "must be lowercase letters, digits and dashes")
    for key in ("map_project", "data_project"):
        if "{slug}" not in projects[key]:
            raise t.error(key, "must contain {slug}: one project per election")
    urls = {
        key: t.string(key).rstrip("/")
        for key in ("sources_url", "results_url", "live_url")
    }
    for key, url in urls.items():
        if not url.startswith("https://"):
            raise t.error(key, "must be an absolute https URL")
    site = Site(
        base_url=base_url.rstrip("/") or None,
        repository=repository,
        **projects,
        **urls,
        file_budget=t.positive_int("file_budget"),
        max_file_bytes=t.positive_int("max_file_bytes"),
        cache_image_max_bytes=t.positive_int("cache_image_max_bytes"),
    )
    t.reject_unknown()
    return site


def load_elections(path: Path, inputs: Inputs) -> tuple[Election, ...]:
    """Load ``elections.toml``, checking the inputs it names against *inputs*."""
    t = _Table(path, _read_toml(path))
    anytime = os.environ.get(RESULTS_ANYTIME_ENV, "")
    if anytime not in ("", "0", "1"):
        raise ConfigError(f"{RESULTS_ANYTIME_ENV}: must be 1, 0 or empty")
    known = {i.name: i for i in inputs.inputs}
    elections = [
        _load_election(t.entry(f"election.{slug}", entry), slug, known, anytime == "1")
        for slug, entry in t.get("election", dict).items()
    ]
    if not elections:
        raise t.error("election", "must define at least one election")
    t.reject_unknown()
    # The jobs and research work on the newest regular election (Config.latest).
    if not any(e.kind == REGULAR for e in elections):
        raise t.error("election", f"must define at least one {REGULAR} election")
    elections.sort(key=lambda e: e.day, reverse=True)
    for newer, older in itertools.pairwise(elections):
        if newer.day == older.day:
            raise t.error(f"election.{older.slug}.day", f"{older.day} is taken")
    # The elections on one extract share its base map (Config.bases), which
    # is cut by the okresy and holds the buildings of the obce they name.
    first: dict[str, Election] = {}
    for e in elections:
        other = first.setdefault(e.osm, e)
        if other.zbgis[:2] != e.zbgis[:2]:
            raise t.error(
                f"election.{e.slug}.zbgis",
                f"levels 0 and 1 must be those of election {other.slug}, which"
                f" shares the base map of {e.osm}",
            )
    return tuple(elections)


def _input_name(
    t: _Table, key: str, value: str, known: dict[str, Input], optional: bool
) -> str:
    """Return *value*, found under *key*, if it names an input of inputs.toml.

    An optional input is allowed only where *optional*: fetch lets one
    fail, so no step may read it.
    """
    if value not in known:
        raise t.error(key, f"no input {value!r} in {INPUTS_FILE}")
    if known[value].optional and not optional:
        raise t.error(key, f"input {value!r} is optional, so no step may read it")
    return value


def _one_of(t: _Table, key: str, allowed: Iterable[str]) -> str:
    """Return string *key* of *t*, which must be one of *allowed*."""
    value = t.string(key)
    if value not in allowed:
        raise t.error(key, f"must be one of {', '.join(allowed)}")
    return value


def _load_election(
    et: _Table, slug: str, known: dict[str, Input], anytime: bool
) -> Election:
    if not SLUG.fullmatch(slug):
        raise ConfigError(
            f"{et.path}: {et.prefix}: the slug must be a digit, then lowercase"
            " letters, digits and dashes"
        )

    def name(t: _Table, key: str) -> str:
        return _input_name(t, key, t.nonempty(key), known, False)

    def names(key: str, optional: bool = False) -> tuple[str, ...]:
        return tuple(_input_name(et, key, v, known, optional) for v in et.str_list(key))

    day = et.date("day")
    kind = _one_of(et, "kind", ELECTION_KINDS)
    open_time = et.get("polls_open", dt.time)
    close_time = et.get("polls_close", dt.time)
    if not open_time < close_time:
        raise et.error("polls_close", "must be later than polls_open")
    polls_open = dt.datetime.combine(day, open_time, _SLOVAK_TIME)
    polls_close = dt.datetime.combine(day, close_time, _SLOVAK_TIME)
    live_days = dt.timedelta(days=et.positive_int("live_days"))
    fields = _kind_fields(et, kind, day)
    zbgis = names("zbgis")
    if len(zbgis) != ZBGIS_LEVELS:
        raise et.error("zbgis", f"must name {ZBGIS_LEVELS} levels, 0 to 2")
    incumbents = None
    if "incumbents" in et.data:
        if kind != REGULAR:
            raise et.error("incumbents", f"only a {REGULAR} election has them")
        incumbents = _load_incumbents(et, day, name)
    if "units" in et.data or kind == REGULAR:
        ut = et.table("units")
        unit_format = _one_of(ut, "format", UNIT_FORMATS)
        table = ut.nonempty("table") if unit_format == "volbysr" else None
        units = Units(unit_format, name(ut, "input"), table)
        ut.reject_unknown()
    else:
        units = None
    election = Election(
        day=day,
        slug=slug,
        kind=kind,
        polls_open=polls_open,
        polls_close=polls_close,
        live=et.get("live", bool) or anytime,
        live_window=None if anytime else (polls_close, polls_close + live_days),
        candidates=_load_candidates(et, kind, fields, name),
        incumbents=incumbents,
        units=units,
        results=_load_results(et, kind, fields, known),
        addresses=name(et, "addresses"),
        zbgis=zbgis,
        osm=name(et, "osm"),
        records=names("records", optional=True),
        **fields,
    )
    et.reject_unknown()
    lists = election.candidates
    named = tuple(lists.inputs.values()) if lists and lists.format == "susr" else ()
    if election.results.format == "susr" and election.results.inputs not in ((), named):
        raise et.error(
            "results",
            "susr reads the packages the susr candidates name, in their order",
        )
    return election


def _kind_fields(et: _Table, kind: str, day: dt.date) -> dict[str, Any]:
    """Return the fields of an election of *kind* that only some kinds have."""
    fields: dict[str, Any] = {}
    if kind in _ROUNDS and "second_round" in et.data:
        fields["second_round"] = et.date("second_round")
        if fields["second_round"] <= day:
            raise et.error("second_round", "must be after the first round's day")
    if kind in _QUESTIONS:
        fields["questions"] = tuple(et.str_list("questions"))
        if not fields["questions"]:
            raise et.error("questions", "must list the referendum's questions")
    if kind in _PARTY_LISTS:
        fields["seats"] = et.positive_int("seats")
        fields["threshold"] = _percent(et, "threshold")
        fields["preferences"] = et.positive_int("preferences")
        fields["preference_quota"] = _percent(et, "preference_quota")
        fields["coalition_thresholds"] = _coalition_thresholds(et)
    return fields


def _percent(t: _Table, key: str) -> float:
    """Return number *key* of *t*, a share in % above 0 and below 100."""
    value = t.data.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        t.used.add(key)
        value = float(value)
    else:
        value = t.get(key, float)
    if not 0 < value < 100:  # noqa: PLR2004 - per cent
        raise t.error(key, "must be a share in %, above 0 and below 100")
    return value


def _coalition_thresholds(et: _Table) -> tuple[tuple[int, float], ...]:
    """Return ``coalition_thresholds``: [[parties, %], …] by ascending parties."""
    out: list[tuple[int, float]] = []
    for i, pair in enumerate(et.optional("coalition_thresholds", list, [])):
        where = f"coalition_thresholds[{i}]"
        # A pair is read as a table of its two items to reuse the checks.
        if not isinstance(pair, list) or len(pair) != 2:  # noqa: PLR2004 - a pair
            raise et.error(where, "must be [parties, threshold in %]")
        pt = et.entry(where, {"parties": pair[0], "threshold": pair[1]})
        parties, threshold = pt.positive_int("parties"), _percent(pt, "threshold")
        if parties < 2 or (out and parties <= out[-1][0]):  # noqa: PLR2004
            raise et.error(where, "parties must be 2 or more, ascending")
        out.append((parties, threshold))
    return tuple(out)


def _load_candidates(
    et: _Table,
    kind: str,
    fields: Mapping[str, Any],
    name: Callable[[_Table, str], str],
) -> CandidateLists | None:
    """Return the ``candidates`` table of an election of *kind*, None if it has none."""
    formats = CANDIDATE_FORMATS[kind]
    if not formats:
        if "candidates" in et.data:
            raise et.error("candidates", f"a {kind} election has no candidates")
        return None
    ct = et.table("candidates")
    format_ = _one_of(ct, "format", formats)
    required, optional = formats[format_]
    inputs = {part: name(ct, part) for part in required}
    inputs |= {part: name(ct, part) for part in optional if part in ct.data}
    ct.reject_unknown()
    # Round 2's list exists only once its day is set.
    if "round2" in inputs and "second_round" not in fields:
        raise ct.error("round2", "needs the election's second_round")
    # ŠÚ SR's packages of the municipal and regional elections, of one where
    # they were held apart (statoffice.py).
    if format_ == "susr" and not inputs.keys() & HALVES.keys():
        raise ct.error("format", "susr needs the package oso, osk or both")
    if "okrsky" in inputs and "oso" not in inputs:
        raise ct.error("okrsky", "needs oso, the package they are of")
    return CandidateLists(format_, inputs)


def _load_results(
    et: _Table, kind: str, fields: Mapping[str, Any], known: dict[str, Input]
) -> Results:
    """Return the ``results`` table of an election of *kind*.

    Without one, the kind's first format and no inputs: none published yet.
    """
    formats = RESULT_FORMATS[kind]
    if "results" not in et.data:
        return Results(next(iter(formats)), ())
    rt = et.table("results")
    results_format = _one_of(rt, "format", formats)
    packages = tuple(
        _input_name(rt, "inputs", v, known, False) for v in rt.str_list("inputs")
    )
    parts = formats[results_format]
    if parts is not None and packages:
        required, optional = parts
        if not len(required) <= len(packages) <= len(required) + len(optional):
            names = ", ".join([*required, *(f"({o})" for o in optional)])
            raise rt.error("inputs", f"must name the packages {names}")
        if len(packages) > 1 and kind in _ROUNDS and "second_round" not in fields:
            raise rt.error("inputs", "round 2's needs the election's second_round")
    rt.reject_unknown()
    return Results(results_format, packages)


def _load_incumbents(
    et: _Table, day: dt.date, name: Callable[[_Table, str], str]
) -> Incumbents:
    """Load the ``incumbents`` table of an election of *day*."""
    it = et.table("incumbents")
    before = it.date("day")
    if before >= day:
        raise it.error("day", "must be before the election's day")
    incumbents = Incumbents(
        before,
        name(it, "municipal"),
        name(it, "regional"),
        tuple(_by_elections(it, before, name)),
    )
    it.reject_unknown()
    return incumbents


def _by_elections(
    it: _Table, last: dt.date, name: Callable[[_Table, str], str]
) -> Iterator[ByElection]:
    """Yield the ``by_elections`` of an ``incumbents`` table, in date order."""
    for i, entry in enumerate(it.get("by_elections", list)):
        bt = it.entry(f"by_elections[{i}]", entry)
        by = ByElection(name(bt, "input"), bt.date("day"))
        bt.reject_unknown()
        if by.day <= last:
            raise bt.error("day", "must be later than the one before")
        last = by.day
        yield by


def _load_language(t: _Table, code: str, entry: object) -> Language:
    key = f"language.{code}"
    if not _LANG_CODE.fullmatch(code):
        raise t.error(key, "language code must be 2-3 lowercase letters")
    lt = t.entry(key, entry)
    lang = Language(
        code=code,
        name=lt.nonempty("name"),
        site_name=lt.nonempty("site_name"),
        script=lt.string("script"),
        direction=lt.string("direction"),
    )
    if not _SCRIPT.fullmatch(lang.script):
        raise lt.error("script", "must be an ISO 15924 code such as 'Latn'")
    if lang.direction not in _DIRECTIONS:
        raise lt.error("direction", f"must be one of {', '.join(_DIRECTIONS)}")
    lt.reject_unknown()
    return lang


def load_languages(path: Path) -> Languages:
    """Load ``languages.toml``."""
    t = _Table(path, _read_toml(path))
    languages = [
        _load_language(t, code, entry)
        for code, entry in t.get("language", dict).items()
    ]
    if not languages:
        raise t.error("language", "at least one language must be enabled")
    codes = {lang.code for lang in languages}

    fallback = tuple(t.str_list("fallback"))
    for code in fallback:
        if code not in codes:
            raise t.error("fallback", f"{code!r} is not an enabled language")
    if len(set(fallback)) != len(fallback):
        raise t.error("fallback", "lists a language twice")

    aliases = {}
    for alias, target in t.get("aliases", dict).items():
        key = f"aliases.{alias}"
        if not isinstance(target, str) or target not in codes:
            raise t.error(key, f"target {target!r} is not an enabled language")
        if alias in codes:
            raise t.error(key, "an enabled language cannot also be an alias")
        aliases[alias] = target
    t.reject_unknown()
    return Languages(tuple(languages), fallback, aliases)


def load_sources(path: Path) -> Sources:
    """Load ``sources.toml`` and the blocklist and official-sites files it names."""
    t = _Table(path, _read_toml(path))
    categories: dict[str, tuple[str, ...]] = {}
    seen: dict[str, str] = {}
    ct = t.table("categories")
    for name in list(ct.data):
        hosts = ct.str_list(name)
        for host in hosts:
            if not is_host(host):
                raise ct.error(name, f"{host!r} is not a lowercase host name")
            if host in seen:
                raise ct.error(name, f"{host!r} is already listed in {seen[host]!r}")
            seen[host] = name
        categories[name] = tuple(hosts)
    if not categories:
        raise t.error("categories", "must define at least one category")

    et = t.table("exclude")
    host_labels = tuple(et.str_list("host_labels"))
    path_segments = tuple(et.str_list("path_segments"))
    et.reject_unknown()

    blocklist_file = t.string("blocklist")
    references = tuple(t.str_list("references"))
    for url in references:
        if not _is_http_url(url):
            raise t.error("references", f"{url!r} is not an absolute http(s) URL")
    blocklist_path = path.parent / blocklist_file
    blocklist = load_blocklist(blocklist_path)
    municipal, regional = load_official_sites(path.parent / t.string("official_sites"))
    for host in (*municipal.values(), *regional.values()):
        seen.setdefault(host, "official")
    _reject_blocked(path, seen, blocklist_path.name, blocklist)

    research = _research_languages(t.table("research"), categories)
    t.reject_unknown()
    return Sources(
        categories=categories,
        exclude_host_labels=host_labels,
        exclude_path_segments=path_segments,
        blocklist_file=blocklist_file,
        blocklist=blocklist,
        references=references,
        research=research,
        municipal_sites=municipal,
        regional_sites=regional,
    )


def _reject_blocked(
    path: Path, seen: dict[str, str], name: str, blocklist: frozenset[str]
) -> None:
    """Raise if a host of category ``seen[host]`` is on the blocklist *name*."""
    for host in sorted(seen):
        if is_blocked(host, blocklist):
            raise ConfigError(
                f"{path}: categories.{seen[host]}: {host!r} is blocked by {name}"
            )


def _research_languages(
    rt: _Table, categories: dict[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    research = {}
    for lang in list(rt.data):
        if not _LANG_CODE.fullmatch(lang):
            raise rt.error(lang, "must be a language code")
        names = tuple(rt.str_list(lang))
        for name in names:
            if name not in categories:
                raise rt.error(lang, f"{name!r} is not a category")
        research[lang] = names
    return research


def load_official_sites(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Load the official websites file: obec → host and kraj → host."""
    t = _Table(path, _read_toml(path))
    municipal = _host_table(t.table("obce"), OBEC_CODE)
    regional = _host_table(t.table("kraje"), _KRAJ_CODE)
    t.reject_unknown()
    return municipal, regional


def _host_table(t: _Table, code: re.Pattern[str]) -> dict[str, str]:
    """Return a table of *code* → host name."""
    sites = {}
    for name in list(t.data):
        host = t.string(name)
        if not code.fullmatch(name):
            raise t.error(name, "is not a code")
        if not is_host(host):
            raise t.error(name, f"{host!r} is not a lowercase host name")
        sites[name] = host
    return sites


def load_blocklist(path: Path) -> frozenset[str]:
    """Load a blocklist: one lowercase host per line, ``#`` starts a comment."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"{path}: cannot read: {e.strerror}") from e
    hosts = set()
    for number, line in enumerate(text.splitlines(), 1):
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        if not is_host(entry):
            raise ConfigError(
                f"{path}:{number}: {entry!r} is not a lowercase host name"
            )
        hosts.add(entry)
    return frozenset(hosts)


def _load_input(t: _Table, name: str, entry: object) -> Input:
    key = f"input.{name}"
    if not _INPUT_NAME.fullmatch(name):
        raise t.error(key, "name must be lowercase letters, digits and dashes")
    it = t.entry(key, entry)
    url = it.http_url("url")
    file = it.string("file")
    if not _INPUT_FILE.fullmatch(file):
        raise it.error("file", "must be a plain file name: letters, digits, . _ -")
    kind = it.string("kind")
    if kind not in INPUT_KINDS:
        raise it.error("kind", f"must be one of {', '.join(INPUT_KINDS)}")
    members, expect, volatile = _input_checks(it, kind)
    sha256 = it.optional("sha256", str, "")
    if "sha256" in it.data and not _SHA256.fullmatch(sha256):
        raise it.error("sha256", "must be 64 lowercase hex digits")
    # Written together by `ems inputs update`: a pinned file was downloaded
    # on some day, which About names.
    retrieved = it.date("retrieved") if "retrieved" in it.data else None
    if bool(sha256) != (retrieved is not None):
        raise it.error("retrieved", "must be given exactly where sha256 is")
    optional = it.optional("optional", bool, False)
    as_of = it.optional("as_of", str, "")
    if as_of and not _AS_OF.fullmatch(as_of):
        raise it.error("as_of", "must be YYYY-MM-DD or YYYY-MM")
    # Keys that belong to another kind are reported as unknown here.
    it.reject_unknown()
    return Input(
        name,
        url,
        file,
        kind,
        members,
        expect,
        volatile,
        sha256,
        optional,
        as_of,
        retrieved,
    )


def _input_checks(
    it: _Table, kind: str
) -> tuple[tuple[str, ...], str, re.Pattern[bytes] | None]:
    """Return the kind-specific keys of one input: members, expect, volatile."""
    members: tuple[str, ...] = ()
    if kind in ("zip", "rar"):
        members = tuple(it.str_list("members"))
        if not members:
            raise it.error("members", "must name at least one member")
    # fetch unpacks a RAR's member for the steps to read (fetch.member_path).
    if kind == "rar" and len(members) != 1:
        raise it.error("members", "must name the one member to unpack")
    # Required for html, where a wrong page is otherwise indistinguishable;
    # optional for csv and for the CSV of a RAR.
    expect = ""
    if kind == "html" or (kind in ("csv", "rar") and "expect" in it.data):
        expect = it.nonempty("expect")
    volatile = None
    if kind == "html" and "volatile" in it.data:
        try:
            volatile = re.compile(it.string("volatile").encode())
        except re.error as e:
            raise it.error("volatile", f"invalid regex: {e}") from e
    return members, expect, volatile


def load_inputs(path: Path) -> Inputs:
    """Load ``inputs.toml`` and check that its CA certificate files exist."""
    t = _Table(path, _read_toml(path))
    contact = t.nonempty("contact")
    certs = tuple(path.parent / name for name in t.str_list("ca_certificates"))
    for cert in certs:
        if not cert.is_file():
            raise t.error("ca_certificates", f"{cert} does not exist")
    store = None
    if "store" in t.data:
        st = t.table("store")
        repository = st.string("repository")
        if not _REPOSITORY.fullmatch(repository):
            raise st.error("repository", "must be owner/name of a GitHub repository")
        store = Store(repository, st.nonempty("release"))
        st.reject_unknown()
    inputs = [
        _load_input(t, name, entry) for name, entry in t.get("input", dict).items()
    ]
    if not inputs:
        raise t.error("input", "must define at least one input")
    t.reject_unknown()
    return Inputs(contact, certs, tuple(inputs), store)


def load_overrides(path: Path, slugs: Sequence[str]) -> dict[str, Overrides]:
    """Load ``overrides.toml``: election slug → its table, for every one of *slugs*."""
    t = _Table(path, _read_toml(path))
    tables = t.optional("election", dict, {})
    for slug in tables:
        if slug not in slugs:
            raise t.error(f"election.{slug}", f"no such election in {ELECTIONS_FILE}")
    out = {
        slug: _election_overrides(t.entry(f"election.{slug}", tables.get(slug, {})))
        for slug in slugs
    }
    t.reject_unknown()
    return out


def _election_overrides(t: _Table) -> Overrides:
    """Load one election's table of ``overrides.toml``."""
    obec = _code_table(t, "obec")
    address = _code_table(t, "address")
    skip = t.str_list("address_skip") if "address_skip" in t.data else []
    for table, keys in (("obec", obec), ("address", address), ("address_skip", skip)):
        for key in keys:
            okres, _, name = key.partition("/")
            if not okres.strip() or not name.strip():
                raise t.error(f"{table}.{key}", "key must be '<okres>/<obec>'")
    if overlap := set(address).intersection(skip):
        raise t.error("address_skip", f"{min(overlap)!r} is in [address] too")
    residence = _code_table(t, "residence")
    for key in residence:
        if not contests.CANDIDACY_ID.fullmatch(key):
            raise t.error(f"residence.{key}", "key must be a candidacy id")
    merge: tuple[tuple[str, ...], ...] = ()
    split: tuple[tuple[str, ...], ...] = ()
    if "person" in t.data:
        pt = t.table("person")
        merge = _candidacy_groups(pt, "merge", 2)
        split = _candidacy_groups(pt, "split", 1)
        pt.reject_unknown()
        seen: set[str] = set()
        for group in split:
            if twice := seen.intersection(group):
                raise pt.error("split", f"{min(twice)!r} is split twice")
            seen.update(group)
    t.reject_unknown()
    return Overrides(obec, residence, merge, split, address, frozenset(skip))


def _party_short(pt: _Table) -> str:
    """Return a party's short form.

    A link names the parties of its candidate filter by their short forms
    (web/js/ballots.js ``filterParams``), the independents as "-", in a
    list after "!" when they are hidden. One party can have entries under
    several names (its spelling in another election's lists, a former
    name) with the same short form, so ``build`` checks that the parties of
    each election have distinct ones.
    """
    short = pt.string("short")
    if not short or len(short) > _MAX_SHORT:
        raise pt.error("short", f"must be 1-{_MAX_SHORT} characters")
    if short == "-" or "," in short or short.startswith("!"):
        raise pt.error("short", 'must not be "-", contain "," or start with "!"')
    return short


def load_parties(path: Path, logo_dir: Path, slugs: Sequence[str]) -> dict[str, Party]:
    """Load ``parties.toml`` and check that the logos it names exist.

    *slugs* are the elections', which the logos are of. A coalition's
    ``members`` must be parties of the file, at least two.
    """
    t = _Table(path, _read_toml(path))
    parties = {}
    for name, entry in t.get("party", dict).items():
        pt = t.entry(f"party.{name}", entry)
        short = _party_short(pt)
        full = pt.nonempty("name")
        logos = {}
        for slug, value in pt.optional("logo", dict, {}).items():
            if slug not in slugs:
                raise pt.error(f"logo.{slug}", "not an election of elections.toml")
            lt = pt.entry(f"logo.{slug}", value)
            file = lt.string("file")
            if "/" in file or "\\" in file or not file.endswith(_LOGO_SUFFIXES):
                raise lt.error(
                    "file", f"must be a {'/'.join(_LOGO_SUFFIXES)} file name"
                )
            if not (logo_dir / file).is_file():
                raise lt.error("file", f"{logo_dir / file} does not exist")
            # Logos are redistributed on a public site, so where each one
            # comes from and under which terms must stay on record.
            logos[slug] = Logo(file, lt.http_url("source"), lt.nonempty("license"))
            lt.reject_unknown()
        members = tuple(pt.str_list("members")) if "members" in pt.data else ()
        pt.reject_unknown()
        parties[name] = Party(short, full, logos, members)
    t.reject_unknown()
    for name, party in parties.items():
        _check_members(t, name, party.members, parties)
    return parties


def _check_members(
    t: _Table, name: str, members: Sequence[str], parties: Mapping[str, Party]
) -> None:
    """Check coalition *name*'s *members*: two or more other parties of the file."""
    if not members and "members" not in t.data["party"][name]:
        return
    key = f"party.{name}.members"
    if len(members) < 2 or len(set(members)) != len(members):  # noqa: PLR2004
        raise t.error(key, "must name two or more parties, each once")
    for member in members:
        if member == name or member not in parties:
            raise t.error(key, f"{member!r} is not another party of the file")
        if parties[member].members:
            raise t.error(key, f"{member!r} is a coalition itself")


def load_obvody(path: Path) -> ObvodList:
    """Load one curated obvod membership file.

    Only the form is checked here; whether the members cover their area
    exactly once needs the municipality table (see :mod:`election_map_slovakia.obvody`).
    """
    t = _Table(path, _read_toml(path))
    source = t.http_url("source")
    title = t.nonempty("title")
    date = t.date("date")
    obvody = []
    for key, entry in t.get("obvod", dict).items():
        name = f"obvod.{key}"
        if not _OBVOD_NUMBER.fullmatch(key):
            raise t.error(name, "obvod number must be a positive integer")
        ot = t.entry(name, entry)
        seats = ot.positive_int("seats")
        okresy = _member_list(ot, "okresy", OKRES_CODE, "okres")
        obce = _member_list(ot, "obce", DISTRICT_CODE, "obec")
        ot.reject_unknown()
        if not okresy and not obce:
            raise t.error(name, "must list okresy or obce")
        obvody.append(Obvod(int(key), seats, okresy, obce))
    obvody.sort(key=lambda o: o.number)
    numbers = [o.number for o in obvody]
    if numbers != list(range(1, len(numbers) + 1)):
        raise t.error("obvod", f"must be numbered 1..{len(numbers)} without gaps")
    t.reject_unknown()
    return ObvodList(path, source, title, date, tuple(obvody))


def load_candidates(path: Path, election: Election) -> CuratedLists:
    """Load ``candidates.toml``, the curated candidate lists of *election*.

    Every contest must be one *election*'s kind has (a by-election's,
    one of the self-governments'), round 2 of a presidential election only
    with its ``second_round``; a party list needs its ``[[subject]]``,
    whose party it names, and a parliamentary or European election's
    party contest is its subjects, not a ``[[contest]]``. A contest's
    ``source`` (the URL of the document transcribed) and ``date`` (the date
    it bears, not after the election) come together; a supplement to a
    by-election's package (any format but ``curated``) needs them in every
    contest.
    """
    supplement = election.candidates is not None and (
        election.candidates.format != "curated"
    )
    t = _Table(path, _read_toml(path))
    allowed = contests.ELECTION_KINDS[election.kind]
    subjects = _curated_subjects(t, allowed)
    out: list[CuratedContest] = []
    for i, entry in enumerate(t.get("contest", list)):
        ct = t.entry(f"contest[{i}]", entry)
        cid = ct.nonempty("id")
        try:
            c = contests.parse(cid)
        except contests.ContestError as e:
            raise ct.error("id", str(e)) from None
        if c.kind.name not in allowed or (c.kind.party and not c.is_list):
            raise ct.error("id", f"{cid}: no [[contest]] of a {election.kind} election")
        if c.kind.sub == "round" and c.sub == 2 and election.second_round is None:  # noqa: PLR2004
            raise ct.error("id", f"{cid}: the election has no second_round")
        if any(o.id == cid for o in out):
            raise ct.error("id", f"{cid} is listed twice")
        seats = (
            ct.positive_int("seats")
            if c.kind.sub == "obvod" and "seats" in ct.data
            else None
        )
        party = ct.nonempty("party") if c.is_list else None
        if c.is_list and subjects.get(c.sub or 0) != party:
            raise ct.error("party", f"must be that of [[subject]] number {c.sub}")
        candidates = _curated_candidates(ct, c)
        source, date = _curated_source(ct, election, required=supplement)
        ct.reject_unknown()
        out.append(CuratedContest(cid, seats, party, source, date, candidates))
    t.reject_unknown()
    return CuratedLists(path, tuple(out), tuple(sorted(subjects.items())))


def load_uncontested(path: Path, election: Election) -> tuple[CuratedUncontested, ...]:
    """Load ``uncontested.toml``: contests of *election* held nowhere, uncontested.

    Those the inputs do not tell (ŠÚ SR's territorial division does the
    rest, :func:`election_map_slovakia.lists.read`): a council obvod the
    municipality's decision lists but no candidate stood in, a mayor a
    by-election called beside council seats. Each ``[[contest]]`` has its
    ``id`` (a mayor's or council's contest of the election's kind), the
    ``source`` (the URL of the document saying it was called) and its
    ``title``, a council obvod's ``seats`` where known::

        [[contest]]
        id = "oz:513156/6"
        seats = 1
        source = "https://www.ilava.sk/…"
        title = "Oznámenie … (uznesenie č. 5/2018): obvod 6, celá Iliavka, 1 poslanec"
    """
    t = _Table(path, _read_toml(path))
    allowed = contests.ELECTION_KINDS[election.kind]
    out: list[CuratedUncontested] = []
    for i, entry in enumerate(t.get("contest", list)):
        ct = t.entry(f"contest[{i}]", entry)
        cid = ct.nonempty("id")
        try:
            c = contests.parse(cid)
        except contests.ContestError as e:
            raise ct.error("id", str(e)) from None
        if c.kind.name not in allowed or c.kind.name not in ("starosta", "oz"):
            raise ct.error(
                "id", f"{cid}: no mayor or council of a {election.kind} election"
            )
        if any(o.id == cid for o in out):
            raise ct.error("id", f"{cid} is listed twice")
        seats = (
            ct.positive_int("seats")
            if c.kind.sub == "obvod" and "seats" in ct.data
            else None
        )
        out.append(
            CuratedUncontested(cid, seats, ct.http_url("source"), ct.nonempty("title"))
        )
        ct.reject_unknown()
    t.reject_unknown()
    return tuple(out)


def dump_uncontested(
    entries: Sequence[CuratedUncontested], header: Sequence[str]
) -> str:
    """Return ``uncontested.toml`` of *entries* (:func:`load_uncontested`), *header* its comment."""
    lines = [f"# {h}".rstrip() for h in header]
    for u in entries:
        lines += ["", "[[contest]]", f"id = {_toml_string(u.id)}"]
        if u.seats is not None:
            lines.append(f"seats = {u.seats}")
        lines += [
            f"source = {_toml_string(u.source)}",
            f"title = {_toml_string(u.title)}",
        ]
    return "\n".join(lines) + "\n"


def _toml_string(text: str) -> str:
    """Return *text* (one line) as a TOML basic string."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _curated_source(
    ct: _Table, election: Election, *, required: bool
) -> tuple[str | None, dt.date | None]:
    """Return a ``[[contest]]``'s ``source`` and ``date``, or Nones without."""
    if not required and "source" not in ct.data and "date" not in ct.data:
        return None, None
    source, date = ct.http_url("source"), ct.date("date")
    if date > election.day:
        raise ct.error("date", f"{date} is after the election ({election.day})")
    return source, date


def _curated_subjects(t: _Table, allowed: Sequence[str]) -> dict[int, str]:
    """Return the ``[[subject]]`` of ``candidates.toml``: number → party."""
    if not any(contests.KINDS[k].party for k in allowed):
        if "subject" in t.data:
            raise t.error("subject", "only a party-list election has subjects")
        return {}
    subjects: dict[int, str] = {}
    for i, entry in enumerate(t.get("subject", list)):
        st = t.entry(f"subject[{i}]", entry)
        number, party = st.positive_int("number"), st.nonempty("party")
        st.reject_unknown()
        if number in subjects:
            raise st.error("number", f"{number} is listed twice")
        subjects[number] = party
    if not subjects:
        raise t.error("subject", "must list the parties on the ballot")
    return subjects


def _curated_candidates(
    ct: _Table, c: contests.Contest
) -> tuple[CuratedCandidate, ...]:
    """Return the ``[[contest.candidate]]`` of contest *c*, by number."""
    # A municipal candidate's obec is the contest's; a president's and a
    # list candidate's parties are none and the list's.
    residence = c.kind.scope != "obec"
    parties = c.kind.scope != "country"
    out: dict[int, CuratedCandidate] = {}
    for i, entry in enumerate(ct.get("candidate", list)):
        pt = ct.entry(f"candidate[{i}]", entry)
        number = pt.positive_int("number")
        if number in out:
            raise pt.error("number", f"{number} is listed twice")
        out[number] = CuratedCandidate(
            number=number,
            title_before=pt.optional("title_before", str, ""),
            first_name=pt.nonempty("first_name"),
            surname=pt.nonempty("surname"),
            title_after=pt.optional("title_after", str, ""),
            age=pt.positive_int("age"),
            occupation=pt.string("occupation"),
            parties=tuple(pt.str_list("parties")) if parties else (),
            residence=pt.optional("residence", str, "") if residence else "",
            withdrawn=pt.optional("withdrawn", bool, False),
        )
        pt.reject_unknown()
    if not out:
        raise ct.error("candidate", "must list the contest's candidates")
    return tuple(out[n] for n in sorted(out))


def _member_list(
    t: _Table, key: str, pattern: re.Pattern[str], kind: str
) -> tuple[str, ...]:
    if key not in t.data:
        return ()
    codes = t.str_list(key)
    if not codes:
        raise t.error(key, "must not be empty; leave the key out instead")
    for code in codes:
        if not pattern.fullmatch(code):
            raise t.error(key, f"{code!r} is not an {kind} code")
    return tuple(codes)


def _code_table(t: _Table, key: str) -> dict[str, str]:
    table = t.optional(key, dict, {})
    for name, code in table.items():
        if not isinstance(code, str) or not OBEC_CODE.fullmatch(code):
            raise t.error(f"{key}.{name}", f"{code!r} is not an obec code")
    return table


def _candidacy_groups(t: _Table, key: str, minimum: int) -> tuple[tuple[str, ...], ...]:
    if key not in t.data:
        return ()
    groups = []
    for number, entry in enumerate(t.get(key, list), 1):
        gt = t.entry(f"{key}[{number}]", entry)
        ids = gt.str_list("candidacies")
        gt.reject_unknown()
        if len(ids) < minimum:
            raise gt.error("candidacies", f"must list at least {minimum}")
        if len(set(ids)) != len(ids):
            raise gt.error("candidacies", "lists a candidacy twice")
        for cid in ids:
            if not contests.CANDIDACY_ID.fullmatch(cid):
                raise gt.error("candidacies", f"{cid!r} is not a candidacy id")
        groups.append(tuple(ids))
    return tuple(groups)


def is_host(value: str) -> bool:
    """Return whether *value* is a lowercase DNS host name with a dot."""
    labels = value.split(".")
    # A bare TLD is no host.
    return len(labels) > 1 and all(
        len(label) <= _MAX_LABEL and _LABEL.fullmatch(label) for label in labels
    )


def is_blocked(host: str, blocklist: frozenset[str]) -> bool:
    """Return whether *host* or any parent domain of it is in *blocklist*."""
    labels = host.split(".")
    return any(".".join(labels[i:]) in blocklist for i in range(len(labels)))


def _is_http_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"{path}: cannot read: {e.strerror}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML: {e}") from e


class _Table:
    """Typed access to one TOML table, tracking which keys were used."""

    def __init__(self, path: Path, data: dict[str, Any], prefix: str = "") -> None:
        self.path = path
        self.data = data
        self.prefix = prefix
        self.used: set[str] = set()

    def error(self, key: str, message: str) -> ConfigError:
        return ConfigError(f"{self.path}: {self.prefix}{key}: {message}")

    def get(self, key: str, kind: type[_T]) -> _T:
        if key not in self.data:
            raise self.error(key, "missing")
        value = self.data[key]
        # bool is an int subclass; a `true` where a number belongs is a typo.
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            raise self.error(
                key, f"expected {kind.__name__}, got {type(value).__name__}"
            )
        self.used.add(key)
        return value

    def optional(self, key: str, kind: type[_T], default: _T) -> _T:
        return self.get(key, kind) if key in self.data else default

    def string(self, key: str) -> str:
        return self.get(key, str)

    def nonempty(self, key: str) -> str:
        value = self.string(key)
        if not value:
            raise self.error(key, "must not be empty")
        return value

    def http_url(self, key: str) -> str:
        value = self.string(key)
        if not _is_http_url(value):
            raise self.error(key, "must be an absolute http(s) URL")
        return value

    def date(self, key: str) -> dt.date:
        value = self.get(key, dt.date)
        # A TOML datetime is a dt.date too.
        if isinstance(value, dt.datetime):
            raise self.error(key, "must be a date without a time")
        return value

    def table(self, key: str) -> _Table:
        """Return the subtable *key*."""
        return self.entry(key, self.get(key, dict))

    def entry(self, key: str, value: object) -> _Table:
        """Return *value*, found under *key*, as a table; raise if it is none."""
        if not isinstance(value, dict):
            raise self.error(key, "must be a table")
        return _Table(self.path, value, prefix=f"{self.prefix}{key}.")

    def positive_int(self, key: str) -> int:
        value = self.get(key, int)
        if value <= 0:
            raise self.error(key, "must be a positive integer")
        return value

    def str_list(self, key: str) -> list[str]:
        value = self.get(key, list)
        if not all(isinstance(item, str) and item for item in value):
            raise self.error(key, "must be a list of non-empty strings")
        return value

    def reject_unknown(self) -> None:
        unknown = sorted(set(self.data) - self.used)
        if unknown:
            raise self.error(unknown[0], "unknown key")
