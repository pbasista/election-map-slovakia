"""Map the okrsky of an election onto those of a later one: the crosswalk.

Polling districts (okrsky) are redrawn between elections, renumbered,
split and merged, so an okrsok's number says little about where it was
before. The crosswalk gives each okrsok of the later election the okrsky
of the earlier one its area was in, with weights, by the best method the
data allow, per obec (a Bratislava or Košice district counts as one):

- the obec has one okrsok now: it is the whole obec, which every okrsok
  of the obec then made up (:data:`results.SAME`);
- by addresses, where both elections place every address of the obec in
  an okrsok (``okrsok``/``okrsky`` in the ``addr/<obec>.json`` of each,
  :mod:`election_map_slovakia.addresses`; an obec of one okrsok has all its
  addresses in okrsok 1). The addresses of both registers are paired by
  their ``IDENTIFIKATOR``, which the register keeps for an address, and
  those left by street (or part of the obec) and house number where one
  address on either side has them. Of the pairs, the share of an earlier
  okrsok's addresses in a later okrsok is its weight there. An okrsok
  with an earlier one each of whose shares of the other's addresses is at
  least :data:`SAME_SHARE` is that okrsok (:data:`results.SAME`, weight
  1); any other is :data:`results.APPROXIMATE`, its figures estimated as
  the weighted sum of the earlier okrsky's; one with no paired address
  :data:`results.UNKNOWN`. An address stands for its share of the voters:
  a block of flats and a cottage weigh the same;
- by number, where the obec has the same okrsok numbers as before and the
  registered voters of each are within :data:`VOTERS_TOLERANCE` of the
  same number's then (:data:`results.IDENTITY`, weight 1);
- else :data:`results.UNKNOWN`: the okrsky changed and nothing tells how.

Council obvody are counted by how their okrsky were mapped: ``whole``
where they make up whole obce, else by the least certain method of their
okrsky (:func:`map_obvody`); their figures are their okrsky's added up
(``council_past`` of :mod:`election_map_slovakia.build`).

With the crosswalk, :func:`past` gives the later results' ``past``
(:class:`results.Past`): the earlier figures of every okrsok of known
method and of every obec wholly in a contest's area, each contest with
the earlier contest of the same body (``<kind>:<area>``, the same codes
in every election) and the votes of the candidates linked to someone who
stood for that body then (``candidacies`` of
:mod:`election_map_slovakia.links`), by their ballot numbers now; and
of a contest of a whole body (a mayor's, a president's), the same
contest's own figures then.

Output (:func:`to_json`), ``data/build/<day>/crosswalk/<earlier slug>.json``
beside the later election's results::

    earlier:  ISO day of the earlier election
    counts:   {okrsky: {method: n}, obce: {method: n}, obvody: {how: n},
               addresses: {id, street, unpaired}}
    obce:     {obec: {how, okrsky: {okrsok: [method, {earlier okrsok:
                                                       weight}]}}}

A method is ``same``, ``identity``, ``approximate`` or ``unknown``. An
obec's ``how`` is ``whole`` (one okrsok now), ``addresses``, ``identity``
or ``unknown``; an obvod's ``whole`` (of whole obce) or the method of its
least certain okrsok. ``counts`` covers the okrsky and obce of several
okrsky then or now (an obec of one okrsok both times is itself), by the
method of each okrsok and the least certain of each obec, every council
obvod, and the address pairs made.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from election_map_slovakia import addresses, progress
from election_map_slovakia.candidates import Admin
from election_map_slovakia.results import (
    APPROXIMATE,
    IDENTITY,
    PAST_DOUBT,
    SAME,
    UNKNOWN,
    Area,
    Live,
    Past,
    okrsok_key,
)

OUTPUT_DIR = "crosswalk"
SAME_SHARE = 0.95
"""The share of each okrsok's addresses that the other holds for two
okrsky of different elections to be the same area."""
VOTERS_TOLERANCE = 0.1
"""How far an okrsok's registered voters may be from those of the same
number before, as a share of those before, for it to be taken for that
okrsok where the addresses do not tell."""
METHOD_NAMES = {
    UNKNOWN: "unknown",
    SAME: "same",
    IDENTITY: "identity",
    APPROXIMATE: "approximate",
}
# How much a method leaves to doubt (results.PAST_DOUBT): an obvod or obec
# is as certain as its least certain okrsok.
_DOUBT = {m: d for d, m in enumerate(PAST_DOUBT)}
WHOLE, ADDRESSES, BY_NUMBER, NONE = "whole", "addresses", "identity", "unknown"
"""How an obec's okrsky were mapped (:attr:`ObecWalk.how`)."""

