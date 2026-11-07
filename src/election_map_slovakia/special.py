"""The special okrsky of a vote: polling districts without territory.

Some okrsky have no addresses of their own; their voters come from
elsewhere. Two kinds are known:

- ``covid``: the 79 special okrsky of the referendum of 21 January 2023,
  one per okres for the voters in COVID-19 quarantine anywhere in it (Act
  No. 395/2022 Coll., § 3(1): "Územným obvodom špeciálneho volebného
  okrsku je okres"), who voted into a mobile box at home and were struck
  off their own okrsok's list (§ 5(8)). The district office set them up,
  not the mayor, so the municipalities' okrsky documents leave them out.
  Each counts as an okrsok of the okres seat, in Bratislava and Košice of
  the city district the head of the district office chose (§ 3(2)): the
  seat's highest-numbered, the two of Košice I and Košice-okolie both in
  Košice-Sever. Where no voter asked, the okrsok did not vote (§ 4(12)),
  yet ŠÚ SR's territorial division still counts it, without results.
  ŠÚ SR's package declares them: its table ``Špeciálne volebné okrsky``
  (:attr:`election_map_slovakia.config.Units.special`) gives each okres
  and whether its special okrsok voted (``Konanie hlasovania``: ``Áno``,
  ``Nie``). The seat of an okres is the obec of the okres named as it, or
  its only obec; ``special-okrsky.toml`` in the election's curated data
  gives the others, each with its source
  (:func:`election_map_slovakia.config.load_special`), and what explains
  the special okrsky, which the app links.
- ``prison``: an okrsok of a prison, in the national votes (only they have
  voting certificates, which its inmates vote with: § 11c of Act No.
  180/2014 Coll.). ``special-okrsky.toml`` lists each one whose
  municipality's document names the facility as the okrsok, with that
  document.

A municipality numbers its own okrsky 1..N, the special ones counted after
them: the special okrsky of an obec must be its highest-numbered. They are
never drawn and have no addresses; the okrsok-rules jobs and ``ems job
reuse`` count only the territorial okrsky (:func:`territorial`), the
crosswalk never matches them, and the app names them without drawing them
(``special`` of ``data/index.json``), their figures staying in the obec's
and the higher totals as ŠÚ SR has them.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from election_map_slovakia import tables
from election_map_slovakia.config import ConfigError, CuratedSpecial, Units

FILE = "special-okrsky.toml"
"""In an election's curated data (:func:`election_map_slovakia.config.load_special`)."""
COVID, PRISON = "covid", "prison"
VOTED, NOT_VOTED = "Áno", "Nie"
"""``Konanie hlasovania`` of the package's table of special okrsky."""


@dataclass(frozen=True)
class Special:
    """A special okrsok."""

    kind: str
    """:data:`COVID` or :data:`PRISON`."""
    url: str
    title: str
    """What explains it: ŠÚ SR's page on the special okrsky, the
    municipality's document naming the prison."""
    okresy: tuple[tuple[str, bool], ...] = ()
    """Of a COVID-19 special okrsok, the okresy whose special okrsky the
    obec holds (one, but Košice-Sever's two), each with whether it voted;
    which of the obec's special okrsky is whose is not told."""
    facility: str = ""
    """Of a prison's okrsok, the facility as the document names it."""


Specials = dict[str, dict[int, Special]]
"""Obec → okrsok → its special okrsok."""


def read(
    package: Path | None,
    units: Units | None,
    curated: CuratedSpecial | None,
    counts: Mapping[str, int],
    where: str,
) -> Specials:
    """Return a vote's special okrsky.

    *package* is the file of its territorial division *units*, which may
    declare COVID-19 special okrsky (:attr:`Units.special`); *curated* its
    ``special-okrsky.toml`` (*where*, for messages), None without;
    *counts* obec → its okrsky in the territorial division.
    """
    out: Specials = defaultdict(dict)
    covid = curated.covid if curated else None
    if units is not None and units.special:
        if package is None or covid is None:
            raise ConfigError(
                f"{where}: [covid] missing: the package declares special okrsky"
                f" ({units.special}), which need what explains them"
            )
        for obec, okrsky in _covid(
            package, units, curated, counts, covid, where
        ).items():
            out[obec] |= okrsky
    elif covid is not None:
        raise ConfigError(
            f"{where}: [covid] without a package declaring special okrsky"
        )
    for p in curated.prisons if curated else ():
        if p.obec not in counts:
            raise ConfigError(
                f"{where}: prison {p.obec}/{p.okrsok}: no obec of the vote"
            )
        if p.okrsok in out[p.obec]:
            raise ConfigError(f"{where}: prison {p.obec}/{p.okrsok}: already special")
        out[p.obec][p.okrsok] = Special(PRISON, p.url, p.title, facility=p.facility)
    for obec, okrsky in out.items():
        count = counts[obec]
        highest = set(range(count - len(okrsky) + 1, count + 1))
        if set(okrsky) != highest or count <= len(okrsky):
            raise ConfigError(
                f"{where}: obec {obec}: special okrsky {sorted(okrsky)} of {count}:"
                " they must be its highest-numbered, beside one okrsok at least"
            )
    return {obec: dict(sorted(k.items())) for obec, k in sorted(out.items())}


