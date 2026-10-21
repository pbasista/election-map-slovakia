"""Turn the MV SR candidate lists into contests, candidacies and persons.

The four lists (mayors, municipal councils, regional presidents, regional
councils) carry municipality names but no codes, so every municipality is
matched by name within its okres to a ZBGIS obec (the 6-digit ŠÚ SR code);
the cities of Bratislava and Košice, which ZBGIS has only as districts, get
the synthetic codes ``BA`` and ``KE``. Persons are not identified in the
lists; candidacies are merged into persons by obec, name and age.

Output, ``data/build/candidates.json`` (UTF-8, compact, sorted; codes are
strings; keys in parentheses are omitted where they do not apply)::

    kraje:       [{code, name}]                         code "1".."8" (ZBGIS IDN2)
    okresy:      [{code, name, kraj}]                   code "101".."813" (IDN3)
    obce:        [{code, name, (okres), kraj, (city)}]  city: BA/KE for districts
    contests:    [{id, kind, area, (obvod), (incumbent),
                   (seats_2022)}]                       id "oz:528595/2"
    candidacies: [{id, contest, number, person, title_before, title_after,
                   first_name, surname, age, occupation, parties, independent,
                   (residence), (incumbent)}]           id "oz:528595/2#7"
    persons:     [{id, obec, candidacies}]

``kind`` is ``starosta``, ``oz``, ``predseda`` or ``zsk``; ``area`` is an
obec code for the first two and a kraj code for the others. ``parties`` is
the list of nominating parties (a coalition has several), empty for an
independent candidate. ``residence`` is the obec of residence of regional
candidates. A person's ``obec`` is the obec its candidacies were merged on,
with Bratislava and Košice districts counted as their city.

Current office holders (see :mod:`election_map_slovakia.incumbents`): a
candidacy's ``incumbent`` lists every role its person holds now, in any
body, as ``[{body, since, result}]`` (``body`` is a contest id without obvod,
such as ``starosta:500011`` or ``zsk:4``; ``since`` the ISO day the role was
won); a mayor or president contest's ``incumbent`` is ``{name, since,
candidacy, result}``, the holder's name with titles, and its candidacy in
that contest or null. ``result`` is how the role was won,
``{votes, valid, voters, eligible, (obvod)}`` (:func:`incumbents.result_json`).
Both are omitted when empty or vacant. A council contest's ``seats_2022`` is
the number of councillors the whole council of its area had elected in the
regular election of 2022 (by-elections leave it unchanged).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from election_map_slovakia import incumbents, output, progress, xlsx
from election_map_slovakia.config import Overrides
from election_map_slovakia.gpkg import GeoPackage

if TYPE_CHECKING:
    import datetime as dt

KINDS = ("starosta", "oz", "predseda", "zsk")
MUNICIPAL = ("starosta", "oz")
OUTPUT_FILE = "candidates.json"
# Inputs in config/inputs.toml: the list of each contest kind, and the
# boundaries level whose attribute tables name the municipalities.
INPUTS = {
    "starosta": "candidates-starosta",
    "oz": "candidates-oz",
    "predseda": "candidates-predseda",
    "zsk": "candidates-zsk",
}
ZBGIS_INPUT = "zbgis-0"
PERSON_ID_LENGTH = 12
# Merge obec, normalized first name, normalized surname, age.
PersonKey = tuple[str, str, str, int]
_INDEPENDENT = frozenset({"nezávislý kandidát", "nezávislá kandidátka"})
_DASH = r"\-\u2010-\u2015"
_SPLIT_NAME = re.compile(rf"[\s{_DASH}]+")
_AROUND_DASH = re.compile(rf"\s*[{_DASH}]\s*")
_SPACES = re.compile(r"\s+")
_SEPARATORS = re.compile(r"[\W_]+")


@dataclass(frozen=True)
class City:
    """A city whose districts are municipalities of their own in ZBGIS."""

    code: str
    name: str
    kraj: str
    okres: str
    """The okres code the candidate lists use for city-wide contests."""
    district_okresy: frozenset[str]
    """The okresy that consist of the city's districts."""


