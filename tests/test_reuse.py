"""Reusing or adopting the latest election's obvod and okrsok rules for an earlier one."""

import dataclasses
import datetime as dt
import shutil
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from election_map_slovakia import config, obvody, reuse

REPO = Path(__file__).resolve().parent.parent
DOCUMENT = {"url": "https://obec.sk/u.pdf", "sha256": "0" * 64, "title": "Uznesenie"}
SEATS = {"oz:500001/1": 3, "oz:500001/2": 2}
# ŠÚ SR's okrsky of obec 500001 by council obvod, with their voters.
THEN = {"500001": {1: {1: 1000, 2: 500}, 2: {3: 800}}}
NOW = {"500001": {1: {1: 1080, 2: 460}, 2: {3: 800}}}


def council(day: dt.date, okrsky: dict[str, list[int]] | None = None) -> obvody.RuleSet:
    """Obvod 1 (Hlavná, Krátka, 3 seats) and 2 (the rest, 2), of *day*."""
    obvod: dict[str, dict[str, Any]] = {
        "1": {"seats": 3, "rules": [{"street": "Hlavná"}, {"street": "Krátka"}]},
        "2": {"seats": 2, "rules": [{"rest": True}]},
    }
    for n, numbers in (okrsky or {}).items():
        obvod[n]["okrsky"] = numbers
    data = {
        "obec": "500001",
        "name": "Alfa",
        "date": day,
        "document": [DOCUMENT],
        "obvod": obvod,
    }
    return obvody.rule_set(data, "test")


@pytest.fixture
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> reuse._Context:
    shutil.copytree(REPO / "config", tmp_path / "config")
    shutil.copytree(REPO / config.PARTY_LOGO_DIR, tmp_path / config.PARTY_LOGO_DIR)
    cfg = config.load(tmp_path / "config")
    places = [
        obvody.Place("Hlavná", "Alfa", "1", ""),
        obvody.Place("Krátka", "Alfa", "2", ""),
        obvody.Place("Lúčna", "Alfa", "3", ""),
    ]
    nan = float("nan")
    p = obvody.ObecPlaces(places, np.full((3, 2), nan), [None] * 3, [])
    monkeypatch.setattr(reuse._Context, "places", lambda _, code: p)
    return reuse._Context(cfg, cfg.election("2022"), cfg.latest, SEATS, THEN, NOW)


def latest_rules(c: reuse._Context) -> obvody.RuleSet:
    """Write the latest election's rule set of obec 500001, with its okrsky."""
    rules = council(dt.date(2026, 6, 1), {"1": [1, 2], "2": [3]})
    path = obvody.rules_path(c.later, "500001")
    path.parent.mkdir(parents=True)
    path.write_text(obvody.dump(rules, ["the 2026 header"]), encoding="utf-8")
    return rules


def test_obvody_reused_where_obvody_seats_okrsky_and_voters_match(context):
    rules = latest_rules(context)
    report = reuse._obvody(context, "500001", {"500001": rules})
    path = obvody.rules_path(context.curated, "500001")
    assert report == f"reused, {path.relative_to(context.cfg.root)}"
    copy = obvody.load_rule_sets(context.curated)["500001"]
    assert copy.reused == copy.okrsky_reused == context.latest.day
    assert copy.okrsky == rules.okrsky
    assert "No document of the elections of 2022-10-29" in (copy.note or "")
    assert "the 2026 header" in path.read_text(encoding="utf-8")


def test_obvody_not_reused_where_the_seats_or_voters_differ(context):
    rules = latest_rules(context)
    seats = dataclasses.replace(context, seats={"oz:500001/1": 3, "oz:500001/2": 3})
    assert reuse._obvody(seats, "500001", {"500001": rules}) == (
        "not reused: obvody and seats 1: 3, 2: 2, then 1: 3, 2: 3"
    )
    # Okrsok 2 had 500 voters in 2022 and 560 now: over 10 % more.
    voters = dataclasses.replace(
        context, later_units={"500001": {1: {1: 1080, 2: 560}, 2: {3: 800}}}
    )
    assert reuse._obvody(voters, "500001", {"500001": rules}) == (
        "not reused: okrsok 2: 500 voters then, 560 in 2026"
    )
    assert reuse._obvody(context, "500001", {}) == (
        "not reused: no rule set of 2026-10-24"
    )
    assert not obvody.rules_path(context.curated, "500001").exists()


