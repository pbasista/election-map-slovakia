"""Load and validate the project configuration in ``config/``.

Every error names the file and the key, so a typo in a TOML file is reported
where it is, not as a failure somewhere downstream.
"""

from __future__ import annotations

import datetime as dt
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

SITE_FILE = "site.toml"
LANGUAGES_FILE = "languages.toml"
SOURCES_FILE = "sources.toml"
INPUTS_FILE = "inputs.toml"
OVERRIDES_FILE = "overrides.toml"
PARTIES_FILE = "parties.toml"
# Relative to the project root; the files are copied to dist/ with web/.
PARTY_LOGO_DIR = Path("web") / "img" / "parties"
_LOGO_SUFFIXES = (".svg", ".png", ".webp")
# Short forms go into compact candidate rows next to the name.
_MAX_SHORT = 20

INPUT_KINDS = ("xlsx", "zip", "csv", "pdf", "html", "geojson")
_INPUT_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
# ZBGIS municipality code (ŠÚ SR, 6 digits) or one of the two synthetic city
# codes; candidacy ids as in docs/pipeline.md (Identifiers).
OBEC_CODE = re.compile(r"\d{6}|BA|KE")
CANDIDACY_ID = re.compile(
    r"(?:starosta|oz):(?:\d{6}|BA|KE)(?:/\d+)?#\d+|(?:predseda|zsk):\d(?:/\d+)?#\d+"
)
OKRES_CODE = re.compile(r"\d{3}")
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
    """``site.toml``: identity of the site and output budgets."""

    base_url: str | None
    repository: str
    """The source code repository, linked from the About dialog."""
    pages_project: str
    """Cloudflare Pages project the deploy workflow uploads to."""
    election: dt.date
    results_mode: bool
    file_budget: int
    max_file_bytes: int
    cache_image_max_bytes: int


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
    """The digest the file must have (a pinned release), or empty."""


@dataclass(frozen=True)
class Inputs:
    """``inputs.toml``: what ``fetch`` downloads and how it checks it."""

    contact: str
    ca_certificates: tuple[Path, ...]
    inputs: tuple[Input, ...]


@dataclass(frozen=True)
class Overrides:
    """``overrides.toml``: manual fixes for matching names to codes."""

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
    """``data/curated/obvody/<area>.toml``: which units form each obvod."""

    path: Path
    source: str
    """URL of the official document the membership was transcribed from."""
    date: dt.date
    """Date of the decision that set the obvody."""
    obvody: tuple[Obvod, ...]
    """Sorted by number, numbered 1..N without gaps."""


@dataclass(frozen=True)
class Party:
    """One entry of ``parties.toml``."""

    short: str
    """The form Slovak media use, for compact candidate rows."""
    name: str
    """Official name as in the Ministry of Interior's party register."""
    logo: str
    """File name in ``web/img/parties/``, or empty."""
    logo_source: str
    """Page the logo was taken from (empty without a logo)."""
    logo_license: str


@dataclass(frozen=True)
class Config:
    """The whole configuration, loaded from one directory."""

    root: Path
    site: Site
    languages: Languages
    sources: Sources
    inputs: Inputs
    overrides: Overrides
    parties: dict[str, Party]
    """Party name as written in the candidate lists → its entry."""

    @property
    def raw_dir(self) -> Path:
        """Return ``data/raw``, where downloads and their manifest live."""
        return self.root / "data" / "raw"

    @property
    def build_dir(self) -> Path:
        """Return ``data/build``, for intermediate pipeline output."""
        return self.root / "data" / "build"

    @property
    def curated_dir(self) -> Path:
        """Return ``data/curated``, for hand-curated, committed inputs."""
        return self.root / "data" / "curated"


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
    return Config(
        root=root,
        site=load_site(directory / SITE_FILE),
        languages=load_languages(directory / LANGUAGES_FILE),
        sources=load_sources(directory / SOURCES_FILE),
        inputs=load_inputs(directory / INPUTS_FILE),
        overrides=load_overrides(directory / OVERRIDES_FILE),
        parties=load_parties(directory / PARTIES_FILE, root / PARTY_LOGO_DIR),
    )


def load_site(path: Path) -> Site:
    """Load ``site.toml``."""
    t = _Table(path, _read_toml(path))
    base_url = t.string("base_url")
    if base_url and not base_url.startswith(("https://", "http://")):
        raise t.error("base_url", "must be empty or an absolute http(s) URL")
    repository = t.string("repository").rstrip("/")
    if not repository.startswith("https://"):
        raise t.error("repository", "must be an absolute https URL")
    election = t.get("election", dt.date)
    if isinstance(election, dt.datetime):
        raise t.error("election", "must be a date without a time")
    pages_project = t.string("pages_project")
    # It becomes the host name <project>.pages.dev.
    if len(pages_project) > _MAX_LABEL or not _LABEL.fullmatch(pages_project):
        raise t.error("pages_project", "must be lowercase letters, digits and dashes")
    site = Site(
        base_url=base_url.rstrip("/") or None,
        pages_project=pages_project,
        repository=repository,
        election=election,
        results_mode=t.get("results_mode", bool),
        file_budget=t.positive_int("file_budget"),
        max_file_bytes=t.positive_int("max_file_bytes"),
        cache_image_max_bytes=t.positive_int("cache_image_max_bytes"),
    )
    t.reject_unknown()
    return site


