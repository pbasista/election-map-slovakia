"""Link the persons of an election to the same persons standing in an earlier one.

Neither the candidate lists nor the results identify persons across
elections, so a person of the later election is linked to one of the
earlier election (both as ``candidates.json`` has them) by the rule
:mod:`election_map_slovakia.incumbents` finds office holders with:

- the same name: :func:`candidates.search_key` of first name and surname;
- an age that fits the time between the election days
  (:func:`incumbents.age_fits`), a year off either way only if nobody fits
  exactly (the lists have a few wrong ages);
- the same area: the same obec persons are merged on (a Bratislava or
  Košice district counts as its city; for regional candidates the obec of
  residence), or regional candidacies in the same kraj in both elections,
  a candidate having moved within it.

Several fitting persons are narrowed, in turn, to those of the same obec,
to those standing for one same office (body) in both elections, and to
those whose names are spelled alike, diacritics included: the candidates
step merges candidacies on the exact spelling, so one person whose name a
list spells otherwise in one candidacy (Kolárčik, Kolarčík) is two persons
of one election, and the rule picks the one that fits best.

A link needs exactly one fitting person each way: a later person that fits
several earlier ones the tie-breaks do not tell apart (namesakes of one age
and place), or whose one fit also fits another later person as well or
better, stays unlinked. Persons are linked, not candidacies; a person
standing for several offices has all of them linked at once. A link is
evidence, not proof: a namesake of the same age in the same place, or a
changed surname, defeats it.

``config/links.toml`` corrects the rule per pair of elections
(:func:`load_overrides`): ``link`` pairs make the persons of a later and an
earlier candidacy one, whatever the rule says; ``unlink`` pairs forbid it,
the rule then running as if they did not fit.

Output (:func:`to_json`), for the later election::

    earlier:     ISO day of the earlier election
    method:      "name-age-area", the rule above, for the UI to explain
    persons:     {later person id: earlier person id}
    candidacies: {later candidacy id: [earlier candidacy ids]}
    counts:      {persons, earlier_persons, linked, overridden, ambiguous,
                  same_office}

``candidacies`` holds, for every later candidacy of a linked person, the
earlier candidacies of that person for the same office: the same obec's
mayor or council (any obvod), the same kraj's president or council (any
obvod); contests are named by the same codes in every election, so that is
the same body (``<kind>:<area>``). ``counts``: the persons of each election,
the links (``overridden`` of them from ``links.toml``), the later persons
fitting someone but left unlinked as ambiguous, and the later candidacies in
``candidacies``.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from election_map_slovakia import candidates, incumbents
from election_map_slovakia.config import CANDIDACY_ID, ConfigError

if TYPE_CHECKING:
    from pathlib import Path

LINKS_FILE = "links.toml"
METHOD = "name-age-area"
_Pair = tuple[str, str]
"""A later and an earlier candidacy id, or a later and an earlier person id."""


class LinksError(Exception):
    """The overrides name candidacies the lists lack, or contradict each other."""


@dataclass(frozen=True)
class Candidates:
    """The candidates of one election: its day and its ``candidates.json``."""

    day: dt.date
    data: Mapping[str, Any]


@dataclass(frozen=True)
class Overrides:
    """The ``links.toml`` corrections of one pair of elections."""

    link: tuple[_Pair, ...] = ()
    """(later candidacy, earlier candidacy) whose persons are one."""
    unlink: tuple[_Pair, ...] = ()
    """(later candidacy, earlier candidacy) whose persons are not."""


@dataclass
class Links:
    """The persons of the later election linked to those of the earlier one."""

    earlier: dt.date
    persons: dict[str, str]
    """Later person id → earlier person id."""
    candidacies: dict[str, list[str]]
    """Later candidacy id → earlier candidacies of the same office."""
    later_persons: int
    earlier_persons: int
    overridden: int
    """Links made by ``link`` overrides."""
    ambiguous: list[str]
    """Descriptions of later persons fitting someone but left unlinked."""


@dataclass(frozen=True)
class _Person:
    id: str
    name: tuple[str, str]
    """:func:`candidates.search_key` of first name and surname."""
    spelling: tuple[str, str]
    """:func:`candidates.person_name_key` of first name and surname."""
    age: int
    obec: str
    """The obec its candidacies were merged on."""
    kraje: frozenset[str]
    """Kraje of its regional candidacies."""
    bodies: Mapping[str, Sequence[str]]
    """Body (``<kind>:<area>``) → its candidacies in it."""
    label: str
    """Name, age and first candidacy, for the report."""


def load_overrides(
    path: Path, days: Mapping[str, dt.date]
) -> dict[tuple[str, str], Overrides]:
    """Load ``links.toml``: (later slug, earlier slug) → its overrides.

    The file has a table per pair, ``[<later slug>.<earlier slug>]``, with
    ``link`` and ``unlink`` lists of ``[later candidacy, earlier candidacy]``
    pairs, each optional. *days* maps the slug of every election to its
    day: both slugs must be among them, the later one the more recent.
    """
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"{path}: cannot read: {e.strerror}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML: {e}") from e
    out = {}
    for later, pairs in data.items():
        if later not in days or not isinstance(pairs, dict):
            raise ConfigError(f"{path}: {later}: expected a table named by a slug")
        for earlier, table in pairs.items():
            where = f"{path}: {later}.{earlier}"
            if earlier not in days or not isinstance(table, dict):
                raise ConfigError(f"{where}: expected a table named by a slug")
            if days[earlier] >= days[later]:
                raise ConfigError(f"{where}: {earlier} is not before {later}")
            if unknown := sorted(set(table) - {"link", "unlink"}):
                raise ConfigError(f"{where}.{unknown[0]}: unknown key")
            out[(later, earlier)] = Overrides(
                _pairs(table, "link", where), _pairs(table, "unlink", where)
            )
    return out


def _pairs(table: Mapping[str, object], key: str, where: str) -> tuple[_Pair, ...]:
    value = table.get(key, [])
    if not isinstance(value, list):
        raise ConfigError(f"{where}.{key}: expected a list of pairs")
    out = []
    for pair in value:
        if not (
            isinstance(pair, list)
            and len(pair) == 2  # noqa: PLR2004 - later and earlier
            and all(isinstance(c, str) and CANDIDACY_ID.fullmatch(c) for c in pair)
        ):
            raise ConfigError(f"{where}.{key}: {pair!r} is not a pair of candidacy ids")
        out.append((pair[0], pair[1]))
    return tuple(out)


def match(
    later: Candidates, earlier: Candidates, overrides: Overrides | None = None
) -> Links:
    """Link the persons of *later* to those of *earlier*; see the module doc."""
    overrides = overrides or Overrides()
    lp, ep = _persons(later.data), _persons(earlier.data)
    forced = _person_pairs(overrides.link, later.data, earlier.data, "link")
    forbidden = set(_person_pairs(overrides.unlink, later.data, earlier.data, "unlink"))
    _check(forced, forbidden, overrides)
    taken_l = {lid for lid, _ in forced}
    taken_e = {eid for _, eid in forced}

    by_name_l = _by_name(p for p in lp.values() if p.id not in taken_l)
    by_name_e = _by_name(p for p in ep.values() if p.id not in taken_e)

    def fits(lat: _Person, ear: _Person, slack: int) -> bool:
        return (
            (lat.id, ear.id) not in forbidden
            and incumbents.age_fits(ear.age, earlier.day, lat.age, later.day, slack)
            and (lat.obec == ear.obec or bool(lat.kraje & ear.kraje))
        )

    forward = {
        p.id: _options(p, by_name_e.get(p.name, []), fits)
        for ps in by_name_l.values()
        for p in ps
    }
    backward = {
        p.id: _options(p, by_name_l.get(p.name, []), lambda e, lat, s: fits(lat, e, s))
        for ps in by_name_e.values()
        for p in ps
    }
    pairs = dict(forced)
    ambiguous = []
    for lid, options in forward.items():
        if not options:
            continue
        if len(options) == 1 and [o.id for o in backward[options[0].id]] == [lid]:
            pairs[lid] = options[0].id
        else:
            ambiguous.append(_describe(lp[lid], options))
    return Links(
        earlier.day,
        dict(sorted(pairs.items())),
        _same_office(pairs, lp, ep),
        len(lp),
        len(ep),
        len(forced),
        sorted(ambiguous),
    )


def _persons(data: Mapping[str, Any]) -> dict[str, _Person]:
    """Return the persons of a ``candidates.json`` by id."""
    by_id = {c["id"]: c for c in data["candidacies"]}
    kinds = {c["id"]: c["kind"] for c in data["contests"]}
    out = {}
    for p in data["persons"]:
        cs = [by_id[cid] for cid in p["candidacies"]]
        first = cs[0]
        bodies: dict[str, list[str]] = defaultdict(list)
        kraje = set()
        for c in cs:
            body = c["contest"].partition("/")[0]
            bodies[body].append(c["id"])
            if kinds[c["contest"]] not in candidates.MUNICIPAL:
                kraje.add(body.partition(":")[2])
        first_name, surname = first["first_name"], first["surname"]
        out[p["id"]] = _Person(
            p["id"],
            (candidates.search_key(first_name), candidates.search_key(surname)),
            (
                candidates.person_name_key(first_name),
                candidates.person_name_key(surname),
            ),
            first["age"],
            p["obec"],
            frozenset(kraje),
            dict(bodies),
            f"{first_name} {surname} ({first['age']}, {first['id']})",
        )
    return out


def _person_pairs(
    pairs: Iterable[_Pair],
    later: Mapping[str, Any],
    earlier: Mapping[str, Any],
    key: str,
) -> list[_Pair]:
    """Return the (later, earlier) persons of candidacy *pairs*."""
    lp = {c["id"]: c["person"] for c in later["candidacies"]}
    ep = {c["id"]: c["person"] for c in earlier["candidacies"]}
    out = []
    for lc, ec in pairs:
        for cid, persons, which in ((lc, lp, "later"), (ec, ep, "earlier")):
            if cid not in persons:
                raise LinksError(f"{LINKS_FILE} {key}: no {which} candidacy {cid!r}")
        out.append((lp[lc], ep[ec]))
    return out


def _check(forced: Sequence[_Pair], forbidden: set[_Pair], ov: Overrides) -> None:
    """Reject a person linked twice, or both linked and unlinked."""
    for side, what in ((0, "later"), (1, "earlier")):
        twice = [p for p, n in Counter(pair[side] for pair in forced).items() if n > 1]
        if twice:
            cids = [ov.link[i][side] for i, f in enumerate(forced) if f[side] in twice]
            raise LinksError(f"{LINKS_FILE} link: {what} person linked twice: {cids}")
    for i, pair in enumerate(forced):
        if pair in forbidden:
            raise LinksError(f"{LINKS_FILE}: {list(ov.link[i])} is linked and unlinked")


def _by_name(persons: Iterable[_Person]) -> dict[tuple[str, str], list[_Person]]:
    out: dict[tuple[str, str], list[_Person]] = defaultdict(list)
    for p in persons:
        out[p.name].append(p)
    return out


def _same_obec(one: _Person, other: _Person) -> bool:
    return one.obec == other.obec


def _shared_office(one: _Person, other: _Person) -> bool:
    return not one.bodies.keys().isdisjoint(other.bodies)


def _same_spelling(one: _Person, other: _Person) -> bool:
    return one.spelling == other.spelling


# Tie-breaks among several fitting persons, in turn; see the module doc.
_TIES = (_same_obec, _shared_office, _same_spelling)


def _options(
    one: _Person,
    named: Sequence[_Person],
    fits: Callable[[_Person, _Person, int], bool],
) -> list[_Person]:
    """Return the persons of *named* (the other election) that may be *one*.

    An age off by a year more counts only when nobody of the exact age fits;
    several fitting persons are narrowed by :data:`_TIES`, each applied only
    where it leaves someone.
    """
    for slack in incumbents.AGE_SLACK:
        options = [p for p in named if fits(one, p, slack)]
        for tie in _TIES:
            if len(options) > 1:
                options = [p for p in options if tie(one, p)] or options
        if options:
            return options
    return []


def _same_office(
    pairs: Mapping[str, str], lp: Mapping[str, _Person], ep: Mapping[str, _Person]
) -> dict[str, list[str]]:
    """Return later candidacy → earlier candidacies of the person in its body."""
    out = {}
    for lid, eid in pairs.items():
        earlier = ep[eid].bodies
        for body, cids in lp[lid].bodies.items():
            if body in earlier:
                out.update(dict.fromkeys(cids, sorted(earlier[body])))
    return dict(sorted(out.items()))


def _describe(p: _Person, options: Sequence[_Person]) -> str:
    return f"{p.label}: {', '.join(o.label for o in options)}"


def to_json(links: Links) -> dict[str, object]:
    """Return the links as the later election's data has them; see the module doc."""
    return {
        "earlier": links.earlier.isoformat(),
        "method": METHOD,
        "persons": links.persons,
        "candidacies": links.candidacies,
        "counts": {
            "persons": links.later_persons,
            "earlier_persons": links.earlier_persons,
            "linked": len(links.persons),
            "overridden": links.overridden,
            "ambiguous": len(links.ambiguous),
            "same_office": len(links.candidacies),
        },
    }


def report(links: Links) -> list[str]:
    """Return the summary lines: links, same-office candidacies, ambiguous."""
    kinds = Counter(cid.partition(":")[0] for cid in links.candidacies)
    lines = [
        f"links to {links.earlier}: {len(links.persons):,} of"
        f" {links.later_persons:,} persons ({links.overridden} by {LINKS_FILE}),"
        f" {len(links.ambiguous)} ambiguous; candidacies for the same office: "
        + ", ".join(f"{k} {kinds[k]:,}" for k in candidates.KINDS)
    ]
    lines += [f"  ambiguous {a}" for a in links.ambiguous]
    return lines
