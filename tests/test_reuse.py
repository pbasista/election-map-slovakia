"""Reusing or adopting the latest election's obvod and okrsok rules for an earlier one."""

import dataclasses
import datetime as dt
import shutil
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from election_map_slovakia import config, obvodrules, obvody, reuse

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
    """The obvody proven, their okrsky not: two okrsky in obvod 1, whose
    voters do not show which addresses each has."""
    rules = latest_rules(context)
    report = reuse._obvody(context, "500001", {"500001": rules})
    path = obvody.rules_path(context.curated, "500001")
    assert report == f"reused, {path.relative_to(context.cfg.root)}"
    copy = obvody.load_rule_sets(context.curated)["500001"]
    assert copy.reused == context.latest.day
    assert not copy.okrsky and copy.okrsky_reused is None and not copy.okrsok_rules
    assert "No document of the elections of 2022-10-29" in (copy.note or "")
    assert "the 2026 header" in path.read_text(encoding="utf-8")


def test_obvody_reused_with_okrsky_each_its_obvod(context):
    """ŠÚ SR counted one okrsok in each obvod: the okrsky are the obvody."""
    rules = council(dt.date(2026, 6, 1), {"1": [1], "2": [2]})
    write_rules(obvody.rules_path(context.later, "500001"), rules)
    units = {"500001": {1: {1: 1500}, 2: {2: 800}}}
    one_each = dataclasses.replace(context, units=units, later_units=units)
    reuse._obvody(one_each, "500001", {"500001": rules})
    copy = obvody.load_rule_sets(context.curated)["500001"]
    assert copy.okrsky == {1: (1,), 2: (2,)}
    assert copy.reused == copy.okrsky_reused == context.latest.day
    assert "each okrsok is its obvod" in (copy.okrsky_note or "")


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


def test_okrsky_added_to_the_earlier_obvody_only_where_each_is_its_obvod(context):
    """Voters alone prove no okrsky: two in obvod 1 are not copied; one in
    each obvod is the obvod, so 2026's are 2022's."""
    rules = latest_rules(context)
    own = council(dt.date(2022, 6, 1))
    path = obvody.rules_path(context.curated, "500001")
    path.parent.mkdir(parents=True)
    path.write_text(obvody.dump(own, ["the 2022 header"]), encoding="utf-8")
    assert reuse._okrsky(context, "500001", own, rules) == (
        f"not reused: {reuse._UNPROVEN}"
    )
    units = {"500001": {1: {1: 1500}, 2: {2: 800}}}
    one_each = dataclasses.replace(context, units=units, later_units=units)
    later = council(dt.date(2026, 6, 1), {"1": [1], "2": [2]})
    assert reuse._okrsky(one_each, "500001", own, later) == (
        f"reused, {path.relative_to(context.cfg.root)}"
    )
    copy = obvody.load_rule_sets(context.curated)["500001"]
    # The obvody stay 2022's, each its okrsok.
    assert copy.date == dt.date(2022, 6, 1) and copy.reused is None
    assert copy.okrsky == {1: (1,), 2: (2,)}
    assert copy.okrsky_reused == context.latest.day
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


def with_okrsok_rules(rules: obvody.RuleSet) -> obvody.RuleSet:
    """Return *rules* with okrsok 1 Hlavná and 2 Krátka in obvod 1."""
    data = tomllib.loads(obvody.dump(rules))
    data["okrsok"] = {
        "1": {"rules": [{"street": "Hlavná"}]},
        "2": {"rules": [{"street": "Krátka"}]},
    }
    return obvody.rule_set(data, "test")


def voted(
    grouped: dict[int, dict[int, int]] | None = None,
    *,
    count: int = 3,
    term: bool = False,
) -> reuse._Voted:
    """Return obec 500001 of *count* okrsky, as it voted in another vote.

    *grouped*: a by-election's council obvody that voted; *term*: a
    by-election proper of seats of its term's council.
    """
    return reuse._Voted("500001", count, grouped or {}, searched=False, term=term)