def test_okrsky_added_to_the_earlier_obvody_where_they_match(context):
    rules = latest_rules(context)
    own = council(dt.date(2022, 6, 1))
    path = obvody.rules_path(context.curated, "500001")
    path.parent.mkdir(parents=True)
    path.write_text(obvody.dump(own, ["the 2022 header"]), encoding="utf-8")
    assert reuse._okrsky(context, "500001", own, rules) == (
        f"reused, {path.relative_to(context.cfg.root)}"
    )
    copy = obvody.load_rule_sets(context.curated)["500001"]
    # The obvody stay 2022's, with the okrsky of 2026.
    assert copy.date == dt.date(2022, 6, 1) and copy.reused is None
    assert copy.okrsky == rules.okrsky and copy.okrsky_reused == context.latest.day
    assert path.read_text(encoding="utf-8").startswith("# the 2022 header")


def test_okrsky_not_reused_where_they_differ(context):
    rules = latest_rules(context)
    own = council(dt.date(2022, 6, 1))
    moved = dataclasses.replace(context, units={"500001": {1: {1: 1000}, 2: {2: 500}}})
    assert reuse._okrsky(moved, "500001", own, rules) == (
        "not reused: okrsky per obvod 1: 1, 2; 2: 3, then 1: 1; 2: 2"
    )
    voters = dataclasses.replace(
        context, later_units={"500001": {1: {1: 880, 2: 460}, 2: {3: 800}}}
    )
    assert reuse._okrsky(voters, "500001", own, rules) == (
        "not reused: okrsok 1: 1,000 voters then, 880 in 2026"
    )
    # Several obvody in 2022 but no rule set for them.
    assert reuse._okrsky(context, "500001", None, rules) == (
        "not reused: several council obvody but no rule set for them"
    )


ADOPT_OBVODY = reuse.Adopt("500001", "Alfa", reuse.OBVODY, "no 2022 houses")
ADOPT_OKRSKY = reuse.Adopt("500001", "Alfa", reuse.OKRSKY, "no 2022 streets")


def test_obvody_adopted_where_numbers_and_seats_match(context):
    rules = latest_rules(context)
    path = obvody.rules_path(context.curated, "500001")
    assert reuse._adopt_obvody(context, ADOPT_OBVODY, {"500001": rules}) == (
        f"adopted, {path.relative_to(context.cfg.root)}"
    )
    copy = obvody.load_rule_sets(context.curated)["500001"]
    # The latest rule set as it stands, marked, not reused.
    assert copy.rules == rules.rules and copy.date == rules.date
    assert copy.reused is None and copy.adoption is not None
    assert copy.adoption.day == context.latest.day
    assert copy.adoption.basis == (
        "no 2022 houses Voters on the roll per obvod (ŠÚ SR), 2022 → 2026:"
        " 1: 1,500 → 1,540, 2: 800 → 800."
    )
    assert obvody.council_origin(copy) == {"adopted": "2026-10-24"}
    # Obvod 1's two okrsky have no rules: only the obvody are drawn.
    assert copy.okrsky == rules.okrsky and copy.okrsky_adoption is None
    # Adopted again, it is replaced.
    assert reuse._adopt_obvody(context, ADOPT_OBVODY, {"500001": rules}).startswith(
        "adopted"
    )


def test_obvody_not_adopted_where_numbers_seats_or_voters_differ(context):
    rules = latest_rules(context)
    seats = dataclasses.replace(context, seats={"oz:500001/1": 3, "oz:500001/2": 3})
    assert reuse._adopt_obvody(seats, ADOPT_OBVODY, {"500001": rules}) == (
        "not adopted: obvody and seats 1: 3, 2: 2, then 1: 3, 2: 3"
    )
    three = dataclasses.replace(context, seats=SEATS | {"oz:500001/3": 1})
    assert reuse._adopt_obvody(three, ADOPT_OBVODY, {"500001": rules}) == (
        "not adopted: obvody and seats 1: 3, 2: 2, then 1: 3, 2: 2, 3: 1"
    )
    # Obvod 1 had 1,500 voters in 2022 and 2,000 now: over 25 % more.
    voters = dataclasses.replace(
        context, later_units={"500001": {1: {1: 1500, 2: 500}, 2: {3: 800}}}
    )
    assert reuse._adopt_obvody(voters, ADOPT_OBVODY, {"500001": rules}) == (
        "not adopted: obvod 1: 1,500 voters then, 2,000 in 2026"
    )
    assert reuse._adopt_obvody(context, ADOPT_OBVODY, {}) == (
        "not adopted: no rule set of 2026-10-24"
    )
    assert not obvody.rules_path(context.curated, "500001").exists()
    own = council(dt.date(2022, 6, 1))
    path = obvody.rules_path(context.curated, "500001")
    path.parent.mkdir(parents=True)
    path.write_text(obvody.dump(own), encoding="utf-8")
    assert reuse._adopt_obvody(context, ADOPT_OBVODY, {"500001": rules}) == (
        "not adopted: it has a rule set of its own"
    )