CITIES = (
    City(
        "BA", "Bratislava", "1", "100", frozenset({"101", "102", "103", "104", "105"})
    ),
    City("KE", "Košice", "8", "800", frozenset({"802", "803", "804", "805"})),
)
CITY_CODES = frozenset(city.code for city in CITIES)


class CandidatesError(Exception):
    """The candidate lists cannot be parsed or matched."""


@dataclass(frozen=True)
class Obec:
    """A municipality: a ZBGIS obec or one of the two cities."""

    code: str
    name: str
    okres: str | None
    kraj: str
    city: str | None = None
    """The city of a Bratislava or Košice district."""


@dataclass
class Admin:
    """The administrative units from ZBGIS plus the two cities."""

    kraje: dict[str, str]
    okresy: dict[str, tuple[str, str]]
    """Okres code → (name, kraj code)."""
    obce: dict[str, Obec]


def load_admin(gpkg: Path) -> Admin:
    """Read kraje, okresy and obce from a ZBGIS boundaries GeoPackage."""
    with (
        progress.stage(f"reading kraje, okresy and obce from {gpkg.name}"),
        GeoPackage(gpkg) as g,
    ):
        kraje = {str(c): n for c, n in g.rows(g.layer("kraj"), ["IDN2", "NM2"])}
        okresy = {
            str(c): (n, str(k))
            for c, n, k in g.rows(g.layer("okres"), ["IDN3", "NM3", "IDN2"])
        }
        rows = list(g.rows(g.layer("obec"), ["IDN4", "NM4", "IDN3", "IDN2"]))
    district_city = {o: city.code for city in CITIES for o in city.district_okresy}
    obce = {city.code: Obec(city.code, city.name, None, city.kraj) for city in CITIES}
    for code, name, okres, kraj in rows:
        okres = str(okres)
        obce[str(code)] = Obec(
            str(code), name, okres, str(kraj), district_city.get(okres)
        )
    return Admin(kraje, okresy, obce)


def name_key(name: str) -> str:
    """Return the key under which municipality and okres names are compared.

    The lists and ZBGIS differ in spacing around dashes (``Bratislava -
    Staré Mesto``, ``Košice - okolie`` vs ``Košice okolie``) and in doubled
    spaces, never in letters, so dashes and spaces are equated and case and
    diacritics are kept.
    """
    words = _SPLIT_NAME.split(unicodedata.normalize("NFC", name).strip())
    return " ".join(w for w in words if w)