def test_voters_alone_prove_no_okrsky(project):
    """A country-wide election's okrsky of the same numbers, each with
    about the same voters, are not proven the 2022 elections': nothing
    copied, a stand-in may take their place."""
    cfg = project
    election, source = cfg.election("2024-prezident"), cfg.election("2022")
    rules = with_okrsok_rules(council(dt.date(2022, 6, 1), {"1": [1, 2], "2": [3]}))
    write_rules(obvody.rules_path(cfg.election_dir(source), "500001"), rules)
    write_places(cfg, election)
    later = {1: {1: 1000, 2: 500}, 2: {3: 800}}
    done, said = reuse._copy_from(cfg, election, voted(), source, rules, later)
    assert not done and said == f"okrsky: {reuse._UNPROVEN}"
    assert obvody.load_obec(cfg.election_dir(election), "500001") is None
    # Nor those a by-election's obvod voted in, by their voters.
    by_election = cfg.election("2023-03")
    write_places(cfg, by_election)
    obvod_1 = voted({1: {1: 1000, 2: 500}})
    done, said = reuse._copy_from(cfg, by_election, obvod_1, source, rules, later)
    assert not done and said == f"okrsky: {reuse._UNPROVEN}"


def test_the_vote_s_own_okrsky_need_their_shape_only():
    rules = with_okrsok_rules(council(dt.date(2022, 6, 1), {"1": [1, 2], "2": [3]}))
    assert reuse._okrsky_problem(rules, voted()) is None
    assert reuse._okrsky_problem(rules, voted(count=4)) == "okrsky 1–3, then 1–4"
    regrouped = voted({1: {1: 1000, 3: 800}})
    assert reuse._okrsky_problem(rules, regrouped) == "obvod 1: okrsky 1, 2, then 1, 3"
    adoption = obvody.Adoption(dt.date(2026, 10, 24), "no 2022 document")
    adopted = dataclasses.replace(rules, okrsky_adoption=adoption)
    assert reuse._okrsky_problem(adopted, voted()) == (
        "its okrsky are a stand-in, not proven to match"
    )


def test_by_election_obvody_proven_by_their_voters():
    rules = council(dt.date(2022, 6, 1))
    source = config.load(REPO / "config").election("2022")
    later = {1: {1: 1000, 2: 500}, 2: {3: 800}}
    assert reuse._obvody_problem(rules, {2: {3: 850}}, later, source) is None
    assert reuse._obvody_problem(rules, {2: {3: 700}}, later, source) == (
        "obvod 2: 700 voters then, 800 in 2022"
    )
    assert reuse._obvody_problem(rules, {3: {4: 800}}, later, source) == (
        "obvod 3: not one of its obvody"
    )


def test_by_election_copies_only_from_its_councils_elections():
    """A by-election fills seats of the council elected before it: never
    the later regular elections' okrsky and obvody, however near; other
    votes take the nearest regular elections either side."""
    cfg = config.load(REPO / "config")
    by_election = dataclasses.replace(cfg.election("2026-03"), day=dt.date(2026, 9, 1))
    days = [e.day for e in reuse.sources(cfg, by_election)]
    assert days and all(d < by_election.day for d in days)
    assert days == sorted(days, reverse=True)
    referendum = cfg.election("2026-referendum")
    assert reuse.sources(cfg, referendum)[0].day == cfg.latest.day


@pytest.fixture
def project(tmp_path: Path) -> config.Config:
    shutil.copytree(REPO / "config", tmp_path / "config")
    shutil.copytree(REPO / config.PARTY_LOGO_DIR, tmp_path / config.PARTY_LOGO_DIR)
    return config.load(tmp_path / "config")


def write_places(cfg: config.Config, election: config.Election) -> None:
    """Write the addresses of obec 500001: Hlavná, Krátka and Lúčna."""
    places = [
        obvody.Place("Hlavná", "Alfa", "1", ""),
        obvody.Place("Krátka", "Alfa", "2", ""),
        obvody.Place("Lúčna", "Alfa", "3", ""),
    ]
    p = obvody.ObecPlaces(places, np.full((3, 2), float("nan")), [None] * 3, [])
    obvody.write_places({"500001": p.to_json()}, obvodrules.places_dir(cfg, election))


def write_rules(path: Path, rules: obvody.RuleSet) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obvody.dump(rules, ["the source header"]), encoding="utf-8")


