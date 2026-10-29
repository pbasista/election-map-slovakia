import json
import shutil
from pathlib import Path

import pytest

from election_map_slovakia import cli, config, lock, stamp

REPO = Path(__file__).resolve().parent.parent


def project(root: Path) -> Path:
    """A repository with the real configuration and a little curated data."""
    shutil.copytree(REPO / "config", root / "config")
    shutil.copy(REPO / "uv.lock", root / "uv.lock")
    shutil.copytree(REPO / "web", root / "web")
    for day in ("2026-10-24", "2022-10-29"):
        obvody = root / "data/curated/elections" / day / "obvody"
        obvody.mkdir(parents=True)
        (obvody / "zsk-1.toml").write_text(f"# {day}\n")
    record(root, "a", ["c1"])
    return root


def record(root: Path, person: str, cached: list[str]) -> None:
    path = root / "data/curated/research" / person[:2] / f"{person}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"findings": [{"cache": c} for c in cached]}))


def keys(root: Path) -> lock.Keys:
    return lock.keys(config.load(root / "config"))


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return project(tmp_path)


def test_keys_follow_from_the_repository_alone(root: Path):
    first = keys(root)
    assert first == keys(root)
    assert set(first.maps) == set(first.data) == {"2026", "2022"}
    values = [*first.maps.values(), *first.data.values(), first.sources, first.results]
    assert len(set(values)) == 6
    assert lock.read(root / lock.LOCK_FILE) is None
    (root / lock.LOCK_FILE).write_text(lock.render(first))
    assert lock.read(root / lock.LOCK_FILE) == first


def test_what_only_the_app_reads_changes_no_key(root: Path):
    before = keys(root)
    (root / "web" / "app.css").write_text("body { color: red }\n")
    edit(root / "config/site.toml", "file_budget = 19000", "file_budget = 18000")
    edit(root / "config/elections.toml", "live = false", "live = true")
    edit(
        root / "config/elections.toml", "polls_open = 07:00:00", "polls_open = 06:00:00"
    )
    assert keys(root) == before


def test_a_shared_input_changes_every_key_but_the_sources(root: Path):
    before = keys(root)
    # The ZBGIS boundaries, which both elections are drawn on.
    edit(root / "config/inputs.toml", 'sha256 = "ff8efeb4', 'sha256 = "0f8efeb4')
    after = keys(root)
    for slug in ("2026", "2022"):
        assert after.maps[slug] != before.maps[slug]
        assert after.data[slug] != before.data[slug]
    assert after.results != before.results
    assert after.sources == before.sources


def test_an_elections_base_map_extract_is_its_maps_alone(root: Path):
    before = keys(root)
    edit(root / "config/inputs.toml", 'sha256 = "b868894a', 'sha256 = "0868894a')
    after = keys(root)
    assert after.maps["2022"] != before.maps["2022"]
    assert after.maps["2026"] == before.maps["2026"]
    assert after.data == before.data
    assert after.results == before.results


def test_curated_data_changes_its_map_and_every_data_key(root: Path):
    before = keys(root)
    (root / "data/curated/elections/2022-10-29/obvody/zsk-1.toml").write_text("x\n")
    after = keys(root)
    assert after.maps["2022"] != before.maps["2022"]
    assert after.maps["2026"] == before.maps["2026"]
    # The elections are entwined: an earlier one's obvody reach the later
    # one's results through the comparison of their okrsky (lock.py).
    assert after.data["2026"] != before.data["2026"]
    assert after.data["2022"] != before.data["2022"]
    assert after.results != before.results


def test_research_changes_the_data_keys_and_no_map_key(root: Path):
    before = keys(root)
    record(root, "b", ["c2"])
    after = keys(root)
    assert after.sources != before.sources
    # The research itself is in every data bundle.
    assert after.data["2026"] != before.data["2026"]
    assert after.data["2022"] != before.data["2022"]
    assert after.maps == before.maps


def test_code_reaches_the_keys_of_what_it_makes(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    package = tmp_path / stamp.PACKAGE.name
    shutil.copytree(
        stamp.PACKAGE, package, ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.setattr(stamp, "PACKAGE", package)

    def fresh() -> lock.Keys:
        lock.code_digest.cache_clear()
        return keys(root)

    try:
        before = fresh()
        # The CLI outside the map steps: the data's, not the maps'.
        edit(package / "cli.py", 'help="serve dist/', 'help="Serve dist/')
        after = fresh()
        assert after.maps == before.maps
        assert after.data["2026"] != before.data["2026"]
        # Code that makes the data but not the maps.
        edit(package / "links.py", "\ndef ", "\nUNUSED = 1\n\n\ndef ")
        again = fresh()
        assert again.maps == before.maps
        assert again.data["2026"] != after.data["2026"]
        # The CLI's part of the map steps, even a comment of it.
        text = (package / "cli.py").read_text(encoding="utf-8")
        body = text.index(":\n", text.index("\ndef _geo(")) + 2
        (package / "cli.py").write_text(
            text[:body] + "    # Reworded.\n" + text[body:], encoding="utf-8"
        )
        assert fresh().maps["2026"] != before.maps["2026"]
    finally:
        lock.code_digest.cache_clear()


def test_an_input_not_pinned_has_no_key(root: Path):
    edit(
        root / "config/inputs.toml",
        'sha256 = "9216341d47d6d1e55a7fdad6464f3fce0f8f8a3be29a27bb076726f71e800bed"\n'
        "retrieved = 2026-10-18\n",
        "",
    )
    with pytest.raises(lock.LockError, match="candidates-zsk not pinned"):
        keys(root)


def test_data_lock_check_fails_on_a_stale_lock(
    root: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(root)
    assert cli.main(["data", "lock", "--check"]) == 1
    assert cli.main(["data", "lock"]) == 0
    assert cli.main(["data", "lock", "--check"]) == 0
    record(root, "b", ["c2"])
    assert cli.main(["data", "lock", "--check"]) == 1
