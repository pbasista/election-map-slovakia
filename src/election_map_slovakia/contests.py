"""The kinds of elections and contests, contest ids and where a contest is filed.

An election (``config/elections.toml``) is of one kind, which says what its
contests can be (:data:`ELECTION_KINDS`). A contest is named
``<kind>:<area>[/<sub>]`` and a candidacy ``<contest>#<number>``; the id
without ``/<sub>`` is the contest's body, the office it elects (the same
across elections):

==========  ==============  =========================  =====================
kind        area            sub                        candidates
==========  ==============  =========================  =====================
starosta    obec, BA, KE    –                          persons
oz          obec, BA, KE    council obvod              persons
predseda    kraj (1–8)      –                          persons
zsk         kraj (1–8)      regional obvod             persons
prezident   ``SK``          round (1, 2)               persons
referendum  ``SK``          question                   answers: 1 yes, 2 no
nrsr, ep    ``SK``          –                          parties, by ballot number
nrsr, ep    ``SK``          a party's ballot number    persons of its list
==========  ==============  =========================  =====================

A party-list contest (``nrsr:SK``) has the parties as its candidates and,
for each party ``p``, a list contest (``nrsr:SK/p``) of the persons on its
list, numbered by their position, among whom a voter gives preference votes.

The web app mirrors this module in ``web/js/kinds.js``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

COUNTRY = "SK"
"""The area of a country-wide contest."""


@dataclass(frozen=True)
class Kind:
    """What a kind of contest is."""

    name: str
    single: bool
    """Whether a voter marks one candidate (a mayor, a president, an answer,
    a party); a list contest of a party-list kind is not single whatever
    this says."""
    scope: str
    """``obec``, ``kraj`` or ``country``: what its area is."""
    sub: str | None
    """What ``/<sub>`` is: ``obvod``, ``round``, ``question``, ``list`` or
    nothing."""
    source: str
    """Its results' source in ``status.json`` (:func:`source_of`)."""
    party: bool = False
    """Whether its candidates are parties, each with a list contest."""


KINDS: dict[str, Kind] = {
    k.name: k
    for k in (
        Kind("starosta", single=True, scope="obec", sub=None, source="oso"),
        Kind("oz", single=False, scope="obec", sub="obvod", source="oso"),
        Kind("predseda", single=True, scope="kraj", sub=None, source="osk"),
        Kind("zsk", single=False, scope="kraj", sub="obvod", source="osk"),
        Kind("prezident", single=True, scope="country", sub="round", source="prez"),
        Kind("referendum", single=True, scope="country", sub="question", source="ref"),
        Kind(
            "nrsr", single=True, scope="country", sub="list", source="nrsr", party=True
        ),
        Kind("ep", single=True, scope="country", sub="list", source="ep", party=True),
    )
}
MUNICIPAL = ("starosta", "oz")
REGIONAL = ("predseda", "zsk")
SELF_GOVERNMENT = MUNICIPAL + REGIONAL

ELECTION_KINDS: dict[str, tuple[str, ...]] = {
    "municipal-regional": SELF_GOVERNMENT,
    "by-election": SELF_GOVERNMENT,
    "presidential": ("prezident",),
    "referendum": ("referendum",),
    "parliament": ("nrsr",),
    "european": ("ep",),
}
"""Election kind → the contest kinds its elections can have."""

NATIONAL = frozenset(
    e
    for e, kinds in ELECTION_KINDS.items()
    if all(KINDS[k].scope == "country" for k in kinds)
)
"""The election kinds whose contests are country-wide."""

_AREA = r"(?:\d{6}|BA|KE)"
_N = r"[1-9]\d*"
CONTEST_ID = re.compile(
    rf"starosta:{_AREA}|oz:{_AREA}/{_N}|predseda:[1-8]|zsk:[1-8]/{_N}"
    rf"|prezident:{COUNTRY}/[12]|referendum:{COUNTRY}/{_N}"
    rf"|(?:nrsr|ep):{COUNTRY}(?:/{_N})?"
)
CANDIDACY_ID = re.compile(rf"(?:{CONTEST_ID.pattern})#{_N}")


class ContestError(ValueError):
    """Not a contest id."""


@dataclass(frozen=True)
class Contest:
    """A contest id taken apart."""

    kind: Kind
    area: str
    sub: int | None

    @property
    def is_list(self) -> bool:
        """Whether it is a party's list (``nrsr:SK/12``)."""
        return self.kind.party and self.sub is not None

    @property
    def single(self) -> bool:
        """Whether a voter marks one of its candidates."""
        return self.kind.single and not self.is_list


def parse(contest: str) -> Contest:
    """Return contest id *contest* taken apart; fail on an unknown form."""
    if not CONTEST_ID.fullmatch(contest):
        raise ContestError(f"not a contest id: {contest!r}")
    kind, _, rest = contest.partition(":")
    area, _, sub = rest.partition("/")
    return Contest(KINDS[kind], area, int(sub) if sub else None)


def body(contest: str) -> str:
    """Return the body contest *contest* elects: its id without ``/<sub>``."""
    return contest.partition("/")[0]


def candidacy_contest(candidacy: str) -> str:
    """Return the contest of candidacy id *candidacy*."""
    return candidacy.rpartition("#")[0]


def source_of(contest: str) -> str:
    """Return the results source of *contest*, a key of ``status.json``.

    Each round of a presidential election is a source of its own.
    """
    c = parse(contest)
    if c.kind.sub == "round":
        return f"{c.kind.source}{c.sub}"
    return c.kind.source


def counterpart(contest: str) -> str | None:
    """Return what *contest* is compared with in an earlier election of its kind.

    The same contest where its area stays the same (a mayor, a round, a
    question, a party contest), the body of a council obvod (obvody are
    redrawn between elections), and None for a party's list (the ballot
    numbers are drawn anew).
    """
    c = parse(contest)
    if c.is_list:
        return None
    return body(contest) if c.kind.sub == "obvod" else contest


def area_name(contest: str, okres_of: Mapping[str, str]) -> str:
    """Return the name of the area file that holds *contest*.

    ``kraj/<k>``, ``city/<BA|KE>``, ``okres/<okres>`` (*okres_of* maps an obec
    to its okres), ``country`` or, for a party's list, ``list/<p>``. The data
    bundle has it as ``data/<name>.json``, the results as ``<name>.json``.
    """
    c = parse(contest)
    if c.kind.scope == "country":
        return f"list/{c.sub}" if c.is_list else "country"
    if c.kind.scope == "kraj":
        return f"kraj/{c.area}"
    if c.area in ("BA", "KE"):
        return f"city/{c.area}"
    return f"okres/{okres_of[c.area]}"


def subject_threshold(contest: Mapping[str, Any], members: int) -> float:
    """Return the % of the valid votes a ballot subject needs for seats.

    *contest* is a party-list contest of ``candidates.json`` (``threshold``,
    optional ``coalition_thresholds``, ``[[least, threshold], ...]``),
    *members* how many parties the subject is a coalition of
    (``config/parties.toml`` ``members``; 0 for a party standing alone): the
    threshold of the largest coalition size it reaches, else the contest's.
    """
    threshold = contest["threshold"]
    for least, value in sorted(contest.get("coalition_thresholds", ())):
        if members >= least:
            threshold = value
    return threshold