def search_key(text: str) -> str:
    """Return *text* as the search compares it.

    Case, diacritics, dashes and punctuation are ignored: ``Nám. SNP`` and
    ``nam snp``, ``Bratislava–Staré Mesto`` and ``bratislava stare mesto``
    are equal.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    letters = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _SEPARATORS.sub(" ", letters.casefold()).strip()


def person_name_key(name: str) -> str:
    """Return the key under which person names are compared for merging.

    Diacritics are kept: Tóth and Toth are different people.
    """
    text = unicodedata.normalize("NFC", name).strip()
    text = _AROUND_DASH.sub("-", _SPACES.sub(" ", text))
    return text.casefold()


def clean(text: str) -> str:
    """Return *text* with surrounding and repeated whitespace removed."""
    return _SPACES.sub(" ", text).strip()


# Title tokens are compared casefolded without dots, so "PhD", "Ph.D." and
# "Phd." are one key. Post-nominal keys, from every distinct token in the
# 2026 municipal lists; everything else is written before the name.
_POST_NOMINAL = frozenset(
    {
        # Doctorates and higher degrees
        "phd", "csc", "drsc", "dsc", "artd", "thd", "lld", "drph", "dmd",
        # Master's and bachelor's degrees (international usage)
        "mba", "emba", "dba", "dpa", "mpa", "mph", "mha", "msc", "ma", "mm",
        "mst", "mres", "mjur", "mpol", "llm", "bsc", "bs", "ba", "bba", "bsba",
        "bahons", "ba(hons)", "hdipnmt",
        # Higher vocational diplomas
        "dis", "disart", "diplf", "dipls", "diplo", "diplra", "diplmtl", "dpos",
        # Professional qualifications
        "ca", "cfc", "fesc", "frcp", "rsc", "euring", "ingpaedigip",
        "ing-paedigip", "oly",
    }
)  # fmt: skip
# Tokens the lists write in several parts, as sequences of keys; they are
# joined before classifying, so "Mgr. art." or "Ph. D." stays one title.
_TITLE_PHRASES = tuple(
    sorted(
        (
            tuple(p.split())
            for p in (
                "ph d", "m a", "m sc", "ll m", "dis art", "eur ing",
                "ing paed igip", "ing- paed igip", "ing-paed igip",
                "dr h c", "dr phil", "dr med dent", "dr techn", "dr jur",
                "mag iur", "mag phil", "mgr art", "mgr a", "ing arch",
                "akad soch", "plk v v", "univ doc", "univ prof",
                "dipl f", "dipl s", "dipl m t l", "dipl-ing (univ)",
                "ba (hons)", "ba hons",
            )
        ),
        key=len,
        reverse=True,
    )
)  # fmt: skip
# Titles written without a space ("PhDr.Ing.", "LL.M.Dr.h.c.") are split
# after these keys only; elsewhere a dot inside a token is part of it
# ("Ph.D.", "M.B.A.", "Dr.P.H.").
_GLUED_HEADS = frozenset(
    {
        "bc", "mgr", "ing", "judr", "phdr", "paeddr", "mudr", "mddr", "rndr",
        "mvdr", "pharmdr", "thdr", "thlic", "doc", "prof", "llm",
    }
)  # fmt: skip
_GLUE_POINT = re.compile(r"(?<=\.)(?=[^\W\d_])")
_TITLE_SEPARATOR = re.compile(r"[\s,]+")


def _title_key(token: str) -> str:
    return token.casefold().replace(".", "")


def _unglue(piece: str) -> list[str]:
    for m in _GLUE_POINT.finditer(piece):
        if _title_key(piece[: m.start()]) in _GLUED_HEADS:
            return [piece[: m.start()], *_unglue(piece[m.start() :])]
    return [piece]


def title_tokens(title: str) -> list[str]:
    """Return the single titles in *title*, multi-part ones joined by a space."""
    pieces = [p for raw in _TITLE_SEPARATOR.split(title) if raw for p in _unglue(raw)]
    keys = [_title_key(p) for p in pieces]
    tokens = []
    i = 0
    while i < len(pieces):
        n = next(
            (len(ph) for ph in _TITLE_PHRASES if tuple(keys[i : i + len(ph)]) == ph),
            1,
        )
        tokens.append(" ".join(pieces[i : i + n]))
        i += n
    return tokens


def is_post_nominal(token: str) -> bool:
    """Return whether the title *token* is written after the name."""
    return _title_key(token).replace(" ", "") in _POST_NOMINAL


def split_title(title: str) -> tuple[str, str]:
    """Split a single-column title into (before name, after name).

    The municipal lists put all titles in one column, in no reliable order
    or punctuation (``Ing. PhD.``, ``Mgr., Bc.``, ``PhDr., MBA,DBA``), so
    each title is classified on its own and keeps its relative order.
    Titles after the name are joined with ``, `` as is customary.
    """
    tokens = title_tokens(title)
    before = [t for t in tokens if not is_post_nominal(t)]
    after = [t for t in tokens if is_post_nominal(t)]
    return " ".join(before), ", ".join(after)


def parse_parties(
    text: str, separator: str, known: Iterable[str] = ()
) -> tuple[list[str], bool]:
    """Return (party names, independent) for a nomination column.

    Municipal lists separate coalition members with ``;``, regional lists
    with ``,``. A ``,`` inside a party name (``Zmena zdola, demokratická únia
    Slovenska``) is only kept where the joined name is in *known*.
    """
    parts = [clean(p) for p in text.split(separator)]
    parts = [p for p in parts if p]
    if separator == ",":
        parts = _rejoin(parts, frozenset(known))
    if len(parts) == 1 and parts[0].casefold() in _INDEPENDENT:
        return [], True
    for p in parts:
        if p.casefold() in _INDEPENDENT:
            raise CandidatesError(f"independent candidate with a party: {text!r}")
    return parts, False


def _rejoin(parts: list[str], known: frozenset[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(parts):
        # Longest known name starting here wins.
        for j in range(len(parts), i + 1, -1):
            if ", ".join(parts[i:j]) in known:
                out.append(", ".join(parts[i:j]))
                i = j
                break
        else:
            out.append(parts[i])
            i += 1
    return out


@dataclass
class Entry:
    """One row of a candidate list, before matching."""

    kind: str
    source: str
    """File and row, for error messages."""
    region: str
    """Okres name (municipal) or kraj name (regional) as written."""
    okres_code: str
    obec: str
    obvod: int | None
    number: int
    first_name: str
    surname: str
    title_before: str
    title_after: str
    age: int
    occupation: str
    parties: list[str]
    independent: bool
    residence: str


# Accepted header texts (whitespace collapsed, casefolded) per field; the
# party column header is long and only its start is compared.
_HEADERS = {
    "okres": ("okres",),
    "kraj": ("kraj",),
    "obec": ("obec",),
    "obvod": ("volebný obvod",),
    "number": ("poradové číslo kandidáta",),
    "first_name": ("meno",),
    "surname": ("priezvisko",),
    "title": ("titul",),
    "title_before": ("titul pred menom",),
    "title_after": ("titul za menom",),
    "age": ("vek",),
    "occupation": ("zamestnanie",),
    "parties": ("názov politickej strany",),
    "okres_code": ("kód okresu", "kod okresu"),
    "residence": ("obec trvalého pobytu kandidáta", "obec tp kandidáta"),
}
_PREFIX_HEADERS = frozenset({"parties"})
_FIELDS = {
    "starosta": ("okres", "obec", "number", "first_name", "surname", "title"),
    "oz": ("okres", "obec", "obvod", "number", "first_name", "surname", "title"),
    "predseda": ("kraj", "number", "first_name", "surname", "title_before"),
    "zsk": ("kraj", "obvod", "number", "first_name", "surname", "title_before"),
}
_COMMON = ("age", "occupation", "parties")
_EXTRA = {
    "starosta": ("okres_code",),
    "oz": ("okres_code",),
    "predseda": ("title_after", "residence"),
    "zsk": ("title_after", "residence"),
}


def _columns(kind: str, header: Sequence[str], path: Path) -> dict[str, int]:
    keys = [clean(h).casefold() for h in header]
    columns = {}
    for name in (*_FIELDS[kind], *_COMMON, *_EXTRA[kind]):
        accepted = _HEADERS[name]
        found = [
            i
            for i, key in enumerate(keys)
            if key in accepted or (name in _PREFIX_HEADERS and key.startswith(accepted))
        ]
        if len(found) != 1:
            raise CandidatesError(f"{path}: no single column {accepted[0]!r}")
        columns[name] = found[0]
    return columns


def read_list(kind: str, path: Path, known_parties: Iterable[str] = ()) -> list[Entry]:
    """Read one candidate list of *kind*."""
    header, rows = xlsx.find_header(
        xlsx.read_rows(path), "Kraj" if kind in ("predseda", "zsk") else "Okres"
    )
    col = _columns(kind, header, path)
    municipal = kind in MUNICIPAL
    known = frozenset(known_parties)
    entries = []
    for line, row in enumerate(rows, 1):
        cells = row + [""] * (len(header) - len(row))

        def get(name: str, cells: list[str] = cells) -> str:
            return clean(cells[col[name]])

        source = f"{path.name}: data row {line}"
        try:
            if municipal:
                before, after = split_title(get("title"))
            else:
                before, after = get("title_before"), get("title_after")
            parties, independent = parse_parties(
                get("parties"), ";" if municipal else ",", known
            )
            entries.append(
                Entry(
                    kind=kind,
                    source=source,
                    region=get("okres" if municipal else "kraj"),
                    okres_code=get("okres_code") if municipal else "",
                    obec=get("obec") if municipal else "",
                    obvod=int(get("obvod")) if "obvod" in col else None,
                    number=int(get("number")),
                    first_name=get("first_name"),
                    surname=get("surname"),
                    title_before=before,
                    title_after=after,
                    age=int(get("age")),
                    occupation=get("occupation"),
                    parties=parties,
                    independent=independent,
                    residence="" if municipal else get("residence"),
                )
            )
        except (ValueError, CandidatesError) as e:
            raise CandidatesError(f"{source}: {e}") from e
    return entries


@dataclass
class Candidacy:
    """One candidate on one ballot, matched to codes."""

    contest: str
    kind: str
    area: str
    """Obec code (municipal contests) or kraj code (regional ones)."""
    obvod: int | None
    entry: Entry
    obec: str
    """Contest obec (municipal) or residence obec (regional)."""
    person: str = ""

    @property
    def id(self) -> str:
        """Return the candidacy id, ``<contest>#<ballot number>``."""
        return f"{self.contest}#{self.entry.number}"

    @property
    def body(self) -> str:
        """Return the elected body; one person stands at most once per body."""
        return f"{self.kind}:{self.area}"

    @property
    def sort_key(self) -> tuple[int, str, int, int]:
        """Return the order of candidacies in the output."""
        return (KINDS.index(self.kind), self.area, self.obvod or 0, self.entry.number)


