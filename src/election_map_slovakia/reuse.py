"""Give a vote without obvod and okrsok rules of its own another vote's.

The ``obvod-rules`` and ``okrsok-rules`` jobs of an earlier election look
for its own documents; where none is found (the not-found lists of
:mod:`election_map_slovakia.obvodrules` and
:mod:`election_map_slovakia.okrsokrules`), the rules transcribed for the
latest election stand in, but only where the layout provably stayed the
same (``ems job reuse --election DAY``):

- the council obvody of an obec with several (``obvody/oz/<obec>.toml``):
  the latest rule set has the same obvod numbers with the same seats (the
  candidate data), and gives each obvod the okrsky ŠÚ SR counted in it in
  the earlier election, each with voters on the roll within
  :data:`TOLERANCE` of the earlier count
  (:func:`election_map_slovakia.obvodrules.official_okrsky` of both); the
  copy brings the okrsky along;
- the okrsky of an obec whose earlier council obvody have a rule set of
  their own: the latest rule set's okrsky per obvod are those ŠÚ SR
  counted, for the same obvod numbers, the voters within the tolerance;
- the okrsky of an obec with one council obvod in both elections
  (``okrsky/<obec>.toml``): as many okrsky, the voters within the
  tolerance.

The copy must also fit the earlier election's addresses as the jobs'
checks demand: every address in exactly one obvod and okrsok, each with
addresses, the okrsky drawable. It is marked ``reused`` (the council rule
set) or ``okrsky_reused`` with the latest election's day and a note saying
why (:mod:`election_map_slovakia.obvody`); the obec stays in the not-found
list, which records the search. Rules naming streets the earlier register
lacks are kept as they are: they select nothing there.

Any other vote (a country-wide one, a by-election) elects no council, or
a by-election some of one: the okrsky of each obec that voted in several
(its ``units``; of a by-election only the obce with a contest) are copied,
where it has neither okrsky nor a rule set yet, from the regular election
nearest in time that proves them the same, else from the next nearest (a
by-election only from the regular elections before it, newest first: it
fills seats of the council elected then, in that council's obvody):
numbered 1..N for the N okrsky of its territorial division, the okrsky of
each council obvod that voted (a by-election's) those of the source's
obvod, and each okrsok that voted with voters on the roll (its okrsok
files: :func:`election_map_slovakia.okrsokrules.okrsok_voters`) within
:data:`TOLERANCE` of its count in that election; and they must fit its
addresses. Without voters per okrsok (before the results, or a
by-election of 2018–2022, whose packages have none) nothing is proven,
so nothing is copied. An okrsky file is copied as such; a council rule set
with its obvody, which where the vote elects no council only place the
okrsky (``ems geo`` draws them within the whole obec). The copy is marked
``okrsky_reused`` (and the rule set ``reused``) with the source election's
day and a note saying so and whether the vote's own document was searched
for; supplements of the source lose their marks, the header keeping the
source file's. Okrsky the source transcribed from the document of the
vote itself (``okrsky_referendum`` of the 2022 elections' rule sets: the
2023 referendum's) are the vote's own: copied without ``okrsky_reused``,
with their documents and dating, only numbered as the territorial
division numbers them. Where a by-election's okrsky are not proven the
same, a council rule set still draws the council obvody that voted, each
with voters on the roll within :data:`TOLERANCE` of its count in the
source, copied without its okrsky.

Where units stay unknown after that, every vote, the latest regular
election too, takes those of another vote all the same, unproven: a
stand-in, so that the map draws something (:func:`stand_in`). For each
obec and kind of unit without units of its own (or with a stand-in, which
is chosen anew), the units of the vote nearest in time, before or after,
whose units of the obec are its own (neither reused nor a stand-in
themselves: no chains; but a by-election's council obvody, below), the
later of two as near; failing that the next nearest:

- council obvody, of an obec whose council the vote elects in several
  obvody (a regular election; a by-election with a council contest in an
  obec whose council has several): a regular election's rule set with
  the same obvod numbers and seats (a by-election's: the obvody that voted
  among them, and only from the regular election of its term, before it:
  a later council's obvody are another council's). A by-election takes
  its term's rule set even where that is another vote's itself (reused,
  or a stand-in there): the council whose seats it fills was elected in
  those obvody, however the term draws them; the copy names the vote
  whose borders they are. Its okrsky come along
  where they fit as below, else each obvod gets those ŠÚ SR counted in it
  without rules (drawn where it has one, which is then the obvod);
- okrsky, of an obec that voted in several: as many as the vote's
  territorial division counts, and where the vote elects the council in
  several obvody those ŠÚ SR counted in each, into its council rule set
  from one with the same obvod numbers; where it elects the council in
  one obvod, or councils elsewhere but none there, an okrsky file; a vote
  electing no council at all (a country-wide one) takes either (a rule
  set's council obvody, marked ``reused``, then only place
  the okrsky). They must place every address.

Where the voters on the roll of a unit are known for both votes (ŠÚ SR's
territorial division or the okrsok files), they must be within
:data:`PLAUSIBLE` of the vote's count: farther apart, the layout clearly
changed; where they are not known, the units stand in all the same. The
copy must fit the vote's addresses as a reused one must. It is marked
``adopted`` (and ``okrsky_adopted`` where its okrsky are drawn) or
``okrsky_adopted`` with the source's day and a basis: why the vote has no
units of its own (the note of the not-found list, where the obec is in
it), which vote stands in and why that one (the nearer ones not taken,
and why), and the voters of both where known. The report says what stood
in from where, and why the rest stays unknown: no other vote has such
units of its own, none fits structurally, the voters differ too much, or
the copy does not fit the addresses. A stand-in that no source fits any
more is withdrawn.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from election_map_slovakia import (
    addresses,
    candidates,
    jobs,
    obvodrules,
    obvody,
    okrsokrules,
)
from election_map_slovakia.config import BY_ELECTION, REGULAR, Config, Election

TOLERANCE = 0.10
"""How far an okrsok's voters may differ between the elections, as a share
of the earlier count."""
PLAUSIBLE = 0.25
"""How far the voters of an obvod or okrsok that stands in may differ,
likewise: farther apart, the layout clearly changed."""
OBVODY, OKRSKY = "obvody", "okrsky"
"""The kinds of unit that stand in, and two of what :func:`_copy_of` copies."""
_SEVERAL = 2
"""Okrsky of an obec that are drawn (an obec of one is its okrsok)."""


@dataclasses.dataclass(frozen=True)
class _Context:
    """What deciding on the obce of one earlier election needs."""

    cfg: Config
    election: Election
    latest: Election
    seats: dict[str, int]
    """Council obvod contest → seats, of the earlier election."""
    units: obvodrules.Okrsky
    """ŠÚ SR's okrsky of the earlier election."""
    later_units: obvodrules.Okrsky
    """ŠÚ SR's okrsky of the latest election."""

    @property
    def curated(self) -> Path:
        """Return the earlier election's curated data."""
        return self.cfg.election_dir(self.election)

    @property
    def later(self) -> Path:
        """Return the latest election's curated data."""
        return self.cfg.election_dir(self.latest)

    def places(self, code: str) -> obvody.ObecPlaces:
        """Return the earlier election's addresses of obec *code*."""
        path = obvodrules.places_dir(self.cfg, self.election) / f"{code}.json"
        if not path.is_file():
            raise jobs.JobError(f"{path} missing; run `ems addresses` first")
        return obvody.load_places(path)

    def obvod_seats(self, code: str) -> dict[int, int]:
        """Return obvod → seats of obec *code* in the earlier election."""
        return {
            int(contest.rpartition("/")[2]): n
            for contest, n in self.seats.items()
            if contest.startswith(f"oz:{code}/")
        }


