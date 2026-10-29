"""The crosswalk: the okrsky of a later election on those of an earlier one."""

import datetime as dt
import json
from pathlib import Path

import pytest

from election_map_slovakia import addresses, crosswalk, results
from election_map_slovakia.candidates import Admin
from election_map_slovakia.results import APPROXIMATE, IDENTITY, SAME, UNKNOWN

DAY = dt.date(2022, 10, 29)
# The registers are read by a stand-in (register_rows), which names no obce.
ADMIN = Admin({}, {}, {})


def test_identity_by_number_and_registered_voters():
    """Without addresses, an obec of the same okrsok numbers as then, each
    with registered voters within 10 % of its own then, keeps them."""
    same = crosswalk.walk_obec({1: 110, 2: 90}, {1: 100, 2: 100}, None)
    assert same.how == crosswalk.BY_NUMBER
    assert same.okrsky == {1: (IDENTITY, {1: 1.0}), 2: (IDENTITY, {2: 1.0})}
    moved = crosswalk.walk_obec({1: 111, 2: 100}, {1: 100, 2: 100}, None)
    assert moved.how == crosswalk.NONE
    assert moved.okrsky == {1: (UNKNOWN, {}), 2: (UNKNOWN, {})}


def test_unknown_where_the_okrsky_changed():
    renumbered = crosswalk.walk_obec({1: 100, 2: 100, 3: 50}, {1: 120, 2: 130}, None)
    assert renumbered.how == crosswalk.NONE
    assert {m for m, _ in renumbered.okrsky.values()} == {UNKNOWN}
    # An obec without results then (Krušovce in 2022).
    assert crosswalk.walk_obec({1: 100, 2: 90}, None, None).how == crosswalk.NONE
    # One okrsok now: the whole obec, every okrsok then.
    merged = crosswalk.walk_obec({1: 300}, {1: 100, 2: 200}, None)
    assert merged.how == crosswalk.WHOLE
    assert merged.okrsky == {1: (SAME, {1: 1.0, 2: 1.0})}


# Okrsok 1 then split 60/40 into 1 and 2 now; 2 then wholly in 2 now; 3
# then nearly all of 3 now, which has nothing else: the same area.
PAIRS = {(1, 1): 60, (1, 2): 40, (2, 2): 50, (3, 3): 97, (3, 2): 3}


def test_addresses_split_an_okrsok_60_40():
    w = crosswalk.walk_obec({1: 70, 2: 110, 3: 100}, {1: 100, 2: 60, 3: 100}, PAIRS)
    assert w.how == crosswalk.ADDRESSES
    assert w.okrsky[1] == (APPROXIMATE, {1: 0.6})
    method, sources = w.okrsky[2]
    assert method == APPROXIMATE
    assert sources == pytest.approx({1: 0.4, 2: 1.0, 3: 0.03})
    assert w.okrsky[3] == (SAME, {3: 1.0})
    # Addresses come first: the numbers would match too.
    w = crosswalk.walk_obec({1: 100, 2: 100}, {1: 100, 2: 100}, {(1, 2): 9, (2, 1): 9})
    assert w.how == crosswalk.ADDRESSES
    assert w.okrsky == {1: (SAME, {2: 1.0}), 2: (SAME, {1: 1.0})}
    # An okrsok now without a paired address is not known.
    w = crosswalk.walk_obec({1: 100, 2: 5}, {1: 100}, {(1, 1): 9})
    assert w.okrsky == {1: (SAME, {1: 1.0}), 2: (UNKNOWN, {})}


def lives() -> tuple[results.Live, results.Live]:
    """The results of an obec of three okrsky then and now, by PAIRS."""
    then = results.Live("final")
    then.add_okrsky(
        "okres/101",
        "starosta:500001",
        {
            "500001/1": (1000, 500, 490, {5: 300, 6: 190}),
            "500001/2": (600, 300, 295, {5: 100, 6: 195}),
            "500001/3": (500, 200, 198, {5: 50, 6: 148}),
        },
    )
    then.add_okrsky(
        "okres/101",
        "oz:500001/1",
        {
            "500001/1": (1000, 500, 480, {1: 200, 2: 100}),
            "500001/2": (600, 300, 290, {1: 50, 2: 70}),
        },
    )
    then.add_okrsky(
        "okres/101", "oz:500001/2", {"500001/3": (500, 200, 190, {1: 100, 2: 30})}
    )
    now = results.Live("final")
    now.add_okrsky(
        "okres/101",
        "starosta:500001",
        {f"500001/{n}": (700, 300, 290, {1: 100, 2: 190}) for n in (1, 2, 3)},
    )
    now.add_okrsky(
        "okres/101", "oz:500001/1", {"500001/1": (700, 300, 280, {1: 50, 2: 60})}
    )
    now.add_okrsky(
        "okres/101",
        "oz:500001/2",
        {n: (700, 300, 280, {1: 50, 2: 60}) for n in ("500001/2", "500001/3")},
    )
    return now, then