def test_referendum_okrsky_of_its_own_document_are_its_own(project):
    """The 2022 elections' okrsky transcribed from the 2023 referendum's
    document are the referendum's own: copied without the reused mark,
    with their date, whatever the voters."""
    cfg = project
    referendum, source = cfg.election("2023-referendum"), cfg.election("2022")
    rules = with_okrsok_rules(council(dt.date(2022, 6, 1), {"1": [1, 2], "2": [3]}))
    rules = dataclasses.replace(
        rules,
        okrsky_date=dt.date(2022, 11, 20),
        okrsky_referendum=referendum.day,
        okrsky_note="the referendum's document; unchanged",
    )
    write_rules(obvody.rules_path(cfg.election_dir(source), "500001"), rules)
    write_places(cfg, referendum)
    done, said = reuse._copy_from(
        cfg, referendum, voted(), source, rules, {1: {1: 1, 2: 1}, 2: {3: 1}}
    )
    assert done and said.startswith("its own, from the referendum's document")
    copy = obvody.load_obec(cfg.election_dir(referendum), "500001")
    assert copy is not None
    assert copy.okrsky_reused is None and copy.okrsky_referendum is None
    assert copy.okrsky_date == dt.date(2022, 11, 20)
    assert copy.okrsky_note and "the referendum's own" in copy.okrsky_note
    # The council obvody only place them: the referendum elects none.
    assert copy.reused == source.day


def test_by_election_council_obvody_copied_without_unproven_okrsky(project):
    """A by-election proper in obvod 2: the obvod's voters prove the
    council rule set of its term, copied without okrsky (obvod 1, which
    did not vote, has two) and marked reused; a council elected anew takes
    nothing of the term."""
    cfg = project
    by_election, source = cfg.election("2023-03"), cfg.election("2022")
    rules = with_okrsok_rules(council(dt.date(2022, 6, 1), {"1": [1, 2], "2": [3]}))
    write_rules(obvody.rules_path(cfg.election_dir(source), "500001"), rules)
    write_places(cfg, by_election)
    obvod_2 = voted({2: {3: 850}}, term=True)
    later = {1: {1: 1000, 2: 500}, 2: {3: 800}}
    done, said = reuse._copy_from(
        cfg, by_election, obvod_2, source, rules, later | {2: {3: 700}}
    )
    assert not done and said == "obvody: obvod 2: 850 voters then, 700 in 2022"
    done, said = reuse._copy_from(cfg, by_election, obvod_2, source, rules, later)
    assert done and said.startswith("council obvody reused, data/")
    copy = obvody.load_obec(cfg.election_dir(by_election), "500001")
    assert copy is not None and copy.reused == source.day and not copy.okrsky
    new = voted({2: {3: 850}})
    done, said = reuse._copy_from(cfg, by_election, new, source, rules, later)
    assert not done and said == f"okrsky: {reuse._UNPROVEN}"


def test_by_election_okrsky_each_their_obvod(project):
    """Both obvody voted, ŠÚ SR counting one okrsok in each: the copy's
    okrsky are its obvody, proven as they are."""
    cfg = project
    by_election, source = cfg.election("2023-03"), cfg.election("2022")
    rules = council(dt.date(2022, 6, 1), {"1": [1], "2": [2]})
    write_rules(obvody.rules_path(cfg.election_dir(source), "500001"), rules)
    write_places(cfg, by_election)
    both = voted({1: {1: 1500}, 2: {2: 820}}, count=2, term=True)
    later = {1: {1: 1480}, 2: {2: 800}}
    done, _ = reuse._copy_from(cfg, by_election, both, source, rules, later)
    copy = obvody.load_obec(cfg.election_dir(by_election), "500001")
    assert done and copy is not None
    assert copy.okrsky == {1: (1,), 2: (2,)} and copy.okrsky_reused == source.day


def all_votes(
    cfg: config.Config, contests: dict[str, list[dict[str, Any]]] | None = None
) -> dict[dt.date, reuse.Vote]:
    """Return every vote of *cfg*, knowing of obec 500001 only its name.

    *contests*: by slug, a vote's council contests there.
    """
    out = {}
    for e in cfg.elections:
        vote = reuse.Vote(cfg, e)
        vote.data = {
            "obce": [{"code": "500001", "name": "Alfa"}],
            "contests": (contests or {}).get(e.slug, []),
        }
        vote.counts, vote.grouped, vote.voters = {}, {}, {}
        out[e.day] = vote
    return out