def run(cfg: Config, election: Election) -> list[str]:
    """Copy other votes' rules where *election* has none; return report lines.

    First what is proven the same: an earlier regular election the latest
    one's (:func:`_run_regular`), any other vote the regular elections'
    (:func:`_run_other`); the latest has nothing later to prove it by.
    Then the stand-ins (:func:`stand_in`). See the module doc.
    """
    if election.kind != REGULAR:
        lines = _run_other(cfg, election)
    elif election.day == cfg.latest.day:
        lines = []
    else:
        lines = _run_regular(cfg, election)
    votes = {e.day: Vote(cfg, e) for e in cfg.elections}
    return lines + stand_in(cfg, election, votes)


def _run_regular(cfg: Config, election: Election) -> list[str]:
    """Copy the latest election's rules where they provably fit *election*'s.

    A stand-in gives way to them (:func:`_obvody`, :func:`_okrsky`).
    """
    latest = cfg.latest
    data = obvodrules.candidate_data(cfg, election)
    c = _Context(
        cfg,
        election,
        latest,
        obvodrules.contest_seats(data),
        obvodrules.official_okrsky(cfg, election),
        obvodrules.official_okrsky(cfg, latest),
    )
    lines = []
    current = obvody.load_rule_sets(c.curated)
    later = obvody.load_rule_sets(c.later)
    for code, entry in obvodrules.load_not_found(cfg, election).items():
        if code not in current or current[code].adoption:
            lines.append(f"{entry['name']} ({code}), obvody: {_obvody(c, code, later)}")
    current = obvody.load_rule_sets(c.curated)
    later_okrsky = obvody.okrsok_rule_sets(c.later)
    for code, entry in okrsokrules.load_not_found(cfg, election).items():
        rules = current.get(code)
        if rules is None or not rules.okrsky or rules.okrsky_adoption:
            lines.append(
                f"{entry['name']} ({code}), okrsky:"
                f" {_okrsky(c, code, rules, later_okrsky.get(code))}"
            )
    return lines


def _obvody(c: _Context, code: str, later: Mapping[str, obvody.RuleSet]) -> str:
    """Copy the latest council rule set of obec *code* if it fits; say what was done."""
    rules = later.get(code)
    if rules is None:
        return f"not reused: no rule set of {c.latest.day}"
    if rules.adoption:
        return f"not reused: the rule set of {c.latest.day} is a stand-in itself"
    seats = c.obvod_seats(code)
    if rules.seats != seats:
        return (
            f"not reused: obvody and seats {_seats(rules.seats)}, then {_seats(seats)}"
        )
    if not rules.okrsky:
        return f"not reused: the rule set of {c.latest.day} lacks the okrsky"
    why = _layout_problem(c, code, rules)
    if why:
        return f"not reused: {why}"
    p = c.places(code)
    a = obvody.assign(rules, p.places, p.kus, p.planar())
    problems = addresses.check_assignment(rules, list(seats), p, a)
    problems = problems or _okrsok_fit(c.cfg, rules, p, a)
    if problems:
        return f"not reused: on the addresses of {c.election.day}: {problems[0]}"
    note = _note(
        c,
        f"this is the rule set of the elections of {c.latest.day}, whose obvody,"
        f" seats and okrsky are those of {c.election.day.year}",
    )
    copy = dataclasses.replace(
        rules,
        reused=c.latest.day,
        note=" ".join(filter(None, (note, rules.note))),
        okrsky_reused=c.latest.day,
        okrsky_referendum=None,
        okrsky_note=" ".join(filter(None, (note, rules.okrsky_note))),
    )
    return _write_rule_set(c, code, copy)


def _okrsky(
    c: _Context,
    code: str,
    current: obvody.RuleSet | None,
    rules: obvody.RuleSet | None,
) -> str:
    """Copy the latest okrsky of obec *code*, *rules*, if they fit; say what was done.

    *current* is its council rule set in the earlier election, None if it
    elected its council in one obvod (or has no rule set yet); *rules* the
    latest election's rule set that gives the okrsky, if one.
    """
    if current is None and len(c.units.get(code, {})) > 1:
        return "not reused: several council obvody but no rule set for them"
    if current is not None and current.adoption:
        return "not reused: its council obvody are a stand-in"
    if rules is None or rules.whole != (current is None):
        return f"not reused: no okrsky of {c.latest.day} of the same kind"
    if rules.okrsky_adoption:
        return f"not reused: the okrsky of {c.latest.day} are a stand-in themselves"
    if current is not None and list(rules.seats) != list(current.seats):
        return "not reused: other obvody"
    why = _layout_problem(c, code, rules)
    if why:
        return f"not reused: {why}"
    note = _note(
        c,
        f"these are the okrsky of the elections of {c.latest.day}, the same"
        f" as in {c.election.day.year}",
    )
    marks = {
        "okrsky_reused": c.latest.day,
        "okrsky_note": " ".join(filter(None, (note, rules.okrsky_note))),
    }
    return _copy_okrsky(c, code, current, rules, marks)


def _write_rule_set(c: _Context, code: str, copy: obvody.RuleSet) -> str:
    """Write *copy*, of the latest rule set of obec *code*; return the report."""
    source = obvody.rules_path(c.later, code)
    path = obvody.rules_path(c.curated, code)
    header = [
        f"The rule set of the elections of {c.latest.day},"
        f" {source.relative_to(c.cfg.root)}, reused by `ems job reuse`. Its header",
        "there:",
        *(f"  {h}" for h in okrsokrules.header(source)),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obvody.dump(copy, header), encoding="utf-8")
    return f"reused, {path.relative_to(c.cfg.root)}"


