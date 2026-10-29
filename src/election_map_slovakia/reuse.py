"""Reuse or adopt the latest election's obvod and okrsok rules for an earlier one.

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

Where no usable document of the earlier election places the addresses at
all (it names the obvody but not their houses, or gives the okrsky only by
obvod) and the layout is not proven to match, the obce listed in the
election's :data:`ADOPT_FILE` are drawn with the latest election's rules
all the same, never others::

    [[adopt]]
    obec = "517488"
    name = "Divina"
    units = "obvody"  # or "okrsky"
    basis = "…"  # why no rules of its own, what is known to differ

Adopted are only the units whose numbers are the earlier election's, so
that its results land on them, each with voters on the roll within
:data:`PLAUSIBLE` of the earlier count:

- ``obvody``, for an obec without a rule set of its own: the latest rule
  set as it stands, with the same obvod numbers and seats; its okrsky
  come along where it gives each obvod those ŠÚ SR counted in it then,
  else each obvod gets them from ŠÚ SR without rules (drawn where an
  obvod has one okrsok, which is then the obvod);
- ``okrsky``, for an obec whose earlier okrsky are known only by obvod,
  or not at all: the latest okrsky that place every address, with the
  okrsky per obvod ŠÚ SR counted then, of the same kind as above.

The copy must fit the addresses as a reused one must. It is marked
``adopted`` (and ``okrsky_adopted`` where its okrsky are drawn) or
``okrsky_adopted``, with the latest election's day and the basis, to which
the voters of both elections are added. Anything else is refused and said
so in the report, the units then staying unknown.
"""

from __future__ import annotations

import dataclasses
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from election_map_slovakia import addresses, jobs, obvodrules, obvody, okrsokrules
from election_map_slovakia.config import Config, Election

TOLERANCE = 0.10
"""How far an okrsok's voters may differ between the elections, as a share
of the earlier count."""
PLAUSIBLE = 0.25
"""How far the voters of an adopted obvod or okrsok may differ, likewise."""
ADOPT_FILE = "adopt.toml"
"""In the earlier election's curated data: the obce whose units are adopted."""
OBVODY, OKRSKY = "obvody", "okrsky"
"""What :class:`Adopt` adopts."""


@dataclasses.dataclass(frozen=True)
class Adopt:
    """One entry of :data:`ADOPT_FILE`."""

    obec: str
    name: str
    units: str
    """:data:`OBVODY` or :data:`OKRSKY`."""
    basis: str
    """Why the election has no rules of its own, and what is known to differ."""


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
    """Copy the latest election's rules where *election* has none; return report lines.

    See the module doc.
    """
    latest = cfg.latest
    if election.day == latest.day:
        raise jobs.JobError(f"{election.day} is the latest election: nothing to reuse")
    adopt = load_adopt(cfg, election)
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
        if code not in current:
            lines.append(f"{entry['name']} ({code}), obvody: {_obvody(c, code, later)}")
    current = obvody.load_rule_sets(c.curated)
    later_okrsky = obvody.okrsok_rule_sets(c.later)
    for code, entry in okrsokrules.load_not_found(cfg, election).items():
        rules = current.get(code)
        if rules is None or not rules.okrsky:
            lines.append(
                f"{entry['name']} ({code}), okrsky:"
                f" {_okrsky(c, code, rules, later_okrsky.get(code))}"
            )
    for a in adopt:
        done = (
            _adopt_obvody(c, a, later)
            if a.units == OBVODY
            else _adopt_okrsky(c, a, later_okrsky.get(a.obec))
        )
        lines.append(f"{a.name} ({a.obec}), {a.units}: {done}")
    return lines


def load_adopt(cfg: Config, election: Election) -> list[Adopt]:
    """Return the entries of *election*'s :data:`ADOPT_FILE`, none if it has none."""
    path = cfg.election_dir(election) / ADOPT_FILE
    if not path.is_file():
        return []
    try:
        listed = tomllib.loads(path.read_text(encoding="utf-8")).get("adopt", [])
    except tomllib.TOMLDecodeError as e:
        raise jobs.JobError(f"{path}: invalid TOML: {e}") from e
    out = []
    for i, entry in enumerate(listed):
        where = f"{path}: adopt[{i}]"
        keys = {f.name for f in dataclasses.fields(Adopt)}
        if not isinstance(entry, dict) or set(entry) != keys:
            raise jobs.JobError(f"{where}: needs exactly {', '.join(sorted(keys))}")
        if not all(isinstance(v, str) and v.strip() for v in entry.values()):
            raise jobs.JobError(f"{where}: every value must be a text")
        a = Adopt(**entry)
        if a.units not in (OBVODY, OKRSKY):
            raise jobs.JobError(f"{where}: units must be {OBVODY} or {OKRSKY}")
        if any((b.obec, b.units) == (a.obec, a.units) for b in out):
            raise jobs.JobError(f"{where}: {a.obec} {a.units} listed twice")
        out.append(a)
    return out


