import shutil
from pathlib import Path

import pytest

from election_map_slovakia import config

REPO = Path(__file__).resolve().parent.parent
REPO_CONFIG = REPO / "config"


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    directory = tmp_path / "config"
    shutil.copytree(REPO_CONFIG, directory)
    shutil.copytree(REPO / config.PARTY_LOGO_DIR, tmp_path / config.PARTY_LOGO_DIR)
    return directory


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_repository_config_loads():
    loaded = config.load(REPO_CONFIG)
    assert loaded.languages.codes[:2] == ("sk", "en")
    assert len(loaded.languages.codes) == 9
    assert loaded.languages.aliases == {"rom": "rmc"}
    assert "hlavnespravy.sk" in loaded.sources.blocklist


def test_found_from_subdirectory(cfg: Path):
    sub = cfg.parent / "a" / "b"
    sub.mkdir(parents=True)
    assert config.find_config_dir(sub) == cfg.resolve()


def test_missing_party_logo_file(cfg: Path):
    (cfg.parent / config.PARTY_LOGO_DIR / "kdh.svg").unlink()
    with pytest.raises(config.ConfigError, match=r"parties\.toml: party\..*\.logo"):
        config.load(cfg)


def test_party_logo_needs_license(cfg: Path):
    edit(cfg / "parties.toml", 'license = "CC0"\n', "")
    with pytest.raises(config.ConfigError, match=r"logo\.2026\.license: missing"):
        config.load(cfg)


def test_party_logo_is_of_an_election(cfg: Path):
    edit(
        cfg / "parties.toml",
        '[party."Bratia Slovenska".logo.2026]',
        '[party."Bratia Slovenska".logo.2018]',
    )
    with pytest.raises(config.ConfigError, match=r"logo\.2018: not an election"):
        config.load(cfg)


def test_unknown_fallback_language(cfg: Path):
    edit(cfg / "languages.toml", 'fallback = ["en", "sk"]', 'fallback = ["en", "ru"]')
    with pytest.raises(config.ConfigError, match=r"languages\.toml: fallback: 'ru'"):
        config.load(cfg)


def test_alias_to_unknown_language(cfg: Path):
    edit(cfg / "languages.toml", 'rom = "rmc"', 'rom = "rom"')
    with pytest.raises(config.ConfigError, match=r"aliases\.rom"):
        config.load(cfg)


def test_duplicate_host_across_categories(cfg: Path):
    edit(cfg / "sources.toml", '"korkep.sk",', '"korkep.sk",\n    "sme.sk",')
    with pytest.raises(config.ConfigError, match=r"'sme\.sk' is already listed"):
        config.load(cfg)


def test_uppercase_host_rejected(cfg: Path):
    edit(cfg / "sources.toml", '"sme.sk"', '"SME.sk"')
    with pytest.raises(config.ConfigError, match="categories.media-sk"):
        config.load(cfg)


def test_malformed_blocklist_line_reports_line_number(cfg: Path):
    path = cfg / "blocklist-konspiratori.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.append("example.com/cs/")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(config.ConfigError, match=rf":{len(lines)}: 'example\.com/cs/'"):
        config.load(cfg)


def test_allowlisted_host_under_blocked_domain(cfg: Path):
    edit(cfg / "sources.toml", '"nrsr.sk",', '"nrsr.sk",\n    "x.hlavnespravy.sk",')
    with pytest.raises(config.ConfigError, match="blocked by"):
        config.load(cfg)


def test_boolean_is_not_a_number(cfg: Path):
    edit(cfg / "site.toml", "file_budget = 19000", "file_budget = true")
    with pytest.raises(config.ConfigError, match="file_budget: expected int"):
        config.load(cfg)


def test_unknown_key_rejected(cfg: Path):
    edit(cfg / "site.toml", "file_budget = ", "result_mode = false\nfile_budget = ")
    with pytest.raises(config.ConfigError, match="site.toml: result"):
        config.load(cfg)


def test_paths_per_election(cfg: Path):
    loaded = config.load(cfg)
    election = loaded.election("2026-10-24")
    assert loaded.election("2026") == election == loaded.latest
    assert loaded.election(None) == election
    assert loaded.election_dir(election) == (
        loaded.root / "data/curated/elections/2026-10-24"
    )
    assert loaded.election_build_dir(election) == loaded.root / "data/build/2026-10-24"
    assert loaded.results_dir(election) == (
        loaded.root / "data/build/2026-10-24/results"
    )
    with pytest.raises(config.ConfigError, match="no election '2018'"):
        loaded.election("2018")