def _copy_okrsky(
    c: _Context,
    code: str,
    current: obvody.RuleSet | None,
    rules: obvody.RuleSet,
    marks: Mapping[str, Any],
) -> str:
    """Write the okrsky *rules* of the latest election for obec *code*; report it.

    Into the earlier council rule set *current*, or as its okrsky file if
    None; *marks* are the ``okrsky_*`` fields saying where they come from.
    A stand-in's mark goes.
    """
    source = (
        obvody.okrsky_path(c.later, code)
        if rules.whole
        else obvody.rules_path(c.later, code)
    )
    origin = {
        "okrsky_reused": None,
        "okrsky_adoption": None,
        "okrsky_referendum": None,
        "okrsky_supplement": None,
        **marks,
    }
    if current is None:
        copy = dataclasses.replace(rules, **origin)
        path = obvody.okrsky_path(c.curated, code)
        header = [f"The okrsky of {rules.name} of the elections of {c.latest.day}"]
    else:
        copy = dataclasses.replace(
            current,
            okrsky=rules.okrsky,
            okrsok_rules=rules.okrsok_rules,
            okrsky_fill=rules.okrsky_fill,
            okrsky_date=rules.okrsky_date,
            okrsky_dating=rules.okrsky_dating,
            addressless=rules.addressless,
            **origin,
        )
        path = obvody.rules_path(c.curated, code)
        header = [
            *okrsokrules.obvod_header(path),
            f"{okrsokrules.ADDED} `ems job reuse`: those of the elections of"
            f" {c.latest.day}",
        ]
    p = c.places(code)
    a = obvody.assign(copy, p.places, p.kus, p.planar())
    problems = _okrsok_fit(c.cfg, copy, p, a)
    if problems:
        return f"not reused: on the addresses of {c.election.day}: {problems[0]}"
    header[-1] += f", {source.relative_to(c.cfg.root)}, reused by `ems job reuse`."
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obvody.dump(copy, header), encoding="utf-8")
    return f"reused, {path.relative_to(c.cfg.root)}"


def _layout_problem(c: _Context, code: str, rules: obvody.RuleSet) -> str | None:
    """Return why the okrsky of *rules* may not stand for the earlier election's.

    They must be those ŠÚ SR counted in each obvod then, each with voters
    on the roll within :data:`TOLERANCE` of the earlier count.
    """
    units = c.units.get(code, {})
    if not units:
        return f"ŠÚ SR's okrsky of {c.election.day} unknown"
    given = {n: list(ks) for n, ks in rules.okrsky.items()}
    official = {n: list(k) for n, k in units.items()}
    if given != official:
        return f"okrsky per obvod {_okrsky_text(given)}, then {_okrsky_text(official)}"
    later = _flat(c.later_units.get(code, {}))
    return _implausible(c, _flat(units), later)


def _implausible(
    c: _Context, then: Mapping[int, int], now: Mapping[int, int]
) -> str | None:
    """Return the first okrsok whose voters *now* are off those *then*, if one."""
    for k, before in then.items():
        after = now.get(k)
        if after is None:
            return f"okrsok {k}: voters of {c.latest.day} unknown"
        if abs(after - before) > TOLERANCE * before:
            return (
                f"okrsok {k}: {before:,} voters then, {after:,} in {c.latest.day.year}"
            )
    return None


def _flat(units: Mapping[int, Mapping[int, int]]) -> dict[int, int]:
    """Return okrsok → voters of ŠÚ SR's okrsky by obvod *units*."""
    return {k: v for ks in units.values() for k, v in ks.items()}


def _okrsok_fit(
    cfg: Config, rules: obvody.RuleSet, p: obvody.ObecPlaces, a: obvody.Assignment
) -> list[str]:
    """Return why the okrsky of *rules* do not fit the addresses *p* (obvody *a*)."""
    if not rules.okrsok_areas:
        return []
    k, problems = okrsokrules.okrsok_problems(rules, p, a.units)
    if problems:
        return problems
    return okrsokrules.draw(cfg, rules, p, a, k)[1]


@dataclasses.dataclass(frozen=True)
class _Voted:
    """What one obec voted in, in a vote other than a regular election."""

    code: str
    count: int
    """Its okrsky in the vote's territorial division."""
    voters: Mapping[int, int]
    """Okrsok → voters on the roll, of those that voted, where the results
    have them (:func:`election_map_slovakia.okrsokrules.okrsok_voters`)."""
    grouped: Mapping[int, Mapping[int, int]]
    """A by-election's council contests: obvod → okrsok → voters, of the
    obvody that voted (:func:`election_map_slovakia.obvodrules.official_okrsky`)."""
    searched: bool
    """Whether its own document was searched for and not found."""
    whole_only: bool = False
    """Whether only okrsky of the whole obec fit: a by-election electing
    councils elsewhere but none here, so that a council rule set would be
    taken for its council's (``ems addresses`` checks it against the contests)."""


def sources(cfg: Config, election: Election) -> list[Election]:
    """Return the regular elections *election* may copy okrsky from, in order.

    Nearest in time first; for a by-election only those before it: it fills
    seats of the council elected then, and a later one's obvody are another
    council's.
    """
    return sorted(
        (
            e
            for e in cfg.elections
            if e.kind == REGULAR
            and (election.kind != BY_ELECTION or e.day < election.day)
        ),
        key=lambda e: abs((e.day - election.day).days),
    )


def _run_other(cfg: Config, election: Election) -> list[str]:
    """Copy the okrsky of the regular elections where *election*, of another kind, has none.

    For each obec it voted in, in several okrsky (its ``units``), without
    okrsky or a rule set yet, or with a stand-in, the okrsky of the first of
    :func:`sources` that proves them the same (:func:`_okrsky_problem`), or
    else of the next; in a by-election, failing that, the council obvody
    alone (:func:`_obvody_problem`). See the module doc.
    """
    regular = sources(cfg, election)
    curated = cfg.election_dir(election)
    data = obvodrules.candidate_data(cfg, election)
    names = {o["code"]: o["name"] for o in data["obce"]}
    voting = okrsokrules.held(election, data)
    voters = okrsokrules.okrsok_voters(cfg, election)
    grouped = obvodrules.official_okrsky(cfg, election)
    not_found = okrsokrules.load_not_found(cfg, election)
    councils = {str(c["area"]) for c in data["contests"] if c["kind"] == "oz"}
    units = {s.day: obvodrules.official_okrsky(cfg, s) for s in regular}
    lines = []
    for code, count in sorted(okrsokrules.okrsok_counts(cfg, election).items()):
        current = obvody.load_obec(curated, code)
        if (
            count < _SEVERAL
            or (voting is not None and code not in voting)
            or (
                current is not None
                and not (current.adoption or current.okrsky_adoption)
            )
        ):
            continue
        voted = _Voted(
            code,
            count,
            voters.get(code, {}),
            grouped.get(code, {}),
            code in not_found,
            whole_only=bool(councils) and code not in councils,
        )
        tried = []
        for s in regular:
            done, said = _copy_from(
                cfg,
                election,
                voted,
                s,
                obvody.load_obec(cfg.election_dir(s), code),
                units[s.day].get(code, {}),
            )
            tried.append(said if done else f"{s.day}: {said}")
            if done:
                break
        else:
            tried.insert(0, "not reused")
        lines.append(f"{names.get(code, code)} ({code}), okrsky: {'; '.join(tried)}")
    return lines