def _obvody(c: _Context, code: str, later: Mapping[str, obvody.RuleSet]) -> str:
    """Copy the latest council rule set of obec *code* if it fits; say what was done."""
    rules = later.get(code)
    if rules is None:
        return f"not reused: no rule set of {c.latest.day}"
    seats = c.obvod_seats(code)
    if rules.seats != seats:
        return (
            f"not reused: obvody and seats {_seats(rules.seats)}, then {_seats(seats)}"
        )
    if not rules.okrsky:
        return f"not reused: the rule set of {c.latest.day} lacks the okrsky"
    why = _layout_problem(c, code, rules, TOLERANCE)
    if why:
        return f"not reused: {why}"
    p = c.places(code)
    a = obvody.assign(rules, p.places, p.kus, p.planar())
    problems = addresses.check_assignment(rules, list(seats), p, a)
    problems = problems or _okrsok_fit(c, rules, p, a)
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
    return _write_rule_set(c, code, copy, "reused")


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
    if rules is None or rules.whole != (current is None):
        return f"not reused: no okrsky of {c.latest.day} of the same kind"
    if current is not None and list(rules.seats) != list(current.seats):
        return "not reused: other obvody"
    why = _layout_problem(c, code, rules, TOLERANCE)
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
    return _copy_okrsky(c, code, current, rules, marks, "reused")


def _adopt_obvody(c: _Context, a: Adopt, later: Mapping[str, obvody.RuleSet]) -> str:
    """Adopt the latest council rule set of obec *a* if its units fit; say what was done."""
    code = a.obec
    current = obvody.load_rule_sets(c.curated).get(code)
    if current is not None and current.adoption is None:
        return "not adopted: it has a rule set of its own"
    rules = later.get(code)
    if rules is None:
        return f"not adopted: no rule set of {c.latest.day}"
    seats = c.obvod_seats(code)
    if rules.seats != seats:
        return (
            f"not adopted: obvody and seats {_seats(rules.seats)}, then {_seats(seats)}"
        )
    units = c.units.get(code, {})
    if not units:
        return f"not adopted: ŠÚ SR's okrsky of {c.election.day} unknown"
    then = {n: sum(ks.values()) for n, ks in units.items()}
    now = {n: sum(ks.values()) for n, ks in c.later_units.get(code, {}).items()}
    why = _implausible(c, "obvod", then, now)
    if why:
        return f"not adopted: {why}"
    official = {n: tuple(ks) for n, ks in units.items()}
    with_okrsky = rules.okrsky == official and not _layout_problem(
        c, code, rules, PLAUSIBLE
    )
    voters = _voters(c, "obvod", then, now)
    copy = dataclasses.replace(
        rules,
        reused=None,
        adoption=obvody.Adoption(c.latest.day, f"{a.basis} {voters}"),
        okrsky_reused=None,
        okrsky_referendum=None,
        okrsky_supplement=None,
    )
    if not with_okrsky:
        # The okrsky by obvod as ŠÚ SR counted them then, without rules.
        copy = dataclasses.replace(
            copy,
            okrsky=official,
            okrsok_rules=(),
            okrsky_fill=False,
            okrsky_date=None,
            okrsky_note=None,
            okrsky_dating=None,
            addressless=(),
        )
    if copy.okrsok_areas:
        later_okrsky = _flat(c.later_units.get(code, {}))
        basis = (
            f"The okrsky of the rule set of {c.latest.day}, those ŠÚ SR counted"
            " in each obvod in both elections."
            if with_okrsky
            else f"ŠÚ SR counted one okrsok per obvod in {c.election.day.year},"
            " so each is drawn as its adopted obvod."
        )
        copy = dataclasses.replace(
            copy,
            okrsky_adoption=obvody.Adoption(
                c.latest.day,
                f"{basis} {_voters(c, 'okrsok', _flat(units), later_okrsky)}",
            ),
        )
    p = c.places(code)
    assigned = obvody.assign(copy, p.places, p.kus, p.planar())
    problems = addresses.check_assignment(copy, list(seats), p, assigned)
    problems = problems or _okrsok_fit(c, copy, p, assigned)
    if problems:
        return f"not adopted: on the addresses of {c.election.day}: {problems[0]}"
    return _write_rule_set(c, code, copy, "adopted")