Sources = dict[int, float]
"""Earlier okrsok → its weight in a later one."""
HouseKey = tuple[str, str, str]
"""An address by ``streets`` or ``parts``, its name and its house number."""


@dataclass(frozen=True)
class ObecWalk:
    """The later okrsky of an obec, each with the earlier okrsky it was in."""

    how: str
    okrsky: dict[int, tuple[int, Sources]]
    """Later okrsok → its method (:data:`results.PAST_METHODS`) and sources
    (none where :data:`results.UNKNOWN`)."""


@dataclass
class Crosswalk:
    """The okrsky of a later election mapped onto those of an earlier one."""

    earlier: dt.date
    obce: dict[str, ObecWalk] = field(default_factory=dict)
    earlier_okrsky: dict[str, dict[int, int]] = field(default_factory=dict)
    """Obec → earlier okrsok → its registered voters then."""
    obvody: dict[str, str] = field(default_factory=dict)
    """Later council contest → how its okrsky were mapped (:func:`map_obvody`)."""
    paired: Counter[str] = field(default_factory=Counter)
    """Address pairs made: ``id``, ``street``, and ``unpaired`` addresses."""

    def several(self) -> dict[str, ObecWalk]:
        """Return the obce of several okrsky then or now."""
        return {
            obec: w
            for obec, w in self.obce.items()
            if len(w.okrsky) > 1 or len(self.earlier_okrsky.get(obec, ())) > 1
        }


def okrsky_of(live: Live) -> dict[str, dict[int, int]]:
    """Return obec → okrsok → its registered voters, of *live*'s okrsok files."""
    out: dict[str, dict[int, int]] = defaultdict(dict)
    for contests in live.okrsky.values():
        for areas in contests.values():
            for key, (eligible, *_) in areas.items():
                obec, _, n = key.partition("/")
                if eligible is not None:
                    out[obec].setdefault(int(n), eligible)
    return dict(out)


def walk_obec(
    later: Mapping[int, int],
    earlier: Mapping[int, int] | None,
    pairs: Mapping[tuple[int, int], int] | None,
) -> ObecWalk:
    """Return how the *later* okrsky of an obec map onto its *earlier* ones.

    Each maps okrsok → registered voters; *earlier* is None for an obec
    not in the earlier results. *pairs* counts the addresses by (earlier
    okrsok, later okrsok), None where either election does not place them.
    """
    if not earlier:
        return ObecWalk(NONE, {j: (UNKNOWN, {}) for j in later})
    if len(later) == 1:
        return ObecWalk(WHOLE, {j: (SAME, dict.fromkeys(earlier, 1.0)) for j in later})
    pairs = {(i, j): n for (i, j), n in (pairs or {}).items() if i in earlier}
    if pairs:
        return ObecWalk(ADDRESSES, _by_addresses(later, pairs))
    if set(later) == set(earlier) and all(
        abs(e - earlier[n]) <= VOTERS_TOLERANCE * earlier[n] for n, e in later.items()
    ):
        return ObecWalk(BY_NUMBER, {j: (IDENTITY, {j: 1.0}) for j in later})
    return ObecWalk(NONE, {j: (UNKNOWN, {}) for j in later})


