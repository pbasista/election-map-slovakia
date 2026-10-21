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