@dataclass
class Person:
    """Candidacies taken to belong to one person."""

    id: str
    obec: str
    candidacies: list[str]


@dataclass
class Result:
    """Everything ``candidates.json`` holds, plus statistics for the report."""

    admin: Admin
    candidacies: list[Candidacy]
    persons: list[Person]
    residence_by: Counter[str]
    """How the residence obce of regional candidates were matched."""
    unmerged: int
    """Candidacies left unmerged because their person key repeats in a body."""
    incumbency: incumbents.Incumbency


def build(
    lists: dict[str, Path],
    gpkg: Path,
    overrides: Overrides,
    results: Mapping[str, Path],
    election: dt.date,
) -> Result:
    """Read the four lists and match them against ZBGIS; see the module doc.

    *results* are the files of :data:`incumbents.INPUTS`; *election* is the
    2026 election day, against which the ages of office holders are checked.
    """
    admin = load_admin(gpkg)
    entries: list[Entry] = []
    for kind in MUNICIPAL:
        with progress.stage(f"reading {lists[kind].name}"):
            entries += read_list(kind, lists[kind])
    known = {p for e in entries for p in e.parties if "," in p}
    for kind in KINDS[2:]:
        with progress.stage(f"reading {lists[kind].name}"):
            entries += read_list(kind, lists[kind], known)
    with progress.stage("matching municipalities and residences"):
        candidacies, residence_by = match(entries, admin, overrides)
        check_numbers(candidacies)
    with progress.stage("merging candidacies into persons"):
        persons, unmerged = merge_persons(candidacies, admin, overrides)
    with progress.stage("finding the current office holders"):
        holders = incumbents.load(results, admin)
        incumbency = incumbents.match(holders, candidacies, persons, admin, election)
    return Result(admin, candidacies, persons, residence_by, unmerged, incumbency)


