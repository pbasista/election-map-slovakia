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
  okrsky come along only where each is its obvod (below);
- the okrsky of an obec whose earlier council obvody have a rule set of
  their own: likewise, only where each is its obvod.

What proves okrsky the same is stricter than what proves council obvody.
Voters on the roll per okrsok, however near, do not show which addresses
an okrsok has: a street moved from one to another, or a few years' drift,
stays within any tolerance that lets real votes through. The address
register gives no okrsok, so the addresses per okrsok it gives are those
of the copied rules themselves, no evidence of the vote's own; neither ŠÚ
SR nor the municipalities publish okrsky by address beside the documents
the ``okrsok-rules`` job transcribes. So another vote's okrsky are the
vote's only where its own document says so (a referendum's, below) or
where ŠÚ SR counted one okrsok in each council obvod of the vote, the
okrsky numbered 1..N for the N obvody (:func:`_by_obvod`): each okrsok
then has its obvod's addresses, proven as far as the obvody are. Any
other okrsky, of an earlier regular election or another vote, stand in
(below), marked indicative, never copied as the same.

The copy must also fit the earlier election's addresses as the jobs'
checks demand: every address in exactly one obvod and okrsok, each with
addresses, the okrsky drawable. It is marked ``reused`` (the council rule
set) or ``okrsky_reused`` with the latest election's day and a note saying
why (:mod:`election_map_slovakia.obvody`); the obec stays in the not-found
list, which records the search. Rules naming streets the earlier register
lacks are kept as they are: they select nothing there. A copy is decided
anew on every run, and withdrawn where no longer proven.