def _load_language(t: _Table, code: str, entry: object) -> Language:
    key = f"language.{code}"
    if not _LANG_CODE.fullmatch(code):
        raise t.error(key, "language code must be 2-3 lowercase letters")
    if not isinstance(entry, dict):
        raise t.error(key, "must be a table")
    lt = _Table(t.path, entry, prefix=key + ".")
    lang = Language(
        code=code,
        name=lt.string("name"),
        site_name=lt.string("site_name"),
        script=lt.string("script"),
        direction=lt.string("direction"),
    )
    if not lang.name:
        raise lt.error("name", "must not be empty")
    if not lang.site_name:
        raise lt.error("site_name", "must not be empty")
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
    ct = _Table(path, t.get("categories", dict), prefix="categories.")
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

    et = _Table(path, t.get("exclude", dict), prefix="exclude.")
    host_labels = tuple(et.str_list("host_labels"))
    path_segments = tuple(et.str_list("path_segments"))
    et.reject_unknown()

    blocklist_file = t.string("blocklist")
    references = tuple(t.str_list("references"))
    for url in references:
        if not url.startswith(("https://", "http://")):
            raise t.error("references", f"{url!r} is not an absolute http(s) URL")
    blocklist_path = path.parent / blocklist_file
    blocklist = load_blocklist(blocklist_path)
    municipal, regional = load_official_sites(path.parent / t.string("official_sites"))
    for host in (*municipal.values(), *regional.values()):
        seen.setdefault(host, "official")
    _reject_blocked(path, seen, blocklist_path.name, blocklist)

    research = _research_languages(
        _Table(path, t.get("research", dict), "research."), categories
    )
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
    tables = []
    for key, code in (("obce", OBEC_CODE), ("kraje", re.compile(r"\d"))):
        st = _Table(path, t.get(key, dict), prefix=f"{key}.")
        sites = {}
        for name in list(st.data):
            host = st.string(name)
            if not code.fullmatch(name):
                raise st.error(name, "is not a code")
            if not is_host(host):
                raise st.error(name, f"{host!r} is not a lowercase host name")
            sites[name] = host
        tables.append(sites)
    t.reject_unknown()
    return tables[0], tables[1]


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
    if not isinstance(entry, dict):
        raise t.error(key, "must be a table")
    it = _Table(t.path, entry, prefix=key + ".")
    url = it.string("url")
    if not url.startswith(("https://", "http://")):
        raise it.error("url", "must be an absolute http(s) URL")
    file = it.string("file")
    if not file or "/" in file or "\\" in file or file.startswith("."):
        raise it.error("file", "must be a plain file name")
    kind = it.string("kind")
    if kind not in INPUT_KINDS:
        raise it.error("kind", f"must be one of {', '.join(INPUT_KINDS)}")
    members, expect, volatile = _input_checks(it, kind)
    sha256 = it.string("sha256") if "sha256" in it.data else ""
    if "sha256" in it.data and not _SHA256.fullmatch(sha256):
        raise it.error("sha256", "must be 64 lowercase hex digits")
    # Keys that belong to another kind are reported as unknown here.
    it.reject_unknown()
    return Input(name, url, file, kind, members, expect, volatile, sha256)


def _input_checks(
    it: _Table, kind: str
) -> tuple[tuple[str, ...], str, re.Pattern[bytes] | None]:
    """Return the kind-specific keys of one input: members, expect, volatile."""
    members: tuple[str, ...] = ()
    if kind == "zip":
        members = tuple(it.str_list("members"))
        if not members:
            raise it.error("members", "must name at least one member")
    # Required for html, where a wrong page is otherwise indistinguishable;
    # optional for csv.
    expect = ""
    if kind == "html" or (kind == "csv" and "expect" in it.data):
        expect = it.string("expect")
        if not expect:
            raise it.error("expect", "must not be empty")
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
    contact = t.string("contact")
    if not contact:
        raise t.error("contact", "must not be empty")
    certs = tuple(path.parent / name for name in t.str_list("ca_certificates"))
    for cert in certs:
        if not cert.is_file():
            raise t.error("ca_certificates", f"{cert} does not exist")
    inputs = [
        _load_input(t, name, entry) for name, entry in t.get("input", dict).items()
    ]
    if not inputs:
        raise t.error("input", "must define at least one input")
    t.reject_unknown()
    return Inputs(contact, certs, tuple(inputs))


