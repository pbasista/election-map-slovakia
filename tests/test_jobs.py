import dataclasses
import datetime as dt
import json
import shutil
from pathlib import Path

import pytest

from election_map_slovakia import candidates, config, jobs, translate

REPO = Path(__file__).resolve().parent.parent

OCCUPATIONS = ["učiteľka", "učiteľka", "SZČO", "vodič"]


def write_candidates(
    cfg: config.Config, e: config.Election, occupations: list[str]
) -> None:
    path = cfg.election_build_dir(e) / candidates.OUTPUT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    candidacies = [{"occupation": o} for o in occupations]
    path.write_text(json.dumps({"candidacies": candidacies}, ensure_ascii=False))


def project(root: Path) -> config.Config:
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / "web" / "i18n", root / "web" / "i18n")
    shutil.copytree(REPO / config.PARTY_LOGO_DIR, root / config.PARTY_LOGO_DIR)
    cfg = config.load(root / "config")
    for e in cfg.elections:
        write_candidates(cfg, e, OCCUPATIONS)
    return cfg


def make(cfg: config.Config, *only: str) -> list[jobs.Job]:
    return jobs.make(cfg, jobs.kinds()["translation"], election=cfg.latest, only=only)


def write_output(job: jobs.Job, items: object) -> None:
    (job.path / jobs.OUTPUT).write_text(
        json.dumps({"items": items}, ensure_ascii=False)
    )


CS = {"učiteľka": "učitelka", "SZČO": "OSVČ", "vodič": "řidič"}


def answers(job: jobs.Job) -> list[dict[str, str]]:
    return [{"id": i["id"], "text": CS[i["source"]]} for i in job.items]


def test_schema_problems_reject_only_their_item(tmp_path: Path):
    cfg = project(tmp_path)
    (job,) = make(cfg, "cs", "occupations")
    good, missing_text, extra = answers(job)
    write_output(
        job,
        [
            good,
            {"id": missing_text["id"]},
            extra | {"note": "x"},
            {"id": "nope", "text": "x"},
        ],
    )
    report = jobs.ingest(cfg, job.path)
    assert report.accepted == 1
    assert set(report.rejected) == {missing_text["id"], extra["id"], "nope"}
    assert "missing required property 'text'" in report.rejected[missing_text["id"]][0]
    assert report.missing == []
    assert not report.ok
    assert "## Rejected" in (job.path / jobs.REPORT).read_text()


@pytest.mark.parametrize(
    "content",
    ['{"items": {}}', "[]", '{"items": [], "more": 1}', "{not json"],
)
def test_malformed_output_is_rejected_as_a_whole(tmp_path: Path, content: str):
    cfg = project(tmp_path)
    (job,) = make(cfg, "cs", "occupations")
    (job.path / jobs.OUTPUT).write_text(content)
    report = jobs.ingest(cfg, job.path)
    assert report.failure
    assert report.accepted == 0
    assert len(report.missing) == len(job.items)
    assert not translate.curated_path(cfg, "cs").exists()


def test_ingest_is_idempotent_and_merges(tmp_path: Path):
    cfg = project(tmp_path)
    (job,) = make(cfg, "cs", "occupations")
    first, *rest = answers(job)
    write_output(job, [first])
    jobs.ingest(cfg, job.path)
    # Pending jobs are not made again; an ingested one is done with.
    assert make(cfg, "cs", "occupations")[0].items == [
        i for i in job.items if i["id"] != first["id"]
    ]
    write_output(job, [first, *rest])
    jobs.ingest(cfg, job.path)
    path = translate.curated_path(cfg, "cs")
    once = path.read_bytes()
    jobs.ingest(cfg, job.path)
    assert path.read_bytes() == once
    assert translate.load(cfg, "cs").occupations == CS


def test_stale_ui_translation_is_made_again(tmp_path: Path):
    cfg = project(tmp_path)
    (job,) = make(cfg, "cs", "ui")
    assert {i["id"] for i in job.items} == set(translate.ui_source(cfg, "en"))
    write_output(job, [{"id": "card.back", "text": "Zpět"}])
    jobs.ingest(cfg, job.path)
    (rest,) = make(cfg, "cs", "ui")
    assert "card.back" not in {i["id"] for i in rest.items}
    # Once the English text changes, the translation is stale.
    en = translate.ui_source(cfg, "en") | {"card.back": "Go back"}
    (tmp_path / "web/i18n/en.json").write_text(json.dumps(en))
    (again,) = make(cfg, "cs", "ui")
    assert again.items == [translate.ui_item("card.back", "Go back", "Späť")]
    assert "card.back" not in translate.load(cfg, "cs").ui_strings(en)


