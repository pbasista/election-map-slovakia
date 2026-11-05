import hashlib
import json
import shutil
from pathlib import Path

import pytest

from election_map_slovakia import cli, config, fetch, output, record, stamp

ROOT = Path(__file__).resolve().parent.parent
EXTRACT = "osm-slovakia-2026"
KEY = ("basemap", EXTRACT)


def project(root: Path) -> Path:
    """A repository with the real configuration, uv.lock and Python pin."""
    shutil.copytree(ROOT / "config", root / "config")
    shutil.copytree(ROOT / config.PARTY_LOGO_DIR, root / config.PARTY_LOGO_DIR)
    shutil.copy(ROOT / "uv.lock", root / "uv.lock")
    # The Python running the tests: what a local run names its inputs by.
    (root / ".python-version").write_text(f"{stamp.PYTHON}\n")
    return root


class Basemap:
    """`ems basemap` of one extract with the step's own work replaced.

    The CLI decides, stamps and records as for real; what the step makes
    of its inputs is *made*, which a test changes to see the step make
    something else of the same inputs.
    """

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.made = b"roads"
        self.runs = 0
        cfg = config.load(root / "config")
        base = cfg.bases[EXTRACT]
        for name in (base.osm, base.okresy, base.obce):
            inp = next(i for i in cfg.inputs.inputs if i.name == name)
            path = fetch.member_path(cfg.raw_dir, inp)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"downloaded")
        monkeypatch.chdir(root)
        monkeypatch.setattr(cli, "_extract_gpkg", lambda cfg, raw: raw.path)
        monkeypatch.setattr(cli.basemap, "build", lambda *args: {})
        monkeypatch.setattr(cli.basemap, "write", self.write)
        monkeypatch.setattr(cli.basemap, "report", lambda files, sizes: [])

    def write(self, data: dict, out: Path, memo: Path) -> dict:
        self.runs += 1
        with output.replacing(out) as tmp:
            (tmp / "roads.json").write_bytes(self.made)
        return {}

    def run(self, *flags: str) -> int:
        """Return how many times the step ran its work."""
        before = self.runs
        assert cli.main(["basemap", "--election", "2026", *flags]) == 0
        return self.runs - before

    @property
    def record_text(self) -> str:
        return (self.root / record.RECORD_FILE).read_text()

    @property
    def entry(self) -> record.Entry:
        return record.read(self.root / record.RECORD_FILE)[KEY]

    @property
    def stamp_path(self) -> Path:
        return self.root / "data/build/base" / EXTRACT / "basemap.stamp.json"


@pytest.fixture
def step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Basemap:
    return Basemap(project(tmp_path), monkeypatch)


def pin(root: Path, name: str, sha256: str) -> None:
    """Pin input *name* of config/inputs.toml to *sha256*."""
    path = root / "config" / config.INPUTS_FILE
    text = path.read_text(encoding="utf-8")
    head = f"[input.{name}]"
    start = text.index(head)
    old = text.index('sha256 = "', start)
    end = text.index('"', old + len('sha256 = "'))
    path.write_text(text[:old] + f'sha256 = "{sha256}' + text[end:], encoding="utf-8")


def test_a_step_records_its_inputs_and_output(step: Basemap):
    assert step.run() == 1
    entry = step.entry
    out = step.root / "data/build/base" / EXTRACT
    assert entry.outputs == stamp.outputs_digest(out, [out / "base"])
    assert entry.parts["python"] == stamp.PYTHON
    assert set(entry.parts) == {"code", "python", "libraries", "pins"}
    assert step.record_text.startswith("# What each step")
    assert f'[basemap."{EXTRACT}"]' in step.record_text
    # From the commit alone, the inputs are those the run recorded.
    cfg = config.load(step.root / "config")
    declared = cli._basemap_declared(cfg, cfg.bases[EXTRACT])
    recorded = record.entry(cli._inputs_of(cfg, "basemap", declared, {}), "")
    assert recorded.inputs == entry.inputs
    # Up to date by its stamp, and the record stays as it is.
    text = step.record_text
    assert step.run() == 0
    assert step.record_text == text


def test_a_step_up_to_date_per_the_record_is_skipped(
    step: Basemap, capsys: pytest.CaptureFixture[str]
):
    """A collaborator's stamp has the inputs of before a change that left
    the output as it was: the record has the inputs of after, with that
    output, so the step is skipped and its stamp takes the new inputs."""
    assert step.run() == 1
    text = step.record_text
    before = step.stamp_path.read_text()
    content = stamp._load(step.stamp_path)
    assert content is not None
    content["inputs"]["code"] = "of the commit before"
    step.stamp_path.write_text(json.dumps(content))
    capsys.readouterr()
    assert step.run() == 0
    assert f"up to date per {record.RECORD_FILE}" in capsys.readouterr().err
    assert step.record_text == text
    assert stamp._load(step.stamp_path)["inputs"] == json.loads(before)["inputs"]


def test_a_step_runs_where_its_inputs_are_not_those_recorded(step: Basemap):
    """Downloads count by their pin: their file is not read again, and a
    new pin runs the step and records it."""
    assert step.run() == 1
    old = step.entry
    raw = next((step.root / "data/raw" / EXTRACT).iterdir())
    raw.write_bytes(b"downloaded again, as fetch checks it against the pin")
    assert step.run() == 0
    pin(step.root, EXTRACT, "0" * 64)
    assert step.run() == 1
    new = step.entry
    assert new.inputs != old.inputs
    assert record.differing(old, new) == ["pins"]
    assert new.outputs == old.outputs