def with_okrsok_rules(rules: obvody.RuleSet) -> obvody.RuleSet:
    """Return *rules* with okrsok 1 Hlavná and 2 Krátka in obvod 1."""
    data = tomllib.loads(obvody.dump(rules))
    data["okrsok"] = {
        "1": {"rules": [{"street": "Hlavná"}]},
        "2": {"rules": [{"street": "Krátka"}]},
    }
    return obvody.rule_set(data, "test")


def test_okrsky_adopted_into_the_earlier_obvody(context, monkeypatch):
    # Drawing them needs points; the jobs' tests check that.
    monkeypatch.setattr(reuse, "_okrsok_fit", lambda *_: [])
    rules = with_okrsok_rules(latest_rules(context))
    own = council(dt.date(2022, 6, 1), {"1": [1, 2], "2": [3]})
    path = obvody.rules_path(context.curated, "500001")
    path.parent.mkdir(parents=True)
    path.write_text(obvody.dump(own, ["the 2022 header"]), encoding="utf-8")
    assert reuse._adopt_okrsky(context, ADOPT_OKRSKY, rules) == (
        f"adopted, {path.relative_to(context.cfg.root)}"
    )
    copy = obvody.load_rule_sets(context.curated)["500001"]
    # The obvody stay 2022's, with the okrsky of 2026 as they stand.
    assert copy.date == dt.date(2022, 6, 1) and copy.adoption is None
    assert copy.okrsok_rules == rules.okrsok_rules
    assert obvody.okrsky_origin(copy) == {"okrsky_adopted": "2026-10-24"}
    assert copy.okrsky_adoption is not None
    assert copy.okrsky_adoption.basis.startswith("no 2022 streets Voters on the roll")
    assert path.read_text(encoding="utf-8").startswith("# the 2022 header")


def test_okrsky_not_adopted_where_numbers_or_voters_differ(context, monkeypatch):
    monkeypatch.setattr(reuse, "_okrsok_fit", lambda *_: [])
    without = latest_rules(context)
    rules = with_okrsok_rules(without)
    own = council(dt.date(2022, 6, 1), {"1": [1, 2], "2": [3]})
    path = obvody.rules_path(context.curated, "500001")
    path.parent.mkdir(parents=True)
    path.write_text(obvody.dump(own), encoding="utf-8")
    moved = dataclasses.replace(context, units={"500001": {1: {1: 1000}, 2: {2: 500}}})
    assert reuse._adopt_okrsky(moved, ADOPT_OKRSKY, rules) == (
        "not adopted: okrsky per obvod 1: 1, 2; 2: 3, then 1: 1; 2: 2"
    )
    voters = dataclasses.replace(
        context, later_units={"500001": {1: {1: 600, 2: 460}, 2: {3: 800}}}
    )
    assert reuse._adopt_okrsky(voters, ADOPT_OKRSKY, rules) == (
        "not adopted: okrsok 1: 1,000 voters then, 600 in 2026"
    )
    # The latest okrsky of obvod 1 have no rules either.
    assert reuse._adopt_okrsky(context, ADOPT_OKRSKY, without) == (
        "not adopted: the okrsky of 2026-10-24 do not place the addresses"
    )
    assert reuse._adopt_okrsky(context, ADOPT_OKRSKY, None) == (
        "not adopted: no okrsky of 2026-10-24 of the same kind"
    )
    assert obvody.load_rule_sets(context.curated)["500001"] == own
    # Okrsky drawn already, one per obvod.
    drawn = council(dt.date(2022, 6, 1), {"1": [1], "2": [2]})
    path.write_text(obvody.dump(drawn), encoding="utf-8")
    assert reuse._adopt_okrsky(context, ADOPT_OKRSKY, rules) == (
        "not adopted: its okrsky are drawn already"
    )


def test_adopt_list_is_checked(context):
    path = context.curated / reuse.ADOPT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = 'obec = "500001"\nname = "Alfa"\nbasis = "b"\n'
    path.write_text(f'[[adopt]]\n{entry}units = "obvody"\n', encoding="utf-8")
    assert reuse.load_adopt(context.cfg, context.election) == [
        reuse.Adopt("500001", "Alfa", reuse.OBVODY, "b")
    ]
    path.write_text(f'[[adopt]]\n{entry}units = "obce"\n', encoding="utf-8")
    with pytest.raises(reuse.jobs.JobError, match="units must be"):
        reuse.load_adopt(context.cfg, context.election)
    path.write_text(f"[[adopt]]\n{entry}", encoding="utf-8")
    with pytest.raises(reuse.jobs.JobError, match="needs exactly"):
        reuse.load_adopt(context.cfg, context.election)
    twice = f'[[adopt]]\n{entry}units = "okrsky"\n' * 2
    path.write_text(twice, encoding="utf-8")
    with pytest.raises(reuse.jobs.JobError, match="listed twice"):
        reuse.load_adopt(context.cfg, context.election)