def test_elections_newest_first(cfg: Path):
    # A second election, older: listed after the latest, whatever the order
    # in the file.
    text = (cfg / "elections.toml").read_text(encoding="utf-8")
    block = text[text.index("[election.2026]") :]
    older = block.replace("election.2026", "election.2025").replace(
        "day = 2026-10-24", "day = 2025-10-24"
    )
    older = older.replace("day = 2022-10-29", "day = 2021-10-29", 1)
    older = older[: older.index("by_elections")] + "by_elections = []\n"
    (cfg / "elections.toml").write_text(older + "\n" + block, encoding="utf-8")
    loaded = config.load(cfg)
    assert [e.slug for e in loaded.elections] == ["2026", "2025", "2022"]
    assert loaded.latest.slug == "2026"


def test_election_input_must_exist(cfg: Path):
    edit(cfg / "elections.toml", 'input = "units-oso2026"', 'input = "units-oso2030"')
    with pytest.raises(config.ConfigError, match=r"election\.2026\.units\.input: no"):
        config.load(cfg)


def test_election_input_must_not_be_optional(cfg: Path):
    edit(cfg / "elections.toml", 'input = "units-oso2026"', 'input = "zsk-obvody-ba"')
    with pytest.raises(config.ConfigError, match="is optional, so no step may read"):
        config.load(cfg)


def test_election_slug_starts_with_a_digit(cfg: Path):
    edit(cfg / "elections.toml", "[election.2026]", "[election.sk]")
    edit(cfg / "elections.toml", "[election.2026.", "[election.sk.")
    edit(cfg / "elections.toml", "[election.2026.", "[election.sk.")
    with pytest.raises(config.ConfigError, match="slug must be a digit"):
        config.load(cfg)


def test_live_window_from_polls_close(cfg: Path, monkeypatch: pytest.MonkeyPatch):
    # The released site polls from the polls' closing for live_days; a build
    # for testing (EMS_RESULTS_ANYTIME=1) at any time.
    monkeypatch.delenv(config.RESULTS_ANYTIME_ENV, raising=False)
    edit(cfg / "elections.toml", "live_days = 7", "live_days = 3")
    election = config.load(cfg).latest
    assert election.live_window is not None
    start, end = election.live_window
    assert start == election.polls_close
    assert end.isoformat() == "2026-10-27T20:00:00+01:00"
    monkeypatch.setenv(config.RESULTS_ANYTIME_ENV, "0")
    assert config.load(cfg).latest.live_window == election.live_window
    monkeypatch.setenv(config.RESULTS_ANYTIME_ENV, "1")
    assert config.load(cfg).latest.live_window is None
    monkeypatch.setenv(config.RESULTS_ANYTIME_ENV, "yes")
    with pytest.raises(config.ConfigError, match="EMS_RESULTS_ANYTIME: must be"):
        config.load(cfg)


def test_live_toggle(cfg: Path, monkeypatch: pytest.MonkeyPatch):
    # elections.toml `live` turns polling on or off; a build for testing
    # (EMS_RESULTS_ANYTIME=1) polls even with it off.
    monkeypatch.delenv(config.RESULTS_ANYTIME_ENV, raising=False)
    edit(cfg / "elections.toml", "live = false", "live = true")
    assert config.load(cfg).latest.live
    edit(cfg / "elections.toml", "live = true", "live = false")
    assert not config.load(cfg).latest.live
    monkeypatch.setenv(config.RESULTS_ANYTIME_ENV, "1")
    assert config.load(cfg).latest.live
    edit(cfg / "elections.toml", "live = false", 'live = "no"')
    with pytest.raises(config.ConfigError, match="live: expected bool"):
        config.load(cfg)


def test_key_of_another_input_kind_rejected(cfg: Path):
    edit(
        cfg / "inputs.toml",
        'file = "Uznesenie_567_2026.pdf"',
        'file = "Uznesenie_567_2026.pdf"\nmembers = ["a.gpkg"]',
    )
    with pytest.raises(config.ConfigError, match=r"zsk-obvody-ke\.members: unknown"):
        config.load(cfg)


def test_override_with_bad_obec_code(cfg: Path):
    edit(cfg / "overrides.toml", '= "520349"', '= "52034"')
    with pytest.raises(config.ConfigError, match=r"residence\.zsk:7/2#9: '52034'"):
        config.load(cfg)


def test_override_with_bad_candidacy_id(cfg: Path):
    edit(cfg / "overrides.toml", '"oz:523909/1#38"', '"oz:523909#x"')
    with pytest.raises(config.ConfigError, match=r"person\.merge\[1\]\.candidacies"):
        config.load(cfg)
