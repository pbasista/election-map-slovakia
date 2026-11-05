import json
import subprocess
from pathlib import Path

import pytest

from election_map_slovakia import cli, config, pages

REPO = Path(__file__).resolve().parent.parent


class FakeWrangler:
    """Wrangler logged in to *accounts*, or not logged in (None).

    Commands it runs, not reading their output, exit with *code*.
    """

    def __init__(self, accounts: list[dict] | None):
        self.accounts = accounts
        self.code = 0
        self.calls: list[tuple[list[str], dict | None]] = []

    def __call__(self, command, *, env=None, capture_output=False, **_):
        args = command[3:]
        self.calls.append((args, env))
        if not capture_output:
            return subprocess.CompletedProcess(command, self.code)
        if self.accounts is None:
            out, code = '{"loggedIn": false}', 1
        elif args[:2] == ["auth", "token"]:
            # The banner some versions print before the JSON.
            out, code = '⛅️ wrangler\n{"type": "oauth", "token": "oauth-token"}', 0
        else:
            out, code = json.dumps({"loggedIn": True, "accounts": self.accounts}), 0
        return subprocess.CompletedProcess(command, code, out, "")


@pytest.fixture
def wrangler(monkeypatch: pytest.MonkeyPatch):
    def install(accounts: list[dict] | None) -> FakeWrangler:
        fake = FakeWrangler(accounts)
        monkeypatch.setattr(subprocess, "run", fake)
        return fake

    monkeypatch.delenv(pages.TOKEN_ENV, raising=False)
    monkeypatch.delenv(pages.ACCOUNT_ENV, raising=False)
    pages.credentials.cache_clear()
    yield install
    pages.credentials.cache_clear()


def test_the_environment_comes_first(wrangler, monkeypatch: pytest.MonkeyPatch):
    fake = wrangler([{"name": "a", "id": "1"}])
    monkeypatch.setenv(pages.TOKEN_ENV, "env-token")
    monkeypatch.setenv(pages.ACCOUNT_ENV, "env-account")
    assert pages.credentials() == ("env-token", "env-account")
    assert fake.calls == []


def test_the_login_of_wrangler(wrangler, tmp_path: Path):
    fake = wrangler([{"name": "Site", "id": "abc"}])
    assert pages.credentials() == ("oauth-token", "abc")
    # Wrangler deploys to that account, without asking which.
    assert pages.deploy(tmp_path, "ems-results", "key") == 0
    args, env = fake.calls[-1]
    assert args[:2] == ["pages", "deploy"]
    assert env is not None and env[pages.ACCOUNT_ENV] == "abc"


def test_several_accounts_need_the_one_named(wrangler, monkeypatch: pytest.MonkeyPatch):
    wrangler([{"name": "Site", "id": "abc"}, {"name": "Other", "id": "def"}])
    with pytest.raises(pages.PagesError, match=r"2 accounts: Site \(abc\)"):
        pages.credentials()
    monkeypatch.setenv(pages.ACCOUNT_ENV, "def")
    pages.credentials.cache_clear()
    assert pages.credentials() == ("oauth-token", "def")


def test_no_credentials(wrangler):
    wrangler(None)
    with pytest.raises(pages.PagesError, match="npx wrangler login"):
        pages.credentials()


