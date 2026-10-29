import ast

from election_map_slovakia import stamp


def test_step_reruns_when_an_input_changes_or_the_output_is_gone(tmp_path):
    raw = tmp_path / "data" / "raw" / "list.xlsx"
    curated = tmp_path / "data" / "curated" / "obvody"
    curated.mkdir(parents=True)
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"rows")
    (curated / "BA.toml").write_text("[obvod.1]\n")
    out = tmp_path / "data" / "build" / "geo"
    out.mkdir(parents=True)
    path = tmp_path / "data" / "build" / "geo.stamp.json"

    def current(values=None):
        digests = stamp.inputs(tmp_path, "geo", [raw], [curated], values)
        return stamp.Stamp(path, digests, [out])

    assert current().changes() == ["no record of a successful run"]
    current().record()
    assert current().changes() == []

    (curated / "BA.toml").write_text("[obvod.1]\nseats = 3\n")
    assert current().changes() == ["data/curated/obvody/ changed"]
    current().record()
    raw.write_bytes(b"other rows")
    assert current().changes() == ["data/raw/list.xlsx changed"]
    current().record()
    assert current({"overrides": {"a": "1"}}).changes() == ["overrides changed"]

    current().record()
    out.rmdir()
    assert current().changes() == ["geo missing"]


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
    code (its module's imports) or digested into its stamp's values
    (`stamp.code_digest`): else a fix to it would leave the step skipped.
    Its constants (paths, names) are not code that computes."""
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
        digested = set().union(
            *(
                stamp.modules(n.args[0].value)
                for n in nodes
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "code_digest"
                and isinstance(n.args[0], ast.Constant)
            )
        )
        assert used - glue - stamp.modules(step) - digested == set(), step