def _by_addresses(
    later: Iterable[int], pairs: Mapping[tuple[int, int], int]
) -> dict[int, tuple[int, Sources]]:
    """Return each later okrsok's method and sources by address *pairs*."""
    per_earlier: Counter[int] = Counter()
    per_later: Counter[int] = Counter()
    for (i, j), n in pairs.items():
        per_earlier[i] += n
        per_later[j] += n
    out: dict[int, tuple[int, Sources]] = {}
    for j in later:
        if not per_later[j]:
            out[j] = (UNKNOWN, {})
            continue
        sources = {i: n / per_earlier[i] for (i, k), n in pairs.items() if k == j}
        same = [
            i
            for i, share in sources.items()
            if share >= SAME_SHARE and pairs[(i, j)] / per_later[j] >= SAME_SHARE
        ]
        out[j] = (SAME, {same[0]: 1.0}) if same else (APPROXIMATE, sources)
    return out


def build(
    later: Mapping[str, Mapping[int, int]],
    earlier: Mapping[str, Mapping[int, int]],
    pairs: Mapping[str, Mapping[tuple[int, int], int]],
    day: dt.date,
) -> Crosswalk:
    """Return the crosswalk of every obec of *later* (:func:`walk_obec`).

    *later* and *earlier* map obec → okrsok → registered voters
    (:func:`okrsky_of`); *pairs* the obce placed by address in both.
    """
    return Crosswalk(
        day,
        {
            obec: walk_obec(okrsky, earlier.get(obec), pairs.get(obec))
            for obec, okrsky in sorted(later.items())
        },
        {obec: dict(okrsky) for obec, okrsky in earlier.items()},
    )


def make(
    later: Live, earlier: Live, registers: Sequence[Register], day: dt.date
) -> Crosswalk:
    """Return the crosswalk of *later*'s okrsky onto *earlier*'s (of *day*).

    By address where both *registers* (earlier, later) place them, with
    the council obvody mapped (:func:`map_obvody`).
    """
    now, then = okrsky_of(later), okrsky_of(earlier)
    with progress.stage("pairing the addresses of both elections"):
        pairs, paired = address_pairs(registers, (then, now))
    walk = build(now, then, pairs, day)
    walk.paired = paired
    walk.obvody = map_obvody(walk, contest_okrsky(later, "oz"))
    return walk


# --- addresses -----------------------------------------------------------------


class Register(NamedTuple):
    """An election's address register, read as its ``addresses`` step did."""

    path: Path
    admin: Admin
    overrides: Mapping[str, str]
    skip: Collection[str]
    addr: Path
    """Its ``addr/`` output (:mod:`election_map_slovakia.addresses`)."""


Lookup = Mapping[HouseKey, int]
"""An obec's addresses → their okrsok, 0 where two of one key differ."""


def okrsok_lookup(path: Path) -> dict[HouseKey, int] | None:
    """Return the okrsok of every address of an ``addr/<obec>.json``.

    None where the file places no address in an okrsok, or is missing.
    """
    try:
        content = json.loads(path.read_bytes())
    except FileNotFoundError:
        return None
    out: dict[HouseKey, int] = {}
    placed = False
    for kind in (addresses.STREETS, addresses.PARTS):
        for group in content.get(kind, ()):
            numbers = group["numbers"]
            if "okrsok" in group:
                units = [group["okrsok"]] * len(numbers)
            elif "okrsky" in group:
                units = group["okrsky"]
            else:
                continue
            placed = True
            for number, unit in zip(numbers, units, strict=True):
                key = (kind, group["name"], number)
                out[key] = unit if out.get(key, unit) == unit else 0
    return out if placed else None


def lookups(
    addr: Path, okrsky: Mapping[str, Collection[int]], obce: Iterable[str]
) -> dict[str, Lookup | None]:
    """Return obec → its addresses' okrsky, of *obce* by ``addr/`` *addr*.

    An obec of one okrsok (*okrsky*) has none to look up (``{}``: all in
    okrsok 1).
    """
    return {
        obec: {}
        if len(okrsky.get(obec, ())) == 1
        else okrsok_lookup(addr / f"{obec}.json")
        for obec in obce
    }


