import ast
import json
import shutil
from pathlib import Path

from election_map_slovakia import cli, config, stamp

ROOT = Path(__file__).resolve().parent.parent


def test_step_reruns_when_an_input_changes_or_the_output_is_gone(tmp_path):
    build = tmp_path / "data" / "build"
    out = build / "geo"
    out.mkdir(parents=True)
    (out / "a.json").write_text("{}")
    path = build / "geo.stamp.json"

    def current(pins=None):
        inputs = {"code": "c", "python": "3.15", "pins": pins or {"zbgis": "1"}}
        return stamp.Stamp(path, inputs, build, [out])

    assert current().changes() == ["no record of a successful run"]
    current().record()
    assert current().changes() == []
    assert current({"zbgis": "2"}).changes() == ["input zbgis changed"]
    assert current({"zbgis": "1", "osm": "3"}).changes() == ["input osm changed"]

    (out / "a.json").write_text('{"changed": 1}')
    assert current().changes() == ["its output changed since it was written"]
    current().record()
    assert current().changes() == []
    shutil.rmtree(out)
    assert current().changes() == ["geo missing"]


def test_the_output_is_read_again_only_where_its_files_changed(tmp_path, monkeypatch):
    """Its digest stands while the names, sizes and times of its files are
    those its stamp has, as git's index tells a file unchanged; not while
    a file is too new for its time to tell a change."""
    out = tmp_path / "geo"
    (out / "okres").mkdir(parents=True)
    (out / "okres" / "a.json").write_text("{}")
    (out / "b.json").write_text("[]")
    path = tmp_path / "geo.stamp.json"
    digest = stamp.Stamp(path, {}, tmp_path, [out]).record()
    assert digest == stamp.outputs_digest(tmp_path, [out])
    # Just written: its times tell nothing yet.
    assert stamp.recorded_outputs(path)["files"] is None
    monkeypatch.setattr(stamp, "_SETTLED", -1)
    read: list[Path] = []
    file_digest = stamp.file_digest

    def counted(p: Path) -> str:
        read.append(p)
        return file_digest(p)

    monkeypatch.setattr(stamp, "file_digest", counted)
    assert stamp.Stamp(path, {}, tmp_path, [out]).changes() == []
    assert len(read) == 2  # read once more, and its times kept
    read.clear()
    assert stamp.Stamp(path, {}, tmp_path, [out]).changes() == []
    assert read == []
    (out / "b.json").write_text("[1]")
    assert stamp.Stamp(path, {}, tmp_path, [out]).changes() == [
        "its output changed since it was written"
    ]


def test_the_output_digest_is_of_names_and_contents_alone(tmp_path):
    """The same on another machine, wherever the build directory is; an
    empty directory is not a missing one."""
    for root in (tmp_path / "a", tmp_path / "b"):
        (root / "links").mkdir(parents=True)
        (root / "candidates.json").write_text("{}")
    a, b = tmp_path / "a", tmp_path / "b"

    def digest(root: Path) -> str:
        return stamp.outputs_digest(root, [root / "candidates.json", root / "links"])

    assert digest(a) == digest(b)
    (b / "links").rmdir()
    assert digest(a) != digest(b)
    (b / "links").mkdir()
    (b / "links" / "2022.json").write_text("{}")
    assert digest(a) != digest(b)


def test_the_base_map_is_made_once_per_extract(tmp_path, monkeypatch):
    """Every election on an extract shares its base map, made once, in
    data/build/base/<extract>/ rather than in an election's directory."""
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(ROOT / config.PARTY_LOGO_DIR, tmp_path / config.PARTY_LOGO_DIR)
    monkeypatch.chdir(tmp_path)
    cfg = config.load(tmp_path / "config")
    made: list[str] = []

    def basemap(cfg, base, args):
        made.append(base.osm)
        return 0

    monkeypatch.setattr(cli, "_basemap", basemap)
    assert cli.main(["basemap", "--election", "2026-referendum"]) == 0
    assert made == ["osm-slovakia-2026"]
    made.clear()
    assert cli.main(["basemap"]) == 0
    assert made == list(cfg.bases)
    assert len(made) == len(set(made)) < len(cfg.elections)
    base = cfg.bases["osm-slovakia-2026"]
    assert (base.okresy, base.obce) == ("zbgis-1-2026", "zbgis-0-2026")
    assert (
        cfg.base_build_dir(base.osm) == tmp_path / "data/build/base/osm-slovakia-2026"
    )


