import argparse
import dataclasses
import datetime as dt
import json
import shutil
from pathlib import Path

import pytest

from election_map_slovakia import cli, config, links
from election_map_slovakia.config import ConfigError
from election_map_slovakia.links import Candidates, LinksError, Overrides

EARLIER = dt.date(2022, 10, 29)
LATER = dt.date(2026, 10, 24)
# 3 years and 361 days apart: a candidate is 3 or 4 years older.
DAYS = {"2026": LATER, "2022": EARLIER}
ROOT = Path(__file__).resolve().parent.parent


def cand(
    cid: str, first: str, surname: str, age: int, residence: str = ""
) -> dict[str, object]:
    item: dict[str, object] = {
        "id": cid,
        "contest": cid.partition("#")[0],
        "first_name": first,
        "surname": surname,
        "age": age,
    }
    if residence:
        item["residence"] = residence
    return item


def lists(*persons: tuple[str, str, list[dict[str, object]]]) -> dict[str, list]:
    """Return a ``candidates.json`` of (person id, merge obec, candidacies)."""
    contests = {}
    candidacies = []
    for pid, _, cs in persons:
        for c in cs:
            contest = str(c["contest"])
            kind, _, area = contest.partition(":")
            contests[contest] = {"id": contest, "kind": kind, "area": area}
            candidacies.append({**c, "person": pid})
    return {
        "contests": list(contests.values()),
        "candidacies": candidacies,
        "persons": [
            {"id": pid, "obec": obec, "candidacies": [c["id"] for c in cs]}
            for pid, obec, cs in persons
        ],
    }


def match(later, earlier, overrides: Overrides | None = None) -> links.Links:
    return links.match(
        Candidates(LATER, later), Candidates(EARLIER, earlier), overrides
    )


def test_same_name_age_and_obec_link_and_same_office_is_listed():
    later = lists(
        (
            "l1",
            "500011",
            [
                cand("starosta:500011#1", "Jan", "Novak", 54),
                cand("oz:500011/1#3", "Jan", "Novak", 54),
            ],
        ),
        ("l2", "500011", [cand("oz:500011/2#1", "Eva", "Malá", 30)]),
    )
    earlier = lists(
        ("e1", "500011", [cand("oz:500011/3#5", "Ján", "Novák", 50)]),
        ("e2", "500411", [cand("oz:500411/1#1", "Eva", "Malá", 26)]),
    )
    result = match(later, earlier)
    assert result.persons == {"l1": "e1"}
    # The mayoral candidacy has no 2022 counterpart; the council one has,
    # in another obvod.
    assert result.candidacies == {"oz:500011/1#3": ["oz:500011/3#5"]}
    assert result.ambiguous == []