def address_pairs(
    registers: Sequence[Register], okrsky: Sequence[Mapping[str, Collection[int]]]
) -> tuple[dict[str, Counter[tuple[int, int]]], Counter[str]]:
    """Return obec → address count by (earlier okrsok, later okrsok).

    *registers* and *okrsky* (obec → okrsok numbers) are the earlier and
    the later election's. For every obec of several okrsky then or now
    that both place by address (:func:`lookups`), the addresses of the two
    registers paired by id, then those left by street and number where
    unique on each side; and how many pairs each way made (``id``,
    ``street``) and how many addresses of either register stayed unpaired
    (``unpaired``).
    """
    candidates = [
        obec
        for obec, numbers in okrsky[1].items()
        if len(numbers) > 1 or len(okrsky[0].get(obec, ())) > 1
    ]
    found = [
        lookups(r.addr, o, candidates) for r, o in zip(registers, okrsky, strict=True)
    ]
    need = {o for o in candidates if all(f.get(o) is not None for f in found)}
    houses = [
        _houses(r, {o: f[o] for o in need})
        for r, f in zip(registers, found, strict=True)
    ]
    pairs: dict[str, Counter[tuple[int, int]]] = {}
    paired: Counter[str] = Counter()
    for obec in sorted(need):
        then, now = houses[0].get(obec, {}), houses[1].get(obec, {})
        counts: Counter[tuple[int, int]] = Counter()
        common = then.keys() & now.keys()
        for ident in common:
            counts[(then[ident][1], now[ident][1])] += 1
        left = [_by_key(h, h.keys() - common) for h in (then, now)]
        streets = 0
        for key in left[0].keys() & left[1].keys():
            a, b = left[0][key], left[1][key]
            if a is not None and b is not None:
                counts[(a, b)] += 1
                streets += 1
        paired["id"] += len(common)
        paired["street"] += streets
        paired["unpaired"] += len(then) + len(now) - 2 * (len(common) + streets)
        pairs[obec] = Counter({k: n for k, n in counts.items() if all(k)})
    return pairs, paired


def _houses(
    register: Register, found: Mapping[str, Lookup | None]
) -> dict[str, dict[str, tuple[HouseKey, int]]]:
    """Return obec → address id → its key and okrsok (0: not placed), of *found*."""
    out: dict[str, dict[str, tuple[HouseKey, int]]] = defaultdict(dict)
    for row in addresses.register_rows(
        register.path, register.admin, register.overrides, register.skip
    ):
        lookup = found.get(row.obec)
        if lookup is None:
            continue
        key = (*row.group, addresses.house_number(row.supisne, row.orientacne))
        out[row.obec][row.identifikator] = (key, lookup.get(key, 0) if lookup else 1)
    return out


def _by_key(
    houses: Mapping[str, tuple[HouseKey, int]], ids: Iterable[str]
) -> dict[HouseKey, int | None]:
    """Return key → okrsok of *ids* among *houses*; None for a key of several."""
    out: dict[HouseKey, int | None] = {}
    for ident in ids:
        key, okrsok = houses[ident]
        out[key] = None if key in out else okrsok
    return out


# --- obvody --------------------------------------------------------------------


def body(contest: str) -> str:
    """Return the body of *contest*: its id without the obvod (``oz:528595``)."""
    return contest.partition("/")[0]


def contest_okrsky(live: Live, kind: str) -> dict[str, list[str]]:
    """Return contest of *kind* → its okrsok keys, of *live*'s okrsok files."""
    return {
        contest: list(areas)
        for contests in live.okrsky.values()
        for contest, areas in contests.items()
        if contest.startswith(f"{kind}:")
    }


