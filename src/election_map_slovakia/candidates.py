"""Turn an election's candidate lists into contests, candidacies and persons.

The lists come in the format ``elections.toml`` names
(:mod:`election_map_slovakia.lists` reads every one): the four lists MV SR
publishes before the regular elections (mayors, municipal councils,
regional presidents, regional councils; :func:`read_lists`), ŠÚ SR's
packages of the definitive results, which list every candidate too
(:func:`election_map_slovakia.statoffice.read_candidates`, and a
by-election's), ŠÚ SR's candidate tables of the country-wide elections, or
lists curated by hand. MV SR's lists and ŠÚ SR's of 2022 name
municipalities but give no codes, so every municipality is matched by name
within its okres to a ZBGIS obec (the 6-digit ŠÚ SR code); the cities of
Bratislava and Košice, which ZBGIS has only as districts, get the
synthetic codes ``BA`` and ``KE``. The others give the codes of their
contests' areas (:attr:`Entry.area`). Persons are not identified in the
lists; candidacies are merged into persons by obec, name and age.
ŠÚ SR's by-election packages of 2019–2022 give neither age, title nor
occupation (:attr:`Entry.age` None), and of a council only the elected.

Output, ``data/build/<election day>/candidates.json`` (UTF-8, compact, sorted; codes are
strings; keys in parentheses are omitted where they do not apply)::

    kraje:       [{code, name}]                         code "1".."8" (ZBGIS IDN2)
    okresy:      [{code, name, kraj}]                   code "101".."813" (IDN3)
    obce:        [{code, name, (okres), kraj, (city),   city: BA/KE for districts
                   (zsk), (council_seats), (past)}]
    contests:    [{id, kind, area, (obvod), (seats),
                   (day), (question), (subjects),
                   (threshold), (coalition_thresholds),
                   (preferences), (quota), (party),
                   (elected_only), (uncontested), (vote),
                   (incumbent), (seats_2022), (past)}]  id "oz:528595/2"
    candidacies: [{id, contest, number, person, title_before, title_after,
                   first_name, surname, age, occupation, parties, independent,
                   (residence), (residence_name), (withdrawn), (incumbent)}]
                                                        id "oz:528595/2#7"
    persons:     [{id, obec, candidacies}]

Contests and their ids are those of :mod:`election_map_slovakia.contests`:
``kind`` is ``starosta``, ``oz``, ``predseda``, ``zsk``, ``prezident``,
``referendum``, ``nrsr`` or ``ep``; ``area`` is an obec code for the first
two, a kraj code for the next two and ``SK`` for the country-wide ones;
``obvod`` is what follows ``/`` in the id: a council's obvod, a
presidential round, a referendum question, a party's ballot number. A
contest is listed where it has candidacies, and where the lists or the
election's configuration name it without: a referendum's questions, a
party-list election's party contest and each party's list, a contest
called but uncontested (below). ``parties`` is
the list of nominating parties (a coalition has several), empty for an
independent candidate; a party list's candidates have its party, a
president's none. ``residence`` is the obec of residence of regional and
country-wide candidates; a country-wide candidate's is matched by name
among all obce, and where no one obec has that name, ``residence_name`` is
the name as written instead. ``age`` is null and ``occupation`` and the
titles empty where the lists do not give them. A person's ``obec`` is the
obec its candidacies were merged on, with Bratislava and Košice districts
counted as their city; empty for a country-wide candidate of unknown
residence.

What ŠÚ SR's packages say beside the candidates (:class:`Lists`), the MV SR
lists do not: a council or regional council contest's ``seats``, the
councillors elected in its obvod; a candidacy's ``withdrawn``, true for a
candidate who withdrew yet stayed on the ballot; an obec's ``zsk``, the
number of its regional obvod within its kraj. A council contest's
``elected_only`` is true where its candidacies are the councillors elected
only, the others not published (a by-election's package of 2019–2022
without a curated list in its place: :mod:`election_map_slovakia.lists`);
their ballot numbers are then the order they were elected in. An obec's
``council_seats``, of a regular election, are its council's seats in all
as ŠÚ SR's territorial division gives them (also where they were not all
filled, or the council was held nowhere).

A by-election's contests say which vote each is (``vote``,
:func:`election_map_slovakia.lists.read_by_election`): ``"new"``, a new
election (nové voľby) of the whole office, a mayor or a council elected
anew, whose council obvody are its own; ``"by"``, a by-election proper
(doplňujúce voľby) of seats of the council its term elected, in that
council's obvody.

A contest called but held nowhere, no candidate having registered for it,
is ``uncontested``: ``{source, title}``, the URL of what says so and what
in it (ŠÚ SR's territorial division, whose ``Typ volieb`` of an obec of a
regular election names what is held there and of a by-election marks
what is held nowhere, ``Nekonajú sa``; the municipality's decision on its
council obvody, which lists one that the candidate lists lack; the
Speaker's decision calling a by-election; :func:`election_map_slovakia.lists.read`).
It has no candidacies, and its ``seats`` where known.

What the election's configuration says of its contests
(:func:`election_map_slovakia.lists.read`): a presidential round 2's
``day`` (ISO); a referendum question's wording, ``question``; a party
contest's ``seats`` (of the body), ``threshold`` (% of the valid votes a
party needs), ``coalition_thresholds`` (``[[parties, %]]``, ascending, where
coalitions need more), ``preferences`` (the candidates a voter may circle
on the chosen list) and ``quota`` (% of its party's votes a candidate's
preference votes must reach to move up the list). A party contest's
``subjects`` are its candidates, the parties on the ballot,
``[{number, party, (candidates), (withdrawn)}]``: ballot number, party name
(a key of ``config/parties.toml``), the size of its list; each has a list
contest, ``<kind>:SK/<number>``, with ``party`` and its persons as
candidacies, numbered by their position on the list.

Office holders before the election, where ``elections.toml`` names where
they come from (``incumbents``; see :mod:`election_map_slovakia.incumbents`): a
candidacy's ``incumbent`` lists every role its person holds at the
election, in any body, as ``[{body, since, result}]`` (``body`` is a contest
id without obvod, such as ``starosta:500011`` or ``zsk:4``; ``since`` the ISO
day the role was won); a mayor or president contest's ``incumbent`` is
``{name, since, candidacy, result}``, the holder's name with titles, and its
candidacy in that contest or null. ``result`` is how the role was won,
``{votes, valid, voters, eligible, (obvod)}`` (:func:`incumbents.result_json`).
Both are omitted when empty or vacant. A council contest's ``seats_2022`` is
the number of councillors the whole council of its area had elected in the
regular election of 2022 (by-elections leave it unchanged).

``past`` is the last election of the whole body a contest elects, with the
turnout in the body's whole area, ``{election, day, eligible, voters}``
(:func:`incumbents.past_json`; for a council all its obvody together): for
mayor and council contests the latest by-election that elected the mayor or
the whole council, else the regular election of 2022; for president
contests the regional election of 2022. Regional council contests have
none, their 2026 obvody being unknown here; an obec's ``past`` is the
regional election of 2022 in it, for ``build`` to sum over them. An
election without office holders has none of these.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

from election_map_slovakia import contests, incumbents, output, progress, xlsx
from election_map_slovakia.config import Incumbents, Overrides
from election_map_slovakia.gpkg import GeoPackage

if TYPE_CHECKING:
    import datetime as dt

_ORDER = {kind: i for i, kind in enumerate(contests.KINDS)}
"""The order of contests and candidacies in the output, by kind first."""
_CONTEST_FIELDS = (
    "seats",
    "day",
    "question",
    "subjects",
    "threshold",
    "coalition_thresholds",
    "preferences",
    "quota",
    "party",
    "elected_only",
    "uncontested",
    "vote",
)
"""The fields of a contest besides its candidacies, in output order (the
module doc); :attr:`Lists.contests` holds them but ``subjects``."""
OUTPUT_FILE = "candidates.json"
PERSON_ID_LENGTH = 12
# Merge obec, normalized first name, normalized surname, age (None where
# the lists do not give it).
PersonKey = tuple[str, str, str, int | None]
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
# The phrases by their first key, each key's in the order above: a token
# is looked up among those it may start only.
_PHRASES_BY_HEAD = {
    head: tuple(ph for ph in _TITLE_PHRASES if ph[0] == head)
    for head in {ph[0] for ph in _TITLE_PHRASES}
}
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
            (
                len(ph)
                for ph in _PHRASES_BY_HEAD.get(keys[i], ())
                if tuple(keys[i : i + len(ph)]) == ph
            ),
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


def _is_title(token: str) -> bool:
    """Return whether a word of a name written with its titles is a title.

    Names have no dots; a title written without one (``Bc``) is one of the
    keys the titles are classified by.
    """
    key = _title_key(token).replace(" ", "")
    return "." in token or key in _GLUED_HEADS or key in _POST_NOMINAL


def split_name(text: str) -> tuple[str, str, str, str]:
    """Split a name written with its titles in one column.

    Returns (title before, first name, surname, title after). ŠÚ SR's
    elected councillors of 2018–2022 (``Meno a priezvisko``) have the titles
    anywhere: ``Ing. Anton Bajzík``, ``Ivana Káňavová, Bc``, ``Bc.Norbert
    Jurčaga``, ``Horňák Ján Ing.``. Of the other words the first is taken
    for the first name and the rest for the surname, as a surname of several
    words (``Plačková Uhrinová``) is common and a first name of several
    rare; a name written surname first is split wrongly, which only a
    curated list puts right (:func:`name_words` matches it either way). A
    name of one word glued of two (``AlžbetaHudačová``, 2018) is split
    where a capital follows a small letter.
    """
    tokens = title_tokens(text)
    words = [t for t in tokens if not _is_title(t)]
    if len(words) == 1:
        words = _split_glued_name(words[0])
    if len(words) < 2:  # noqa: PLR2004 - a first name and a surname
        raise CandidatesError(f"no first name and surname in {text!r}")
    before, after = split_title(" ".join(t for t in tokens if _is_title(t)))
    return before, words[0], " ".join(words[1:]), after


def _split_glued_name(word: str) -> list[str]:
    """Return *word* split where a capital follows a small letter."""
    cuts = [
        i for i in range(1, len(word)) if word[i - 1].islower() and word[i].isupper()
    ]
    return [word[i:j] for i, j in pairwise([0, *cuts, len(word)])]


def name_words(text: str) -> tuple[str, ...]:
    """Return the name *text* as names are matched across lists.

    Its words without the titles (as :func:`split_name` tells them), each as
    :func:`search_key` has it, sorted: case, diacritics and the order of
    first name and surname do not matter (``Horňák Ján Ing.`` is ``Ján
    Horňák``).
    """
    words = [t for t in title_tokens(text) if not _is_title(t)]
    return tuple(sorted(search_key(" ".join(words)).split()))


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
    """What follows ``/`` in its contest id: a council's obvod, a
    presidential round, a party's ballot number (its list)."""
    number: int
    first_name: str
    surname: str
    title_before: str
    title_after: str
    age: int | None
    """None where the lists do not give it, and then *occupation* and the
    titles are empty."""
    occupation: str
    parties: list[str]
    independent: bool
    residence: str
    area: str = ""
    """Its contest's area code where the list gives it (an obec, ``BA``,
    ``KE``, a kraj or ``SK``), else empty: matched by *region* and *obec*."""


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
    municipal = kind in contests.MUNICIPAL
    header, rows = xlsx.find_header(
        xlsx.read_rows(path), "Okres" if municipal else "Kraj"
    )
    columns = _columns(kind, header, path)
    known = frozenset(known_parties)
    entries = []
    for line, row in enumerate(rows, 1):
        # Trailing empty cells may be missing from a row.
        cell = {
            name: clean(row[i]) if i < len(row) else "" for name, i in columns.items()
        }
        source = f"{path.name}: data row {line}"
        try:
            if municipal:
                before, after = split_title(cell["title"])
            else:
                before, after = cell["title_before"], cell["title_after"]
            parties, independent = parse_parties(
                cell["parties"], ";" if municipal else ",", known
            )
            entries.append(
                Entry(
                    kind=kind,
                    source=source,
                    region=cell["okres" if municipal else "kraj"],
                    okres_code=cell.get("okres_code", ""),
                    obec=cell.get("obec", ""),
                    obvod=int(cell["obvod"]) if "obvod" in cell else None,
                    number=int(cell["number"]),
                    first_name=cell["first_name"],
                    surname=cell["surname"],
                    title_before=before,
                    title_after=after,
                    age=int(cell["age"]),
                    occupation=cell["occupation"],
                    parties=parties,
                    independent=independent,
                    residence=cell.get("residence", ""),
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
    """Obec code (municipal contests), kraj code (regional ones) or ``SK``."""
    obvod: int | None
    entry: Entry
    obec: str
    """Contest obec (municipal) or residence obec (regional, country-wide;
    empty where a country-wide candidate's is not known)."""
    person: str = ""

    @property
    def id(self) -> str:
        """Return the candidacy id, ``<contest>#<ballot number>``."""
        return f"{self.contest}#{self.entry.number}"

    @property
    def body(self) -> str:
        """Return the elected body; one person stands at most once per body."""
        return contests.body(self.contest)

    @property
    def sort_key(self) -> tuple[int, str, int, int]:
        """Return the order of candidacies in the output."""
        return (_ORDER[self.kind], self.area, self.obvod or 0, self.entry.number)


@dataclass
class Person:
    """Candidacies taken to belong to one person."""

    id: str
    obec: str
    candidacies: list[str]


@dataclass(frozen=True)
class Subject:
    """A ballot subject of a party-list election: a party or coalition."""

    number: int
    party: str
    """Its name as written, a key of ``config/parties.toml``."""
    candidates: int | None = None
    """The size of its list where the lists state it, which its list
    contest's candidacies must match."""
    withdrawn: bool = False
    """Whether it withdrew, yet stayed on the ballot."""


@dataclass
class Lists:
    """An election's candidate lists, read, and what they say beside them."""

    entries: list[Entry]
    """Every row, in list order."""
    withdrawn: set[str] = field(default_factory=set)
    """Candidacy ids of the candidates who withdrew, where the lists say."""
    seats: dict[str, int] = field(default_factory=dict)
    """Council and regional council contest id → seats, where they say."""
    zsk: dict[str, int] = field(default_factory=dict)
    """Obec → its regional obvod's number within its kraj, where they say."""
    council_seats: dict[str, int] = field(default_factory=dict)
    """Obec → its council's seats in all, of a regular election's
    territorial division (``council_seats`` of the output)."""
    new_councils: set[str] | None = None
    """Of a by-election: the obce whose council it elects anew (``vote``
    ``"new"``), the others' seats of their term's council (``"by"``);
    None of any other election."""
    subjects: dict[str, list[Subject]] = field(default_factory=dict)
    """Party contest id → its ballot subjects, by number."""
    contests: dict[str, dict[str, object]] = field(default_factory=dict)
    """Contest id → its fields beside its candidacies but ``subjects``
    (:data:`_CONTEST_FIELDS`), for every contest the lists or the election's
    configuration name, whether it has candidacies or not."""
    partial: bool = False
    """Whether the lists are of some areas only (a by-election): a council's
    obvody need not all have candidates."""
    not_held: dict[str, Uncontested] = field(default_factory=dict)
    """Contest id → what says it was called but held nowhere, no candidate
    having registered (:func:`election_map_slovakia.lists.read` makes them
    ``uncontested`` contests)."""
    unplaced: list[str] = field(default_factory=list)
    """Such contests that cannot be named, for the report: a council's
    seats called in one of its several obvody, not saying which."""


@dataclass(frozen=True)
class Uncontested:
    """What says that a contest was called but no candidate registered.

    A document (``source``, its URL) or, where the inputs say it, a part of
    the candidate inputs (``part``, a key of the election's ``candidates``),
    whose URL :func:`election_map_slovakia.lists.read` takes; ``title``
    names what in it says so.
    """

    title: str
    source: str = ""
    part: str = ""


NEW, BY = "new", "by"
"""A by-election's contest's ``vote``: a new election of the whole office,
a by-election proper of seats of its term's council (the module doc)."""


def new_councils(contests: Iterable[Mapping[str, Any]]) -> set[str]:
    """Return the obce whose council contests of *contests* elect it anew (``vote`` ``"new"``)."""
    return {
        str(c["area"]) for c in contests if c["kind"] == "oz" and c.get("vote") == NEW
    }


NOT_HELD_TYPES = {
    "nekonajú sa": ("starosta", "oz"),
    "len zastupiteľstvo": ("starosta",),
    "len starosta": ("oz",),
}
"""ŠÚ SR's kind of election of an obec in a regular election (``Typ
volieb`` of the territorial division, case aside) → its contests called
but held nowhere for want of candidates."""


def not_held(
    lists: Lists,
    obec: str,
    kinds: Iterable[str],
    obvody: int,
    seats: int | None,
    why: Uncontested,
) -> None:
    """Add to *lists* the contests of *kinds* of *obec* held nowhere, *why*.

    A council's (``oz``) in each of its *obvody*, with its *seats* where it
    has one obvod (per obvod they are not known); a mayor's (``starosta``).
    """
    for kind in kinds:
        if kind == "starosta":
            lists.not_held[f"starosta:{obec}"] = why
            continue
        for n in range(1, obvody + 1):
            lists.not_held[f"oz:{obec}/{n}"] = why
        if obvody == 1 and seats:
            lists.seats[f"oz:{obec}/1"] = seats


@dataclass
class Result:
    """Everything ``candidates.json`` holds, plus statistics for the report."""

    admin: Admin
    lists: Lists
    candidacies: list[Candidacy]
    persons: list[Person]
    residence_by: Counter[str]
    """How the residence obce of regional and country-wide candidates were
    matched."""
    unmerged: int
    """Candidacies left unmerged because their person key repeats in a body."""
    incumbency: incumbents.Incumbency | None
    """None for an election whose office holders before are not known."""


def read_lists(paths: Mapping[str, Path]) -> Lists:
    """Read the four MV SR lists, *paths* by contest kind (format ``mvsr``)."""
    entries: list[Entry] = []
    for kind in contests.MUNICIPAL:
        with progress.stage(f"reading {paths[kind].name}"):
            entries += read_list(kind, paths[kind])
    known = {p for e in entries for p in e.parties if "," in p}
    for kind in contests.REGIONAL:
        with progress.stage(f"reading {paths[kind].name}"):
            entries += read_list(kind, paths[kind], known)
    return Lists(entries)


def build(
    lists: Lists,
    gpkg: Path,
    overrides: Overrides,
    holders: tuple[Incumbents, Mapping[str, Path]] | None,
    election: dt.date,
) -> Result:
    """Match the *lists* against ZBGIS and merge persons; see the module doc.

    *gpkg* is ZBGIS level 0, whose attribute tables name the municipalities.
    *holders* is where the office holders before the election come from,
    with the files of its inputs, or None where they are not known;
    *election* is the election day, against which their ages are checked.
    """
    admin = load_admin(gpkg)
    with progress.stage("matching municipalities and residences"):
        candidacies, residence_by = match(lists.entries, admin, overrides)
        check_numbers(candidacies, whole=not lists.partial)
        _check_stated(lists, candidacies, admin)
    with progress.stage("merging candidacies into persons"):
        persons, unmerged = merge_persons(candidacies, admin, overrides)
    incumbency = None
    if holders is not None:
        with progress.stage("finding the current office holders"):
            loaded = incumbents.load(*holders, admin)
            incumbency = incumbents.match(loaded, candidacies, persons, admin, election)
    return Result(
        admin, lists, candidacies, persons, residence_by, unmerged, incumbency
    )


def _check_stated(lists: Lists, candidacies: Sequence[Candidacy], admin: Admin) -> None:
    """Check that what *lists* say beside the rows names their contests.

    A contest held nowhere (:attr:`Lists.not_held`) has no candidacies and
    is of an obec (or Bratislava, Košice) there is.
    """
    ids = {c.id for c in candidacies}
    held = {c.contest for c in candidacies}
    councils = {c.contest for c in candidacies if _is_council(c.kind)}
    councils |= {c for c in lists.not_held if _is_council(contests.parse(c).kind.name)}
    errors = [f"withdrawn: no candidacy {cid}" for cid in sorted(lists.withdrawn - ids)]
    errors += [
        f"seats: no council contest {c}" for c in sorted(lists.seats.keys() - councils)
    ]
    errors += [
        f"{c}: held nowhere ({lists.not_held[c].title}), yet it has candidates"
        for c in sorted(lists.not_held.keys() & held)
    ]
    errors += [
        f"{c}: held nowhere, of no obec there is"
        for c in sorted(lists.not_held)
        if contests.parse(c).area not in admin.obce.keys() | set(CITY_CODES)
    ]
    errors += [
        f"regional obvod: no obec {o}"
        for o in sorted(lists.zsk.keys() - admin.obce.keys())
    ]
    errors += [
        f"{cid}: not a contest id"
        for cid in sorted({*lists.contests, *lists.subjects})
        if not contests.CONTEST_ID.fullmatch(cid)
    ]
    errors += _list_problems(lists, candidacies)
    if errors:
        raise CandidatesError(
            "\n  ".join(["the lists do not fit their rows:", *errors])
        )


def _is_council(kind: str) -> bool:
    """Return whether contests of *kind* elect a council by obvod."""
    return contests.KINDS[kind].sub == "obvod"


def _list_problems(lists: Lists, candidacies: Sequence[Candidacy]) -> list[str]:
    """Return how the party lists' candidacies do not fit their subjects."""
    sizes = Counter(c.contest for c in candidacies)
    numbers = {
        f"{party}/{s.number}": s for party, ss in lists.subjects.items() for s in ss
    }
    errors = [
        f"{c}: no ballot subject {c.partition('/')[2]}"
        for c in sorted(sizes)
        if contests.parse(c).is_list and c not in numbers
    ]
    errors += [
        f"{c}: {sizes[c]} candidates, the list states {s.candidates}"
        for c, s in sorted(numbers.items())
        if s.candidates is not None and s.candidates != sizes[c]
    ]
    return errors


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
        scope = contests.KINDS[e.kind].scope
        if e.area:
            area = _given_area(e, admin, scope)
            problem = f"{e.source}: no area {e.area!r} of a {e.kind} contest"
        elif scope == "obec":
            place = f"{e.region}/{e.obec}"
            override = overrides.obec.get(place)
            if override is not None:
                used_obec.add(place)
                area = _known(admin, override, f"overrides obec {place}")
            else:
                area = _match_obec(e, admin, municipal)
            problem = f"obec {e.obec!r} in okres {e.region!r} ({e.okres_code})"
        elif scope == "kraj":
            area = kraje.get(name_key(e.region.removesuffix("samosprávny kraj")))
            problem = f"kraj {e.region!r}"
        else:
            area = contests.COUNTRY
            problem = ""
        if area is None:
            unmatched.add(problem)
            continue
        contest = f"{e.kind}:{area}" + (f"/{e.obvod}" if e.obvod is not None else "")
        c = Candidacy(contest, e.kind, area, e.obvod, e, area)
        candidacies.append(c)
        if scope != "obec":
            pending.append(c)

    residence_by = _match_residences(pending, candidacies, admin, overrides, unmatched)
    for place in set(overrides.obec) - used_obec:
        unmatched.add(f"unused override obec {place!r}")
    if unmatched:
        raise CandidatesError(
            f"{len(unmatched)} unmatched (add them to overrides.toml):\n  "
            + "\n  ".join(sorted(unmatched))
        )
    candidacies.sort(key=lambda c: c.sort_key)
    return candidacies, residence_by


def _given_area(e: Entry, admin: Admin, scope: str) -> str | None:
    """Return the area code *e* gives if it is one of its contest's scope."""
    known = {"obec": admin.obce, "kraj": admin.kraje}.get(scope, {contests.COUNTRY})
    return e.area if e.area in known else None


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
    """Set the residence obec of regional and country-wide candidacies.

    A regional candidate's is matched within the kraj. Names repeat across
    okresy (three Selce in one kraj). An ambiguous name is settled by a
    municipal candidacy of the same person in one of the candidate obce,
    else by ``[residence]`` in ``overrides.toml``. A country-wide
    candidate's is the one obec of that name in the country, else unknown
    (empty): the lists name only the obec, and a wrong one is worse.
    """
    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for obec in admin.obce.values():
        by_name[(obec.kraj, name_key(obec.name))].append(obec.code)
        by_name[(contests.COUNTRY, name_key(obec.name))].append(obec.code)
    municipal = {
        _person_key(admin, c.obec, c.entry)
        for c in candidacies
        if c.kind in contests.MUNICIPAL
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
        if len(options) > 1 and c.area != contests.COUNTRY:
            options = [
                o for o in options if _person_key(admin, o, c.entry) in municipal
            ]
            how = "municipal candidacy"
        else:
            how = "name"
        if len(options) == 1:
            c.obec = options[0]
            residence_by[how] += 1
        elif c.area == contests.COUNTRY:
            c.obec = ""
            residence_by["none (name only)"] += 1
        else:
            unmatched.add(
                f"residence {c.entry.residence!r} of {c.id}"
                f" ({c.entry.first_name} {c.entry.surname})"
            )
    for cid in set(overrides.residence) - used:
        unmatched.add(f"unused override residence {cid!r}")
    return residence_by


def merge_area(admin: Admin, code: str) -> str:
    """Return the obec persons are merged on: a district counts as its city.

    Empty for an unknown residence.
    """
    return (admin.obce[code].city or code) if code else ""


def _person_key(admin: Admin, obec: str, e: Entry) -> PersonKey:
    return (
        merge_area(admin, obec),
        person_name_key(e.first_name),
        person_name_key(e.surname),
        e.age,
    )


def check_numbers(candidacies: Sequence[Candidacy], *, whole: bool = True) -> None:
    """Check ballot numbers unique per contest and obvody numbered from 1.

    The obvody only where the *whole* councils are elected, not in a
    by-election.
    """
    errors = []
    seen: dict[str, str] = {}
    obvody: dict[str, set[int]] = defaultdict(set)
    for c in candidacies:
        if c.id in seen:
            errors.append(f"{c.id}: {c.entry.source} repeats {seen[c.id]}")
        seen[c.id] = c.entry.source
        if whole and c.obvod is not None and _is_council(c.kind):
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
    surname and age agree, an unknown age agreeing with an unknown one (a
    by-election's mayor and councillor of one name in one obec are one
    person). Where such a key occurs twice within one elected
    body (two namesakes on one council ballot or in two obvody of one
    council) it cannot tell people apart, so none of its candidacies merge.
    The rounds of a presidential election are contests of one office that
    one person stands in both of, so there each round counts on its own
    (:func:`_ballot`).
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

    keys = {c.id: _person_key(admin, c.obec, c.entry) for c in candidacies}
    by_key: dict[PersonKey, list[Candidacy]] = defaultdict(list)
    for c in candidacies:
        by_key[keys[c.id]].append(c)
    groups: list[set[str]] = []
    unmerged = 0
    for same in by_key.values():
        if len({_ballot(c) for c in same}) == len(same):
            groups.append({c.id for c in same})
        else:
            groups += [{c.id} for c in same]
            unmerged += len(same)
    _apply_overrides(groups, overrides)
    return _persons(groups, by_id, keys), unmerged


def _ballot(c: Candidacy) -> str:
    """Return what a person stands at most once in: its body, a round's contest."""
    return c.contest if contests.KINDS[c.kind].sub == "round" else c.body


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
    for a, b in pairwise(persons):
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


def _contest_key(contest: str) -> tuple[int, str, int]:
    """Return the order of contests in the output, that of their candidacies."""
    c = contests.parse(contest)
    return (_ORDER[c.kind.name], c.area, c.sub or 0)


def _contest_json(cid: str, result: Result, sizes: Counter[str]) -> dict[str, object]:
    """Return contest *cid* as the output has it; *sizes* its lists' candidacies."""
    c = contests.parse(cid)
    contest: dict[str, object] = {"id": cid, "kind": c.kind.name, "area": c.area}
    if c.sub is not None:
        contest["obvod"] = c.sub
    if cid in result.lists.seats:
        contest["seats"] = result.lists.seats[cid]
    extra = result.lists.contests.get(cid, {})
    for key in _CONTEST_FIELDS:
        if key == "subjects" and cid in result.lists.subjects:
            contest[key] = [
                _subject_json(s, sizes[f"{cid}/{s.number}"])
                for s in result.lists.subjects[cid]
            ]
        elif key in extra:
            contest[key] = extra[key]
    inc = result.incumbency
    if inc is None:
        return contest
    body = contests.body(cid)
    # Only mayor and president contests have one holder to name.
    held = inc.contests.get(cid)
    if held is not None:
        contest["incumbent"] = incumbents.contest_json(*held)
    seats_2022 = inc.holders.seats_2022.get(body)
    if seats_2022:
        contest["seats_2022"] = seats_2022
    past = inc.holders.past.get(body)
    if past is not None:
        contest["past"] = incumbents.past_json(past)
    return contest


def _subject_json(s: Subject, candidates: int) -> dict[str, object]:
    """Return ballot subject *s*, whose list has *candidates*."""
    item: dict[str, object] = {"number": s.number, "party": s.party}
    if candidates:
        item["candidates"] = candidates
    if s.withdrawn:
        item["withdrawn"] = True
    return item


def _obec_json(o: Obec, result: Result) -> dict[str, object]:
    item: dict[str, object] = {"code": o.code, "name": o.name}
    if o.okres is not None:
        item["okres"] = o.okres
    item["kraj"] = o.kraj
    if o.city is not None:
        item["city"] = o.city
    if o.code in result.lists.zsk:
        item["zsk"] = result.lists.zsk[o.code]
    if o.code in result.lists.council_seats:
        item["council_seats"] = result.lists.council_seats[o.code]
    held = result.incumbency
    if held is None:
        return item
    past = held.holders.regional.get(o.code)
    if past is not None:
        item["past"] = incumbents.past_json(past)
    return item


def to_json(result: Result) -> dict[str, list[Any]]:
    """Return the content of ``candidates.json``; see the module doc."""
    admin = result.admin
    obce = [
        _obec_json(o, result) for o in sorted(admin.obce.values(), key=lambda o: o.code)
    ]
    sizes = Counter(c.contest for c in result.candidacies)
    ids = sorted(
        {*sizes, *result.lists.contests, *result.lists.subjects}, key=_contest_key
    )
    candidacies = []
    for c in result.candidacies:
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
        scope = contests.KINDS[c.kind].scope
        if scope == "kraj" or (scope == "country" and c.obec):
            item["residence"] = c.obec
        elif scope == "country" and e.residence:
            item["residence_name"] = e.residence
        if c.id in result.lists.withdrawn:
            item["withdrawn"] = True
        roles = result.incumbency.roles.get(c.person) if result.incumbency else None
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
        "contests": [_contest_json(cid, result, sizes) for cid in ids],
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
    yield f"candidacies {len(cs):,}: " + ", ".join(
        f"{k} {n:,}" for k, n in sorted(kinds.items(), key=lambda kn: _ORDER[kn[0]])
    )
    obvody: dict[str, Counter[str]] = {k: Counter() for k in ("oz", "zsk")}
    for c in {c.contest: c for c in cs if _is_council(c.kind)}.values():
        obvody[c.kind][c.area] += 1
    multi = sum(1 for n in obvody["oz"].values() if n > 1)
    if obvody["oz"] or obvody["zsk"]:
        yield (
            f"municipal obvody {obvody['oz'].total():,} in {len(obvody['oz']):,} obce,"
            f" {multi} with more than one; VÚC obvody {obvody['zsk'].total()}"
        )
    named = {*result.lists.contests, *result.lists.subjects}
    bare = len(named - {c.contest for c in cs})
    if bare:
        yield f"contests without candidacies: {bare:,}"
    not_held = Counter(contests.parse(c).kind.name for c in result.lists.not_held)
    if not_held:
        yield "uncontested, held nowhere: " + ", ".join(
            f"{k} {n:,}" for k, n in sorted(not_held.items())
        )
    for line in result.lists.unplaced:
        yield f"uncontested, of an obvod not known: {line}"
    elected_only = sum(
        1 for f in result.lists.contests.values() if f.get("elected_only")
    )
    if elected_only:
        yield f"council contests of the elected only: {elected_only:,}"
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
        "+".join(
            sorted((by_id[cid].kind for cid in p.candidacies), key=_ORDER.__getitem__)
        )
        for p in multiple
    )
    for combo, n in combos.most_common():
        yield f"  {combo:<26} {n:>6,}"
    if result.incumbency is not None:
        yield from incumbents.report(result.incumbency)
    else:
        yield "office holders before: not known for this election"