def fake_api(monkeypatch: pytest.MonkeyPatch, projects: list[dict]) -> list[str]:
    """Serve *projects* as the Pages API lists them, two to a page."""
    urls: list[str] = []

    def read(url, headers=None):
        urls.append(url)
        assert headers == {"Authorization": "Bearer env-token"}
        assert url.startswith(f"{pages.API}/accounts/env-account/pages/projects?")
        page = int(url.rsplit("page=", 1)[1])
        return {
            "success": True,
            "result": projects[2 * (page - 1) : 2 * page],
            "result_info": {"page": page, "total_pages": (len(projects) + 1) // 2},
        }

    monkeypatch.setattr(pages, "_read", read)
    return urls


def project(name: str, branch: str = "main", *domains: str) -> dict:
    """A project as the Pages API lists it."""
    return {"name": name, "production_branch": branch, "domains": list(domains)}


@pytest.fixture
def account(wrangler, monkeypatch: pytest.MonkeyPatch) -> FakeWrangler:
    """The account of the environment's credentials, the repository's site."""
    monkeypatch.setenv(pages.TOKEN_ENV, "env-token")
    monkeypatch.setenv(pages.ACCOUNT_ENV, "env-account")
    monkeypatch.chdir(REPO)
    return wrangler([])


def test_missing_projects_are_created_and_existing_left_alone(
    account: FakeWrangler,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    site = config.load().site
    existing = [
        project("unrelated"),
        project(site.pages_project, "main", "volebnamapa.sk"),
        project("ems-map-2026"),
        project("ems-data-2026"),
        project(site.sources_project, "main", "sources.volebnamapa.sk"),
        project(site.results_project, "production"),
    ]
    urls = fake_api(monkeypatch, existing)
    need = pages.needed(config.load())
    names = {p["name"] for p in existing}
    missing = [name for name in need if name not in names]
    assert "ems-map-2022" in missing and "ems-data-2024-prezident" in missing
    # One project for every base map, which needs no domain.
    assert site.base_project in missing and need[site.base_project] == ()
    # The live results of an election night have a project of their own,
    # served at their own domain.
    assert site.live_project in missing
    assert need[site.live_project] == ("live.volebnamapa.sk",)
    assert set(need) - set(missing) == names - {"unrelated"}

    # The listing reads every page of the API and changes nothing.
    assert cli.main(["data", "projects"]) == 0
    assert len(urls) == 3
    assert account.calls == []
    out = capsys.readouterr().out
    assert f"{len(missing)} missing; `ems data projects --create` for them" in out
    by_hand = out[out.index("by hand") :].splitlines()[1:]
    assert sorted(step.strip() for step in by_hand) == [
        f"{site.pages_project}: custom domain www.volebnamapa.sk",
        f"{site.live_project}: custom domain live.volebnamapa.sk",
        f"{site.results_project}: custom domain results.volebnamapa.sk",
        f"{site.results_project}: production branch production, not main",
    ]

    assert cli.main(["data", "projects", "--create"]) == 0
    assert [args for args, _ in account.calls] == [
        ["pages", "project", "create", name, "--production-branch=main"]
        for name in missing
    ]
    assert all(env[pages.ACCOUNT_ENV] == "env-account" for _, env in account.calls)


def test_a_failed_creation_stops(
    account: FakeWrangler,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    fake_api(monkeypatch, [])
    account.code = 7
    assert cli.main(["data", "projects", "--create"]) == 7
    assert len(account.calls) == 1
    assert "exit code 7" in capsys.readouterr().err


def test_prune_deletes_only_projects_of_elections_no_release_has(
    account: FakeWrangler,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    site = config.load().site
    fake_api(
        monkeypatch,
        [
            project(site.pages_project, "main", "volebnamapa.sk"),
            project(site.sources_project),
            project(site.base_project),
            project("ems-map-2026"),
            project("ems-map-2010-ep"),
            project("ems-data-2010-ep"),
            project("ems-data-2009"),
            project("ems-map-notes"),
            project("unrelated"),
        ],
    )
    # A repository whose release v0.1.0 had the 2010 EP election, gone since.
    shows = {
        "HEAD:config/elections.toml": "[election.2026]\n",
        "v0.1.0:config/elections.toml": "[election.2026]\n[election.2010-ep]\n",
    }

    def git(_root, *args):
        return "v0.1.0\n" if args[0] == "tag" else shows[args[1]]

    monkeypatch.setattr(pages, "_git", git)

    assert cli.main(["data", "projects"]) == 0
    out = capsys.readouterr().out
    assert "1 unneeded; `ems data projects --prune`" in out
    assert [line.split()[0] for line in out.splitlines() if "kept" in line] == [
        "ems-map-2010-ep",
        "ems-data-2010-ep",
    ]
    assert account.calls == []

    assert cli.main(["data", "projects", "--prune"]) == 0
    assert [args for args, _ in account.calls] == [
        ["pages", "project", "delete", "ems-data-2009", "--yes"]
    ]