Any other vote (a country-wide one, a by-election) elects no council, or
a by-election some of one. For each obec that voted in several okrsky
(its ``units``; of a by-election only the obce with a contest) without
okrsky or a rule set of its own (none, a copy, or a stand-in), the
regular elections nearest in time are tried, nearest first (a
by-election only those before it, newest first: it fills seats of the
council elected then, in that council's obvody), for what they prove:

- okrsky the source transcribed from the document of the vote itself
  (``okrsky_referendum`` of the 2022 elections' rule sets: the 2023
  referendum's) are the vote's own: copied without ``okrsky_reused``,
  with their documents and dating, numbered 1..N for the N territorial
  okrsky of its territorial division, each council obvod that voted with
  its okrsky;
- a by-election proper (``vote`` ``"by"`` of its council contests, not a
  council elected anew: :func:`election_map_slovakia.candidates.new_councils`)
  takes the council rule set, each obvod that voted being one of it with
  voters on the roll within :data:`TOLERANCE` of its count in the source,
  marked ``reused``; its okrsky come along, ``okrsky_reused``, only where
  every obvod voted with one okrsok each (:func:`_by_obvod`).

Nothing else is copied. A council rule set comes along with the okrsky
as a whole, which where the vote elects no council only place them
(``ems geo`` draws them within the whole obec); supplements of the source
lose their marks, the header keeping the source file's, and the note says
whether the vote's own document was searched for. A copy no source
proves any more (``okrsky_reused`` of the rules before) is withdrawn.

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
  the same obvod numbers and seats. A by-election proper's: the obvody
  that voted among them, and only from the regular election of its term,
  before it (a later council's obvody are another council's); it takes
  its term's rule set even where that is another vote's itself (reused,
  or a stand-in there): the council whose seats it fills was elected in
  those obvody, however the term draws them; the copy names the vote
  whose borders they are. A council elected anew (new elections, ``vote``
  ``"new"``) inherits nothing of its term: its obvody are its own
  document's, whose ``obvod-rules`` job asks for them, and until then
  stand in as a regular election's do. Its okrsky come along
  where they fit as below, else each obvod gets those ŠÚ SR counted in it
  without rules (drawn where it has one, which is then the obvod);
- okrsky, of an obec that voted in several: as many as the vote's
  territorial division counts with territory (its special okrsky, which
  have none, left out: :mod:`election_map_slovakia.special`), and where
  the vote elects the council in
  several obvody those ŠÚ SR counted in each, into its council rule set
  from one with the same obvod numbers; where it elects the council in
  one obvod, or councils elsewhere but none there, an okrsky file; a vote
  electing no council at all (a country-wide one) takes either (a rule
  set's council obvody, marked ``reused``, then only place
  the okrsky). They must place every address.

Where the voters on the roll of a unit are known for both votes (ŠÚ SR's
territorial division or the okrsok files; never of a special okrsok, whose
number may be an ordinary okrsok's in the other vote), they must be within
:data:`PLAUSIBLE` of the vote's count: farther apart, the layout clearly
changed. Of an obec of :data:`OUTLIERS_FROM` okrsky or more, one okrsok
(or :data:`OUTLIERS_SHARE` of them, where that is more) may be farther
apart all the same, named with both counts in the basis: in a town one
okrsok's roll changes while the layout holds. That is only where no
source fits with every okrsok within: a source that does wins, however
much further in time. Where the voters are not
known, the units stand in all the same. The copy must fit the vote's
addresses as a reused one must. It is marked ``adopted`` (and
``okrsky_adopted`` where its okrsky are drawn) or
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
    division,
    jobs,
    obvodrules,
    obvody,
    okrsokrules,
    special,
)
from election_map_slovakia.config import BY_ELECTION, REGULAR, Config, Election

TOLERANCE = 0.10
"""How far an okrsok's voters may differ between the elections, as a share
of the earlier count."""
PLAUSIBLE = 0.25
"""How far the voters of an obvod or okrsok that stands in may differ,
likewise: farther apart, the layout clearly changed."""
OUTLIERS_FROM = 10
"""Okrsky an obec must have for some of the okrsky that stand in to be
beyond :data:`PLAUSIBLE`: in a town, one okrsok's roll may change (a new
estate, a hall of residence moved) while the layout holds; in a village
of a few, one changed is the layout changing."""
OUTLIERS_SHARE = 0.05
"""How many of its okrsky may then be beyond :data:`PLAUSIBLE`: one, or
this share of them where that is more."""
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

    A stand-in gives way to them, and an earlier copy is decided anew,
    withdrawn where no longer proven (:func:`_obvody`, :func:`_okrsky`).
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
        rules = current.get(code)
        if rules is None or rules.adoption or rules.reused:
            said = _obvody(c, code, later)
            if rules is not None and rules.reused and not said.startswith(_REUSED):
                said += _withdraw_copy(cfg, election, rules)
            lines.append(f"{entry['name']} ({code}), obvody: {said}")
    current = obvody.load_rule_sets(c.curated)
    later_okrsky = obvody.okrsok_rule_sets(c.later)
    for code, entry in okrsokrules.load_not_found(cfg, election).items():
        rules = current.get(code)
        if (
            rules is None
            or not rules.okrsky
            or rules.okrsky_adoption
            or rules.okrsky_reused
        ):
            said = _okrsky(c, code, rules, later_okrsky.get(code))
            copied = obvody.load_obec(c.curated, code)
            if copied and copied.okrsky_reused and not said.startswith(_REUSED):
                said += _withdraw_copy(cfg, election, copied, keep_obvody=True)
            lines.append(f"{entry['name']} ({code}), okrsky: {said}")
    return lines


_REUSED = "reused"
"""How the report of a copy written begins."""


def _obvody(c: _Context, code: str, later: Mapping[str, obvody.RuleSet]) -> str:
    """Copy the latest council rule set of obec *code* if it fits; say what was done.

    Its okrsky come along only where each is its obvod (:func:`_by_obvod`).
    """
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
    copy = _without_okrsky(
        dataclasses.replace(
            rules,
            reused=c.latest.day,
            note=" ".join(filter(None, (note, rules.note))),
        )
    )
    okrsky = _by_obvod(list(rules.seats), c.units.get(code, {}))
    if okrsky is not None:
        copy = dataclasses.replace(
            copy,
            okrsky=okrsky,
            okrsky_reused=c.latest.day,
            okrsky_note=f"{note} {_BY_OBVOD.format(year=c.election.day.year)}",
        )
    return _write_rule_set(c, code, copy)


def _okrsky(
    c: _Context,
    code: str,
    current: obvody.RuleSet | None,
    rules: obvody.RuleSet | None,
) -> str:
    """Give obec *code* the latest okrsky, *rules*, if proven; say what was done.

    *current* is its council rule set in the earlier election, None if it
    elected its council in one obvod (or has no rule set yet); *rules* the
    latest election's rule set that gives the okrsky, if one. Proven only
    where each okrsok is its council obvod (:func:`_by_obvod`).
    """
    if current is None and len(c.units.get(code, {})) > 1:
        return "not reused: several council obvody but no rule set for them"
    if current is None:
        return f"not reused: {_UNPROVEN}"
    if current.adoption:
        return "not reused: its council obvody are a stand-in"
    if rules is None or rules.whole:
        return f"not reused: no okrsky of {c.latest.day} of the same kind"
    if rules.okrsky_adoption:
        return f"not reused: the okrsky of {c.latest.day} are a stand-in themselves"
    if list(rules.seats) != list(current.seats):
        return "not reused: other obvody"
    why = _layout_problem(c, code, rules)
    if why:
        return f"not reused: {why}"
    okrsky = _by_obvod(list(current.seats), c.units.get(code, {}))
    if okrsky is None:
        return f"not reused: {_UNPROVEN}"
    note = _note(
        c,
        f"these are the okrsky of the elections of {c.latest.day}, the same"
        f" as in {c.election.day.year}",
    )
    marks = {
        "okrsky_reused": c.latest.day,
        "okrsky_note": f"{note} {_BY_OBVOD.format(year=c.election.day.year)}",
    }
    proven = dataclasses.replace(_without_okrsky(rules), okrsky=okrsky)
    return _copy_okrsky(c, code, current, proven, marks)


_UNPROVEN = (
    "no document of the vote and not each okrsok a council obvod: voters on"
    " the roll per okrsok do not show which addresses each has"
)
"""Why another vote's okrsky are not proven the vote's (the module doc)."""
_BY_OBVOD = (
    "ŠÚ SR counted one okrsok in each council obvod in {year}, so each okrsok"
    " is its obvod."
)
"""The note on okrsky proven so (:func:`_by_obvod`)."""


def _by_obvod(
    numbers: Sequence[int], units: Mapping[int, Mapping[int, int]], count: int = 0
) -> dict[int, tuple[int, ...]] | None:
    """Return the okrsky of the council obvody *numbers* where each is its obvod.

    *units* are ŠÚ SR's okrsky by obvod of the vote (obvod → okrsok →
    voters), which must give each obvod one okrsok, numbered 1..N for the
    vote's N okrsky (*count*, else as many as *units* has): each okrsok
    then has its obvod's addresses, whose borders prove it as much as the
    obvody are proven. None otherwise.
    """
    okrsky = {n: tuple(units.get(n, {})) for n in numbers}
    flat = sorted(k for ks in okrsky.values() for k in ks)
    count = count or len(_flat(units))
    if any(len(ks) != 1 for ks in okrsky.values()) or flat != list(range(1, count + 1)):
        return None
    return okrsky


def _without_okrsky(rules: obvody.RuleSet) -> obvody.RuleSet:
    """Return the council rule set *rules* without its okrsky."""
    return dataclasses.replace(
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


def _withdraw_copy(
    cfg: Config, election: Election, rules: obvody.RuleSet, *, keep_obvody: bool = False
) -> str:
    """Remove the copy *rules* of *election* that no source proves any more; say so.

    A copied file goes, but a council rule set whose obvody are of the
    vote's own or still proven (*keep_obvody*) only loses its okrsky. A
    stand-in may then take their place.
    """
    curated = cfg.election_dir(election)
    path = (obvody.okrsky_path if rules.whole else obvody.rules_path)(
        curated, rules.obec
    )
    if rules.whole or (rules.reused and not keep_obvody):
        path.unlink()
    else:
        bare = _without_okrsky(rules)
        path.write_text(
            obvody.dump(bare, okrsokrules.obvod_header(path)), encoding="utf-8"
        )
    return f"; the copy before, {path.relative_to(cfg.root)}, withdrawn"


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
    grouped: Mapping[int, Mapping[int, int]]
    """A by-election's council contests: obvod → okrsok → voters, of the
    obvody that voted (:func:`election_map_slovakia.obvodrules.official_okrsky`)."""
    searched: bool
    """Whether its own document was searched for and not found."""
    whole_only: bool = False
    """Whether only okrsky of the whole obec fit: a by-election electing
    councils elsewhere but none here, so that a council rule set would be
    taken for its council's (``ems addresses`` checks it against the contests)."""
    term: bool = False
    """Whether it is a by-election proper of seats of its term's council,
    whose obvody are the term's (not a council elected anew)."""


def sources(cfg: Config, election: Election) -> list[Election]:
    """Return the regular elections *election* may copy from, in order.

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
    """Copy what the regular elections prove where *election*, of another kind, has nothing.

    For each obec it voted in, in several okrsky (its ``units``), without
    okrsky or a rule set of its own (none, a stand-in, or a copy, decided
    anew), the first of :func:`sources` that proves something
    (:func:`_copy_from`), else the next; a copy no source proves any more is
    withdrawn, for a stand-in to take its place. See the module doc.
    """
    regular = sources(cfg, election)
    curated = cfg.election_dir(election)
    data = obvodrules.candidate_data(cfg, election)
    names = {o["code"]: o["name"] for o in data["obce"]}
    voting = okrsokrules.held(election, data)
    grouped = obvodrules.official_okrsky(cfg, election)
    not_found = okrsokrules.load_not_found(cfg, election)
    councils = {str(c["area"]) for c in data["contests"] if c["kind"] == "oz"}
    new = candidates.new_councils(data["contests"])
    units = {s.day: obvodrules.official_okrsky(cfg, s) for s in regular}
    lines = []
    for code, count in sorted(division.territorial_counts(cfg, election).items()):
        current = obvody.load_obec(curated, code)
        if (
            count < _SEVERAL
            or (voting is not None and code not in voting)
            or (
                current is not None
                and not (
                    current.adoption or current.okrsky_adoption or current.okrsky_reused
                )
            )
        ):
            continue
        voted = _Voted(
            code,
            count,
            grouped.get(code, {}),
            code in not_found,
            whole_only=bool(councils) and code not in councils,
            term=election.kind == BY_ELECTION and code in councils - new,
        )
        refused: dict[str, list[str]] = {}
        said = ""
        for s in regular:
            done, said = _copy_from(
                cfg,
                election,
                voted,
                s,
                obvody.load_obec(cfg.election_dir(s), code),
                units[s.day].get(code, {}),
            )
            if done:
                break
            refused.setdefault(said, []).append(str(s.day))
        else:
            said = "not reused"
            if current is not None and current.okrsky_reused:
                said += _withdraw_copy(cfg, election, current)
        # The sources refused for the same reason, said once.
        tried = [f"{', '.join(days)}: {why}" for why, days in refused.items()]
        lines.append(
            f"{names.get(code, code)} ({code}), okrsky: {'; '.join([said, *tried])}"
        )
    return lines


def _copy_from(
    cfg: Config,
    election: Election,
    voted: _Voted,
    source: Election,
    rules: obvody.RuleSet | None,
    later: Mapping[int, Mapping[int, int]],
) -> tuple[bool, str]:
    """Copy what *source*'s rules of an obec, *rules*, prove; say what was done.

    The okrsky only where they are the vote's own, from its document
    (:data:`OWN`): voters on the roll per okrsok do not show which addresses
    each has. Of a by-election proper, the council obvody that voted, each
    with voters on the roll within :data:`TOLERANCE` of its count in
    *source* (:func:`_obvody_problem`; *later* is ŠÚ SR's okrsky of the obec
    in *source* by obvod, with their voters), with their okrsky where each
    is its obvod (:data:`OBVODY`). Returns whether they were copied, and the
    report: what was written, or why not.
    """
    if rules is None:
        return False, "no rule set"
    if voted.whole_only and not rules.whole:
        return False, "okrsky by council obvod, the vote electing no council there"
    # Okrsky transcribed, for the regular election, from this referendum's
    # own document are its own.
    if rules.okrsky_referendum == election.day:
        why = _okrsky_problem(rules, voted)
        if why is not None:
            return False, why
        how = OWN
    elif voted.term and voted.grouped and not rules.whole:
        why = _obvody_problem(rules, voted.grouped, later, source)
        if why is not None:
            return False, f"obvody: {why}"
        how = OBVODY
    else:
        return False, f"okrsky: {_UNPROVEN}"
    copy, problem = _copy_of(cfg, election, voted, source, rules, how)
    if problem is not None:
        return False, problem
    return True, f"{_COPIED[how]}, {copy.relative_to(cfg.root)}"


OWN = "own"
"""What :func:`_copy_of` copies, besides :data:`OBVODY`: okrsky of the
vote's own document, transcribed for another election."""
_COPIED = {
    OWN: "its own, from the referendum's document",
    OBVODY: "council obvody reused",
}
"""How the report says what :func:`_copy_of` copied."""


def _okrsky_problem(rules: obvody.RuleSet, voted: _Voted) -> str | None:
    """Return why the vote's own okrsky *rules* may not stand for those *voted* in.

    They must place every address, be numbered 1..N for the N okrsky of
    the territorial division, and give each council obvod that voted (a
    by-election's) the okrsky that voted in it.
    """
    if rules.adoption or rules.okrsky_adoption:
        return "its okrsky are a stand-in, not proven to match"
    if not rules.okrsok_areas:
        return "its okrsky do not place the addresses"
    return _shape_problem(rules, voted.count, voted.grouped)


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

    :data:`OWN`, the okrsky as the vote's own; :data:`OBVODY`, the council
    obvody, with their okrsky marked ``okrsky_reused`` where each is its
    obvod (:func:`_by_obvod`), else none. A council rule set comes along
    marked ``reused``, its rules having lost their supplement marks (the
    header keeping the source file's). Returns the file, and why it could
    not be written: the copy does not fit the election's addresses.
    """
    code = voted.code
    searched = (
        f"No document of {election.day} was found (okrsky/not-found.json)."
        if voted.searched
        else f"No document of {election.day} was searched for."
    )
    if how == OWN:
        note = (
            f"These okrsky were transcribed for the elections of {source.day}"
            f" from the municipality's document for the referendum of"
            f" {election.day}: they are the referendum's own."
        )
        copy = dataclasses.replace(
            rules,
            okrsky_referendum=None,
            okrsky_note=" ".join(filter(None, (note, rules.okrsky_note))),
        )
    else:
        note = (
            f"These are the council obvody of the elections of {source.day}: in"
            f" {election.day} each obvod that voted had voters on the roll within"
            f" {TOLERANCE:.0%} of its count then. {searched}"
        )
        copy = _without_okrsky(rules)
        okrsky = _by_obvod(list(rules.seats), voted.grouped, voted.count)
        if okrsky is not None:
            copy = dataclasses.replace(
                copy,
                okrsky=okrsky,
                okrsky_reused=source.day,
                okrsky_note=_BY_OBVOD.format(year=election.day),
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
    def specials(self) -> special.Specials:
        """Return its special okrsky, without territory (:mod:`election_map_slovakia.special`)."""
        return division.special_okrsky(self.cfg, self.election)

    @functools.cached_property
    def counts(self) -> dict[str, int]:
        """Return obec → its territorial okrsky in the territorial division."""
        return special.territorial(
            division.okrsok_counts(self.cfg, self.election), self.specials
        )

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
    def new(self) -> set[str]:
        """Return the obce whose council a by-election elects anew (``vote`` ``"new"``)."""
        return candidates.new_councils(self.data["contests"])

    @functools.cached_property
    def grouped(self) -> obvodrules.Okrsky:
        """Return obec → council obvod → okrsok → voters on the roll."""
        return obvodrules.official_okrsky(self.cfg, self.election)

    @functools.cached_property
    def voters(self) -> dict[str, dict[int, int]]:
        """Return obec → okrsok → voters on the roll, of the okrsok files."""
        return okrsokrules.okrsok_voters(self.cfg, self.election)

    def okrsok_voters(self, code: str) -> dict[int, int]:
        """Return okrsok → voters on the roll of obec *code*, where known.

        Of its territorial okrsky: a special okrsok's number may be an
        ordinary okrsok's in another vote, and its voters say nothing of it.
        """
        voters = _flat(self.grouped.get(code, {})) | self.voters.get(code, {})
        return {k: v for k, v in voters.items() if k not in self.specials.get(code, {})}

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
    term: bool
    """Whether that council is its term's (a by-election proper's): not
    elected anew, its obvody are the term's."""
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
    # A by-election proper's council obvody are its term's alone; a new
    # election's, as any other vote's, the nearest regular election's.
    regular = [e for e in cfg.elections if e.kind == REGULAR and e != election]
    nearest = [votes[e.day] for e in _nearest(election, regular)]
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
                [term_vote] if t.term and term_vote else nearest,
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
    # A by-election proper fills seats of the council elected in its term's
    # obvody; a council elected anew has obvody of its own.
    of_term = term is not None and bool(council) and code not in vote.new
    obvody_of = term.council.get(code, {}) if term and of_term else council
    several = bool(council) and len(obvody_of) >= _SEVERAL
    return _Target(
        code,
        name,
        vote.counts.get(code, 0),
        council,
        several,
        of_term,
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
    A by-election proper's one source, its term, may give a rule set that is
    another vote's itself: it fills seats of the council elected in those
    obvody, however that election draws them. A council elected anew takes
    the nearest regular election's own, as any other vote's.
    """
    by_election = t.term

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
    # Strict: where they fail, the okrsky are searched for on their own
    # (:func:`_stand_in_okrsky`), a clean source first.
    off, allowed, outliers = _okrsky_off(
        t.voters, voters, t.count, election, source, lenient=False
    )
    if (
        own
        and not _shape_problem(copy, t.count, t.grouped)
        and not off
        and not _okrsok_fit(cfg, copy, p, a)
    ):
        basis = " ".join(
            filter(
                None,
                (
                    f"The okrsky of the same rule set: {t.count} okrsky, those ŠÚ SR"
                    " counted in each obvod.",
                    _voters_said("okrsok", t.voters, voters, election, source),
                    allowed,
                ),
            )
        )
        return dataclasses.replace(
            copy, okrsky_adoption=obvody.Adoption(source.day, basis, outliers)
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
    *missing* says why there are none of its own. A source whose okrsky
    all have voters within :data:`PLAUSIBLE` wins, the nearest in time;
    only where none has, the nearest with some farther apart, as an obec
    of its size allows (:func:`_okrsky_off`): the allowance gives a
    stand-in where there would be none, never a nearer one with outliers.
    """

    def attempt(s: Vote, nearer: Sequence[str], *, lenient: bool) -> _Tried:
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
        off, allowed, outliers = _okrsky_off(
            t.voters, voters, t.count, election, source, lenient=lenient
        )
        if off:
            return _Tried(_VOTERS, off)
        fit = f"{t.count} okrsky" + (
            ", those ŠÚ SR counted in each council obvod" if t.grouped else ""
        )
        basis = " ".join(
            filter(
                None,
                (
                    missing,
                    f"These are the okrsky of the vote of {source.day} ({source.slug}),"
                    f" the nearest in time with okrsky of its own that fit: {fit}"
                    f"{_not_taken(nearer)}.",
                    _voters_said("okrsok", t.voters, voters, election, source),
                    allowed,
                ),
            )
        )
        adoption = obvody.Adoption(source.day, basis, outliers)
        copy = _okrsky_copy(rules, into, source, adoption)
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

    found = _search(sources, functools.partial(attempt, lenient=False))
    if found[0] is None:
        found = _search(sources, functools.partial(attempt, lenient=True))
    return found


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


def _beyond(
    then: Mapping[int, int], later: Mapping[int, int]
) -> list[tuple[int, int, int]]:
    """Return (unit, voters *then*, *later*'s) beyond :data:`PLAUSIBLE`, known in both."""
    return [
        (k, then[k], later[k])
        for k in sorted(then.keys() & later.keys())
        if abs(later[k] - then[k]) > PLAUSIBLE * then[k]
    ]


def _off(
    unit: str, then: Mapping[int, int], later: Mapping[int, int], source: Election
) -> str | None:
    """Return the first *unit* whose voters *then* are off *later*'s, in *source*.

    Beyond :data:`PLAUSIBLE`, of those known in both votes.
    """
    beyond = _beyond(then, later)
    if not beyond:
        return None
    k, before, after = beyond[0]
    return f"{unit} {k}: {before:,} voters then, {after:,} in {source.day}"


def _outliers_allowed(count: int) -> int:
    """Return how many of *count* okrsky that stand in may be beyond :data:`PLAUSIBLE`."""
    return max(1, int(OUTLIERS_SHARE * count)) if count >= OUTLIERS_FROM else 0


def _okrsky_off(
    then: Mapping[int, int],
    later: Mapping[int, int],
    count: int,
    election: Election,
    source: Election,
    *,
    lenient: bool,
) -> tuple[str | None, str, tuple[tuple[int, int, int], ...]]:
    """Return why okrsky of *source* may not stand in by their voters, if so.

    Else None, the sentence naming those beyond :data:`PLAUSIBLE` all the
    same, where *lenient*, as an obec of *count* okrsky allows
    (:func:`_outliers_allowed`), and those okrsky, (okrsok, voters *then*,
    *later*'s): empty where none is.
    """
    beyond = _beyond(then, later)
    if not beyond:
        return None, "", ()
    if len(beyond) > (_outliers_allowed(count) if lenient else 0):
        return _off("okrsok", then, later, source), "", ()
    each = ", ".join(f"{k} ({b:,} → {a:,})" for k, b, a in beyond)
    which = f"okrsok {each} differs" if len(beyond) == 1 else f"okrsky {each} differ"
    said = (
        f"Of these, {which} by more than {PLAUSIBLE:.0%} ({election.day} →"
        f" {source.day}), allowed in an obec of {count} okrsky: of"
        f" {OUTLIERS_FROM} or more, one okrsok, or {OUTLIERS_SHARE:.0%} of"
        " them, may differ while the layout holds."
    )
    return None, said, tuple(beyond)


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