def contest(obvod: int, seats: int) -> dict[str, Any]:
    return {"id": f"oz:500001/{obvod}", "kind": "oz", "area": "500001", "seats": seats}


def write_okrsky(
    cfg: config.Config,
    slug: str,
    okrsky: dict[str, list[int]] | None = None,
    **marks: Any,
) -> None:
    """Write the okrsky of obec 500001 in vote *slug*: by default 1 and 2 in obvod 1, 3 in 2."""
    day = cfg.election(slug).day
    if okrsky is None:
        rules = with_okrsok_rules(council(day, {"1": [1, 2], "2": [3]}))
    else:
        rules = council(day, okrsky)
    path = obvody.rules_path(cfg.election_dir(cfg.election(slug)), "500001")
    write_rules(path, dataclasses.replace(rules, **marks))


@pytest.fixture
def presidential(
    project: config.Config, monkeypatch: pytest.MonkeyPatch
) -> tuple[config.Election, dict[dt.date, reuse.Vote]]:
    """The presidential election of 2024, obec 500001 of three okrsky in it."""
    # Drawing okrsky needs points; the jobs' tests check that.
    monkeypatch.setattr(reuse, "_okrsok_fit", lambda *_: [])
    election = project.election("2024-prezident")
    votes = all_votes(project)
    votes[election.day].counts = {"500001": 3}
    write_places(project, election)
    return election, votes


def stood_in(cfg: config.Config, election: config.Election) -> obvody.RuleSet:
    rules = obvody.load_obec(cfg.election_dir(election), "500001")
    assert rules is not None and rules.okrsky_adoption is not None
    return rules


def test_stand_in_from_the_nearest_vote_either_way(project, presidential):
    """The EP election 77 days after stands in before the parliamentary one
    175 days before; without it, the earlier; of two as near, the later."""
    election, votes = presidential
    write_okrsky(project, "2023-nrsr")
    write_okrsky(project, "2024-ep")
    lines = reuse.stand_in(project, election, votes)
    assert lines[0].startswith("Alfa (500001), okrsky: from 2024-06-08 (2024-ep)")
    copy = stood_in(project, election)
    assert copy.okrsky_adoption.day == dt.date(2024, 6, 8)
    # The council obvody of a vote without a council contest only place them.
    assert copy.reused == dt.date(2024, 6, 8)
    assert lines[-1].startswith("2024-03-23 okrsky: 1 stand in (from 2024-06-08: 1)")
    obvody.rules_path(
        project.election_dir(project.election("2024-ep")), "500001"
    ).unlink()
    reuse.stand_in(project, election, votes)
    assert stood_in(project, election).okrsky_adoption.day == dt.date(2023, 9, 30)
    before, after = (
        dataclasses.replace(election, day=election.day + dt.timedelta(days=d))
        for d in (-10, 10)
    )
    assert reuse._nearest(election, [before, after]) == [after, before]


def test_stand_in_only_of_a_vote_s_own_okrsky(project, presidential):
    """Okrsky another vote copied, proven or itself standing in, are no
    source: the nearest that are its own stand in."""
    election, votes = presidential
    write_okrsky(project, "2023-nrsr")
    reused = {"okrsky_reused": dt.date(2022, 10, 29), "okrsky_note": "2022's"}
    write_okrsky(project, "2024-ep", **reused)
    reuse.stand_in(project, election, votes)
    assert stood_in(project, election).okrsky_adoption.day == dt.date(2023, 9, 30)
    adoption = obvody.Adoption(dt.date(2022, 10, 29), "no document")
    write_okrsky(project, "2024-ep", okrsky_adoption=adoption)
    reuse.stand_in(project, election, votes)
    assert stood_in(project, election).okrsky_adoption.day == dt.date(2023, 9, 30)


def test_stand_in_skips_okrsky_of_another_structure(project, presidential):
    """Two okrsky where the vote counted three: the next nearest stand in,
    the basis saying why the nearer did not."""
    election, votes = presidential
    write_okrsky(project, "2023-nrsr")
    write_okrsky(project, "2024-ep", {"1": [1], "2": [2]})
    reuse.stand_in(project, election, votes)
    copy = stood_in(project, election)
    assert copy.okrsky_adoption.day == dt.date(2023, 9, 30)
    assert "2024-06-08: okrsky 1, 2, then 1–3" in copy.okrsky_adoption.basis