def map_obvody(walk: Crosswalk, later: Mapping[str, Collection[str]]) -> dict[str, str]:
    """Return later council contest → how its okrsky were mapped.

    *later* maps council contests to their okrsok keys
    (:func:`contest_okrsky`). :data:`WHOLE` for an obvod of whole obce, else
    the name of the least certain method of its okrsky. The figures of an
    obvod are its okrsky's added up (``build.council_past``); this only
    counts how the obvody fared (:func:`counts`).
    """
    out: dict[str, str] = {}
    for contest, keys in sorted(later.items()):
        by_obec: dict[str, set[int]] = defaultdict(set)
        for key in keys:
            obec, _, n = key.partition("/")
            by_obec[obec].add(int(n))
        out[contest] = _obvod_how(walk, by_obec)
    return out


def _obvod_how(walk: Crosswalk, by_obec: Mapping[str, set[int]]) -> str:
    """Return how the okrsky *by_obec* of an obvod were mapped (:func:`map_obvody`)."""
    doubt = 0
    whole = True
    for obec, numbers in by_obec.items():
        w = walk.obce.get(obec)
        if w is None or not walk.earlier_okrsky.get(obec):
            return METHOD_NAMES[UNKNOWN]
        if numbers == set(w.okrsky):
            continue
        whole = False
        doubt = max(doubt, *(_DOUBT[w.okrsky[n][0]] for n in numbers))
    return WHOLE if whole else METHOD_NAMES[PAST_DOUBT[doubt]]


# --- the past of the later results ---------------------------------------------