def _copy_from(
    cfg: Config,
    election: Election,
    voted: _Voted,
    source: Election,
    rules: obvody.RuleSet | None,
    later: Mapping[int, Mapping[int, int]],
) -> tuple[bool, str]:
    """Copy *source*'s rules of an obec, *rules*, where they fit; say what was done.

    *later* is ŠÚ SR's okrsky of the obec in *source* by obvod, with their
    voters. Returns whether they were copied, and the report: what was
    written, or why not.
    """
    if rules is None:
        return False, "no okrsky"
    if voted.whole_only and not rules.whole:
        return False, "okrsky by council obvod, the vote electing no council there"
    # Okrsky transcribed, for the regular election, from this referendum's
    # own document are its own.
    own = rules.okrsky_referendum == election.day
    why = _okrsky_problem(rules, voted, _flat(later), source, own=own)
    if why is None:
        how = OWN if own else OKRSKY
    elif voted.grouped and not rules.whole:
        # A council by-election draws its obvody, okrsky or not.
        obvody_why = _obvody_problem(rules, voted.grouped, later, source)
        if obvody_why is not None:
            return False, f"{why}; obvody: {obvody_why}"
        how = OBVODY
    else:
        return False, why
    copy, problem = _copy_of(cfg, election, voted, source, rules, how)
    if problem is not None:
        return False, problem
    return True, f"{_COPIED[how]}, {copy.relative_to(cfg.root)}"


OWN = "own"
"""What :func:`_copy_of` copies, besides :data:`OBVODY` and :data:`OKRSKY`:
okrsky of the vote's own document, transcribed for another election."""
_COPIED = {
    OKRSKY: "reused",
    OWN: "its own, from the referendum's document",
    OBVODY: "council obvody reused, without okrsky",
}
"""How the report says what :func:`_copy_of` copied."""


def _okrsky_problem(
    rules: obvody.RuleSet,
    voted: _Voted,
    later: Mapping[int, int],
    source: Election,
    *,
    own: bool = False,
) -> str | None:
    """Return why *source*'s okrsky *rules* may not stand for those *voted* in.

    *later* is each okrsok's voters in *source*. They must place every
    address, be numbered 1..N for the N okrsky of the territorial
    division, give each council obvod that voted (a by-election's) the
    okrsky that voted in it, and each okrsok that voted must have voters
    on the roll within :data:`TOLERANCE` of its count in *source*; unless
    they are the vote's *own*, from its document, whose voters prove
    nothing more.
    """
    if rules.adoption or rules.okrsky_adoption:
        return "its okrsky are a stand-in, not proven to match"
    if not rules.okrsok_areas:
        return "its okrsky do not place the addresses"
    shape = _shape_problem(rules, voted.count, voted.grouped)
    if shape or own:
        return shape
    return _okrsok_voters_problem(voted.voters, later, source)


def _shape_problem(
    rules: obvody.RuleSet, count: int, grouped: Mapping[int, Mapping[int, int]]
) -> str | None:
    """Return why the okrsky of *rules* are not those of a vote, if they are not.

    They must be numbered 1..*count*, the okrsky of its territorial
    division, each council obvod of *grouped* (obvod → okrsok → voters)
    with its okrsky.
    """
    numbers = sorted(k for ks in rules.okrsky.values() for k in ks)
    official = list(range(1, count + 1))
    if numbers != official:
        return f"okrsky {_numbers(numbers)}, then {_numbers(official)}"
    for n, ks in grouped.items():
        mine = sorted(rules.okrsky.get(n, ()))
        if mine != sorted(ks):
            return f"obvod {n}: okrsky {_numbers(mine)}, then {_numbers(sorted(ks))}"
    return None


def _okrsok_voters_problem(
    then: Mapping[int, int], later: Mapping[int, int], source: Election
) -> str | None:
    """Return the first okrsok voted in whose voters *then* are off *later*'s.

    *later* are the okrsky's voters in *source*; within :data:`TOLERANCE`.
    """
    if not then:
        return "the voters per okrsok unknown (no results per okrsok): not proven"
    for k, before in then.items():
        after = later.get(k)
        if after is None:
            return f"okrsok {k}: voters unknown"
        if abs(after - before) > TOLERANCE * before:
            return f"okrsok {k}: {before:,} voters then, {after:,} in {source.day.year}"
    return None


def _obvody_problem(
    rules: obvody.RuleSet,
    grouped: Mapping[int, Mapping[int, int]],
    later: Mapping[int, Mapping[int, int]],
    source: Election,
) -> str | None:
    """Return why *source*'s council rule set *rules* may not draw a by-election's obvody.

    *grouped* and *later* are ŠÚ SR's okrsky by obvod, with their voters,
    of the obvody that voted in the by-election and of *source*. Each obvod
    that voted must be one of the rule set, with voters on the roll within
    :data:`TOLERANCE` of its count in *source*.
    """
    if rules.adoption:
        return "its obvody are a stand-in, not proven to match"
    for n, ks in grouped.items():
        if n not in rules.seats:
            return f"obvod {n}: not one of its obvody"
        before, after = sum(ks.values()), sum(later.get(n, {}).values())
        if not after:
            return f"obvod {n}: voters unknown"
        if abs(after - before) > TOLERANCE * before:
            return f"obvod {n}: {before:,} voters then, {after:,} in {source.day.year}"
    return None


def _copy_of(
    cfg: Config,
    election: Election,
    voted: _Voted,
    source: Election,
    rules: obvody.RuleSet,
    how: str,
) -> tuple[Path, str | None]:
    """Write *how* much of *source*'s *rules* of an obec for *election*.

    :data:`OKRSKY`, the okrsky marked ``okrsky_reused``; :data:`OWN`, the
    okrsky as the vote's own; :data:`OBVODY`, the council obvody alone. A
    council rule set comes along marked ``reused``, its rules having lost
    their supplement marks (the header keeping the source file's). Returns
    the file, and why it could not be written: the copy does not fit the
    election's addresses.
    """
    code = voted.code
    searched = (
        f"No document of {election.day} was found (okrsky/not-found.json)."
        if voted.searched
        else f"No document of {election.day} was searched for."
    )
    within = f"voters on the roll within {TOLERANCE:.0%} of its count then"
    if how == OBVODY:
        proof = (
            f"the council obvody of the elections of {source.day}: in"
            f" {election.day} each obvod that voted had {within}"
        )
    else:
        proof = (
            f"the okrsky of the elections of {source.day}: in {election.day}"
            f" the obec had as many okrsky, each that voted with {within}"
        )
    note = f"These are {proof}. {searched}"
    if how == OWN:
        note = (
            f"These okrsky were transcribed for the elections of {source.day}"
            f" from the municipality's document for the referendum of"
            f" {election.day}: they are the referendum's own."
        )
        copy = dataclasses.replace(rules, okrsky_referendum=None)
    elif how == OKRSKY:
        # A copy is another vote's okrsky as a whole: what of them came from a
        # later source there is said in the source file, whose header it keeps.
        copy = dataclasses.replace(
            rules,
            okrsky_reused=source.day,
            okrsky_referendum=None,
            okrsky_supplement=None,
            okrsok_rules=_unmarked(rules.okrsok_rules),
        )
    else:
        copy = dataclasses.replace(
            rules,
            okrsky={},
            okrsok_rules=(),
            okrsky_fill=False,
            okrsky_date=None,
            okrsky_note=None,
            okrsky_reused=None,
            okrsky_adoption=None,
            okrsky_referendum=None,
            okrsky_dating=None,
            okrsky_supplement=None,
            addressless=(),
        )
    if how != OBVODY:
        copy = dataclasses.replace(
            copy, okrsky_note=" ".join(filter(None, (note, rules.okrsky_note)))
        )
    if not rules.whole:
        # The council obvody only place the okrsky where the vote elects
        # none of the council; a by-election's council contest needs them.
        council = f"The council obvody of the elections of {source.day}."
        copy = dataclasses.replace(
            copy,
            reused=source.day,
            note=" ".join(
                filter(None, (note if how == OBVODY else council, rules.note))
            ),
            supplement=None,
            rules=_unmarked(rules.rules),
        )
    places = obvodrules.places_dir(cfg, election) / f"{code}.json"
    if not places.is_file():
        raise jobs.JobError(f"{places} missing; run `ems addresses` first")
    p = obvody.load_places(places)
    a = obvody.assign(copy, p.places, p.kus, p.planar())
    problems = a.problems(p.places) or _okrsok_fit(cfg, copy, p, a)
    curated, origin = cfg.election_dir(election), cfg.election_dir(source)
    where = obvody.okrsky_path if rules.whole else obvody.rules_path
    path, source_path = where(curated, code), where(origin, code)
    if problems:
        return path, f"on the addresses of {election.day}: {problems[0]}"
    what = "council obvody" if how == OBVODY else "okrsky"
    header = [
        f"The {what} of {rules.name} of the elections of {source.day},"
        f" {source_path.relative_to(cfg.root)}, copied by `ems job reuse`"
        f" ({_COPIED[how]}). Its header there:",
        *(f"  {h}" for h in okrsokrules.header(source_path)),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obvody.dump(copy, header), encoding="utf-8")
    return path, None