def test_stand_in_refused_where_the_voters_differ_too_much(project, presidential):
    """Okrsok 1 had 1,000 voters, 1,300 in the EP election: over 25 % more,
    the layout changed; the parliamentary election's 1,100 are near enough.
    Without it nothing stands in."""
    election, votes = presidential
    votes[election.day].voters = {"500001": {1: 1000, 2: 500, 3: 800}}
    votes[dt.date(2024, 6, 8)].voters = {"500001": {1: 1300, 2: 500, 3: 800}}
    votes[dt.date(2023, 9, 30)].voters = {"500001": {1: 1100, 2: 500, 3: 800}}
    write_okrsky(project, "2023-nrsr")
    write_okrsky(project, "2024-ep")
    reuse.stand_in(project, election, votes)
    copy = stood_in(project, election)
    assert copy.okrsky_adoption.day == dt.date(2023, 9, 30)
    assert "1: 1,000 → 1,100" in copy.okrsky_adoption.basis
    obvody.rules_path(
        project.election_dir(project.election("2023-nrsr")), "500001"
    ).unlink()
    lines = reuse.stand_in(project, election, votes)
    assert lines[0] == (
        "Alfa (500001), okrsky: unknown: the voters differ too much from every"
        " fitting source's (2024-06-08: okrsok 1: 1,000 voters then, 1,300 in"
        " 2024-06-08); the stand-in before, data/curated/elections/2024-03-23/"
        "obvody/oz/500001.toml, withdrawn"
    )
    assert obvody.load_obec(project.election_dir(election), "500001") is None


def ten(voters: int = 1000, **off: int) -> dict[int, int]:
    """Return okrsok → voters of ten okrsky, those named ``k<n>`` *off*."""
    return {k: off.get(f"k{k}", voters) for k in range(1, 11)}


def write_ten(cfg: config.Config, slug: str) -> None:
    """Write ten okrsky of obec 500001 in vote *slug*, each with a street."""
    e = cfg.election(slug)
    data = tomllib.loads(
        obvody.dump(council(e.day, {"1": list(range(1, 10)), "2": [10]}))
    )
    streets = ["Hlavná", "Krátka", *(f"Ulica {k}" for k in range(3, 10))]
    data["okrsok"] = {
        str(k): {"rules": [{"street": s}]} for k, s in enumerate(streets, 1)
    }
    path = obvody.rules_path(cfg.election_dir(e), "500001")
    write_rules(path, obvody.rule_set(data, "test"))


def test_stand_in_allows_one_okrsok_beyond_plausible_of_ten(project, presidential):
    """Of ten okrsky one may differ by more than 25 %, named in the basis
    with both counts; two may not."""
    election, votes = presidential
    votes[election.day].counts = {"500001": 10}
    write_ten(project, "2024-ep")
    votes[election.day].voters = {"500001": ten()}
    votes[dt.date(2024, 6, 8)].voters = {"500001": ten(k4=1400)}
    reuse.stand_in(project, election, votes)
    copy = stood_in(project, election)
    basis = copy.okrsky_adoption.basis
    assert "Of these, okrsok 4 (1,000 → 1,400) differs by more than 25%" in basis
    assert "in an obec of 10 okrsky" in basis
    # Recorded for the map to name, and read back from the file as written.
    assert copy.okrsky_adoption.outliers == ((4, 1000, 1400),)
    assert obvody.okrsky_origin(copy)["okrsky_outliers"] == [[4, 1000, 1400]]
    votes[dt.date(2024, 6, 8)].voters = {"500001": ten(k4=1400, k7=600)}
    lines = reuse.stand_in(project, election, votes)
    assert lines[0].startswith(
        "Alfa (500001), okrsky: unknown: the voters differ too much from every"
        " fitting source's (2024-06-08: okrsok 4: 1,000 voters then, 1,400 in"
    )