def match(
    entries: Sequence[Entry], admin: Admin, overrides: Overrides
) -> tuple[list[Candidacy], Counter[str]]:
    """Assign obec and kraj codes to *entries*; fail listing every mismatch.

    Returns the candidacies in output order and how many residences were
    matched by name, by a municipal candidacy of the same person, or by
    override.
    """
    unmatched: set[str] = set()
    candidacies = []
    municipal = municipal_index(admin)
    kraje = {name_key(n): c for c, n in admin.kraje.items()}
    used_obec: set[str] = set()
    pending = []
    for e in entries:
        if e.kind in MUNICIPAL:
            override = overrides.obec.get(f"{e.region}/{e.obec}")
            if override is not None:
                used_obec.add(f"{e.region}/{e.obec}")
                area = _known(admin, override, f"overrides obec {e.region}/{e.obec}")
            else:
                area = _match_obec(e, admin, municipal)
            if area is None:
                unmatched.add(f"obec {e.obec!r} in okres {e.region!r} ({e.okres_code})")
                continue
        else:
            region = name_key(e.region.removesuffix("samosprávny kraj"))
            area = kraje.get(region)
            if area is None:
                unmatched.add(f"kraj {e.region!r}")
                continue
        contest = f"{e.kind}:{area}" + (f"/{e.obvod}" if e.obvod is not None else "")
        c = Candidacy(contest, e.kind, area, e.obvod, e, area)
        candidacies.append(c)
        if e.kind not in MUNICIPAL:
            pending.append(c)

    residence_by = _match_residences(pending, candidacies, admin, overrides, unmatched)
    stale = sorted(set(overrides.obec) - used_obec)
    if stale:
        unmatched.add(f"unused override obec {stale[0]!r}")
    if unmatched:
        raise CandidatesError(
            f"{len(unmatched)} unmatched (add them to overrides.toml):\n  "
            + "\n  ".join(sorted(unmatched))
        )
    candidacies.sort(key=lambda c: c.sort_key)
    return candidacies, residence_by