class Vote:
    """One vote's units by obec, as ŠÚ SR counted them, each read when first needed."""

    def __init__(self, cfg: Config, election: Election) -> None:
        """Read nothing yet: most votes are asked for little, their results slow to read."""
        self.cfg = cfg
        self.election = election
        self.curated = cfg.election_dir(election)

    @functools.cached_property
    def data(self) -> dict[str, Any]:
        """Return its ``candidates.json``."""
        return obvodrules.candidate_data(self.cfg, self.election)

    @functools.cached_property
    def counts(self) -> dict[str, int]:
        """Return obec → its okrsky in the territorial division."""
        return okrsokrules.okrsok_counts(self.cfg, self.election)

    @functools.cached_property
    def council(self) -> dict[str, dict[int, int | None]]:
        """Return obec → council obvod contested → its seats, None where not given."""
        seats = obvodrules.contest_seats(self.data)
        out: dict[str, dict[int, int | None]] = {}
        for contest in self.data["contests"]:
            kind, _, area = contest["id"].partition(":")
            obec, _, n = area.partition("/")
            if kind == "oz" and n:
                out.setdefault(obec, {})[int(n)] = seats.get(contest["id"])
        return {obec: dict(sorted(s.items())) for obec, s in out.items()}

    @functools.cached_property
    def grouped(self) -> obvodrules.Okrsky:
        """Return obec → council obvod → okrsok → voters on the roll."""
        return obvodrules.official_okrsky(self.cfg, self.election)

    @functools.cached_property
    def voters(self) -> dict[str, dict[int, int]]:
        """Return obec → okrsok → voters on the roll, of the okrsok files."""
        return okrsokrules.okrsok_voters(self.cfg, self.election)

    def okrsok_voters(self, code: str) -> dict[int, int]:
        """Return okrsok → voters on the roll of obec *code*, where known."""
        return _flat(self.grouped.get(code, {})) | self.voters.get(code, {})

    def obvod_voters(self, code: str) -> dict[int, int]:
        """Return council obvod → voters on the roll of obec *code*, where known."""
        return {n: sum(ks.values()) for n, ks in self.grouped.get(code, {}).items()}


@dataclasses.dataclass(frozen=True)
class _Target:
    """An obec of the vote that another's units stand in for: what they must fit."""

    code: str
    name: str
    count: int
    """Its okrsky in the vote's territorial division."""
    council: Mapping[int, int | None]
    """Its council obvody contested → seats (None where not given); empty
    where the vote elects none of its council."""
    several: bool
    """Whether the council it elects has several obvody (a council rule set)."""
    whole_only: bool
    """Whether, without *several*, only okrsky of the whole obec (an okrsky
    file) fit: the vote elects its council in one obvod, or elects councils
    elsewhere but none here, so a council rule set would be taken for its
    council's (``ems addresses`` checks it against the contests)."""
    grouped: Mapping[int, Mapping[int, int]]
    """Where *several*: ŠÚ SR's okrsky by council obvod that voted, with
    their voters."""
    voters: Mapping[int, int]
    """Okrsok → voters on the roll, where known."""
    obvod_voters: Mapping[int, int]
    """Council obvod → voters on the roll, where known."""


@dataclasses.dataclass(frozen=True)
class _Tried:
    """How far one source got (:data:`_NONE` … :data:`_DONE`), and what it says."""

    stage: int
    said: str


_NONE, _SHAPE, _VOTERS, _ADDRESSES, _DONE = range(5)
"""How far a source got: no units of its own, not of the same structure,
voters too far apart, not fitting the addresses; standing in."""
_UNKNOWN = {
    _NONE: "no other vote has them of its own",
    _SHAPE: "no source fits structurally",
    _VOTERS: "the voters differ too much from every fitting source's",
    _ADDRESSES: "no fitting source fits the addresses",
}
"""Why units stay unknown, by the furthest stage a source got to."""
_NO_COUNCIL = "its council obvody are unknown"
"""Why the okrsky of an obec with several council obvody stay unknown
where the obvody do."""


