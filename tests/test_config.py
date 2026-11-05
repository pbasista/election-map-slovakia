import datetime as dt
import re
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
        '[party."Bratia Slovenska".logo.2015]',
    )
    with pytest.raises(config.ConfigError, match=r"logo\.2015: not an election"):
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
    # The live results of its night, apart from the final ones.
    assert loaded.live_dir(election) == loaded.root / "data/build/2026-10-24/live"
    assert loaded.site.live_project == "ems-live"
    assert loaded.site.live_url == "https://live.volebnamapa.sk"
    with pytest.raises(config.ConfigError, match="no election '2015'"):
        loaded.election("2015")


def test_elections_newest_first(cfg: Path):
    # A second election, older: listed after the latest, whatever the order
    # in the file.
    text = (cfg / "elections.toml").read_text(encoding="utf-8")
    start = text.index("[election.2026]")
    end = re.compile(r"^\[election\.(?!2026[.\]])", re.M).search(text, start)
    assert end is not None
    block = text[start : end.start()]
    older = block.replace("[election.2026", "[election.2015").replace(
        "day = 2026-10-24", "day = 2015-10-24"
    )
    older = older.replace("day = 2022-10-29", "day = 2011-10-29", 1)
    older = older[: older.index("by_elections")] + "by_elections = []\n"
    (cfg / "elections.toml").write_text(older + "\n" + text, encoding="utf-8")
    loaded = config.load(cfg)
    days = [e.day for e in loaded.elections]
    assert days == sorted(days, reverse=True)
    slugs = [e.slug for e in loaded.elections]
    assert slugs[0] == "2026"
    assert slugs.index("2015") == sum(e.day.year > 2015 for e in loaded.elections)
    assert loaded.latest.slug == "2026"


def test_election_input_must_exist(cfg: Path):
    edit(cfg / "elections.toml", 'input = "units-oso2026"', 'input = "units-oso2030"')
    with pytest.raises(config.ConfigError, match=r"election\.2026\.units\.input: no"):
        config.load(cfg)


def test_election_input_must_not_be_optional(cfg: Path):
    edit(
        cfg / "elections.toml",
        'input = "units-oso2026"',
        'input = "zsk-obvody-ba-2026"',
    )
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
    with pytest.raises(
        config.ConfigError, match=r"zsk-obvody-ke-2026\.members: unknown"
    ):
        config.load(cfg)


def test_override_with_bad_obec_code(cfg: Path):
    edit(cfg / "overrides.toml", '= "520349"', '= "52034"')
    with pytest.raises(config.ConfigError, match=r"residence\.zsk:7/2#9: '52034'"):
        config.load(cfg)


def test_override_with_bad_candidacy_id(cfg: Path):
    edit(cfg / "overrides.toml", '"oz:523909/1#38"', '"oz:523909#x"')
    with pytest.raises(config.ConfigError, match=r"person\.merge\[1\]\.candidacies"):
        config.load(cfg)


# Inputs of the repository's inputs.toml that elections of other kinds name
# here only to have something to name.
OTHER = """
polls_open = 07:00:00
polls_close = 22:00:00
live = false
live_days = 7
addresses = "addresses-2026"
zbgis = ["zbgis-0-2026", "zbgis-1-2026", "zbgis-2-2026"]
osm = "osm-slovakia-2026"
records = []
"""
KINDS = {
    "2014-prezident": """
kind = "presidential"
day = 2014-03-15
second_round = 2014-04-05
candidates = { format = "volbysr", round1 = "results-oso2026", round2 = "results-osk2026" }
results = { format = "volbysr", inputs = ["results-oso2026"] }
""",
    "2009-referendum": """
kind = "referendum"
day = 2009-01-24
questions = ["Súhlasíte …?"]
""",
    "2010-nrsr": """
kind = "parliament"
day = 2010-06-12
seats = 150
threshold = 5
coalition_thresholds = [[2, 7.0], [4, 10.0]]
preferences = 4
preference_quota = 3.0
candidates = { format = "volbysr", subjects = "results-oso2026", candidates = "results-osk2026" }
units = { format = "xlsx", input = "units-oso2026" }
""",
    "2009-ep": """
kind = "european"
day = 2009-06-06
seats = 15
threshold = 5.0
preferences = 2
preference_quota = 10.0
candidates = { format = "curated" }
""",
    "2012-03": """
kind = "by-election"
day = 2012-03-17
candidates = { format = "susr-by", package = "results-oso202603" }
results = { format = "susr-by", inputs = ["results-oso202603"] }
""",
    # Not a real configuration: of the inputs, any to name.
    "2013": """
kind = "municipal-regional"
day = 2013-11-09
units = { format = "volbysr", input = "results-osk2022", table = "tab0dc" }
candidates = { format = "susr", osk = "results-osk2022" }
results = { format = "susr", inputs = ["results-osk2022"] }
""",
}