def load_overrides(path: Path) -> Overrides:
    """Load ``overrides.toml``."""
    t = _Table(path, _read_toml(path))
    obec = _code_table(t, "obec")
    address = _code_table(t, "address")
    for table, codes in (("obec", obec), ("address", address)):
        for key in codes:
            okres, _, name = key.partition("/")
            if not okres.strip() or not name.strip():
                raise t.error(f"{table}.{key}", "key must be '<okres>/<obec>'")
    residence = _code_table(t, "residence")
    for key in residence:
        if not CANDIDACY_ID.fullmatch(key):
            raise t.error(f"residence.{key}", "key must be a candidacy id")
    merge: tuple[tuple[str, ...], ...] = ()
    split: tuple[tuple[str, ...], ...] = ()
    if "person" in t.data:
        pt = _Table(path, t.get("person", dict), prefix="person.")
        merge = _candidacy_groups(pt, "merge", 2)
        split = _candidacy_groups(pt, "split", 1)
        pt.reject_unknown()
        seen: set[str] = set()
        for group in split:
            if seen & set(group):
                raise pt.error(
                    "split", f"{sorted(seen & set(group))[0]!r} is split twice"
                )
            seen |= set(group)
    t.reject_unknown()
    return Overrides(obec, residence, merge, split, address)


def load_parties(path: Path, logo_dir: Path) -> dict[str, Party]:
    """Load ``parties.toml`` and check that the logos it names exist."""
    t = _Table(path, _read_toml(path))
    parties = {}
    for name, entry in t.get("party", dict).items():
        key = f"party.{name}"
        if not isinstance(entry, dict):
            raise t.error(key, "must be a table")
        pt = _Table(path, entry, prefix=key + ".")
        short = pt.string("short")
        if not short or len(short) > _MAX_SHORT:
            raise pt.error("short", f"must be 1-{_MAX_SHORT} characters")
        full = pt.string("name")
        if not full:
            raise pt.error("name", "must not be empty")
        logo = source = license_ = ""
        if "logo" in pt.data:
            logo = pt.string("logo")
            if "/" in logo or "\\" in logo or not logo.endswith(_LOGO_SUFFIXES):
                raise pt.error(
                    "logo", f"must be a {'/'.join(_LOGO_SUFFIXES)} file name"
                )
            if not (logo_dir / logo).is_file():
                raise pt.error("logo", f"{logo_dir / logo} does not exist")
            # Logos are redistributed on a public site, so where each one
            # comes from and under which terms must stay on record.
            source = pt.string("logo_source")
            if not source.startswith(("https://", "http://")):
                raise pt.error("logo_source", "must be an absolute http(s) URL")
            license_ = pt.string("logo_license")
            if not license_:
                raise pt.error("logo_license", "must not be empty")
        pt.reject_unknown()
        parties[name] = Party(short, full, logo, source, license_)
    t.reject_unknown()
    return parties


def load_obvody(path: Path) -> ObvodList:
    """Load one curated obvod membership file.

    Only the form is checked here; whether the members cover their area
    exactly once needs the municipality table (see :mod:`election_map_slovakia.obvody`).
    """
    t = _Table(path, _read_toml(path))
    source = t.string("source")
    if not source.startswith(("https://", "http://")):
        raise t.error("source", "must be an absolute http(s) URL")
    date = t.get("date", dt.date)
    if isinstance(date, dt.datetime):
        raise t.error("date", "must be a date without a time")
    table = t.get("obvod", dict)
    obvody = []
    for key, entry in table.items():
        name = f"obvod.{key}"
        if not _OBVOD_NUMBER.fullmatch(key):
            raise t.error(name, "obvod number must be a positive integer")
        if not isinstance(entry, dict):
            raise t.error(name, "must be a table")
        ot = _Table(path, entry, prefix=name + ".")
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
    return ObvodList(path, source, date, tuple(obvody))


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
    table = t.get(key, dict)
    for name, code in table.items():
        if not isinstance(code, str) or not OBEC_CODE.fullmatch(code):
            raise t.error(f"{key}.{name}", f"{code!r} is not an obec code")
    return table


def _candidacy_groups(t: _Table, key: str, minimum: int) -> tuple[tuple[str, ...], ...]:
    if key not in t.data:
        return ()
    groups = []
    for number, entry in enumerate(t.get(key, list), 1):
        name = f"{key}[{number}]"
        if not isinstance(entry, dict):
            raise t.error(name, "must be a table")
        gt = _Table(t.path, entry, prefix=f"{t.prefix}{name}.")
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

    def string(self, key: str) -> str:
        return self.get(key, str)

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