def municipal_index(admin: Admin) -> dict[tuple[str, str], str]:
    """Return (okres code, :func:`name_key` of the name) → obec code."""
    index = {(city.okres, name_key(city.name)): city.code for city in CITIES}
    for obec in admin.obce.values():
        if obec.okres is not None:
            key = (obec.okres, name_key(obec.name))
            if key in index:
                raise CandidatesError(
                    f"two obce named {obec.name!r} in okres {obec.okres}"
                )
            index[key] = obec.code
    return index


def _match_obec(
    e: Entry, admin: Admin, index: dict[tuple[str, str], str]
) -> str | None:
    """Return the obec of a municipal row, matched by name within its okres.

    The okres code column picks the okres; its name is compared as well so
    that a shifted column cannot go unnoticed.
    """
    city = next((c for c in CITIES if c.okres == e.okres_code), None)
    okres_name = city.name if city else admin.okresy.get(e.okres_code, ("",))[0]
    if name_key(okres_name) != name_key(e.region):
        return None
    return index.get((e.okres_code, name_key(e.obec)))


def _known(admin: Admin, code: str, where: str) -> str:
    if code not in admin.obce:
        raise CandidatesError(f"{where}: no obec {code}")
    return code


def _match_residences(
    pending: Sequence[Candidacy],
    candidacies: Sequence[Candidacy],
    admin: Admin,
    overrides: Overrides,
    unmatched: set[str],
) -> Counter[str]:
    """Set the residence obec of regional candidacies, matched within the kraj.

    Names repeat across okresy (three Selce in one kraj). An ambiguous name
    is settled by a municipal candidacy of the same person in one of the
    candidate obce, else by ``[residence]`` in ``overrides.toml``.
    """
    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for obec in admin.obce.values():
        by_name[(obec.kraj, name_key(obec.name))].append(obec.code)
    municipal = {
        (_merge_area(admin, c.obec), *_name_age(c.entry))
        for c in candidacies
        if c.kind in MUNICIPAL
    }
    residence_by: Counter[str] = Counter()
    used = set()
    for c in pending:
        override = overrides.residence.get(c.id)
        if override is not None:
            used.add(c.id)
            c.obec = _known(admin, override, f"overrides residence {c.id}")
            residence_by["override"] += 1
            continue
        options = by_name.get((c.area, name_key(c.entry.residence)), [])
        if len(options) > 1:
            options = [
                o
                for o in options
                if (_merge_area(admin, o), *_name_age(c.entry)) in municipal
            ]
            how = "municipal candidacy"
        else:
            how = "name"
        if len(options) != 1:
            unmatched.add(
                f"residence {c.entry.residence!r} of {c.id}"
                f" ({c.entry.first_name} {c.entry.surname})"
            )
            continue
        c.obec = options[0]
        residence_by[how] += 1
    for cid in sorted(set(overrides.residence) - used):
        unmatched.add(f"unused override residence {cid!r}")
    return residence_by


def _merge_area(admin: Admin, code: str) -> str:
    """Return the obec persons are merged on: a district counts as its city."""
    return admin.obce[code].city or code


def _name_age(e: Entry) -> tuple[str, str, int]:
    return person_name_key(e.first_name), person_name_key(e.surname), e.age


