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
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

SITE_FILE = "site.toml"
LANGUAGES_FILE = "languages.toml"
SOURCES_FILE = "sources.toml"
INPUTS_FILE = "inputs.toml"
ELECTIONS_FILE = "elections.toml"
OVERRIDES_FILE = "overrides.toml"
PARTIES_FILE = "parties.toml"
RESULTS_ANYTIME_ENV = "EMS_RESULTS_ANYTIME"
"""Set to 1 at build time for testing with the output of ``ems results fake``
or ``poll`` before an election: the app then reads the results of every
election every minute at any time, not only from the polls' closing
(elections.toml ``live``, ``live_days``)."""
# The elections' times (elections.toml polls_open, polls_close) are Slovak time.
_SLOVAK_TIME = ZoneInfo("Europe/Bratislava")
ELECTIONS_DIR = "elections"
"""Below ``data/curated/``: the data of each election (:meth:`Config.election_dir`)."""
RESULTS_DIR = "results"
"""Below each election's build directory and below ``dist/``: the results
of that election (:meth:`Config.results_dir`)."""
ELECTION_KINDS = ("municipal-regional",)
"""The kinds of election (elections.toml ``kind``), each the app names
with its own heading in the list of elections (UI string
``elections.kind.<kind>``): ``municipal-regional``, the municipal and
regional elections held together. The steps read those only, so far."""
CANDIDATE_FORMATS = {
    "mvsr": ("starosta", "oz", "predseda", "zsk"),
    "susr": ("oso", "osk"),
}
"""Format of an election's candidate lists → the inputs ``candidates``
names: ``mvsr``, the four lists MV SR publishes before an election (xlsx),
one per contest kind; ``susr``, ŠÚ SR's definitive packages of the
municipal (``oso``) and regional (``osk``) elections, whose tables list the
candidates (src/election_map_slovakia/statoffice.py)."""
UNIT_FORMATS = ("xlsx", "susr")
"""Format of an election's territorial division (ŠÚ SR ``tab0dd``): ``xlsx``,
the table alone; ``susr``, the table in ŠÚ SR's package of the municipal
elections (statoffice.py)."""
RESULT_FORMATS = {"volbysr": None, "susr": ("oso", "osk")}
"""Format of an election's definitive results → what its inputs are, in
order (None: any number, none until published): ``volbysr``, the CSV
tables of ŠÚ SR's results site of 2026 (results.py ``read_final``);
``susr``, ŠÚ SR's packages of the municipal and regional elections of
2022 (statoffice.py)."""
ZBGIS_LEVELS = 3
"""ZBGIS levels of detail an election names, 0 (full detail) to 2."""
# An election's slug starts with a digit (it is the year), so that its
# pages and files (/<lang>/<slug>/, /<slug>/) never take the name of a
# language or of a directory the elections share.
_SLUG = re.compile(r"\d[0-9a-z]*(?:-[0-9a-z]+)*")
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
# codes; candidacy ids as in docs/pipeline.md (Identifiers).
OBEC_CODE = re.compile(r"\d{6}|BA|KE")
CANDIDACY_ID = re.compile(
    r"(?:starosta|oz):(?:\d{6}|BA|KE)(?:/\d+)?#\d+|(?:predseda|zsk):\d(?:/\d+)?#\d+"
)
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
    sources_project: str
    results_project: str
    sources_url: str
    """Where the sources project serves the cached copies the app links."""
    results_url: str
    """Where the results project serves the results the app fetches."""
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
    """One of :data:`CANDIDATE_FORMATS`: how the lists are read."""
    inputs: dict[str, str]
    """What the format reads (for ``mvsr`` a contest kind) → input name."""


@dataclass(frozen=True)
class Units:
    """Where an election's territorial division comes from (``elections.toml``)."""

    format: str
    """One of :data:`UNIT_FORMATS`: how the table is read."""
    input: str