def stand_in(
    cfg: Config, election: Election, votes: Mapping[dt.date, Vote]
) -> list[str]:
    """Let other votes' units stand in where *election* has none; return report lines.

    *votes* are every vote by day. The council obvody of each obec first
    (:func:`_stand_in_obvody`), then its okrsky (:func:`_stand_in_okrsky`),
    each where it has none of its own or a stand-in, which is chosen anew
    (and withdrawn where none fits any more); the report ends with the
    counts. See the module doc.
    """
    vote = votes[election.day]
    term = cfg.term(election)
    names = {o["code"]: o["name"] for o in vote.data["obce"]}
    voting = okrsokrules.held(election, vote.data)
    by_obvody = obvodrules.load_not_found(cfg, election)
    by_okrsky = okrsokrules.load_not_found(cfg, election)
    if election.kind == BY_ELECTION:
        obvod_sources = [votes[term.day]] if term else []
    else:
        regular = [e for e in cfg.elections if e.kind == REGULAR and e != election]
        obvod_sources = [votes[e.day] for e in _nearest(election, regular)]
    others = [e for e in cfg.elections if e != election]
    okrsok_sources = [votes[e.day] for e in _nearest(election, others)]
    lines = []
    tally: Counter[tuple[str, str]] = Counter()
    codes = (vote.council.keys() | vote.counts.keys()) - candidates.CITY_CODES
    for code in sorted(codes):
        if voting is not None and code not in voting:
            continue
        term_vote = votes[term.day] if term else None
        t = _target(vote, term_vote, code, names.get(code, code))
        current = obvody.load_obec(vote.curated, code)
        along = False
        if t.several and (current is None or current.adoption):
            source, said = _stand_in_obvody(
                cfg,
                election,
                t,
                obvod_sources,
                _missing(election, OBVODY, by_obvody.get(code), None),
            )
            if source is None and current is not None:
                said += _withdraw(cfg, election, t, current, OBVODY)
            lines.append(f"{t.name} ({code}), obvody: {said}")
            tally[OBVODY, _counted(source, said)] += 1
            current = obvody.load_obec(vote.curated, code)
            along = source is not None and current is not None and current.okrsok_areas
        if t.count < _SEVERAL or along:
            continue
        if current is not None and current.okrsok_areas and not current.okrsky_adoption:
            continue
        if t.several and (current is None or current.whole):
            lines.append(f"{t.name} ({code}), okrsky: unknown: {_NO_COUNCIL}")
            tally[OKRSKY, _NO_COUNCIL] += 1
            continue
        missing = _missing(election, OKRSKY, by_okrsky.get(code), current)
        source, said = _stand_in_okrsky(
            cfg, election, t, current if t.several else None, okrsok_sources, missing
        )
        if source is None and current is not None and current.okrsky_adoption:
            said += _withdraw(cfg, election, t, current, OKRSKY)
        lines.append(f"{t.name} ({code}), okrsky: {said}")
        tally[OKRSKY, _counted(source, said)] += 1
    return lines + _summary(election, tally)


def _nearest(election: Election, others: Sequence[Election]) -> list[Election]:
    """Return *others* by distance in time from *election*, either way.

    Of two as near, the later first: the owner's choice, as a later vote's
    units carry the changes made since the earlier one.
    """
    return sorted(
        others, key=lambda e: (abs((e.day - election.day).days), -e.day.toordinal())
    )


def _target(vote: Vote, term: Vote | None, code: str, name: str) -> _Target:
    """Return obec *code* of *vote* as a target; *term*: a by-election's regular election."""
    council = vote.council.get(code, {})
    # A by-election fills seats of the council elected in its term's obvody.
    obvody_of = term.council.get(code, {}) if term else council
    several = bool(council) and len(obvody_of) >= _SEVERAL
    return _Target(
        code,
        name,
        vote.counts.get(code, 0),
        council,
        several,
        not several and bool(council or vote.council),
        vote.grouped.get(code, {}) if several else {},
        vote.okrsok_voters(code),
        vote.obvod_voters(code),
    )


def _missing(
    election: Election,
    units: str,
    entry: Mapping[str, Any] | None,
    current: obvody.RuleSet | None,
) -> str:
    """Return why *election* has no *units* of its own, from its not-found *entry*."""
    if entry is not None:
        note = entry.get("note")
        said = f": {note.rstrip('.')}." if note else "."
        return f"No document of {election.day} setting the {units} was found ({entry.get('job')}){said}"
    if current is not None and current.okrsky and not current.okrsky_adoption:
        return f"The documents of {election.day} do not place the addresses in {units}."
    return f"No document of {election.day} placing the addresses in {units} is known."


def _search(
    sources: Sequence[Vote], attempt: Callable[[Vote, Sequence[str]], _Tried]
) -> tuple[Election | None, str]:
    """Try *sources* in order until one stands in; return it and the report.

    *attempt* tries one, given what the nearer ones that had units of
    their own said; the report says what stood in, or why none did.
    """
    nearer: list[str] = []
    furthest = _NONE
    for s in sources:
        tried = attempt(s, nearer)
        if tried.stage == _DONE:
            return s.election, tried.said
        if tried.stage > _NONE:
            nearer.append(f"{s.election.day}: {tried.said}")
        furthest = max(furthest, tried.stage)
    tried_said = f" ({'; '.join(nearer)})" if nearer else ""
    return None, f"unknown: {_UNKNOWN[furthest]}{tried_said}"


def _stand_in_obvody(
    cfg: Config,
    election: Election,
    t: _Target,
    sources: Sequence[Vote],
    missing: str,
) -> tuple[Election | None, str]:
    """Write the first council rule set of *sources* that fits obec *t*; report it.

    *missing* says why there is none of its own. Its okrsky come along
    where they fit too, else each obvod gets ŠÚ SR's okrsky without rules.
    A by-election's one source, its term, may give a rule set that is
    another vote's itself: it fills seats of the council elected in those
    obvody, however that election draws them.
    """
    by_election = election.kind == BY_ELECTION

    def attempt(s: Vote, nearer: Sequence[str]) -> _Tried:
        source = s.election
        rules = obvody.load_obec(s.curated, t.code)
        if rules is None or rules.whole:
            return _Tried(_NONE, "no council rule set")
        if (rules.reused or rules.adoption) and not by_election:
            return _Tried(_NONE, "its council rule set is another vote's")
        # The vote whose borders the term's rule set draws, where not its own.
        origin = rules.adoption.day if rules.adoption else rules.reused
        shape = _council_problem(rules.seats, t.council, part=by_election)
        if shape:
            return _Tried(_SHAPE, shape)
        off = _off("obvod", t.obvod_voters, s.obvod_voters(t.code), source)
        if off:
            return _Tried(_VOTERS, off)
        if origin:
            how = "proven the same" if rules.reused else "standing in"
            whose = (
                f"These are the council obvody of the council elected on"
                f" {source.day} ({source.slug}), whose seats the by-election"
                f" fills, as that election draws them: with those of the vote"
                f" of {origin}, {how} there."
            )
        else:
            fit = (
                "the obvody that voted, of the council elected then"
                if by_election
                else "the same obvody and seats"
            )
            whose = (
                f"These are the council obvody of the vote of {source.day}"
                f" ({source.slug}), the nearest in time with a rule set of its"
                f" own of {fit}{_not_taken(nearer)}."
            )
        basis = " ".join(
            (
                missing,
                whose,
                _voters_said(
                    "obvod", t.obvod_voters, s.obvod_voters(t.code), election, source
                ),
            )
        )
        copy = dataclasses.replace(
            rules,
            reused=None,
            adoption=obvody.Adoption(origin or source.day, basis),
            supplement=None,
            rules=_unmarked(rules.rules),
            okrsky_reused=None,
            okrsky_referendum=None,
            okrsky_supplement=None,
            okrsok_rules=_unmarked(rules.okrsok_rules),
        )
        p = _places(cfg, election, t.code)
        a = obvody.assign(copy, p.places, p.kus, p.planar())
        problems = addresses.check_assignment(
            copy, list(t.council), p, a, part=by_election
        )
        if problems:
            return _Tried(
                _ADDRESSES, f"on the addresses of {election.day}: {problems[0]}"
            )
        own = okrsokrules.own(rules) and rules.okrsok_areas
        copy = _okrsky_along(cfg, election, t, s, copy, p, a, own=own)
        path = obvody.rules_path(cfg.election_dir(election), t.code)
        _write(cfg, source, path, copy, "council obvody")
        return _Tried(
            _DONE, f"from {source.day} ({source.slug}), {path.relative_to(cfg.root)}"
        )

    return _search(sources, attempt)


