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
    edit(cfg / "parties.toml", 'logo_license = "CC0"\n', "")
    with pytest.raises(config.ConfigError, match=r"logo_license: missing"):
        config.load(cfg)


def test_party_short_form_used_twice(cfg: Path):
    # A shared link's filter names its parties by short form.
    edit(cfg / "parties.toml", 'short = "Alternatíva"', 'short = "Bratia Slovenska"')
    with pytest.raises(config.ConfigError, match=r"short: is also the short form"):
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
    edit(cfg / "site.toml", "election = ", "result_mode = false\nelection = ")
    with pytest.raises(config.ConfigError, match="site.toml: result"):
        config.load(cfg)


def test_live_url_from_environment(cfg: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(config.LIVE_URL_ENV, raising=False)
    assert config.load(cfg).site.live_url == "https://live.volebnamapa.sk"
    monkeypatch.setenv(config.LIVE_URL_ENV, "http://127.0.0.1:8766/")
    assert config.load(cfg).site.live_url == "http://127.0.0.1:8766"
    monkeypatch.setenv(config.LIVE_URL_ENV, "")
    assert config.load(cfg).site.live_url is None
    monkeypatch.setenv(config.LIVE_URL_ENV, "https://live.example.sk/results")
    with pytest.raises(config.ConfigError, match="EMS_LIVE_URL: must be empty"):
        config.load(cfg)


def test_live_window_from_polls_close(cfg: Path, monkeypatch: pytest.MonkeyPatch):
    # The released site polls from the polls' closing for live_days; a test
    # server (EMS_LIVE_URL) at any time.
    monkeypatch.delenv(config.LIVE_URL_ENV, raising=False)
    edit(cfg / "site.toml", "live_days = 7", "live_days = 3")
    site = config.load(cfg).site
    assert site.live_window is not None
    start, end = site.live_window
    assert start == site.polls_close
    assert end.isoformat() == "2026-10-27T20:00:00+01:00"
    monkeypatch.setenv(config.LIVE_URL_ENV, "http://127.0.0.1:8766")
    assert config.load(cfg).site.live_window is None


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