def _covid(
    package: Path,
    units: Units,
    curated: CuratedSpecial | None,
    counts: Mapping[str, int],
    covid: tuple[str, str],
    where: str,
) -> Specials:
    """Return the COVID-19 special okrsky *package* declares (:attr:`Units.special`).

    Each okres's at its seat (see the module doc), the seats of *curated*
    (*where*) where the package does not tell them; *covid* is what
    explains them.
    """
    try:
        p = tables.open_package([package], dt.UTC)
        division = p.table(units.table or "")
        declared = p.table(units.special or "")
        d_okres, d_obec, d_name = (
            division.column("Kód okresu"),
            division.column("Kód obce"),
            division.column("Názov obce"),
        )
        okres, name, voted = (
            declared.column("Kód okresu"),
            declared.column("Názov okresu"),
            declared.column("Konanie hlasovania"),
        )
    except tables.TableError as e:
        raise ConfigError(str(e)) from None
    obce: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in division.rows:
        obce[row[d_okres]].append((row[d_obec], row[d_name]))
    seats = {s.okres: s for s in curated.seats} if curated else {}
    at: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for row in declared.rows:
        code, label, flag = row[okres], row[name], row[voted]
        if flag not in (VOTED, NOT_VOTED):
            raise ConfigError(
                f"{declared.name}: okres {code}: {flag!r}, not Áno or Nie"
            )
        own = [c for c, n in obce.get(code, ()) if n == label] or [
            c for c, _ in obce.get(code, ())[:1] if len(obce[code]) == 1
        ]
        seat = seats.pop(code, None)
        if own and seat:
            raise ConfigError(
                f"{where}: seat of okres {code} {label}: the package names it, {own[0]}"
            )
        if not own and not seat:
            raise ConfigError(
                f"{where}: okres {code} {label}: its seat is not told by the package;"
                " a [[covid.seat]] must give it"
            )
        obec = own[0] if own else seat.obec if seat else ""
        if obec not in counts:
            raise ConfigError(
                f"{where}: seat of okres {code}: no obec {obec} of the vote"
            )
        at[obec].append((label, flag == VOTED))
    if seats:
        raise ConfigError(
            f"{where}: [[covid.seat]] of okresy the package does not declare:"
            f" {', '.join(sorted(seats))}"
        )
    url, title = covid
    out: Specials = {}
    for obec, okresy in at.items():
        count = counts[obec]
        special = Special(COVID, url, title, tuple(okresy))
        out[obec] = {n: special for n in range(count - len(okresy) + 1, count + 1)}
    return out


def describe(s: Special) -> str:
    """Return what special okrsok *s* is, in words, for reports and job items."""
    if s.kind == PRISON:
        return f"the okrsok of a prison, {s.facility}"
    okresy = " or ".join(name for name, _ in s.okresy)
    voted = (
        "it voted"
        if all(v for _, v in s.okresy)
        else "no voter asked, so it did not vote"
        if not any(v for _, v in s.okresy)
        else "of which some voted"
    )
    return (
        f"the COVID-19 special okrsok of okres {okresy} (Act No. 395/2022 Coll.),"
        f" set up by the district office; {voted}"
    )


def territorial(counts: Mapping[str, int], specials: Specials) -> dict[str, int]:
    """Return obec → its territorial okrsky: *counts* less its special ones."""
    return {obec: n - len(specials.get(obec, ())) for obec, n in counts.items()}


def keys(specials: Specials) -> set[str]:
    """Return the special okrsky as ``<obec>/<n>``, as the results key okrsky."""
    return {f"{obec}/{n}" for obec, okrsky in specials.items() for n in okrsky}