def _council_problem(
    seats: Mapping[int, int], council: Mapping[int, int | None], *, part: bool
) -> str | None:
    """Return why obvody of *seats* (obvod → seats) are not the contests' *council*.

    The same obvody with the same seats where they are given, or, for a
    by-election electing *part* of the council, among them with no more.
    """
    if not part and list(seats) != list(council):
        return f"obvody {_numbers(list(seats))}, then {_numbers(list(council))}"
    for n, then in council.items():
        if n not in seats:
            return f"obvod {n}: not one of its obvody"
        if then is not None and (then > seats[n] if part else then != seats[n]):
            return f"obvod {n}: {seats[n]} seats, then {then}"
    return None


def _okrsky_along(
    cfg: Config,
    election: Election,
    t: _Target,
    s: Vote,
    copy: obvody.RuleSet,
    p: obvody.ObecPlaces,
    a: obvody.Assignment,
    *,
    own: bool,
) -> obvody.RuleSet:
    """Return the council rule set *copy* of *s* with the okrsky it can draw.

    Its okrsky, where they are *own* (not another vote's) and fit obec *t*
    as the okrsky that stand in must (:func:`_stand_in_okrsky`), else ŠÚ
    SR's of the obvody (none where not known for each), drawn where each
    obvod has one.
    """
    source = s.election
    voters = s.okrsok_voters(t.code)
    if (
        own
        and not _shape_problem(copy, t.count, t.grouped)
        and not _off("okrsok", t.voters, voters, source)
        and not _okrsok_fit(cfg, copy, p, a)
    ):
        basis = (
            f"The okrsky of the same rule set: {t.count} okrsky, those ŠÚ SR counted"
            f" in each obvod. {_voters_said('okrsok', t.voters, voters, election, source)}"
        )
        return dataclasses.replace(
            copy, okrsky_adoption=obvody.Adoption(source.day, basis)
        )
    numbers = {n: tuple(ks) for n, ks in t.grouped.items()}
    complete = list(numbers) == list(copy.seats) and sorted(
        k for ks in numbers.values() for k in ks
    ) == list(range(1, t.count + 1))
    bare = dataclasses.replace(
        copy,
        okrsky=numbers if complete else {},
        okrsok_rules=(),
        okrsky_fill=False,
        okrsky_date=None,
        okrsky_note=None,
        okrsky_dating=None,
        okrsky_adoption=None,
        addressless=(),
    )
    if not bare.okrsok_areas:
        return bare
    basis = (
        f"ŠÚ SR counted one okrsok per obvod in {election.day}, so each is drawn"
        " as its obvod."
    )
    # Each drawn as its obvod, they have the borders of the vote whose obvody stand in.
    day = copy.adoption.day if copy.adoption else source.day
    return dataclasses.replace(bare, okrsky_adoption=obvody.Adoption(day, basis))


def _stand_in_okrsky(
    cfg: Config,
    election: Election,
    t: _Target,
    into: obvody.RuleSet | None,
    sources: Sequence[Vote],
    missing: str,
) -> tuple[Election | None, str]:
    """Write the first okrsky of *sources* that fit obec *t*; report it.

    Where the vote elects its council in several obvody, *into* its
    council rule set, from one with the same obvody; in one obvod, an
    okrsky file; else either (a rule set's obvody then only place them).
    *missing* says why there are none of its own.
    """

    def attempt(s: Vote, nearer: Sequence[str]) -> _Tried:
        source = s.election
        rules = obvody.load_obec(s.curated, t.code)
        if rules is None or not okrsokrules.own(rules) or not rules.okrsok_areas:
            return _Tried(_NONE, "no okrsky of its own that place the addresses")
        shape = _kind_problem(rules, t, into) or _shape_problem(
            rules, t.count, t.grouped
        )
        if shape:
            return _Tried(_SHAPE, shape)
        voters = s.okrsok_voters(t.code)
        off = _off("okrsok", t.voters, voters, source)
        if off:
            return _Tried(_VOTERS, off)
        fit = f"{t.count} okrsky" + (
            ", those ŠÚ SR counted in each council obvod" if t.grouped else ""
        )
        basis = " ".join(
            (
                missing,
                f"These are the okrsky of the vote of {source.day} ({source.slug}),"
                f" the nearest in time with okrsky of its own that fit: {fit}"
                f"{_not_taken(nearer)}.",
                _voters_said("okrsok", t.voters, voters, election, source),
            )
        )
        copy = _okrsky_copy(rules, into, source, obvody.Adoption(source.day, basis))
        p = _places(cfg, election, t.code)
        a = obvody.assign(copy, p.places, p.kus, p.planar())
        problems = a.problems(p.places) or _okrsok_fit(cfg, copy, p, a)
        if problems:
            return _Tried(
                _ADDRESSES, f"on the addresses of {election.day}: {problems[0]}"
            )
        path = _write_okrsky(cfg, election, source, copy, into=into is not None)
        return _Tried(
            _DONE, f"from {source.day} ({source.slug}), {path.relative_to(cfg.root)}"
        )

    return _search(sources, attempt)


def _kind_problem(
    rules: obvody.RuleSet, t: _Target, into: obvody.RuleSet | None
) -> str | None:
    """Return why okrsky *rules* are not of the kind obec *t* needs, if not.

    Into a council rule set *into*, okrsky of one with the same obvody;
    where only an okrsky file fits (:attr:`_Target.whole_only`), one.
    """
    if into is not None:
        if rules.whole:
            return (
                "okrsky of the whole obec, the council then elected in several obvody"
            )
        if list(rules.seats) != list(into.seats):
            given, then = list(rules.seats), list(into.seats)
            return f"council obvody {_numbers(given)}, then {_numbers(then)}"
    elif t.whole_only and not rules.whole:
        if t.council:
            return "okrsky by council obvod, the council then elected in one"
        return "okrsky by council obvod, the vote electing no council there"
    return None


def _okrsky_copy(
    rules: obvody.RuleSet,
    into: obvody.RuleSet | None,
    source: Election,
    adoption: obvody.Adoption,
) -> obvody.RuleSet:
    """Return the okrsky *rules* of *source* standing in, by *adoption*.

    In the council rule set *into*, else as they are, a rule set's council
    obvody marked ``reused``: where the vote elects none there, they only
    place the okrsky.
    """
    marks = {
        "okrsok_rules": _unmarked(rules.okrsok_rules),
        "okrsky_reused": None,
        "okrsky_referendum": None,
        "okrsky_supplement": None,
        "okrsky_adoption": adoption,
    }
    if into is not None:
        return dataclasses.replace(
            into,
            okrsky=rules.okrsky,
            okrsky_fill=rules.okrsky_fill,
            okrsky_date=rules.okrsky_date,
            okrsky_note=rules.okrsky_note,
            okrsky_dating=rules.okrsky_dating,
            addressless=rules.addressless,
            **marks,
        )
    copy = dataclasses.replace(rules, **marks)
    if rules.whole:
        return copy
    note = (
        f"The council obvody of the vote of {source.day}: they only place the okrsky."
    )
    return dataclasses.replace(
        copy,
        reused=source.day,
        note=" ".join(filter(None, (note, rules.note))),
        supplement=None,
        rules=_unmarked(rules.rules),
    )


