"""Okrsok jobs of a vote other than a regular election: a country-wide one, a by-election."""

import datetime as dt
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from election_map_slovakia import (
    candidates,
    config,
    division,
    jobs,
    obvodrules,
    obvody,
    okrsokrules,
)

REPO = Path(__file__).resolve().parent.parent
DOCUMENT = {"url": "https://alfa.sk/u.pdf", "sha256": "0" * 64, "title": "Určenie"}
PRESIDENTIAL = "2024-prezident"
BY_ELECTION = "2023-03"


@pytest.fixture
def cfg(tmp_path: Path) -> config.Config:
    shutil.copytree(REPO / "config", tmp_path / "config")
    shutil.copytree(REPO / config.PARTY_LOGO_DIR, tmp_path / config.PARTY_LOGO_DIR)
    return config.load(tmp_path / "config")


def write_units(cfg: config.Config, e: config.Election, counts: dict[str, int]) -> None:
    """Write *e*'s territorial division: obec → okrsky."""
    units = division.units_of(e)
    inp = next(i for i in cfg.inputs.inputs if i.name == units.input)
    path = cfg.raw_dir / inp.name / inp.file
    path.parent.mkdir(parents=True)
    table = "Kód obce;Počet okrskov\n" + "".join(
        f"{c};{n}\n" for c, n in counts.items()
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"X_{units.table}.csv", table.encode("cp1250"))


def write_candidates(
    cfg: config.Config, e: config.Election, codes: list[str], contests: list[dict]
) -> None:
    obce = [
        {"code": c, "name": f"Obec {c}", "okres": "101", "kraj": "1"} for c in codes
    ]
    data = {
        "obce": obce,
        "okresy": [{"code": "101", "name": "Okres"}],
        "kraje": [{"code": "1", "name": "Kraj"}],
        "contests": contests,
    }
    path = cfg.election_build_dir(e) / candidates.OUTPUT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_places(cfg: config.Config, e: config.Election, codes: list[str]) -> None:
    """Write each obec's addresses: Hlavná 1, Krátka 2, Lúčna 3."""
    places = [
        obvody.Place("Hlavná", "Alfa", "1", ""),
        obvody.Place("Krátka", "Alfa", "2", ""),
        obvody.Place("Lúčna", "Alfa", "3", ""),
    ]
    p = obvody.ObecPlaces(places, np.full((3, 2), float("nan")), [None] * 3, [])
    obvody.write_places(
        dict.fromkeys(codes, p.to_json()), obvodrules.places_dir(cfg, e)
    )


def write_okrsky(cfg: config.Config, e: config.Election, contests: dict) -> None:
    """Write *e*'s final results per okrsok: contest → okrsok → [eligible, …]."""
    path = cfg.results_dir(e) / "okrsky" / "okres" / "101.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"contests": contests, "past": {}}), encoding="utf-8")


def council(code: str, **extra: Any) -> dict[str, Any]:
    """Return the rule set of obec *code*: obvod 1 Hlavná, Krátka; 2 the rest."""
    return {
        "obec": code,
        "name": f"Obec {code}",
        "date": dt.date(2022, 6, 1),
        "document": [DOCUMENT],
        "obvod": {
            "1": {"seats": 3, "rules": [{"street": "Hlavná"}, {"street": "Krátka"}]},
            "2": {"seats": 2, "rules": [{"rest": True}]},
        },
        **extra,
    }


def whole(code: str, **extra: Any) -> dict[str, Any]:
    """Return the okrsky of obec *code*: 1 Hlavná, 2 the rest."""
    return {
        "obec": code,
        "name": f"Obec {code}",
        "document": [DOCUMENT],
        "okrsok": {
            "1": {"rules": [{"street": "Hlavná"}]},
            "2": {"rules": [{"rest": True}]},
        },
        **extra,
    }


def write(path: Path, rules: obvody.RuleSet) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obvody.dump(rules, ["a header"]), encoding="utf-8")


COPY = {"okrsky_reused": dt.date(2022, 10, 29), "okrsky_note": "copied"}