def test_stand_in_prefers_a_clean_source_to_a_nearer_outlier(project, presidential):
    """The EP election, nearer, has one okrsok beyond 25 %; the parliamentary
    one, farther, none: it stands in. Without it, the EP election's does."""
    election, votes = presidential
    votes[election.day].counts = {"500001": 10}
    write_ten(project, "2024-ep")
    write_ten(project, "2023-nrsr")
    votes[election.day].voters = {"500001": ten()}
    votes[dt.date(2024, 6, 8)].voters = {"500001": ten(k4=1400)}
    votes[dt.date(2023, 9, 30)].voters = {"500001": ten(k4=1100)}
    reuse.stand_in(project, election, votes)
    copy = stood_in(project, election)
    assert copy.okrsky_adoption.day == dt.date(2023, 9, 30)
    assert copy.okrsky_adoption.outliers == ()
    obvody.rules_path(
        project.election_dir(project.election("2023-nrsr")), "500001"
    ).unlink()
    reuse.stand_in(project, election, votes)
    copy = stood_in(project, election)
    assert copy.okrsky_adoption.day == dt.date(2024, 6, 8)
    assert copy.okrsky_adoption.outliers == ((4, 1000, 1400),)


def test_okrsky_beyond_plausible_allowed_by_size(project):
    """One okrsok of ten or more, two only of forty or more (5 %), none of nine."""
    e, s = project.election("2024-prezident"), project.election("2024-ep")
    then = {1: 1000, 2: 1000}
    one, two = {1: 1400, 2: 1000}, {1: 1400, 2: 600}
    assert reuse._okrsky_off(then, one, 9, e, s, lenient=True)[0] == (
        "okrsok 1: 1,000 voters then, 1,400 in 2024-06-08"
    )
    off, said, outliers = reuse._okrsky_off(then, one, 10, e, s, lenient=True)
    assert off is None and "okrsok 1 (1,000 → 1,400) differs" in said
    assert outliers == ((1, 1000, 1400),)
    assert reuse._okrsky_off(then, one, 10, e, s, lenient=False)[0]
    assert reuse._okrsky_off(then, two, 39, e, s, lenient=True)[0]
    off, said, _ = reuse._okrsky_off(then, two, 40, e, s, lenient=True)
    assert off is None and "okrsky 1 (1,000 → 1,400), 2 (1,000 → 600) differ" in said
    assert reuse._okrsky_off(then, then, 3, e, s, lenient=True) == (None, "", ())


def test_by_election_council_obvody_stand_in_only_from_its_term(project, monkeypatch):
    """A by-election in obvod 2 fills a seat of the council elected in 2022:
    the obvody of 2026 are another council's, however its rule set fits."""
    monkeypatch.setattr(reuse, "_okrsok_fit", lambda *_: [])
    by_election = project.election("2023-03")
    votes = all_votes(
        project,
        {"2023-03": [contest(2, 1)], "2022": [contest(1, 3), contest(2, 2)]},
    )
    write_places(project, by_election)
    write_okrsky(project, "2026")
    lines = reuse.stand_in(project, by_election, votes)
    assert lines[0] == (
        "Alfa (500001), obvody: unknown: no other vote has them of its own"
    )
    write_okrsky(project, "2022")
    lines = reuse.stand_in(project, by_election, votes)
    assert lines[0].startswith("Alfa (500001), obvody: from 2022-10-29 (2022)")
    copy = obvody.load_obec(project.election_dir(by_election), "500001")
    assert copy is not None and copy.adoption is not None
    assert copy.adoption.day == dt.date(2022, 10, 29)
    assert obvody.council_origin(copy) == {"adopted": "2022-10-29"}