def add_election(cfg: Path, slug: str, body: str) -> None:
    path = cfg / "elections.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(f"{text}\n[election.{slug}]{body}{OTHER}", encoding="utf-8")


def test_elections_on_one_extract_share_its_base_map(cfg: Path):
    loaded = config.load(cfg)
    on = [e.slug for e in loaded.elections if e.osm == "osm-slovakia-2026"]
    assert len(on) > 1
    assert list(loaded.bases) == list(dict.fromkeys(e.osm for e in loaded.elections))
    assert loaded.bases["osm-slovakia-2026"] == config.Base(
        "osm-slovakia-2026", "zbgis-1-2026", "zbgis-0-2026"
    )
    # Its base map is cut by the okresy and holds the buildings of the obce
    # of ZBGIS levels 1 and 0: those of every election on it.
    swapped = '"zbgis-1-2026", "zbgis-0-2026"'
    path = cfg / "elections.toml"
    path.write_text(
        f"{path.read_text(encoding='utf-8')}\n[election.2009-ep]{KINDS['2009-ep']}"
        + OTHER.replace('"zbgis-0-2026", "zbgis-1-2026"', swapped),
        encoding="utf-8",
    )
    with pytest.raises(
        config.ConfigError,
        match=r"election\.2009-ep\.zbgis: levels 0 and 1 must be those of election"
        r" \S+, which shares the base map of osm-slovakia-2026",
    ):
        config.load(cfg)


def test_elections_of_every_kind(cfg: Path):
    for slug, body in KINDS.items():
        add_election(cfg, slug, body)
    loaded = config.load(cfg)
    by_slug = {e.slug: e for e in loaded.elections}
    president = by_slug["2014-prezident"]
    assert president.candidates == config.CandidateLists(
        "volbysr", {"round1": "results-oso2026", "round2": "results-osk2026"}
    )
    assert [r[0].isoformat() for r in president.rounds] == [
        "2014-03-15T07:00:00+01:00",
        "2014-04-05T07:00:00+02:00",
    ]
    assert president.units is None and president.incumbents is None
    referendum = by_slug["2009-referendum"]
    assert referendum.candidates is None
    assert referendum.questions == ("Súhlasíte …?",)
    # No results table: none published yet, in the kind's format.
    assert referendum.results == config.Results("volbysr", ())
    nrsr = by_slug["2010-nrsr"]
    assert (nrsr.seats, nrsr.threshold, nrsr.preferences) == (150, 5.0, 4)
    assert nrsr.coalition_thresholds == ((2, 7.0), (4, 10.0))
    assert nrsr.preference_quota == 3.0
    assert by_slug["2009-ep"].coalition_thresholds == ()
    assert by_slug["2012-03"].results == config.Results(
        "susr-by", ("results-oso202603",)
    )
    # A regular election of one half: before 2022, the regional on its own.
    regional = by_slug["2013"]
    assert (regional.halves, regional.label) == (("osk",), "regional")
    assert (by_slug["2026"].halves, by_slug["2026"].label) == (
        ("oso", "osk"),
        "municipal-regional",
    )
    assert (president.halves, president.label) == ((), "presidential")
    # The home is the newest election but a by-election, the latest the
    # newest regular one.
    assert loaded.elections[0].slug == "2026"
    assert loaded.latest.slug == "2026"
    edit(cfg / "elections.toml", "day = 2014-03-15", "day = 2027-03-20")
    edit(
        cfg / "elections.toml", "second_round = 2014-04-05", "second_round = 2027-04-03"
    )
    edit(cfg / "elections.toml", "\nday = 2012-03-17", "\nday = 2027-05-01")
    loaded = config.load(cfg)
    assert loaded.elections[0].slug == "2012-03"
    assert loaded.home.slug == "2014-prezident"
    assert loaded.latest.slug == "2026"


def test_upcoming_election_is_home(cfg: Path):
    """An election configured ahead of its day is the home at once, so the
    site opens on it; a by-election after it, held in a few places only,
    is not."""
    day = dt.date.today() + dt.timedelta(days=365)
    referendum = KINDS["2009-referendum"].replace("2009-01-24", day.isoformat())
    add_election(cfg, f"{day.year}-upcoming", referendum)
    later = (day + dt.timedelta(days=7)).isoformat()
    by_election = KINDS["2012-03"].replace("2012-03-17", later)
    add_election(cfg, f"{day.year}-upcoming-by", by_election)
    loaded = config.load(cfg)
    assert loaded.elections[0].slug == f"{day.year}-upcoming-by"
    assert loaded.home.slug == f"{day.year}-upcoming"
    # The jobs' default stays the newest regular election.
    assert loaded.latest.slug == "2026"