def test_a_step_reruns_for_its_own_glue_only(tmp_path, monkeypatch):
    """A release (the package version) reruns no step; a change to the CLI
    reruns the steps whose glue it is in: the step's own functions and what
    they call (`_stamp`, shared by all), not another step's wiring."""
    package = tmp_path / stamp.PACKAGE.name
    shutil.copytree(
        stamp.PACKAGE, package, ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.setattr(stamp, "PACKAGE", package)
    before = {s: stamp.code_digest(s) for s in ("basemap", "geo")}
    init = package / "__init__.py"
    init.write_text(init.read_text() + '\n__version__ = "99.0.0"\n')
    assert {s: stamp.code_digest(s) for s in before} == before
    cli_py = package / "cli.py"

    def edit(function: str) -> None:
        text = cli_py.read_text()
        head = f"def {function}("
        assert head in text
        cli_py.write_text(text.replace(head, f"def {function}(  # reworded\n", 1))

    edit("_run_check")
    assert {s: stamp.code_digest(s) for s in before} == before
    edit("_basemap")
    assert stamp.code_digest("basemap") != before["basemap"]
    assert stamp.code_digest("geo") == before["geo"]
    edit("_stamp")
    assert stamp.code_digest("geo") != before["geo"]


def test_imports_are_parsed_once_per_content_of_a_module(tmp_path, monkeypatch):
    """Kept across runs by each module's source, the imports give the same
    digest without parsing; a module changed since is parsed again, and the
    kept file holds the modules as they are."""
    package = tmp_path / stamp.PACKAGE.name
    shutil.copytree(
        stamp.PACKAGE, package, ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.setattr(stamp, "PACKAGE", package)
    kept = tmp_path / "shared" / "stamp"
    parsed: list[bytes] = []
    imports = stamp._imports

    def parse(source: bytes, package: str) -> tuple[str, ...]:
        parsed.append(source)
        return imports(source, package)

    monkeypatch.setattr(stamp, "_imports", parse)

    def run() -> str:
        """Return the code digest of `geo` as a new process makes it."""
        monkeypatch.setattr(stamp, "_SCANS", {})
        stamp._code_digest.cache_clear()
        with stamp.scans_kept(kept):
            return stamp.code_digest("geo")

    before = run()
    assert len(parsed) == len(set(parsed)) > 1
    parsed.clear()
    assert run() == before
    assert parsed == []

    old = stamp.modules("geo")
    geo_py = package / "geo.py"
    geo_py.write_text(
        geo_py.read_text() + "\nfrom election_map_slovakia import jobs  # noqa\n"
    )
    after = run()
    assert after != before
    assert "jobs" in stamp.modules("geo")
    # The changed module is parsed, and those it imports first now; no other.
    assert parsed[0] == geo_py.read_bytes()
    unchanged = {(package / f"{m}.py").read_bytes() for m in old - {"geo"}}
    assert not set(parsed[1:]) & unchanged
    sources = {stamp._scan_key(p.read_bytes()) for p in package.glob("*.py")}
    assert json.loads((kept / stamp.SCANS_FILE).read_bytes()).keys() <= sources

    (kept / stamp.SCANS_FILE).write_text("{broken")
    parsed.clear()
    assert run() == after
    assert len(parsed) > 1


def test_code_of_a_step_includes_every_package_module_it_uses():
    assert stamp.modules("addresses") >= {
        "addresses",
        "geo",
        "candidates",
        "obvody",
        "gpkg",
        "xlsx",
        "config",
    }


def test_each_step_stamps_the_code_its_cli_function_calls():
    """A package module a step's function in the CLI uses is in the step's
    code (its module's imports, or the modules its CLI functions name,
    `stamp.glue`): else a fix to it would leave the step skipped. Its
    constants (paths, names) are not code that computes."""
    package = {p.stem for p in stamp.PACKAGE.glob("*.py")}
    tree = ast.parse((stamp.PACKAGE / "cli.py").read_bytes())
    functions = {f.name: f for f in tree.body if isinstance(f, ast.FunctionDef)}
    # The run's glue and the errors it catches compute no output.
    glue = {"config", "jobs", "output", "progress", "stamp"}
    for step in ("candidates", "links", "geo", "basemap", "addresses", "results"):
        nodes = list(ast.walk(functions[f"_{step}"]))
        used = {
            n.value.id
            for n in nodes
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id in package
            and not n.attr.isupper()
        }
        # The modules the step's CLI functions name are in its code too.
        named = set().union(
            *(stamp.modules(m) for m in stamp.glue((f"_{step}", f"_run_{step}"))[1])
        )
        assert used - glue - stamp.modules(step) - named == set(), step


def test_every_upstream_output_a_step_reads_is_declared():
    """The candidates of `links`, `addresses`, `geo` and `results`, the
    addresses of `geo`, and what `results` compares with: the links of its
    election, the addresses of both and the results of the one before."""
    cfg = config.load(ROOT / "config")
    declared = {(s, k): d for s, k, d in cli._declarations(cfg)}
    assert set(declared) == cli._record_keys(cfg)
    assert declared["geo", "2026-10-24"].upstream == (
        ("candidates", "2026-10-24"),
        ("addresses", "2026-10-24"),
    )
    day = cfg.election("2022").day
    assert set(declared["links", "2022-10-29"].upstream) == {
        ("candidates", e.day.isoformat()) for e in cfg.elections if e.day <= day
    }
    assert set(declared["results", "2026-10-24"].upstream) == {
        ("candidates", "2026-10-24"),
        ("geo", "2026-10-24"),
        ("links", "2026-10-24"),
        ("addresses", "2026-10-24"),
        ("addresses", "2022-10-29"),
        ("results", "2022-10-29"),
    }
    # A by-election's council obvody are its term's (addresses.council_parts).
    assert declared["results", "2026-03-21"].upstream == (
        ("candidates", "2026-03-21"),
        ("geo", "2026-03-21"),
        ("candidates", "2022-10-29"),
    )
    assert declared["addresses", "2026-03-21"].upstream == (
        ("candidates", "2026-03-21"),
        ("candidates", "2022-10-29"),
    )
    for (step, key), d in declared.items():
        for upstream in d.upstream:
            assert upstream in declared, (step, key, upstream)
    # Its outputs are the crosswalk beside its results.
    assert declared["results", "2026-10-24"].outputs[1].parent.name == "crosswalk"