@dataclass(frozen=True)
class Results:
    """Where an election's definitive results come from (``elections.toml``)."""

    format: str
    """One of :data:`RESULT_FORMATS`: how the packages are read."""
    inputs: tuple[str, ...]
    """The packages; none until they are published."""


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
    """Whether the app polls the results (``live``, or
    ``EMS_RESULTS_ANYTIME=1``); without, it reads them once per page load."""
    live_window: tuple[dt.datetime, dt.datetime] | None
    """When the app, polling, reads the results every minute: from the
    polls' closing for ``live_days``; before, it reads nothing, after, once
    per page load. None with ``EMS_RESULTS_ANYTIME=1``, for testing: any
    time."""
    candidates: CandidateLists
    incumbents: Incumbents | None
    """None where the office holders before it are not known."""
    units: Units
    """The territorial division (ŠÚ SR tab0dd): okrsky per obec."""
    results: Results
    """The definitive results (municipal, regional), once published."""
    addresses: str
    """The address register."""
    zbgis: tuple[str, ...]
    """The administrative boundaries, by level of detail (0 to 2)."""
    osm: str
    """The OpenStreetMap extract of the base map."""
    records: tuple[str, ...]
    """Records of sources no step reads (optional inputs): the documents
    the curated obvody come from, the originals of data that stand in."""


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
        return f"{inp.sha256}-{inp.file}"

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
        """Return the newest election, the one ``/<lang>/`` shows."""
        return self.elections[0]

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
        return self.root / "data" / "build"

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

        ``candidates.json``, ``addr/``, ``obvod-addresses/``, ``geo/``,
        ``base/``, its results (:meth:`results_dir`), and the stamps and
        gzip memos of its steps.
        """
        return self.build_dir / election.day.isoformat()

    def results_dir(self, election: Election) -> Path:
        """Return ``data/build/<day>/results``: *election*'s results.

        ``ems results`` (``poll``, ``final``, ``fake``) writes them, the
        ``results`` step of ``ems make`` from the final results inputs;
        ``build`` copies them to ``dist/results/<day>/``.
        """
        return self.election_build_dir(election) / RESULTS_DIR


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
            "sources_project",
            "results_project",
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
    urls = {key: t.string(key).rstrip("/") for key in ("sources_url", "results_url")}
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
    elections.sort(key=lambda e: e.day, reverse=True)
    for newer, older in itertools.pairwise(elections):
        if newer.day == older.day:
            raise t.error(f"election.{older.slug}.day", f"{older.day} is taken")
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
    if not _SLUG.fullmatch(slug):
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
    ct = et.table("candidates")
    format_ = _one_of(ct, "format", CANDIDATE_FORMATS)
    lists = CandidateLists(
        format_, {part: name(ct, part) for part in CANDIDATE_FORMATS[format_]}
    )
    ct.reject_unknown()
    ut = et.table("units")
    units_format = _one_of(ut, "format", UNIT_FORMATS)
    units = Units(units_format, name(ut, "input"))
    ut.reject_unknown()
    rt = et.table("results")
    results_format = _one_of(rt, "format", RESULT_FORMATS)
    packages = tuple(
        _input_name(rt, "inputs", v, known, False) for v in rt.str_list("inputs")
    )
    kinds = RESULT_FORMATS[results_format]
    if kinds is not None and len(packages) != len(kinds):
        raise rt.error("inputs", f"must name the packages {', '.join(kinds)}")
    rt.reject_unknown()
    zbgis = names("zbgis")
    if len(zbgis) != ZBGIS_LEVELS:
        raise et.error("zbgis", f"must name {ZBGIS_LEVELS} levels, 0 to 2")
    election = Election(
        day=day,
        slug=slug,
        kind=kind,
        polls_open=polls_open,
        polls_close=polls_close,
        live=et.get("live", bool) or anytime,
        live_window=None if anytime else (polls_close, polls_close + live_days),
        candidates=lists,
        incumbents=_load_incumbents(et, day, name) if "incumbents" in et.data else None,
        units=units,
        results=Results(results_format, packages),
        addresses=name(et, "addresses"),
        zbgis=zbgis,
        osm=name(et, "osm"),
        records=names("records", optional=True),
    )
    et.reject_unknown()
    return election


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
        if not CANDIDACY_ID.fullmatch(key):
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

    *slugs* are the elections', which the logos are of.
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
        pt.reject_unknown()
        parties[name] = Party(short, full, logos)
    t.reject_unknown()
    return parties


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
            if not CANDIDACY_ID.fullmatch(cid):
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