def presidential(cfg: config.Config) -> config.Election:
    """Set up the 2024 presidential election of five obce.

    500001, of three okrsky, has those of 2022 copied with the council
    rule set placing them; 500002 has its own; 500003 votes in one okrsok;
    500004 has none; 500005 has a copy, its own document not found.
    """
    e = cfg.election(PRESIDENTIAL)
    codes = ["500001", "500002", "500003", "500004", "500005"]
    write_units(
        cfg, e, {"500001": 3, "500002": 2, "500003": 1, "500004": 2, "500005": 2}
    )
    write_candidates(
        cfg,
        e,
        codes,
        [{"id": "prezident:SK/1", "kind": "prezident", "area": "SK", "obvod": 1}],
    )
    write_places(cfg, e, codes)
    rounds = {
        "prezident:SK/1": {"500001/1": [900, 1, 1, {}], "500001/2": [450, 1, 1, {}]},
        "prezident:SK/2": {"500001/1": [905, 1, 1, {}]},
    }
    write_okrsky(cfg, e, rounds)
    curated = cfg.election_dir(e)
    copied = council("500001", reused=dt.date(2022, 10, 29), note="copied", **COPY)
    copied["obvod"]["1"]["okrsky"] = [1, 2]
    copied["obvod"]["2"]["okrsky"] = [3]
    copied["okrsok"] = {
        "1": {"rules": [{"street": "Hlavná"}]},
        "2": {"rules": [{"street": "Krátka"}]},
    }
    write(obvody.rules_path(curated, "500001"), obvody.rule_set(copied, "test"))
    write(
        obvody.okrsky_path(curated, "500002"),
        obvody.okrsky_set(whole("500002"), "test"),
    )
    write(
        obvody.okrsky_path(curated, "500005"),
        obvody.okrsky_set(whole("500005", **COPY), "test"),
    )
    tried = {"name": "Obec 500005", "job": "x", "tried": ["https://a.sk/"], "note": ""}
    jobs.write_json(okrsokrules.not_found_path(cfg, e), {"500005": tried})
    return e


def make(cfg: config.Config, e: config.Election, *only: str) -> list[jobs.Job]:
    return jobs.make(cfg, jobs.kinds()[okrsokrules.NAME], election=e, only=only)


def test_items_of_a_vote_without_councils_include_copies(cfg):
    """Every obec voting in several okrsky without its own: a copy (even one
    a council rule set places) is an item as a whole obec, to be replaced;
    its own okrsky, one okrsok, or a document not found are not."""
    e = presidential(cfg)
    made = make(cfg, e)
    items = {i["id"]: i for j in made for i in j.items}
    assert set(items) == {"500001", "500004"}
    first = items["500001"]
    assert "obvody" not in first
    assert first["okrsky"] == 3
    assert (
        first["vote"]
        == "the presidential election of 23 March 2024 (round 2: 6 April 2024)"
    )
    # Round 1's voters, of the okrsky the results have.
    assert first["voters"] == {"1": 900, "2": 450}
    assert first["copied"]["from"] == "2022-10-29"
    assert first["copied"]["documents"][0]["url"] == DOCUMENT["url"]
    assert "voľba prezidenta" in first["search"][0]
    assert "voters" not in items["500004"] and "copied" not in items["500004"]
    prompt = (made[0].path / jobs.PROMPT).read_text(encoding="utf-8")
    assert "the presidential election of 23 March 2024" in prompt
    assert "## A past vote" in prompt and "## An earlier election" not in prompt
    assert '"voľba prezidenta Slovenskej republiky 2024"' in prompt
    assert "## The referendum" not in prompt
    (again,) = make(cfg, e, "500005", "500002")[:1]
    assert {i["id"] for i in again.items} <= {"500002", "500005"}


def test_by_election_items_only_where_held(cfg):
    """A by-election's obce are those with a contest; one with a council
    contest and its council's rule set gets its okrsky by obvod, checked
    against the okrsky of the obvody that voted."""
    e = cfg.election(BY_ELECTION)
    codes = ["500001", "500004", "500006"]
    write_units(cfg, e, {"500001": 2, "500004": 3, "500006": 2})
    contests = [
        {"id": "starosta:500001", "kind": "starosta", "area": "500001", "obvod": None},
        {"id": "oz:500004/2", "kind": "oz", "area": "500004", "obvod": 2},
    ]
    write_candidates(cfg, e, codes, contests)
    write_places(cfg, e, codes)
    write_okrsky(
        cfg,
        e,
        {
            "starosta:500001": {
                "500001/1": [700, 1, 1, {}],
                "500001/2": [650, 1, 1, {}],
            },
            "oz:500004/2": {"500004/3": [800, 1, 1, {}]},
        },
    )
    rules = obvody.rule_set(council("500004"), "test")
    write(obvody.rules_path(cfg.election_dir(e), "500004"), rules)
    items = {i["id"]: i for j in make(cfg, e) for i in j.items}
    assert set(items) == {"500001", "500004"}
    assert items["500001"]["voters"] == {"1": 700, "2": 650}
    assert "obvody" not in items["500001"]
    obvody_of = {o["number"]: o for o in items["500004"]["obvody"]}
    assert "okrsky" not in obvody_of[1] and obvody_of[2]["okrsky"] == [3]
    with_okrsky = council("500004")
    with_okrsky["obvod"]["1"]["okrsky"] = [1, 2]
    with_okrsky["obvod"]["2"]["okrsky"] = [3]
    given = obvody.rule_set(with_okrsky, "test")
    units = {2: {3: 800}}
    assert okrsokrules.grouping_problems(given, units, every=False) == []
    assert okrsokrules.grouping_problems(given, units) == [
        "obvod 1: okrsky 1, 2 given, the Statistical Office's results count none"
    ]