def test_past_estimates_the_figures_then_by_the_weights():
    """The 2022 figures of every okrsok of known method, weighed, and of the
    obec wherever all its okrsky are in a contest; the votes of the
    candidates who stood for the same body then, by their numbers now."""
    now, then = lives()
    walk = crosswalk.build(
        crosswalk.okrsky_of(now), crosswalk.okrsky_of(then), {"500001": PAIRS}, DAY
    )
    linked = {
        "starosta:500001#2": ["starosta:500001#5"],
        # A councillor who stood in obvod 2 then: not on the ballot of 1.
        "oz:500001/2#1": ["oz:500001/2#2"],
    }
    past = crosswalk.past(now, then, walk, linked)
    assert past.day == "2022-10-29"
    assert past.methods == {
        "500001/1": APPROXIMATE,
        "500001/2": APPROXIMATE,
        "500001/3": SAME,
    }
    mayor = past.contests["starosta:500001"]
    assert mayor["500001/1"] == (600, 300, 294, {2: 180})
    # 0.4 of 1, all of 2, 0.03 of 3.
    assert mayor["500001/2"] == (1015, 506, 497, {2: 222})
    assert mayor["500001/3"] == (500, 200, 198, {2: 50})
    assert mayor["500001"] == (2100, 1000, 983, {2: 450})
    council = past.contests["oz:500001/2"]
    # The votes where the councillor was on the ballot: 0.03 of okrsok 3.
    assert council["500001/2"] == (1015, 506, 488, {1: 1})
    assert council["500001/3"] == (500, 200, 190, {1: 30})
    assert "500001" not in council
    assert past.contests["oz:500001/1"] == {"500001/1": (600, 300, 288, {})}
    # Only a whole body has its contest's own figures then, whatever its
    # units add up to.
    assert past.totals == {}
    then.add(
        "obec/500001",
        "starosta:500001",
        results.Record("final", None, 2200, 1100, 1083, None, None, [(5, 500, 1)]),
    )
    then.add("obec/500001", "oz:500001/1", results.Record("final", None, 1, 1, 1))
    past = crosswalk.past(now, then, walk, linked)
    assert past.totals == {"starosta:500001": (2200, 1100, 1083, {2: 500})}


def test_past_unknown_where_an_okrsok_then_has_no_figures_of_the_body():
    """An okrsok then without the body's figures (Košice's okrsky whose
    council votes cannot be told apart) leaves every unit it is part of
    without them, not short by its share."""
    now, then = lives()
    then.add_okrsky("okres/101", "oz:500001/2", {})
    walk = crosswalk.build(
        crosswalk.okrsky_of(now), crosswalk.okrsky_of(then), {"500001": PAIRS}, DAY
    )
    past = crosswalk.past(now, then, walk, {})
    assert "oz:500001/2" not in past.contests
    assert past.contests["oz:500001/1"] == {"500001/1": (600, 300, 288, {})}
    assert past.contests["starosta:500001"]["500001"] == (2100, 1000, 983, {})


def test_obvody_counted_by_their_least_certain_okrsok():
    now, then = lives()
    walk = crosswalk.build(
        crosswalk.okrsky_of(now), crosswalk.okrsky_of(then), {"500001": PAIRS}, DAY
    )
    assert crosswalk.map_obvody(walk, crosswalk.contest_okrsky(now, "oz")) == {
        "oz:500001/1": "approximate",
        "oz:500001/2": "approximate",
    }
    assert crosswalk.map_obvody(
        walk,
        {
            "oz:500001/1": ["500001/3"],
            # An obvod of whole obce, and one of an obec unknown then.
            "oz:500001/2": ["500001/1", "500001/2", "500001/3"],
            "oz:500002/1": ["500002/1"],
        },
    ) == {"oz:500001/1": "same", "oz:500001/2": "whole", "oz:500002/1": "unknown"}


def test_addresses_paired_by_id_then_by_street_and_number(tmp_path, monkeypatch):
    """An address is the same by its id in both registers; one whose id is
    new by its street and house number, where only one has them."""
    rows = {
        "then": [("a1", "A", "1"), ("a2", "A", "2"), ("a3", "A", "3")],
        "now": [("a1", "A", "1"), ("a2", "A", "2"), ("x3", "A", "3"), ("n4", "B", "1")],
    }

    def register_rows(path, *_):
        for i, (ident, street, number) in enumerate(rows[path.name]):
            yield addresses.Row(ident, "500001", "X", street, number, "", "", "", i)

    monkeypatch.setattr(addresses, "register_rows", register_rows)
    files = {
        "then": {
            "streets": [{"name": "A", "numbers": ["1", "2", "3"], "okrsky": [1, 1, 2]}]
        },
        "now": {
            "streets": [
                {"name": "A", "numbers": ["1", "2", "3"], "okrsok": 1},
                {"name": "B", "numbers": ["1"], "okrsok": 2},
            ]
        },
    }
    registers = []
    for name, content in files.items():
        addr = tmp_path / name / "addr"
        addr.mkdir(parents=True)
        (addr / "500001.json").write_text(json.dumps(content))
        registers.append(crosswalk.Register(Path(name), ADMIN, {}, (), addr))
    okrsky = ({"500001": {1: 10, 2: 5}}, {"500001": {1: 10, 2: 5}})
    pairs, paired = crosswalk.address_pairs(registers, okrsky)
    assert pairs == {"500001": {(1, 1): 2, (2, 1): 1}}
    assert paired == {"id": 2, "street": 1, "unpaired": 1}
    # An obec placed by address in one election only is left to the numbers.
    (tmp_path / "then" / "addr" / "500001.json").write_text(json.dumps({"streets": []}))
    assert crosswalk.address_pairs(registers, okrsky)[0] == {}