def check_numbers(candidacies: Sequence[Candidacy]) -> None:
    """Check ballot numbers unique per contest and obvody numbered from 1."""
    errors = []
    seen: dict[str, str] = {}
    obvody: dict[str, set[int]] = defaultdict(set)
    for c in candidacies:
        if c.id in seen:
            errors.append(f"{c.id}: {c.entry.source} repeats {seen[c.id]}")
        seen[c.id] = c.entry.source
        if c.obvod is not None:
            obvody[c.body].add(c.obvod)
    for body, numbers in sorted(obvody.items()):
        if numbers != set(range(1, len(numbers) + 1)):
            errors.append(f"{body}: obvody {sorted(numbers)} are not 1..{len(numbers)}")
    if errors:
        raise CandidatesError("\n  ".join(["inconsistent numbering:", *errors]))


def merge_persons(
    candidacies: Sequence[Candidacy], admin: Admin, overrides: Overrides
) -> tuple[list[Person], int]:
    """Group *candidacies* into persons and set their ``person`` ids.

    Candidacies merge when obec (a district counts as its city), first name,
    surname and age agree. Where such a key occurs twice within one elected
    body (two namesakes on one council ballot or in two obvody of one
    council) it cannot tell people apart, so none of its candidacies merge.
    ``[[person.split]]`` then detaches candidacies into a person of their
    own and ``[[person.merge]]`` joins the persons of the listed ones.

    Returns the persons sorted by id and the number of candidacies kept
    apart by the same-body rule.
    """
    by_id = {c.id: c for c in candidacies}
    for group in (*overrides.person_split, *overrides.person_merge):
        for cid in group:
            if cid not in by_id:
                raise CandidatesError(f"overrides.toml: no candidacy {cid!r}")

    keys: dict[str, PersonKey] = {
        c.id: (_merge_area(admin, c.obec), *_name_age(c.entry)) for c in candidacies
    }
    by_key: dict[PersonKey, list[Candidacy]] = defaultdict(list)
    for c in candidacies:
        by_key[keys[c.id]].append(c)
    groups: list[set[str]] = []
    unmerged = 0
    for same in by_key.values():
        if len({c.body for c in same}) == len(same):
            groups.append({c.id for c in same})
        else:
            groups += [{c.id} for c in same]
            unmerged += len(same)
    _apply_overrides(groups, overrides)
    return _persons(groups, by_id, keys), unmerged


def _persons(
    groups: Iterable[set[str]],
    by_id: dict[str, Candidacy],
    keys: Mapping[str, PersonKey],
) -> list[Person]:
    """Return a person per non-empty group, sorted by id; set ``person``.

    *keys* holds the person key of every candidacy.
    """
    members = [sorted(g, key=lambda cid: by_id[cid].sort_key) for g in groups if g]
    identity = Counter(keys[m[0]] for m in members)
    persons = []
    for m in members:
        first = by_id[m[0]]
        k = keys[first.id]
        # A key shared by several persons gets its first candidacy appended;
        # either way the id survives unrelated changes to the lists.
        pid = person_id(k, first.id if identity[k] > 1 else None)
        persons.append(Person(pid, k[0], m))
        for cid in m:
            by_id[cid].person = pid
    persons.sort(key=lambda p: p.id)
    for a, b in zip(persons, persons[1:]):
        if a.id == b.id:
            raise CandidatesError(
                f"person id collision {a.id}: {a.candidacies[0]}, {b.candidacies[0]}"
            )
    return persons


def _apply_overrides(groups: list[set[str]], overrides: Overrides) -> None:
    """Apply ``[[person.split]]``, then ``[[person.merge]]``, to *groups*.

    Groups emptied by either are left in place for the caller to drop.
    """
    owner = {cid: i for i, g in enumerate(groups) for cid in g}
    for split in overrides.person_split:
        for cid in split:
            groups[owner[cid]].discard(cid)
        groups.append(set(split))
        owner.update(dict.fromkeys(split, len(groups) - 1))
    for merge in overrides.person_merge:
        target = owner[merge[0]]
        for cid in merge[1:]:
            source = owner[cid]
            if source != target:
                groups[target] |= groups[source]
                owner.update(dict.fromkeys(groups[source], target))
                groups[source] = set()


def person_id(key: PersonKey, candidacy: str | None) -> str:
    """Return the short stable hash that identifies a person."""
    text = "\x1f".join(map(str, (*key, candidacy or "")))
    return hashlib.sha256(text.encode()).hexdigest()[:PERSON_ID_LENGTH]