def past(
    later: Live,
    earlier: Live,
    walk: Crosswalk,
    linked: Mapping[str, Sequence[str]],
) -> Past:
    """Return the ``past`` of the *later* results: *earlier*'s by *walk*.

    *linked* maps later candidacies to the earlier candidacies of their
    persons for the same body (``candidacies`` of the links). Every okrsok
    of an obec of several then or now gets its method; every okrsok of a
    known one and every obec all of whose okrsky are in a contest get the
    contest body's earlier figures there, rounded estimates where weighed;
    every contest of a whole body its own figures then (``totals``).
    """
    then: dict[str, dict[str, tuple[str, Area]]] = defaultdict(dict)
    for contests in earlier.okrsky.values():
        for contest, areas in contests.items():
            for key, area in areas.items():
                then[key][body(contest)] = (contest, area)
    ballots: dict[str, dict[int, dict[str, int]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for candidacy, theirs in linked.items():
        contest, _, number = candidacy.partition("#")
        for other in theirs:
            c, _, n = other.partition("#")
            ballots[contest][int(number)][c] = int(n)
    methods = {
        okrsok_key(obec, n): method
        for obec, w in walk.several().items()
        for n, (method, _) in w.okrsky.items()
    }
    out = Past(walk.earlier.isoformat(), methods)
    now = okrsky_of(later)
    records = earlier.records()
    for contests in later.okrsky.values():
        for contest, areas in contests.items():
            mine = ballots.get(contest, {})
            estimate = _Estimate(then, body(contest), mine)
            units = _units(walk, methods, now, areas, estimate)
            if units:
                out.contests[contest] = units
            record = records.get(contest)
            if contest == body(contest) and record is not None:
                votes = {c[0]: c[1] for c in record.candidates}
                out.totals[contest] = (
                    record.eligible,
                    record.voters,
                    record.valid,
                    {
                        n: votes[theirs[contest]]
                        for n, theirs in sorted(mine.items())
                        if theirs.get(contest) in votes
                    },
                )
    return out


def _units(
    walk: Crosswalk,
    methods: Mapping[str, int],
    now: Mapping[str, Mapping[int, int]],
    okrsky: Iterable[str],
    estimate: _Estimate,
) -> dict[str, Area]:
    """Return the earlier figures of a contest's *okrsky* and whole obce.

    *methods* are those of the okrsky of the obce of several, *now* every
    obec's okrsky.
    """
    units: dict[str, Area] = {}
    by_obec: dict[str, set[int]] = defaultdict(set)
    for key in okrsky:
        obec, _, n = key.partition("/")
        by_obec[obec].add(int(n))
        if methods.get(key, UNKNOWN) != UNKNOWN:
            figure = estimate(obec, walk.obce[obec].okrsky[int(n)][1])
            if figure is not None:
                units[key] = figure
    for obec, numbers in by_obec.items():
        earlier = walk.earlier_okrsky.get(obec)
        if earlier and numbers == set(now.get(obec, ())):
            figure = estimate(obec, dict.fromkeys(earlier, 1.0))
            if figure is not None:
                units[obec] = figure
    return units


class _Estimate:
    """The earlier figures of a body, weighed over earlier okrsky.

    *then* maps earlier okrsky to body → (earlier contest, figures);
    *ballots* later ballot numbers to earlier contest → earlier number.
    """

    def __init__(
        self,
        then: Mapping[str, Mapping[str, tuple[str, Area]]],
        of: str,
        ballots: Mapping[int, Mapping[str, int]],
    ) -> None:
        self.then = then
        self.body = of
        self.ballots = ballots

    def __call__(self, obec: str, sources: Mapping[int, float]) -> Area | None:
        """Return the figures of okrsky *sources* of *obec*.

        None if any of weight has no figures of the body: counted as nought,
        it would leave the sum short.
        """
        eligible = voters = valid = 0.0
        votes: dict[int, float] = {}
        for i, weight in sources.items():
            hit = self.then.get(okrsok_key(obec, i), {}).get(self.body)
            if hit is None:
                if weight > 0:
                    return None
                continue
            contest, (e, v, b, x) = hit
            eligible += weight * (e or 0)
            voters += weight * (v or 0)
            valid += weight * (b or 0)
            for n, theirs in self.ballots.items():
                number = theirs.get(contest)
                if number is not None:
                    votes[n] = votes.get(n, 0.0) + weight * x.get(number, 0)
        if not sources:
            return None
        return (
            round(eligible),
            round(voters),
            round(valid),
            {n: round(v) for n, v in sorted(votes.items())},
        )


# --- output --------------------------------------------------------------------


def counts(walk: Crosswalk) -> dict[str, dict[str, int]]:
    """Return the okrsky, obce and obvody of each method; see the module doc."""
    several = walk.several()
    okrsky = Counter(
        METHOD_NAMES[m] for w in several.values() for m, _ in w.okrsky.values()
    )
    obce = Counter(
        METHOD_NAMES[max((m for m, _ in w.okrsky.values()), key=_DOUBT.__getitem__)]
        for w in several.values()
    )
    obvody = Counter(walk.obvody.values())
    return {
        "okrsky": dict(sorted(okrsky.items())),
        "obce": dict(sorted(obce.items())),
        "obvody": dict(sorted(obvody.items())),
        "addresses": dict(sorted(walk.paired.items())),
    }


def to_json(walk: Crosswalk) -> dict[str, Any]:
    """Return the crosswalk as written; see the module doc."""
    return {
        "earlier": walk.earlier.isoformat(),
        "counts": counts(walk),
        "obce": {
            obec: {
                "how": w.how,
                "okrsky": {
                    str(n): [
                        METHOD_NAMES[m],
                        {str(i): round(x, 4) for i, x in sorted(s.items())},
                    ]
                    for n, (m, s) in sorted(w.okrsky.items())
                },
            }
            for obec, w in walk.several().items()
        },
    }


def report(walk: Crosswalk, figures: Past) -> list[str]:
    """Return the summary lines: methods of okrsky, obce and obvody, pairs."""
    c = counts(walk)

    def line(name: str) -> str:
        return ", ".join(f"{m} {n:,}" for m, n in c[name].items())

    contests = len(figures.contests)
    units = sum(len(u) for u in figures.contests.values())
    return [
        f"crosswalk to {walk.earlier}: okrsky of the obce of several then or now:"
        f" {line('okrsky')}",
        f"  obce, by their least certain okrsok: {line('obce')}",
        f"  council obvody: {line('obvody')}",
        f"  addresses paired: {line('addresses')}",
        f"  past: {units:,} figures of {contests:,} contests",
    ]