def _adopt_okrsky(c: _Context, a: Adopt, rules: obvody.RuleSet | None) -> str:
    """Adopt the latest okrsky of obec *a*, *rules*, if they fit; say what was done.

    *rules* is the latest election's rule set that gives the okrsky, if one.
    """
    code = a.obec
    current = obvody.load_obec(c.curated, code)
    if current is None and len(c.units.get(code, {})) > 1:
        return "not adopted: several council obvody but no rule set for them"
    if current is not None and (current.reused or current.adoption):
        return "not adopted: its council obvody are another election's"
    if current is not None and current.okrsok_areas and not current.okrsky_adoption:
        return "not adopted: its okrsky are drawn already"
    whole = current is None or current.whole
    if rules is None or rules.whole != whole:
        return f"not adopted: no okrsky of {c.latest.day} of the same kind"
    if not rules.okrsok_areas:
        return f"not adopted: the okrsky of {c.latest.day} do not place the addresses"
    if not whole and current is not None and list(rules.seats) != list(current.seats):
        return "not adopted: other obvody"
    why = _layout_problem(c, code, rules, PLAUSIBLE)
    if why:
        return f"not adopted: {why}"
    later_okrsky = _flat(c.later_units.get(code, {}))
    voters = _voters(c, "okrsok", _flat(c.units[code]), later_okrsky)
    marks = {
        "okrsky_adoption": obvody.Adoption(c.latest.day, f"{a.basis} {voters}"),
        "okrsky_note": rules.okrsky_note,
    }
    # An okrsky file of the earlier election is replaced, as when reused.
    return _copy_okrsky(c, code, None if whole else current, rules, marks, "adopted")


def _write_rule_set(c: _Context, code: str, copy: obvody.RuleSet, verb: str) -> str:
    """Write *copy*, of the latest rule set of obec *code*; return the report."""
    source = obvody.rules_path(c.later, code)
    path = obvody.rules_path(c.curated, code)
    header = [
        f"The rule set of the elections of {c.latest.day},"
        f" {source.relative_to(c.cfg.root)}, {verb} by `ems job reuse`. Its header",
        "there:",
        *(f"  {h}" for h in okrsokrules.header(source)),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obvody.dump(copy, header), encoding="utf-8")
    return f"{verb}, {path.relative_to(c.cfg.root)}"


def _copy_okrsky(
    c: _Context,
    code: str,
    current: obvody.RuleSet | None,
    rules: obvody.RuleSet,
    marks: Mapping[str, Any],
    verb: str,
) -> str:
    """Write the okrsky *rules* of the latest election for obec *code*; report it.

    Into the earlier council rule set *current*, or as its okrsky file if
    None; *marks* are the ``okrsky_*`` fields saying where they come from.
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
    problems = _okrsok_fit(c, copy, p, a)
    if problems:
        return f"not {verb}: on the addresses of {c.election.day}: {problems[0]}"
    header[-1] += f", {source.relative_to(c.cfg.root)}, {verb} by `ems job reuse`."
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obvody.dump(copy, header), encoding="utf-8")
    return f"{verb}, {path.relative_to(c.cfg.root)}"


def _layout_problem(
    c: _Context, code: str, rules: obvody.RuleSet, tolerance: float
) -> str | None:
    """Return why the okrsky of *rules* may not stand for the earlier election's.

    They must be those ŠÚ SR counted in each obvod then, each with voters
    on the roll within *tolerance* of the earlier count.
    """
    units = c.units.get(code, {})
    if not units:
        return f"ŠÚ SR's okrsky of {c.election.day} unknown"
    given = {n: list(ks) for n, ks in rules.okrsky.items()}
    official = {n: list(k) for n, k in units.items()}
    if given != official:
        return f"okrsky per obvod {_okrsky_text(given)}, then {_okrsky_text(official)}"
    later = _flat(c.later_units.get(code, {}))
    return _implausible(c, "okrsok", _flat(units), later, tolerance)


def _implausible(
    c: _Context,
    unit: str,
    then: Mapping[int, int],
    now: Mapping[int, int],
    tolerance: float = PLAUSIBLE,
) -> str | None:
    """Return the first *unit* whose voters *now* are off those *then*, if one."""
    for k, before in then.items():
        after = now.get(k)
        if after is None:
            return f"{unit} {k}: voters of {c.latest.day} unknown"
        if abs(after - before) > tolerance * before:
            return (
                f"{unit} {k}: {before:,} voters then, {after:,} in {c.latest.day.year}"
            )
    return None


def _flat(units: Mapping[int, Mapping[int, int]]) -> dict[int, int]:
    """Return okrsok → voters of ŠÚ SR's okrsky by obvod *units*."""
    return {k: v for ks in units.values() for k, v in ks.items()}


def _voters(
    c: _Context, unit: str, then: Mapping[int, int], now: Mapping[int, int]
) -> str:
    """Return the sentence giving each *unit*'s voters on the roll in both elections."""
    each = ", ".join(
        f"{k}: {v:,} → {f'{now[k]:,}' if k in now else 'unknown'}"
        for k, v in then.items()
    )
    return (
        f"Voters on the roll per {unit} (ŠÚ SR), {c.election.day.year}"
        f" → {c.latest.day.year}: {each}."
    )


def _okrsok_fit(
    c: _Context, rules: obvody.RuleSet, p: obvody.ObecPlaces, a: obvody.Assignment
) -> list[str]:
    """Return why the okrsky of *rules* do not fit the addresses *p* (obvody *a*)."""
    if not rules.okrsok_areas:
        return []
    k, problems = okrsokrules.okrsok_problems(rules, p, a.units)
    if problems:
        return problems
    return okrsokrules.draw(c.cfg, rules, p, a, k)[1]


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