def _contest_json(c: Candidacy, result: Result) -> dict[str, object]:
    contest: dict[str, object] = {"id": c.contest, "kind": c.kind, "area": c.area}
    if c.obvod is not None:
        contest["obvod"] = c.obvod
    # Only mayor and president contests have one holder to name.
    held = result.incumbency.contests.get(c.contest)
    if held is not None:
        contest["incumbent"] = incumbents.contest_json(*held)
    seats_2022 = result.incumbency.holders.seats_2022.get(f"oz:{c.area}")
    if c.kind == "oz" and seats_2022:
        contest["seats_2022"] = seats_2022
    return contest


def to_json(result: Result) -> dict[str, list[dict[str, object]]]:
    """Return the content of ``candidates.json``; see the module doc."""
    admin = result.admin
    obce = []
    for o in sorted(admin.obce.values(), key=lambda o: o.code):
        item: dict[str, object] = {"code": o.code, "name": o.name}
        if o.okres is not None:
            item["okres"] = o.okres
        item["kraj"] = o.kraj
        if o.city is not None:
            item["city"] = o.city
        obce.append(item)
    contests: dict[str, dict[str, object]] = {}
    candidacies = []
    for c in result.candidacies:
        if c.contest not in contests:
            contests[c.contest] = _contest_json(c, result)
        e = c.entry
        item = {
            "id": c.id,
            "contest": c.contest,
            "number": e.number,
            "person": c.person,
            "title_before": e.title_before,
            "title_after": e.title_after,
            "first_name": e.first_name,
            "surname": e.surname,
            "age": e.age,
            "occupation": e.occupation,
            "parties": e.parties,
            "independent": e.independent,
        }
        if c.kind not in MUNICIPAL:
            item["residence"] = c.obec
        roles = result.incumbency.roles.get(c.person)
        if roles:
            item["incumbent"] = incumbents.roles_json(roles)
        candidacies.append(item)
    return {
        "kraje": [{"code": c, "name": n} for c, n in sorted(admin.kraje.items())],
        "okresy": [
            {"code": c, "name": n, "kraj": k}
            for c, (n, k) in sorted(admin.okresy.items())
        ],
        "obce": obce,
        "contests": list(contests.values()),
        "candidacies": candidacies,
        "persons": [
            {"id": p.id, "obec": p.obec, "candidacies": p.candidacies}
            for p in result.persons
        ],
    }


def write(result: Result, path: Path) -> int:
    """Write ``candidates.json`` to *path* atomically; return its size."""
    data = output.to_json(to_json(result)) + b"\n"
    output.write_file(path, data)
    return len(data)


def report(result: Result) -> Iterator[str]:
    """Yield the human-readable summary lines of *result*."""
    cs = result.candidacies
    kinds = Counter(c.kind for c in cs)
    yield f"candidacies {len(cs):,}: " + ", ".join(f"{k} {kinds[k]:,}" for k in KINDS)
    obvody: dict[str, Counter[str]] = {k: Counter() for k in ("oz", "zsk")}
    for contest in {(c.kind, c.area, c.contest) for c in cs if c.obvod is not None}:
        obvody[contest[0]][contest[1]] += 1
    multi = sum(1 for n in obvody["oz"].values() if n > 1)
    yield (
        f"municipal obvody {obvody['oz'].total():,} in {len(obvody['oz']):,} obce,"
        f" {multi} with more than one; VÚC obvody {obvody['zsk'].total()}"
    )
    yield "residences matched: " + ", ".join(
        f"by {how} {n:,}" for how, n in sorted(result.residence_by.items())
    )
    persons = result.persons
    multiple = [p for p in persons if len(p.candidacies) > 1]
    yield (
        f"persons {len(persons):,}, {len(multiple):,} with 2+ candidacies;"
        f" {result.unmerged} candidacies kept apart (same key within one body)"
    )
    by_id = {c.id: c for c in cs}
    combos = Counter(
        "+".join(sorted((by_id[cid].kind for cid in p.candidacies), key=KINDS.index))
        for p in multiple
    )
    for combo, n in combos.most_common():
        yield f"  {combo:<26} {n:>6,}"
    yield from incumbents.report(result.incumbency)