def test_output_unlike_the_record_for_the_same_inputs_is_a_warning(
    step: Basemap, capsys: pytest.CaptureFixture[str]
):
    """The record keeps its entry, and says why it may be wrong."""
    assert step.run() == 1
    text = step.record_text
    step.made = b"other roads"
    shutil.rmtree(step.root / "data/build/base" / EXTRACT / "base")
    capsys.readouterr()
    assert step.run() == 1
    err = capsys.readouterr().err
    assert "warning: ems basemap osm-slovakia-2026: the output is not the one" in err
    assert step.record_text == text
    # --force runs it; the same inputs and output change nothing.
    assert step.run("--force") == 1
    assert step.record_text == text


def test_compare_warns_where_an_output_is_not_the_one_recorded(
    step: Basemap,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """As a release runs it: a warning annotation and a job summary, and
    success all the same."""
    assert step.run() == 1
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    capsys.readouterr()
    assert cli.main(["record", "compare", "--github"]) == 0
    out = capsys.readouterr().out
    assert f"basemap {EXTRACT}" not in out
    assert "geo 2026-10-24: no entry" in out

    path = step.root / record.RECORD_FILE
    entries = record.read(path)
    entries[KEY] = record.Entry(step.entry.inputs, "0" * 64, step.entry.parts)
    path.write_text(record.render(entries))
    assert cli.main(["record", "compare", "--github"]) == 0
    out = capsys.readouterr().out
    assert f"basemap {EXTRACT}: the output differs, not its inputs" in out
    assert f"::warning title={record.RECORD_FILE}::" in out
    text = summary.read_text()
    assert f"| basemap | {EXTRACT} | the output differs, not its inputs |" in text


def test_the_record_is_written_sorted_and_read_back(tmp_path: Path):
    path = tmp_path / "outputs.toml"
    a = record.Entry("1" * 64, "2" * 64, {"code": "abc", "python": "3.15"})
    b = record.Entry("3" * 64, "4" * 64, {"code": "def", "python": "3.15"})
    keep = {("geo", "2026-10-24"), ("candidates", "2026-10-24")}
    record.update(path, ("geo", "2026-10-24"), a, keep)
    record.update(path, ("candidates", "2026-10-24"), b, keep)
    record.update(path, ("candidates", "1999-01-01"), b, keep | {("x", "y")})
    text = path.read_text()
    assert text.index("[candidates.") < text.index("[geo.")
    assert record.read(path) == {
        ("geo", "2026-10-24"): a,
        ("candidates", "2026-10-24"): b,
        ("candidates", "1999-01-01"): b,
    }
    # An election no longer configured goes when the record is written.
    record.update(path, ("geo", "2026-10-24"), a, keep)
    assert set(record.read(path)) == keep


def consistent(root: Path) -> None:
    """Write a record with the inputs of every step at the commit in *root*."""
    cfg = config.load(root / "config")
    entries: dict[record.Key, record.Entry] = {}
    for step, key, declared in cli._declarations(cfg):
        outputs = hashlib.sha256(f"{step} {key}".encode()).hexdigest()
        inputs = cli._inputs_of(cfg, step, declared, entries)
        entries[step, key] = record.entry(inputs, outputs)
    (root / record.RECORD_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / record.RECORD_FILE).write_text(record.render(entries))


def test_the_check_names_the_steps_a_change_of_code_makes_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """From the repository alone: no data/raw/ nor data/build/."""
    root = project(tmp_path / "repo")
    package = tmp_path / stamp.PACKAGE.name
    shutil.copytree(
        stamp.PACKAGE, package, ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.setattr(stamp, "PACKAGE", package)
    monkeypatch.chdir(root)
    consistent(root)
    assert not (root / "data/raw").exists()
    assert not (root / "data/build").exists()
    assert cli.main(["record", "check"]) == 0
    assert "has the inputs of all" in capsys.readouterr().out

    links_py = package / "links.py"
    source = links_py.read_text()
    links_py.write_text(source + "\n# A comment is code too.\n")
    assert cli.main(["record", "check"]) == 1
    err = capsys.readouterr().err
    assert "links 2026-10-24: not as recorded: code" in err
    assert "geo 2026-10-24" not in err
    links_py.write_text(source)
    assert cli.main(["record", "check"]) == 0

    pin(root, EXTRACT, "0" * 64)
    assert cli.main(["record", "check"]) == 1
    err = capsys.readouterr().err
    assert f"basemap {EXTRACT}: not as recorded: pins" in err
    assert "geo 2026-10-24: not as recorded: pins" in err
    assert "candidates 2026-10-24" not in err


def test_the_check_takes_the_python_of_the_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Whatever Python runs it: CI runs it under several."""
    root = project(tmp_path)
    monkeypatch.chdir(root)
    consistent(root)
    monkeypatch.setattr(stamp, "PYTHON", "3.0")
    assert cli.main(["record", "check"]) == 0
    (root / ".python-version").write_text("3.99.1\n")
    assert cli.main(["record", "check"]) == 1
    assert "not as recorded: python" in capsys.readouterr().err


def test_an_empty_curated_directory_counts_as_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Git keeps no empty directory: one left in a working tree is not part
    of the commit, which a fresh checkout (CI) has without it; a file in it
    is."""
    root = project(tmp_path)
    monkeypatch.chdir(root)
    consistent(root)
    cfg = config.load(root / "config")
    rules = cfg.election_dir(cfg.latest) / "obvody"
    (rules / "oz").mkdir(parents=True)
    assert cli.main(["record", "check"]) == 0
    (rules / "oz" / "500011.json").write_text("{}")
    assert cli.main(["record", "check"]) == 1
    assert "geo 2026-10-24: not as recorded: curated" in capsys.readouterr().err