def _write_okrsky(
    cfg: Config,
    election: Election,
    source: Election,
    copy: obvody.RuleSet,
    *,
    into: bool,
) -> Path:
    """Write the okrsky *copy* of *source* standing in for *election*; return its file.

    *into* the vote's council rule set, else as a file of their own, which
    replaces the obec's other file, if one: an obec's okrsky are in one.
    """
    curated = cfg.election_dir(election)
    path = (obvody.okrsky_path if copy.whole else obvody.rules_path)(curated, copy.obec)
    if not into:
        for other in (
            obvody.okrsky_path(curated, copy.obec),
            obvody.rules_path(curated, copy.obec),
        ):
            if other != path:
                other.unlink(missing_ok=True)
    _write(cfg, source, path, copy, "okrsky", into=into)
    return path


def _write(
    cfg: Config,
    source: Election,
    path: Path,
    copy: obvody.RuleSet,
    what: str,
    *,
    into: bool = False,
) -> None:
    """Write *copy*, *what* of *source* standing in, to *path*.

    The header quotes the source file's; okrsky *into* a council rule set
    of the vote's own keep its header, saying where they come from.
    """
    where = obvody.okrsky_path if copy.whole else obvody.rules_path
    source_path = where(cfg.election_dir(source), copy.obec).relative_to(cfg.root)
    if into:
        header = [
            *okrsokrules.obvod_header(path),
            f"{okrsokrules.ADDED} `ems job reuse`: those of the vote of {source.day},"
            f" {source_path}, standing in.",
        ]
    else:
        header = [
            f"The {what} of {copy.name} of the vote of {source.day}, {source_path},"
            " standing in, by `ems job reuse`. Its header there:",
            *(f"  {h}" for h in okrsokrules.header(cfg.root / source_path)),
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obvody.dump(copy, header), encoding="utf-8")


def _withdraw(
    cfg: Config, election: Election, t: _Target, current: obvody.RuleSet, units: str
) -> str:
    """Remove the stand-in *units* of obec *t*, which none fits any more; say so.

    A stand-in's file goes; okrsky in a council rule set of the vote's
    own leave it without okrsky.
    """
    curated = cfg.election_dir(election)
    path = (obvody.okrsky_path if current.whole else obvody.rules_path)(curated, t.code)
    if units == OBVODY or not t.several or current.adoption:
        path.unlink()
    else:
        bare = dataclasses.replace(
            current,
            okrsky={},
            okrsok_rules=(),
            okrsky_fill=False,
            okrsky_date=None,
            okrsky_note=None,
            okrsky_dating=None,
            okrsky_adoption=None,
            addressless=(),
        )
        path.write_text(
            obvody.dump(bare, okrsokrules.obvod_header(path)), encoding="utf-8"
        )
    return f"; the stand-in before, {path.relative_to(cfg.root)}, withdrawn"


def _places(cfg: Config, election: Election, code: str) -> obvody.ObecPlaces:
    """Return *election*'s addresses of obec *code*, as its rules see them."""
    path = obvodrules.places_dir(cfg, election) / f"{code}.json"
    if not path.is_file():
        raise jobs.JobError(f"{path} missing; run `ems addresses` first")
    return obvody.load_places(path)


def _off(
    unit: str, then: Mapping[int, int], later: Mapping[int, int], source: Election
) -> str | None:
    """Return the first *unit* whose voters *then* are off *later*'s, in *source*.

    Beyond :data:`PLAUSIBLE`, of those known in both votes.
    """
    for k in sorted(then.keys() & later.keys()):
        before, after = then[k], later[k]
        if abs(after - before) > PLAUSIBLE * before:
            return f"{unit} {k}: {before:,} voters then, {after:,} in {source.day}"
    return None


def _voters_said(
    unit: str,
    then: Mapping[int, int],
    later: Mapping[int, int],
    election: Election,
    source: Election,
) -> str:
    """Return the sentence giving each *unit*'s voters on the roll in both votes."""
    known = sorted(then.keys() & later.keys())
    if not known:
        return (
            f"The voters on the roll per {unit} are not known for both votes, so"
            " whether the layout changed is not known either."
        )
    each = ", ".join(f"{k}: {then[k]:,} → {later[k]:,}" for k in known)
    return (
        f"Voters on the roll per {unit} (ŠÚ SR), {election.day} → {source.day}: {each}."
    )


def _not_taken(nearer: Sequence[str]) -> str:
    """Return the clause naming the nearer sources not taken, and why."""
    return f" (nearer, not taken: {'; '.join(nearer)})" if nearer else ""


def _counted(source: Election | None, said: str) -> str:
    """Return what the summary counts a unit under: its source, or why unknown."""
    if source is not None:
        return f"from {source.day}"
    return next(why for why in _UNKNOWN.values() if why in said)


def _summary(election: Election, tally: Counter[tuple[str, str]]) -> list[str]:
    """Return the report's closing lines: stand-ins by source, unknown by reason."""
    lines = []
    for units in (OBVODY, OKRSKY):
        counts = {label: n for (u, label), n in sorted(tally.items()) if u == units}
        done = {k: n for k, n in counts.items() if k.startswith("from ")}
        left = {k: n for k, n in counts.items() if k not in done}
        lines.append(
            f"{election.day} {units}: {sum(done.values())} stand in"
            f" ({_listed(done)}), {sum(left.values())} unknown ({_listed(left)})"
        )
    return lines


def _listed(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{k}: {n}" for k, n in counts.items()) or "none"


def _unmarked(rules: Sequence[obvody.Rule]) -> tuple[obvody.Rule, ...]:
    """Return *rules* none of which is marked as from a later source."""
    return tuple(dataclasses.replace(r, supplemented=False) for r in rules)


def _numbers(numbers: Sequence[int]) -> str:
    """Return *numbers* as a list, runs of three or more as ranges (1–32)."""
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return (
        ", ".join(
            f"{r[0]}–{r[-1]}" if len(r) > _SEVERAL else ", ".join(map(str, r))
            for r in runs
        )
        or "none"
    )


def _note(c: _Context, copied: str) -> str:
    """Return the note of a copy of the latest election's rules, *copied* saying what."""
    return (
        f"No document of the elections of {c.election.day} was found; {copied}"
        f" (each okrsok's voters on the roll within {TOLERANCE:.0%})."
    )


def _seats(seats: Mapping[int, int]) -> str:
    return ", ".join(f"{n}: {s}" for n, s in seats.items()) or "none"


def _okrsky_text(okrsky: Mapping[int, Sequence[int]]) -> str:
    return "; ".join(f"{n}: {', '.join(map(str, ks))}" for n, ks in okrsky.items())