def test_by_election_of_obvod_1_takes_its_term_s_stand_in(project, monkeypatch):
    """Obvod 1 alone, with its seats, of a council elected in 2022 in two
    (Divina, 2026-03): the 2022 rule set, itself 2026's standing in, draws
    it, named as 2026's borders; a regular election takes no stand-in."""
    monkeypatch.setattr(reuse, "_okrsok_fit", lambda *_: [])
    by_election = project.election("2023-03")
    votes = all_votes(
        project,
        {"2023-03": [contest(1, 3)], "2022": [contest(1, 3), contest(2, 2)]},
    )
    write_places(project, by_election)
    adoption = obvody.Adoption(dt.date(2026, 10, 24), "No 2022 document.")
    write_okrsky(project, "2022", {}, adoption=adoption)
    lines = reuse.stand_in(project, by_election, votes)
    assert lines[0].startswith("Alfa (500001), obvody: from 2022-10-29 (2022)")
    copy = obvody.load_obec(project.election_dir(by_election), "500001")
    assert copy is not None and copy.adoption is not None
    assert list(copy.seats) == [1, 2]
    assert copy.adoption.day == dt.date(2026, 10, 24)
    assert (
        "the council elected on 2022-10-29 (2022), whose seats the by-election"
        " fills, as that election draws them: with those of the vote of"
        " 2026-10-24, standing in there." in copy.adoption.basis
    )
    regular = project.election("2018")
    write_places(project, regular)
    regular_votes = all_votes(project, {"2018": [contest(1, 3), contest(2, 2)]})
    assert reuse.stand_in(project, regular, regular_votes)[0] == (
        "Alfa (500001), obvody: unknown: no other vote has them of its own"
    )


def test_council_elected_anew_inherits_no_term_obvody(project, monkeypatch):
    """A new election of the whole council (``vote`` ``"new"``) is not its
    term's: the term's rule set, 2026's standing in, does not draw it as a
    by-election proper's; the nearest regular election's own stands in,
    indicative, all its obvody those of the contests."""
    monkeypatch.setattr(reuse, "_okrsok_fit", lambda *_: [])
    by_election = project.election("2023-03")
    anew = [{**contest(1, 3), "vote": "new"}, {**contest(2, 2), "vote": "new"}]
    votes = all_votes(
        project, {"2023-03": anew, "2022": [contest(1, 3), contest(2, 2)]}
    )
    write_places(project, by_election)
    adoption = obvody.Adoption(dt.date(2026, 10, 24), "No 2022 document.")
    write_okrsky(project, "2022", {}, adoption=adoption)
    lines = reuse.stand_in(project, by_election, votes)
    assert lines[0] == (
        "Alfa (500001), obvody: unknown: no other vote has them of its own"
    )
    write_okrsky(project, "2026", {})
    lines = reuse.stand_in(project, by_election, votes)
    assert lines[0].startswith("Alfa (500001), obvody: from 2026-10-24 (2026)")
    copy = obvody.load_obec(project.election_dir(by_election), "500001")
    assert copy is not None and copy.adoption is not None
    assert copy.adoption.day == dt.date(2026, 10, 24)
    assert "the same obvody and seats" in copy.adoption.basis


def test_by_election_without_a_council_there_takes_okrsky_files_only(
    project, monkeypatch
):
    """A by-election electing a council elsewhere and only a mayor here: a
    council rule set would be taken for its council's (`ems addresses`
    checks it against the contests), so the referendum's, nearer, is passed
    over for the okrsky file of 2022."""
    monkeypatch.setattr(reuse, "_okrsok_fit", lambda *_: [])
    by_election = project.election("2023-03")
    mayor = {"id": "starosta:500001", "kind": "starosta", "area": "500001"}
    elsewhere = {"id": "oz:500002/1", "kind": "oz", "area": "500002", "seats": 5}
    votes = all_votes(project, {"2023-03": [mayor, elsewhere]})
    votes[by_election.day].counts = {"500001": 3}
    write_places(project, by_election)
    write_okrsky(project, "2023-referendum")
    tables = {
        "1": {"rules": [{"street": "Hlavná"}]},
        "2": {"rules": [{"street": "Krátka"}]},
        "3": {"rules": [{"rest": True}]},
    }
    data = {"obec": "500001", "name": "Alfa", "document": [DOCUMENT], "okrsok": tables}
    whole = obvody.okrsky_set(data, "test")
    write_rules(
        obvody.okrsky_path(project.election_dir(project.election("2022")), "500001"),
        whole,
    )
    lines = reuse.stand_in(project, by_election, votes)
    assert lines[0].startswith("Alfa (500001), okrsky: from 2022-10-29 (2022)")
    curated = project.election_dir(by_election)
    assert not obvody.rules_path(curated, "500001").exists()
    copy = obvody.load_obec(curated, "500001")
    assert copy is not None and copy.whole and copy.okrsky_adoption is not None
    assert (
        "2023-01-21: okrsky by council obvod, the vote electing no council there"
        in (copy.okrsky_adoption.basis)
    )