def test_age_off_by_a_year_more_only_when_nobody_fits_exactly():
    later = lists(
        ("l1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 55)]),
        ("l2", "500011", [cand("oz:500011/1#2", "Anna", "Hrubá", 40)]),
        ("l3", "500011", [cand("oz:500011/1#3", "Ivan", "Tichý", 40)]),
    )
    earlier = lists(
        ("e1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 50)]),
        ("e2", "500011", [cand("oz:500011/1#2", "Anna", "Hrubá", 37)]),
        ("e3", "500011", [cand("oz:500011/1#3", "Anna", "Hrubá", 38)]),
        ("e4", "500011", [cand("oz:500011/1#4", "Ivan", "Tichý", 34)]),
    )
    result = match(later, earlier)
    # Kováč is 5 years older: a year off, and nobody else fits. Hrubá fits
    # 37 exactly (3 years) and 38 only a year off; Tichý is 6 years older.
    assert result.persons == {"l1": "e1", "l2": "e2"}
    assert result.ambiguous == []


def test_namesakes_link_nobody():
    later = lists(
        ("l1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 55)]),
        ("l2", "500411", [cand("oz:500411/1#1", "Jana", "Biela", 40)]),
        ("l3", "500411", [cand("oz:500411/1#2", "Jana", "Biela", 40)]),
    )
    earlier = lists(
        ("e1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 51)]),
        ("e2", "500011", [cand("oz:500011/1#2", "Peter", "Kováč", 51)]),
        ("e3", "500411", [cand("oz:500411/1#1", "Jana", "Biela", 36)]),
    )
    result = match(later, earlier)
    # Two earlier Kováč fit one later one; two later Biela claim one earlier.
    assert result.persons == {}
    assert len(result.ambiguous) == 3


def test_the_better_fit_wins_a_shared_earlier_person():
    later = lists(
        ("l1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 55)]),
        ("l2", "500011", [cand("oz:500011/1#2", "Peter", "Kováč", 56)]),
    )
    earlier = lists(("e1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 51)]))
    result = match(later, earlier)
    # 56 is a year off: the earlier person fits 55 exactly, and only that.
    assert result.persons == {"l1": "e1"}
    assert len(result.ambiguous) == 1


def test_municipal_candidacies_need_the_same_obec():
    later = lists(("l1", "500411", [cand("oz:500411/1#1", "Peter", "Kováč", 55)]))
    earlier = lists(
        ("e1", "500011", [cand("zsk:4/3#1", "Peter", "Kováč", 51, "500011")])
    )
    assert match(later, earlier).persons == {}


def test_regional_candidacies_link_within_the_kraj_residence_breaking_ties():
    later = lists(
        ("l1", "500011", [cand("zsk:4/1#2", "Peter", "Kováč", 55, "500011")]),
        ("l2", "500411", [cand("zsk:4/2#7", "Jana", "Biela", 40, "500411")]),
        # A mayor of 500011 who stood for the kraj from 500011 in 2022.
        ("l3", "500011", [cand("starosta:500011#3", "Ivan", "Tichý", 40)]),
    )
    earlier = lists(
        ("e1", "500011", [cand("zsk:4/3#5", "Peter", "Kováč", 51, "500011")]),
        ("e2", "500411", [cand("zsk:4/2#1", "Peter", "Kováč", 51, "500411")]),
        ("e3", "500011", [cand("zsk:4/3#9", "Jana", "Biela", 36, "500011")]),
        ("e4", "500011", [cand("zsk:4/3#1", "Ivan", "Tichý", 36, "500011")]),
    )
    result = match(later, earlier)
    # Kováč fits both by kraj, the one living in the same obec wins; Biela
    # moved within the kraj.
    assert result.persons == {"l1": "e1", "l2": "e3", "l3": "e4"}
    assert result.candidacies == {
        "zsk:4/1#2": ["zsk:4/3#5"],
        "zsk:4/2#7": ["zsk:4/3#9"],
    }


def test_bratislava_districts_count_as_the_city():
    later = lists(
        (
            "l1",
            "BA",
            [
                cand("oz:528595/2#9", "Peter", "Kováč", 55),
                cand("oz:BA/3#7", "Peter", "Kováč", 55),
            ],
        )
    )
    earlier = lists(
        (
            "e1",
            "BA",
            [
                cand("starosta:529320#1", "Peter", "Kováč", 51),
                cand("oz:528595/1#4", "Peter", "Kováč", 51),
            ],
        )
    )
    result = match(later, earlier)
    assert result.persons == {"l1": "e1"}
    # The city council is another office than a district's.
    assert result.candidacies == {"oz:528595/2#9": ["oz:528595/1#4"]}


def test_one_person_spelt_two_ways_links_by_office_then_spelling():
    later = lists(
        ("l1", "525146", [cand("oz:525146/2#3", "Jozef", "Kolarčík", 46)]),
        ("l2", "501352", [cand("zsk:4/1#1", "Jaroslav", "Adrian", 47, "501352")]),
        ("l3", "501352", [cand("starosta:501352#1", "Jaroslav", "Adrián", 47)]),
    )
    earlier = lists(
        ("e1", "525146", [cand("oz:525146/2#3", "Jozef", "Kolárčik", 42)]),
        ("e2", "525146", [cand("zsk:7/8#16", "Jozef", "Kolarčík", 42, "525146")]),
        ("e3", "501352", [cand("oz:501352/1#1", "Jaroslav", "Adrián", 43)]),
    )
    result = match(later, earlier)
    # Kolarčík stood for the same council again; Adrián is spelt alike.
    assert result.persons == {"l1": "e1", "l3": "e3"}
    assert len(result.ambiguous) == 1


def test_overrides_link_and_unlink():
    later = lists(
        ("l1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 55)]),
        ("l2", "500411", [cand("oz:500411/1#1", "Jana", "Biela", 40)]),
        ("l3", "500411", [cand("oz:500411/1#2", "Ivan", "Tichý", 40)]),
    )
    earlier = lists(
        ("e1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 51)]),
        ("e2", "500011", [cand("oz:500011/1#2", "Peter", "Kováč", 51)]),
        ("e3", "500011", [cand("oz:500011/1#3", "Jana", "Bielová", 36)]),
        ("e4", "500411", [cand("oz:500411/1#4", "Ivan", "Tichý", 36)]),
    )
    overrides = Overrides(
        link=(("oz:500411/1#1", "oz:500011/1#3"),),
        unlink=(("oz:500011/1#1", "oz:500011/1#2"), ("oz:500411/1#2", "oz:500411/1#4")),
    )
    result = match(later, earlier, overrides)
    # Biela married and moved; of the two Kováč one is unlinked, leaving
    # the other; Tichý is not the one of 2022.
    assert result.persons == {"l1": "e1", "l2": "e3"}
    assert result.overridden == 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (Overrides(link=(("oz:500011/1#9", "oz:500011/1#1"),)), "no later candidacy"),
        (Overrides(unlink=(("oz:500011/1#1", "oz:500011/1#9"),)), "no earlier"),
        (
            Overrides(
                link=(
                    ("oz:500011/1#1", "oz:500011/1#1"),
                    ("oz:500011/1#2", "oz:500011/1#1"),
                )
            ),
            "earlier person linked twice",
        ),
        (
            Overrides(
                link=(("oz:500011/1#1", "oz:500011/1#1"),),
                unlink=(("oz:500011/1#1", "oz:500011/1#1"),),
            ),
            "linked and unlinked",
        ),
    ],
)
def test_contradictory_overrides_fail(overrides, message):
    later = lists(
        ("l1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 55)]),
        ("l2", "500011", [cand("oz:500011/1#2", "Jana", "Biela", 40)]),
    )
    earlier = lists(("e1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 51)]))
    with pytest.raises(LinksError, match=message):
        match(later, earlier, overrides)


def test_to_json():
    later = lists(("l1", "500011", [cand("oz:500011/1#1", "Peter", "Kováč", 55)]))
    earlier = lists(
        ("e1", "500011", [cand("oz:500011/2#4", "Peter", "Kováč", 51)]),
        ("e2", "500411", [cand("oz:500411/1#1", "Jana", "Biela", 36)]),
    )
    assert links.to_json(match(later, earlier)) == {
        "earlier": "2022-10-29",
        "method": "name-age-area",
        "persons": {"l1": "e1"},
        "candidacies": {"oz:500011/1#1": ["oz:500011/2#4"]},
        "counts": {
            "persons": 1,
            "earlier_persons": 2,
            "linked": 1,
            "overridden": 0,
            "ambiguous": 0,
            "same_office": 1,
        },
    }


def test_load_overrides(tmp_path):
    path = tmp_path / "links.toml"
    path.write_text(
        "[2026.2022]\n"
        'link = [["oz:528595/2#7", "oz:528595/1#3"]]\n'
        'unlink = [["zsk:7/2#9", "zsk:7/1#30"]]\n'
    )
    assert links.load_overrides(path, DAYS) == {
        ("2026", "2022"): Overrides(
            link=(("oz:528595/2#7", "oz:528595/1#3"),),
            unlink=(("zsk:7/2#9", "zsk:7/1#30"),),
        )
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[2030.2022]\n", "2030: expected a table named by a slug"),
        ("[2022.2026]\n", "2026 is not before 2022"),
        ("[2026.2022]\nlinks = []\n", "unknown key"),
        ('[2026.2022]\nlink = [["oz:528595/2#7"]]\n', "not a pair of candidacy ids"),
        ('[2026.2022]\nunlink = [["oz:1/2#7", "oz:528595/1#3"]]\n', "not a pair"),
        ("[2026.2022\n", "invalid TOML"),
    ],
)
def test_load_overrides_rejects(tmp_path, text, message):
    path = tmp_path / "links.toml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        links.load_overrides(path, DAYS)


def test_the_overrides_file_loads():
    elections = config.load(ROOT / "config").elections
    links.load_overrides(
        ROOT / "config" / links.LINKS_FILE, {e.slug: e.day for e in elections}
    )


def test_each_pair_of_elections_takes_its_own_overrides(tmp_path, monkeypatch):
    """`ems links` corrects the links of the later election to each earlier
    one by the table of that pair alone."""
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(ROOT / config.PARTY_LOGO_DIR, tmp_path / config.PARTY_LOGO_DIR)
    cfg = config.load(tmp_path / "config")
    older = dataclasses.replace(
        cfg.election("2022"), day=dt.date(2018, 11, 10), slug="2018"
    )
    cfg = dataclasses.replace(cfg, elections=(*cfg.elections, older))
    lists_of = {
        "2026": lists(("l2", "500411", [cand("oz:500411/1#1", "Jana", "Biela", 40)])),
        "2022": lists(("e3", "500011", [cand("oz:500011/1#3", "Jana", "Bielová", 36)])),
        "2018": lists(("f3", "500011", [cand("oz:500011/1#5", "Jana", "Bielová", 32)])),
    }
    for e in cfg.elections:
        path = cfg.election_build_dir(e) / "candidates.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(lists_of[e.slug]))
    (tmp_path / "config" / links.LINKS_FILE).write_text(
        '[2026.2022]\nlink = [["oz:500411/1#1", "oz:500011/1#3"]]\n'
        '[2022.2018]\nlink = [["oz:500011/1#3", "oz:500011/1#5"]]\n'
    )
    monkeypatch.chdir(tmp_path)
    assert cli._links(cfg, cfg.latest, argparse.Namespace(force=False)) == 0
    out = cfg.election_build_dir(cfg.latest) / "links"
    assert json.loads((out / "2022.json").read_text())["persons"] == {"l2": "e3"}
    # Nothing corrects 2026 to 2018: the rule, which does not link them.
    assert json.loads((out / "2018.json").read_text())["persons"] == {}
    assert cli._links(cfg, cfg.election("2022"), argparse.Namespace(force=False)) == 0
    out = cfg.election_build_dir(cfg.election("2022")) / "links"
    assert json.loads((out / "2018.json").read_text())["persons"] == {"e3": "f3"}