def test_okrsky_of_a_vote_without_councils_checked_against_units_and_voters(cfg):
    """As many okrsky as the territorial division has; the voters of
    the okrsky that voted give the plausibility notes."""
    e = cfg.election(PRESIDENTIAL)
    item = {"id": "500001", "okrsky": 3, "voters": {"1": 300, "2": 300, "3": 300}}
    three = whole("500001")
    three["okrsok"] = {
        "1": {"rules": [{"street": "Hlavná"}]},
        "2": {"rules": [{"street": "Krátka"}]},
        "3": {"rules": [{"rest": True}]},
    }
    rules = obvody.okrsky_set(three, "test")
    units, problems = okrsokrules._count_problems(cfg, e, item, rules)
    assert problems == [] and units == {1: {1: 300, 2: 300, 3: 300}}
    two = obvody.okrsky_set(whole("500001"), "test")
    assert okrsokrules._count_problems(cfg, e, item, two)[1] == [
        "2 okrsky given, the territorial division has 3"
    ]
    placed = obvody.Assignment([1] * 90 + [2] * 5 + [3] * 5, [None] * 100)
    assert okrsokrules.okrsok_plausibility(rules, placed, units) == [
        "plausibility: okrsok 2 has 5% of the addresses (5) but 33% of the voters (300)",
        "plausibility: okrsok 3 has 5% of the addresses (5) but 33% of the voters (300)",
    ]


def test_not_found_keeps_a_copy_and_own_okrsky_replace_it(cfg):
    e = presidential(cfg)
    curated = cfg.election_dir(e)
    (job,) = [j for j in make(cfg, e) if j.items[0]["id"] == "500001"]
    item = job.items[0]
    not_found = {"id": "500001", "status": "not_found", "tried": ["https://alfa.sk/"]}
    lines = okrsokrules.accept(cfg, job, [(item, not_found)])
    assert "Obec 500001 (500001): its copied okrsky stay" in lines
    copy = obvody.load_obec(curated, "500001")
    assert copy is not None and copy.okrsky_reused == dt.date(2022, 10, 29)
    assert "500001" in okrsokrules.load_not_found(cfg, e)
    # Its own document, found after all, replaces the copy and the rule set
    # that placed it.
    name = f"{'1' * 64}.pdf"
    documents = job.path / obvodrules.DOCUMENTS_DIR
    documents.mkdir()
    (documents / name).write_bytes(b"%PDF")
    jobs.write_json(documents / "index.json", {"https://alfa.sk/okrsky.pdf": name})
    found = {
        "id": "500001",
        "status": "found",
        "tried": [],
        "website": "https://alfa.sk/",
        "documents": [{"url": "https://alfa.sk/okrsky.pdf", "title": "Určenie"}],
        "date": "2024-01-20",
        "okrsky": [
            {"number": 1, "text": "Hlavná", "rules": [{"street": "Hlavná"}]},
            {"number": 2, "text": "Krátka", "rules": [{"street": "Krátka"}]},
            {"number": 3, "text": "ostatné", "rules": [{"rest": True}]},
        ],
    }
    lines = okrsokrules.accept(cfg, job, [(item, found)])
    assert not obvody.rules_path(curated, "500001").exists()
    own = obvody.load_obec(curated, "500001")
    assert own is not None and own.whole and okrsokrules.own(own)
    assert "500001" not in okrsokrules.load_not_found(cfg, e)
    # Reported not found again, its own okrsky go.
    okrsokrules.accept(cfg, job, [(item, not_found)])
    assert obvody.load_obec(curated, "500001") is None