@pytest.mark.parametrize(
    ("slug", "old", "new", "error"),
    [
        # A format of another kind, or keys of another format.
        ("2014-prezident", 'format = "volbysr"', 'format = "mvsr"', r"format: must be one of volbysr, curated"),
        ("2014-prezident", "round1 =", "subjects =", r"candidates\.round1: missing"),
        ("2014-prezident", "second_round = 2014-04-05\n", "", r"round2: needs the election's second_round"),
        ("2014-prezident", "second_round = 2014-04-05", "second_round = 2014-03-01", "must be after"),
        ("2010-nrsr", "seats = 150\n", "", r"2010-nrsr\.seats: missing"),
        ("2010-nrsr", "threshold = 5\n", "threshold = 105\n", r"threshold: must be a share"),
        ("2010-nrsr", "[[2, 7.0], [4, 10.0]]", "[[4, 10.0], [2, 7.0]]", "ascending"),
        ("2010-nrsr", 'candidates = "results-osk2026"', 'lists = "results-osk2026"', r"candidates\.candidates: missing"),
        ("2009-ep", "seats = 15\n", 'seats = 15\nquestions = ["?"]\n', r"2009-ep\.questions: unknown key"),
        ("2009-referendum", 'questions = ["Súhlasíte …?"]', "questions = []", "must list the referendum's questions"),
        ("2009-referendum", 'questions = ["Súhlasíte …?"]', 'questions = ["?"]\ncandidates = { format = "curated" }', "has no candidates"),
        ("2012-03", 'format = "susr-by", package', 'format = "susr-by", oso', r"package: missing"),
        ("2012-03", '["results-oso202603"]', '["results-oso202603", "results-oso202509"]', r"must name the packages package"),
        ("2012-03", "kind = \"by-election\"\n", 'kind = "by-election"\nincumbents = { day = 2022-10-29, municipal = "results-oso2022", regional = "results-osk2022" }\n', r"incumbents: only a municipal-regional"),
        ("2013", 'osk = "results-osk2022"', 'okrsky = "results-osk2022"', r"susr needs the package oso, osk or both"),
        ("2013", 'osk = "results-osk2022"', 'osk = "results-osk2022", okrsky = "results-oso2022"', r"okrsky: needs oso"),
        ("2013", '["results-osk2022"]', '["results-oso2022"]', r"2013\.results: susr reads the packages the susr candidates name"),
    ],
)  # fmt: skip
def test_election_kinds_reject(cfg: Path, slug: str, old: str, new: str, error: str):
    for s, body in KINDS.items():
        add_election(cfg, s, body.replace(old, new, 1) if s == slug else body)
    with pytest.raises(config.ConfigError, match=error):
        config.load(cfg)


def test_regular_election_needs_units(cfg: Path):
    edit(
        cfg / "elections.toml",
        'units = { format = "xlsx", input = "units-oso2026" }\n',
        "",
    )
    with pytest.raises(config.ConfigError, match=r"election\.2026\.units: missing"):
        config.load(cfg)


def test_a_regular_election_is_required(cfg: Path):
    (cfg / "elections.toml").write_text("", encoding="utf-8")
    add_election(cfg, "2009-referendum", KINDS["2009-referendum"])
    with pytest.raises(config.ConfigError, match="at least one municipal-regional"):
        config.load(cfg)


def test_party_members(cfg: Path):
    path = cfg / "parties.toml"
    text = path.read_text(encoding="utf-8")
    coalition = """
[party."Spolu A B"]
short = "AB"
name = "Spolu A B"
members = ["Demokrati", "Kdh - kresťanskodemokratické hnutie"]
"""
    path.write_text(text + coalition, encoding="utf-8")
    loaded = config.load(cfg)
    assert loaded.parties["Spolu A B"].members == (
        "Demokrati",
        "Kdh - kresťanskodemokratické hnutie",
    )
    assert loaded.parties["Demokrati"].members == ()
    path.write_text(
        text + coalition.replace('"Demokrati", ', '"Nikto", '), encoding="utf-8"
    )
    with pytest.raises(
        config.ConfigError, match=r"members: 'Nikto' is not another party"
    ):
        config.load(cfg)
    path.write_text(text + coalition.replace('"Demokrati", ', ""), encoding="utf-8")
    with pytest.raises(config.ConfigError, match="must name two or more parties"):
        config.load(cfg)