def test_occupations_are_those_of_every_election(tmp_path: Path):
    cfg = project(tmp_path)
    earlier = dataclasses.replace(cfg.latest, day=dt.date(2022, 10, 29), slug="2022")
    cfg = dataclasses.replace(cfg, elections=(cfg.latest, earlier))
    write_candidates(cfg, earlier, ["vodič", "vodič", "kuchár"])
    (job,) = make(cfg, "cs", "occupations")
    # Counts summed: vodič 3, učiteľka 2, then the rest by name.
    assert [i["source"] for i in job.items] == ["vodič", "učiteľka", "SZČO", "kuchár"]
    (cfg.election_build_dir(earlier) / candidates.OUTPUT_FILE).unlink()
    with pytest.raises(jobs.JobError, match="2022-10-29"):
        make(cfg, "cs", "occupations")


def per_election_kind() -> jobs.Kind:
    def make_one(cfg: config.Config, options: jobs.MakeOptions) -> list[jobs.Batch]:
        batch = jobs.Batch([{"id": "a"}], "prompt", "title")
        return [] if options.pending else [batch]

    return jobs.Kind(
        name="example",
        summary="an example",
        item_schema={
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}},
        },
        default_size=1,
        make=make_one,
        check=lambda cfg, job, item, out: [],
        accept=lambda cfg, job, accepted: [],
        per_election=True,
    )


def test_per_election_jobs_record_their_election(tmp_path: Path):
    cfg = project(tmp_path)
    (job,) = jobs.make(cfg, per_election_kind(), election=cfg.latest)
    day = cfg.latest.day.isoformat()
    assert json.loads((job.path / jobs.INPUT).read_text())[jobs.ELECTION] == day
    assert jobs.election(cfg, jobs.load_job(job.path)) == cfg.latest
    # The pending job leaves its items out of its own election's jobs only.
    assert jobs.make(cfg, per_election_kind(), election=cfg.latest) == []
    earlier = dataclasses.replace(cfg.latest, day=dt.date(2022, 10, 29), slug="2022")
    assert len(jobs.make(cfg, per_election_kind(), election=earlier)) == 1


def test_a_job_without_its_election_must_be_made_again(tmp_path: Path):
    cfg = project(tmp_path)
    job = jobs.Job(tmp_path / "example-001", "example", {}, [{"id": "a"}])
    with pytest.raises(jobs.JobError, match="make it again"):
        jobs.election(cfg, job)


def check(source: str, text: str, lang: str = "cs", **kwargs) -> list[str]:
    script = "Cyrl" if lang in ("uk", "rue") else "Latn"
    return translate.problems(source, text, lang=lang, script=script, **kwargs)


def test_placeholders_must_be_kept():
    assert check("Mayor of {name}", "Starosta obce {name}") == []
    assert check("Mayor of {name}", "Starosta obce {jméno}")
    assert check("{n} seats", "{n} {n} míst")


def test_script_must_be_the_languages():
    assert check("age {n}", "вік {n}", lang="uk") == []
    assert check("age {n}", "age {n}", lang="uk")
    # Names in the source may stay in Latin script.
    assert check("Data: ZBGIS © ÚGKK SR", "Дані: ZBGIS © ÚGKK SR", lang="uk") == []
    assert check("pensioner", "пенсионер, ы", lang="uk")
    assert check("pensioner", "dôchodca", lang="cs")
    # A letter of another script inside a word, either way round.
    assert check("the mayor said", "примátор сказав", lang="uk")
    assert check("Ráž said", "Rážа powiedział", lang="pl")
    # Names declined by the translation keep their script and letters.
    assert check("Maroš Eľko said", "Podle Maroše Eľka", lang="cs") == []
    assert check("OĽaNO's minister", "ministr OĽaNO's", lang="cs") == []
    assert check("Béla Bugár said", "Béla Bugára сказав", lang="uk") == []
    assert check("Býva v Michalovciach.", "Живе в Michalovce.", lang="uk") == []
    # Not a name of the source, nor one in another form.
    assert check("Maroš Eľko said", "Eľko řekl, že veľmi", lang="cs")
    assert check("Maroš Eľko said", "Podle Eľkovského", lang="cs")
    assert check("Béla Bugár said", "Béla Bugárа сказав", lang="uk")


def test_untranslated_copy_needs_the_flag():
    assert check("starosta", "starosta")
    assert check("starosta", "starosta", identical=True) == []
    assert check("Back", "Späť", reference="Späť")
    long = "Slovak media and more words than a name has"
    assert check(long, long, identical=True)
